//! §14.7 key-file slot decoder: never panic on any 512 bytes at any position; a valid slot names
//! the position it was read at.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_keys::file::{SLOT_BYTES, SlotState, decode_slot};

fuzz_target!(|data: &[u8]| {
    let Some((pos, slot)) = data.split_first_chunk::<8>() else {
        return;
    };
    let pos = u64::from_be_bytes(*pos) % 1024;
    let mut s = [0u8; SLOT_BYTES];
    for (d, b) in s.iter_mut().zip(slot) {
        *d = *b;
    }
    if let SlotState::Valid(r) = decode_slot(&s, pos) {
        assert_eq!(r.domain_index, pos);
    }
    let _ = decode_slot(slot, pos);
});
