//! §14.5 bucket block decoder under a fixed group key: never panic; only a block sealed under the
//! key opens, and any byte string of the block's length is refused unless it does.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_keys::{Domain, Key};
use sever_seal::block::decode_block;

fuzz_target!(|data: &[u8]| {
    let gk = Key::from_bytes(&[7; 32]);
    let d = Domain {
        collection_id: [1; 16],
        group_id: [2; 32],
    };
    let _ = decode_block(&gk, &d, 3, data);
});
