//! §6.3 `partition.svp` parser: never panics. Each input is parsed as is (the hash check is first,
//! so almost all fail there) and with a correct SHA-256 appended, which reaches every field check.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sha2::{Digest, Sha256};

fuzz_target!(|data: &[u8]| {
    let _ = sever_partition::PartitionArtefact::parse(data);
    let mut with_hash = data.to_vec();
    with_hash.extend_from_slice(&Sha256::digest(data));
    if let Ok(a) = sever_partition::PartitionArtefact::parse(&with_hash) {
        // Accepted: the checks of §6.3 hold.
        assert!(a.d > 0 && a.d % 8 == 0);
        assert_eq!(a.centroids.len(), a.k_frozen * a.d);
        assert_eq!(a.precision.len(), a.d * a.d);
        assert!(a.tau.is_finite() && a.precision.iter().all(|v| v.is_finite()));
    }
});
