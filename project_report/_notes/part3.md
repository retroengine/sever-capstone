# Part 3 "The Receipt" — reading notes for the cryptography section

Scope: crates `sever-crypto`, `sever-commit`, `sever-log`, `sever-cert`, `sever-p3`, `sever-py-p3`,
`sever-crashkit-p3`; separate workspaces `verifier/` (sever-verify) and `audit/` (sever-audit);
`spikes/p3-proof`; Python `sever_refmodel_certs`, `sever_testkit_p3`, `sever_db_p3`, `sever_demo_p3`;
spec §9, §10, §11, §16.2–16.3; `spec/registers_p3.yaml`; `golden/p3_*`; `docs/SOUNDNESS.md`; G-34 / DB-95.

Tag key: [CODE: file:Lx-Ly] = read in code; [DOC: file §N] = claim in a document; [INFERRED: why];
[NOT FOUND: what was searched]. Line numbers were checked with grep -n / sed -n on the working copy
(branch `bughunt-2026-11`, HEAD `4a03951`; Parts 3 and 4 are frozen, tag v1.0.0).
All paths are relative to `/home/saiki/sever-db`. No secrets, keys or database directories were opened;
the golden files contain only test keys (public golden values; not printed here).

---------------------------------------------------------------------------------------------------

## 0. Overview in ten lines

- Part 3 adds one claim: every deletion yields a certificate anyone can verify offline [DOC: CLAUDE.md §6.1; docs/SEVER-DB_BUILD_PLAN_PART_3-4.md §1.1].
- Group: ristretto255 (RFC 9496) via `curve25519-dalek =4.1.3` [CODE: crates/sever-crypto/Cargo.toml:L17].
- Commitment: vector Pedersen over d components + one blinding generator `H`: `C = r·H + Σ scalar(v_i)·G_i` [CODE: crates/sever-crypto/src/commit.rs:L14-L26].
- Proof: non-interactive (Fiat–Shamir) Okamoto/Schnorr proof of knowledge of an opening of `C_S_post`, bound to a 152-byte deletion context [CODE: crates/sever-crypto/src/posk.rs:L56-L85, L130-L156].
- Log: RFC 9162 Merkle tree over SHA-256, operator-signed checkpoints, 5 simulated witnesses, threshold 4 [CODE: crates/sever-log/src/merkle.rs:L20-L37; checkpoint.rs:L11-L26].
- Certificate: TLV, tags 1..13 ascending + trailer `0xFF ‖ u32be 64 ‖ Ed25519 sig` over `DST_CERT ‖ body` [CODE: crates/sever-cert/src/encoding.rs:L216-L253].
- Verifier is a separate Cargo workspace that re-implements everything (xmd, generators, parser, proof check, Merkle) from the spec [CODE: verifier/Cargo.toml:L1-L35].
- Auditor is a separate workspace holding byte-identical copies of 9 verifier files; checks chain/consistency over a log export [CODE: audit/Cargo.toml:L1-L10; cmp output, see §8].
- Witnesses are simulated by the project in v1; their keys live in the key directory file `WITNESSES` [CODE: crates/sever-p3/src/witnesses.rs:L1-L9].
- Part 3 stores everything in plaintext (`PlaintextSealer`); no confidentiality claim until Part 4 [CODE: crates/sever-p3/src/lib.rs:L22, L224; DOC: CLAUDE.md §7 "Plaintext on disk"].

---------------------------------------------------------------------------------------------------

## 1. Table of every cryptographic primitive in Part 3 code

Pins (all `=`-exact, spec §20.1) and the versions locked in `Cargo.lock`:

| Crate | Pin in Cargo.toml | Locked version [CODE: Cargo.lock] |
|---|---|---|
| curve25519-dalek | `=4.1.3` [CODE: crates/sever-crypto/Cargo.toml:L17] | 4.1.3 |
| sha2 | `=0.10.9` [CODE: crates/sever-crypto/Cargo.toml:L18] | 0.10.9 |
| ed25519-dalek | `=2.2.0` [CODE: crates/sever-crypto/Cargo.toml:L19] | 2.2.0 |
| merlin | `=3.0.0` [CODE: crates/sever-crypto/Cargo.toml:L20] | 3.0.0 |
| rand_core | `=0.6.4`, feature `getrandom` [CODE: crates/sever-crypto/Cargo.toml:L21] | 0.6.4 |
| zeroize | `=1.9.0` [CODE: crates/sever-crypto/Cargo.toml:L22] | 1.9.0 |
| hmac (Part 1, used for scrambled IDs, not in sever-crypto) | `=0.12.1` [CODE: crates/sever-index/Cargo.toml:L28] | 0.12.1 |
| pyo3 (SDK binding) | `=0.29.2`, `abi3-py313` [CODE: crates/sever-py-p3/Cargo.toml:L24] | 0.29.2 |
| Rust toolchain | channel `1.98.1` [CODE: rust-toolchain.toml]; MSRV 1.85, edition 2024 [CODE: Cargo.toml:L10-L11] | — |

Verifier and auditor pin the same three primitive crates: curve25519-dalek `=4.1.3`, sha2 `=0.10.9`,
ed25519-dalek `=2.2.0` (+ `serde_json = "1"` for anchors/golden files) [CODE: verifier/Cargo.toml:L24-L28; audit/Cargo.toml:L24-L28].
They do NOT depend on merlin, rand_core or zeroize (the verifier never derives nonces).

| # | Primitive | Algorithm / group / parameters | Library | Where [CODE] |
|---|---|---|---|---|
| P1 | Prime-order group | ristretto255, RFC 9496; scalar field order ℓ = 2^252 + 27742317777372353535851937790883648493 | curve25519-dalek 4.1.3 (`RistrettoPoint`, `Scalar`) | crates/sever-crypto/src/group.rs:L1-L55; lib.rs:L518-L519 |
| P2 | `expand_message_xmd`, H = SHA-512 | RFC 9380 §5.3.1; `b_in_bytes`=64, `s_in_bytes`=128; Z_pad = 128 zero bytes; limits ell≤255, len≤65535, len(DST)≤255 | project's own code (dalek 4.1.3 lacks it; DB-52) on sha2 | crates/sever-crypto/src/xmd.rs:L14-L59 (params L10-L11); verifier copy verifier/src/xmd.rs (59 lines) |
| P3 | One-way map / `hash_to_group` | `RistrettoPoint::from_uniform_bytes(expand_message_xmd_sha512(msg, DST, 64))` (RFC 9496 §4.3.4) | curve25519-dalek | crates/sever-crypto/src/group.rs:L10-L20; verifier/src/gens.rs:L33-L38 |
| P4 | Generators H, G_0..G_{d-1} | see §2 | — | crates/sever-crypto/src/generators.rs:L17-L45 |
| P5 | Generator digest `gdigest` | SHA-512(enc(H) ‖ enc(G_0) ‖ … ‖ enc(G_{d-1})), 64 bytes | sha2 | crates/sever-crypto/src/generators.rs:L35-L45 |
| P6 | Pedersen commitment (vector) | `blind·H + Σ scalar(v_i)·G_i`, constant-time `multiscalar_mul` | curve25519-dalek | crates/sever-crypto/src/commit.rs:L14-L26 |
| P7 | Proof of knowledge of a representation | Fiat–Shamir Σ-protocol, d+1 witnesses, see §5 | curve25519-dalek, sha2 | crates/sever-crypto/src/posk.rs |
| P8 | Fiat–Shamir challenge hash | SHA-512 → `Scalar::from_bytes_mod_order_wide` (64-byte reduction) | sha2, dalek | posk.rs:L56-L85 |
| P9 | Hedged nonce derivation | Merlin 3 transcript (STROBE-128), `rekey_with_witness_bytes`, `finalize` with 32 B OS entropy; each nonce = `from_bytes_mod_order_wide(64 B)` | merlin 3.0.0, rand_core OsRng | crates/sever-crypto/src/nonce.rs:L117-L147 |
| P10 | OS entropy | `OsRng` (getrandom) wrapped as `StrictProofRng` (not `SeedableRng`) | rand_core 0.6.4 | nonce.rs:L56-L86 |
| P11 | Digital signature | Ed25519 (RFC 8032), signing deterministic; verification ONLY `verify_strict` | ed25519-dalek 2.2.0 | crates/sever-crypto/src/sig.rs:L22-L63; verifier/src/verify.rs:L55-L59 |
| P12 | Key generation | 32 bytes from `OsRng` → `SigningKey::from_bytes` | ed25519-dalek, rand_core | sig.rs:L26-L33; crates/sever-p3/src/keys.rs:L29-L34 |
| P13 | Merkle leaf / node hash | SHA-256; `leaf_hash = SHA-256(0x00 ‖ leaf)`, `node_hash = SHA-256(0x01 ‖ l ‖ r)`, empty root = SHA-256("") | sha2 | crates/sever-log/src/merkle.rs:L20-L42; verifier/src/merkle.rs (66 lines) |
| P14 | Scrambled record ID | HMAC-SHA-512(k_scramble 64 B from OS, collection_id ‖ record_id), 64 bytes (Part 1 code, consumed by Part 3 as `scrambled_id`) | hmac 0.12.1 + sha2 | crates/sever-index/src/scramble.rs:L16-L40 |
| P15 | Integrity digest of witness file | SHA-256 over `WITNESSES` file body (not a security primitive for the claim; tamper/corruption check) | sha2 | crates/sever-p3/src/witnesses.rs:L72-L80 |
| P16 | Test-only memo key | SHA-256 over `SEVERDB-INV3-MEMO ‖ C_S ‖ r_agg ‖ S` (feature `memo-checks`, test tooling) | sha2 | crates/sever-commit/src/lib.rs:L392-L401 |

