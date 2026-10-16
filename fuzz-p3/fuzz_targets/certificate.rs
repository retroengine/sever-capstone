//! §11.1 certificate parser (the engine's, at d = 16): never panic; an accepted certificate
//! re-encodes exactly.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_cert::Certificate;

fuzz_target!(|data: &[u8]| {
    if let Ok(c) = Certificate::parse(data, 16) {
        assert_eq!(c.to_bytes(), data);
    }
});
