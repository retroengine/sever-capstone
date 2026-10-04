# Part 3 preview: commitments, the proof of knowledge, certificates, the offline verifier

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

Files (engine): [crypto.py](../../python/sever_demo/crypto.py), [posk.py](../../python/sever_demo/posk.py),
[cert.py](../../python/sever_demo/cert.py), commitments in [group.py](../../python/sever_demo/group.py)
and [index.py](../../python/sever_demo/index.py), [receipts.py](../../python/sever_demo/receipts.py).
Verifier (separate, shares no code): [python/sever_verify/](../../python/sever_verify/).
Tests: `test_crypto.py`, `test_posk.py`, `test_cert.py`, `test_group_commitments.py`,
`test_architecture.py`, plus Part 3 cases in `test_stress.py`, `test_repl.py`, `test_sabotage.py`.
Written by Claude (write mode, 3 Oct 2026), on the user's request "A + B + C".

**This is a preview, not Part 3.** The build plan puts Part 3 after Part 2 (crash safety). Everything
below is named as a preview, and every simplification is listed in "Simplifications".

## One line

Each group publishes a sealed fingerprint of its sum (`C_S`). Every deletion produces a signed receipt
that anyone can check with no database access: the fingerprint moved by exactly the deleted record's
fingerprint, and the operator proves it knows what is inside the new one.

## 1. The commitment (Pedersen), in plain words

A **commitment** is a sealed envelope:
- **hiding**: nobody can read the value inside;
- **binding**: you can't later claim a different value was inside.

Pedersen's envelope can also be **added without opening it**: envelope(a) + envelope(b) = envelope(a + b).

Formula (§9.3): `C = r·H + x·G`. `x` is the value, `r` is a random secret (blinding) that hides it, and
`G`, `H` are fixed public points whose relation nobody knows.

**Toy** (mod 101, G = 7, H = 13; insecure, only to see the arithmetic; checked by running it):

| | x | r | C = 7x + 13r (mod 101) |
|---|---|---|---|
| record a | 5 | 20 | **93** |
| record b | 9 | 33 | **88** |
| group a + b | 14 | 53 | **80** = 93 + 88 (mod 101) |

Delete a: the group becomes b alone, `C_S_post = 88`. Anyone can check `88 + 93 = 80 (mod 101)`:
**`C_S_post + C_t = C_S_pre`** (§9.3), without seeing any x or r.

In the system:
- one generator per number: `C_t = r_t·H + Σ x̃_i·G_i` (d = 384, generators from a public string, §9.2);
- a group's `C_S = r_agg·H + Σ S_i·G_i`, where `r_agg` = sum of its members' `r_t`;
- it only works because `S` is an **exact integer**. A float sum could not be committed to.
- The real group is **ristretto255** (an elliptic-curve group): "dividing by G" is infeasible, which is
  what makes the envelope hiding and binding.

## 2. Why the public check is not enough

An operator could publish `C_S_post = C_S_pre − C_t` **without deleting anything**: the equation would
still hold. So the operator must also prove it **knows the contents** of `C_S_post`: the real `S_post`
and `r_post`. That is the proof of knowledge (§9.5).

## 3. The proof of knowledge (§9.5), in plain words

A Schnorr-style proof ("I know the secrets inside this envelope, without showing them"):
1. pick fresh random numbers `k` (one per secret), publish `A` = envelope of the `k`s;
2. compute a challenge `c` = hash of (`C_S_post`, `A`, the deletion context): the operator can't choose it;
3. reveal `z = k + c·secret` for each secret.

The verifier checks `envelope(z) = A + c·C_S_post`. Only someone who knows the secrets can produce
`z` values that pass for an unpredictable `c`. The `k`s hide the secrets.

**Toy** (same mod 101; secrets x = 9, r = 33, so C = 88; k_x = 4, k_r = 10, pretend c = 3):
`A = 7·4 + 13·10 = 57`; `z_x = 4 + 3·9 = 31`; `z_r = 10 + 3·33 = 109 → 8`.
Check: `7·31 + 13·8 = 321 → 18` and `A + c·C = 57 + 3·88 = 321 → 18`. ✓

Real sizes: 385 secrets (r and 384 sums), so the proof is `A ‖ z_r ‖ z_0 … z_383` = **12,352 bytes**.
The context binds `C_S_pre`, `C_t`, the scrambled record ID, the deletion number and the collection, so a
proof can't be reused in another certificate (tested).

## 4. The certificate (§11.1) and the verifier (§11.3)

13 fields in a fixed order (tag, length, value), then the operator's **Ed25519 signature**.

| Tag | Field | In the preview |
|---|---|---|
| 1 | `C_t` | ✓ |
| 2, 3 | `C_S_pre`, `C_S_post` | ✓ |
| 4 | proof of knowledge | ✓ 12,352 bytes |
| 5, 6, 7 | user insert signature, log inclusion, witness cosignatures | **empty** (no log yet) |
| 8 | key epoch | 0 |
| 9 | scrambled record ID = HMAC-SHA-512(secret key, collection ‖ ID) | ✓ the real ID never appears |
| 10 | `database_lsn` | **this session's deletion counter** (no log) |
| 11 | group emptied? | ✓ |
| 12, 13 | kind (0 = from a group), collection ID | ✓ |

