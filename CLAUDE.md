# CLAUDE.md — SEVER-DB

Read this file first in every session. It says what the project is, where the truth lives, how we
work together, and what "done" means for each stage. It contains no code on purpose: behaviour is
defined by the specification, and tests are derived from the specification, not from the code.

---

## 1. The project in six lines

SEVER-DB is a vector database with **provable deletion**. Each group of vectors keeps an exact
integer sum `S` and a count `n` (vectors are quantised to Q24 integers), so deleting a vector
subtracts it exactly. A Pedersen commitment `C_S` to each group, a public RFC 9162 transparency log
and a signed deletion certificate let anyone verify a deletion without database access. Everything
secret is stored encrypted under a three-level key hierarchy, and every deletion destroys the old key
(crypto-shredding). The engine will be Rust (P2–P9); the **current track is the Python demo**, whose
pure core becomes the reference model C-18 of phase P1.

---

## 2. Sources of truth (in priority order)

| # | Document | Role |
|---|---|---|
| 1 | `docs/SEVER-DB_SPECIFICATION.md` (cite as **§N**) | **Normative.** What the software must do, byte for byte. |
| 2 | `docs/SEVER-DB_PROJECT_OVERVIEW.md` (cite as **Overview §N**, **DB-N**, **L-N**) | Why: decisions, phases, testing strategy, limits. |
| 3 | `docs/SEVER-DB_DEMO_PLAN.md` (cite as **Plan §N**, **S-N**, **D-N**, **G-N**) | How the demo is built: steps S1–S17, simplifications D-1…D-12, spec gaps G-1…G-4. |
| 4 | `docs/PROGRESS.md` | Where we are right now. |
| 5 | The code | Must agree with 1–3. When it disagrees, the code is wrong or the spec has a gap. |

- **The spec wins.** If code and spec disagree, fix the code, or record a gap in `docs/SPEC_GAPS.md`
  and fix the spec **in the same commit** with a decision entry (Overview §13.4). Never change the
  spec quietly to match code.
- **The only allowed deviations in the demo are D-1…D-12 (Plan §3).** Anything else is a bug or a
  new gap.
- When explaining or reviewing, **always cite the section** (for example "§5.4, idempotent delete").

---

## 3. How we work together

The user is building this to **understand it deeply and think independently**. Claude is a pair
programmer and teacher, not a code generator.

### 3.1 Modes (the user names one; default is **coach**)

| Mode | What Claude does | What Claude does not do |
|---|---|---|
| **coach** (default) | Points to the spec sections for the task, asks what the user thinks the rule means, reviews code against the spec, and finds bugs by asking questions first ("what happens when `n` is 0?") | Write implementation code |
| **explain** | Explains a concept or spec section from first principles, with a small worked example in numbers | Jump ahead to later stages |
| **quiz** | Asks 3–5 questions about the current stage; the user answers; Claude corrects | Give answers before the user tries |
| **review** | Reads the diff, checks each rule of the stage's spec sections, lists findings with § and severity | Rewrite the code itself |
| **tests** | Proposes test cases as plain-language descriptions, with the § each checks and whether it is a must-fail | Write the implementation |
| **write** | Only when the user says "write it": writes the code, marks each rule with a `§` comment, then asks the user 2 questions to confirm they can explain it | Write more than was asked |

### 3.2 Standing behaviour

- Before suggesting anything, check `docs/PROGRESS.md` for the current stage and stay inside it.
- Prefer the smallest next step. One function, one test, one concept at a time.
- If the user's idea contradicts the spec, say so plainly, quote the rule, and let them fix it.
- If something is unclear in the spec, say it is unclear. Don't invent an answer; propose a gap
  entry.
- Never claim a test passes without running it. Never mark a stage done without its checklist (§4).
- Explanations use plain words first, then the precise term.

### 3.3 Session rituals

