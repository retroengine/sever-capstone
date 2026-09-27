# SEVER-DB — Live Demo Build Plan

A plan for a Python demo of SEVER-DB, runnable on your laptop, that you can walk your guide through
end to end. It is written against `SEVER-DB_SPECIFICATION.md` (cited as **§**) and
`SEVER-DB_PROJECT_OVERVIEW.md` (cited as **Overview §** / **DB-** / **L-**). Where this plan and the
spec disagree, **the spec wins**; every place the demo deliberately does less is listed in §3 as a
numbered simplification (D-1 … D-12), so nothing is simplified silently.

Checked on 27 Sep 2026: all library behaviour in §2 was tested in a sandbox, not assumed.

---

## 0. Verdict: build a new demo; do not build on the old one

### 0.1 Why not rebuild around the old demo

| | Old demo (`demo.zip`) | What the new demo needs |
|---|---|---|
| **Runs on its own?** | **No.** Every commitment goes through `sever_crypto`, a compiled Rust extension that is not in the zip (`_bootstrap.py`, `src/sever/crypto/__init__.py`). It also needs `configs/build.yaml` v6.0 and the old project's virtualenv. | `pip install` and run |
| **Data** | 8 synthetic random vectors in 3 fake topics; no text | Real SciQ and NQ passages and your P0 embeddings |
| **Index** | One hand-named group, `demo-group` | 128 frozen groups, drift test, holding area, spawned groups (§6, §7) |
| **Search** | Brute force inside one group | IVF-flat, 25 % probe (§8) |
| **Receipts** | None | Log, log checkpoints, witnesses, proof, certificate, independent verifier (§9–§11) |
| **Erasure** | None | Encryption at rest, key hierarchy, crypto-shredding (§13) |
| **Rules followed** | The superseded prototype's decisions (numbered 1–107) | This spec (DB-1 … DB-43) |

The old code also **contradicts the current spec** in several places, so copying it would import bugs:

| Topic | Old demo | Current spec |
|---|---|---|
| Proof domain and challenge | `SEVER_POSK`, 74-byte preimage | `SEVERDB_POSK_V1`, 231-byte preimage with a 152-byte `ctx` (§9.5) |
| Quantisation bound | Rejects `abs(x̃) ≥ 2^24`, so a one-hot vector is refused | No such rejection; `abs(x̃) ≤ 2^24 + 16`, stored as `i32` (§4.2). **A one-hot vector is legal.** |
| Blinding value | 31 random bytes plus a zero byte | 64 random bytes reduced mod ℓ (§9.4) |
| Deletion check | Uses the supplied `r_t` without checking it | Recompute `C_t`; it must equal the logged `C_t`, else `AuthorisationFailed` (§15.3 step 2) |
| Insert check | None | `CommitmentMismatch` and `BadUserSignature` (§9.3, §15.1) |
| Record-ID rule | `str.isdecimal()` (also matches non-ASCII digits); no length limit | `^[+-]?[0-9]+$` on ASCII digits; 1–256 bytes; not already live (§3.2) |
| Error messages | Print record IDs | Must never contain a record ID, vector, key, `r_t` or text (§17) |
| Stored vector | `int64` | `i32`, widened to `i64` only inside the blob (§4.2, §5.5) |

DB-1 (independent project) and DB-4 ("using the old prototype as the oracle" is rejected) point the
same way.

### 0.2 What is still worth reusing (re-type it; don't copy the files)

- **The canonical group blob layout.** §5.5 says it is byte-identical to the prototype's.
- **The five-field `assert_state_equivalent`** and its "why five fields, not two" scene: replay the
  survivors with fresh blinding values, and `S` and `n` match but `C_S` does not.
- **Replaying survivors in reverse order** to show that insertion order does not matter.
- **Physical excision, sorted member list, idempotent delete** (§5.4).
- **A scripted `--scripted` mode** that runs every scene with no keyboard and doubles as a self-check.
- **The frozen generator values** in `generator_vector.json`. Same public string, same derivation
  (§2.3, Appendix B item 1), so they are your golden check:
  - `H   = 80162606b4d5c1e2f2c40f1d21a2338e768114d9fa841739788f0b0f018b2556`
  - `G_0 = 46fd08889c692c2040cf735ad765e0a14a15c729b005926ae27922b1f9e46e3b`

### 0.3 The demo becomes the first piece of the real project

The spec's P1 already asks for **C-18, the Python reference model**: a slow, in-memory,
obviously correct implementation of §3–§8 and §11's arithmetic, used later as the oracle for the Rust
engine (DB-4). So build the demo in **two layers**:

1. **`sever_refmodel/`**: the pure core. No disk, no encryption, no clock. It grows into C-18.
2. **`demo/`**: everything that exists only for the presentation. Encrypted storage and keys, the
   engine wrapper, the client, the witnesses, the scripts and the UI.

