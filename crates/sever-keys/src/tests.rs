//! Tests of the keys, the key file and the recovery rule. Expected bytes are written out by hand
//! from the §14.7 layout (oracle A) with the CRC from an independent bitwise CRC-32C below (oracle
//! B); the recovery table is §13.4's rule written row by row (oracle A).

use std::collections::BTreeMap;
use std::sync::Arc;

use sever_spec::spec;
use sever_types::Error;
use sever_vfs::{CrashPolicy, OpenMode, SimVfs, Vfs};

use crate::file::*;
use crate::recovery::plan;
use crate::*;

/// CRC-32C (Castagnoli, reflected polynomial 0x82F63B78), one bit at a time: an implementation
/// independent of the `crc32c` crate the code uses.
fn crc32c_bitwise(data: &[u8]) -> u32 {
    let mut crc = !0u32;
    for &byte in data {
        crc ^= u32::from(byte);
        for _ in 0..8 {
            crc = if crc & 1 == 1 {
                (crc >> 1) ^ 0x82F6_3B78
            } else {
                crc >> 1
            };
        }
    }
    !crc
}

#[test]
// oracle: B the CRC-32C check value of RFC 3720 §B.4 ("123456789" → 0xE3069283)
fn p4_keys_the_test_crc_is_crc32c() {
    assert_eq!(crc32c_bitwise(b"123456789"), 0xE306_9283);
}

fn domain(c: u8, g: u8) -> Domain {
    let mut group_id = [0u8; 32];
    group_id[1] = g;
    Domain {
        collection_id: [c; 16],
        group_id,
    }
}

fn record(index: u64, version: u64, d: Domain, key: u8) -> SlotRecord {
    SlotRecord {
        domain_index: index,
        key_version: version,
        domain: d,
        key: Key::from_bytes(&[key; 32]),
    }
}

fn slot_bytes(index: u64, version: u64, d: Domain, key: u8) -> Vec<u8> {
    encode_slot(&record(index, version, d, key))
        .as_bytes()
        .to_vec()
}

fn vfs() -> (SimVfs, Arc<dyn Vfs>) {
    let sim = SimVfs::new();
    let v: Arc<dyn Vfs> = Arc::new(sim.clone());
    (sim, v)
}

fn read_all(v: &dyn Vfs, path: &str) -> Vec<u8> {
    let f = v.open(path, OpenMode::Existing).unwrap();
    sever_vfs::read_all(f.as_ref()).unwrap()
}

// --- §14.7 bytes --------------------------------------------------------------------------------

#[test]
// oracle: A §14.7 header written out by hand; B the bitwise CRC-32C
#[spec("SR-14.7-1")]
fn p4_keys_header_is_the_exact_bytes_of_section_14_7() {
    let mut want = vec![0u8; 4_096];
    want[..8].copy_from_slice(b"SVDBKEYS");
    want[8..10].copy_from_slice(&[0x00, 0x01]); // u16be version 1 (§14.9)
    let crc = crc32c_bitwise(&want[..4_092]);
    want[4_092..].copy_from_slice(&crc.to_be_bytes());
    assert_eq!(encode_header().to_vec(), want);
    assert!(check_header(&want).is_ok());
}

#[test]
// oracle: A §14.7 slot written out by hand (DB-90); B the bitwise CRC-32C
#[spec("SR-14.7-2")]
fn p4_keys_slot_is_the_exact_bytes_of_section_14_7() {
    let mut collection_id = [0u8; 16];
    for (i, b) in collection_id.iter_mut().enumerate() {
        *b = 0xA0 + i as u8;
    }
    let mut group_id = [0u8; 32];
    group_id[0] = 0x00;
    group_id[1] = 0x05; // a §5.1 label, zero-padded to 32 bytes (§14.3)
    let d = Domain {
        collection_id,
        group_id,
    };
    let mut want = vec![0u8; 512];
    want[0..4].copy_from_slice(&[0x53, 0x56, 0x4B, 0x53]); // b"SVKS"
    want[4..12].copy_from_slice(&[0, 0, 0, 0, 0, 0, 0, 3]); // u64be domain_index 3
    want[12..20].copy_from_slice(&[0, 0, 0, 0, 0, 0, 0, 7]); // u64be key_version 7
    want[20..52].copy_from_slice(&[0x11; 32]); // key
    want[52..68].copy_from_slice(&collection_id);
    want[68..100].copy_from_slice(&group_id);
    let crc = crc32c_bitwise(&want[..508]);
    want[508..].copy_from_slice(&crc.to_be_bytes());
    assert_eq!(slot_bytes(3, 7, d, 0x11), want);
    match decode_slot(&want, 3) {
        SlotState::Valid(r) => {
            assert_eq!((r.domain_index, r.key_version, r.domain), (3, 7, d));
            assert_eq!(r.key.as_bytes(), &[0x11; 32]);
        }
        other => panic!("{other:?}"),
    }
}

