# Studio audit 2: what is still faked, overstated or only explained

23 Oct 2026, branch `studio-raw` at `09d6658`. Report only; no Studio code was changed for it.
Every claim names its evidence. `audit2.py` reruns experiments E1–E6 on a copy of a synthetic work
directory (on ext4):

```bash
rsync -a studio/work/studio-synthetic/ ~/.cache/sever-audit/syn-a2/
uv run --project studio --no-sync python studio/audit/audit2.py ~/.cache/sever-audit/syn-a2
```

Output on 23 Oct:

```
E1 freetext ticked=True source='live'; encoder used: test-encoder@0
E2 encoder ticked=True: artefact test-encoder@0; data test-encoder@0; the fixture has no encoder
E3 key dir holds ['KEYS', 'SECRETS', 'WITNESSES']; anchors list 5 witnesses
E4 corrupted cosignature: Studio's climb says valid=True, 5 witnesses cosigned; sever-verify says: {"accepted":false,"reason":"the operator signature does not verify","step":2}
E5 erase checks on a 'verify FAILED' output: ('every certificate of the deletion verifies', True)
E6 delete_flow says: Keys -> the group's and the record's bucket key replaced, the old on...; it reads no key file
```

## 1. Verdict

The core is real. Every number about records, groups, routing, search, receipts and crashes comes
from the engine or from a separate checker run live (audit 1, §8; `spawn_proof.py`). What is
wrong is around it:

- **Claims stated stronger than the system:**
  - "independent witnesses": they are simulated by the database itself;
  - "nothing deleted can be recovered from raw storage": stated as fact, but the real-disk gate
    has not run;
  - a "whole disk" scan: it is a simulated image of 6 records.
- **Checks that cannot fail:**
  - two synthetic checklist rows tick from a stand-in encoder;
  - a Part 4 check is a substring test;
  - the climb never checks a signature.
- **Diagrams that state, rather than show, what happened:**
  - the deletion diagram asserts a key rotation nothing observed;
  - "Float vs exact" is still a numpy model with its own tab and tour chapter.

## 2. Findings

### Critical: a claim the system does not make

**C1. "Independent witnesses" are simulated by the database itself.**
- **The spec:** "In v1 the witnesses are simulated by the project" (§10.4); independence is limit
  L-7.
- **Evidence:**
  - the database's own key directory holds `WITNESSES`, the five witnesses' keys (E3);
  - the database's own process cosigns.
- **Where Studio claims otherwise:**
  - "cosigned by independent witnesses": `ui/copy.py:158`, `ui/tour.py:155`;
  - "4 or more independent witnesses cosigned": `ui/copy.py:234`, `README.md:81`.
- **Nowhere does Studio say "simulated".**
- **Fix:** say "five simulated witnesses (v1, run by the database itself; real independent
  witnesses are future work, L-7)" wherever witnesses appear.

**C2. The four Home claims are stated as facts, with no status.**
- **Erasure:** "nothing deleted can be recovered from raw storage" (`ui/copy.py:31`). The only
  evidence Studio has:
  - Part 4's demo: a simulated disk image of 6 records at d = 16 (`scripts/demo-p4.sh`, its own
    comment);
  - Studio's disk tab: a plaintext search for 40 live records.
- **The real-disk gates have not run:** P4-T1 and P4-T2 (target T-2, EX-2) wait for the VM run.
- **Receipts:** Part 3's gates are interim too. Parts 3 and 4 are not frozen, and their fairness
  runs are FAIL (the Evidence screen shows that).
- **Fix:** each claim card shows its status:
  - "Part 1: frozen";
  - "Part 2: frozen";
  - "Part 3: built; gates on the VM pending";
  - "Part 4: built; shown on a simulated disk; the real-disk gate is pending".

### High: a check that cannot fail, or shows more than it checked

**H1. On synthetic data, two rows tick from a stand-in.**
- **Freetext:** "Your own text, encoded by the pinned model" ticks ✓, though the text went
  through `fixture_encode`, a SHA-256 stand-in (`corpus.py:153`; E1). The check is only "the
  vector has length 1".
- **Encoder:** "One encoder" ticks ✓ by comparing three name strings (`actions.py:435-441`;
  E2).
- **Why it matters:** the tour's "Do it" runs on synthetic.
- **Fix:** offline, both rows stay "not available offline (no encoder)" and never tick.

**H2. The log-tree climb counts cosignatures; it never checks one.**
- **The test:** a receipt whose last cosignature byte was flipped.
- **Studio's climb says:** valid, "5 witnesses cosigned".
- **sever-verify says:** REJECT (E4; `wow.py:97` reads the count byte).
- **Why it matters:** the screen says the top "must equal the root that the operator signed and
  4 or more independent witnesses cosigned".
- **Fix:** say what the climb checks (the hashes, up to the root written in the receipt), and
  leave the signatures to sever-verify, run beside it.