C-18 must not contain storage machinery (DB-4 says the point of the oracle is that it has "none of
that machinery"), which is why the split matters.

---

## 1. What the demo shows, and what it leaves out

**In one sentence:** load 2,000 real Wikipedia passages into a SEVER index built on frozen SciQ
groups, search it, delete a record, and prove three things live: the index is exactly as if the
record never existed, anyone can verify the deletion receipt without the database, and the bytes
left on disk can no longer be read.

**Shown (every component except storage durability):**

| Scene | Spec |
|---|---|
| Real passages become Q24 integers | §4 |
| 128 frozen groups, drift threshold τ, pooled Ledoit–Wolf | §6 |
| Routing: in-distribution → frozen group; out-of-distribution → holding area → spawned group of exactly 200 | §7 |
| IVF-flat search, probing 25 % of groups | §8 |
| Exact deletion: `S`, `n`, `r_agg`, `C_S` return exactly; five-field equivalence proof | §5 |
| User keys, blinding values, commitments, insert signatures, scrambled IDs | §3.3, §9 |
| RFC 9162 transparency log, signed log checkpoints, 5 simulated witnesses (threshold 4) | §10 |
| Proof of knowledge and the 13-field deletion certificate | §9.5, §11 |
| A verifier that shares no code with the database | §11.3, C-16 |
| Crypto-shredding with the three-level key hierarchy | §13 |
| Attacks and refusals | §15, §17 |

**Left out (the "ACID and other DB features"):** the WAL (§12.3), storage checkpoints (§12.4),
transactions, locks and isolation (§12.5), crash recovery and the phase A/B/C crash table (§15.4,
§15.7), `SimVfs` fault injection (C-1), the page and slot file formats (§14.1–§14.2), memory hygiene
(§12.8), platform checks (§12.9), multiple collections, the server (C-14), and key-epoch rotation.
The demo applies each operation's steps in the spec's order, but not atomically.

---

## 2. Facts verified in a sandbox (so you don't have to guess)

| # | Check | Result |
|---|---|---|
| V-1 | `pynacl` has ristretto255 functions | **No.** Don't use it for this. |
| V-2 | `pysodium` has them | Yes, but it needs a separate libsodium DLL on Windows. Avoid. |
| V-3 | `rbcl` 1.1.2 has them and ships a **Windows wheel for Python 3.13** (`rbcl-1.1.2-cp313-abi3-win_amd64.whl`) with libsodium inside | **Yes. Use `rbcl`.** |
| V-4 | Pure-Python `expand_message_xmd` (RFC 9380 §5.3.1, SHA-512) + `rbcl.crypto_core_ristretto255_from_hash` reproduces `H` and `G_0` from the Rust/dalek prototype | **Both match exactly.** So your Python generators equal the spec's generators byte for byte. |
| V-5 | `crypto_scalarmult_ristretto255(0, P)` | **Raises an error** instead of returning the identity. Use `crypto_scalarmult_ristretto255_allow_scalar_zero`, which returns the identity (32 zero bytes). This matters: many components of `S` can be 0, and an emptied group is all zeros. |
| V-6 | `add(identity, P) == P`; `sub(P, P)` gives 32 zero bytes | Yes (§5.2: the identity is the all-zero encoding) |
| V-7 | Commitments are additive: `Σ C_t == commit(r_agg, S)`; after a delete, `C_S_post + C_t == C_S_pre`; an emptied group is the identity | All true |
| V-8 | Okamoto proof at d = 384: size, verification, tamper rejection | 12,352 bytes; verifies; a flipped bit is rejected |
| V-9 | Speed in the sandbox (expect the same order of magnitude on your laptop) | One d = 384 commitment ≈ **35 ms**; one proof ≈ **50 ms** |
| V-10 | `cryptography` 50.0.1 has `AESGCMSIV` | Yes; it adds a 16-byte tag, and you prepend the 12-byte nonce yourself (28 bytes total, §13.2) |
| V-11 | scikit-learn `KMeans(random_state=seed)` with the spec's 64-bit sub-seed | **Crashes**: `Seed must be between 0 and 2**32 - 1`. See spec gap G-1 in §8. |
| V-12 | `streamlit` 1.64 requires `pyarrow != 25.0.0` | So keep the demo in its **own** virtualenv, away from the P0 environment |

---

## 3. Demo simplifications (each one is deliberate; say them out loud)

| ID | The spec says | The demo does | Why it is acceptable |
|---|---|---|---|
| D-1 | WAL, transactions, crash safety (§12, §15.4–15.7) | None. Steps run in order, not atomically. | Out of scope by your request |
| D-2 | Page and slot files (§14) | An append-only encrypted file, a key file and a plaintext index file (§4, step S12) | Keeps the §13.2 plaintext rules exactly, in a much simpler shape |
| D-3 | `curve25519-dalek` (§9.1) | libsodium through `rbcl`; pure-Python `expand_message_xmd` | Same group, same generators (V-4) |
| D-4 | Merlin hedged nonces (§9.6) | 64 bytes from `secrets.token_bytes`, reduced mod ℓ | The verifier never recomputes nonces (§9.6 says the derivation is "not consensus-critical"). Never use a seed. |
| D-5 | Ed25519 `verify_strict` (§9.8) | `cryptography`'s Ed25519 verify | Not strict about small-order keys; say so |
| D-6 | Pinned float order (§7.1, §7.2, §8.2) | Plain numpy sums in the demo | Only near-ties can change. C-18 must switch to the pinned order before any differential test (tip in step S7). |
| D-7 | Log checkpoint every 10,000 leaves plus on demand (§10.3) | Keep both rules in code; at 2,000 leaves only "on demand" fires | Same rule, smaller scale |
| D-8 | Witnesses must be independent (L-7) | 5 in-process witness keys, threshold 4 | The spec's v1 does the same |
| D-9 | Key erasure relies on the device (L-1); memory is zeroed (§12.8) | Overwrite with zeros and `os.fsync`; Python memory is not zeroed | Say it: an SSD may keep old copies, and Python cannot reliably wipe memory |
| D-10 | Collections (§3.1) | One collection, but a real random 16-byte `collection_id` | It appears in every message the protocol signs |
| D-11 | 90-day operator epochs (§9.8) | Epoch 0 throughout | A demo lasts minutes |
| D-12 | The independent Ledoit–Wolf oracle is a MUST (§6.2 step 7) | Optional for the demo | If you skip it, name the file `partition-demo.svp` and never use it as the official P1 artefact |

---

## 4. Setup

### 4.1 Order of work versus your running P0 encode

- **Do not install anything into the P0 `.venv` while `encode` runs.** Library versions must stay
  fixed for the whole run.
- Steps **S1–S5** need only `sciq_reference/embeddings.npy`, which is already finished, so you can
  start them now in a **separate** virtualenv.
- Steps that load `nq_1m/embeddings.npy` wait until `python prepare_data.py verify` prints
  `verify: OK`. That file is only assembled after the last shard.

### 4.2 Virtualenv (PowerShell, from the repo root — the folder that contains `datasets\`)

```powershell
py -3.13 -m venv .venv-demo
.\.venv-demo\Scripts\Activate.ps1
python --version                                   # 3.13.x
pip install "numpy==2.5.*" "pyarrow==25.0.*" "scikit-learn==1.9.*" "rbcl==1.1.2" "cryptography==50.0.*" "rich==15.0.*"
# optional, only for typing your own questions live (scene 9):
pip install "torch==2.14.*" --index-url https://download.pytorch.org/whl/cpu
pip install "sentence-transformers==6.1.*"
# optional, only for the web UI (step S16):
pip install "streamlit==1.64.*"
```

### 4.3 Five one-line checks (all must pass before step S1)

1. `python -c "import rbcl; print(rbcl.crypto_core_ristretto255_BYTES)"` → `32`
2. `python -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCMSIV as A; k=A.generate_key(256); print(len(A(k).encrypt(b'0'*12,b'x',b'')))"` → `17`
3. `python -c "import sklearn; print(sklearn.__version__)"` → `1.9.x`
4. `python -c "import numpy as np; print(np.load(r'datasets\processed\sciq_reference\embeddings.npy', mmap_mode='r').shape)"` → `(13679, 384)`
5. After step S3: your derived `H` and `G_0` equal the two hex strings in §0.2.

---

## 5. Folder layout and who owns what

One repository, laid out as spec §19.2. The demo lives in `demo/` inside the real project, not in a
separate repository (the reason is in `CLAUDE.md`, "Workflow").

```
sever-db/                            repo root (your C:\Users\saiki\final-vdb after `git init`)
  CLAUDE.md                          how we work; read first every session
  docs/
    SEVER-DB_SPECIFICATION.md        normative
    SEVER-DB_PROJECT_OVERVIEW.md     why, decisions, phases, limits
    SEVER-DB_DEMO_PLAN.md            this file
    PROGRESS.md  SPEC_GAPS.md  TRACEABILITY.md  notes/Sxx.md
  tools/data_prep/                   P0 (prepare_data.py)
  datasets/                          P0 output — read only; data files not in git
  golden/                            frozen vectors (Appendix B); committed
  python/
    sever_refmodel/                  PURE CORE → grows into C-18. No file writes, no AES, no clock.
      constants.py   domain strings and fixed parameters (§2.2, §2.3)
      errors.py      the typed errors of §17 (names exactly as in the spec)
      q24.py         normalisation check, quantise, dequantise, scalar(v) (§4)
      crypto.py      expand_message_xmd, generators, commit, point/scalar ops, proof, HMAC (§9.2–9.7)
      groups.py      group state, insert/delete arithmetic, members, canonical blob, assert_state_equivalent (§5)
      partition.py   read and verify partition.svp (§6.3)
      routing.py     nearest frozen group, Mahalanobis, destination rule, spawn ID (§7)
      search.py      group ranking, probe budget, scan, top-k (§8)
      merkle.py      RFC 9162 tree hash, inclusion and consistency proofs (§10.1)
      certificate.py TLV encode/parse of the 13 fields and tag 6; no signing (§11.1, §11.2)
    sever_partition/
      build.py       C-15: fit and write partition.svp (§6.2, §6.3)
  demo/                              DEMO-ONLY LAYER
    demo_config.json
    client.py        the user: Ed25519 key, r_t, C_t, signature, keychain (§3.3, §9.4, §16.2)
    vault.py         encrypted storage and the three-level key hierarchy (§13, simplified §14)
    witnesses.py     5 simulated witnesses (§10.4)
    engine.py        insert / delete / delete_user / search / stats (§15 without ACID)
    build_demo_db.py one-time load of the demo corpus
    run_demo.py      terminal demo: interactive menu and --scripted
    app.py           optional Streamlit UI
    verifier_py/     C-16 stand-in. Imports NOTHING from python/ or demo/.
      verify.py      standalone certificate verifier (§11.3)
      anchors.json   operator key, witness keys, generator golden values
  tests/
    refmodel/  demo/  verifier/      one test file per step: test_s06_groups.py, …
  demo_db/  client_keychain/         generated at run time; never committed
```

**Three dependency rules (write them at the top of each package; a test enforces each):**

1. `python/sever_refmodel` never writes files, never encrypts, never reads the clock. It receives
   randomness only from its caller (except proof nonces, D-4).
2. Nothing under `python/` imports from `demo/`. The reference model must not depend on the demo.
3. `demo/verifier_py` imports only the standard library, `rbcl` and `cryptography`. It re-derives its
   own generators, parses TLV with its own code, and checks Merkle paths with its own code (C-16:
   "shares no code with C-1…C-15").

---

## 6. The demo data (fix these choices in `demo/demo_config.json`)

| Setting | Value | Why |
|---|---|---|
| Reference set | All 13,679 SciQ rows (`sciq_reference/embeddings.npy`) | §6.2; never inserted into the index (Overview §10.1) |
| Demo corpus | The first **1,000** rows of `nq_1m/passages.parquet` with `judged == True`, plus the first **1,000** rows with `judged == False` | Answers plus distractors. Select by the `judged` column, not by row numbers. |
| Record ID | The `id` column (for example `doc123`) | Passes §3.2 |
| Stored text | The `text` column (already `title + " " + body`) | Overview §10.2 |
| Cohort (for `delete_user`) | The `cohort` column (the Wikipedia title) | Overview §10.8 |
| Insert order | Shuffle with `numpy.random.Generator(PCG64(sub_seed(42, b"stream")))` | Overview §10.6; makes the build reproducible |
| Demo queries | Test queries (`nq_queries`) that have at least one qrels passage in the corpus **and** in a searchable group after the build | Search needs something to find. Pick about 10. |
| Query vectors | Rows of `nq_queries/embeddings.npy` | No model needed at demo time |
| `k_results` | 10 | |

**What to expect, and use as a sanity check.** The earlier prototype measured about **89 %** of NQ
passages as out-of-distribution against SciQ groups (τ ≈ 25.5). So from 2,000 inserts expect
roughly 200–300 in frozen groups, about **8 spawned groups** of 200, and the remaining under-200
records **waiting in the holding area, unsearchable**. If the OOD rate comes out below 50 % or above
99 %, stop and check step S5.

**Spillover will not appear at this size, and that is correct.** A spawned group has room only if
`2·k·n_g < 3·N` (§7.3). After the first flush, `k = 129` and `n_g = 200`, so room needs
`N > 17,200`. With 2,000 records the check is always false. Show the numbers of that check live
rather than hiding it.

---

## 7. Build steps

Each step lists **what**, **spec**, **rules**, **traps** and **done when**. Do them in order; each
leaves something runnable. Write the test for a step before moving on.

### S1 — Constants and errors
- **What.** `constants.py`, `errors.py`.
- **Spec.** §2.2 (d = 384, f = 24, tolerance `8·2^-23`, 128 groups, cap 1,000,000, spawn 200,
  multiplier 1.5, probe 25 %, 64 buckets, 5 witnesses with threshold 4, ID length 1–256), §2.3
  (seven domain strings), §17 (error names).
- **Rules.** Domain strings are `bytes`, with lengths 41, 15, 21, 17, 14, 17, 15. Write the length
  next to each constant and assert it.
- **Traps.** `SEVERDB_POSK_V1`, not the old `SEVER_POSK`. Error messages must never contain a
  record ID, vector, key, `r_t` or text (§17).
- **Done when.** An import-time assertion checks all seven lengths.

### S2 — Vector arithmetic
- **What.** `q24.py`: `check_normalised(x)`, `quantise(x) → int32[d]`, `dequantise(x̃) → float64[d]`,
  `scalar(v) → 32 bytes`.
- **Spec.** §4.1–4.5.
- **Rules.** Input must be `float32` of length `d` (`WrongDimension`), finite (`NonFinite`), and have
  `abs(norm − 1) ≤ 8·2^-23` in float64 (`NotNormalised`). Quantise with
  `np.rint(x.astype(np.float64) * 2**24).astype(np.int32)`; `np.rint` rounds half to even.
  `scalar(v) = (v % ℓ).to_bytes(32, "little")`. Python's `%` already gives `ℓ − (|v| mod ℓ)` for
  negative `v`.
- **Traps.** Do **not** reject `abs(x̃) = 2^24` (the old demo did; the spec does not). Validate
  normalisation; never "fix" it by normalising for the caller.
- **Done when.** Golden checks pass: `scalar(0)` is 32 zero bytes, `scalar(-1)` encodes ℓ − 1, and
  `scalar(±2^44)` are correct (Appendix B item 4). Half-step inputs round to even (item 5). A one-hot
  vector is accepted.

### S3 — Cryptographic core
- **What.** `crypto.py`: `expand_message_xmd(msg, dst, 64)`, `generators(d)`, `commit(r, values)`,
  `point_add/sub`, `scalar_add/sub/mul`, `random_scalar()`, `scramble(k, cid, rid)`.
- **Spec.** §9.2, §9.3, §9.4, §9.7, §9.9.
- **Rules.**
  - `H = from_hash(xmd(b"H", DST_GEN, 64))`; `G_i = from_hash(xmd(b"G" + u32be(i), DST_GEN, 64))`.
    Use one `xmd` call per generator.
  - `r_t = crypto_core_ristretto255_scalar_reduce(secrets.token_bytes(64))`.
  - `commit(r, xs) = r·H + Σ scalar(x_i)·G_i`, using the **allow_scalar_zero** multiply (V-5).
  - `scrambled_id = HMAC-SHA-512(k_scramble, collection_id ‖ record_id_bytes)`, 64 bytes.
  - Decoding untrusted data: a point must pass `is_valid_point`; a scalar must be `< ℓ` as a
    little-endian integer; `C_t` must not be the identity (§9.9).
- **Traps.** RFC 9380's `xmd` uses `I2OSP(len, 2)` for the output length, a single zero byte, and
  `DST ‖ I2OSP(len(DST), 1)`. The block size for the zero-pad is **128 bytes** for SHA-512, not 64.
  If your `H` is wrong, this is almost always the cause.
- **Done when.** `H` and `G_0` equal §0.2. Also freeze `G_383` and
  `gdigest = SHA-512(H ‖ G_0 ‖ … ‖ G_383)` into `golden/` (Appendix B items 1–2). A random
  commitment test shows `Σ C_t == commit(Σ r_t, Σ x̃)`.

### S4 — Proof of knowledge
- **What.** `prove(r_post, S_post, C_S_post, ctx)` and `verify(proof, C_S_post, ctx)` in `crypto.py`.
- **Spec.** §9.5 (and D-4 for the nonces).
- **Rules.** `ctx = C_S_pre ‖ C_t ‖ scrambled_id ‖ u64be(database_lsn) ‖ collection_id`
  (152 bytes). The challenge is `c = scalar_reduce(SHA-512(DST_POSK ‖ C_S_post ‖ A ‖ ctx))` over a
  231-byte preimage. Responses are `z_r = k_r + c·r_post` and `z_i = k_i + c·scalar(S_i)`, all mod ℓ.
  `proof = A ‖ z_r ‖ z_0 … z_383` (12,352 bytes). Verify with
  `z_r·H + Σ z_i·G_i == A + c·C_S_post`.
- **Traps.** Assert the preimage is 231 bytes and the proof is 12,352 bytes. **Never** derive nonces
  from a seed: `prove` takes no RNG argument at all (§16.2, `SeededNonceForbidden`).
- **Done when.** Honest proofs verify. Flipping any byte of `A` or of one `z` fails. Swapping `A` and
  `C_S_post` in the preimage changes `c` (Appendix B item 3). A proof built for one `ctx` fails
  against another.

### S5 — Partition builder (C-15)
- **What.** `sever_partition/build.py` → `partition.svp` (or `partition-demo.svp`, D-12).
- **Spec.** §6.2 steps 1–7, §6.3.
- **Rules.**
  1. Quantise and dequantise all 13,679 SciQ rows first (step 1).
  2. Run `KMeans(n_clusters=128, init="k-means++", n_init=10, max_iter=300, tol=1e-4,
     algorithm="lloyd", random_state=…)`.
  3. Residuals `R = x̂ − μ_label`; run **one** `LedoitWolf(assume_centered=False).fit(R)`.
  4. `P = Σ^-1` by Cholesky: `L = cholesky(Σ)`, then invert `L` and use `P = L^-T L^-1`. Do not use
     `precision_` from sklearn, which uses `pinvh`.
  5. `τ = np.percentile(d_M, 99, method="linear")`.
  6. Write the artefact exactly per §6.3: big-endian, `sha256_reference` over the raw float32 rows,
     the encoder string `sentence-transformers/all-MiniLM-L6-v2@<commit from PINS.json>`, and
     `sha256_artefact` last.
- **Traps.**
  - **The seed** (V-11): `random_state = sub_seed(42, b"kmeans")` crashes. Use
    `sub_seed(42, b"kmeans") % 2**32` and record it as spec gap G-1.
  - "Pooled" means one fit over the stacked residuals, **not** an average of 128 per-group fits.
    Averaging moves τ by about 3 units (DB-10). That is P1's must-fail test.
  - For the spec's sequential summation order in d_M, `np.cumsum(P * δ, axis=1)[:, -1]` is
    sequential. `P @ δ` and `np.sum` are not (D-6).
- **Done when.** τ is a finite positive number, near the prototype's 25.5 (not equal: a different
  seed and library version). `P` is finite and symmetric. The file re-reads with the hash verified.
  Running the build twice gives the same `sha256_artefact`.

