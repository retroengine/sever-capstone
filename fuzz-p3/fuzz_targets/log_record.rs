//! §14.6 log WAL records (LOG_LEAF with its placement, LOG_CHECKPOINT, CERT_REF), and the insert
//! leaf of §10.2: never panic; an accepted record re-encodes exactly.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_format::{RecordType, WalRecord};
use sever_log::leaf::InsertLeaf;
use sever_log::store::LogRecord;

fuzz_target!(|data: &[u8]| {
    if let Some((&t, rest)) = data.split_first() {
        let ty = match t % 3 {
            0 => RecordType::LogLeaf,
            1 => RecordType::LogCheckpoint,
            _ => RecordType::CertRef,
        };
        let r = WalRecord {
            ty,
            wal_seq: 0,
            txn_id: 0,
            payload: rest.to_vec(),
        };
        if let Ok(l) = LogRecord::decode(&r) {
            assert_eq!(l.encode(), (ty, rest.to_vec()));
        }
    }
    if let Ok(l) = InsertLeaf::parse(data) {
        assert_eq!(l.to_bytes().as_slice(), data);
    }
});
