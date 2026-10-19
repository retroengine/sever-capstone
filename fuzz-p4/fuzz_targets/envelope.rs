//! §14.4 record-key envelopes: unwrapping arbitrary bytes under a fixed bucket key never panics.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_keys::{Domain, Key};
use sever_seal::block::{BucketKey, unwrap_record_key};

fuzz_target!(|data: &[u8]| {
    let bk = BucketKey {
        version: 1,
        key: Key::from_bytes(&[9; 32]),
    };
    let d = Domain {
        collection_id: [1; 16],
        group_id: [2; 32],
    };
    let _ = unwrap_record_key(&bk, &d, &[3; 64], data);
});