- **Start:** read `docs/PROGRESS.md`. State in 3 lines: current stage, what is done, the next small
  step.
- **End:** draft an update to `docs/PROGRESS.md` (done, next, open questions); the user confirms it.

---

## 4. The stage loop (every stage, S1–S17)

1. **Read.** Claude lists the spec sections for the stage (table in §6). The user reads them.
2. **Explain back.** The user writes 5–10 lines in `docs/notes/Sxx.md`: what the stage does, and why,
   in their own words. Claude corrects misunderstandings.
3. **Tests first.** From the stage's *done when* and *sabotage* lists, the user writes the tests.
   Each test names the rule it checks (§6.3 of this file).
4. **Implement.** The user writes the code until the tests pass.
5. **Sabotage.** For each sabotage item, deliberately break the code, confirm a test goes **red**,
   then revert. A test that never fails proves nothing (Overview §9.2).
6. **Review.** Claude reviews the diff against every rule in the stage's spec sections.
7. **Trace.** Add rows to `docs/TRACEABILITY.md` (spec rule → test name). This is P1.G3.
8. **Close.** Update `docs/PROGRESS.md`, commit, merge the stage branch, and tag at the end of a tier.

A stage is **done** only when steps 3–7 are complete.

---

## 5. Workflow: repository, branches, commits

- **One repository, not a separate demo repository.** The demo's pure core (`python/sever_refmodel`)
  *is* the start of C-18, the reference model the Rust engine will be tested against (DB-4), and
  `python/sever_partition` *is* C-15. A second repository would create two copies that drift apart.
  The old prototype demo needed a whole `_bootstrap.py` isolation system just to manage its copied
  core; avoid that. Demo-only code lives in `demo/` and nothing in `python/` may import it.
- Layout: Plan §5 (it follows spec §19.2).
- **Branches:** `main` is always green. One branch per stage: `s03-crypto`, `s06-groups`, and so on.
  Merge when the stage loop (§4) is complete.
- **Tags:** `demo-tier-a`, `demo-tier-b`, `demo-tier-c` (Plan §10), and `demo-shown` for the version
  shown to the guide.
- **Commit messages:** `S06: canonical group blob and five-field equivalence (§5.5)`. A spec change
  goes in the same commit as its gap entry.
