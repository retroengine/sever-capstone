//! The scanner's targets file: never panic on any text.
#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    if let Ok(t) = std::str::from_utf8(data) {
        let _ = sever_scan::parse_targets(t);
    }
});
