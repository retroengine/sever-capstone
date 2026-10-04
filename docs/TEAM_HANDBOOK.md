# SEVER-DB — Team Handbook for Documentation Work

| | |
|---|---|
| **For** | Teammates joining SEVER-DB to do documentation, review and research work |
| **Owner** | SaiKiran Vanaparthi, who makes every decision and every change to the specification |
| **Written** | 28 September 2026, against commit `968d4ea` |
| **Project status** | Part 1 (The Idea) has started. No engine code exists yet |

**How to use this handbook.** Read Part A (about an hour), then the rules in Part B (ten minutes), then
your work package in Part C. Part D maps every section of the four project documents to its line number,
so you can go straight to what you need.

**Line numbers** are for commit `968d4ea`. If a document has changed since then, search for the section
heading instead. Headings do not change without a recorded decision.

---

## Contents

- [Part A — The project](#part-a--the-project)
  - A.1 SEVER-DB in plain words · A.2 The idea in numbers · A.3 How a vector moves through the system ·
    A.4 Where the truth lives · A.5 Where the project is now · A.6 Every identifier and where it is
    defined · A.7 Words from the build plans
- [Part B — Rules for all teammate work](#part-b--rules-for-all-teammate-work)
- [Part C — Work packages](#part-c--work-packages)
  - WP-1 Decision packet · WP-2 Onboarding docs · WP-3 Standards conformance · WP-4 Consistency audit ·
    WP-5 Requirements catalogue · WP-6 Diagrams · WP-7 Data and licences · WP-8 Literature and references
- [Part D — Maps of the four documents](#part-d--maps-of-the-four-documents)
- [Part E — Decisions only the owner can make](#part-e--decisions-only-the-owner-can-make)

---

## Part A — The project

### A.1 SEVER-DB in plain words

**The problem.** AI search systems (semantic search, retrieval-augmented generation) store text as
*embedding vectors*: lists of numbers, 384 of them here. To search fast they sort vectors into groups,
and each group keeps a summary, such as its average. When someone asks for their data to be deleted, most
systems only hide the record. The group's summary still carries that person's contribution, and so do
the log files, old backups and freed disk blocks. The project calls these leftovers **the ghost**. And
nobody outside the company can check even the accounting of a deletion. SEVER-DB lets anyone check that
accounting from a certificate; its erasure holds against anyone who later obtains the disks, but not
against the operator, who runs the service and holds its keys (Overview §1.2, L-27).

**The idea, in three parts:**

1. **Store sums, not averages.** Each group keeps an exact integer *sum* `S` and a *count* `n`. Deleting a
   vector subtracts it, so the group becomes bit-for-bit identical to a group that never received it.
   An average cannot be undone exactly; an integer sum can.
2. **Issue a receipt.** Each group's sum is sealed in a cryptographic *commitment* (a Pedersen
   commitment). Every deletion produces a *certificate* that anyone can check with no access to the
   database.
3. **Destroy the old keys.** Everything secret goes to disk only encrypted, under a three-level key
   tree. Every deletion replaces and destroys the key that protected the old copies, so they become
   unreadable. This is called *crypto-shredding*.

**Four parts, each adding one claim** (Build §0.1, `SEVER-DB_BUILD_PLAN_PART_1-2.md` L30–50):

| Part | Name | The one claim it adds |
|---|---|---|
| **1** | The Idea (**current**) | Deleting a vector returns its group, bit for bit, to the state it would have had if the vector had never arrived |
| 2 | The Database | That exactness survives a crash at any point; no acknowledged operation is lost; a deletion across many groups is all-or-nothing |
| 3 | The Receipt | Every deletion yields a certificate anyone can verify offline |
| 4 | The Erasure | After a deletion is acknowledged, nothing deleted can be recovered from raw storage; the full evaluation |

When a part is finished it is **frozen**: its files are hashed, and CI fails if any of them changes (Build
§0.3, L63–90). Later parts plug in through declared *extension points*. That is why the documentation has
to be right early: a mistake found after a freeze costs a formal erratum.

**What's built from what:**

- the engine, in Rust;
- the partition builder, in Python (component C-15), which fits the frozen groups offline;
- the reference model, in Python (C-18), a slow, obviously correct second implementation, written from
  the spec only, that the engine is tested against byte for byte.

### A.2 The idea in numbers (a toy example)

**Turning floats into integers (Q24, spec §4.2, L281–292).** Multiply each float by 2^24 = 16,777,216
and round to the nearest integer; exact halves round to the even neighbour ("ties to even").

| Float `x_i` | `x_i · 2^24` | Stored integer `x̃_i` |
|---|---|---|
| 0.5 | 8,388,608 | 8,388,608 |
| 2.5 / 2^24 | 2.5 | 2 (tie → even) |
| 3.5 / 2^24 | 3.5 | 4 (tie → even) |
| −2.5 / 2^24 | −2.5 | −2 (tie → even) |

**Exact deletion (spec §5.3, L332–350).** A toy group with 2 dimensions (the real system has 384):

| Step | Members | Sum `S` | Count `n` |
|---|---|---|---|
| Insert a = (3, −1) | a | (3, −1) | 1 |
| Insert b = (5, 2) | a, b | (8, 1) | 2 |
| Insert c = (−4, 7) | a, b, c | (4, 8) | 3 |
| **Delete b** | a, c | (4 − 5, 8 − 2) = **(−1, 6)** | **2** |
| A group that only ever got a and c | a, c | (3 − 4, −1 + 7) = **(−1, 6)** | **2** |

The last two rows are identical. That is the whole claim of Part 1. With float averages, "removing" b
means recomputing an average from an already-rounded average, and the bits generally no longer match.
Part 1's demo measures that difference (Build §4.9, L692–725).

The **canonical group blob** (spec §5.5, L363–397) is a fixed byte layout of a group: its sum, its count,
the commitment fields and its members sorted by ID. Two groups are "the same" only if their blobs are
byte-identical and four other fields match too (the five-field *exactness relation*).

### A.3 How a vector moves through the system (Part 1 view)

```
insert(record_id, x)
  → check the ID (§3.2): 1–256 bytes, not a bare integer, not already live
  → check x (§4.1): every value finite, length within 8 float32 ULPs of 1
  → quantise to integers x̃ (§4.2)
  → route (§7): nearest frozen group; Mahalanobis drift test against threshold τ
        in-distribution            → that frozen group
        out-of-distribution        → a spawned group with room, if any ("spillover")
                                   → otherwise the holding area (not searchable)
        200th holding-area record  → all 200 become one new spawned group ("flush")
  → S ← S + x̃, n ← n + 1

delete(record_id)
  → is it still a member? if not: AlreadyAbsent, change nothing (§5.4)
  → S ← S − x̃, n ← n − 1; physically remove it (no "deleted" markers)

search(q, k)  (§8)
  → rank every group centroid by distance to q
  → scan the closest 25 % of groups (empty groups still count)
  → score with the pinned kernel (bit-identical scalar and AVX2)
  → return the top k
```

The 128 frozen groups are fitted once, offline, on a public dataset (SciQ) by the partition builder
(§6), and never change.

### A.4 Where the truth lives

| Priority | File | Lines | What it is |
|---|---|---|---|
| 1 | `docs/SEVER-DB_SPECIFICATION.md` ("spec §N") | 1,772 | **Normative.** What the software must do, byte for byte. It wins every disagreement |
| 2 | `docs/SEVER-DB_PROJECT_OVERVIEW.md` ("Overview §N") | 1,535 | Why: goals, decisions DB-1…DB-43 and DB-55, phases, targets, datasets, limits, risks, references |
| 3 | `docs/SEVER-DB_BUILD_PLAN_PART_1-2.md` ("Build §N") | 967 | How it's built: the four parts, the freeze rule, engineering and test standards, extension points, Parts 1–2 |
| 4 | `docs/SEVER-DB_BUILD_PLAN_PART_3-4.md` ("Build 3-4 §N") | 688 | Parts 3–4 and the cross-part registers |
| 5 | `docs/PROGRESS.md` | 52 | Where the project is right now |
| — | `docs/SPEC_GAPS.md` | 12 | Known spec problems G-1…G-5 |
| — | `docs/TRACEABILITY.md` | 13 | Requirement → test table (empty so far) |
| — | `CLAUDE.md` | — | The owner's working rules. Sections 2, 5, 7 and 8 apply to you too |
| — | `datasets/PINS.json`, `datasets/processed/meta.json`, `datasets/MANIFEST.sha256` | — | Pinned dataset versions, build facts and file hashes |
| — | `pyproject.toml`, `uv.lock`, `.python-version` | — | The Python environment |
| — | `scripts/data-preparation/prepare_data.py` | — | The P0 data download, encode and verify script |

**The spec wins.** If documents disagree, the spec is right, or the spec has a *gap* that the owner fixes
with a recorded decision. The build plans' proposed decisions DB-44…DB-54 take effect only once they are
copied into the overview's decision register (Overview §6).

### A.5 Where the project is now

From `docs/PROGRESS.md`:

- **P0 data:** done and verified on 27 Sep 2026.
- **Current part:** Part 1. **Current module:** `sever-types`, not started. No code exists.
- **Owner's next step:** decide the proposed decisions DB-44…DB-50, then read spec §2, §3.2 and §17.
- **Open gaps:** G-1 to G-5 (`docs/SPEC_GAPS.md`). G-5 (repository layout) must be settled before the
  first crate.
- **Open questions:** what overwrote `sciq_reference/passages.parquet` on 27 Sep; DB-44…DB-54 are not yet
  in the decision register.

### A.6 Every identifier and where it is defined

| ID | Meaning | Defined in | Example |
|---|---|---|---|
| `SR-<section>-<n>` | A spec requirement | Build §2.2 (L166); list to live in `spec/requirements.yaml` (not created yet; WP-5) | `SR-4.1-3` |
| `DB-N` | A design decision | Overview §6 (L395–821), DB-1…DB-43, DB-55 (§6.8); proposed DB-44…DB-50 in Build §3.5 (L463), DB-51…DB-54 in Build 3-4 §3.5 (L674) | `DB-42` licences |
| `G-N` | A spec gap | `docs/SPEC_GAPS.md` | `G-1` |
| `C-N` | A software component | Spec §19.1 (L1569); brief list in Overview §7 (L823) | `C-18` reference model |
| `INV-N` | An invariant the engine checks | Spec §21 (L1690) | `INV-4` group cap |
| `T-N` | A pre-registered target | Overview §3.4 (L272) | `T-6` |
| `EX-N` | An experiment | Overview §11 (L1101) | `EX-4` |
| `RQ-N` | A research question | Overview §3.1 (L231) | `RQ-2` |
| `L-N` | A known limit | Overview §14 (L1253) | `L-19` |
| `R-N` | A risk | Overview §15 (L1332) | `R-1` |
| `[RN]` | A reference | Overview §20 (L1447); R1…R55 | `[R25]` |
| `O-N` | An open item | Overview §17 (L1368) | `O-2` |
| `G1`…`G8` | A project goal | Overview §1.4 (L140) | `G7` |
| `P0`…`P9` | An overview phase; `P1.G3` is phase P1's goal 3 | Overview §8 (L852) | `P1.G3` |
| Part 1…4 | A build part | Build §0.1 (L30) | Part 1 |
| `P1-Gn`, `P1-Tn` | A Part 1 goal or target (also `P2-…`, `P3-…`, `P4-…`) | Build §4.2 (L499), §4.8 (L673) | `P1-T7` |
| `F-1`…`F-6` | Freeze rules | Build §0.3 (L63) | `F-6` errata |
| `E-N` | An erratum to a frozen part | `ERRATA.md` (created when needed); template in Build §6.3 (L957) | — |
| `L1`…`L14` | A test level | Build §2.1 (L140) | `L3` spec conformance |
| `SB-N` | A sabotage (a deliberately broken build) | Build §2.6 (L248) | `SB-9` |
| `EP-N` | An extension point | Build §3.3 (L362), EP-1…EP-9; EP-10 in Build 3-4 §1.5 (L116); EP-11 in Build 3-4 §2.4 (L373) | `EP-1` |
| `E2E-n.m` | An end-to-end scenario | Build §4.7 (L585), E2E-1.1…1.7 | `E2E-1.5` |
| `AT-N` | An attack certificate | Build 3-4 §1.8 (L242–258) | `AT-17` |
| `AF-N` | An auditor failure case | Build 3-4 §1.8 (L264–268) | `AF-2` |
| `DST_…` | A domain string | Spec §2.3 (L180) | `DST_POSK` |

**Names that collide. Always write the full form.**

| Looks like | Could mean | Write |
|---|---|---|
| `P1` | Overview phase P1, or build **Part 1** | "phase P1" / "Part 1" |
| `P1.G3` / `P1-G3` | Phase P1 goal 3 (a traceability matrix) / Part 1 goal 3 (routing) | Quote the full ID and its document |
| `G1` / `G-1` / `P1-G1` | Project goal / spec gap / Part goal | Full ID |
| `R-1` / `[R1]` | Risk / reference | Full ID with brackets for references |
| `L-1` / `L1` | Known limit / test level | Full ID |
| `P2` / `P2-T1` | Phase P2 (cryptography) / a Part 2 (database) target | "phase P2" / "Part 2 target P2-T1" |

### A.7 Words from the build plans

The overview's glossary (Overview §19, L1411–1446) covers the system's vocabulary. These build-plan words
are not in it:

| Word | Meaning | Where |
|---|---|---|
| **Plan / apply** | Every change is first computed by a pure `plan` step (which can fail and changes nothing), then installed by an `apply` step that cannot fail | Build §1.1 (L94) |
| **ChangeSet** | What `plan` returns: every field before and after, every slot move, every created group | Build §3.3, EP-3 (L362–442) |
| **Extension point** | A declared interface a later part plugs into without editing frozen code | Build §3.3 |
| **Composition root** | The small crate that wires one part's pieces together (`sever-p1` …) | Build §1.1 |
| **Contract suite** | Shared tests every implementation of an extension point must pass | Build §3.4 (L444) |
| **Proof spike** | A throwaway prototype showing an extension point can express a later part's needs | Build §3.4 |
| **Gate / measure** | A gate is pass/fail (a miss is a bug). A measure is recorded as found and never "fixed" | Build §2.5 (L237) |
| **Sabotage** | A build with one deliberate bug; some test must go red | Build §2.6 (L248) |
| **Trace file** | JSON Lines of operations and expected results, used to compare Rust with Python | Build §2.4 (L223) |
| **Sealer** / `PlaintextSealer` | Turns stored data into stored bytes; the plaintext one is used until Part 4 adds encryption | Build §3.3, EP-6 |
| **`SimVfs`** | A simulated file system that injects crashes deterministically (Part 2) | Spec §19.1 C-1 |
| **Freeze / erratum** | A finished part's files are hashed and locked; the only fix is a formal erratum | Build §0.3 |

---

## Part B — Rules for all teammate work

### B.1 What you may and may not touch

| You may | You may not |
|---|---|
| Create new files under `docs/reviews/`, `docs/drafts/`, `docs/diagrams/`, `docs/research/`, and the specific files your work package names | Edit the four source documents (the spec, the overview, both build plans). Propose changes instead (B.6) |
| Propose spec gaps and decision entries in your own files | Edit `CLAUDE.md`, `docs/PROGRESS.md` or `docs/SPEC_GAPS.md` (the owner maintains them) |
| Read everything | Touch anything in `datasets/`, even a single byte. Data files are pinned by hash |
| Run read-only commands | Write implementation code or tests (Rust crates, Python packages), or `docs/notes/P1-*.md` (the owner's own learning notes) |
| Ask the owner questions | Commit data, keys, database directories or anything a run writes |

### B.2 Setup

1. Ask the owner for access to the repository and clone it.
2. For docs work you need a Markdown editor with Mermaid preview (VS Code with a Mermaid extension, or
   GitHub's web view).
3. Optional, for WP-3 and WP-4 scripts: the project uses `uv` and Python 3.13 under WSL or Linux. Run
   `uv sync` in the repo root, then `uv run python …`.
4. **You won't have the data files.** Only `datasets/PINS.json`, `datasets/MANIFEST.sha256` and
   `datasets/processed/meta.json` are in git. The embeddings and passages are on the owner's machine.
   Nothing in this handbook needs them.

### B.3 Branches, commits and pull requests

- One branch per work package: `docs-wp<N>-<topic>`, for example `docs-wp4-audit`.
- Commit messages: `docs(<area>): <what>`, for example `docs(audit): compare sabotage registers`.
- Every change goes through a pull request the owner reviews. Paste this checklist into the description
  (adapted from Build §6.1, L941–949):

```
- [ ] Work package: WP-__. Which part does it serve (1–4)?
- [ ] Touches none of: the four source documents, CLAUDE.md, PROGRESS.md, SPEC_GAPS.md, datasets/, code.
- [ ] Every factual claim cites a document, section and line (B.4).
- [ ] Every proposed spec change is a proposed gap (B.6), not an edit.
- [ ] No data, keys or passage text included.
- [ ] Diagrams render (if any).
```

### B.4 How to cite

Always name the document, the section and the lines:

- `spec §4.2 (L281–292)`
- `Overview §10.4 (L1030–1039)`
- `Build §2.6 (L248–289)`
- `Build 3-4 §3.4 (L660–672)`

Quote the exact words when the wording matters. Never paraphrase a rule into something stronger or
weaker than it is.

### B.5 How to report a finding

Use one block per finding:

```
### F-<WP>-<n>  <one-line title>
Severity:   Blocker | Major | Minor | Editorial
Part:       1 | 2 | 3 | 4 | all
Where:      <doc §, lines>  and  <doc §, lines>
Says:       "<exact quote 1>"  vs  "<exact quote 2>"
Problem:    <plain words: why this is wrong, ambiguous or incomplete>
Suggested:  <smallest fix; which document should change>
```

Severity scale:

| Severity | Meaning |
|---|---|
| **Blocker** | Two documents disagree about behaviour or bytes the current part (Part 1) builds, or a rule cannot be implemented as written |
| **Major** | The same kind of problem, for a later part; or a missing rule that someone would have to invent |
| **Minor** | Inconsistent names, IDs, counts or cross-references that could mislead |
| **Editorial** | Wording, typos, stale sentences |

### B.6 How to propose a spec gap or a decision

You never edit the spec. You write a *proposed gap* in your own file, and the owner decides. Number your
proposals `PG-<WP>-<n>` so teammates' numbers never collide. The owner assigns the real `G-N` on
acceptance.

```
| PG-4-1 | <spec § and lines> | <problem, with quotes> | <proposed fix: exact before/after text> | proposed |
```

For a proposed decision entry, use the overview's format (see WP-1) and leave the number as `DB-??`.

### B.7 When you're stuck

- If the spec is unclear, **write down the question. Don't invent an answer.** An honest "the spec
  doesn't say" is a valuable finding.
- If two readings are both plausible, record both and say which you'd pick and why.
- Ask the owner, and quote the exact lines you're asking about.

---

## Part C — Work packages

### C.0 Overview

| WP | Name | Who | Rough size | Starts | Output |
|---|---|---|---|---|---|
| **WP-1** | Decision packet | Research writing | 3–5 days | Week 1 | `docs/drafts/DECISION_PACKET.md` |
| **WP-2** | Onboarding docs | Newcomers | 4–6 days | Week 1 | `README.md`, `CONTRIBUTING.md`, `docs/READING_GUIDE.md`, `docs/GLOSSARY.md` |
| **WP-3** | Standards conformance | Crypto / math | 4–6 days | Week 1 (§9.7 first) | `docs/reviews/STANDARDS_CONFORMANCE.md`, `docs/TEST_VECTOR_SOURCES.md` |
| **WP-4** | Consistency audit | Research writing (+ crypto for C.4.4) | 4–5 days | Week 2 | `docs/reviews/DOC_AUDIT.md` |
| **WP-5** | Requirements catalogue, Part 1 | Crypto (math sections) + newcomers (table sections) | 6–10 person-days | After the owner decides G-6 | `spec/requirements.yaml`, rows in `docs/TRACEABILITY.md` |
| **WP-6** | Diagrams | Newcomers | 3–5 days | After WP-2 | `docs/diagrams/*.md` |
| **WP-7** | Data and licences | Research writing | 2–3 days | Any time | `docs/DATA.md` |
| **WP-8** | Literature and references | Research writing | 5–8 days | Any time | `docs/research/RELATED_WORK_NOTES.md` |

The sizes are rough guesses for one person. **Suggested order:** week 1, WP-1 + WP-2 + WP-3; week 2, WP-4;
then WP-5 once the owner has decided G-6; WP-6, WP-7 and WP-8 fill the gaps.

**Already found while preparing this handbook** (these are leads, not decisions; each is detailed in its
work package):

1. **Most spec rules have no MUST.** Spec §0.1 (L44–47) says a statement without MUST/SHOULD/MAY is
   "explanatory", yet only 37 lines of the spec contain MUST. The Q24 formula, the byte layouts and the
   builder steps have none. Build §2.2 (L173) gives IDs only to "Every MUST or MUST NOT", but the same
   section (L192–198) wants every table and byte layout tested. Its example `SR-4.1-3` also matches
   §4.1's *step* number 3, although step 3 is only the second MUST. So which rules get an ID is
   ambiguous in both documents. → WP-4, WP-5 (proposed gap G-6).
2. **`nq-10k` is never defined.** The build plan uses it everywhere in Part 1 (Build §2.7 L291–304, §4.7,
   §4.9 demo, E2E-1.x) and says it comes "from overview §10". But Overview §10.4 (L1030–1039) defines only
   `nq-100k` and `nq-1m`, and `meta.json` builds only those two. → WP-4, WP-7.
3. **Golden vector ownership disagrees.** Spec Appendix B is titled "to generate in P1" (L1754); Overview
   phase P1 generates items 4, 5, 7 and 8 (L875–888); Build 3-4 §3.4 (L660–672) puts items 5, 7 and 8
   (core form) in Part 1 and item 4 in Part 3. → WP-4.
4. **The sabotage register is not a superset.** Build §2.6 (L252–253) says it "contains every item of
   overview §9.2 plus the phase-level must-fail tests of overview §8", but some phase must-fails in
   Overview §8 have no SB item (details in C.4.2). → WP-4.
5. **Spec §9.2 (L623–625) cites the wrong RFC for one set of test vectors.** It says to "run the RFC 9496
   known-answer tests for … `expand_message_xmd`", but those vectors are in RFC 9380. Spec §20.3 check 3
   (L1670–1671) has it right. → WP-3.

---

### WP-1 — Decision packet

**Goal.** Turn the proposed decisions DB-44…DB-54 and the open gaps G-1…G-5 into ready-to-accept text,
so the owner can decide each one in minutes rather than hours. This is the owner's current next step
(A.5).

**Who.** Research writing. No code knowledge needed, but you must read the sources closely.

**Inputs.**

- The decision register format: Overview §6 (L395–821). Read DB-1 (L402–410) and DB-42 (L776–782) as
  models. Entries use **Decision. Why. Rejected. Consequence.** Register rule (L397–398): "A decision is
  changed only by a new, dated entry that names the one it supersedes."
- The proposals: Build §3.5 (L463–479) for DB-44…DB-50; Build 3-4 §3.5 (L674–688) for all eleven, with
  their source sections.
- The gaps: `docs/SPEC_GAPS.md`.

**Steps.**

1. For each proposed decision, read its source section in full (table below), then write an entry in the
   template.
2. For each, find **every sentence in the spec and overview that the decision changes**, and write the
   exact before/after text. The "likely affected text" column is a starting point, not a complete list.
   Search for more.
3. For each gap G-1…G-5, write the exact before/after spec text and the decision entry that would go
   with it (the rule is: spec change + gap + decision in the same commit).
4. Mark each item "needed for Part 1: yes/no", so the owner can decide the urgent ones first.

**The proposed decisions.**

| ID | Plain words | Source (read in full) | Likely affected text | Needed for Part 1? |
|---|---|---|---|---|
| DB-44 | Build in four frozen parts; erasure after certificates | Build §0.1–0.3 (L30–90) | Overview §8 phase order (L852–966), §16 timeline (L1349–1366); spec App. B title "to generate in P1" (L1754) | Yes (it is the plan of record) |
| DB-45 | Plan/apply with a `ChangeSet`; extension points EP-1…EP-9; a WAL `EXTENSION` record | Build §1.1 (L94–110), §3.3 (L362–442) | Spec §14.6 WAL record (L1169), §12.3 (L919) | Yes (Part 1 declares EP-1…EP-4) |
| DB-46 | New slot payload order; `seal_version` in the group header | Build §3.5 row DB-46 | Spec §14.4 payload line (L1157–1161), §14.3 `group_key_version` row (L1131–1142), Appendix A slot rows | Partly (Part 1 keeps slots in memory only) |
| DB-47 | The canonical blob gets an extension region; magic `SEVERC` without commitments, `SEVERG` with | Build §3.5 row DB-47; Build 3-4 §3.4 item 8 | Spec §5.5 blob layout (L365–379), App. B item 8 (L1770) | **Yes** (Part 1 builds the `SEVERC` blob) |
| DB-48 | Every storage file records a `sealer_id`; no confidentiality claim before Part 4 | Build §3.5 row DB-48 | Spec §14.1 (L1099), §13.2 plaintext list (L1025–1027) | No (Part 2) |
| DB-49 | Any dimension that is a multiple of 8, and any number of frozen groups; v1 fixes 384 and 128 | Build §3.5 row DB-49; Build §2.7 (L291–304) | Spec §2.2 "Fixed parameters (v1)" (L160–178), §6.2 `k_frozen` (L419–422) | **Yes** (Part 1 tests use `d = 16`) |
| DB-50 | The `SecretMemory` provider is installed once, at startup | Build §1.1 (L106–107), EP-4 row | Spec §12.8 (L973) | **Yes** (`sever-types` declares EP-4; it is the first module) |
| DB-51 | The certificate reference model uses a small pure-Python ristretto255 | Build 3-4 §1.6 (L132–146) | Spec §19.1 row C-18 (about L1592); closes G-3 | No (Part 3) |
| DB-52 | Implement `expand_message_xmd` if the pinned curve library lacks it | Build 3-4 §1.4 (L111–115) | Spec §9.1 "No primitive is implemented by this project" (L610) | No (Part 3; but WP-3 can check the library now) |
| DB-53 | Extension points EP-10 `Witness` and EP-11 `PlatformProbe` | Build 3-4 §1.5 (L116–131), §2.4 (L373–392) | Spec §10.4 (L772–778), §12.9 (L982) | No |
| DB-54 | Evaluation build variants `key-export`, `noerase`, `softdelete` | Build 3-4 §2.7 (L430–446) | Overview §11 EX-2 (L1108) and EX-7 (L1114) | No |

**The gaps.**

| Gap | Where | What to draft | Needed for Part 1? |
|---|---|---|---|
| G-1 | Spec §6.2 step 2 (L426–430); Overview §10.6 (L1048–1053) | `random_state = seed_kmeans mod 2^32`, in both places, plus a decision entry | **Yes** (partition builder) |
| G-2 | Spec §13.2 table (L1013–1019; the three rows at L1017–1019) | Write "`group_id` (32, zero-padded)" in all three AD rows | No (Part 4) |
| G-3 | Spec §19.1 row C-18 | Text that goes with DB-51 | No (Part 3) |
| G-4 | Spec §11.3 inputs (L848–849); §10.3–10.4 | Define the genesis log checkpoint (tree_size 0, root = SHA-256 of the empty string, which is RFC 9162's empty-tree hash), or remove it from the inputs | No (Part 3) |
| G-5 | Spec §19.2 (L1597–1621) against Build §3.2 (L353–360) | A replacement §19.2 tree using Build §3.2's crate and package names; the `tests/` subfolders of Build §2.1's "Lives in" column (L142–157); and a `docs/` line that names all four documents | **Yes, urgent** (before the first crate) |

**Output template** (`docs/drafts/DECISION_PACKET.md`, one block per item):

```
#### DB-?? — <short title>            (proposed as DB-47; source: Build §3.5, L463–479)

**Decision.** <one paragraph, present tense>
**Why.** <the reason, from the source>
**Rejected.** <the alternatives the source mentions or implies; say "none stated" if none>
**Consequence.** <what follows, including any limit (L-N) or later work>
**Supersedes / amends.** <DB-N or spec §, or "none">
**Spec and overview text that changes.**
  - spec §5.5, L365: before "b\"SEVERG\"   6 bytes"  →  after "<new text>"
  - …
**Needed for Part 1:** yes / no — <why>
**Questions for the owner:** <anything the source leaves open>
```

**Done when.**

- [ ] All 11 decisions and all 5 gaps have a block.
- [ ] Every block lists at least one exact before/after edit, or says "no text changes" and why.
- [ ] Part 1 items come first in the file.
- [ ] Nothing in the four source documents was edited.

---

### WP-2 — Onboarding docs

**Goal.** A newcomer (like you, now) should understand the project and start contributing in one day.
Writing these files is also the fastest way for you to learn the project.

**Who.** Newcomers. Pair with anyone for a review.

**Rules specific to WP-2.**

- **Claim nothing that doesn't exist.** There is no code yet. The README must say so. Build §2.9
  (L328) requires the README to agree with the code at every freeze.
- Every fact links to its source section.

**Files and their outlines.**

1. **`README.md`** (repo root, about one page)
   - What SEVER-DB is: three sentences, from A.1 and spec §1 (L82–133).
   - Status: "Part 1 of 4 in progress; nothing runnable yet", with a link to `docs/PROGRESS.md`.
   - The four parts table (Build §0.1).
   - Where to start reading: link to `docs/READING_GUIDE.md`.
   - Licence: `MIT OR Apache-2.0` for code; data under upstream licences (Overview DB-42, L776–782).
2. **`CONTRIBUTING.md`**
   - Setup: WSL or Linux, `uv sync`, Python 3.13 (`CLAUDE.md` §9; `pyproject.toml`).
   - The rule of truth: spec first; gaps and decisions go in the same commit (`CLAUDE.md` §2; Overview
     §13.4, L1238–1243).
   - Branches, commits, PRs, with the checklist (Build §1.3 L124–136, §6.1 L941–949).
   - The never-commit list (`CLAUDE.md` §5, last bullets): raw and processed data files, `.venv*`, any
     database directory, key file, keychain or certificate from a run.
   - Test conventions for later (Build §2.1, §2.2, §6.2): the levels, `SR-…` annotations, test names, no
     flaky tests, `PYTHONHASHSEED=0`.
   - The freeze rule in five lines (Build §0.3).
3. **`docs/READING_GUIDE.md`**
   - How the four documents relate (A.4 of this handbook, expanded).
   - Three reading paths:
     - "one hour": Overview §1, §5; spec §1; Build §0.1, §4.1.
     - "Part 1 contributor": spec §2–§8, §9.7; Build §2, §3, §4.
     - "crypto reviewer": spec §9–§11; Overview §4, DB-14…DB-25.
   - The identifier table and the collisions table (A.6), expanded with more examples.
4. **`docs/GLOSSARY.md`**
   - Merge the overview glossary (L1411–1446, 25 terms), the spec symbols (spec §2.1, L137–158), the fixed
     parameters (spec §2.2, L160–178) and the build-plan words (A.7).
   - Each entry: a plain-words definition first, then the precise term and its source section.
   - Where two documents define a word differently, don't choose. Record both as a finding for WP-4.

**Done when.**

- [ ] A teammate who hasn't read the docs follows `READING_GUIDE.md` and can explain A.2's toy example back.
- [ ] Every link and section reference resolves.
- [ ] `README.md` claims no feature that does not exist.

---

### WP-3 — Standards conformance review

**Goal.** Check that every place the spec relies on an external standard (RFCs, FIPS) matches that
standard exactly, and list the official test vectors the project must run. The spec says (Appendix B,
L1756–1759) that correctness of the primitives "rests on the third-party RFC test vectors", so this list
matters.

**Who.** The crypto / math teammate.

**Order.** Do row 1 first (Part 1 needs it). The rest is early review for Parts 3–4, cheap now and
expensive after a freeze.

**What to check.**

| # | Spec text | Standard to compare | What to verify | Part |
|---|---|---|---|---|
| 1 | §9.7 scrambled IDs (L711–719): `HMAC-SHA-512(k_scramble, collection_id ‖ record_id_bytes)`, 64-byte key | RFC 2104; test vectors in **RFC 4231** (HMAC-SHA-512) | Key length against SHA-512's 128-byte block (no key hashing needed); that the input is unambiguous (`collection_id` is fixed at 16 bytes); that RFC 4231 is missing from Overview §20 (propose adding it) | **1** |
| 2 | §2.1 value of ℓ (L153) | RFC 9496 §4; RFC 8032 | The digits of `2^252 + 27742317777372353535851937790883648493` | 1 and 3 |
| 3 | §2.3 domain strings (L180–194) | — (internal) | Lengths already checked by Claude: 41, 15, 21, 17, 14, 17, 15 all match. Note the mixed `_` / `-` separators; ask the owner whether that is deliberate | 3 |
| 4 | §4.5 `scalar(v)` (L306–311) | Math | That it maps negative integers correctly mod ℓ and is additive (so commitments subtract exactly); golden vector 4 inputs `0, 1, −1, 2^44, −2^44` | 3 |
| 5 | §9.2 generators (L612–625) | RFC 9380 §5.3.1 (`expand_message_xmd`), RFC 9380 Appendix B (hash to ristretto255), RFC 9496 §4.3.4 (element derivation) | Output length 64, DST length ≤ 255, one call per generator; that the KAT sentence at L623–625 cites RFC 9380 (not RFC 9496) for `expand_message_xmd` vectors | 3 |
| 6 | DB-52 question (Build 3-4 L111–115) | docs.rs for `curve25519-dalek` **4.1.3** exactly | Does 4.1.3 expose `from_uniform_bytes`? Does it expose `expand_message_xmd`? Record the exact API names | 3 |
| 7 | §9.9 canonical encoding (L734–737); identity = 32 zero bytes (spec §5.2, L330) | RFC 9496 §4.3.1 (decode), §4.3.2 (encode) | That "canonical" decoding in the RFC rejects everything the spec wants rejected; that the identity encodes to 32 zero bytes | 3 |
| 8 | §9.4 blinding values (L636–643), 64-byte wide reduction | RFC 9496 / general practice | Bias of reducing 512 bits mod ℓ (negligible?); state it with numbers | 3 |
| 9 | §9.5 proof (L645–681) | Schnorr / Okamoto / Camenisch–Stadler; Fiat–Shamir | The verification equation; the 231-byte preimage (15 + 32 + 32 + 152); `ctx` = 32 + 32 + 64 + 8 + 16 = 152; the soundness note's extraction formula | 3 |
| 10 | §9.6 hedged nonces (L683–709) | Merlin 3.0.0 API docs (merlin.cool, docs.rs) | That `Transcript::new`, `append_message`, `build_rng`, `rekey_with_witness_bytes` and `finalize` exist with these meanings in merlin 3.0.0 | 3 |
| 11 | §9.8 signatures (L720–732) | RFC 8032 §5.1 (Ed25519), §7.1 (test vectors); `ed25519-dalek` 2.2.0 `verify_strict` docs | Message lengths 65, 66, 83; what `verify_strict` rejects compared with RFC 8032 §5.1.7 (which allows a choice between cofactored and cofactorless checks) | 3 |
| 12 | §10.1 Merkle log (L743–748) | RFC 9162 §2.1.1 (hashes), §2.1.3 (inclusion), §2.1.4 (consistency) | The `0x00`/`0x01` prefixes; "largest complete left subtree" matches the RFC's split rule; the empty-tree hash (links to G-4) | 3 |
| 13 | §13.2 AES-256-GCM-SIV (L1007–1027) | RFC 8452 (algorithm; Appendix C test vectors; security considerations) | 12-byte nonce, 16-byte tag, 32-byte key, 28-byte overhead; the RFC's limits on messages per key with random nonces, compared with how many ciphertexts one key protects here (spec §13.1–13.3) | 4 |
| 14 | SHA-256 / SHA-512 uses (§9.1 table, L596–608) | FIPS 180-4; NIST CAVP vectors | Where each hash is used and which vectors apply | 1, 3 |

**Outputs.**

1. `docs/reviews/STANDARDS_CONFORMANCE.md`: one section per row above, each with the spec quote, the
   standard's quote (with section number), and a verdict: *matches* / *mismatch* / *spec is silent*.
   Mismatches become findings (B.5) and proposed gaps (B.6).
2. `docs/TEST_VECTOR_SOURCES.md`: a table with columns primitive, standard, exact appendix or section,
   number of vectors, which spec check uses it (spec §9.2 L623–625, §20.3 check 3 L1670–1671), and which
   part needs it.

**Done when.**

- [ ] All 14 rows have a verdict with quotes from both sides.
- [ ] The test-vector table covers every primitive in spec §9.1.
- [ ] Row 6 names the exact API in `curve25519-dalek` 4.1.3 (with a docs.rs link).

---

### WP-4 — Consistency audit of the four documents

**Goal.** Find every place where the four documents disagree, reference something that doesn't exist,
or have fallen out of date. Each finding becomes a proposed gap for the owner.

**Who.** Research writing. C.4.4 (arithmetic) goes to the crypto / math teammate.

#### C.4.1 Every reference resolves

For each identifier type in A.6, list every use and check it is defined. Use commands like these (run
from the repo root):

```bash
grep -on 'DB-[0-9]\+'  docs/*.md | awk -F: '{print $3}' | sort -t- -k2 -n | uniq -c
grep -on 'SB-[0-9]\+'  docs/*.md | awk -F: '{print $3}' | sort -t- -k2 -n | uniq -c
grep -on 'INV-[0-9]\+' docs/*.md | awk -F: '{print $3}' | sort -t- -k2 -n | uniq -c
grep -on 'EP-[0-9]\+'  docs/*.md | awk -F: '{print $3}' | sort -t- -k2 -n | uniq -c
grep -on 'L-[0-9]\+'   docs/*.md | awk -F: '{print $3}' | sort -t- -k2 -n | uniq -c
grep -on '\[R[0-9]\+\]' docs/*.md | awk -F: '{print $3}' | sort | uniq -c
grep -on '§[0-9][0-9.]*' docs/SEVER-DB_BUILD_PLAN_PART_1-2.md | head
```

For every `§N` cited in a build plan as "spec §N", check that the spec section exists and says what the
build plan claims it says.

#### C.4.2 Lists that appear in more than one place

| # | List | Locations to compare | Leads already found |
|---|---|---|---|
| 1 | Sabotage | Overview §9.2 (L983–991, 23 items) and Overview §8 phase "Must-fail" lines (L852–966) against Build §2.6 (L248–289, SB-1…SB-30) | Build says the register "contains every item of overview §9.2 plus the phase-level must-fail tests of overview §8" (L252–253). Phase must-fails with no SB item: phase P0 "changing one corpus row changes the manifest hash" (L872); phase P1 "corrupting each of the five exactness fields is caught separately" (L887–888); phase P2 "a seeded RNG passed to proof generation (a compile-fail test)" and "skipping the witness rekeying step" (L900–902); phase P6 "a proof reused in another certificate" and "cosignatures over a different log checkpoint" (L940–941). Some may be covered by AT-2, AT-10 (Build 3-4 L243, L251) or by P3 test plans. Record which, and whether the Build §2.6 sentence should change |
| 2 | Components | Spec §19.1 (L1569–1595), Overview §7 (L823–850), Build §0.2 (L52–61), Build 3-4 §3.2 (L632–645) | Spec C-18 (about L1592) "depends on C-7 via Python binding" (that is G-3); C-7 in the spec includes the quantiser, but Build puts it in `sever-quant` (Part 1) |
| 3 | Invariants | Spec §21 (L1690–1714) against Build 3-4 §3.3 (L647–658) | Check all 16, both the wording and the parts |
| 4 | Golden vectors | Spec App. B (L1754–1772), Overview phase P1 (L877–879), Build §4.3 (L511–523), Build 3-4 §3.4 (L660–672) | Item 4 `scalar(v)`: phase P1 per the overview, Part 3 per Build 3-4. The App. B title says "to generate in P1". Follows from DB-44's reorder; propose the edit |
| 5 | Phases and parts | Overview §8 (L852–966), Build §0.2 (L52–61), `CLAUDE.md` §6.1 | Every phase's work lands in exactly one part |
| 6 | Targets | Overview §3.4 (L272–294), Build 3-4 §3.1 (L621–630), each part's targets table | Every T-N is established somewhere |
| 7 | Certificate attacks | Overview §11 EX-4 list (L1117–1123, 16 attacks) against Build 3-4 AT-1…AT-17 (L242–258) | AT-17 (duplicate witness) is new in the build plan; should the overview list gain it? |
| 8 | Test folders | Spec §19.2 `tests/` line (L1617), Build §2.1 "Lives in" column (L142–157), `CLAUDE.md` §6.2 | They differ: part of G-5 |
| 9 | Identifier tables | Spec §0.3 (L60–70), Overview §0 (L56–58) | Neither lists SR, SB, EP, F, G-N, E-N, E2E, AT, AF; both say "the two documents" |
| 10 | Errors | Spec §17 (L1394–1413) against every "reject with …" / "raise …" in the spec | Every raised error is in the table, and every table row is raised somewhere. Lead: `WrongDimension` is raised when "§4.1 fails", but §4.1 (L270–279) has no explicit dimension rule |

#### C.4.3 Specific leads to write up

| # | Lead | Where | Suggested severity |
|---|---|---|---|
| a | **Normative words.** Spec §0.1 makes any sentence without MUST/SHOULD/MAY "explanatory"; only 37 lines contain MUST; formulas, layouts and algorithm steps (e.g. §4.2 L283, §5.5 L365–379, §6.2 L423–446, §14.4 L1144–1161) have none. Build §2.2 gives IDs to "Every MUST or MUST NOT" (L173) but also wants every table and byte layout tested (L192–198), and its example `SR-4.1-3` (L173–174) matches §4.1's step number, not its MUST count. Propose gap **G-6** with the two options in WP-5 | Spec §0.1 (L44–47); Build §2.2 (L166–205) | **Blocker** (blocks WP-5 and Part 1's traceability gate P1-T9) |
| b | **`nq-10k` undefined.** Used by Build §2.7 (L298), §4.7 (L585–671, the L4 and L9 items), §4.9 (L694), the demo command, `CLAUDE.md` §9. Build says the slices come "from overview §10", but Overview §10.4 (L1030–1039) defines only `nq-100k` and `nq-1m`; EX-1 (L1107) uses "the first 10,000 passages of the seed's stream order", which differs per seed. `meta.json` builds only 100k and 1M (`size_small`, `size_big`). Propose a definition (for example, the first 10,000 rows of `nq-100k`, or a per-seed stream prefix), and let the owner choose | See left | **Blocker** (Part 1 demo and differential tests) |
| c | Golden-vector ownership (C.4.2 row 4) | | Minor |
| d | Sabotage superset claim (C.4.2 row 1) | | Major |
| e | "These two documents": spec header "Companion" (L7) lists only the overview; §19.2 `docs/` line (L1618); Overview L15–16 "Together, these two documents are self-contained"; Overview header "Team: One person" (L11) | | Editorial |
| f | Overview §6 heading "DB-1 … DB-43" (L395) must change when DB-44+ are accepted | | Editorial |
| g | Checkpoint qualifier: spec §0.4 (L72–80) says "checkpoint" never appears bare. Build 3-4 EP-10 row (L130) says "its last cosigned checkpoint". Search all four documents for other bare uses | | Minor |
| h | Spec §9.2 KAT sentence cites RFC 9496 for `expand_message_xmd` vectors (L623–625); §20.3 check 3 (L1670–1671) correctly cites RFC 9380 | | Minor (shared with WP-3) |
| i | Build §0.2 says Part 1 covers "§2–§8, §9.7" (L56), but §3.3, §3.4, §4.5 and the `C_S`/`r_agg` halves of §5.2–5.3 belong to Part 3 (Build §4.3 L511–523 is more precise). Propose that §0.2 cite §4.3 | | Minor |

#### C.4.4 Recompute Appendix A (crypto / math teammate)

Spec Appendix A (L1716–1752) derives 27 sizes and bounds. Claude recomputed all of them by hand on
28 Sep 2026, and they all agree, with one note. **Confirm independently** (it takes about an hour, and a
second check is the point), then record the result in the audit.

| Row | Check | Result |
|---|---|---|
| `x̃` bound | `2^24 + 16 = 16,777,232 < 2^31 − 1` | ✓ |
| `S` bound at 10^6 | `10^6 × 16,777,232 = 1.6777 × 10^13 < 2^44 = 1.759 × 10^13`; spare bits 63 − 44 = 19 | ✓ |
| Sum bits at 10^7 | `log2(10^7 × 16,777,232) ≈ 47.25 → 48` | ✓ |
| Tolerance | `8 × 2^−23 = 9.537 × 10^−7` | ✓ |
| Challenge preimage | 15 + 32 + 32 + 152 = 231 | ✓ |
| Proof size | 32 + 32 + 384 × 32 = 12,352 | ✓ |
| Nonce output | 385 × 64 = 24,640 | ✓ |
| Insert-signature message | 17 + 16 + 32 = 65 | ✓ |
| Insert leaf | 1 + 16 + 64 + 32 + 32 + 64 = 209 | ✓ |
| **Certificate** | TLV headers 13 × 5 = 65; values 32+32+32+12,352+64+1,007 (tag 6: 1+209+8+116+1+21×32) + tag 7 + 4+64+8+1+1+16; trailer 69. With **5** cosignatures (tag 7 = 1 + 5×69 = 346) → **14,093** | ✓, but it assumes all five witnesses cosign. With the minimum four it is 14,024. Suggest the row say so |
| Slot payload | 2 + 256 + 8 + 1 + 32 + 1,536 = 1,835 | ✓ |
| Slot | 64 + 60 + 1,863 = 1,987 → next multiple of 8 = 1,992 | ✓ |
| Accumulator | 384 × 8 + 32 = 3,104; + 28 = 3,132 | ✓ |
| Group header | 32 + 1 + 8 + 8 + 32 + 3,072 + 3,132 = 6,285 | ✓ |
| Bucket block | 64 × (8 + 60) = 4,352 | ✓ |
| Deletion rewrite, three-level | 4,352 + ⌈5,703/64⌉ × 60 + 3,132 = 4,352 + 5,400 + 3,132 = 12,884 ≈ 12.9 KB | ✓ |
| Deletion rewrite, two-level | 5,703 × 60 = 342,180 | ✓ |
| Probe counts | ⌈0.25 × 128⌉ = 32; ⌈0.25 × 263⌉ = ⌈65.75⌉ = 66 | ✓ |
| Witness threshold | smallest t > 10/3 → 4 | ✓ |
| Log tree | 2 × 1.9 × 10^6 × 32 ≈ 0.12 GB; path length ⌈log2(1.9 × 10^6)⌉ = 21 | ✓ |
| Slots, mirror | 1,992 × 10^6 = 1.99 GB; 10^6 × 384 × 4 = 1.54 GB | ✓ |

**Output.** `docs/reviews/DOC_AUDIT.md`: a summary table of all findings, then one B.5 block per finding,
then a "Proposed gaps" table (B.6).

**Done when.**

- [ ] Every row of C.4.2 has a verdict: consistent, or findings.
- [ ] Every lead in C.4.3 is written up (or rejected, with the reason).
- [ ] Appendix A is independently confirmed.

---

### WP-5 — Requirements catalogue for Part 1

**Goal.** Give every rule of Part 1's spec sections a stable ID `SR-<section>-<n>` in
`spec/requirements.yaml`, so every test can name the rules it checks, and CI can later fail if a rule has
no test (Build §2.2, L166–205; target P1-T9: traceability 100 %). This is the largest package.

**Who.** Split by section. The crypto / math teammate takes the formula-heavy sections; newcomers take
the table-shaped ones.

**Before you start: two owner decisions.**

1. **G-6: which statements count as requirements?** (See C.4.3 lead a.) The two options:
   - **(a)** Amend spec §0.1: numbered algorithm steps, formulas, byte layouts, the rows of normative
     tables, and definitions in §2–§21 are normative; only text marked as rationale ("Why …", "Note",
     explanations after a rule) is explanatory. The spec's wording stays as it is. **Recommended**: it is
     small, and it fits Build §2.2's wish to test every table and layout. Build §2.2 L173 ("Every MUST or
     MUST NOT … gets a stable ID") would need the same amendment.
   - **(b)** Rewrite every rule with MUST. This is a large spec edit touching hundreds of lines.
2. **The schema below.** The owner approves it (or changes it) before anyone fills it in.

**Schema (proposed).**

```yaml
# spec/requirements.yaml — one entry per requirement. IDs are never reused or renumbered.
- id: SR-4.1-3                  # SR-<spec subsection>-<n>, n in order of appearance
  section: "4.1"
  lines: "250"                  # at commit 968d4ea; informational
  text: "|norm − 1| ≤ 8 · 2^−23 MUST hold. Otherwise reject with NotNormalised."   # verbatim quote
  kind: must                    # must | must-not | step | formula | layout | table-row | definition
  part: 1                       # the part that owns it (Build §0.2, §4.3)
  technique: [boundary]         # equivalence | boundary | decision-table | state | table-driven | property
  error: NotNormalised          # optional: the §17 error it raises
  related: [INV-1]              # optional: INV-N, SB-N, golden-N, E2E-N
  notes: "Boundaries: exactly ±8 ULPs and one ULP beyond, both sides (Build §2.2)."
  status: active                # active | retired (never delete an entry)
```

**Worked example: spec §4.1–4.2 (L270–292) fully catalogued.**

```yaml
- id: SR-4.1-1
  section: "4.1"
  text: "Every component MUST be finite."
  kind: must
  part: 1
  technique: [equivalence]
  error: NonFinite
  related: [INV-1]
  notes: "Classes: finite, NaN, +inf, -inf."
- id: SR-4.1-2
  section: "4.1"
  text: "Compute norm = sqrt(Σ_{i=0}^{d−1} (f64)x_i²) in float64, summing sequentially from i = 0."
  kind: step
  part: 1
  technique: [table-driven]
  notes: "No MUST in the text (see G-6). The summation order matters for bit-exact results."
- id: SR-4.1-3
  section: "4.1"
  text: "|norm − 1| ≤ 8 · 2^−23 MUST hold. Otherwise reject with NotNormalised."
  kind: must
  part: 1
  technique: [boundary]
  error: NotNormalised
- id: SR-4.2-1
  section: "4.2"
  text: "x̃_i = round_half_to_even( (f64)x_i · 2^24 ), stored as i32."
  kind: formula
  part: 1
  technique: [table-driven, boundary]
  related: [golden-5]
- id: SR-4.2-2
  section: "4.2"
  text: "The SDK on the application backend and the engine MUST use the same quantiser, because the application backend builds C_t from x̃."
  kind: must
  part: 3
  notes: "The SDK's quantiser on the application backend arrives in Part 3 (Build 3-4 §1.4, sever_db_p3)."
```

The bullets "The float32-to-float64 conversion … are both exact" and "Bound: |x_i| ≤ …" in §4.2 are
explanations (why the rule is safe). List them in your "not requirements" list (below), with the reason.

**Rules for cataloguing.**

1. **Quote verbatim.** Never reword a rule. If a rule needs context to make sense, put that in `notes`.
2. **One testable claim per entry.** Split a sentence with two claims into two entries.
3. **Tables:** one entry per row (for example, each §17 error row, each §5.1 group kind).
4. **Byte layouts:** one entry for the whole layout (`kind: layout`), plus one entry per parser rejection
   rule (for example, §5.5 L381 lists five rejections, so five entries).
5. **Mixed ownership:** where a sentence covers Part 1 and Part 3 fields (for example §5.3's `S`, `n`
   and `r_agg`, `C_S`), split it and give each entry its own `part`.
6. **Anything you're unsure about:** catalogue it, and add `notes: "QUESTION: …"`.
7. **Everything you skip** goes in a "not requirements" list at the end of your section, with the line
   and the reason (rationale, example, cross-reference). This is how the owner checks that nothing was
   missed.
8. Don't write tests or choose levels. The owner writes the tests (the learning loop, `CLAUDE.md` §4).

**Split of the work.**

| Assignee | Sections | Lines |
|---|---|---|
| Crypto / math | §4 vector arithmetic (4.1–4.4; 4.5 is Part 3 but catalogue it with `part: 3`) | L268–311 |
| Crypto / math | §6 partition builder and artefact | L410–471 |
| Crypto / math | §7.1–7.2 nearest group, Mahalanobis drift | L473–495 |
| Crypto / math | §9.7 scrambled IDs | L711–719 |
| Newcomer A | §0.2 encodings; §2.2 fixed parameters; §2.3 domain strings (catalogue with `part: 3`) | L49–58, L160–197 |
| Newcomer A | §3.1–3.5 data model (3.2 and 3.5 are Part 1; 3.1, 3.3, 3.4 mostly later parts) | L199–266 |
| Newcomer A | §17 errors: every row, with a `part` each | L1394–1413 |
| Newcomer B | §5 groups, accumulators, exact deletion | L313–408 |
| Newcomer B | §7.3–7.7 destination rule, holding area, spawn, counters, determinism | L496–552 |
| Newcomer B | §8 search, including the kernel | L554–592 |
| Anyone | §21 invariants owned by Part 1: INV-1, INV-2 (partly), INV-4…INV-9, INV-16 (Build 3-4 §3.3) | L1690–1714 |

**Sabotage mapping** (for the `related` field and the traceability table, from Build §2.6):

| SB | Rule it attacks |
|---|---|
| SB-1 flip a bit of a sum | §5.5 exactness relation |
| SB-2 skip the count decrement | §5.3 |
| SB-3 subtract twice on retry | §5.4 idempotent deletion |
| SB-4 forget the locator update | §14.4 last bullet (in-memory semantics, Build §4.3) |
| SB-5 keep a deleted vector in the mirror | §8.1 last paragraph, INV-9 |
| SB-6 skip empty groups in the probe budget | §8.1 step 2 |
| SB-7 route to "most recent group with room" | §7 intro (L475–476), INV-16 |
| SB-8 holding area before spillover | §7.3 |
| SB-9 FMA in the SIMD kernel | §8.2 |
| SB-10 average per-group Ledoit–Wolf fits | §6.2 step 4 |

**Traceability rows.** For every entry, add a row to `docs/TRACEABILITY.md` in its existing format:
`| SR-4.1-3 | norm tolerance, NotNormalised | | | | 1 |`. Leave **Test** and **Level** empty for the
owner, and fill **Sabotage** where the mapping above applies.

**Done when.**

- [ ] Every line of your sections is either an entry or in your "not requirements" list.
- [ ] YAML parses (`uv run python -c "import yaml, sys; yaml.safe_load(open('spec/requirements.yaml'))"`,
      or any YAML linter).
- [ ] IDs are unique and in order.
- [ ] A second teammate spot-checks 10 random entries against the spec text.
- [ ] Every `QUESTION:` note is copied into the PR description for the owner.

---

### WP-6 — Diagrams

**Goal.** Pictures that make Part 1 understandable at a glance. They are explanatory only: the spec
still wins.

**Who.** Newcomers, after WP-2.

**Rules.**

- Use Mermaid in Markdown, one diagram per file under `docs/diagrams/`. GitHub renders it.
- Every diagram starts with the line: `> Explanatory only. Source: spec §N (Lx–Ly). If this diagram and
  the spec disagree, the spec is right.`
- Every box and arrow must come from a sentence in the source. If you need to invent something to make
  the picture work, stop and record it as a finding: the spec may have a gap.

**Part 1 diagrams (do these first).**

| # | File | Shows | Source | Mermaid type |
|---|---|---|---|---|
| D1 | `record-lifecycle.md` | ABSENT / HOLDING / IN_GROUP and every transition, including the non-transitions (delete when absent) | Build §2.3 (L207–221); spec §5.4, §7.4 | `stateDiagram-v2` |
| D2 | `routing.md` | The destination rule: nearest frozen group → drift test → spillover → holding area → flush at 200 | Spec §7.1–7.4 (L478–522) | `flowchart` |
| D3 | `canonical-blob.md` | The byte layout with offsets at d = 384 | Spec §5.5 (L365–379) | Table plus a `packet-beta` or block diagram |
| D4 | `partition-artefact.md` | `partition.svp` layout with offsets | Spec §6.3 (L450–467) | Table |
| D5 | `crate-layers.md` | The four-part crate layering and extension points | Build §3.1–3.2 (L336–360) | `flowchart TB` |
| D6 | `search.md` | Rank centroids → probe budget (empty groups count) → kernel → top-k, plus the 8-lane kernel reduction tree | Spec §8.1–8.2 (L556–584) | `flowchart` + a tree |
| D7 | `four-parts.md` | The four parts, their claims and the freeze rule | Build §0.1, §0.3 (L30–90) | `flowchart LR` |

**Check your offsets.**

- D3: at d = 384 the members start at byte **3,162**: magic 0–5, version 6–7, `d` 8–9, `n` 10–17, `S`
  18–3089, `C_S` 3090–3121, `r_agg` 3122–3153, `member_count` 3154–3161. Each member then takes
  2 + `id_len` + 3,072 bytes. Show the `SEVERC` form of proposed DB-47 as a separate, clearly marked
  "proposed" variant, and only if the owner has accepted DB-47.
- D4: the fixed prefix is 80 bytes up to the encoder string, so the total size is
  `1,572,976 + encoder_len` at d = 384, k = 128. Derive this yourself, and show your arithmetic in the
  file.

**Later (Parts 2–4).** Insert and delete protocols (spec §15.1, §15.3, L1211–1268); the key hierarchy
(§13.1, L995–1005); slot and group-header layouts (§14.3–14.4, L1131–1163); the certificate TLV (§11.1,
L790–831); the overview's end-to-end sketch (Overview §5, L379–391).

**Done when.**

- [ ] D1–D7 render on GitHub.
- [ ] Each has the explanatory-only header line and the source lines.
- [ ] Another teammate traced every arrow to a sentence.

---

### WP-7 — Data and licence documentation

**Goal.** One page that tells anyone exactly what data the project uses, where it came from, under which
licence, and what is known about it.

**Who.** Research writing.

**Rule.** Never modify `datasets/`. Read only the three committed files there.

**Facts already in the repo** (so you don't have to hunt):

| Item | Value | Source |
|---|---|---|
| Pinned at | 2026-09-27 12:11 UTC | `datasets/PINS.json` |
| Encoder | `sentence-transformers/all-MiniLM-L6-v2` @ `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | `PINS.json` |
| Live corpus | `BeIR/nq` @ `b7253e6c379163d024ddb1d6948152a91a2e3b46`; 2,681,468 passages | `PINS.json`; `meta.json` `build.nq.corpus_total` |
| Queries and judgements | `BeIR/nq-qrels` @ `519acd4e48bb3e5da22b2b888ce36c614f4f2bc9`; 3,452 queries; 4,201 judgements | `PINS.json`; `meta.json` |
| Reference set | `allenai/sciq` @ `2c94ad3e1aafab77146f384e23536f97a4849815`; 13,679 passages (train + validation + test); **1,427** use the question fallback | `PINS.json`; `meta.json` `build.sciq` |
| Corpora | 100,000 and 1,000,000 passages; the small one is a prefix of the big one; all 4,201 judged passages kept; corpus seed 42 → value 17497888457110469931 | `meta.json` `build.nq` |
| Cohorts (article titles) | 51,350 in the 100k corpus; 101,670 in the 1M corpus | `meta.json` |
| Non-overlap | 0 shared IDs; 0 shared texts, query vs corpus and SciQ vs corpus (lower-cased, whitespace-collapsed SHA-256) | `meta.json` `build.non_overlap` |
| Truncation (256 tokens) | NQ 1M: 49,148 rows (4.91 %); SciQ: 960 rows (7.02 %); queries: 0 | `meta.json` `encode` |
| Encode environment | Windows 11, Python 3.13.9, torch 2.14.0+cpu, sentence-transformers 6.1.0, numpy 2.5.3; CPU, 4 threads, batch 64 | `meta.json` `encode.versions`, `settings` |
| Embedding hashes | `sha256_rows` per set | `meta.json`; `datasets/MANIFEST.sha256` |

**Licences to verify** (Overview DB-42, L776–782; Overview §10.1–10.3, L1006–1028; limit L-19, L1320):

| Artefact | Licence the docs claim | What to check |
|---|---|---|
| SciQ | CC BY-NC 3.0 | The dataset card at the pinned revision on Hugging Face |
| BEIR NQ corpus | CC BY-SA 3.0 | The dataset card at the pinned revision; the original Natural Questions licence |
| BEIR NQ qrels | (not stated) | The dataset card |
| all-MiniLM-L6-v2 | (not stated in the overview) | The model card at the pinned revision |
| Code | `MIT OR Apache-2.0` | Compatibility with the dependency licences named in DB-42 |

**What to write in `docs/DATA.md`:**

1. One section per dataset and the encoder: source URL at the pinned revision, licence (verified, with
   the link), size, how the project uses it (reference / indexed / queries), and the text rule
   (Overview §10.1–10.2).
2. How the corpora are built (Overview §10.4–10.6), plus the facts above that the overview doesn't
   state: the prefix property, the cohort counts, the fallback count and the truncation rates.
3. The licence matrix, and what the non-commercial term means for release (DB-42 consequence, L-19).
4. Known issues:
   - the open question about `sciq_reference/passages.parquet` being overwritten on 27 Sep
     (`PROGRESS.md`);
   - encoding ran on Windows, while spec §20.4 (L1678–1688) says experiments run on native Linux. This is
     fine because embeddings are pinned by hash (risk R-6, L1342), but record it;
   - `nq-10k` is undefined (C.4.3 lead b).
5. Any difference between the overview's claims and the facts, written as a finding (B.5).

**Done when.**

- [ ] Every licence is verified against the source at the pinned revision, with links.
- [ ] Every number in `DATA.md` cites `meta.json`, `PINS.json` or an overview section.

---

### WP-8 — Literature and references

**Goal.** Make sure every reference the project cites is correct and says what we claim it says, and
find the related work that's missing. This feeds the research paper (phase P9) and protects its
credibility.

**Who.** Research writing.

**Part 1: verify all 55 references** (Overview §20, L1447–1518). They are grouped by topic, not in
numeric order:

| Group | IDs | Lines |
|---|---|---|
| Standards and primitives | R1–R20, R52 | L1451–1472 |
| Secure and verifiable deletion | R21–R28, R51 | L1474–1483 |
| Storage engines and durability | R29–R34, R40–R42 | L1485–1494 |
| Vector search | R35–R39 | L1496–1501 |
| Data and models | R43–R46 | L1503–1507 |
| Statistics | R53–R54 | L1509–1511 |
| Tooling and platform | R47–R50, R55 | L1513–1518 |

For each reference:

1. **Does the link resolve?** Does the DOI point to the right work?
2. **Are the bibliographic details right?** Authors, title, venue, year.
3. **Where is it cited?** Find every place: `grep -n '\[R25\]' docs/*.md`.
4. **Does the source actually say what the citing sentence claims?** This is the important part.

Claims to check first:

- Overview §2.3 (L204–227): NIST SP 800-88 Rev. 2 "singles out" cryptographic erasure [R21], and its date
  "final 26 September 2025" (L1475); flash drives don't reliably overwrite in place [R25]; FreshDiskANN
  "repairs graphs approximately rather than exactly" [R38]; the Garg–Goldwasser–Vasudevan notion that
  post-deletion state looks as if the data never arrived [R27]; Boneh–Lipton revocable backups [R22];
  key trees bounding re-encryption [R24].
- Overview §14 (L1253–1328): the claims behind [R25] and [R21] in L-1.
- [R18]: is the draft really expired? [R13]: what is the draft's current status?
- [R49] needs an Intel account. Find a public source for the Core Ultra 5 226V instruction sets.
- **Missing standards:** RFC 4231 (HMAC-SHA-512 test vectors) is not in the list (see WP-3).

**Part 2: find missing related work.** These are **candidate topics**. Verify each source exists and
is relevant before recommending it:

- How production vector stores delete: FAISS `remove_ids`; Milvus (delete plus compaction); Qdrant and
  Weaviate (HNSW tombstones); pgvector (Postgres MVCC and `VACUUM`); LanceDB (deletion files);
  Lucene/Elasticsearch soft deletes and segment merges.
- Research on deletion in graph-based approximate nearest-neighbour indexes (beyond FreshDiskANN).
- Forensic recovery of deleted data from database files.
- Transparency logs beyond Certificate Transparency: Trillian, Sigstore Rekor, key transparency (CONIKS),
  and witness cosigning.
- Legal framing: GDPR Article 17 (right to erasure) and regulators' guidance on what "erasure" means.
- Surveys of machine unlearning (complementary; Overview §2.3 already cites [R51]).

**Output: `docs/research/RELATED_WORK_NOTES.md`.**

```
### [R25] Wei et al., "Reliably erasing data from flash-based SSDs", FAST 2011
Link:         ✓ resolves (checked 2026-10-__)
Details:      ✓ / ✗ <correction>
Cited at:     Overview §2.3 L207; Overview §14 L-1 L1262
Claim made:   "flash drives do not reliably overwrite in place"
Source says:  <quote or page reference>
Verdict:      supported / overstated / wrong / cannot verify
Notes:        <2–5 lines a paper author would want>
```

Then a "Candidate additions" section: for each, the citation, why it's relevant, and which overview
section it belongs in. Don't edit Overview §20. The owner adds references.

**Done when.**

- [ ] All 55 references have a block with a verdict.
- [ ] Every "overstated" or "wrong" verdict is also a finding (B.5).
- [ ] At least the vector-store deletion topic has verified candidates.

---

## Part D — Maps of the four documents

### D.1 Specification (`docs/SEVER-DB_SPECIFICATION.md`)

"Part" is the build part that owns the section (Build §0.2, L52–61; Build §4.3).

| § | Title | Line | Part |
|---|---|---|---|
| 0 | Conventions | 42 | all |
| 0.1 | Normative words | 44 | all |
| 0.2 | Encodings | 49 | all |
| 0.3 | Identifiers used across the two documents | 60 | — |
| 0.4 | Two kinds of checkpoint | 72 | 2, 3 |
| 1 | The system on one page | 82 | — |
| 2.1 | Symbols | 137 | 1 |
| 2.2 | Fixed parameters (v1) | 160 | 1 |
| 2.3 | Domain strings | 180 | 3 |
| 3.1 | Collections | 201 | 2 |
| 3.2 | Records (ID rules) | 208 | **1** |
| 3.3 | Users and blinding values | 227 | 3 |
| 3.4 | Passage text | 256 | 4 |
| 3.5 | Cohorts | 261 | **1** |
| 4.1 | Normalisation check | 270 | **1** |
| 4.2 | Quantisation (Q24) | 281 | **1** |
| 4.3 | Dequantisation | 294 | **1** |
| 4.4 | Accumulator bounds | 299 | **1** |
| 4.5 | Integer-to-scalar mapping | 306 | 3 |
| 5.1 | Group kinds | 315 | **1** |
| 5.2 | Group state | 325 | **1** (+3) |
| 5.3 | Insert and delete arithmetic | 332 | **1** (+3) |
| 5.4 | Membership, idempotency and excision | 352 | **1** |
| 5.5 | Canonical group blob and exactness relation | 363 | **1** (+3) |
| 5.6 | Capacity | 399 | **1** |
| 6.1 | Purpose (partition) | 412 | **1** |
| 6.2 | Builder algorithm | 419 | **1** |
| 6.3 | Artefact format (`partition.svp`) | 450 | **1** |
| 7 | Routing, drift detection and spawning | 473 | **1** |
| 7.1 | Nearest frozen group | 478 | **1** |
| 7.2 | Mahalanobis drift test | 483 | **1** |
| 7.3 | Destination rule | 496 | **1** |
| 7.4 | Holding area and flush | 512 | **1** |
| 7.5 | A spawned group's identity and centroid | 524 | **1** |
| 7.6 | Counters | 536 | **1** |
| 7.7 | Determinism claim | 542 | **1** |
| 8.1 | Search algorithm | 556 | **1** |
| 8.2 | The pinned distance kernel | 573 | **1** |
| 8.3 | Why IVF-flat | 586 | **1** |
| 9.1 | Primitive set | 596 | 3 |
| 9.2 | Generators | 612 | 3 |
| 9.3 | Commitments | 627 | 3 |
| 9.4 | Blinding values | 636 | 3 |
| 9.5 | Proof of knowledge | 645 | 3 |
| 9.6 | Hedged nonce derivation | 683 | 3 |
| 9.7 | Scrambled record IDs | 711 | **1** |
| 9.8 | Signatures and key epochs | 720 | 3 |
| 9.9 | Encoding rules | 734 | 3 |
| 10.1–10.5 | Transparency log, log checkpoints, witnesses | 743–781 | 3 |
| 11.1 | Certificate encoding | 790 | 3 |
| 11.2 | `insert_inclusion` field | 833 | 3 |
| 11.3 | Verification algorithm | 846 | 3 |
| 12.1–12.7 | Storage engine | 897–964 | 2 |
| 12.8 | Memory hygiene | 973 | 4 |
| 12.9 | Platform checks at startup | 982 | 4 |
| 13.1–13.6 | Key hierarchy and physical erasure | 995–1086 | 4 |
| 14.1–14.4 | Directory layout, pages, group header, slot | 1099–1144 | 2 |
| 14.5 | Bucket block | 1165 | 4 |
| 14.6 | WAL record | 1169 | 2 |
| 14.7 | Key file | 1192 | 4 |
| 14.8 | Append stores | 1201 | 2 |
| 15.1–15.2 | Insert, flush protocols | 1211, 1232 | 2 |
| 15.3–15.4 | Delete protocol, crash table | 1243, 1270 | 4 |
| 15.5–15.7 | Search, storage checkpoint, recovery | 1280–1293 | 2 |
| 15.8–15.9 | Acknowledgement, drop collection | 1307, 1314 | 4 |
| 16.1 | Engine API (Rust) | 1324 | 2 |
| 16.2–16.3 | Python SDK, command-line tools | 1358, 1383 | 3 |
| 17 | Errors | 1394 | all |
| 18.1–18.2 | `engine.yaml`, `partition.yaml` | 1420, 1538 | all |
| 19.1 | Components | 1569 | — |
| 19.2 | Repository layout | 1597 | — (G-5) |
| 20.1–20.4 | Toolchain, dependencies, compatibility checks, hardware | 1625–1678 | all |
| 21 | Invariants checklist | 1690 | all |
| App. A | Derived sizes and bounds | 1716 | all |
| App. B | Golden vectors | 1754 | 1, 3 |

### D.2 Overview (`docs/SEVER-DB_PROJECT_OVERVIEW.md`)

| § | Title | Line |
|---|---|---|
| 0 | How to read this document (identifier list at L56–58) | 47 |
| 1.1–1.5 | What SEVER-DB is, why, what's new, goals G1–G8, non-goals | 76–153 |
| 2.1–2.3 | Origins, prior evidence, related work | 169–204 |
| 3.1 | Research questions RQ-1…RQ-5 | 231 |
| 3.2–3.3 | Claims and non-claims | 246, 256 |
| 3.4 | Pre-registered targets T-1…T-6 | 272 |
| 4.1–4.3 | Threat model | 298–319 |
| 5 | The design in plain words | 327 |
| 6.1 | Decisions: foundations (DB-1…) | 400 |
| 6.2 | Decisions: arithmetic and data model | 440 |
| 6.3 | Decisions: partition, drift, spawning, search | 481 |
| 6.4 | Decisions: cryptography | 538 |
| 6.5 | Decisions: log and certificates | 607 |
| 6.6 | Decisions: storage, keys, erasure | 655 |
| 6.7 | Decisions: process (… DB-42 at L776, DB-43) | 745 |
| 6.8 | Amendments (DB-55; DB-44…DB-54 reserved) | 790 |
| 7 | Components at a glance | 823 |
| 8 | Phases P0–P9 (P0 L858, P1 L875, P2 L890, P3 L904, P4 L914, P5 L924, P6 L935, P7 L943, P8 L951, P9 L957) | 852 |
| 9.1–9.3 | Oracles; sabotage list; techniques | 970, 983, 993 |
| 10.1–10.9 | Datasets: reference set, live set, encoder, corpora, splits, seeds, streams and arms, cohorts and rungs, metrics | 1006–1083 |
| 11 | Evaluation plan EX-1…EX-8 (attack list L1117) | 1101 |
| 12 | Experiment configuration (`experiments.yaml` draft) | 1133 |
| 13.1–13.5 | Repository, CI, run ledger, documentation rules, release | 1213–1245 |
| 14 | Known limits L-1…L-27 (L-16 retired) | 1253 |
| 15 | Risks R-1…R-10 | 1332 |
| 16 | Timeline | 1349 |
| 17 | Open items O-1…O-9 | 1368 |
| 18 | Recommendations | 1384 |
| 19 | Glossary | 1411 |
| 20 | References R1…R55 | 1447 |
| — | Changelog | 1522 |

### D.3 Build plan, Parts 1–2 (`docs/SEVER-DB_BUILD_PLAN_PART_1-2.md`)

| § | Title | Line |
|---|---|---|
| 0.1 | One claim per part | 30 |
| 0.2 | Mapping to the spec and overview | 52 |
| 0.3 | The freeze rule, F-1…F-6 | 63 |
| 1.1–1.3 | Modularity, code quality, workflow | 94, 112, 124 |
| 2.1 | Test levels L1–L14 | 140 |
| 2.2 | Specification-based testing (SR IDs) | 166 |
| 2.3 | Record lifecycle | 207 |
| 2.4 | Differential testing through trace files | 223 |
| 2.5 | Gates and measurements | 237 |
| 2.6 | Sabotage register SB-1…SB-30 | 248 |
| 2.7 | Test data | 291 |
| 2.8 | CI tiers | 306 |
| 2.9 | Definition of done | 314 |
| 3.1 | Layering | 336 |
| 3.2 | Crate and package map | 353 |
| 3.3 | Extension points EP-1…EP-9 | 362 |
| 3.4 | Contract suites and proof spikes | 444 |
| 3.5 | Spec amendments DB-44…DB-50 | 463 |
| 4.1–4.10 | Part 1: announcement, goals, scope, modules, public surface, requirements, test plan, targets, demo, exit gate | 482–727 |
| 5.1–5.10 | Part 2: the same structure | 737–931 |
| 6.1 | PR checklist | 941 |
| 6.2 | Test naming | 951 |
| 6.3 | Erratum template | 957 |

### D.4 Build plan, Parts 3–4 (`docs/SEVER-DB_BUILD_PLAN_PART_3-4.md`)

| § | Title | Line |
|---|---|---|
| 0 | Relation to the first plan | 21 |
| 1.1–1.3 | Part 3: announcement, goals (P3-G9 `SOUNDNESS.md` at L86), scope | 41–88 |
| 1.4 | Part 3 modules (DB-52 note at L111) | 96 |
| 1.5 | How Part 3 plugs in; EP-10 | 116 |
| 1.6 | Independence rules (DB-51) | 132 |
| 1.7 | Requirements owned by Part 3 | 147 |
| 1.8 | Test plan (AT-1…AT-17 at L242; AF-1…AF-5 at L264) | 161 |
| 1.9–1.11 | Targets, demo, exit gate | 282–314 |
| 2.1–2.3 | Part 4: announcement, goals, scope | 326–365 |
| 2.4 | Part 4 modules; EP-11 | 373 |
| 2.5 | How Part 4 plugs in | 393 |
| 2.6 | Requirements owned by Part 4 | 417 |
| 2.7 | Build variants (DB-54) | 430 |
| 2.8–2.13 | Test plan, evaluation, targets, demo, deliverables, final freeze | 447–612 |
| 3.1 | Targets mapped to T-1…T-6 | 621 |
| 3.2 | Components mapped to parts | 632 |
| 3.3 | Invariants mapped to parts | 647 |
| 3.4 | Golden vectors mapped to parts | 660 |
| 3.5 | Proposed decisions DB-44…DB-54 | 674 |

### D.5 Handy searches

```bash
# Where is a section? (headings)
grep -n '^#\{1,4\} ' docs/SEVER-DB_SPECIFICATION.md

# Every MUST / MUST NOT in the spec
grep -n 'MUST' docs/SEVER-DB_SPECIFICATION.md

# Every use of an ID across all documents
grep -n 'SB-7\b' docs/*.md CLAUDE.md

# Every place a reference is cited
grep -n '\[R21\]' docs/*.md
```

---

## Part E — Decisions only the owner can make

These block or shape teammate work. Teammates prepare them; the owner decides.

| # | Decision | Blocks | Prepared by |
|---|---|---|---|
| 1 | G-6: which spec statements count as requirements (option a or b) | WP-5 | WP-4 lead a |
| 2 | The `spec/requirements.yaml` schema | WP-5 | WP-5 |
| 3 | How `nq-10k` is defined | Part 1 demo and tests; WP-7 | WP-4 lead b |
| 4 | Accept, change or reject DB-44…DB-54, starting with the Part 1 ones (DB-44, 45, 47, 49, 50) | Part 1 design; WP-6 D3 | WP-1 |
| 5 | The fixes for G-1 and G-5 (both needed for Part 1) | First crate; partition builder | WP-1 |
| 6 | Which audit findings become gaps | Spec edits | WP-3, WP-4 |
| 7 | Whether the overview header ("Team: One person") and the "two documents" wording change | — | WP-4 lead e |

**Stays with the owner, not delegated:** the learning notes `docs/notes/P1-*.md`, all tests and code,
`configs/experiments.yaml` (the pre-registration: committed once, never changed; a teammate may
cross-check its pins against `PINS.json`), `docs/PROGRESS.md`, and every edit to the four source
documents.

**Not now:** `docs/SOUNDNESS.md`, the proof write-up (completeness, special soundness, zero-knowledge),
is a Part 3 gate (Build 3-4 P3-G9, L86). A crypto teammate could start reading for it once Part 2 is
frozen.