### S6 — Groups and exact deletion
- **What.** `groups.py`: a `Group` (id, kind, `S` int64[d], `n`, `C_S`, `r_agg`, centroid, members
  sorted by ID bytes), `apply_insert`, `apply_delete`, `canonical_blob()`, and
  `assert_state_equivalent(a, b)`.
- **Spec.** §5.1–5.6.
- **Rules.**
  - The initial state is `S = 0`, `n = 0`, `r_agg = 0`, `C_S = 32 zero bytes`.
  - Insert and delete are the four-line updates of §5.3.
  - Delete first checks membership; if absent → `AlreadyAbsent`, nothing changes.
  - Excision physically removes the member. There is no flag and no placeholder.
  - Blob: `b"SEVERG" ‖ u16be 1 ‖ u16be d ‖ u64be n ‖ i64be×d S ‖ C_S ‖ r_agg ‖ u64be count ‖`
    members ascending by ID bytes as `u16be id_len ‖ id ‖ i64be×d x̃`. Serialise vectors with
    `.astype(">i8").tobytes()`.
  - The equivalence helper compares **all five** fields independently: `S`, `n`, `C_S`, blob, and
    member-ID list.
- **Traps.**
  - Sort by **UTF-8 bytes** (`key=lambda m: m.id.encode()`), not by Python string order. They differ
    for non-ASCII IDs.
  - The frozen group's centroid comes from the artefact and **never** from `S/n`.
  - Enforce the cap `n ≤ 1,000,000` on insert (`GroupCapacityExceeded`).