#[test]
// oracle: A §14.7 "an erased slot is 512 zero bytes" (DB-90)
#[spec("SR-14.7-2")]
fn p4_keys_an_erased_slot_is_512_zero_bytes() {
    assert!(matches!(decode_slot(&[0u8; 512], 0), SlotState::Erased));
    let (_, v) = vfs();
    let (mut f, _) = KeyFile::open(v.clone(), "KEYS").unwrap();
    f.append(domain(1, 1), 1, &Key::from_bytes(&[9; 32]))
        .unwrap();
    f.erase_slot(0, 0).unwrap();
    let bytes = read_all(v.as_ref(), "KEYS");
    assert_eq!(&bytes[4_096..5_120], &[0u8; 1_024][..]);
}

#[test]
// oracle: A §14.7 "a torn slot fails its CRC and is treated as absent"
#[spec("SR-14.7-3")]
fn p4_keys_a_torn_slot_is_treated_as_absent() {
    let good = slot_bytes(2, 4, domain(1, 2), 0x33);
    let torn = |f: &dyn Fn(&mut Vec<u8>)| {
        let mut s = good.clone();
        f(&mut s);
        matches!(decode_slot(&s, 2), SlotState::Torn)
    };
    let recrc = |s: &mut Vec<u8>| {
        let crc = crc32c_bitwise(&s[..508]);
        s[508..].copy_from_slice(&crc.to_be_bytes());
    };
    assert!(matches!(decode_slot(&good, 2), SlotState::Valid(_)));
    assert!(torn(&|s| s[25] ^= 1), "a key byte flipped");
    assert!(torn(&|s| s[510] ^= 1), "a CRC byte flipped");
    assert!(torn(&|s| s.truncate(300)), "half a slot");
    assert!(
        torn(&|s| s[200..].fill(0)),
        "a write torn at a 512-byte boundary's half"
    );
    assert!(
        torn(&|s| {
            s[0] = b'X';
            recrc(s);
        }),
        "another magic with a valid CRC"
    );
    assert!(
        torn(&|s| {
            s[300] = 1;
            recrc(s);
        }),
        "non-zero padding with a valid CRC"
    );
    assert!(
        matches!(decode_slot(&good, 5), SlotState::Torn),
        "a domain_index that is not the pair's position"
    );
}

// --- the file -----------------------------------------------------------------------------------

#[test]
// oracle: A §14.7 "4 KB plus 1 KB per domain"; Appendix A
#[spec("SR-14.7-5")]
fn p4_keys_the_file_is_4096_bytes_plus_1024_per_domain() {
    let (_, v) = vfs();
    let (mut f, slots) = KeyFile::open(v.clone(), "KEYS").unwrap();
    assert!(slots.is_empty());
    assert_eq!(read_all(v.as_ref(), "KEYS").len(), 4_096);
    for n in 1..=5u8 {
        f.append(domain(1, n), 1, &Key::generate()).unwrap();
        assert_eq!(
            read_all(v.as_ref(), "KEYS").len(),
            4_096 + 1_024 * usize::from(n)
        );
    }
    assert_eq!(file_size(5), 9_216);
}

