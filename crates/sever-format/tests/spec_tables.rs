//! L3 conformance of fixed facts the spec states in its tables: which WAL record types belong to
//! transaction participants (§14.6), and the size limits of WAL and store records (§12.3, §14.8).

#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use sever_format::{RecordType, StoreRecord, WalParse, WalRecord};
use sever_spec::spec;

#[test]
#[spec("SR-14.6-1")]
fn p2_format_participant_record_types_are_4_9_10_11_14() {
    // §14.6: "The payloads of types 4, 9, 10, 11 and 14 belong to transaction participants".
    for code in 0u8..=255 {
        if let Some(t) = RecordType::from_byte(code) {
            assert_eq!(
                t.is_participant(),
                [4, 9, 10, 11, 14].contains(&code),
                "type {code}"
            );
        } else {
            assert!(code == 0 || code > 17, "type {code} is defined in §14.6");
        }
    }
}

#[test]
#[spec("SR-14.8-1")]
fn p2_format_store_values_are_at_most_16_mib() {
    // §14.8: `u64be key ‖ u32be len ‖ bytes ‖ u32be crc32c`; "the value of a record is at most 16 MiB".
    let max = 16 * 1024 * 1024;
    let ok = StoreRecord {
        key: 3,
        bytes: vec![7; max],
    }
    .encode();
    assert_eq!(ok.len(), 8 + 4 + max + 4);
    let (r, used) = StoreRecord::parse_next(&ok).unwrap();
    assert_eq!((r.key, r.bytes.len(), used), (3, max, ok.len()));
    let over = StoreRecord {
        key: 3,
        bytes: vec![7; max + 1],
    }
    .encode();
    assert!(
        StoreRecord::parse_next(&over).is_none(),
        "16 MiB + 1 byte is refused"
    );
}

#[test]
#[spec("SR-14.6-1")]
fn p2_format_wal_records_fit_a_64_mib_segment() {
    // §14.6: len is the whole record, 25 + payload bytes. A segment is 64 MiB with a 32-byte
    // header (§12.3, §14.9), so the largest record is 64 MiB − 32 bytes.
    let largest = 64 * 1024 * 1024 - 32;
    let rec = |payload: usize| {
        WalRecord {
            ty: RecordType::Extension,
            wal_seq: 1,
            txn_id: 1,
            payload: vec![0; payload],
        }
        .encode()
    };
    let b = rec(largest - 25);
    assert_eq!(
        u32::from_be_bytes(b[..4].try_into().unwrap()) as usize,
        largest
    );
    assert!(matches!(WalRecord::parse_next(&b), WalParse::Record(_, n) if n == largest));
    let b = rec(largest - 24);
    assert!(
        !matches!(WalRecord::parse_next(&b), WalParse::Record(..)),
        "one byte too long"
    );
}
