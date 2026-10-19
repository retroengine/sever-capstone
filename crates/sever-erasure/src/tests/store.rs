//! The wrapped-key store's recovery scan (DB-91) after a crash: a record the crash cut short at
//! the end of the newest segment was never synced, so it is dropped, as Part 2's append store
//! drops a torn tail (§12.2: only synced data survives a crash); damage in an older segment,
//! which was synced, is refused. Found by the Part 4 crash campaign (a `Random` crash during the
//! phase C append left a record with a complete length and a failing CRC).

use std::sync::Arc;

use sever_types::Error;
use sever_vfs::{OpenMode, SimVfs, Vfs};

use crate::store::{DIR, WrappedStore};

fn values(n: usize) -> Vec<Vec<u8>> {
    (0..n)
        .map(|i| vec![u8::try_from(i).unwrap(); 300])
        .collect()
}

fn segments(v: &SimVfs) -> Vec<String> {
    let mut s: Vec<String> = v.list(DIR).unwrap();
    s.sort();
    s
}

/// A record header with a complete length and a body that fails its CRC, at the end of `seg`.
fn tear(v: &SimVfs, seg: &str) {
    let mut f = v.open(&format!("{DIR}/{seg}"), OpenMode::Existing).unwrap();
    let mut rec = 99u64.to_be_bytes().to_vec();
    rec.extend_from_slice(&40u32.to_be_bytes());
    rec.extend_from_slice(&[0xA5; 44]); // 40 bytes of value and a 4-byte CRC that does not match
    f.append(&rec).unwrap();
    f.fsync().unwrap();
}

// oracle: A §12.2 (only synced data survives a crash; a cut-off tail is not data) and DB-91 (the
// store is scanned in order at recovery, like Part 2's append stores)
#[test]
fn p4_erasure_store_drops_a_torn_record_at_the_end_of_the_newest_segment() {
    let v = SimVfs::new();
    let (mut s, got) = WrappedStore::open(Arc::new(v.clone()), 1 << 20).unwrap();
    assert!(got.is_empty());
    s.append(&values(3)).unwrap();
    drop(s);
    let last = segments(&v).last().cloned().unwrap();
    tear(&v, &last);
    let (mut s, got) = WrappedStore::open(Arc::new(v.clone()), 1 << 20).unwrap();
    assert_eq!(
        got,
        values(3),
        "the torn record is dropped, the synced ones kept"
    );
    s.append(&values(4)[3..]).unwrap();
    drop(s);
    let (_, got) = WrappedStore::open(Arc::new(v.clone()), 1 << 20).unwrap();
    assert_eq!(got, values(4), "appends continue after the cut");
}

// oracle: A §12.2 and §17 IntegrityViolation: synced data that fails its check is corruption
#[test]
fn p4_erasure_store_refuses_a_damaged_record_in_an_older_segment() {
    let v = SimVfs::new();
    let (mut s, _) = WrappedStore::open(Arc::new(v.clone()), 1024).unwrap();
    for chunk in values(8).chunks(1) {
        s.append(chunk).unwrap();
    }
    drop(s);
    let segs = segments(&v);
    assert!(segs.len() >= 2, "{segs:?}");
    let mut f = v
        .open(&format!("{DIR}/{}", segs[0]), OpenMode::Existing)
        .unwrap();
    f.write_at(16 + 12 + 5, &[0x5A]).unwrap(); // inside the first record's value
    f.fsync().unwrap();
    drop(f);
    assert!(matches!(
        WrappedStore::open(Arc::new(v.clone()), 1024),
        Err(Error::IntegrityViolation { .. })
    ));
}