#[test]
// oracle: A §14.7 "pair i starts at byte 4,096 + 1,024·i … appended in creation order, never reused"
#[spec("SR-14.7-4")]
fn p4_keys_a_domain_index_is_its_pair_position_in_creation_order() {
    let (_, v) = vfs();
    let (mut f, _) = KeyFile::open(v.clone(), "KEYS").unwrap();
    let got: Vec<u64> = (0..4u8)
        .map(|g| f.append(domain(1, g), 1, &Key::generate()).unwrap())
        .collect();
    assert_eq!(got, [0, 1, 2, 3]);
    f.write_slot(2, 1, domain(1, 2), 2, &Key::from_bytes(&[0x44; 32]))
        .unwrap();
    // Erasing a domain's slots does not free its index: the next domain still appends.
    f.erase_slot(1, 0).unwrap();
    assert_eq!(f.append(domain(1, 9), 1, &Key::generate()).unwrap(), 4);
    let bytes = read_all(v.as_ref(), "KEYS");
    let at = 4_096 + 1_024 * 2 + 512;
    assert_eq!(&bytes[at..at + 4], b"SVKS");
    assert_eq!(&bytes[at + 4..at + 12], &[0, 0, 0, 0, 0, 0, 0, 2]);
    assert_eq!(&bytes[at + 20..at + 52], &[0x44; 32]);
}

#[test]
// oracle: A §14.7 "a trailing partial pair (a crash while the file grew) is truncated at recovery"
#[spec("SR-14.7-6")]
fn p4_keys_a_trailing_partial_pair_is_truncated_at_open() {
    let (_, v) = vfs();
    let (mut f, _) = KeyFile::open(v.clone(), "KEYS").unwrap();
    f.append(domain(1, 1), 1, &Key::generate()).unwrap();
    f.append(domain(1, 2), 1, &Key::generate()).unwrap();
    drop(f);
    let mut raw = v.open("KEYS", OpenMode::Existing).unwrap();
    raw.write_at(4_096 + 2_048, &[0x5A; 700]).unwrap();
    raw.fsync().unwrap();
    drop(raw);
    let (f, slots) = KeyFile::open(v.clone(), "KEYS").unwrap();
    assert_eq!((f.pairs(), slots.len()), (2, 2));
    assert_eq!(read_all(v.as_ref(), "KEYS").len(), 4_096 + 2_048);
}

#[test]
// oracle: A §14.7 "written once, when the file is created, and never rewritten"
#[spec("SR-14.7-1")]
fn p4_keys_the_header_is_written_once_and_checked_at_open() {
    let (sim, v) = vfs();
    let (mut f, _) = KeyFile::open(v.clone(), "KEYS").unwrap();
    f.append(domain(1, 1), 1, &Key::generate()).unwrap();
    drop(f);
    sim.set_faults(sever_vfs::FaultPlan::default());
    let (mut f, _) = KeyFile::open(v.clone(), "KEYS").unwrap();
    assert_eq!(
        sim.ops_since_plan(),
        0,
        "opening an intact file writes nothing"
    );
    f.write_slot(0, 1, domain(1, 1), 2, &Key::generate())
        .unwrap();
    f.erase_slot(0, 0).unwrap();
    assert_eq!(&read_all(v.as_ref(), "KEYS")[..4_096], &encode_header()[..]);
    drop(f);
    let mut raw = v.open("KEYS", OpenMode::Existing).unwrap();
    raw.write_at(9, &[2]).unwrap(); // version 2
    drop(raw);
    assert!(matches!(
        KeyFile::open(v, "KEYS"),
        Err(Error::IntegrityViolation { .. })
    ));
}