- **Done when.**
  - Any insertion order gives an identical blob.
  - Insert-then-delete returns bit-identical state.
  - Corrupting each of the five fields separately is caught (P1 must-fail).
  - A fixed three-member group's blob is frozen into `golden/` (Appendix B item 8).

### S7 — Routing, holding area and spawning
- **What.** `routing.py`: `route(x̃, state) → frozen id | spawned id | "holding"`, `spawn_id(ids)`,
  and the flush arithmetic.
- **Spec.** §7.1–7.7, §5.6.
- **Rules.**
  - Nearest frozen centroid by squared Euclidean distance on `x̂ = x̃/2^24` in float64. Ties go to
    the smaller label.
  - `d_M = sqrt(δᵀ P δ)`; `q < 0` → `IntegrityViolation`. In-distribution iff `d_M ≤ τ`.
  - OOD: first spawned groups with room (`2·k·n_g < 3·N`, in integers, with `k` and `N` from before
    the insert), nearest centroid, ties by group-ID bytes; else the holding area.
  - The holding area stores `x̃` and `r_t` but has no accumulator and is not counted in `N`.
  - When it reaches **exactly 200**, flush in the same operation:
    1. Sort by ID bytes.
    2. `spawn_id = "spawn-" + sha256(‖ u16be(len) ‖ id).hexdigest()[:16]`.
    3. Build the group: sum `x̃` into `S`, `r_t` into `r_agg`, and compute
       `C_S = commit(r_agg, S)`.
    4. Centroid `μ_i = (S_i / 2^24) / 200`, frozen.
    5. `N += 200`, `k += 1`.
