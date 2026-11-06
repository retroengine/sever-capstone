# B04 · Cryptography basics (everything SEVER-DB uses, from zero)

## In simple words

Cryptography gives us tools to **fingerprint** data (hashes), **hide** data (encryption), **vouch**
for data (signatures), **lock in** a hidden number without revealing it (commitments), **prove** you
know something without revealing it (proofs of knowledge), and keep a **tamper-evident history**
(Merkle trees and transparency logs). SEVER-DB uses each of these for one specific job. This file builds
them up one by one, with intuition and tiny examples, then shows where SEVER-DB uses them.

> **Prerequisites.** Modular arithmetic ("clock arithmetic": 7 + 8 mod 12 = 3) and bytes
> ([15_prerequisites §2](../15_prerequisites.md#2-maths)). Glossary: see each linked term.

## The problem this solves

To delete provably and permanently, SEVER-DB must (a) let anyone check arithmetic on hidden numbers,
(b) make the history of inserts and deletes impossible to rewrite quietly, and (c) make old disk copies
useless. Each needs a different tool.

## Build up step by step

### 1. Hash functions

A **hash function** (e.g. SHA-256) maps any input to a fixed-size output (32 bytes) so that it is
infeasible to find two inputs with the same output (*collision resistance*) or an input for a given
output (*preimage resistance*). Change one bit of the input and about half the output bits change.
*Analogy:* a fingerprint — tiny, unique in practice, and you cannot rebuild the person from it.
*Where it stops:* fingerprints can be forged by hand; good hashes cannot be "forged" with any known method.
SEVER-DB: SHA-256 for Merkle leaves, artefact and blob digests; SHA-512 for challenges and generator
derivation ([07a](../07a_crypto_overview.md)).

**HMAC** is a keyed hash: only someone with the key can compute it. SEVER-DB uses HMAC-SHA-512 to turn
record IDs into pseudonyms (`scrambled_id`) [CODE: crates/sever-index/src/scramble.rs:L31-L40].

**Domain separation:** prefix each hashed message with a label so hashes made for one purpose can't be
reused for another (SEVER-DB has seven such labels, [07a](../07a_crypto_overview.md)).

### 2. Symmetric encryption, AEAD and nonces

**Symmetric encryption** uses one secret key to encrypt and decrypt. **AEAD** (authenticated encryption
with associated data) also detects any change to the ciphertext and authenticates extra public bytes
(the **associated data**) — e.g. "this ciphertext belongs to record X, version 7". A **nonce** ("number
used once") is a fresh value per encryption; with ordinary AES-GCM, reusing a nonce with the same key is
catastrophic. **AES-GCM-SIV** (RFC 8452) is *nonce-misuse resistant*: a repeat only reveals whether two
messages were identical. SEVER-DB: AES-256-GCM-SIV with random 96-bit nonces for every secret on disk
[CODE: crates/sever-seal/src/aead.rs:L18-L28].

### 3. Key wrapping, key hierarchies and crypto-shredding

**Wrapping** a key = encrypting it under another key. A **key hierarchy** wraps many small keys under a
few bigger ones. **Crypto-shredding** = destroying the key so the ciphertext, wherever its copies are,
becomes useless. *Analogy:* burning the only key to a locked box; the box can stay in the attic forever.
*Where it stops:* if anyone copied the key earlier, burning yours does nothing.
SEVER-DB: group → bucket → record keys; only group keys need physical erasure
([07e](../07e_encryption_and_crypto_shredding.md)).

### 4. Digital signatures

A **signature** scheme has a private key (sign) and a public key (verify). Anyone with the public key
can check that a message was signed by the private-key holder and not changed. SEVER-DB: **Ed25519**
(RFC 8032), verification only with `verify_strict` [CODE: crates/sever-crypto/src/sig.rs:L56-L63].

### 5. Groups and elliptic curves (intuition only)

A **group** is a set with an "addition" that behaves nicely (there is a zero, every element has a
negative). Elliptic-curve groups have points you can add; `a·P` (add `P` to itself `a` times) is easy to
compute, but from `a·P` and `P` finding `a` is believed infeasible (**discrete-log problem**).
**ristretto255** (RFC 9496) is such a group with a clean prime order and canonical 32-byte encodings.

**Illustrative toy (not secure):** numbers mod 23 under addition; `5·7 mod 23 = 12`. In a real group the
"reverse" (find 5 from 12 and 7) is hard; in this toy it is easy — the toy only shows the arithmetic.

### 6. Commitments — hiding and binding, and the homomorphic property

A **commitment** to `m` is a value `C` that **hides** `m` (reveals nothing) and **binds** the committer
(they cannot later open it to another value). **Pedersen:** `C = r·H + m·G` with random `r`. It is
**homomorphic**: `C(m1, r1) + C(m2, r2) = C(m1 + m2, r1 + r2)`.
*Analogy:* a sealed, tamper-evident envelope; you can add two envelopes' contents without opening them.
*Where it stops:* envelopes can be steamed open; a Pedersen commitment cannot be opened without `r`.

**Illustrative example (toy mod 23, `H = 5`, `G = 7`):** `C(3, r=2) = 10 + 21 = 31 → 8`;
`C(4, r=6) = 30 + 28 = 58 → 12`; sum `8 + 12 = 20`; `C(7, r=8) = 40 + 49 = 89 → 20` ✓.

SEVER-DB: `C_t` per record, `C_S` per group; deletion gives `C_S_post = C_S_pre − C_t`
([07b](../07b_pedersen_commitments_and_proofs.md)).

### 7. Proofs of knowledge and zero knowledge (intuition)

A **proof of knowledge** convinces a verifier that the prover *knows* a secret (e.g. the opening of a
commitment) without revealing it (**zero-knowledge**). The **Schnorr protocol**: commit to a random
nonce (`A = k·H`), receive a random challenge `c`, answer `z = k + c·r`; the verifier checks
`z·H = A + c·C`. **Fiat–Shamir** replaces the verifier's random `c` with a hash of the transcript,
making the proof a single message. *Analogy:* proving you know a cave's secret door by coming out of
whichever side the verifier shouts. *Where it stops:* the cave story has a 50 % cheat chance per round;
the real protocol's cheat chance is about 1/ℓ.

**Illustrative (toy):** `r = 4`, `C = 20`; `k = 3`, `A = 15`; `c = 2`; `z = 11`; `11·5 = 55 → 9`;
`15 + 2·20 = 55 → 9` ✓.

### 8. Merkle trees, inclusion and consistency proofs

A **Merkle tree** hashes leaves in pairs up to one **root**. An **inclusion proof** (the sibling hashes
along a path) shows a leaf is in the tree; a **consistency proof** shows an older root is a prefix of a
newer tree. Changing any leaf changes the root. Example and diagram:
[07c](../07c_transparency_log_and_signatures.md).

### 9. Transparency logs and witnesses

A **transparency log** is a public append-only Merkle log whose roots are signed (RFC 9162, Certificate
Transparency). **Witnesses** independently check consistency between successive roots and **cosign**
them, so a log cannot show different histories to different people (split view). SEVER-DB uses five
witnesses with a threshold of four — **simulated** in v1.

## How SEVER-DB uses each tool

| Tool | SEVER-DB job | File |
|---|---|---|
| SHA-256/512, HMAC | fingerprints, pseudonymous IDs | [05](../05_part1_the_idea.md), [07a](../07a_crypto_overview.md) |
| Pedersen commitments | public arithmetic on hidden group sums | [07b](../07b_pedersen_commitments_and_proofs.md) |
| Schnorr-style proof + Fiat–Shamir | operator knows the new group state | [07b](../07b_pedersen_commitments_and_proofs.md) |
| Ed25519 | user, operator, witness signatures | [07c](../07c_transparency_log_and_signatures.md) |
| Merkle log + witnesses | tamper-evident history | [07c](../07c_transparency_log_and_signatures.md) |
| AES-256-GCM-SIV + key hierarchy | encryption and crypto-shredding | [07e](../07e_encryption_and_crypto_shredding.md) |

## Key points to remember

- Hash = fingerprint; HMAC = keyed fingerprint; domain strings keep purposes apart.
- AEAD = confidentiality + integrity + authenticated context; GCM-SIV tolerates nonce mistakes.
- Commitments hide and bind; Pedersen commitments add up.
- A proof of knowledge proves you know a secret without revealing it.
- Merkle logs + witnesses make history tamper-evident.

## Check your understanding

1. *What does "binding" mean?* — The committer cannot open the commitment to a different value.
2. *Why does crypto-shredding beat overwriting?* — Copies of ciphertext you cannot reach become useless once the key is gone.
3. *What does Fiat–Shamir replace?* — The verifier's random challenge, with a hash.
4. *What does a consistency proof show?* — An old log root is a prefix of the new log.
5. *What do witnesses prevent?* — A log showing different histories to different people.
