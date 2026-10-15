//! Domain strings (§2.3): exact ASCII bytes. Every hash, signature and proof input starts with one.

/// Generator derivation (§9.2). Kept from the earlier SEVER prototype (DB-14).
pub const DST_GEN: &[u8] = b"PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS";
/// Proof challenge (§9.5).
pub const DST_POSK: &[u8] = b"SEVERDB_POSK_V1";
/// Merlin transcript label for the hedged nonces (§9.6).
pub const DST_NONCE: &[u8] = b"SEVERDB_POSK_NONCE_V1";
/// User insert signature (§9.8).
pub const DST_INSERT: &[u8] = b"SEVERDB-INSERT-V1";
/// Operator log-checkpoint signature (§10.3).
pub const DST_STH: &[u8] = b"SEVERDB-STH-V1";
/// Witness cosignature (§10.4).
pub const DST_COSIGN: &[u8] = b"SEVERDB-COSIGN-V1";
/// Operator certificate signature (§11).
pub const DST_CERT: &[u8] = b"SEVERDB-CERT-V1";