- **Traps.**
  - Routing must be a pure function: no clock, no counter, no "latest group".
  - An ID that already exists → `IntegrityViolation`.
  - After a flush, assert `C_S == Σ C_t` of the 200. It is a free check of V-7.
  - Counters (§7.6): holding-area inserts and deletes never change `N`.
- **Done when.** The three §7.7 tests pass:
  1. The same `(x̃, state)` gives the same destination.
  2. Changing only the group creation order gives the same destination.
  3. The same inputs and order give an identical state.

  The spawn ID of a fixed 200-ID cohort is frozen into `golden/` (Appendix B item 7).

### S8 — Search
- **What.** `search.py`: `search(q, k_results) → [(record_id, score)]` plus a trace (the ranked
  groups, the probed set, and `p`) for display.
- **Spec.** §8.1.
- **Rules.**
  1. Rank **all** frozen and spawned groups, **empty ones included**, by
     `D_g = Σ((f64)q_i − μ_{g,i})²`. Sort by `(D_g, group-ID bytes)`.
  2. `p = ceil(0.25·k)`, for example `ceil(0.25·136) = 34`.
  3. Score each member of the probed groups as float32 squared L2 against `x̂` in float32.
  4. Sort by `(score, record-ID bytes)` and return the top k.
- **Traps.**
  - Holding-area records never appear.
  - Use integer arithmetic for the probe count: `p = (k + 3) // 4`. `math.ceil(0.25*k)` is also
    exact here, but integers avoid the question.
  - Keep a float32 mirror of each member's `x̂` (§12.6) so search doesn't re-dequantise every time.
