# 07b · Pedersen commitments and the deletion proof (Part 3)

## In simple words

Each record gets a **commitment** `C_t`: a 32-byte value that locks in the record's vector without
revealing it. Each group keeps a commitment `C_S` to its sum. Because these commitments can be added
and subtracted like numbers, deleting a record changes the group's commitment by exactly the record's
commitment: `C_S_after = C_S_before − C_t`. Anyone can check that subtraction from public values. The
operator also attaches a short **proof** that it really knows the group's new contents. These pieces
go into the deletion certificate ([07d](07d_deletion_certificate_and_verification.md)).

> **Prerequisites.** Modular arithmetic and groups (intuition), hashes, commitments, the homomorphic
> property, zero-knowledge proofs (intuition) — [B04](background/B04_cryptography_basics.md).
> Q24 integers — [B03](background/B03_floating_point_vs_exact_integers.md).
> Glossary: [Pedersen commitment](16_glossary.md#pedersen-commitment), [ristretto255](16_glossary.md#ristretto255),
> [r_t](16_glossary.md#r_t), [C_t](16_glossary.md#c_t), [C_S](16_glossary.md#c_s), [Fiat–Shamir](16_glossary.md#fiat-shamir).

## The problem this solves

A user is told "your record was deleted from group 17". How could anyone check that without seeing the
group's private contents? If the operator published the group's sum `S`, everyone would learn the data.
If it published nothing, the claim is unverifiable. Commitments sit in between: public values that
**bind** the operator to the hidden numbers but **hide** them.

## Build up step by step

### Step 1 — A group where "adding points" is hard to reverse

SEVER-DB works in **ristretto255** (RFC 9496): a set of points with an addition operation, a special
"zero" point called the **identity** (encoded as 32 zero bytes), and a size **ℓ** (the *group order*):
`ℓ = 2^252 + 27742317777372353535851937790883648493` [DOC: docs/SEVER-DB_SPECIFICATION.md §2.1]. For a
number `a` and a point `P`, `a·P` means "add `P` to itself `a` times" (*scalar multiplication*).
Computing `a·P` is easy; recovering `a` from `a·P` is believed infeasible (the *discrete-log problem*).
Numbers used as multipliers are **scalars**, taken modulo ℓ. Library: `curve25519-dalek =4.1.3`
[CODE: crates/sever-crypto/Cargo.toml:L17].

### Step 2 — Generators nobody can cheat with

The commitment needs `d + 1` independent base points: `H` and `G_0 … G_{d−1}`. They are derived by
hashing public strings, so no one knows any relation between them (*nothing-up-my-sleeve*):

```
H   = from_uniform_bytes( expand_message_xmd_SHA512( b"H",            DST_GEN, 64 ) )
G_i = from_uniform_bytes( expand_message_xmd_SHA512( b"G" ‖ u32be(i), DST_GEN, 64 ) )
DST_GEN = "PROJECT_SEVER_V1_RISTRETTO255_SHA512_NUMS"  (41 bytes)
```
[CODE: crates/sever-crypto/src/generators.rs:L17-L30; group.rs:L10-L20; dst.rs:L4]

`expand_message_xmd` (RFC 9380 §5.3.1) is the **only** primitive the project implements itself,
because the pinned dalek version lacks it (DB-52) [CODE: crates/sever-crypto/src/xmd.rs:L14-L59].
At startup the engine re-derives the generators and checks RFC known-answer vectors and golden values,
refusing to run on any mismatch (INV-10) [CODE: generators.rs:L141-L200].

### Step 3 — Turning integers into scalars

Group sums can be negative. The map is `scalar(v) = v mod ℓ` for `v ≥ 0`, and `ℓ − (|v| mod ℓ)` for
`v < 0` [DOC: §4.5]. Code: `scalar_from_i64` takes `|v|` and negates it in the group when `v < 0`
[CODE: crates/sever-crypto/src/group.rs:L50-L55].

### Step 4 — The record commitment `C_t` and the group commitment `C_S`

```
C_t = r_t·H + Σ_{i=0}^{d−1} scalar(x̃_i)·G_i
C_S = r_agg·H + Σ_{i=0}^{d−1} scalar(S_i)·G_i ,   r_agg = Σ r_t mod ℓ over members
```
[CODE: crates/sever-crypto/src/commit.rs:L14-L44]

What each symbol means: `x̃_i` is component `i` of the quantised vector; `S_i` is component `i` of the
group's exact sum; `r_t` is a random **blinding scalar** (a secret random number that makes the
commitment hide the vector); `r_agg` is the sum of the members' blinding scalars. This is a **vector
Pedersen commitment**: one base point per component plus `H` for the blinding.

- **Hiding**: because `r_t` is uniformly random, `C_t` reveals nothing about `x̃`.
- **Binding**: finding two different openings of the same `C_t` would solve a discrete-log problem.
- **Homomorphic**: `C(a) + C(b) = C(a + b)` when blinding scalars are added too.

**Illustrative example, not from the repository** — a toy group where "points" are numbers mod 23
and scalar multiplication is ordinary multiplication mod 23 (this toy is **not secure**; it only shows
the arithmetic). Let `H = 5`, `G_0 = 7`, `d = 1`.

| Record | `x̃` | `r` | `C = r·H + x̃·G_0 mod 23` |
|---|---|---|---|
| a | 3 | 2 | 2·5 + 3·7 = 31 → **8** |
| b | 4 | 6 | 6·5 + 4·7 = 58 → **12** |
| group {a, b} | S = 7 | r_agg = 8 | 8·5 + 7·7 = 89 → **20** = 8 + 12 mod 23 ✓ |
| delete b | S = 3 | r = 2 | `C_S − C_b` = 20 − 12 = **8** = `C_a` ✓ |

The group commitment after the deletion equals the commitment of a group that never contained `b`.

### Step 5 — Where `r_t` comes from

The **application backend** runs `prepare_insert`: quantise → draw 64 bytes from the OS random
generator and reduce them modulo ℓ to get `r_t` → compute `C_t` → sign
`DST_INSERT ‖ collection_id ‖ C_t` with the account's Ed25519 key
[CODE: crates/sever-py-p3/src/lib.rs:L276-L316]. `r_t` travels inside the request and is stored by the
engine with the record (encrypted in Part 4); it is never exposed to Python code
[CODE: python/sever_db_p3/__init__.py:L127-L137]. The engine recomputes `C_t` from `x̃` and `r_t` and
rejects a mismatch (`CommitmentMismatch`), checks the signature with `verify_strict`
(`BadUserSignature`), and rejects `C_t` = identity [CODE: crates/sever-commit/src/lib.rs:L203-L227;
commit.rs:L55-L63].

### Step 6 — Exact homomorphic update on insert and delete

```rust
// add:    public.0 += c_t;  secret.0 += record.r_t
// remove: public.0 -= c_t;  secret.0 -= record.r_t
```
[CODE: crates/sever-commit/src/lib.rs:L229-L255] (paraphrased from the two methods; the verified public
check is `transition_holds`: `C_S_post + C_t == C_S_pre` [CODE: commit.rs:L46-L53]).

So `S`, `n`, `r_agg` and `C_S` change together in one transaction (INV-2), and an emptied group returns
to `S = 0`, `r_agg = 0`, `C_S` = identity exactly [CODE: crates/sever-crypto/src/tests.rs:L491].

### Step 7 — The proof of knowledge (what the operator proves)

**Statement.** The operator knows `(r_post, s_0 … s_{d−1})` with `s_i = scalar(S_post_i)` such that
`C_S_post = r_post·H + Σ s_i·G_i` [DOC: §9.5]. This is a **proof of knowledge of a representation**
(a multi-secret Schnorr / Okamoto Σ-protocol), made non-interactive with **Fiat–Shamir** (the
verifier's random challenge is replaced by a hash of the transcript).

**Deletion context** (152 bytes) — bound into the challenge so a proof cannot be reused elsewhere:
`ctx = C_S_pre(32) ‖ C_t(32) ‖ scrambled_id(64) ‖ u64be(database_lsn)(8) ‖ collection_id(16)`
[CODE: crates/sever-crypto/src/posk.rs:L15-L54].

**Prover** [CODE: posk.rs:L128-L156]:
```
nonces k_r, k_0 … k_{d−1}           (hedged, Step 8)
A   = k_r·H + Σ k_i·G_i
c   = wide_reduce( SHA-512( DST_POSK ‖ C_S_post ‖ A ‖ ctx ) )      DST_POSK = "SEVERDB_POSK_V1"
z_r = k_r + c·r_post   (mod ℓ)
z_i = k_i + c·s_i      (mod ℓ)
proof = A ‖ z_r ‖ z_0 … z_{d−1}      (32·(d+2) bytes = 12,352 bytes at d = 384)
```
**Verifier** [CODE: posk.rs:L158-L195; verifier/src/posk.rs:L47-L90]: decode strictly; recompute `c`;
accept iff `z_r·H + Σ z_i·G_i = A + c·C_S_post`. Why it works:
`(k_r + c·r)H + Σ(k_i + c·s_i)G_i = (k_rH + Σk_iG_i) + c(rH + Σs_iG_i) = A + c·C_S_post`.

**Illustrative example, not from the repository** (same toy group mod 23, one secret, `H = 5`):
secret `r = 4`, so `C = 4·5 = 20`. Nonce `k = 3` → `A = 15`. Suppose the hash gives `c = 2`.
`z = 3 + 2·4 = 11`. Check: `z·H = 55 mod 23 = 9`; `A + c·C = 15 + 40 = 55 mod 23 = 9` ✓.

**Important detail for the paper.** The proof covers the *post*-state only. The link to the
transition comes from the separate public check `C_S_post + C_t = C_S_pre` and from `C_S_pre` and
`C_t` being inside `ctx` [CODE: verifier/src/verify.rs:L191-L215] [INFERRED from the two checks].
A soundness argument (completeness, special-soundness extractor, simulator) is in `docs/SOUNDNESS.md`
and executed as tests (`p3_crypto_soundness_*`, crates/sever-crypto/src/tests.rs:L999-L1051); it is the
author's own argument, "not an independent review" [DOC: docs/SOUNDNESS.md; Overview L-21].

### Step 8 — Hedged nonces (and why seeds are forbidden)

If a nonce vector were ever reused with two different challenges, the secrets — the group's whole
sum — could be computed. So nonces mix three sources in a **Merlin** transcript (merlin 3.0.0): the
public statement and context, the secret witness, and 32 fresh bytes from the OS
[CODE: crates/sever-crypto/src/nonce.rs:L117-L147]:

```
T = Transcript::new("SEVERDB_POSK_NONCE_V1"); T.append("gens", gdigest); T.append("stmt", C_S_post); T.append("ctx", ctx)
rng = T.build_rng().rekey_with_witness_bytes("r", r_post) … ("s", s_i) … .finalize(StrictProofRng)
```

`prove()` accepts only `StrictProofRng`, a wrapper of the OS generator that deliberately does **not**
implement `SeedableRng`; `compile_fail` doc-tests prove a seeded generator cannot be passed
[CODE: nonce.rs:L22-L66, L150-L158]. The Python SDK raises `SeededNonceForbidden` for any extra
argument [CODE: python/sever_db_p3/__init__.py:L91-L95]. Sabotage SB-18 replaces the entropy with
zeros to prove a test detects repeated `A` values.

### Step 9 — The emptied-group exception (G-34, DB-95)

When a deletion empties a group, `C_S_post` is the identity and the check becomes `… = A + c·O = A`,
which no longer depends on `c`; such a proof would verify in **any** emptied certificate. An interim
attack run found this (AT-2 accepted in 3 of about 900 instances, seeds 777 and 9999). The spec was
corrected to state the exception; nothing false is certified because step 6 still forces
`C_S_pre = C_t` and tag 11 must be 1, and the operator signature covers every field. The attack
generator now takes donors only from non-emptying certificates [DOC: docs/SPEC_GAPS.md G-34;
Overview DB-95; CODE: crates/sever-crashkit-p3/src/attacks.rs:L339-L350].

## Everyday analogy

*Analogy:* A commitment is a sealed, tamper-evident envelope with a number inside. You can add two
envelopes without opening them, and the result is a sealed envelope with the sum. *Where it stops:*
real envelopes can be opened by force; a Pedersen commitment cannot be "opened" without the blinding
value, and even the sender cannot later claim a different number (binding).

*Analogy:* The proof of knowledge is like proving you know a safe's combination by opening it in
front of a witness who chose a random question, without telling them the combination.

## Key points to remember

- `C_t = r_t·H + Σ x̃_i·G_i`; `C_S = Σ C_t`; a deletion makes `C_S_post = C_S_pre − C_t`.
- Generators are hashed from a public string; the project implements only `expand_message_xmd`.
- The proof shows knowledge of `C_S_post`'s opening, bound to a 152-byte context.
- Nonces are hedged; seeded randomness cannot reach the prover.
- Emptied groups are a documented exception to proof binding (G-34).

## Check your understanding

1. *Why add `r_t·H`?* — Without it, equal vectors give equal commitments and small spaces can be guessed.
2. *Who draws `r_t`?* — The application backend's SDK, from the OS random generator.
3. *What does the verifier check about the transition?* — `C_S_post + C_t == C_S_pre` (step 6).
4. *What does `ctx` prevent?* — Replaying a proof under another pre-state, record, position or collection.
5. *Why can an emptied group's proof be replayed?* — With `C_S_post` = identity the equation ignores `c`.
