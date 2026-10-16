//! A leaf's placement (DB-86): never panic; an accepted placement re-encodes exactly.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_log::leaf::Placement;

fuzz_target!(|data: &[u8]| {
    if let Ok(p) = Placement::parse(data) {
        assert_eq!(p.to_bytes().as_slice(), data);
    }
});