- **Done when.**
  - A deleted record never appears afterwards (INV-9).
  - The other results' scores are **bit-identical** before and after an unrelated deletion. Compare
    `np.float32(score).tobytes()`.
  - Recall@10 against brute force over all searchable records is reported.

### S9 — Transparency log
- **What.** `merkle.py`: `leaf_hash`, `root(leaves)`, `inclusion_path(i, n)`,
  `verify_inclusion(...)`, `consistency_path(m, n)`, `verify_consistency(...)`.
- **Spec.** §10.1, §10.2; RFC 9162 §2.1.
- **Rules.**
  - `leaf_hash = SHA-256(0x00 ‖ leaf)`; `node = SHA-256(0x01 ‖ L ‖ R)`.
  - Split at the **largest power of two strictly less than n**.
  - The empty tree's root is `SHA-256(b"")`.
  - Insert leaf (209 bytes): `0x01 ‖ collection_id ‖ scrambled_id ‖ C_t ‖ user_pk ‖ user_sig`.
  - Delete leaf: `0x02 ‖ certificate`.
  - `database_lsn` is the 0-based leaf index.
- **Traps.** Implement RFC 9162's own verification algorithms (§2.1.3.2 and §2.1.4.2), not a
  home-made shortcut. It is easy to get an off-by-one that only fails at non-power-of-two sizes.
- **Done when.**
  - For every tree size 1–64 and every leaf, inclusion verifies. For every pair m ≤ n ≤ 64,
    consistency verifies.
  - Tampering any path hash fails.
  - The 7-leaf proofs are frozen into `golden/` (Appendix B item 9).

### S10 — Log checkpoints and witnesses
- **What.** `demo/witnesses.py` and checkpoint signing inside the engine.
- **Spec.** §9.8, §10.3, §10.4.
- **Rules.**
  - Checkpoint message = `DST_STH ‖ u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch`
    (66 bytes), signed by the operator.
  - Each witness signs `DST_COSIGN ‖ <66 bytes>` (83 bytes) **only after** verifying the consistency
    proof from the last checkpoint it cosigned.
  - A checkpoint is witnessed with ≥ 4 valid cosignatures.
  - Issue one at every multiple of 10,000 leaves, and on demand before a deletion whose insert leaf
    is not yet covered.
- **Traps.** The first checkpoint needs a starting point. Define a genesis checkpoint
  (tree_size 0, root = `SHA-256(b"")`) at database creation (spec gap G-4).
- **Done when.** A witness refuses a checkpoint whose history was rewritten (swap an old leaf and
  re-root; its consistency proof fails).

### S11 — Certificates (encoding in the core, signing in the engine)
- **What.** `certificate.py`: `encode(fields) → bytes`, `parse(bytes) → fields` (strict), and the
  tag-6 structure.
- **Spec.** §11.1, §11.2.
- **Rules.**
  - Tags 1…13 appear in order, each exactly once, as `u8 tag ‖ u32be len ‖ value`. Then
    `0xFF ‖ u32be 64 ‖ sig`, where the operator signature covers `DST_CERT ‖ all preceding bytes`.
  - Tag 6 is `u8 1 ‖ insert_leaf(209) ‖ u64be leaf_index ‖ (u64be tree_size ‖ root ‖
    u64be ts_ms ‖ u32be epoch ‖ sig64) ‖ u8 path_len ‖ hashes`.
  - Tag 7 is `u8 count ‖ count×(u8 witness_index ‖ u32be witness_epoch ‖ sig64)`.
  - For a holding-area deletion, tags 2, 3 and 4 have length 0, tag 11 = 0 and tag 12 = 1.
- **Size check (use it as a test).** With 5 cosignatures, a group-deletion certificate is
  **13,421 + 32 × path_len bytes**. At the spec's 21-hash path that is exactly 14,093, matching
  Appendix A. With 2,000 leaves the path is about 11 hashes, so ≈ **13,773 bytes**. A holding-area
  certificate is **1,005 + 32 × path_len** bytes.
- **Done when.** Encode → parse → encode is byte-identical. The parser rejects: a missing, repeated
  or out-of-order tag, a wrong fixed length, and trailing bytes.

### S12 — Encrypted storage and key hierarchy (the vault)
- **What.** `demo/vault.py`. Files inside `demo_db/`:
  - `blobs.bin` — **append-only**; every ciphertext ever written, never overwritten.
  - `keys.bin` — fixed 512-byte slots holding group keys, overwritten with zeros on erasure.
  - `index.json` — **only** the plaintext the spec allows (§13.2): group IDs, kinds, `n`, `C_S`,
    centroids, key versions, bucket versions, `scrambled_id`s, and offsets into `blobs.bin`.
  - `public/` — log leaves, checkpoints, certificates.
- **Spec.** §13.1–13.5; slot payload format §14.4; header fields §14.3.
- **Rules.**
  - **Three levels.** The group key `GK_g` lives only in `keys.bin`. 64 bucket keys are wrapped
    under `GK_g`. Each record key `RK_t` is wrapped under bucket `b(t) = scrambled_id[0] % 64`. The
    holding area has its own `GK` and 64 buckets too.
  - **AES-256-GCM-SIV.** Use a random 12-byte nonce and store `nonce ‖ ciphertext ‖ tag`. The
    associated data follows the §13.2 table exactly, with `group_id` zero-padded to 32 bytes
    everywhere (spec gap G-2).
  - **Payload plaintext (1,835 bytes, §14.4):** `u16be id_len ‖ id padded to 256 ‖
    u64be insert_leaf_index ‖ u8 has_rt ‖ r_t(32) ‖ x̃ as i32be×d`. Passage text is a separate
    ciphertext under `RK_t` with AD tag `0x02`.
  - **Rotation on every departure** (a delete from a group or from the holding area, or a flush out
    of the holding area), §13.3 steps 1–5:
    1. New `GK` (version + 1).
    2. New bucket key for each bucket that lost a record.
    3. Re-wrap all 64 bucket keys under the new `GK`.
    4. Re-wrap the surviving record keys of the rotated buckets.
    5. Re-encrypt `S ‖ r_agg` (not for the holding area).

    Append all new ciphertexts to `blobs.bin`, write the new `GK` into a free slot, `fsync`, **then**
    overwrite the old slot with zeros and `fsync` (the §13.4 order, minus the WAL).
  - Joining a group (insert, or moving in by a flush) never rotates anything.
