//! P3-T1 and P3-T2 (overview EX-4, T-4): honest certificates from the engine, and every attack of
//! the register (`spec/registers_p3.yaml`, AT-1 … AT-20) applied to each, written as JSON lines
//! for the independent verifier (`sever-verify --batch`) to judge. The attacker is a dishonest
//! operator who holds the operator's key (read here from `SECRETS`, test harness only), so every
//! attack but AT-4 is re-signed and reaches the rule under attack.

use std::io::Write;

use sever_crypto::{KeyPair, certificate_message, checkpoint_message};
use sever_db::Deleted;
use sever_format::Secrets;
use sever_types::Error;
use sever_vfs::{OpenMode, Vfs, read_all};

use crate::world::{Disks, World};

/// `(tag, value)` of each TLV, in order, and the trailer's signature.
type Tlvs = Vec<(u8, Vec<u8>)>;

fn split(cert: &[u8]) -> Option<(Tlvs, Vec<u8>)> {
    let mut out = Vec::new();
    let mut at = 0usize;
    while at < cert.len() {
        let tag = *cert.get(at)?;
        let n = u32::from_be_bytes(cert.get(at + 1..at + 5)?.try_into().ok()?) as usize;
        let v = cert.get(at + 5..at + 5 + n)?.to_vec();
        at += 5 + n;
        if tag == 0xFF {
            return Some((out, v));
        }
        out.push((tag, v));
    }
    None
}

fn encode(t: &Tlvs) -> Vec<u8> {
    let mut b = Vec::new();
    for (tag, v) in t {
        b.push(*tag);
        b.extend_from_slice(&(v.len() as u32).to_be_bytes());
        b.extend_from_slice(v);
    }
    b
}

fn with_trailer(body: &[u8], sig: &[u8]) -> Vec<u8> {
    let mut b = body.to_vec();
    b.push(0xFF);
    b.extend_from_slice(&(sig.len() as u32).to_be_bytes());
    b.extend_from_slice(sig);
    b
}

fn get(t: &Tlvs, tag: u8) -> Vec<u8> {
    t.iter()
        .find(|(k, _)| *k == tag)
        .map(|(_, v)| v.clone())
        .unwrap_or_default()
}

fn set(t: &Tlvs, tag: u8, v: Vec<u8>) -> Tlvs {
    t.iter()
        .map(|(k, x)| (*k, if *k == tag { v.clone() } else { x.clone() }))
        .collect()
}

/// `v` with byte `i` set to `b`.
fn put(mut v: Vec<u8>, i: usize, b: u8) -> Vec<u8> {
    if let Some(x) = v.get_mut(i) {
        *x = b;
    }
    v
}

fn flip(mut v: Vec<u8>, i: usize) -> Vec<u8> {
    if let Some(b) = v.get_mut(i) {
        *b ^= 1;
    }
    v
}

/// Offsets inside tag 6 (§11.2): version 1, leaf 209, leaf_index 8, then the checkpoint.
const CP: usize = 1 + 209 + 8;

/// The operator's epoch-0 secret, from `SECRETS` (DB-83 kind 2).
fn operator_key(disks: &Disks) -> Result<KeyPair, String> {
    let f = disks
        .keys
        .open(sever_p3::keys::SECRETS, OpenMode::Existing)
        .map_err(|e| format!("SECRETS: {e:?}"))?;
    let s = Secrets::parse(
        &read_all(f.as_ref()).map_err(|e| format!("{e:?}"))?,
        sever_format::SEALER_AES_GCM_SIV,
    )
    .map_err(|e| format!("SECRETS: {e}"))?;
    let (_, v) = s
        .entries
        .iter()
        .find(|(k, v)| *k == sever_p3::keys::K_OPERATOR_KEY && v.get(..4) == Some(&[0; 4]))
        .ok_or("no epoch-0 operator key")?;
    let secret: [u8; 32] = v.get(4..36).and_then(|s| s.try_into().ok()).ok_or("key")?;
    Ok(KeyPair::from_secret(&secret))
}