Size: **12,676 bytes** (the spec's full certificate is about 14.1 KB; the difference is tags 5-7).

The verifier (`python -m sever_verify anchors.json some.cert`) needs only the file and the operator's
public key. Its steps:

| Step | Checks | Preview |
|---|---|---|
| 1 | strict parse; points canonical; `C_t` not the identity | PASS/FAIL |
| 2 | operator signature | PASS/FAIL |
| 3, 4, 5 | insert was logged, witnesses cosigned, ordering | **NOT CHECKED** (said, never faked) |
| 6a | `C_S_post + C_t = C_S_pre` | PASS/FAIL |
| 6b | proof of knowledge | PASS/FAIL |
| 6c | "emptied" flag ⇔ `C_S_post` is the identity | PASS/FAIL |

## 5. How it was built so it can be trusted

- **No crypto implemented by us** (§9.1): ristretto255 and Ed25519 come from the system **libsodium
  1.0.18**, through `ctypes`. No new pip package (none on PyPI exposes ristretto255). Only
  `expand_message_xmd` (a hashing recipe, RFC 9380) is written here.
- **Two separate implementations**: the engine's and the verifier's, written apart; a test forbids either
  from importing the other. The verifier is also the **test oracle** for every `C_S`.
- **Pinned to published test vectors**: RFC 9496 (16 generator multiples, 29 invalid encodings, 11
  uniform-bytes cases), RFC 9380 (10 expand_message cases), RFC 8032 (3 Ed25519 cases). Both
  implementations pass all of them, and their 385 generators agree byte for byte.
- **A trap found and handled**: libsodium returns an error for `0·P`; the spec requires the identity
  (CLAUDE.md §7). Both wrappers return the identity; a test pins it.
- **Secrets stay in memory**: `r_t`, the signing key and the HMAC key come from the OS and are never
  printed, logged or written (tests check certificates and the ledger for them).

## 6. Simplifications (say them before you are asked)

| Simplification | Why | Spec |
|---|---|---|
| A preview inside the Python demo, before Part 2 | user request for the review | Build §0 order |
| Loaded groups get `C_S` in one step from `(S, r_agg)` | 1M per-record commitments ≈ 20 h; the value is identical (commitments add). After load, every insert and delete updates `C_S` record by record | §5.3 |
| Proof nonces are OS-random only, not Merlin-hedged | no Merlin in Python | §9.6 |
| No transparency log, witnesses or user insert signatures: tags 5-7 empty, steps 3-5 NOT CHECKED | Part 3's log is not built | §10, §11.2 |
| `database_lsn` = session deletion counter; one operator key, epoch 0 | no log, no key epochs | §9.8, §10.2 |
| Python big-integer arithmetic is not constant-time | demo, not the engine | §9.5 note |
| Keys and certificates are per session (`results/certs/` is git-ignored) | keys live only in memory | §13 |

## 7. Measured

Smoke run (50,000 rows, 2 Oct 21:39 UTC): **PASS**, 5 of 5 fields on all touched groups, 63
certificates of 12,676 bytes, **63 accepted**, 10 tampered copies **10 rejected**. Group commitments
took ~9 s for 128 groups; a certificate ~0.15 s to make and ~0.17 s to verify.

`--sabotage SB-4` (r_agg not reduced on delete), 20,000 rows: **FAIL**. Survivors check: S, n,
members and **C_S ✓**, blob **✗**; **all 37 certificates rejected** (the proof cannot be made). The
public check alone can't see this bug; the proof can.

Full run (1,000,000 rows, 2 Oct 21:50 UTC): **PASS**, 5 of 5 fields on all 23 touched groups, **912
certificates, 912 accepted**, **10 of 10 forged copies rejected**, 771 s. Details: [P1-demo-run.md](P1-demo-run.md).

## Trap questions

**1. "If anyone can check `C_S_post + C_t = C_S_pre`, why do you need a proof?"**
<details><summary>Answer</summary>
The equation holds for any operator who just subtracts points, even one who deleted nothing. The proof
shows the operator knows the real contents (`S_post`, `r_post`) of the new commitment. SB-4 shows it:
C_S moved correctly, but the proof failed.
</details>

**2. "Does a valid certificate prove the data is gone?"**
<details><summary>Answer</summary>
No. It proves the group's accounting moved by exactly that record and the operator knows the new state.
No cryptography can prove the operator kept no copy (spec §11.3, "What no certificate can prove").
Destroying the stored copies is Part 4 (crypto-shredding).
</details>

**3. "Why can't the commitment reveal the vector?"**
<details><summary>Answer</summary>
`r_t` is random and secret. For any guessed vector there is some `r` that gives the same `C`, so `C`
says nothing about `x` (hiding). Finding a second opening would need a discrete logarithm (binding).
</details>

**4. "Why is `C_S` checked separately from the blob, if the blob contains `C_S`?"**
<details><summary>Answer</summary>
§5.5: each field on its own. SB-4 shows why it helps to have both: `C_S` was right but `r_agg` (in the
blob) was wrong.
</details>

**5. "Did you implement the cryptography yourself?"**
<details><summary>Answer</summary>
No. The group and signatures are libsodium 1.0.18. My code combines them (commitments, the proof, the
certificate format) as the spec describes, and is checked against RFC test vectors and a second,
separately written verifier.
</details>

**6. "What does the verifier NOT check?"**
<details><summary>Answer</summary>
That the record was inserted in a public, witnessed log (steps 3-5). It says NOT CHECKED, never PASS.
That needs the transparency log, which is not built.
</details>

## Open fixes

- Golden vectors (spec Appendix B) for `H`, `G_0`, `G_383`, gdigest and a fixed certificate: not yet
  frozen in `golden/`.
- Transparency log (§10), insert signatures, witnesses, key epochs: Part 3 proper.
- Merlin-hedged nonces (§9.6) and constant-time arithmetic: the Rust engine.
