//! Database creation and recovery (spec §15.7), with the full invariant check (§21: INV-2 to
//! INV-9 in Part 2's scope).
//!
//! **Creation** writes `SECRETS`, the WAL, the payload store and an empty storage checkpoint, and
//! installs `MANIFEST` last: until `MANIFEST` exists there is no database, and a half-created one
//! (which holds no data) is cleared at the next open.
//!
//! **Recovery** (every startup): read `MANIFEST`; load the storage checkpoint; replay every WAL
//! transaction with a valid `COMMIT` (participant records go to their participants), discard the
//! rest; let participants recover; rebuild every index from the image; run the full invariant
//! check, and refuse to serve on any violation.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::sync::atomic::{AtomicBool, AtomicU64};
use std::sync::{Arc, Mutex, RwLock};

use sever_appendstore::{AppendStore, FileStore};
use sever_checkpoint as checkpoint;
use sever_format::image::CheckpointMeta;
use sever_format::{CollectionImage, CollectionMeta, CoreRecord, DbImage, KindByte, Manifest};
use sever_index::{Counters, IdScrambler};
use sever_partition::PartitionArtefact;
use sever_txn::{Participants, Sealer, StoredExtension, decode_collection, rebuild_changeset};
use sever_types::constants::MAX_GROUP_MEMBERS;
use sever_types::{CollectionId, Error, GroupId, ScrambledId};
use sever_vfs::{Vfs, VfsError};
use sever_wal::{Wal, WalConfig};

use crate::config::EngineConfig;
use crate::engine::{Engine, State, Writer, read_secrets, store_cfg, write_secrets};

fn inv(check: &'static str) -> Error {
    Error::IntegrityViolation { invariant: check }
}

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

/// Names a half-created database may have left (no `MANIFEST` yet, so no data).
const CREATION_LEFTOVERS: [&str; 5] = [
    "wal",
    "payloads",
    "checkpoint",
    "MANIFEST.tmp",
    "ENGINE.lock",
];

fn remove_tree(vfs: &dyn Vfs, path: &str) -> Result<(), Error> {
    match vfs.unlink(path) {
        Ok(()) => return Ok(()),
        Err(VfsError::IsADirectory) => {}
        Err(e) => return Err(io(e)),
    }
    for name in vfs.list(path).map_err(io)? {
        remove_tree(vfs, &format!("{path}/{name}"))?;
    }
    vfs.remove_dir(path).map_err(io)
}

/// Creates a new database in an empty data directory; returns its `MANIFEST`.
pub(crate) fn create(
    vfs_arc: &Arc<dyn Vfs>,
    keys: &dyn Vfs,
    cfg: &EngineConfig,
    sealer_id: u16,
) -> Result<Manifest, Error> {
    let vfs = vfs_arc.as_ref();
    let entries = vfs.list("").map_err(|_| inv("§14.1 data directory"))?;
    if entries
        .iter()
        .any(|e| !CREATION_LEFTOVERS.contains(&e.as_str()))
    {
        return Err(inv(
            "§14.1 data directory holds files that are not a database",
        ));
    }
    for e in entries.iter().filter(|e| e.as_str() != "ENGINE.lock") {
        remove_tree(vfs, e)?;
    }
    sever_vfs::durable::sync_dir(vfs, "").map_err(io)?;
    write_secrets(keys, sealer_id)?;
    Wal::create(
        Arc::clone(vfs_arc),
        WalConfig {
            sealer_id,
            segment_bytes: cfg.wal_segment_bytes,
        },
        1,
        1,
    )?;
    FileStore::create(Arc::clone(vfs_arc), store_cfg(cfg, sealer_id))?;
    checkpoint::create_root(vfs)?;
    let meta = CheckpointMeta {
        checkpoint_id: 1,
        next_wal_seq: 1,
        next_txn_id: 1,
        config_hash: cfg.config_hash,
    };
    checkpoint::write(vfs, sealer_id, &DbImage::default(), &meta, &|_| {
        sever_format::Layout::plain(8)
    })?;
    checkpoint::read_manifest(vfs, sealer_id)?.ok_or(inv("§14.1 MANIFEST"))
}