- **Traps.**
  - Nothing secret may reach `index.json`: no record IDs, no text, no `S`, no `r_agg`, no keys.
    `n`, `C_S` and centroids are allowed (§13.2).
  - Zero the key slot in place: `open("keys.bin", "r+b")`, `seek`, write 512 zero bytes, `flush`,
    `os.fsync`.
  - Because `blobs.bin` is append-only, the **old** accumulator ciphertext is still on disk after a
    delete. That is the point of scene 7: it is there, and it cannot be read.
- **Done when.** A test deletes a record and then:
  - Tries every key still in `keys.bin` against the record's old wrapped key, payload, and the old
    `S ‖ r_agg`. Every attempt fails with `InvalidTag`, or the needed key version is gone.
  - Byte-scans `demo_db/` for the record ID, a 40-character chunk of its text, and its `x̃` bytes.
    There are 0 hits.

### S13 — The client (the user's side)
- **What.** `demo/client.py`: `UserKey.generate()`,
  `prepare_insert(cid, record_id, x) → (request, secret_r_t)`, and a keychain file
  `client_keychain/` **outside** `demo_db/`.
- **Spec.** §3.3, §9.4, §9.8, §16.2.
- **Rules.** The client quantises with **the same** `q24.py`, draws `r_t`, computes `C_t`, and signs
  `DST_INSERT ‖ collection_id ‖ C_t` (65 bytes). Its keychain keeps `record_id → r_t` and the user's
  private key.
- **Traps.** The engine receives `r_t` at insert only to add it into `r_agg`. It stores `r_t` only
  for holding-area records, and only encrypted (§9.4).
- **Done when.** A request signed by one user and replayed with another user's key fails with
  `BadUserSignature`.

### S14 — The engine (wiring, §15 without ACID)
- **What.** `demo/engine.py` with the §16.1 surface in Python: `create_collection(artefact)`,
  `insert(req)`, `delete(record_id, r_t)`, `delete_user(list)`, `search(q, k)`,
  `certificate(lsn)`, `latest_log_checkpoint()`, `stats()`, and a demo-only
  `group_snapshot(group_id)`.
- **Insert, in §15.1 order:**
  1. Validate the vector and the ID; reject a live duplicate with `DuplicateRecord`.
  2. Quantise; recompute `C_t`, else `CommitmentMismatch`; verify the signature, else
     `BadUserSignature`.
  3. Route; check the cap.
  4. Encrypt the payload and text; wrap `RK_t`.
  5. Update the accumulator: `S`, `n`, `r_agg`, `C_S`, `N`.
  6. Append the insert leaf; checkpoint if the size is a multiple of 10,000.
  7. Flush if the holding area reached 200.
  8. Return `(database_lsn, placement)`.
- **Delete, in §15.3 order:**
  1. Look up `scrambled_id`; if absent → `AlreadyAbsent`, no certificate.
  2. Decrypt; recompute `C_t` from the stored `x̃` and the supplied `r_t`; it must equal the insert
     leaf's `C_t`, else `AuthorisationFailed`.
  3. If the insert leaf is not covered by a witnessed checkpoint, issue one.
  4. Compute the post-state, `ctx` with `database_lsn = current tree size`, the proof and the
     certificate; sign it.
  5. Rotate keys and append the new ciphertexts.
  6. Apply the change to memory.
  7. Append the delete leaf.
  8. Zero the old key slot.
  9. Return the certificate.
- **`delete_user`.** Steps 1–4 for each record in list order, so consecutive certificates for the
  same group **chain**: `C_S_pre` of one equals `C_S_post` of the previous one.
- **Startup check.** On load, recompute `C_S == commit(r_agg, S)` for every group (INV-3) and check
  `N = Σ n` and `k` = the number of frozen plus spawned groups (INV-8). About 5 s for ~136 groups.
- **Done when.** An end-to-end test covers: insert → search finds it → delete → certificate verifies
  in `verifier_py` → search no longer finds it → a repeat delete returns `AlreadyAbsent`.

### S15 — The independent verifier
- **What.** `demo/verifier_py/verify.py <cert_file> --anchors anchors.json`. It prints each §11.3 step
  with PASS or FAIL.
- **Spec.** §11.3 steps 1–8. Anchors: operator public key for epoch 0, the 5 witness public keys,
  and the generator golden values.
- **Rules.** It re-derives `H` and `G_i` with its **own** `xmd` code and compares them with the
  anchors before doing anything else. It parses TLV and checks the Merkle path with its own code.
- **Done when.** It accepts every honest certificate, and **rejects** each of these, naming the
  failing step:
  - (a) a flipped byte in tag 4 → step 6 (proof);
  - (b) a different `C_t` in tag 1 → step 3 (leaf mismatch);
  - (c) only 3 cosignatures → step 4;
  - (d) the proof from certificate A pasted into certificate B → step 6, because `ctx` differs;
  - (e) `database_lsn ≤ leaf_index` → step 5;
  - (f) any change after signing → step 2.

### S16 — Presentation layer
- **What.** `demo/run_demo.py` (rich terminal, **must have**) with `--scripted` (all scenes, no
  keyboard) and an interactive menu. Optionally `demo/app.py` in Streamlit.
- **Rules.** Build the database once with `build_demo_db.py` (≈ 2,000 × ~75 ms ≈ **3 minutes**).
  After that, the demo loads the database (step S14 startup) instead of rebuilding it. In Streamlit,
  hold the engine in `st.cache_resource`; Streamlit reruns the script on every click.
- **Traps.** On demo day, set `$env:HF_HUB_OFFLINE="1"` so the optional live encoder never touches
  the network.