- [CODE: crates/sever-crypto/src/lib.rs:L506-L508] `#![forbid(unsafe_code)]`.
- [CODE: crates/sever-crypto/src/commit.rs:L14-L26] Constant-time multiscalar multiplication is used wherever the inputs are secret (commit, prover's `A`); the verifier's equation uses `vartime_multiscalar_mul` because every input is public [CODE: posk.rs:L148-L151, L190-L194].
- [DOC: docs/SEVER-DB_SPECIFICATION.md §9.1] "No other primitive is used. No primitive is implemented by this project except `expand_message_xmd`." Confirmed: only `xmd.rs` re-implements a standard primitive. [INFERRED: the TLV, Merkle algorithms (RFC 9162 loops), Ed25519 usage and Merlin are all library or RFC-transcribed code; the Merkle verify routines are hand-transcribed RFC 9162 algorithms (merkle.rs:L191-L274) not a library.]
- AES-256-GCM-SIV, CRC-32C belong to Parts 2/4 and are not used in Part 3 certificates. [NOT FOUND: any aes/crc use in sever-crypto, sever-log, sever-cert, verifier, audit (grep).]
- The only AEAD in the Part 3 tree is in `spikes/p3-proof` (throwaway; see §15).

### 1.1 Domain separation strings (exact bytes; spec §2.3)

All defined in `crates/sever-crypto/src/dst.rs`; mirrored independently (not shared code) in `verifier/src/dst.rs` (14 lines; contains 6 of 7: no DST_NONCE) and `audit/src/dst.rs`.

| Name | Bytes (ASCII) | Len | Used for | Code |
|---|---|---|---|---|
| `DST_GEN` | `PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS` | 41 | `expand_message_xmd` DST for H, G_i (§9.2); kept from earlier prototype (DB-14) | dst.rs:L4; used generators.rs:L24, L29 |
| `DST_POSK` | `SEVERDB_POSK_V1` | 15 | first bytes of Fiat–Shamir challenge preimage | dst.rs:L6; posk.rs:L59 |
| `DST_NONCE` | `SEVERDB_POSK_NONCE_V1` | 21 | Merlin transcript label for hedged nonces | dst.rs:L8; nonce.rs:L125 |
| `DST_INSERT` | `SEVERDB-INSERT-V1` | 17 | user insert signature message prefix | dst.rs:L10; sig.rs:L68 |
| `DST_STH` | `SEVERDB-STH-V1` | 14 | operator log-checkpoint signature prefix ("signed tree head") | dst.rs:L12; sig.rs:L82 |
| `DST_COSIGN` | `SEVERDB-COSIGN-V1` | 17 | witness cosignature prefix | dst.rs:L14; sig.rs:L95 |
| `DST_CERT` | `SEVERDB-CERT-V1` | 15 | operator certificate signature prefix | dst.rs:L16; sig.rs:L100-L104 |

- [DOC: docs/SEVER-DB_SPECIFICATION.md §2.3] lengths 41/15/21/17/14/17/15 match `len()` of the constants in code (counted by eye from the byte strings above; the red proof PR3-C01 "a domain string differs by one character" guards them [CODE: tests/proofs/p3/MANIFEST.yaml:L5-L10]).
- Other fixed labels (not DSTs in §2.3): Merlin message labels `b"gens"`, `b"stmt"`, `b"ctx"` and witness-rekey labels `b"r"`, `b"s"` [CODE: nonce.rs:L126-L133]; XMD KAT DST `QUUX-V01-CS02-with-expander-SHA512-256` (test vector only) [CODE: generators.rs:L108]; `WITNESSES` magic `SVDBWITN` [CODE: witnesses.rs:L27]; blob magic `SEVERG` [CODE: crates/sever-commit/src/lib.rs:L201]; test-only `SEVERDB-INV3-MEMO` [CODE: sever-commit lib.rs:L394].
- Note: `DST_STH` message (66 B) is also the inner part of the witness message: `DST_COSIGN ‖ checkpoint_message` (83 B) [CODE: sig.rs:L92-L97]. The cosignature therefore binds the operator's checkpoint message but NOT the operator's signature over it.

---------------------------------------------------------------------------------------------------

## 2. Generators G and H

- [DOC: spec §9.2]
  ```
  H   = ristretto255_from_uniform_bytes( expand_message_xmd_sha512( msg = b"H",            DST_GEN, 64 ) )
  G_i = ristretto255_from_uniform_bytes( expand_message_xmd_sha512( msg = b"G" ‖ u32be(i), DST_GEN, 64 ) )   i = 0..d-1
  ```
- [CODE: crates/sever-crypto/src/generators.rs:L17-L25] `generator_g(i)`: 5-byte msg = `b'G'` then `i.to_be_bytes()`; `hash_to_group(&msg, DST_GEN)`.
- [CODE: generators.rs:L27-L30] `generator_h()` = `hash_to_group(b"H", DST_GEN)`.
- [CODE: crates/sever-crypto/src/group.rs:L15-L20] `hash_to_group`: `expand_message_xmd_sha512(msg, dst, 64)` then `RistrettoPoint::from_uniform_bytes` (L10-L12).
- One independent `expand_message` call per generator: no counter chaining, one fixed DST, fixed-width big-endian index [DOC: spec §9.2]. Verified identically in verifier [CODE: verifier/src/gens.rs:L33-L52].
- `H` is the blinding generator; `G_0..G_{d-1}` are per-component value generators. d = 384 in v1 (spec §2.2); golden vectors also at d = 16 and 8.
- No one knows a discrete-log relation between them because they are hashed from the public string `DST_GEN` ("nothing up my sleeve") [DOC: spec §2.3].
- `gdigest = SHA-512(H ‖ G_0 ‖ … ‖ G_{d-1})` over 32-byte encodings, 64 bytes [CODE: generators.rs:L35-L45; verifier gens.rs:L54-L68]. It is (a) the first message of the nonce transcript and (b) a field of the anchors file; the verifier refuses anchors whose `gdigest` differs from its own derivation [CODE: verifier/src/main.rs:L148-L150].
- Golden values (public, from the Python reference model `sever_refmodel_certs`, DB-51) [CODE: generators.rs:L92-L100]:
  - H     = `80162606b4d5c1e2f2c40f1d21a2338e768114d9fa841739788f0b0f018b2556`
  - G_0   = `46fd08889c692c2040cf735ad765e0a14a15c729b005926ae27922b1f9e46e3b`
  - G_383 = `c465fe97602fba52cc235da917cd7f5617484838cda4a5a5582d2da051d1425b`
  - gdigest(d=384) = `91632a1b…636c9de7` (128 hex; full value in generators.rs:L96-L98 and golden/p3_generators.json)
- Startup self-check (INV-10, DB-77), refuses to run on mismatch, error names the check not a value [CODE: generators.rs:L141-L200; wired in crates/sever-p3/src/lib.rs:L202-L204 and crates/sever-py-p3/src/lib.rs:L154]:
  1. RFC 9380 K.3 known answer for `expand_message_xmd` (msg "abc", len 32, DST `QUUX-V01-CS02-with-expander-SHA512-256`);
  2. RFC 9496 A.3 one-way-map known answer;
  3. H, G_0 and G_383 equal the golden file at every d (G_383 derived for the check if d ≤ 383);
  4. gdigest compared when d = 384.
- Verifier's independent self-check reads golden files bundled at compile time via `include_str!("../../golden/p3_*.json")` (`p3_generators.json`, `p3_rfc9496_ristretto255.json`, `p3_rfc9380_k3_expand_xmd_sha512.json`) and also checks that invalid ristretto encodings are refused [CODE: verifier/src/gens.rs:L12-L16, L88-L160]. The verifier's self_check additionally asserts `dst_gen` of the golden file equals `DST_GEN` [CODE: verifier/src/gens.rs, `self_check` body].

---------------------------------------------------------------------------------------------------

## 3. Commitments, scalar map, group state

### 3.1 Scalar map (spec §4.5)
- [DOC: spec §4.5] `scalar(v) = v mod ℓ` for v ≥ 0; `ℓ − (|v| mod ℓ)` for v < 0. `i64::MIN` cannot occur (§4.4).
- [CODE: crates/sever-crypto/src/group.rs:L50-L55] `scalar_from_i64(v)`: `m = Scalar::from(v.unsigned_abs())`; return `-m` if `v < 0` else `m`. Since |v| ≤ 2^63 < ℓ, |v| mod ℓ = |v| and ℓ−|v| equals group negation, so negative values map to `ℓ − |v|` correctly. `unsigned_abs` makes `i64::MIN` safe anyway. [INFERRED: correct by the comment and by golden/p3_scalar_map.json (vector 4) which has v = 0, 1, −1 … ]
- `x̃` is an `i32` (Q24: `round_half_even(x·2^24)`, |x̃| ≤ 16,777,232) [DOC: spec §4.2]; it is widened with `i64::from(v)` before `scalar_from_i64` [CODE: commit.rs:L28-L35].
- `S_i` is `i64`; |S_i| ≤ 1.68×10^13 < 2^44 with the 10^6 cap [DOC: spec §4.4].
- Quantiser: Part 1 `sever_quant::quantise` (not in Part 3 scope), called by the SDK [CODE: crates/sever-py-p3/src/lib.rs:L293].

### 3.2 Record commitment
- [DOC: spec §9.3] `C_t = r_t·H + Σ_{i=0}^{d-1} scalar(x̃_i)·G_i`.
- [CODE: commit.rs:L14-L26 (`commit`), L28-L36 (`commit_record`)]: scalars = `[blind] ‖ [scalar(v_i)…]`, points = `[H] ‖ [G_i…]`, `RistrettoPoint::multiscalar_mul` (constant time). Length mismatch → `CryptoError::WrongLength`.
- It is a *vector* Pedersen commitment: one generator per component, one extra generator `H` for the blinding (d+1 bases), not a single scalar commit.
- `r_t` is drawn as 64 OS bytes reduced by `Scalar::from_bytes_mod_order_wide` [DOC: spec §9.4; CODE: crates/sever-py-p3/src/lib.rs:L294-L296].

### 3.3 Group commitment and blinding aggregate
- `C_S = r_agg·H + Σ scalar(S_i)·G_i` [CODE: commit.rs:L37-L44 `commit_group`].
- `r_agg = Σ r_t mod ℓ` over members; `C_S = Σ C_t` (commitments add) [DOC: spec §9.3, §11.3 export paragraph].
- State carriers in EP-1 extension [CODE: crates/sever-commit/src/lib.rs]: `GroupCommitment(RistrettoPoint)` default = identity (L93-L105); `BlindingTotal(Scalar)` zeroized on drop (L107-L115); `RecordBlind {insert_leaf_index, has_rt=1, r_t}` zeroized on drop (L117-L132).
- Homomorphic update:
  - add: `public.0 += c_t; secret.0 += record.r_t` [CODE: sever-commit lib.rs:L229-L241];
  - remove: `public.0 -= c_t; secret.0 -= record.r_t` [CODE: lib.rs:L243-L255] — "the exact inverse of add".
  - i.e. `C_S_new = C_S_old − C_t` and `r_agg_new = r_agg_old − r_t` (all mod ℓ / in the group).
- Public transition check (what the verifier recomputes): `C_S_post + C_t = C_S_pre` [CODE: commit.rs:L46-L53 `transition_holds`; verifier/src/verify.rs:L199-L201].
- INV-3 consistency check: `C_S == r_agg·H + Σ scalar(S_i)·G_i` recomputed from stored S and r_agg [CODE: sever-commit lib.rs:L284-L305].
- Blob extension region: magic `SEVERG`, fields `C_S (32) ‖ r_agg (32)` [CODE: lib.rs:L201, L278-L282]. Record secret layout 41 bytes: `u64be insert_leaf_index ‖ u8 has_rt ‖ r_t(32)` [CODE: lib.rs:L320-L352; DOC: spec §14.4, DB-46].

### 3.4 Zero scalar and identity handling
- Zero scalars are accepted and contribute the identity: comment on `commit` [CODE: commit.rs:L11-L13]. An empty group (S = 0, r_agg = 0) commits to the identity (32 zero bytes) [CODE test: crates/sever-crypto/src/tests.rs:L491 `p3_crypto_the_empty_group_commits_to_the_identity`].
- `C_t` must NOT be the identity: `decode_record_commitment` decodes canonically then rejects identity with `CryptoError::IdentityCommitment` [CODE: commit.rs:L55-L63]. Checked at: engine admission (`admit`, sever-commit lib.rs:L205), certificate builder (sever-cert builder.rs:L126), verifier step 1 [CODE: verifier/src/verify.rs:L102-L104]. Test: tests.rs:L500 `p3_crypto_a_record_commitment_may_not_be_the_identity`.
- `C_S_pre`/`C_S_post` MAY be the identity (emptied group), allowed; only `C_t` is forbidden [DOC: spec §9.9, §11.3 step 6].
- Canonical decoding: points via `CompressedRistretto::decompress` (RFC 9496 §4.3.1 DECODE) [CODE: group.rs:L28-L34]; scalars via `Scalar::from_canonical_bytes` (reject ≥ ℓ) [CODE: group.rs:L40-L48]. Verifier decodes the same way [CODE: verifier/src/posk.rs:L59-L73; verify.rs:L51-L53].

### 3.5 Admission (what the engine checks on insert) — EP-1 `admit`
[CODE: crates/sever-commit/src/lib.rs:L203-L227]
1. Decode supplied `C_t` (canonical, not identity) else `CommitmentMismatch` (DB-78 treats malformed as mismatch).
2. Decode `r_t` canonical else `CommitmentMismatch`.
3. Recompute `C_t' = r_t·H + Σ scalar(x̃_i)G_i` from the quantised vector; if `C_t' ≠ C_t` → `CommitmentMismatch` [DOC: spec §9.3].
4. Verify user's Ed25519 signature over `DST_INSERT ‖ collection_id ‖ C_t` with `verify_strict` else `BadUserSignature`.
5. Stage the insert leaf fields (`StagedInsert`) with `insert_leaf_index = log.next_leaf_index()`.
- Before delete: `check_removal` re-derives `C_t` from stored `x̃` and `r_t` and compares with the `C_t` in the record's insert *leaf* (read from the log); mismatch → `IntegrityViolation("§15.3 C_t")`; `has_rt ≠ 1` → `IntegrityViolation("§14.4 has_rt")` [CODE: lib.rs:L257-L276].

---------------------------------------------------------------------------------------------------

## 4. prepare_insert (SDK, application backend)

- [DOC: spec §16.2] "`prepare_insert` quantises (§4.2), draws `r_t` (§9.4), computes `C_t`, signs." `r_t` travels inside the request; engine stores it; caller keeps nothing.
- [CODE: crates/sever-py-p3/src/lib.rs:L276-L316]:
  1. `d = vector.len()` (dimension taken from the vector; engine rejects mismatch, `WrongDimension`).
  2. `x = sever_quant::quantise(&vector, d)?` (Part 1 quantiser, Q24, round-half-even).
  3. `wide = 64 bytes from OsRng.fill_bytes` (L294-L295); `r_t = Scalar::from_bytes_mod_order_wide(&wide)` (L296). Buffer is `Zeroizing`.
  4. `C_t = encode_point(commit_record(generators(d), x, r_t))` (L297-L300).
  5. `signature = KeyPair::from_secret(&secret).sign(&insert_message(collection_id, &c_t))` (L301): Ed25519 over `DST_INSERT ‖ collection_id(16) ‖ C_t(32)` = 65 bytes.
  6. Returns `PyInsertRequest {collection_id, record_id, vector, c_t, r_t (Zeroizing), user_public_key, signature}`; `__repr__` hides record, vector and r_t (L271-L273).
- `r_t` never crosses into Python: no accessor exposed [CODE: crates/sever-py-p3/src/lib.rs:L10-L12, L208-L270; python/sever_db_p3/__init__.py:L127-L137 docstring "`r_t` cannot be read from it"].
- `generators(d)` derives + self-checks (INV-10) before use [CODE: sever-py-p3 lib.rs:L146-L158].
- User key: `UserKey.generate()` 32 OS bytes → Ed25519; never rotates; the backend keeps the secret [CODE: sever-py-p3 lib.rs:L139-L141, L179; python/sever_db_p3/__init__.py:L97-L119].
- An insert retried after a lost ack reuses the same request (same r_t, hence same C_t) [DOC: spec §16.2, §15.1].
- Seeded randomness forbidden (SB-?): there is no sabotage item named for the SDK; the guards are:
  - (a) Python wrapper: any extra positional or keyword argument to `prepare_insert` / `UserKey.generate` raises `SeededNonceForbidden` [CODE: python/sever_db_p3/__init__.py:L91-L95, L106-L109, L127-L137];
  - (b) Rust type system: `prove()` accepts only `&mut StrictProofRng`, which implements `RngCore + CryptoRng` but deliberately NOT `SeedableRng`; `compile_fail` doctests prove a seeded RNG cannot be passed [CODE: crates/sever-crypto/src/nonce.rs:L22-L66 (doctests), L150-L158 (signature)];
  - (c) SB-18 is the sabotage that replaces entropy with `NoEntropy` (always 0) to prove a test catches nonce reuse (see §11).
- Trust boundary note: the application backend holds the user key and decides who may delete; the engine cannot prove the user personally authorised a deletion [DOC: spec §3.3, §11.3 "What no certificate can prove"; Overview L-2, L-27].

---------------------------------------------------------------------------------------------------

## 5. The deletion proof

### 5.1 Statement
- [DOC: spec §9.5] After a deletion the operator proves knowledge of `(r_post, s_0 … s_{d-1})`, `s_i = scalar(S_post_i)`, such that `C_S_post = r_post·H + Σ_i s_i·G_i`. Proof of knowledge of a representation (Okamoto; Camenisch–Stadler), the multi-secret Schnorr proof, made non-interactive by Fiat–Shamir.
- Public: `H, G_0..G_{d-1}`, `C_S_post`, and `ctx` (152 B). Witness: `r_post` and the d scalars. The proof does NOT, by itself, prove the transition from `C_S_pre`; that is the separate public check `C_S_post + C_t = C_S_pre` (§11.3 step 6) [DOC: spec §9.5, §11.3].

### 5.2 Deletion context (152 bytes)
[CODE: crates/sever-crypto/src/posk.rs:L15-L54; verifier/src/posk.rs:L11-L35]
```
ctx = C_S_pre (32) ‖ C_t (32) ‖ scrambled_id (64) ‖ u64be(database_lsn) (8) ‖ collection_id (16)   = 152
```
The context is hashed into the challenge, so a proof cannot be replayed under another pre-state, record, log position or collection (except the emptied-group case, §10).

### 5.3 Prover [CODE: posk.rs:L128-L156 `prove_with_nonces`; nonce.rs:L150-L170 `prove`]
```
(k_r, k_0..k_{d-1})  <- hedged nonces (§5.5 below)
A   = k_r·H + Σ k_i·G_i                                             (constant-time multiscalar mul; posk.rs:L148-L151)
c   = Scalar::from_bytes_mod_order_wide( SHA-512( DST_POSK ‖ C_S_post ‖ A ‖ ctx ) )     (posk.rs:L56-L85)
z_r = k_r + c·r_post  (mod ℓ)                                       (posk.rs:L153)
z_i = k_i + c·s_i     (mod ℓ)                                       (posk.rs:L154)
proof = A (32) ‖ z_r (32) ‖ z_0 … z_{d-1} (32 each)                 = 32 + 32 + 32·d bytes = 12,352 B at d = 384   (posk.rs:L95-L110)
```
- Challenge preimage length `15 + 32 + 32 + 152 = 231` [CODE: posk.rs:L18 `CHALLENGE_PREIMAGE_LEN = 231`].
- Order of the preimage: `DST_POSK` first, then `C_S_post`, then `A`, then `ctx` [CODE: posk.rs:L58-L74]. (SB-16 swaps `A` and `C_S_post`; SB-17 drops `ctx`; SB-23 reduces only 32 bytes.)
- `prove()` recomputes `C_S_post` itself from `(S_post, r_post)` via `commit_group` rather than trusting a caller-supplied point [CODE: nonce.rs:L152-L153]. It zeroizes `k_r`, `k` and `s` after use [CODE: nonce.rs:L163-L166].

### 5.4 Verifier [CODE: posk.rs:L158-L195; verifier/src/posk.rs:L47-L90]
1. Strict decode: exact length `32·(d+2)`; `A` canonical ristretto point; every `z` a canonical scalar (< ℓ) else error.
2. Recompute `c` from `(C_S_post bytes, A bytes, ctx)`.
3. Accept iff `z_r·H + Σ_i z_i·G_i = A + c·C_S_post` (vartime multiscalar mul).
- Verification equation (completeness): `(k_r + c r)H + Σ(k_i + c s_i)G_i = A + c(rH + Σ s_i G_i)`.
- Independent re-implementation in the verifier: `verifier/src/posk.rs` (90 lines) — same equations, written from spec text, no `sever-crypto` dependency.

### 5.5 Hedged nonces (spec §9.6) [CODE: crates/sever-crypto/src/nonce.rs:L117-L147]
```
T = merlin::Transcript::new(b"SEVERDB_POSK_NONCE_V1")
T.append_message(b"gens", gdigest)         (64 B)
T.append_message(b"stmt", C_S_post)        (32 B)
T.append_message(b"ctx",  ctx)             (152 B)
B = T.build_rng().rekey_with_witness_bytes(b"r", bytes(r_post))
for each s_i:  B = B.rekey_with_witness_bytes(b"s", bytes(s_i))
rng = B.finalize(&mut StrictProofRng)      // injects 32 bytes of OsRng entropy
for k in [k_r, k_0..k_{d-1}] in that order:  fill 64 bytes; k = from_bytes_mod_order_wide(bytes); zeroize buf
```
- Three entropy sources at once: secret witness, public statement/context, fresh OS bytes — so neither a broken RNG nor a fault injected mid-proof repeats a nonce vector [DOC: spec §9.6].
- The nonce derivation is not consensus-critical (the verifier never recomputes it) [DOC: spec §9.6]. [CODE confirms: DST_NONCE absent from verifier/src/dst.rs.]
- Why: two accepting transcripts with the same `A` and different challenges reveal every secret (extractor) so one reused nonce vector would leak the group's whole sum [DOC: spec §9.5 "Soundness note"; docs/SOUNDNESS.md §3].

### 5.6 Soundness argument (docs/SOUNDNESS.md)
- [DOC: docs/SOUNDNESS.md §2-§4] completeness (identity), special soundness extractor `r = (z_r − z'_r)/(c − c')`, `s_i = (z_i − z'_i)/(c − c')`, and an HVZK simulator (pick c, z uniformly, set `A = Σ z·G − c·C_S_post`). Model: random oracle + DL hardness in ristretto255; author's own argument, "not an independent review (overview L-21)".
- Tests that execute these: `p3_crypto_soundness_completeness_for_random_states` (tests.rs:L999), `p3_crypto_soundness_extractor_recovers_the_opening` (L1016), `p3_crypto_soundness_simulator_transcripts_verify` (L1051) [CODE: crates/sever-crypto/src/tests.rs].
- Certificate leakage beyond the proof: `C_S_pre`, `C_S_post`, `C_t` (hiding Pedersen commitments) and the 1-bit `group_emptied` [DOC: SOUNDNESS.md §4].
- Unconventional detail worth stating in the paper: the proof is of the *post*-state only; binding to the transition comes from the public equation check and ctx binding (`C_S_pre`, `C_t` in ctx), not from a combined statement.

---------------------------------------------------------------------------------------------------

## 6. Transparency log (RFC 9162), checkpoints, witnesses, keys

### 6.1 Tree
- [DOC: spec §10.1] RFC 9162 §2.1: SHA-256, `leaf_hash = SHA-256(0x00 ‖ leaf)`, `node_hash = SHA-256(0x01 ‖ left ‖ right)`, left-heavy tree from the largest complete left subtree (split = largest power of two < n). Not a Merkle Mountain Range.
- [CODE: crates/sever-log/src/merkle.rs:L20-L26 leaf_hash (prefix `[0u8]`), L28-L37 node_hash (prefix `[1u8]`), L39-L42 empty root = SHA-256(""), L44-L51 `split`].
- `MerkleTree` keeps every level of complete subtrees (`levels[k][j]` = hash of leaves [j·2^k,(j+1)·2^k)), giving O(log n) proofs (≈122 MB at 1.9M leaves per spec §10.5) [CODE: merkle.rs:L53-L124].
- Inclusion proof `PATH(m, D[0:n])` for `m < n ≤ size` [CODE: merkle.rs:L135-L159]; consistency `PROOF(m, D[0:n])` only for `0 < m < n ≤ size` (none for equal sizes; G-50/DB-116) [CODE: merkle.rs:L161-L188; DOC: spec §10.1].
- Verification algorithms are RFC 9162 §2.1.3.2 (inclusion; merkle.rs:L193-L225) and §2.1.4.2 (consistency; merkle.rs:L229-L274), stepwise-commented. The verifier has its own copy of inclusion verification in `verifier/src/merkle.rs` (66 lines); the auditor generates consistency proofs from raw leaves [CODE: audit/src/audit.rs:L104-L204].

### 6.2 Leaf formats (spec §10.2) [CODE: crates/sever-log/src/leaf.rs]
| Type | Bytes | Code |
|---|---|---|
| Insert | `0x01 ‖ collection_id(16) ‖ scrambled_id(64) ‖ C_t(32) ‖ user_public_key(32) ‖ user_signature(64)` = 209 B | leaf.rs:L6-L11 (`LEAF_INSERT=0x01`, `INSERT_LEAF_LEN=209`), L22-L79 |
| Delete | `0x02 ‖ certificate bytes` | leaf.rs:L81-L96 (`LEAF_DELETE=0x02`) |
| Placement (kept beside leaf hash, NOT in the leaf; DB-86) | `group(32, zero-padded text id) ‖ flush(32, zero-padded or zeros)` = 64 B | leaf.rs:L98-L153 |
- `database_lsn` = 0-based index of the operation's own leaf (insert → insert leaf; delete → delete leaf) [DOC: spec §10.2; CODE: sever-cert participant.rs `lsn = log.next_index()` at ~L378-L380].
- Publishing the user's public key in the insert leaf fixes which account key signed each commitment; it records that the service acted for an authenticated account but does not stop a dishonest operator who holds the keys [DOC: spec §10.2; Overview L-27].
- Leaf hash at the verifier is computed over the 209-byte insert leaf [CODE: verifier/src/verify.rs:L147-L153].

### 6.3 Log checkpoint ("STH") and signature
- Struct: `(tree_size u64, root 32, timestamp_ms u64, epoch u32, operator_signature 64)`; encoded size 116 B [CODE: crates/sever-log/src/checkpoint.rs:L21-L23, L28-L41, L87-L121].
- Signed message (66 B): `DST_STH(14) ‖ u64be tree_size ‖ root(32) ‖ u64be timestamp_ms ‖ u32be epoch` [CODE: crates/sever-crypto/src/sig.rs:L72-L90; verifier/src/verify.rs:L61-L69]. 14+8+32+8+4 = 66.
- Operator signature verified with the key for the checkpoint's epoch via `verify_strict` [CODE: checkpoint.rs:L80-L85].
- Cadence: one checkpoint whenever tree_size reaches a positive multiple of 10,000 [CODE: checkpoint.rs:L11-L12, L123-L126], and on demand before a deletion when no witnessed checkpoint covers all current leaves [CODE: crates/sever-cert/src/participant.rs:L165-L177 `due_checkpoints`; DOC: spec §10.3, DB-80]. Each checkpoint is committed as its own transaction over committed leaves only (DB-82).
- Genesis checkpoint `(0, SHA-256(""), creation time, epoch 0)` signed by the operator at database creation; the first checkpoint every witness remembers [CODE: checkpoint.rs:L73-L78; DOC: spec §10.3, DB-79]. The genesis checkpoint is NOT cosigned (auditor skips witness check at index 0) [CODE: audit/src/audit.rs:L367-L369].
- Certificate's checkpoint choice: the latest witnessed checkpoint with `tree_size > insert_leaf_index` [CODE: participant.rs:L368-L378 (inside `prepare_delete`)]. If a delete finds the freshly issued on-demand checkpoint not witnessed by 4 → `IntegrityViolation("§10.4 witnesses")` and abort [CODE: participant.rs:L240-L248].

### 6.4 Witnesses
- Count 5, threshold 4 [CODE: checkpoint.rs:L13-L17: `WITNESSES: u8 = 5`, `THRESHOLD: usize = 4` (SB-20 sets 3)].
- A witness remembers the last checkpoint it cosigned (starting from genesis), requires an RFC 9162 consistency proof from it, verifies, and only then cosigns [CODE: crates/sever-log/src/witness.rs:L28-L66 `Witness` trait (EP-10) + `extends`; L121-L148 `SimulatedWitness::cosign`]. Rules in `extends`: shrink → `Shrunk`; same size different root → `Fork`; `last.tree_size == 0` → accepted without proof (RFC 9162 proofs need 0 < first); else `verify_consistency` or `Inconsistent`. Also checks the new checkpoint's operator signature first (`OperatorSignature`).
- Cosignature = `u8 witness_index ‖ u32be witness_epoch ‖ signature(64)` = 69 B [CODE: checkpoint.rs:L24-L26, L128-L172]; signature over `DST_COSIGN ‖ checkpoint_message(66)` = 83 B [CODE: sig.rs:L92-L97].
- A checkpoint is *witnessed* iff ≥ 4 valid cosignatures from DISTINCT witness indices each verified under that witness's key for its stated epoch [CODE: checkpoint.rs:L174-L190 `is_witnessed`; verifier verify.rs:L170-L186 uses `BTreeSet` of indices].
- In v1 witnesses are SIMULATED by the project, in-process, all five keys on the same machine [DOC: spec §9.8 "In v1 the five witnesses are simulated by the project, and their keys live in the test harness"; §10.4; limit L-7]. [CODE: crates/sever-p3/src/witnesses.rs:L1-L9, L130-L200] Concretely: `SimWitness` wraps `SimulatedWitness`; keys by epoch and last checkpoint are persisted in a single `WITNESSES` file in the **key directory**; layout `magic "SVDBWITN" ‖ u16be 1 ‖ u64be genesis_ms ‖ u8 count ‖ count × (u8 index ‖ last checkpoint(116) ‖ u32be n ‖ n × (u32be epoch ‖ secret 32)) ‖ SHA-256(all preceding)` [CODE: witnesses.rs:L7-L9, L57-L75]. So "witness" secrets sit beside the operator's secrets; no independence in v1. [INFERRED: this means the 4-of-5 threshold gives zero independent-witness guarantee in v1; the spec says so explicitly.]
- Witness key origin: each witness creates its epoch-0 key at database creation from 32 OS bytes (G-37 / DB-99) and records it in `WITNESSES` before use; later-epoch keys are created at first cosign in that epoch [CODE: witnesses.rs:L170-L200, L226-L245 (`os_secret` via keys.rs:L29-L34)].
- The EP-10 contract suite (`ep10_contract`) tests that a witness cosigns honest growth and refuses fork, shrink and bad operator signature [CODE: witness.rs:L171-L238]; gate P3-T12.

### 6.5 Operator and user keys
- Operator: Ed25519, **90-day epochs** counted from database genesis: `epoch = floor((t − genesis)/ (90 d in ms))`, `None` before genesis [CODE: sig.rs:L18, L115-L121 `epoch_of`; `EPOCH_MS = 90·24·60·60·1000`].
- Operator secret per epoch: 32 OS bytes drawn at first use, written durably to `SECRETS` (kinds `K_OPERATOR_KEY = 2`: `u32be epoch ‖ secret(32)`; `K_GENESIS_MS = 3`: `u64be ms`) BEFORE its first signature, so a restart cannot create a second key for an already-used epoch [CODE: crates/sever-p3/src/keys.rs:L1-L5, L18-L21, L172-L189].
- Old public keys remain resolvable forever (Keyring is append-only; `insert` refuses a conflicting key for an epoch) [CODE: crates/sever-log/src/keys.rs:L9-L35].
- Key-directory file `SECRETS` has mode 0600 on POSIX [CODE: crates/sever-p3/src/lib.rs:L505-L514 `secrets_0600`] (Part 3 stores it plaintext; Part 4 seals).
- User/account key: Ed25519 per account, held by the application backend, never rotates; its public key is published in the insert leaf [DOC: spec §3.3, §9.8].
- All signature verifications use `verify_strict` (rejects small-order keys / non-canonical `R`,`S`) [CODE: sig.rs:L56-L63; verifier/src/verify.rs:L55-L59; audit copy identical].

---------------------------------------------------------------------------------------------------

## 7. Deletion certificate (byte level) and verifier steps

### 7.1 Format (spec §11.1) [CODE: crates/sever-cert/src/encoding.rs:L216-L253 `body`/`to_bytes`; L259-L308 `parse`]
```
for tag = 1 … 13, ascending, each exactly once:   u8 tag ‖ u32be length ‖ value
trailer:                                          u8 0xFF ‖ u32be 64 ‖ operator_signature (64)
operator_signature = Ed25519( DST_CERT ‖ all preceding bytes )    (sig.rs:L99-L106 certificate_message)
```
| Tag | Field | Value / size | Notes [CODE] |
|---|---|---|---|
| 1 | commitment_to_deleted_vector | `C_t`, 32 | encoding.rs:L221 |
| 2 | group_commitment_before | `C_S_pre`, 32 (empty for holding-area deletion) | L222; `optional_point` L202-L208 |
| 3 | group_commitment_after | `C_S_post`, 32 (empty for holding-area deletion) | L223 |
| 4 | posk_proof | `A ‖ z_r ‖ z_0…z_{d-1}` = 32(d+2) bytes = 12,352 at d=384 (empty for holding) | L224; length check L273-L275 |
| 5 | user_authorisation_signature | user's insert signature, 64 | L225 |
| 6 | insert_inclusion | nested (below) | L226 |
| 7 | witness_cosignatures | `u8 count ‖ count × (u8 index ‖ u32be witness_epoch ‖ sig 64)` (69 B each) | L227-L232; parse L311-L321 |
| 8 | key_period | `u32be` operator epoch signing the certificate | L233 |
| 9 | scrambled_record_id | 64 | L234 |
| 10 | database_lsn | `u64be`, this deletion's own leaf index | L235 |
| 11 | group_emptied_by_this_deletion | `u8` 0 or 1 | L236 |
| 12 | deletion_kind | `u8` 0 = from a group, 1 = from the holding area | L237 |
| 13 | collection_id | 16 | L238 |
| 0xFF | trailer | `0xFF ‖ u32be 64 ‖ sig(64)` = 69 B | L11-L13, L248-L253 |

- Tag 6 (`insert_inclusion`, spec §11.2) [CODE: encoding.rs:L48-L111]: `u8 version=1 ‖ insert_leaf(209) ‖ u64be leaf_index ‖ checkpoint(116: u64be tree_size ‖ root(32) ‖ u64be timestamp_ms ‖ u32be epoch ‖ operator_signature(64)) ‖ u8 path_len ‖ path_len × 32-byte hashes`. Fixed part = 1+209+8+116+1 = 335 bytes; path ≤ 255 hashes (`u8`).
- Parser rejects: missing/repeated/out-of-order tags; wrong fixed length; tags 11/12 ∉ {0,1}; tag-6 version ≠ 1, non-insert leaf type, wrong inner lengths; tags 2–4 inconsistent with kind (`ParseError::Kind`: group deletion must carry all of 2,3,4; holding must carry none and tag 11 = 0); trailing bytes [CODE: encoding.rs:L15-L46, L259-L308]. The verifier's own parser does the same with string reasons [CODE: verifier/src/cert.rs:L187-L239].
- Sizes: group deletion at d=384 ≈ 14.1 KB predicted [DOC: spec Appendix A / §11.1]; measured min 1,197 B (holding), max 13,645 B (20 deletions, nq-10k), predicted 14,093 [DOC: results/p3-measures-nq-10k-20261030T232049Z.json "P3-T13", a measure not a gate]; proof time median ≈ 15.8 ms, verify ≈ 2.7 ms (same file).
- Certificate issuance (builder) order [CODE: crates/sever-cert/src/builder.rs:L80-L167 `build`]: (1) verify inclusion path of the insert leaf under the checkpoint (≤255 hashes); (2) checkpoint operator sig; (3) ≥4 distinct cosignatures; (4) `database_lsn > leaf_index`; (5) `key_period = epoch_at(now)`; (6) for group: decode `C_S_pre`, `C_t` (non-identity), `C_S_post = commit_group(S_post, r_post)`, `transition_holds` else `TransitionBroken`, build `DeletionContext`, `prove(...)` with `StrictProofRng`, `emptied = (n_post == 0)` (SB-22 sets `n_post <= 1`); (7) tags 1,5,9,13 are copied from the insert leaf so they always agree; (8) operator signs `certificate_message(body)` with key of `key_period`. The builder refuses to sign anything a verifier would reject (apart from the proof itself).
- Where the certificate is built in the engine: inside the delete transaction's `prepare` of `LogParticipant`, one certificate per deleted record, tracking the group state step by step so multi-record deletions chain [CODE: crates/sever-cert/src/participant.rs:L324-L470]. Randomness there: `StrictProofRng::new()` [CODE: participant.rs:L437].
- Atomicity: the delete leaf + certificate are staged in the transaction and only become durable with the COMMIT; SB-21 breaks that by syncing before commit [CODE: crates/sever-p3/src/lib.rs:L156-L167].

### 7.2 Verifier algorithm (spec §11.3), exact step numbers in `verifier/src/verify.rs`
Inputs: certificate bytes, anchors, generators of `anchors.d`. A rejection is `Rejection{step, reason}` with a fixed `&'static str` reason, no input bytes. Success returns `Accepted{...}`. The CLI prints step as JSON or with `--explain` lists the 8 labelled steps [CODE: verifier/src/main.rs:L25-L56].

| Step | Check | Code | Failure reasons (step number, string) |
|---|---|---|---|
| pre | generators' dimension equals anchors' `d` | verify.rs:L76-L82 | step 1: "the generators are not of the anchors' dimension" |
| 1 | Strict parse (§11.1), canonical decode of every point/scalar, `C_t` ≠ identity | verify.rs:L83-L104; cert.rs:L187-L239 | step 1 with: "a tag is missing, repeated or out of order", "a tag is missing", "tag N length is not …", "tag 11 is not one byte 0 or 1" (tag 12 likewise), "tag 6 version is not 1", "tag 6 truncated", "tag 6 has trailing bytes", "tag 7 length is not 1 + 69 × count", "tag 4 length is not 32 + 32 + 32·d", "the trailer is missing…", "the trailer's length is not 64", "trailing bytes after the trailer", "C_t is not a canonical point", "C_S_pre/C_S_post is not a canonical point", "the proof holds a non-canonical point or scalar", "C_t is the identity" |
| 2 | Operator signature: key for tag 8's epoch must exist in anchors; `verify_strict` over `DST_CERT ‖ body` | verify.rs:L105-L112 | step 2: "unknown operator epoch"; "the operator signature does not verify" |
| 3 | Insert inclusion: leaf type 0x01; leaf's collection_id, scrambled_id, C_t, user_signature equal tags 13, 9, 1, 5; user signature verifies under the leaf's user key over `DST_INSERT ‖ collection_id ‖ C_t`; RFC 9162 inclusion path to checkpoint root; checkpoint operator signature under its own epoch's key | verify.rs:L113-L169 | step 3: "the leaf is not an insert leaf"; "the leaf's fields differ from tags 13, 9, 1 and 5"; "the leaf is truncated"; "the user signature does not verify"; "the inclusion path does not lead to the checkpoint's root"; "the checkpoint's operator epoch is unknown"; "the checkpoint's operator signature does not verify" |
| 4 | Witnesses: ≥ 4 DISTINCT witness indices with valid cosignature under key `(witness_index, witness_epoch)` in anchors, over `DST_COSIGN ‖ checkpoint message` | verify.rs:L170-L186 (`THRESHOLD = 4` L17) | step 4: "fewer than four distinct valid cosignatures" |
| 5 | Ordering: `database_lsn > leaf_index` | verify.rs:L187-L190 | step 5: "database_lsn is not after the insert leaf" |
| 6 (kind 0, group) | needs tags 2,3,4; `C_S_post + C_t == C_S_pre`; proof verifies with ctx = `C_S_pre ‖ C_t ‖ scrambled_id ‖ u64be lsn ‖ collection_id`; `(tag11==1) == (C_S_post == identity)` | verify.rs:L191-L215 | step 6: "a group deletion needs tags 2, 3 and 4"; "C_S_post + C_t differs from C_S_pre"; "the proof of knowledge does not verify"; "group_emptied disagrees with C_S_post" |
| 7 (kind 1, holding) | tags 2,3,4 empty, tag 11 = 0 | verify.rs:L216-L227 | step 7: "a holding-area certificate carries tags 2, 3 or 4"; "a holding-area certificate has tag 11 = 1" |
| 8 | accept | verify.rs:L229-L238 | — |
Note: any `deletion_kind` other than 0 falls into the `_` arm (step 7) [CODE: verify.rs:L191, L217], but the parser already restricts tag 12 to {0,1} (cert.rs:L133-L138).
- `--explain` labels steps 1..8 as: parse; operator signature; insert leaf/user sig/path/checkpoint sig; four cosignatures; lsn ordering; group arithmetic; holding area; "every step passed" [CODE: verifier/src/main.rs:L26-L35].
- Exit codes: 0 accepted, 1 rejected (names step), 2 usage, 3 self-check or anchors refused [CODE: verifier/src/main.rs:L1-L8; DOC: spec §16.3].
- What is NOT checked by the verifier (by design): that the deletion leaf is in the log at `database_lsn`; consecutive-certificate chaining; log consistency across checkpoints → auditor's job [DOC: spec §11.3 "What it does not prove"].
- Not verified by the verifier either: any timestamp bounds / expiry; the checkpoint's `timestamp_ms` is signed but not compared to anything. [INFERRED: no `timestamp` comparison in verify.rs (read in full).]
- Forward limit: anchors fixed at release cannot verify certificates under later operator epochs [DOC: spec §11.3].

### 7.3 Trust anchors file (JSON) [DOC: spec §11.3, DB-85; CODE: crates/sever-p3/src/lib.rs:L100-L140 `Anchors::to_json`; verifier/src/anchors.rs:L1-L82]
```json
{"d": 384,
 "gdigest": "<128 hex>",
 "operator":  {"0": "<64 hex ed25519 pubkey>", "1": "..."},
 "witnesses": [ {"0": "<64 hex>"}, {"0": "<64 hex>"}, {"0": "<64 hex>"}, {"0": "<64 hex>"}, {"0": "<64 hex>"} ]}
```
- `witnesses` is a list indexed by witness number; each entry maps epoch → key. Verifier flattens to `BTreeMap<(u8 index, u32 epoch), key>` [CODE: anchors.rs:L64-L74]. `gdigest` optional at parse (`Option`) but if present must equal the verifier's own derivation [CODE: anchors.rs:L52-L59; main.rs:L148-L150].
- Epoch-0 keys of operator and all five witnesses are listed from database creation (G-37/DB-99); later-epoch keys are listed from first use [DOC: spec §11.3].
- The generator golden file is compiled into the verifier (not in the anchors JSON): it is a trust anchor in the spec's sense (DB-79) [CODE: verifier/src/gens.rs:L12-L16].
- Produced by `sever-db-p3 anchors` [CODE: crates/sever-p3/src/bin/sever-db-p3.rs `"anchors" =>` branch].

---------------------------------------------------------------------------------------------------

## 8. Independence of verifier/ and audit/ from crates/

Evidence gathered (read-only):
- `verifier/Cargo.toml` has `[workspace]` (own workspace), own `Cargo.lock`; `[dependencies]` = curve25519-dalek `=4.1.3`, sha2 `=0.10.9`, ed25519-dalek `=2.2.0`, serde_json `1` — no `path =` dependencies [CODE: verifier/Cargo.toml:L12, L24-L28].
- The ONE path dependency is a **dev-dependency** `sever-spec = { path = "../crates/sever-spec" }` — described as "Test labels only (#[spec("SR-…")]): a no-op attribute, no verification code (DB-85)" [CODE: verifier/Cargo.toml:L29-L31]. `sever-spec` is a proc-macro crate whose `#[spec]` attribute returns the item unchanged (it only validates the `"SR-<section>-<n>"` string form) [CODE: crates/sever-spec/src/lib.rs:L1-L32, crates/sever-spec/Cargo.toml `proc-macro = true`]. So the verifier's production build has zero engine code. [DOC mismatch: Build 3-4 §1.6 says "no path dependencies", see mismatches list.]
- `verifier/Cargo.lock` lists `sever-spec` and `sever-verify` as the only `sever-*` packages [CODE: verifier/Cargo.lock:L262-L272 per grep].
- `grep -rn 'include!|#\[path|sever_crypto|sever_cert|sever_log|sever-crypto…'` over `verifier/src`, `audit/src`, fuzz manifests: no hits except harmless words "path" and the fuzz crates' own path to the sibling crate (`verifier/fuzz` → `..`, `audit/fuzz` → `..`). No `include!()` of engine source.
- Data (not code) shared by `include_str!`: golden files `golden/p3_generators.json`, `p3_rfc9496_ristretto255.json`, `p3_rfc9380_k3_expand_xmd_sha512.json` (compiled into verifier/audit [CODE: verifier/src/gens.rs:L12-L16]); tests include `golden/p3_certificates.json`, `p3_attacks.json`, `p3_merkle_7.json`, `p3_audit.json` and `spec/registers_p3.yaml` [CODE: verifier/src/tests.rs:L18-L21; audit/src/tests.rs:L15-L16]. The goldens are written by the Python reference model, not by the Rust engine [CODE: golden files' `"source"` field = `sever_refmodel_certs…`].
- `audit/Cargo.toml`: own `[workspace]`; same three crates; dev-dep `sever-spec` only; comment "copies nine of the verifier's files into src/ (kept identical by tests/architecture) and depends on neither the verifier nor the engine" [CODE: audit/Cargo.toml:L1-L10, L24-L31].
- Byte-identical check performed with `cmp verifier/src/X.rs audit/src/X.rs`: `anchors, cert, dst, gens, hex, merkle, posk, verify, xmd` — all 9 identical [CODE: cmp output, this session].
- Architecture tests enforce this: `test_p3_arch_verifier_shares_no_code_with_the_engine` (checks own workspace, lockfile names, no engine imports in `verifier/src`) and `test_p3_arch_auditor_copies_the_verifier_and_depends_on_neither` (byte-identity of copied files; lockfile; `use` set ⊆ `{sever_audit, sever_spec}`) [CODE: tests/architecture/test_architecture_p3.py:L52-L106].
- Reference model (`python/sever_refmodel_certs`) uses only the Python standard library and its own ristretto255, Ed25519, XMD, Merkle (no binding to the engine) [CODE: python/sever_refmodel_certs/__init__.py:L1-L9; ristretto.py:L1-L4; ed25519.py:L1-L9].
- Shared *dependencies* are not shared *code*: both workspaces use the same upstream curve25519-dalek 4.1.3 / sha2 / ed25519-dalek. A bug in dalek would be common-mode. [INFERRED from Cargo manifests; the Build plan §1.6 requires "cargo tree must show exactly curve25519-dalek 4.1.3 in both workspaces".]
- Tool-chain/compile-level: Rust 1.98.1, `unsafe_code = "forbid"`, clippy denies `unwrap/expect/panic/indexing_slicing` in verifier & audit [CODE: verifier/Cargo.toml:L33-L42].

---------------------------------------------------------------------------------------------------

## 9. sever-audit: what it checks on a log export

Export (DB-86): JSON `{"version":1,"leaves":[hex],"placements":[{"group","flush"}],"checkpoints":[hex]}`; each checkpoint entry = `checkpoint(116) ‖ u8 count ‖ count × cosignature(69)` [CODE: audit/src/audit.rs:L51-L102; engine side crates/sever-p3/src/lib.rs:L377-L396 `export_log`]. CLI: `sever-audit <log export> --anchors FILE [--certificate FILE]…`; exit 0 none, 1 findings, 2 usage, 3 refused [DOC: spec §16.3; CODE: audit/src/main.rs].

Checks in `audit()` [CODE: audit/src/audit.rs:L256-L429]:
1. Counts: placements count equals leaves count ("leaf" finding).
2. Replay inserts: per `(collection_id, group)` a map `scrambled_id → C_t`; a flush (placement.flush set) moves all holding-area members plus the new record into the created spawned group (§15.2) (L280-L317).
3. For each delete leaf (`0x02 ‖ cert`): run the full verifier `verify()` (finding `certificate`); require `database_lsn == leaf index` (**AF-1**, L329-L335); the deleted record (scrambled_id, C_t) must be a member of the group it left (**AF-2**, L339-L340); for a group deletion, `C_S_pre` must equal the sum of the members' `C_t` (L341-L344: `sum(group) != c.c_s_pre`, **AF-2**); a holding-area certificate must refer to the holding area and vice versa (L345-L347); remove the member (L348).
4. For each checkpoint: well-formed; operator signature under its epoch's key (finding "checkpoint"); for `j > 0` ≥ 4 distinct valid cosignatures (genesis is not cosigned); `tree_size` ≤ leaves in export (**AF-1** "covers leaves the export lacks"); `root` equals RFC 9162 MTH of the first `tree_size` leaf hashes (**AF-5**); one root per tree size (**AF-3**); consistency with the previous checkpoint using a proof *computed from the leaves* and verified with the RFC 9162 §2.1.4.2 algorithm (**AF-3**) (L350-L412).
5. Certificates users hold (`--certificate`): leaf at the cert's `database_lsn` must equal `0x02 ‖ cert` (**AF-4**) (L413-L427).
- Not checked by the auditor [INFERRED from reading audit.rs in full]: the insert-leaf user signature inside the export itself (only inside each certificate via the verifier), timestamps' monotonicity, that an insert leaf's `C_t` is non-identity, duplicate scrambled_ids across inserts (map insertion overwrites silently), and chaining by *previous certificate's `C_S_post`* explicitly — instead it recomputes `C_S_pre` as the sum of members' `C_t` (so chain correctness is verified via replay, inserts in between included) [DOC: spec §11.3 export paragraph].
- Findings kinds: `AF-1` … `AF-5`, `leaf`, `certificate`, `checkpoint` [CODE: audit.rs:L30-L39].
- Faults register AF-1…AF-5: `spec/registers_p3.yaml` `faults:` (see §12); golden `golden/p3_audit.json` (honest export + one export per fault) produced by `python/sever_refmodel_certs/audit.py`.

---------------------------------------------------------------------------------------------------

## 10. G-34 / DB-95: emptied-group proof replay

- Finding [DOC: docs/SPEC_GAPS.md G-34 (row at L41)]: spec §9.5 said a proof "cannot be replayed in another certificate", but when `C_S_post` is the identity (group emptied) the verification equation reduces to `z_r·H + Σ z_i·G_i = A` for *every* challenge, so the challenge (and with it the bound context) has no effect; one emptied certificate's proof verifies in any other emptied certificate. Found by an interim P3-T2 run (19 Oct 2026): AT-2 ("proof copied from another certificate") copied an emptied certificate's proof into the next emptied one and the verifier accepted it (seeds 777 and 9999; 3 of ≈900 instances).
- Mathematical reason [INFERRED, checks with equation in posk.rs:L194]: with `C_S_post = O`, `A + c·O = A`, so the accepting condition no longer depends on `c`; any honest-looking proof of the identity (e.g. `s=0, r=0`, any nonces) is valid regardless of ctx.
- Why nothing false is certified [DOC: G-34, spec §9.5]: step 6 still checks `C_S_post + C_t = C_S_pre` (so `C_S_pre = C_t`: the group contained only this record), tag 11 must be 1 iff `C_S_post` is the identity, and the operator's signature covers every tag including ctx-bearing fields. The proof of an empty group's opening shows only what everyone knows (opening is all zeros, §5.4).
- Resolution: **DB-95** (19 Oct 2026) [DOC: docs/SEVER-DB_PROJECT_OVERVIEW.md L1487-L1500]: (1) spec §9.5 now states the exception explicitly (spec "Binding the context into the challenge" paragraph); (2) the attack generators (`sever-crashkit-p3`, `sever-crashkit-p4`) take the donor certificate for AT-2, AT-3, AT-13 from group certificates that do NOT empty their group, so every AT-2 instance swaps in a proof that really cannot verify; (3) P3-T2 reran. Rejected: a special proof form for the identity (format change for no security gain) and dropping AT-2 on emptied certificates.
- [CODE: crates/sever-crashkit-p3/src/attacks.rs:L339-L350] `donor` closure: `get(&t,12) == [0] && get(&t,11) == [0]` (group deletion, not emptied); used for `first_group` and `other`.
- No change to verifier or proof code was made. [INFERRED: verifier/src/posk.rs unchanged — it implements exactly the equation in the spec.]
- Test coverage: no unit test labelled G-34/DB-95 was found [NOT FOUND: grep for `G-34|DB-95` in crates/, verifier/, audit/, python/, tests/ outside cleanroom returned only attacks.rs files]. Relevant executable evidence: the golden file contains an honest *emptied* certificate (`honest.emptied`) that the verifier must accept [CODE: python/sever_refmodel_certs/attacks.py:L218-L224, L248; verifier/src/tests.rs:L111-L113 asserts `group_emptied`], the attack run `p3-attacks` (nq-10k, 5 seeds, 1000 certs each, ≈45,282 attacks per seed) PASS recorded 2026-11-01 commit `94d0b24` [DOC: docs/RESULTS.md L61; results/p3-attacks-nq-10k-20261101T085746Z.json: AT-2 899/899 rejected etc.], and AT-14 (tag 11 inconsistent with C_S_post; includes the emptied-with-flag-0 variant) [CODE: attacks.py:L227-L229].
- Related-but-different gaps: G-37 (witness epoch-0 keys listed in anchors, DB-99), G-41 (error naming, DB-101), G-50 (consistency proofs only for 0<m<n, DB-116), G-38 (placement text form) [DOC: docs/SPEC_GAPS.md L44-L57].

---------------------------------------------------------------------------------------------------

## 11. Sabotage items SB-16 … SB-23 (each built from the same source with feature `sabotage-SB-N`, one deliberate bug)

Runner: `tests/sabotage/run.sh` builds `cargo test -p <crate> --features sabotage-SB-N` and requires a failing test [CODE: tests/sabotage/run.sh:L1-L60; Part 3 block lists `for sb in SB-16 SB-17 SB-18 SB-19 SB-23; do rust "$sb" sever-crypto; done; rust SB-20 sever-log; rust SB-22 sever-cert; rust SB-21 sever-p3`]. Features declared in crate manifests [CODE: sever-crypto/Cargo.toml:L8-L13; sever-log/Cargo.toml:L11-L13; sever-cert/Cargo.toml:L9-L10; sever-p3/Cargo.toml:L10-L11].

| ID | Crate | Where | What it breaks | Caught by (register `caught_by`) |
|---|---|---|---|---|
| SB-16 | sever-crypto | posk.rs:L60-L69 | Challenge preimage order: hashes `A` before `C_S_post` | golden vector 3 (challenge differs) |
| SB-17 | sever-crypto | posk.rs:L70-L73 | Deletion context left out of the challenge (`let _ = ctx;`) | golden vector 3; proof for one ctx rejected under another |
| SB-18 | sever-crypto | nonce.rs:L91-L112 (`NoEntropy`), L159-L162 | Proof nonces derived with a zero-entropy source → same statement ⇒ same `A` (nonce reuse) | two proofs of the same statement must have different `A`; compile-fail test for seedable RNG |
| SB-19 | sever-crypto | group.rs:L43-L47 | `decode_scalar` reduces (`from_bytes_mod_order`) instead of rejecting scalars ≥ ℓ | canonical-decoding tests with RFC 9496 non-canonical encodings and scalars ≥ ℓ |
| SB-20 | sever-log | checkpoint.rs:L16-L20 | Witness threshold 3 instead of 4 | a checkpoint with three valid cosignatures must not be witnessed |
| SB-21 | sever-p3 | lib.rs:L156-L167 | In `prepare` of a Delete, calls `sync_stores` and `after_commit` BEFORE the COMMIT ⇒ certificate/leaf durable for a rolled-back deletion | crash before COMMIT leaves no certificate and no delete leaf (test comment at crates/sever-p3/src/tests.rs:L413) |
| SB-22 | sever-cert | builder.rs:L140-L143 | `group_emptied` set when `n_post <= 1` instead of `== 0` | deleting last member gives tag 11=1, others 0; honest certificate verifies |
| SB-23 | sever-crypto | posk.rs:L75-L83 | Challenge reduced from first 32 bytes of the SHA-512 output (`from_bytes_mod_order`) instead of 64 (`from_bytes_mod_order_wide`) | golden vector 3 |
- Doc-vs-code detail: SB-19 is documented as "accept a non-canonical point **or** scalar" (spec/registers_p3.yaml) but the code sabotages only `decode_scalar`; point decoding (`decode_point`, group.rs:L28-L34) is not altered under the feature. [CODE: group.rs:L40-L48]
- Proof manifest for "red proofs": `tests/proofs/p3/MANIFEST.yaml` (1,799 lines; patches `PR3-*.patch`) – each (test,label) pair needs a patch that turns the labelled tests red [CODE: tests/proofs/p3/MANIFEST.yaml:L1-L10; DOC: CLAUDE.md §6.3].
- Result record: `p3-checks` (includes P3-T9 sabotage) PASS 2026-11-01, commit `94d0b24` [DOC: docs/RESULTS.md L64].

---------------------------------------------------------------------------------------------------

## 12. Attack register AT-1 … AT-20 and fault register AF-1 … AF-5 (`spec/registers_p3.yaml`)

Method [CODE: spec/registers_p3.yaml:L4-L11]: the attacker is a dishonest operator who holds the operator key. `resign: true` means the attack certificate is re-signed with the operator's key so the targeted rule is reached rather than failing at the trailer; `steps` are the §11.3 steps that may reject it; the suite checks the verifier's rejection step is one of them. AT-4 alone is NOT re-signed (shows the trailer covers every field). Executed by `sever-crashkit-p3 attacks` (honest + attack certificates) judged by the independent verifier; gate P3-T2 [CODE: crates/sever-crashkit-p3/src/attacks.rs; main.rs doc header]. The reference model (`python/sever_refmodel_certs/attacks.py`) produced `golden/p3_attacks.json` with `model_step` for each variant.

| ID | Description (register text) | resign | Allowed verifier steps | Golden `model_step`/reason per variant (golden/p3_attacks.json) | Requirements |
|---|---|---|---|---|---|
| AT-1 | A forged proof | yes | 6 | v0,v1: 6 "proof of knowledge" | SR-9.5-6, SR-11.3-6 |
| AT-2 | A proof copied from another certificate | yes | 6 | v0: 6 | SR-9.5-1, 9.5-3, 11.3-6 |
| AT-3 | A substituted C_t | yes | 3, 6 | v0: 3 "leaf fields differ from tags 13, 9, 1, 5" | SR-9.3-2, 11.3-3, 11.3-6 |
| AT-4 | Each single-field tamper: tags 1–13 and the trailer (14 variants) | NO | 1, 2 | v0-3: 1 non-canonical encoding; v5: 1 insert_inclusion version; v6: 1 tag 7 length; v4,v8-v13: 2 operator signature; v7: 2 unknown operator epoch | SR-9.8-4, 11.1-1, 11.3-2 |
| AT-5 | A certificate under an unknown operator epoch | yes | 2 | 2 "unknown operator epoch" | SR-9.8-5, 11.3-2 |
| AT-6 | An insert leaf from another collection | yes | 3 | 3 | SR-11.3-3 |
| AT-7 | A wrong inclusion path | yes | 3 | v0,v1: 3 "inclusion path" | SR-10.1-2, 11.3-3 |
| AT-8 | A log checkpoint signed by the wrong key | yes | 3 | 3 "checkpoint signature" | SR-9.8-2, 11.3-3 |
| AT-9 | Three instead of four cosignatures | yes | 4 | 4 "3 distinct valid cosignatures" | SR-10.4-2, 11.3-4 |
| AT-10 | Cosignatures over a different log checkpoint | yes | 4 | v0,v1: 4 "0 distinct valid" | SR-9.8-3, 11.3-4 |
| AT-11 | A non-canonical point or scalar | yes | 1 | v0-2: 1 | SR-9.9-1, 11.3-1 |
| AT-12 | The identity as C_t | yes | 1 | 1 "C_t is the identity" | SR-9.9-2, 11.3-1 |
| AT-13 | A holding-area certificate carrying arithmetic fields (tags 2–4 non-empty, or tag 11 = 1) | yes | 7 | v0-3: 7 | SR-11.3-7 |
| AT-14 | `group_emptied_by_this_deletion` inconsistent with `C_S_post` | yes | 6 | v0,v1: 6 "group_emptied disagrees with C_S_post" | SR-11.3-6 |
| AT-15 | `database_lsn` not after the insert leaf | yes | 5 | v0,v1: 5 | SR-11.3-5 |
| AT-16 | Malformed TLV: missing, repeated or reordered tag, or trailing bytes | yes | 1 | v0-4: 1 (tag 6 where 5 belongs; 5 where 6; 5 where 4; trailing bytes; truncated) | SR-11.1-2, 11.3-1 |
| AT-17 | Four cosignatures where two come from the same witness | yes | 4 | v0: 4 (3 distinct); v1: 4 (2 distinct) | SR-11.3-4 |
| AT-18 | Fixed-size field with wrong length, or tag 11/12 outside {0,1} | yes | 1 | v0-5: 1 (tag 9 len, tag 11 value, tag 12 value, tag 1 len, tag 10 len, trailer len) | SR-11.1-2, 11.1-3 |
| AT-19 | Insert leaf whose type is not 0x01, or insert_inclusion version ≠ 1 | yes | 1, 3 | v0: 3 "leaf type"; v1: 1 "insert_inclusion version" | SR-11.2-1, 11.3-3 |
| AT-20 | Log checkpoint or cosignature under an epoch or witness index not in the anchors | yes | 3, 4 | v0: 3 (checkpoint sig); v1,v2: 4 (3 distinct) | SR-11.3-3, 11.3-4 |

- Attack counts per seed in the latest gate PASS (1000 certificates each; 45,282 attacks/seed): AT-1 1798, AT-2 899, AT-3 1000, AT-4 12586, AT-5 1000, AT-6 1000, AT-7 1999, AT-8 1000, AT-9 1000, AT-10 1000, AT-11 1798, AT-12 1000, AT-13 303, AT-14 899, AT-15 1000, AT-16 5000, AT-17 1000, AT-18 6000, AT-19 2000, AT-20 3000; all rejected; honest 1000/1000 accepted [DOC: results/p3-attacks-nq-10k-20261101T085746Z.json, seed 42 shown; seeds 42, 123, 777, 2024, 9999 PASS per docs/RESULTS.md L61]. The AT-2 (899) and AT-13 (303) counts are lower because donors exclude emptied certificates (DB-95). [INFERRED: counts below 1000 for AT-2/AT-13/AT-14 reflect which certificate kinds an attack applies to.]
- Faults (auditor; gate P3-T6) [CODE: spec/registers_p3.yaml:L38-L43]:
  - AF-1 a skipped deletion leaf → auditor finding on `database_lsn ≠ leaf index` or checkpoint covering missing leaves [CODE: audit.rs:L329-L335, L386];
  - AF-2 a broken chain (`C_S_pre` ≠ the previous `C_S_post`, here checked as replayed sum of members) [CODE: audit.rs:L336-L348];
  - AF-3 two checkpoints not consistent (forked log) [CODE: audit.rs:L392-L410];
  - AF-4 a leaf at `database_lsn` that does not match its certificate [CODE: audit.rs:L413-L427];
  - AF-5 a checkpoint root not matching the tree at its size [CODE: audit.rs:L387-L389].

---------------------------------------------------------------------------------------------------

## 13. Randomness in Part 3 and the "no seed" rules

Sources of entropy (all OS CSPRNG via `rand_core::OsRng`, i.e. getrandom):
| Secret/value | Source | Code |
|---|---|---|
| `r_t` (64 bytes, reduced wide) | `OsRng` in the SDK `prepare_insert` | crates/sever-py-p3/src/lib.rs:L294-L296 |
| User (account) Ed25519 key | `OsRng` 32 B | sever-py-p3 lib.rs:L139-L141, L179; crates/sever-crypto/src/sig.rs:L26-L33 |
| Operator epoch key | `os_secret()` = `OsRng` 32 B, durable before first use | crates/sever-p3/src/keys.rs:L29-L34, L172-L189 |
| Witness epoch keys (5 witnesses) | `os_secret()`; epoch-0 at database creation | crates/sever-p3/src/witnesses.rs:L170-L200, L226-L245 |
| Proof nonces | Merlin-hedged: witness + statement + 32 B `OsRng` through `StrictProofRng` | crates/sever-crypto/src/nonce.rs:L56-L147 |
| `k_scramble`, `collection_id` | OS CSPRNG (Part 1/2 code; consumed here) | [DOC: spec §9.7, §3.1] |
- Rule: "Never pass a seed into proof or key generation" [DOC: CLAUDE.md §6.2 Seeds]. The five overview seeds are only for data order, synthetic data and k-means.
- Enforcement mechanisms:
  1. `StrictProofRng` is a zero-sized wrapper of `OsRng` with only `RngCore + CryptoRng`; no `SeedableRng`, no constructor taking a seed; `prove()` takes `&mut StrictProofRng` concretely. Three doctests: one `compile_fail` passing a seedable RNG, one passing example, one `compile_fail` asserting `StrictProofRng` is not `SeedableRng` [CODE: nonce.rs:L22-L66, L150-L158].
  2. `hedged_nonces` is `pub(crate)` and generic only so that tests can supply a fixed source [CODE: nonce.rs:L117-L123]; `prove_with_nonces` is `pub(crate)` ("Only the hedged prover may call it outside tests") [CODE: posk.rs:L128-L131].
  3. Python SDK: no randomness arguments; any extra arg → `SeededNonceForbidden` [CODE: python/sever_db_p3/__init__.py:L91-L95]; Rust module doc "No function takes a generator, seed or nonce" [CODE: sever-py-p3 lib.rs:L10-L12]; `Error::SeededNonceForbidden` mapped to a Python exception [CODE: sever-py-p3 lib.rs:L93, L123].
  4. SB-18 proves a test would detect nonce reuse (§11).
- Test-only exception: golden proof vector 3 and the extractor/simulator tests use fixed nonces via `prove_with_nonces` inside the crate; this is crate-internal and not exposed [INFERRED from visibility `pub(crate)`; golden file `p3_posk.json` produced by the Python reference model which takes explicit nonces (`posk.prove(..., nonces)` in python/sever_refmodel_certs/posk.py).]
- Time/clock: certificate epoch and checkpoint timestamps come from the engine `Clock` (EP-9) [CODE: participant.rs:L219, L352]; `SimClock` in tests.

---------------------------------------------------------------------------------------------------

## 14. Engine integration points (so the cryptography can be located in the running system)

- Composition root: `Engine<CommitmentExtension, PlaintextSealer, (LogParticipant)>` [CODE: crates/sever-p3/src/lib.rs:L197-L234 `open_on`; Cargo description]. Order at open: derive generators → `self_check` (INV-10) → load operator keys → load witnesses → build `LogParticipant` → `CommitmentExtension::new(gens, log as LeafLog)` → `Engine::open`.
- EP-1 `GroupExtension` = `CommitmentExtension`; EP-7 `TxnParticipant` = `LogParticipant` wrapped by `Guarded` (SB-21 hook lives in `Guarded::prepare`); EP-8 append stores for leaves, hashes, checkpoints, certificates; EP-9 `Clock`; EP-10 `Witness` [DOC: Build 3-4 §1.5].
- Log store directories: `log`, `log/leaves`, `log/hashes`, `log/checkpoints`, `certs` [CODE: crates/sever-log/src/store.rs:L29-L37]. "Insert leaves and certificates are written and fsynced before the COMMIT that covers them; leaf hashes and checkpoints are written only after it" [DOC: spec §10.5].
- Transaction ordering for deletes (`pre_transaction` → issue due checkpoints → `prepare` builds certificates → commit): [CODE: participant.rs:L222-L255, L324-L470].
- Delete requires `check_removal` pass first (C_t re-derivation vs insert leaf) [CODE: sever-commit lib.rs:L257-L276].
- CLI `sever-db-p3` subcommands: create, insert, delete, delete-user, certificate, anchors, export-log, latest-checkpoint, search, stats, drop, checkpoint, verify [CODE: crates/sever-p3/src/bin/sever-db-p3.rs:L193-L290].
- `sever-crashkit-p3`: test tooling (never linked into the engine): `replay` (P3-T5, Part 1 traces vs. model of commitments), `campaign` (P3-T4, crash at every VFS op using SimVfs, checks log/certificates after recovery), `attacks` (P3-T1/T2), `measure` (P3-T13) [CODE: crates/sever-crashkit-p3/src/lib.rs:L1-L12; main.rs:L1-L12].
- Python test kit `sever_testkit_p3` (gates, oracle_check, proofs, registers, rfc_vectors, spec_trace) and demo `sever_demo_p3/receipt.py` (`sever-demo receipt`) [CODE: file listing, wc].

## 15. Spike (spikes/p3-proof)

- A "THROWAWAY proof spike": an `AeadSealer` (AES-256-GCM-SIV) seals `r_t` and `r_agg`, and a `StubRotation` EP-7 participant sits after `LogParticipant`, showing that Part 4 can be added without editing Part 3 [CODE: spikes/p3-proof/src/lib.rs:L1-L11; Cargo.toml description]. Its only output is the `gates p3-spikes` ledger entry; header says "deleted after its gate".
- [CODE/DOC mismatch] The directory still exists in the working tree (src/lib.rs, tests/spike.rs, target/). The comment says it is deleted after the gate; I did not find a deletion. Pins in the spike: aes-gcm-siv `=0.11.1` [CODE: spikes/p3-proof/Cargo.toml].

---------------------------------------------------------------------------------------------------

## 16. Golden files and oracles (independent of engine)

- `golden/p3_generators.json` (Appendix B vectors 1–2), `p3_scalar_map.json` (vector 4), `p3_commitments.json` (§9.3, d=384 records, transition, group sums, identity), `p3_posk.json` (vector 3: ctx fields, C_S_post, A, c, proof at d=16), `p3_group_stream.json` (d=8, insert/delete stream with r_t and C_t), `p3_merkle_7.json`, `p3_certificates.json` (vector 6, d=384, with test keys, one group deletion and one holding deletion), `p3_attacks.json` (d=16, anchors + honest + 14+… attacks with model_step), `p3_audit.json` (honest export + AF-1..5), `p3_full_blob.json`, RFC vectors `p3_rfc8032_ed25519.json`, `p3_rfc9380_k3_expand_xmd_sha512.json`, `p3_rfc9496_ristretto255.json` [CODE: ls golden; python3 key listing].
- All Part 3 goldens were written by `sever_refmodel_certs` (pure-Python RFC 9496, RFC 9380, RFC 8032, RFC 9162), by design never from engine output [CODE: golden `source` fields; python/sever_refmodel_certs docstrings; DOC: Build 3-4 §1.6, §3.4, CLAUDE.md §6.3].
- Reference model internals: `ristretto.py` (field arithmetic mod 2^255−19, extended coordinates), `ed25519.py` (RFC 8032 with `verify_strict` conditions: S<ℓ, small-order checks), `xmd.py`, `merkle.py` (recursive MTH/PATH/PROOF), `posk.py` (nonces given explicitly, hedged derivation not modelled), `cert.py` (`verify` raising `VerifyError(step)`), `attacks.py`, `audit.py`, `group.py` [CODE: python/sever_refmodel_certs/*].

---------------------------------------------------------------------------------------------------

## 17. Doc-vs-code mismatches and open observations

1. **Verifier "no path dependencies"** [DOC: Build 3-4 §1.6 "A separate workspace with its own Cargo.lock, no path dependencies"] vs [CODE: verifier/Cargo.toml:L29-L31, audit/Cargo.toml:L29-L31]: both have a dev-dependency path to `../crates/sever-spec` (a no-op test-label proc-macro). Manifest comments disclose it (DB-85). Production build unaffected. Also `include_str!` reaches `../../golden/` and `../../spec/` outside the verifier directory (data only).
2. **"HMAC helpers" in sever-crypto** [DOC: Build 3-4 §1.4 modules table lists HMAC helpers under `sever-crypto`] vs [CODE: no hmac dependency in crates/sever-crypto/Cargo.toml; HMAC-SHA-512 scrambling lives in crates/sever-index/src/scramble.rs:L16-L40 (Part 1)]. Not a runtime problem; documentation drift.
3. **SB-19 scope**: register says "non-canonical point or scalar" but the sabotage affects only scalar decoding [CODE: group.rs:L43-L47]. Point-canonicality rejection has no sabotage item (other tests, AT-11, cover it at system level).
4. **Spike lifecycle**: spikes/p3-proof header says deleted after gate; directory still present [CODE: spikes/p3-proof/].
5. **G-34 test labelling**: no test cites G-34/DB-95; the repair lives in the attack generators (donor selection) and in the spec text, not in verifier/proof code. This is by design (the verifier was right; the attack was empty) [DOC: DB-95 "Why"].
6. **Nonce derivation not consensus-critical** (DOC) – confirmed: verifier has no `DST_NONCE`, no Merlin dependency.
7. **Witness independence**: spec admits simulation (§9.8, §10.4, L-7). Code confirms all 5 witness secret keys and "last cosigned checkpoint" live in one `WITNESSES` file in the engine's key directory [CODE: witnesses.rs:L1-L9]. The 4-of-5 threshold therefore does not provide independence in v1, and a compromised operator host controls all witnesses.
8. **Cosignature binds only the checkpoint message** (`DST_COSIGN ‖ DST_STH-message`), not the operator signature bytes [CODE: sig.rs:L92-L97]. Not a flaw per se (the operator's signature is verified separately at step 3), but worth stating accurately in the paper.
9. **Timestamp unused**: checkpoint `timestamp_ms` is signed and used to pick the operator epoch at signing time, but no verifier step compares it to certificate time or requires monotonicity (auditor also does not check monotonicity). [INFERRED: verify.rs and audit.rs read in full.]
10. **Operator signs with the epoch at `now_ms` of certificate issue**, whereas the embedded checkpoint carries its own (possibly older) epoch; the verifier therefore needs both epochs' keys in the anchors [CODE: builder.rs:L116; verify.rs:L105-L112, L160-L163].
11. **Auditor duplicate IDs**: `Members` is a `BTreeMap<scrambled_id, C_t>`; a second insert with the same `scrambled_id` silently overwrites (no AF) [CODE: audit.rs:L243-L244, L296-L314]. [INFERRED; engine prevents duplicate live IDs (§3.2), so only a dishonest log would show it.]
12. The `Guarded` wrapper in `sever-p3` forwards everything (EP-7) and exists to host SB-21 [CODE: lib.rs:L142-L190]; no production behaviour.
13. Part 3 is plaintext on disk (including `SECRETS` with operator keys, `r_t` in slot payloads); confidentiality arrives in Part 4 [DOC: CLAUDE.md §7; spec §13.2 note].
14. Spec Appendix A sizes (proof 12,352 B; certificate ≈ 14.1 KB; insert leaf 209 B; checkpoint 116 B; cosignature 69 B) all match constants in code (posk.rs:L97, leaf.rs:L11, checkpoint.rs:L23, L26) [CODE].

---------------------------------------------------------------------------------------------------

## 18. Gate/result pointers (as recorded, not re-run)

- P3-T1, P3-T2 (honest accepted, all attacks rejected): PASS 2026-11-01 08:57 at `94d0b24`, nq-10k, seeds 42 123 777 2024 9999 [DOC: docs/RESULTS.md L61].
- P3-T4 crash campaign PASS 2026-10-29 at `7c445b5` [DOC: RESULTS.md L75]; P3-T5 replay nq-100k five seeds PASS 2026-10-30 [L73]; P3-T10 fuzz PASS [L70]; P3-T9 mutants PASS at `fd40dfe` after earlier FAILs [L71-L74]; full-tier checks (P3-T3, T6, T7, T8, T9 sabotage, T11, T12) PASS 2026-11-01 at `94d0b24` [L64]; P3-T13 measure recorded [L66].
- Build targets list P3-T1…P3-T13 [DOC: Build 3-4 §1.9].

---------------------------------------------------------------------------------------------------

## 19. Glossary

- **Pedersen commitment**: `C = r·H + Σ m_i·G_i`; hiding (r uniform) and binding (no known DL relation among H, G_i).
- **Vector Pedersen**: one generator per component (`G_i`) plus a blinding generator (`H`).
- **ristretto255**: prime-order group (order ℓ) built from Curve25519 (RFC 9496), canonical 32-byte encodings; identity = 32 zero bytes.
- **ℓ**: group order, 2^252 + 27742317777372353535851937790883648493; scalars live mod ℓ, 32-byte little-endian.
- **x̃ (x-tilde)**: Q24-quantised vector, `i32` components, `round_half_even(x·2^24)`.
- **S, n**: exact `i64` component sum and count of a group; **r_agg**: Σ of members' `r_t` mod ℓ; **C_S**: group commitment, `Σ C_t`.
- **C_t / r_t**: per-record commitment and its blinding scalar (64 OS bytes reduced mod ℓ).
- **C_S_pre / C_S_post**: group commitment before / after a deletion; transition `C_S_post + C_t = C_S_pre`.
- **ctx**: 152-byte deletion context hashed into the Fiat–Shamir challenge.
- **posk**: proof of knowledge of an opening of `C_S_post` (Okamoto/Schnorr generalisation, Fiat–Shamir).
- **Hedged nonce**: nonce derived from witness + statement + fresh OS entropy via Merlin, so repeated or faulty RNG cannot repeat a nonce.
- **Merlin transcript**: STROBE-based transcript API (merlin 3.0.0) for domain-separated hashing/RNG.
- **DST**: domain separation tag, a fixed ASCII prefix on every hash/signature input (§2.3).
- **`verify_strict`**: ed25519-dalek verification that rejects small-order keys and non-canonical encodings.
- **expand_message_xmd**: RFC 9380 §5.3.1 uniform-bytes expander (SHA-512 here); **hash_to_group**: its output into RFC 9496 one-way map.
- **gdigest**: SHA-512 of the generator encodings; ties anchors to a generator set.
- **Insert leaf (0x01)**, **delete leaf (0x02)**: log leaves; delete leaf contains the whole certificate.
- **database_lsn**: 0-based index of an operation's own log leaf.
- **Log checkpoint (STH)**: operator-signed `(tree_size, root, timestamp_ms, epoch)`.
- **Witness / cosignature**: independent party (simulated in v1) that checks consistency between checkpoints and signs `DST_COSIGN ‖ checkpoint message`; 4 of 5 = "witnessed".
- **Epoch**: 90-day key period from database genesis; `key_period` (tag 8) names the operator epoch signing a certificate.
- **Anchors**: JSON of operator and witness public keys by epoch + `d` + `gdigest` given to the verifier; generator golden file is compiled in.
- **Holding area**: pre-group buffer; deletions from it get `deletion_kind = 1`, no accumulator arithmetic.
- **Emptied group (tag 11)**: the deletion removed the last member; `C_S_post` is the identity.
- **AT-N / AF-N / SB-N**: attack, auditor-fault and sabotage register IDs; **SR-…**: requirement IDs; **DB-N**: decision; **G-N**: spec gap; **P3-Tn**: Part 3 gate/measure; **EP-n**: extension point.
- **Red proof**: a patch that breaks one rule and the labelled tests that must go red (CLAUDE.md §6.3).
- **Oracle A/B/C/D**: classification of where a test's expected value comes from (spec by hand / independent oracle / frozen Part 1 / code under test).