/// Every attack variant on `honest` (a group certificate when `group`); `other` is another
/// group certificate (for AT-2, AT-3, AT-13). Returns `(attack id, certificate)`.
fn variants(
    honest: &[u8],
    other: &[u8],
    group: bool,
    op: &KeyPair,
) -> Option<Vec<(&'static str, Vec<u8>)>> {
    let (t, sig) = split(honest)?;
    let (o, _) = split(other)?;
    let resign = |t: &Tlvs| {
        let body = encode(t);
        with_trailer(&body, &op.sign(&certificate_message(&body)))
    };
    let inc = get(&t, 6);
    let cos = get(&t, 7);
    let mut out: Vec<(&'static str, Vec<u8>)> = Vec::new();
    if group {
        let p = get(&t, 4);
        out.push(("AT-1", resign(&set(&t, 4, flip(p.clone(), 40)))));
        let mut zero = p.clone();
        if let Some(z) = zero.get_mut(32..64) {
            z.fill(0);
        }
        out.push(("AT-1", resign(&set(&t, 4, zero))));
        out.push(("AT-2", resign(&set(&t, 4, get(&o, 4)))));
        let mut big = p.clone();
        if let Some(z) = big.get_mut(32..64) {
            z.fill(0xFF); // ≥ ℓ: not a canonical scalar
        }
        out.push(("AT-11", resign(&set(&t, 4, big))));
        let pp = put(put(vec![0xFF; 32], 0, 0xED), 31, 0x7F); // p: not a canonical field element
        out.push(("AT-11", resign(&set(&t, 3, pp))));
        // AT-14 flips the flag: a deletion that emptied its group already carries 1.
        let emptied = get(&t, 11) == [1];
        out.push(("AT-14", resign(&set(&t, 11, vec![u8::from(!emptied)]))));
        // AT-4: each field changed, not re-signed (tags 1–13 and the trailer).
        for k in 1u8..=13 {
            let v = get(&t, k);
            out.push(("AT-4", with_trailer(&encode(&set(&t, k, flip(v, 0))), &sig)));
        }
        out.push(("AT-4", with_trailer(&encode(&t), &flip(sig.clone(), 0))));
    } else {
        out.push(("AT-13", resign(&set(&t, 2, get(&o, 2)))));
        out.push(("AT-13", resign(&set(&t, 11, vec![1]))));
        out.push((
            "AT-13",
            resign(&set(
                &set(&set(&t, 2, get(&o, 2)), 3, get(&o, 3)),
                4,
                get(&o, 4),
            )),
        ));
    }
    out.push(("AT-3", resign(&set(&t, 1, get(&o, 1)))));
    out.push(("AT-5", resign(&set(&t, 8, 7u32.to_be_bytes().to_vec()))));
    out.push(("AT-6", resign(&set(&t, 6, flip(inc.clone(), 1)))));
    let path_len = inc.get(CP + 116).copied().unwrap_or(0);
    if path_len > 0 {
        out.push(("AT-7", resign(&set(&t, 6, flip(inc.clone(), CP + 117)))));
    }
    let mut li = inc.clone();
    if let Some(b) = li.get_mut(1 + 209 + 7) {
        *b ^= 1; // leaf_index ± 1
    }
    out.push(("AT-7", resign(&set(&t, 6, li))));
    // A checkpoint signed by another key, re-signed by the operator with another timestamp, or
    // under an epoch the anchors lack.
    let cp = inc.get(CP..CP + 116)?.to_vec();
    let size = u64::from_be_bytes(cp.get(..8)?.try_into().ok()?);
    let root: [u8; 32] = cp.get(8..40)?.try_into().ok()?;
    let ts = u64::from_be_bytes(cp.get(40..48)?.try_into().ok()?);
    let with_cp = |ts: u64, epoch: u32, signer: &KeyPair| {
        let mut i = inc.clone();
        let mut c = size.to_be_bytes().to_vec();
        c.extend_from_slice(&root);
        c.extend_from_slice(&ts.to_be_bytes());
        c.extend_from_slice(&epoch.to_be_bytes());
        c.extend_from_slice(&signer.sign(&checkpoint_message(size, &root, ts, epoch)));
        if let Some(dst) = i.get_mut(CP..CP + 116) {
            dst.copy_from_slice(&c);
        }
        i
    };
    out.push((
        "AT-8",
        resign(&set(&t, 6, with_cp(ts, 0, &KeyPair::generate()))),
    ));
    out.push(("AT-10", resign(&set(&t, 6, with_cp(ts + 1, 0, op)))));
    out.push(("AT-20", resign(&set(&t, 6, with_cp(ts, 9, op)))));
    let entry = |i: usize| cos.get(1 + 69 * i..70 + 69 * i).map(<[u8]>::to_vec);
    let n = usize::from(*cos.first()?);
    let keep = |idx: &[usize], edit: &dyn Fn(usize, Vec<u8>) -> Vec<u8>| -> Option<Vec<u8>> {
        let mut v = vec![u8::try_from(idx.len()).ok()?];
        for (j, &i) in idx.iter().enumerate() {
            v.extend(edit(j, entry(i)?));
        }
        Some(v)
    };
    let same = |_: usize, e: Vec<u8>| e;
    if n >= 4 {
        out.push(("AT-9", resign(&set(&t, 7, keep(&[0, 1, 2], &same)?))));
        out.push(("AT-17", resign(&set(&t, 7, keep(&[0, 1, 2, 2], &same)?))));
        let bad_index = |j: usize, e: Vec<u8>| if j == 3 { put(e, 0, 7) } else { e };
        out.push((
            "AT-20",
            resign(&set(&t, 7, keep(&[0, 1, 2, 3], &bad_index)?)),
        ));
        let bad_epoch = |j: usize, e: Vec<u8>| if j == 3 { put(e, 4, 3) } else { e }; // epoch 0 → 3
        out.push((
            "AT-20",
            resign(&set(&t, 7, keep(&[0, 1, 2, 3], &bad_epoch)?)),
        ));
    }
    out.push(("AT-12", resign(&set(&t, 1, vec![0; 32]))));
    let leaf_index = u64::from_be_bytes(inc.get(210..218)?.try_into().ok()?);
    out.push((
        "AT-15",
        resign(&set(&t, 10, leaf_index.to_be_bytes().to_vec())),
    ));
    // AT-16: missing, repeated, reordered tag; trailing bytes; no trailer.
    let body = encode(&t);
    let mut missing = t.clone();
    missing.remove(4);
    out.push(("AT-16", resign(&missing)));
    let mut repeated = t.clone();
    repeated.insert(5, t.get(4)?.clone());
    out.push(("AT-16", resign(&repeated)));
    let mut swapped = t.clone();
    swapped.swap(3, 4);
    out.push(("AT-16", resign(&swapped)));
    let mut trailing = resign(&t);
    trailing.push(0);
    out.push(("AT-16", trailing));
    out.push(("AT-16", body));
    // AT-18: wrong fixed lengths; tags 11 and 12 outside {0, 1}; a short trailer.
    out.push(("AT-18", resign(&set(&t, 9, get(&t, 9).get(..63)?.to_vec()))));
    out.push(("AT-18", resign(&set(&t, 11, vec![2]))));
    out.push(("AT-18", resign(&set(&t, 12, vec![2]))));
    out.push((
        "AT-18",
        resign(&set(&t, 10, get(&t, 10).get(1..)?.to_vec())),
    ));
    let mut c1 = get(&t, 1);
    c1.push(0);
    out.push(("AT-18", resign(&set(&t, 1, c1))));
    let short = encode(&t);
    let s = op.sign(&certificate_message(&short));
    out.push(("AT-18", with_trailer(&short, s.get(..63)?)));
    // AT-19: a leaf of another type; an inclusion of another version.
    let lt = put(inc.clone(), 1, 0x02);
    out.push(("AT-19", resign(&set(&t, 6, lt))));
    let ver = put(inc, 0, 2);
    out.push(("AT-19", resign(&set(&t, 6, ver))));
    Some(out)
}

/// Writes `n` honest certificates (deletions from groups and from the holding area) and every
/// attack on each, as JSON lines `{"kind": "honest"|"AT-…", "of": i, "cert": hex}`, after a first
/// line with the anchors.
pub fn write(
    world: &World,
    rows: &dyn sever_crashkit::rows::Rows,
    artefact: &[u8],
    spawn_target: usize,
    n: usize,
    out: &mut dyn Write,
) -> Result<(u64, u64), String> {
    let disks = Disks::new();
    let db = world.open(&disks).map_err(|e| format!("open: {e}"))?;
    let cid = db
        .create_collection(
            artefact,
            sever_engine::CollectionOptions {
                spawn_target,
                spawning_enabled: true,
                store_passages: false,
            },
        )
        .map_err(|e| format!("create_collection: {e}"))?;
    let op = operator_key(&disks)?;
    // Insert 3n records (and more, until n / 10 + 1 have landed in the holding area; those first
    // n / 10 + 1 are deleted at once, so holding-area certificates and AT-13 are covered, and the
    // rest of the n certificates come from groups), then delete cohorts of up to four (delete_user).
    let total = 3 * n;
    let (mut ids, mut held) = (Vec::new(), Vec::new());
    let mut certs: Vec<(Vec<u8>, bool)> = Vec::new();
    let take = |outs: Vec<Deleted>, certs: &mut Vec<(Vec<u8>, bool)>| {
        for o in outs {
            if let Deleted::Deleted { certificate, .. } = o {
                let group = split(&certificate).is_some_and(|(t, _)| get(&t, 12) == [0]);
                certs.push((certificate, group));
            }
        }
    };
    let mut i = 0usize;
    while ids.len() < total || held.len() < n / 10 + 1 {
        let Ok(v) = rows.row(i) else { break };
        let id = format!("rec-{i:07}");
        i += 1;
        let cred = world.credential(cid, &v).map_err(|e| e.to_string())?;
        match db.insert(
            cid,
            sever_engine::InsertRequest {
                record_id: id.clone(),
                vector: v,
                credential: cred.credential(),
                passage: None,
            },
        ) {
            // Deleted at once, while it still sits in the holding area (later inserts would
            // flush it into a spawned group): a holding-area certificate, for AT-13.
            Ok((_, sever_index::Placement::Holding)) if held.len() < n / 10 + 1 => {
                take(
                    vec![db.delete(cid, &id).map_err(|e| format!("delete: {e}"))?],
                    &mut certs,
                );
                held.push(id);
            }
            Ok(_) => ids.push(id),
            Err(Error::NotNormalised | Error::NonFinite | Error::GroupCapacityExceeded) => {}
            Err(e) => return Err(format!("insert {i}: {e}")),
        }
    }
    for chunk in ids.chunks(4).step_by(3) {
        if certs.len() >= n {
            break;
        }
        let refs: Vec<&str> = chunk.iter().map(String::as_str).collect();
        take(
            db.delete_user(cid, &refs)
                .map_err(|e| format!("delete_user: {e}"))?,
            &mut certs,
        );
    }
    certs.truncate(n);
    writeln!(out, "{}", db.anchors().to_json()).map_err(|e| e.to_string())?;
    let hex = |b: &[u8]| b.iter().map(|x| format!("{x:02x}")).collect::<String>();
    let first_group = certs
        .iter()
        .find(|c| c.1)
        .map(|c| c.0.clone())
        .ok_or("no group cert")?;
    let mut attacked = 0u64;
    for (i, (c, group)) in certs.iter().enumerate() {
        writeln!(
            out,
            "{}",
            serde_json::json!({"kind": "honest", "of": i, "cert": hex(c)})
        )
        .map_err(|e| e.to_string())?;
        // Another group certificate for the substitutions.
        let other = certs
            .iter()
            .skip(i + 1)
            .chain(certs.iter())
            .find(|x| x.1 && x.0 != *c)
            .map_or(first_group.clone(), |x| x.0.clone());
        for (id, v) in variants(c, &other, *group, &op).ok_or("attack")? {
            writeln!(
                out,
                "{}",
                serde_json::json!({"kind": id, "of": i, "cert": hex(&v)})
            )
            .map_err(|e| e.to_string())?;
            attacked += 1;
        }
    }
    Ok((certs.len() as u64, attacked))
}
