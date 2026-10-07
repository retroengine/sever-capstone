//! §14.6 WAL framing and typed payloads: never panic; an accepted record re-encodes exactly.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_format::{CoreRecord, Layout, WalParse, WalRecord};
use sever_types::CollectionId;

fuzz_target!(|data: &[u8]| {
    if let WalParse::Record(r, n) = WalRecord::parse_next(data) {
        assert_eq!(r.encode(), data[..n]);
        let layout = |_: &CollectionId| Some(Layout::plain(8));
        if let Ok(c) = CoreRecord::parse(r.ty, &r.payload, &layout) {
            assert_eq!(c.encode_payload(&Layout::plain(8)).ok().as_deref(), Some(&r.payload[..]));
        }
    }
    // Typed payloads straight from bytes, every type.
    if let Some((&t, rest)) = data.split_first() {
        if let Some(ty) = sever_format::RecordType::from_byte(t) {
            let layout = |_: &CollectionId| Some(Layout::plain(8));
            let _ = CoreRecord::parse(ty, rest, &layout);
        }
    }
});
