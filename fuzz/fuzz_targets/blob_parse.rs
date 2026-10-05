//! §5.5 blob parser: never panics, and an accepted blob re-encodes to exactly the same bytes.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_index::blob::{canonical_blob, parse_blob};
use sever_index::changeset::GroupState;
use sever_index::{GroupExtension, NoExtension};
use sever_quant::QVec;
use sever_types::RecordId;

fuzz_target!(|data: &[u8]| {
    let Ok(p) = parse_blob(data, &<NoExtension as GroupExtension>::BLOB_MAGIC, 0) else {
        return;
    };
    // The parser enforces the §5.5 rules on what it accepted.
    assert_eq!(p.members.len() as u64, p.n);
    for w in p.members.windows(2) {
        assert!(w[0].0 < w[1].0, "IDs strictly ascending by bytes");
    }
    // Round trip when every member is a valid record with x̃ in i32 (the stored width).
    let d = p.s.len();
    let mut members = Vec::new();
    for (id, x) in &p.members {
        let Ok(rid) = RecordId::from_bytes(id) else { return };
        let Ok(x32) = x.iter().map(|&v| i32::try_from(v)).collect::<Result<Vec<_>, _>>() else {
            return;
        };
        let Ok(q) = QVec::from_stored(x32, d) else { return };
        members.push((rid, q));
    }
    let mut state = GroupState::<NoExtension>::empty(d);
    state.s = p.s.clone();
    state.n = p.n;
    let refs: Vec<(&RecordId, &QVec)> = members.iter().map(|(r, x)| (r, x)).collect();
    assert_eq!(canonical_blob(&NoExtension, d, &state, &refs), data);
});
