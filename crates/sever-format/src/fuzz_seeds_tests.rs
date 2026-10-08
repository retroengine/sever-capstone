//! Writes the fuzz seeds of `fuzz-p2/` (valid encodings of every structure): run with
//! `cargo test -p sever-format --release -- --ignored p2_format_write_fuzz_seeds`.
//!
//! Test code (it writes fixture files with `std::fs`), kept out of the storage code that the
//! architecture test holds to the VFS rule (SR-12.2-1).

use crate::image::tests;
use crate::image::*;
use crate::wal::{CoreRecord, WalRecord};
use crate::{Manifest, Secrets, SegmentHeader, StoreRecord, magic, paged};
use sever_types::CollectionId;

#[test]
#[ignore]
fn p2_format_write_fuzz_seeds() {
    let root = std::path::Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/../../fuzz-p2/seeds"));
    let put = |target: &str, name: &str, bytes: &[u8]| {
        let d = root.join(target);
        std::fs::create_dir_all(&d).unwrap();
        std::fs::write(d.join(name), bytes).unwrap();
    };
    let (img, l) = tests::sample();
    let meta = CheckpointMeta {
        checkpoint_id: 1,
        next_wal_seq: 7,
        next_txn_id: 2,
        config_hash: [3; 32],
    };
    let s = img.to_streams(&meta, &|_| l).unwrap();
    put(
        "checkpoint_file",
        "slots_paged",
        &paged::encode(&magic::SLOTS, 0, 7, &s.slots),
    );
    let lens = [
        s.meta.len() / 4,
        s.collections.len() / 2,
        s.groups.len() / 8,
        s.slots.len() / 8,
        s.locator.len() / 4,
        s.payload_refs.len() / 2,
    ];
    if lens.iter().all(|&n| n < 256) {
        let mut b: Vec<u8> = lens.iter().map(|&n| n as u8).collect();
        for st in [
            &s.meta,
            &s.collections,
            &s.groups,
            &s.slots,
            &s.locator,
            &s.payload_refs,
        ] {
            b.extend_from_slice(st);
        }
        put("checkpoint_file", "streams", &b);
    }
    let cid = CollectionId::from_bytes([1; 16]);
    let rec = CoreRecord::Counters {
        cid,
        big_n: 5,
        k: 2,
    };
    for (i, r) in [rec, CoreRecord::Begin, CoreRecord::CollectionDrop { cid }]
        .iter()
        .enumerate()
    {
        let w = WalRecord {
            ty: r.ty(),
            wal_seq: 9,
            txn_id: 3,
            payload: r.encode_payload(&l).unwrap(),
        };
        put("wal_record", &format!("r{i}"), &w.encode());
    }
    put(
        "manifest",
        "manifest",
        &Manifest {
            sealer_id: 0,
            checkpoint_id: 4,
            first_wal_seq: 8,
        }
        .encode(),
    );
    put(
        "manifest",
        "segment",
        &SegmentHeader {
            sealer_id: 0,
            segment_seq: 2,
            first_wal_seq: 8,
        }
        .encode(),
    );
    put(
        "manifest",
        "secrets",
        &Secrets {
            sealer_id: 0,
            entries: vec![(1, vec![7; 64])],
        }
        .encode(),
    );
    put(
        "store_record",
        "r",
        &StoreRecord {
            key: 4,
            bytes: b"passage".to_vec(),
        }
        .encode(),
    );
}