/// Opens and recovers an existing database (§15.7).
pub(crate) fn open_existing<E: StoredExtension, S: Sealer>(
    vfs: Arc<dyn Vfs>,
    keys: Arc<dyn Vfs>,
    sealer: S,
    ext: E,
    mut participants: Participants<E>,
    cfg: EngineConfig,
    manifest: Manifest,
) -> Result<Engine<E, S>, Error> {
    let sid = sealer.sealer_id();
    let k_scramble = read_secrets(keys.as_ref(), sid)?;
    let layout_of_meta = |m: &CollectionMeta| sever_txn::layout_for::<E>(usize::from(m.d), &sealer);
    // §15.7 step 3: the storage checkpoint, then every committed WAL transaction.
    let (meta, mut image) = checkpoint::load(vfs.as_ref(), &manifest, &layout_of_meta)?;
    let (wal, txns, _report) = Wal::recover(
        Arc::clone(&vfs),
        WalConfig {
            sealer_id: sid,
            segment_bytes: cfg.wal_segment_bytes,
        },
        manifest.first_wal_seq,
        meta.next_txn_id,
    )?;
    for rec in txns.iter().flat_map(|t| &t.records) {
        if rec.ty.is_participant() {
            let owner = participants.iter_mut().find(|p| p.owns(rec));
            match owner {
                Some(p) => p.replay(rec)?,
                None => return Err(inv("§15.7 participant record without participant")),
            }
            continue;
        }
        let layout_of = |c: &CollectionId| image.collection(c).map(|c| layout_of_meta(&c.meta));
        let core = CoreRecord::parse(rec.ty, &rec.payload, &layout_of)?;
        image.apply(&core)?;
    }
    for p in participants.iter_mut() {
        p.recover()?;
    }
    let store = FileStore::open(Arc::clone(&vfs), store_cfg(&cfg, sid))?;
    checkpoint::remove_others(vfs.as_ref(), manifest.checkpoint_id)?;

    // §15.7 step 5–6: rebuild every index and check every invariant before serving.
    let mut live = BTreeMap::new();
    for (cid, coll) in &image.collections {
        let art = PartitionArtefact::parse(&coll.artefact)?;
        let ix = rebuild_collection(&ext, &sealer, &k_scramble, coll, &art)?;
        check_payload_refs(coll, &store)?;
        live.insert(*cid, ix);
    }
    for p in &participants {
        p.check_invariants()?;
    }
    let checkpoint_id = manifest.checkpoint_id;
    let wal_bytes = wal.appended();
    Ok(Engine {
        vfs,
        sealer,
        ext,
        cfg,
        k_scramble,
        state: RwLock::new(State { image, live }),
        writer: Mutex::new(Writer {
            wal,
            store,
            participants,
            store_key: 0,
            checkpoint_id,
            #[cfg(feature = "test-hooks")]
            hook: None,
        }),
        poisoned: AtomicBool::new(false),
        wal_bytes: AtomicU64::new(wal_bytes),
        checkpoint_id: AtomicU64::new(checkpoint_id),
    })
}

