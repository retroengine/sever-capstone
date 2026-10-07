//! §14.9 MANIFEST, segment header, file header and SECRETS: never panic; accepted ones re-encode.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_format::{FileHeader, Manifest, Secrets, SegmentHeader, magic};

fuzz_target!(|data: &[u8]| {
    if let Ok(m) = Manifest::parse(data, 0) {
        assert_eq!(m.encode(), data);
    }
    if let Ok(h) = SegmentHeader::parse(data, 0) {
        assert_eq!(h.encode(), data);
    }
    if let Ok(h) = FileHeader::parse(data, &magic::STORE, 0) {
        assert_eq!(h.encode(), data);
    }
    if let Ok(s) = Secrets::parse(data, 0) {
        assert_eq!(s.encode(), data);
        let _ = s.k_scramble();
    }
});