- **Never commit:** `datasets/raw/`, `datasets/processed/` data files, `.venv*`, `demo_db/`,
  `client_keychain/` (it holds the user's secret `r_t` values and private key). **Do commit:**
  `datasets/PINS.json`, `datasets/MANIFEST.sha256`, `datasets/processed/meta.json`, and `golden/`.
- A private GitHub remote is recommended as a backup.

---

## 6. Current track: the demo, stages S1–S17

Full detail for every stage is in **Plan §7**. This table is the contract: goal, spec, and the tests
that decide "done". "Sabotage" items are from Overview §9.2 where one applies.

### 6.1 Stages

| Stage | Goal | Spec | Becomes | Done when (tests) | Sabotage that must turn a test red |
|---|---|---|---|---|---|
| **S1** Constants, errors | Every fixed parameter and domain string in one place | §2.2, §2.3, §17 | C-18 | All seven domain-string lengths asserted (41, 15, 21, 17, 14, 17, 15); every §17 error name exists | Change one domain-string byte |
| **S2** Vector arithmetic | Float vectors become exact integers | §4.1–4.5 | C-18 | Non-finite, wrong-dimension and unnormalised input rejected with the §17 error; half-steps round to even; `scalar(v)` golden values for 0, 1, −1, ±2^44 (App. B 4, 5); **a one-hot vector is accepted** | Round half away from zero; normalise instead of rejecting |
| **S3** Crypto core | Generators, commitments, scrambled IDs | §9.2–9.4, §9.7, §9.9 | C-18 | `H` and `G_0` equal the golden hex (Plan §0.2); `G_383` and `gdigest` frozen (App. B 1, 2); `Σ C_t == commit(Σ r_t, Σ x̃)`; zero components and empty groups give the identity; non-canonical point or scalar rejected | Accept a non-canonical encoding; derive all generators from one `xmd` call |
| **S4** Proof of knowledge | The operator proves it knows the post-deletion state | §9.5, D-4 | C-18 | 231-byte preimage; 12,352-byte proof; honest proofs verify; any flipped byte fails; a proof moved to another `ctx` fails; the swap-order vector frozen (App. B 3) | Swap the challenge preimage order; omit `ctx` from the challenge; reuse a proof nonce |
| **S5** Partition builder | 128 frozen groups, pooled Ledoit–Wolf precision matrix, τ | §6.2, §6.3, G-1 | C-15 | Artefact re-reads with its hash verified; two builds give the same hash; τ finite, near 25; `P` finite and symmetric; oracle agreement (required for the official P1 artefact, optional for the demo, D-12) | Per-group Ledoit–Wolf averaging must change τ and fail the oracle check (P1 must-fail) |
| **S6** Groups, exact deletion | `S`, `n`, `r_agg`, `C_S` move together; deletion is exact | §5.1–5.6 | C-18 | Any insertion order gives the same blob; insert-then-delete is bit-identical; five-field equivalence catches each field corrupted **separately**; absent delete returns `AlreadyAbsent` and changes nothing; cap enforced; 3-member blob frozen (App. B 8) | Flip a bit of a sum; skip the count decrement; subtract twice on retry; compare only 2 of 5 fields |
| **S7** Routing, holding area, spawning | Out-of-distribution data forms spawned groups of exactly 200 | §7.1–7.7, §5.6 | C-18 | The three §7.7 purity tests; flush at exactly 200; spawn ID from sorted IDs, fixed-cohort ID frozen (App. B 7); after a flush `C_S == Σ C_t`; `N` and `k` counters follow §7.6 | Route by recency; buffer before spillover; spill into the group being created |
| **S8** Search | IVF-flat with a 25 % probe | §8.1 | C-18 | Empty groups count in `p = ceil(k/4)`; ties broken by ID bytes; a deleted record never appears (INV-9); other scores are bit-identical after an unrelated delete; recall@10 vs brute force reported | Skip empty groups in the probe budget; keep a deleted vector in the search mirror |
| **S9** Merkle log | RFC 9162 tree, inclusion and consistency | §10.1, §10.2 | C-18 | Inclusion verifies for every leaf of trees of size 1–64; consistency for every m ≤ n ≤ 64; a tampered path fails; 7-leaf proofs frozen (App. B 9) | Split at the wrong power of two; drop the 0x00/0x01 prefixes |
| **S10** Log checkpoints, witnesses | Signed tree heads, 5 witnesses, threshold 4 | §9.8, §10.3, §10.4, G-4 | demo | 66-byte and 83-byte messages; on-demand checkpoint before a delete; a witness refuses rewritten history | Cosign without checking consistency |
| **S11** Certificate encoding | Deterministic 13-field TLV | §11.1, §11.2 | C-18 | Encode→parse→encode identical; size `13,421 + 32 × path_len` bytes (group), `1,005 + 32 × path_len` (holding); parser rejects missing, repeated or out-of-order tags, wrong lengths and trailing bytes | Accept tags out of order |
| **S12** Vault and crypto-shredding | Encrypted at rest; old keys destroyed on every departure | §13.1–13.5, §14.3–14.4, G-2 | demo | After a delete: every remaining key fails to open the old record key, payload and old `S ‖ r_agg`; a byte scan of `demo_db/` finds 0 hits for the record ID, its text and its `x̃` | Skip group-key rotation; skip bucket-key rotation; skip holding-area rotation on flush; write an unwrapped key to disk; reuse an AEAD nonce |
| **S13** Client | The user's side: keys, `r_t`, `C_t`, signature | §3.3, §9.4, §9.8, §16.2 | demo | Same quantiser as the engine; a request replayed under another user's key fails `BadUserSignature` | Sign a message missing the domain string |
| **S14** Engine | Insert, delete, `delete_user`, search, in §15 order (no ACID, D-1) | §15.1, §15.2, §15.3, §16.1, §21 | demo | End to end: insert → found → delete → certificate verifies → not found → repeat delete gives `AlreadyAbsent`; wrong `r_t` gives `AuthorisationFailed`; `delete_user` certificates chain; startup checks INV-3 and INV-8 | Skip the membership check before subtracting |
| **S15** Independent verifier | Anyone can check a certificate | §11.3 | C-16 stand-in | Accepts every honest certificate; rejects Plan S15 cases (a)–(f), naming the failed step; imports nothing from `python/` or `demo/` | Accept three of five cosignatures; skip the `C_S_post + C_t == C_S_pre` check; accept a proof reused in another certificate; accept cosignatures over a different log checkpoint; accept a wrong `group_emptied_by_this_deletion` (P6 must-fail) |
| **S16** Presentation | Terminal demo (must), Streamlit (optional) | Plan §9 | demo | `run_demo.py --scripted` runs all 11 scenes with PASS | — |
| **S17** Self-check | Rehearsal gate | Plan §7 S17, §11 | demo | All tests green; dependency-rule tests pass; `index.json` contains no record ID or text | — |

### 6.2 Tiers (each ends with a working demo; Plan §10)

- **Tier A:** S1–S8, S13, a thin S14, S16 terminal. Scenes 2–6.
- **Tier B:** S9–S11, S15. Scenes 8–10.
- **Tier C:** S12. Scene 7.
- **Tier D (optional):** Streamlit, live typed queries, a spillover build with more than 20,000
  records.

### 6.3 Test conventions

- `pytest`. One file per stage: `tests/refmodel/test_s06_groups.py`, `tests/demo/test_s12_vault.py`,
  `tests/verifier/test_s15_verify.py`.
- Test names say the rule: `test_s06_delete_absent_is_noop`. The first docstring line cites the
  section: `§5.4 idempotent deletion`.
- Must-fail (sabotage) tests carry `@pytest.mark.mustfail` and the Overview §9.2 item they cover.
- Golden values live in `golden/` and are frozen once. A golden file changes only with a recorded
  reason.
- **No flaky tests and no retries** (Overview §9.3). Run with `PYTHONHASHSEED=0`.
- Randomness: keys, `r_t`, nonces and `collection_id` come from the OS (`secrets`). Seeds appear only
  for data order and k-means, derived as in Overview §10.6. **Never pass a seed into proof or key
  generation.**

---

## 7. Rules that apply to all code (from the spec)

- **Encodings (§0.2):** integers big-endian and fixed-width; scalars 32-byte little-endian mod ℓ;
  points 32-byte canonical ristretto255; the identity is 32 zero bytes. `‖` is raw concatenation.
- **Every hash, signature and proof input starts with its domain string (§2.3).**
- **Errors (§17):** typed, and never containing a record ID, vector value, key, `r_t` or text.
  Group sizes are allowed.
- **Record IDs (§3.2):** 1–256 UTF-8 bytes; not `^[+-]?[0-9]+$` (use a full match); not already
  live. Sort and compare by **UTF-8 bytes**.
- **Arithmetic (§4):** validate normalisation, never perform it; round half to even; `x̃` stored as
  `i32`, sums as `i64`.
- **Exactness (§5):** `S`, `n`, `r_agg`, `C_S` change together; physical excision, no deletion
  markers; membership check before subtracting; five-field equivalence, never fewer.
- **Routing (§7):** a pure function of `(x̃, state)`. No clock, no counter, no "latest group".
- **Crypto (§9):** use `crypto_scalarmult_ristretto255_allow_scalar_zero` (plain `scalarmult` raises
  on 0, Plan V-5). Decode untrusted points and scalars canonically. `C_t` must not be the identity.
- **Plaintext on disk (§13.2):** only `n`, group sizes, `C_S`, centroids, `scrambled_id`s, log
  leaves, certificates, group IDs and key versions. Nothing else.
- **Floats (D-6):** the demo may use plain numpy sums. Anything C-18 will compare against the Rust
  engine must use the pinned orders of §7.1, §7.2 and §8.2 (`np.cumsum(...)[..., -1]` is sequential;
  `np.sum` and `@` are not).
- **Dependency rules (Plan §5):** `python/sever_refmodel` has no file I/O, encryption or clock;
  `python/` never imports `demo/`; `demo/verifier_py` shares no code with anything.

---

## 8. Never do these

- Never modify anything in `datasets/`, or install packages into the P0 `.venv`, while the P0 encode
  runs or after the manifest is committed. The demo uses `.venv-demo`.
- Never reuse code from the old prototype demo (`demo.zip`) by copying. Re-type ideas against this
  spec (Plan §0).
- Never "fix" a failing test by editing the golden file or loosening the test without a recorded
  reason.
- Never move a target or threshold after seeing a result (Overview §3.4).
- Never print, log or commit `r_t`, private keys, group keys or passage text from `demo_db/`.

---

## 9. Commands (Windows PowerShell, from the repo root)

| Purpose | Command |
|---|---|
| Activate the demo environment | `.\.venv-demo\Scripts\Activate.ps1` |
| All tests | `$env:PYTHONHASHSEED="0"; python -m pytest -q` |
| One stage | `python -m pytest -q tests/refmodel/test_s06_groups.py` |
| Must-fail tests only | `python -m pytest -q -m mustfail` |
| Build the partition (S5) | `python -m sever_partition.build` (with `python/` on the path) |
| Build the demo database (S14) | `python demo/build_demo_db.py` (about 3 minutes, once) |
| Run the demo | `python demo/run_demo.py` or `python demo/run_demo.py --scripted` |
| Verify a certificate | `python demo/verifier_py/verify.py <cert> --anchors demo/verifier_py/anchors.json` |
| Offline model on demo day | `$env:HF_HUB_OFFLINE="1"` |
| P0 data check | `python tools/data_prep/prepare_data.py verify --root .` |

---

## 10. The long road after the demo (Overview §8)

| Phase | What | Exit gate (Overview §8) |
|---|---|---|
| P0 | Pinned data, embeddings, manifest | Spec §20.3 checks 1, 5, 6, 7; manifest verifies on a fresh clone (**final `verify` pending**) |
| P1 | Partition builder C-15, reference model C-18 | Artefacts for all 5 seeds with the Ledoit–Wolf oracle agreeing; equivalence sabotage suite passes; traceability matrix complete; gaps fixed in the spec |
| P2 | Rust crypto C-7, verifier C-16 | Spec §20.3 checks 2, 3, 4 |
| P3 | Durable core: VFS, WAL, storage checkpoints | 0 lost acknowledged writes, 0 corrupt recoveries; recovery byte-identical to pre-crash state |
| P4 | Keys and physical erasure C-6 | Clean forensic scans on 5 seeds; every sabotage detected |
| P5 | SEVER index on the new storage | T-3 canonical-blob part at 10^5 passages on 5 seeds; startup invariants pass after every EX-1 crash |
| P6 | Log and certificates C-11, auditor C-17 | T-4 on the attack suite (EX-4); auditor detects a skipped deletion leaf and a broken chain |
| P7 | Search C-10 | Identical top-k lists vs C-18 on all seeds; scalar and AVX2 identical |
| P8 | API, SDK, collections | Every experiment runs through the SDK; no error leaks an ID, vector or key |
| P9 | Evaluation and paper | Every target reported as found; every limit stated; tagged release with a DOI |
