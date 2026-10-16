//! A log checkpoint with its cosignatures (§10.3, §11.1 tag 7): never panic; an accepted one
//! re-encodes exactly.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_log::store::Witnessed;

fuzz_target!(|data: &[u8]| {
    if let Some(w) = Witnessed::parse(data) {
        assert_eq!(w.to_bytes(), data);
    }
});
