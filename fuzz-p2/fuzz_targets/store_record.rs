//! §14.8 append-store records: never panic; an accepted record re-encodes exactly.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_format::StoreRecord;

fuzz_target!(|data: &[u8]| {
    if let Some((r, n)) = StoreRecord::parse_next(data) {
        assert_eq!(r.encode(), data[..n]);
    }
});