**H3. Part 4's proof card.**
- **What it says:** "a forensic scanner with the whole disk" (`ui/copy.py:213`).
- **What runs:** a simulated image, 6 records, d = 16 (step 1 of its own output).
- **A check that cannot fail:** "every certificate of the deletion verifies" passes when step 2
  merely contains the word "verify" (`proofs.py:205`), so it passes on "verify FAILED" (E5).
- **Fix:**
  - say "simulated disk image, 6 records";
  - test step 2 for "verify (C_S pre → post)" on every certificate line it prints.

**H4. The deletion diagram asserts what nobody observed.**
- **`explain.delete_flow`:**
  - prints "the group's and the record's bucket key replaced, the old ones overwritten", and "C_S
    … moved by exactly C_t (§9.3)", for every deletion (E6);
  - reads no key file and checks no point arithmetic.
- **The tour's "Delete" chapter** says "keys rotated, old keys overwritten" too.
- **Fix:** replace the diagram with what was observed (n before and after from the engine, the
  receipt number, sever-verify's verdict); drop the unobserved steps.

### Medium

- **M1. "Float vs exact" is a mock of the engine's arithmetic.**
  - It's a numpy model, labelled, and it ticks nothing.
  - It still has its own tab and tour chapter, with the engine's real program one click away.
  - **Fix:** show Part 1's own result ("SEVER sum: 0 differences; float mean: N differ") as the
    demonstration and remove the model.
- **M2. Stale or overcounted words:**
  - tour chapter 3 says "Blue dots are in frozen groups … pink dots are in spawned groups"; the map
    now colours each frozen group and greys spawned ones;
  - "Five forgeries; each one caught": the lab has six rows;
  - the checklist row says "Every forgery of a receipt is caught" from 5 attempts.
- **M3. The sabotage lab has no control run.**
  - "Caught" means "a test failed" with the planted bug (`sabotage.py:148`).
  - A test failing for another reason would count too.
  - **Fix:** run the same command without the feature first; it must be green.
- **M4. After a crash, an insert that did not commit is re-sent by Studio silently.**
  - Where: `backend.py:589`.
  - The tile only says "the write in flight landed: no".
  - **Fix:** say "not committed; the application sent it again".
- **M5. Groups made says "k-means, as the partition builder (C-15) runs it".**
  - C-15 keeps the best of 10 k-means++ starts (`python/sever_partition/build.py:94-101`).
  - Studio steps one start with its own Lloyd loop (equal to scikit-learn's from the same start).
  - **Fix:** say "the same algorithm, one start".

### Low

- **L1.** The search row ticks when any judged answer is in any top 10 (`actions.py:690`).
- **L2.** Replay animates the preparation's recorded placements; only the tooltip says so.
- **L3.** The log screen's "✓ witness n" chips come from the checkpoint's list, not a signature
  check; the audit row does check them.

## 3. Simpler demonstrations instead of diagrams (the owner's ask)

| Now | Instead |
|---|---|
| Insert flow, 5 steps (`explain.insert_flow`) | One line: "the engine put it in X; its routing code agrees (d_M 3.2 > τ 2.9)" (already on the add result) |
| Delete flow, 5 steps with unobserved claims (H4) | One line: "deleted; frozen-0012 n 34 → 33; receipt #812, sever-verify ACCEPT" |
| Key hierarchy diagram (`explain.KEYS`, Disk tab) | Part 4's program, run: "scanner on the image: live record recovered; deleted: 0 findings; with rotation skipped (SB-24): found" |
| Commit-point diagram (`explain.COMMIT`, Crash tab) and the kill timeline | The crash and kill demos' own results: "killed after 112 acknowledged inserts; all 112 there; the one in flight: not committed" |
| Float vs exact model (M1) | Part 1's program result, two numbers |
| Log-tree climb drawing | Keep the climb as a short hash list with the honest label (H2), beside sever-verify's verdict |
| 21-chapter tour with long notes | About 10 chapters, one action each: add, search, delete, verify, tamper, crash, disk, part programs, sabotage, evidence |

Kept, because they show the real thing:
- sever-verify's step list on the receipt;
- the attack lab and the operator forgeries;
- the map in 2-D and 3-D;
- the 384-D separation chart;
- the crash, kill, restart and refusal demos;
- the four part programs.

## 4. Re-verified as real in this audit

- The engine's log replay against Studio's index, record by record.
- Routing predicted by the engine's own code against its placements (1,000 of 1,000).
- Spawned groups' IDs, sizes and centres (`spawn_proof.py`, bit for bit).
- Receipts verified and tampered with by `sever-verify`; the log audited by `sever-audit`.
- The attack lab, and Part 3's operator forgeries.
- Crash, kill-a-delete and restart with real SIGKILL and recovery.
- The SDK's typed refusals.
- The live plaintext scan of the database's files.
- The four part programs run live.
- The 384-D separation (§8.1, bit for bit).
- The Evidence screen, which shows the FAIL fairness runs as FAIL.
