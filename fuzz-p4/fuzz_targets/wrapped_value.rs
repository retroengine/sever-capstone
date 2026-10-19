//! §14.8 wrapped-key store values (DB-91): never panic; a parsed value re-encodes exactly.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_erasure::records::{Value, block_value, drop_value, envelopes_value, parse};

fuzz_target!(|data: &[u8]| {
    if let Ok(v) = parse(data) {
        let again = match &v {
            Value::Block(d, version, blk) => block_value(d, *version, blk),
            Value::Envelopes(d, entries) => envelopes_value(d, entries),
            Value::Drop(cid) => drop_value(cid),
        };
        assert_eq!(again, data);
    }
});
