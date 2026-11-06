# 07a · Cryptography overview: every primitive in the code

## In simple words

SEVER-DB uses a small, fixed set of standard cryptographic tools, each for one job: hashes to
fingerprint data, commitments to lock in hidden numbers, a proof to show knowledge without revealing,
signatures to say "the operator vouches for this", a Merkle log to make history tamper-evident, and
authenticated encryption plus key destruction to make deleted data unreadable. This file is the map;
files 07b–07g explain each part.

> **Prerequisites.** [B04](background/B04_cryptography_basics.md) (all crypto basics).
> Glossary: [hash function](16_glossary.md#hash-function), [AEAD](16_glossary.md#aead),
> [digital signature](16_glossary.md#digital-signature), [Pedersen commitment](16_glossary.md#pedersen-commitment).

## The problem this solves (beginner map)

| Problem | Tool | Where explained |
|---|---|---|
| "Prove the group changed by exactly this record, without revealing the group" | Pedersen commitments (homomorphic) | [07b](07b_pedersen_commitments_and_proofs.md) |
| "Prove the operator knows the new group state" | Schnorr/Okamoto proof of knowledge + Fiat–Shamir | [07b](07b_pedersen_commitments_and_proofs.md) |
| "Prove the record was really inserted, and history was not rewritten" | RFC 9162 Merkle log, signed checkpoints, witnesses | [07c](07c_transparency_log_and_signatures.md) |
| "Who vouches for this?" | Ed25519 signatures (user, operator, witnesses) | [07c](07c_transparency_log_and_signatures.md) |
| "Let anyone check offline" | Deletion certificate + independent verifier | [07d](07d_deletion_certificate_and_verification.md) |
| "Make old copies of deleted data unreadable" | AES-256-GCM-SIV + key hierarchy + crypto-shredding | [07e](07e_encryption_and_crypto_shredding.md) |
| "Detect accidental corruption of stored bytes" | CRC-32C (not a security primitive) | [06](06_part2_the_database.md) |
| "Hide record IDs below the API" | HMAC-SHA-512 scrambled IDs | [05](05_part1_the_idea.md) |

## Every primitive actually in the code

Versions are the `=` pins in `Cargo.toml` and the locked versions in `Cargo.lock`
[RUN: parse of Cargo.lock in this session].

| # | Primitive | Algorithm / parameters | Library (locked version) | Code | Part |
|---|---|---|---|---|---|
| 1 | Prime-order group | ristretto255 (RFC 9496), order ℓ = 2^252 + 27742317777372353535851937790883648493 | curve25519-dalek 4.1.3 | crates/sever-crypto/src/group.rs:L1-L55 | 3 |
| 2 | Hash-to-bytes | `expand_message_xmd` with SHA-512 (RFC 9380 §5.3.1) — **the only primitive implemented by the project** (DB-52) | own code on sha2 0.10.9 | crates/sever-crypto/src/xmd.rs:L14-L59; verifier/src/xmd.rs | 3 |
| 3 | Hash-to-group | RFC 9496 one-way map `from_uniform_bytes` over 64 xmd bytes | curve25519-dalek | group.rs:L10-L20 | 3 |
| 4 | Generators `H`, `G_0…G_{d−1}` | hashed from `DST_GEN`; digest `gdigest` = SHA-512 of all encodings | — | generators.rs:L17-L45 | 3 |
| 5 | Vector Pedersen commitment | `r·H + Σ scalar(v_i)·G_i`, constant-time multiscalar multiplication | curve25519-dalek | commit.rs:L14-L44 | 3 |
| 6 | Proof of knowledge of a representation | Fiat–Shamir Σ-protocol, `d + 1` witnesses; challenge = SHA-512 → wide reduction mod ℓ | curve25519-dalek, sha2 | posk.rs:L56-L195 | 3 |
| 7 | Hedged nonces | Merlin transcript (STROBE-128) + witness + 32 OS bytes | merlin 3.0.0, rand_core 0.6.4 | nonce.rs:L56-L147 | 3 |
| 8 | Signatures | Ed25519 (RFC 8032); verification only `verify_strict` | ed25519-dalek 2.2.0 | sig.rs:L22-L106 | 3 |
| 9 | Merkle log | RFC 9162 §2.1, SHA-256, leaf prefix `0x00`, node prefix `0x01` | sha2 | crates/sever-log/src/merkle.rs:L20-L274 | 3 |
| 10 | Scrambled record ID | HMAC-SHA-512, 64-byte key, over `collection_id ‖ record_id` | hmac 0.12.1 + sha2 | crates/sever-index/src/scramble.rs:L16-L40 | 1 |
| 11 | Spawned-group ID; blob/state digests | SHA-256 | sha2 | crates/sever-index/src/index.rs:L147-L159 | 1 |
| 12 | Partition artefact hash | SHA-256 of all preceding bytes | sha2 | crates/sever-partition/src/lib.rs:L114-L124 | 1 |
| 13 | AEAD | AES-256-GCM-SIV (RFC 8452), random 96-bit nonce, 16-byte tag, 28 B overhead | aes-gcm-siv 0.11.1 (aes 0.8.4 with `zeroize`) | crates/sever-seal/src/aead.rs:L4-L35 | 4 |
| 14 | Key wrapping | the same AEAD with associated data naming owner and version (not RFC 3394 key wrap) | aes-gcm-siv | crates/sever-seal/src/ad.rs, ring.rs | 4 |
| 15 | Checksums | CRC-32C (Castagnoli) on every on-disk record and key slot | crc32c 0.6.8 | crates/sever-format/src/codec.rs:L11-L14; crates/sever-keys | 2, 4 |
| 16 | Secret wiping | `Zeroize` / `ZeroizeOnDrop` | zeroize 1.9.0 | throughout | 1–4 |

"No other primitive is used" [DOC: docs/SEVER-DB_SPECIFICATION.md §9.1]; a grep found no AES or CRC use
in the Part 3 crypto crates and no other cipher [DOC: _notes/part3.md §1].

## Domain strings (every hash or signature input starts with one)

| Name | Exact bytes | Length | Used for |
|---|---|---|---|
| `DST_GEN` | `PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS` | 41 | generator derivation |
| `DST_POSK` | `SEVERDB_POSK_V1` | 15 | proof challenge |
| `DST_NONCE` | `SEVERDB_POSK_NONCE_V1` | 21 | Merlin nonce transcript |
| `DST_INSERT` | `SEVERDB-INSERT-V1` | 17 | user insert signature |
| `DST_STH` | `SEVERDB-STH-V1` | 14 | operator checkpoint signature |
| `DST_COSIGN` | `SEVERDB-COSIGN-V1` | 17 | witness cosignature |
| `DST_CERT` | `SEVERDB-CERT-V1` | 15 | operator certificate signature |

[CODE: crates/sever-crypto/src/dst.rs:L4-L16; DOC: §2.3]. **Domain separation** (definition: putting a
unique label at the start of every hashed or signed message) prevents a signature or hash made for one
purpose from being accepted for another.

## Where randomness comes from — and how seeds are kept out

| Value | Source | Code |
|---|---|---|
| `r_t` (64 bytes, reduced mod ℓ) | OS (`OsRng`) in the SDK's `prepare_insert` | crates/sever-py-p3/src/lib.rs:L294-L296 |
| user Ed25519 key | OS, 32 bytes | sig.rs:L26-L33 |
| operator and witness epoch keys | OS, 32 bytes, durable before first use | crates/sever-p3/src/keys.rs:L29-L34; witnesses.rs:L170-L245 |
| proof nonces | hedged: witness + statement + 32 OS bytes | nonce.rs:L117-L147 |
| AEAD nonces | OS, 12 bytes | crates/sever-seal/src/aead.rs:L18-L28 |
| group/bucket/record keys | OS, 32 bytes | DOC: §13.1 |
| `k_scramble` (64 B), `collection_id` (16 B) | OS | crates/sever-p1/src/root.rs:L24-L36; crates/sever-engine/src/engine.rs:L90-L96 |

The five experiment seeds (42, 123, 777, 2024, 9999) feed only data order, synthetic data and k-means
[CODE: python/sever_testkit/seeds.py:L9-L23; CLAUDE.md §6.2]. Seeds are kept out of proofs and keys by:
`StrictProofRng` (not `SeedableRng`, enforced by `compile_fail` doc-tests) [CODE: nonce.rs:L22-L66]; no
SDK function taking a generator, seed or nonce, with `SeededNonceForbidden` for any extra argument
[CODE: python/sever_db_p3/__init__.py:L91-L95]; and sabotage SB-18 / SB-30 proving that nonce reuse is
detected.

## Everyday analogy

*Analogy:* The crypto toolkit is a notary's office: an envelope sealer (commitments), a stamp
(signatures), a bound ledger with page fingerprints (Merkle log), witnesses who countersign, and a
shredder for keys. *Where it stops:* a notary is one trusted person; SEVER-DB's guarantees hold only
under the stated assumptions (discrete-log hardness, honest-majority witnesses — simulated in v1).

## Key points to remember

- ristretto255 + Pedersen + Schnorr-style proof for the arithmetic claim.
- Ed25519 `verify_strict` for every signature; seven domain strings.
- RFC 9162 Merkle log with SHA-256.
- AES-256-GCM-SIV for every ciphertext, with associated data.
- All randomness from the OS; seeds never reach keys, `r_t`, nonces.

## Check your understanding

1. *Which primitive does the project implement itself, and why?* — `expand_message_xmd`, missing in dalek 4.1.3.
2. *Is CRC-32C a security tool here?* — No; it detects accidental corruption only.
3. *How are keys "wrapped"?* — Encrypted with AES-256-GCM-SIV under the parent key, with AD naming owner and version.
4. *Why distinct domain strings?* — So a signature for one purpose cannot be reused for another.
5. *Can a test seed influence `r_t`?* — No; `r_t` comes from the OS inside the SDK.
