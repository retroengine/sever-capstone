//! Domain strings (spec §2.3, all ASCII, exact bytes).

/// Generator derivation (§9.2), 41 bytes.
pub const DST_GEN: &[u8] = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS";
/// Proof challenge (§9.5), 15 bytes.
pub const DST_POSK: &[u8] = b"SEVERDB_POSK_V1";
/// User insert signature (§9.8), 17 bytes.
pub const DST_INSERT: &[u8] = b"SEVERDB-INSERT-V1";
/// Operator log-checkpoint signature (§10.3), 14 bytes.
pub const DST_STH: &[u8] = b"SEVERDB-STH-V1";
/// Witness cosignature (§10.4), 17 bytes.
pub const DST_COSIGN: &[u8] = b"SEVERDB-COSIGN-V1";
/// Operator certificate signature (§11), 15 bytes.
pub const DST_CERT: &[u8] = b"SEVERDB-CERT-V1";