/// Rebuilds one collection's index from its image and checks every invariant (§15.7 step 6,
/// §21 INV-2 … INV-8).
pub(crate) fn rebuild_collection<E: StoredExtension, S: Sealer>(
    ext: &E,
    sealer: &S,
    k_scramble: &[u8; 64],
    coll: &CollectionImage,
    art: &PartitionArtefact,
) -> Result<crate::engine::Ix<E>, Error> {
    let meta = &coll.meta;
    let cid = meta.cid;
    let scrambler = sever_index::HmacSha512Scrambler::new(k_scramble);
    if art.sha256_artefact != meta.artefact_sha256 || art.d != usize::from(meta.d) {
        return Err(inv("§6.3 artefact does not match the collection"));
    }
    let d = art.d;
    let layout = sever_txn::layout_for::<E>(d, sealer);
    // Group structure: frozen groups in label order with the artefact's centroids, then the
    // holding area, then spawned groups.
    let k_frozen = art.k_frozen;
    for (i, g) in coll.groups.iter().enumerate() {
        let id = g.header.group_id;
        let want_kind = match i {
            i if i < k_frozen => KindByte::Frozen,
            i if i == k_frozen => KindByte::Holding,
            _ => KindByte::Spawned,
        };
        if g.header.kind() != want_kind {
            return Err(inv("§5.1 group order"));
        }
        if want_kind == KindByte::Frozen {
            let label = u16::try_from(i).ok().and_then(GroupId::frozen);
            let mu = art.centroid(i).ok_or(inv("§5.1 frozen centroid"))?;
            let same = mu
                .iter()
                .zip(&g.header.centroid)
                .all(|(a, b)| a.to_bits() == b.to_bits());
            if label != Some(id) || !same {
                return Err(inv("§5.1 frozen group"));
            }
        }
        if g.header.n != g.slots.len() as u64 {
            return Err(inv("INV-6 n equals the slot count"));
        }
        if g.header.n > MAX_GROUP_MEMBERS {
            return Err(inv("INV-4 group cap"));
        }
    }
    if coll.groups.len() <= k_frozen {
        return Err(inv("§5.1 holding area missing"));
    }
    let groups = decode_collection::<E>(coll, &layout, sealer)?;
    // INV-6 (S = Σ x̃), the extension's own invariants, §9.7 scrambled IDs, one live record per
    // ID, and INV-7 (locator ↔ slots, exactly).
    let mut seen_ids = HashSet::new();
    let mut derived: BTreeMap<ScrambledId, (GroupId, u64)> = BTreeMap::new();
    let (mut big_n, mut k) = (0u64, 0u64);
    for g in &groups {
        if let Some(state) = &g.state {
            let mut s = vec![0i64; d];
            for slot in &g.slots {
                for (acc, &v) in s.iter_mut().zip(slot.x.as_slice()) {
                    *acc = acc
                        .checked_add(i64::from(v))
                        .ok_or(inv("INV-6 sum overflow"))?;
                }
            }
            if s != state.s || state.n != g.slots.len() as u64 {
                return Err(inv("INV-6 S equals the sum of members"));
            }
            ext.check_group(&state.s, &state.ext_public, &state.ext_secret)?;
            big_n += state.n;
            k += 1;
        }
        for (i, slot) in g.slots.iter().enumerate() {
            if scrambler.scramble(&cid, &slot.record_id) != slot.scrambled_id {
                return Err(inv("§9.7 scrambled ID"));
            }
            if !seen_ids.insert(slot.record_id.clone()) {
                return Err(inv("§3.2 one live record per ID"));
            }
            derived.insert(slot.scrambled_id, (g.id, i as u64));
        }
    }
    if derived != coll.locator {
        return Err(inv("INV-7 locator matches slots"));
    }
    // INV-8: N and k.
    if big_n != coll.big_n || k != coll.k {
        return Err(inv("INV-8 N and k"));
    }
    let mut ix = sever_index::Index::new(
        art,
        sever_index::IndexConfig {
            spawning_enabled: meta.spawning_enabled,
            spawn_target: meta.spawn_target as usize,
        },
        ext.clone(),
        sever_index::HmacSha512Scrambler::new(k_scramble),
        cid,
    )?;
    ix.apply(rebuild_changeset(d, groups, Counters { big_n, k }));
    // Part 1's own checks on the rebuilt index (INV-5 … INV-8 from its side).
    ix.check_invariants()?;
    if ix.k() != k {
        return Err(inv("INV-8 k"));
    }
    Ok(ix)
}

/// Every passage reference names a live record and a readable, CRC-valid store record.
fn check_payload_refs(coll: &CollectionImage, store: &FileStore) -> Result<(), Error> {
    let live: BTreeSet<&ScrambledId> = coll.locator.keys().collect();
    for (sid, at) in &coll.payload_refs {
        if !live.contains(sid) {
            return Err(inv("§14.8 passage of a record that is not live"));
        }
        store.read(at)?;
    }
    Ok(())
}