#[test]
// oracle: A §13.4 phase A "writes the new key … and fsyncs it", phase C "overwrites … and fsyncs it"
#[spec("SR-13.4-2")]
fn p4_keys_writes_and_erasures_are_durable_when_they_return() {
    let (sim, v) = vfs();
    let (mut f, _) = KeyFile::open(v.clone(), "KEYS").unwrap();
    f.append(domain(1, 1), 1, &Key::from_bytes(&[0x21; 32]))
        .unwrap();
    f.write_slot(0, 1, domain(1, 1), 2, &Key::from_bytes(&[0x22; 32]))
        .unwrap();
    drop(f);
    sim.restart(CrashPolicy::DropAll);
    let (mut f, slots) = KeyFile::open(v.clone(), "KEYS").unwrap();
    let versions: Vec<Option<u64>> = slots[0]
        .iter()
        .map(|s| match s {
            SlotState::Valid(r) => Some(r.key_version),
            _ => None,
        })
        .collect();
    assert_eq!(
        versions,
        [Some(1), Some(2)],
        "the file, the append and the write survive"
    );
    f.erase_slot(0, 0).unwrap();
    drop(f);
    sim.restart(CrashPolicy::DropAll);
    let (_, slots) = KeyFile::open(v, "KEYS").unwrap();
    assert!(
        matches!(slots[0][0], SlotState::Erased),
        "the erasure survives"
    );
}

// --- §13.4 the recovery rule --------------------------------------------------------------------

/// One slot's state in the recovery table: the active version `a`, a stale one `s`, the next one
/// `n` (an orphan of phase A), torn `t`, erased `-`.
fn slot_of(c: char, d: Domain, index: u64) -> SlotState {
    match c {
        'a' => SlotState::Valid(record(index, 5, d, 0xAA)),
        's' => SlotState::Valid(record(index, 4, d, 0x55)),
        'n' => SlotState::Valid(record(index, 6, d, 0x66)),
        't' => SlotState::Torn,
        _ => SlotState::Erased,
    }
}

#[test]
// oracle: A §13.4 recovery rule, every combination of two slot states written out row by row
#[spec("SR-13.4-3", "SR-21-14")]
fn p4_keys_recovery_rule_for_every_combination_of_slot_states() {
    // (slot 0, slot 1, expected): `refuse`, or `keep K erase E…` (slots by number).
    let table = [
        ("a", "a", "refuse"),
        ("a", "s", "keep 0 erase 1"),
        ("a", "n", "keep 0 erase 1"),
        ("a", "t", "keep 0 erase 1"),
        ("a", "-", "keep 0 erase"),
        ("s", "a", "keep 1 erase 0"),
        ("n", "a", "keep 1 erase 0"),
        ("t", "a", "keep 1 erase 0"),
        ("-", "a", "keep 1 erase"),
        ("s", "s", "refuse"),
        ("s", "n", "refuse"),
        ("s", "t", "refuse"),
        ("s", "-", "refuse"),
        ("n", "s", "refuse"),
        ("n", "n", "refuse"),
        ("n", "t", "refuse"),
        ("n", "-", "refuse"),
        ("t", "s", "refuse"),
        ("t", "n", "refuse"),
        ("t", "t", "refuse"),
        ("t", "-", "refuse"),
        ("-", "s", "refuse"),
        ("-", "n", "refuse"),
        ("-", "t", "refuse"),
        ("-", "-", "refuse"),
    ];
    let d = domain(7, 3);
    let active = BTreeMap::from([(d, 5u64)]);
    for (s0, s1, want) in table {
        let c = |s: &str| s.chars().next().unwrap();
        let slots = vec![[slot_of(c(s0), d, 0), slot_of(c(s1), d, 0)]];
        let got = match plan(&active, slots) {
            Err(Error::IntegrityViolation {
                invariant: "INV-14",
            }) => "refuse".to_owned(),
            Err(e) => format!("error {e:?}"),
            Ok(r) => {
                let k = &r.keys[&d];
                assert_eq!((k.pair, k.key_version), (0, 5), "{s0}{s1}");
                assert_eq!(k.key.as_bytes(), &[0xAA; 32], "{s0}{s1}: the active key");
                let erase: Vec<String> = r.erase.iter().map(|(_, s)| format!(" {s}")).collect();
                format!("keep {} erase{}", k.slot, erase.concat())
            }
        };
        assert_eq!(got, want, "slots {s0} {s1}");
    }
}

