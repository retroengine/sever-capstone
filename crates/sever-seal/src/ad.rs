//! The associated data of spec §13.2, one function per row of its table. Every value is bound to
//! its owner, so it cannot be moved to another record, field or key version.
//!
//! | Data | Key | Associated data |
//! |---|---|---|
//! | Slot payload | `RK_t` | `collection_id ‖ scrambled_id ‖ 0x01` |
//! | Passage text | `RK_t` | `collection_id ‖ scrambled_id ‖ 0x02` |
//! | Wrapped record key | `BK_{g,b}` | `collection_id ‖ group_id(32) ‖ scrambled_id ‖ u64be bucket_version` |
//! | Wrapped bucket key | `GK_g` | `collection_id ‖ group_id(32) ‖ u8 b ‖ u64be group_key_version` |
//! | `S ‖ r_agg` | `GK_g` | `collection_id ‖ group_id(32) ‖ u64be group_key_version ‖ u64be n` |

use sever_keys::Domain;

/// A scrambled ID (§9.7), 64 bytes.
pub type Sid = [u8; 64];

/// Row 1: the slot payload (record ID, `x̃`, insert leaf index, `r_t`).
pub fn slot_payload(collection_id: &[u8; 16], sid: &Sid) -> Vec<u8> {
    [&collection_id[..], &sid[..], &[0x01]].concat()
}

/// Row 2: the passage text.
pub fn passage(collection_id: &[u8; 16], sid: &Sid) -> Vec<u8> {
    [&collection_id[..], &sid[..], &[0x02]].concat()
}

/// Row 3: a record key wrapped under its bucket key.
pub fn record_key(d: &Domain, sid: &Sid, bucket_version: u64) -> Vec<u8> {
    [
        &d.collection_id[..],
        &d.group_id[..],
        &sid[..],
        &bucket_version.to_be_bytes(),
    ]
    .concat()
}

/// Row 4: a bucket key wrapped under the group key.
pub fn bucket_key(d: &Domain, bucket: u8, group_key_version: u64) -> Vec<u8> {
    [
        &d.collection_id[..],
        &d.group_id[..],
        &[bucket],
        &group_key_version.to_be_bytes(),
    ]
    .concat()
}

/// Row 5: the accumulator `S ‖ r_agg`.
pub fn accumulator(d: &Domain, group_key_version: u64, n: u64) -> Vec<u8> {
    [
        &d.collection_id[..],
        &d.group_id[..],
        &group_key_version.to_be_bytes(),
        &n.to_be_bytes(),
    ]
    .concat()
}