### S17 — Self-check before every rehearsal
- `pytest` passes: one file per step S2–S15 (`tests/refmodel/`, `tests/demo/`, `tests/verifier/`).
- `python demo/run_demo.py --scripted` finishes with every scene PASS.
- A test asserts `demo/verifier_py` imports nothing from `python/` or the rest of `demo/`, and nothing under `python/` imports `demo/`.
- A test asserts `index.json` contains no record ID and no text from the corpus.

---

## 8. Spec gaps found while cross-referencing (fix them in the spec; P1's exit gate requires it)

| ID | Where | Problem | Proposed fix |
|---|---|---|---|
| **G-1** | §6.2 step 2, Overview §10.6 | `random_state = seed_kmeans` is a u64, but scikit-learn only accepts seeds below 2^32. **The build crashes as written** (V-11). | Specify `random_state = seed_kmeans mod 2^32`, and record it as a new decision. |
| **G-2** | §13.2 | `group_id` is "zero-padded to 32" in the wrapped-record-key AD but unspecified in the wrapped-bucket-key and `S ‖ r_agg` ADs. §14.3 stores it zero-padded. | Say "`group_id` (32, zero-padded)" in all three rows. |
| **G-3** | §19.1 C-18 | The reference model "depends on C-7 via Python binding", but C-7 is built in P2, after P1. | Let C-18 use libsodium via `rbcl` (a genuinely independent crypto implementation, which makes the differential test stronger), and record the decision. |
| **G-4** | §11.3 inputs, §10.4 | A "genesis log checkpoint" is listed as a verifier input but never defined, and no verification step uses it. Witnesses need a starting checkpoint. | Define genesis as tree_size 0 with root `SHA-256("")`, signed at creation. Either use it in a step or drop it from the inputs. |

---

## 9. The demo, scene by scene (about 20 minutes)

| # | Scene | What you do | What your guide sees and why it matters |
|---|---|---|---|
| 1 | The problem | One slide: deleting from an IVF index usually leaves centroids and summaries that still carry the data | Motivation (Overview §1.2) |
| 2 | From text to integers | Show a passage, its 384 floats, its Q24 integers, and `x̂` back | Exact integers are what make subtraction exact (§4) |
| 3 | The frozen map | `stats()`: 128 frozen groups, τ, the artefact hash; then the build results: frozen vs spawned vs holding counts and the OOD rate | Groups are fixed on public data and never move (§6) |
| 4 | Routing live | Insert one new passage; show its nearest group, `d_M` vs τ, the destination, and the `2·k·n < 3·N` check | Drift handling (§7) |
| 5 | Search | Pick a demo query; show the ranked groups, the probed 25 % (34 of 136 if 8 groups spawned), the top 10 with text, and the relevant ones marked; recall vs brute force | It works as a vector database (§8) |
| 6 | Delete + exactness | Delete the top hit. Show `S`, `n`, `C_S` before and after. Rebuild that group from scratch from its survivors in reverse order: **EXACT** on all five fields. Then replay with fresh blinding values: `S` and `n` match, `C_S` doesn't → **rejected**. | The central claim (§5.5) |
| 7 | Crypto-shredding | Show the record's old ciphertext still in `blobs.bin` at the same offset, byte for byte. Try every remaining key → fails. Scan `demo_db/` for its ID and text → 0 hits. The old `S ‖ r_agg` ciphertext is also still there and also unreadable, so `S_pre − S_post` cannot be computed. | Physical erasure without trusting the disk (§13.5, INV-12) |
| 8 | The receipt | Save the certificate (~13.8 KB); run `verify.py` in a **fresh terminal**: every step PASS | Anyone can check it without the database (§11.3) |
| 9 | Attacks | Flip one byte → REJECT (step 6). Only 3 witnesses → REJECT (step 4). Delete with the wrong `r_t` → `AuthorisationFailed`. Delete twice → `AlreadyAbsent`, no certificate. Counter-shaped ID `"42"` → `InvalidRecordId`. | The checks are real |
| 10 | Delete a person | `delete_user` on one cohort (a Wikipedia title); show the certificates chaining | Deleting "everything about X" (§15.3) |
| 11 | Honest limits | The D-list in §3, especially D-1, D-4, D-8 and D-9, plus L-1 and L-7 | Credibility |

Two questions to expect, with answers ready:

- **"The text is still in your datasets folder."** Yes: those are the public input files standing in
  for user data (L-22). The claim is about the database directory, and the scan in scene 7 covers
  exactly that.
- **"Why are some passages not searchable?"** They are in the holding area, waiting for 200
  out-of-distribution records to form a group (§7.4). They are still deletable at once, with a
  holding-area certificate.

---

## 10. Order of work and effort

Each tier ends with a working demo, so a deadline cuts features, not correctness.

| Tier | Steps | Adds | Rough effort |
|---|---|---|---|
| A | S1–S8, S13, a thin S14, S16 terminal | Real data, partition, routing, spawning, search, exact deletion and scenes 2–6 | 4 days |
| B | S9–S11, S15 | Log, witnesses, proof, certificate, verifier; scenes 8–10 | 3 days |
| C | S12 | Encrypted storage and crypto-shredding; scene 7 | 2 days |
| D | Streamlit, live typed queries, a spillover build with more than 20,000 records | Polish | 1–2 days |

Start S1–S5 now (SciQ is ready). Start S14's data loading after `verify: OK`.

---

## 11. Pre-demo checklist

- [ ] `pytest` all green; `run_demo.py --scripted` all PASS on the **demo laptop**
- [ ] `demo_db/` built fresh this week; `build_demo_db.py` output saved (counts, τ, OOD rate)
- [ ] The demo query list shows at least one relevant hit for each query
- [ ] `verifier_py` runs from a separate terminal with only `anchors.json`
- [ ] `$env:HF_HUB_OFFLINE="1"` set if using live queries; laptop on power; sleep disabled
- [ ] A backup: a screen recording of `--scripted`
- [ ] The limits slide (§3 and §9 scene 11) is in the deck