#[test]
// oracle: A §13.4 "slots that belong to no domain are erased" (a rolled-back create or flush, DB-90)
#[spec("SR-13.4-3")]
fn p4_keys_recovery_erases_the_slots_of_no_domain() {
    let live = domain(1, 1);
    let gone = domain(1, 2);
    let slots = vec![
        [slot_of('a', live, 0), slot_of('-', live, 0)],
        [slot_of('a', gone, 1), slot_of('t', gone, 1)],
        [slot_of('-', gone, 2), slot_of('n', gone, 2)],
    ];
    let r = plan(&BTreeMap::from([(live, 5)]), slots).unwrap();
    assert_eq!(r.keys.keys().copied().collect::<Vec<_>>(), [live]);
    assert_eq!(r.erase, [(1, 0), (1, 1), (2, 1)]);
}

#[test]
// oracle: A §13.4 "the slot holding v MUST exist … otherwise refuse": with two, it is not known
#[spec("SR-13.4-3")]
fn p4_keys_recovery_refuses_a_domain_whose_active_version_is_in_two_slots() {
    let d = domain(1, 1);
    let slots = vec![
        [slot_of('a', d, 0), slot_of('-', d, 0)],
        [slot_of('a', d, 1), slot_of('-', d, 1)],
    ];
    assert!(matches!(
        plan(&BTreeMap::from([(d, 5)]), slots),
        Err(Error::IntegrityViolation {
            invariant: "INV-14"
        })
    ));
}

#[test]
// oracle: A §13.4 + §14.7 end to end: the file read back, then the rule (KF-1, KF-3 of the registers)
#[spec("SR-13.4-3")]
fn p4_keys_recovery_from_a_file_after_a_crash_in_phase_a() {
    let (sim, v) = vfs();
    let d = domain(3, 3);
    let (mut f, _) = KeyFile::open(v.clone(), "KEYS").unwrap();
    f.append(d, 1, &Key::from_bytes(&[0x01; 32])).unwrap();
    // Phase A of rotation to version 2 wrote the inactive slot; the COMMIT was lost.
    f.write_slot(0, 1, d, 2, &Key::from_bytes(&[0x02; 32]))
        .unwrap();
    drop(f);
    sim.restart(CrashPolicy::DropAll);
    let (_, slots) = KeyFile::open(v.clone(), "KEYS").unwrap();
    let r = plan(&BTreeMap::from([(d, 1)]), slots).unwrap();
    assert_eq!(r.keys[&d].key.as_bytes(), &[0x01; 32]);
    assert_eq!(r.erase, [(0, 1)], "the orphan of phase A is erased");
    // KF-1: the active slot torn → refuse.
    let mut raw = v.open("KEYS", OpenMode::Existing).unwrap();
    raw.write_at(4_096 + 30, &[0xFF]).unwrap();
    drop(raw);
    let (_, slots) = KeyFile::open(v, "KEYS").unwrap();
    assert!(plan(&BTreeMap::from([(d, 1)]), slots).is_err());
}

// --- §13.1 --------------------------------------------------------------------------------------

#[test]
// oracle: A §13.1 b(t) = scrambled_id[0] mod 64, values worked out by hand
#[spec("SR-13.1-2")]
fn p4_keys_a_bucket_is_the_first_scrambled_byte_mod_64() {
    for (first, want) in [
        (0x00, 0),
        (0x01, 1),
        (0x3F, 63),
        (0x40, 0),
        (0x85, 5),
        (0xFF, 63),
    ] {
        let mut sid = [0xEEu8; 64];
        sid[0] = first;
        assert_eq!(bucket_of(&sid), want, "first byte {first:#04x}");
    }
}

#[test]
// oracle: A §13.1 "all keys are 32 bytes from the OS CSPRNG"
#[spec("SR-13.1-3")]
fn p4_keys_keys_are_32_fresh_bytes() {
    let keys: Vec<Key> = (0..64).map(|_| Key::generate()).collect();
    for (i, k) in keys.iter().enumerate() {
        assert_eq!(k.as_bytes().len(), 32);
        assert!(k.as_bytes().iter().any(|b| *b != 0), "key {i} is zero");
        for other in &keys[..i] {
            assert_ne!(k, other, "two generated keys are equal");
        }
    }
}
