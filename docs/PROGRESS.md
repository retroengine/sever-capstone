# Progress

Updated at the end of every session (CLAUDE.md §3.3). Newest session first in the log.

## Now

- **Phase:** P0 finishing (full `encode` running since 27 Sep 2026, 17:48 IST); demo track starting.
- **Current stage:** S1 — Constants and errors
- **Next small step:** read spec §2.2, §2.3 and §17; write `docs/notes/S01.md` in your own words.
- **Blocked on:** nothing for S1–S5 (SciQ embeddings are done). S14 data loading waits for `verify: OK`.

## Stages

| Stage | Status | Branch | Notes |
|---|---|---|---|
| P0 verify | running | — | Run `verify`; commit PINS.json, MANIFEST.sha256, meta.json |
| S1 Constants, errors | not started | | |
| S2 Vector arithmetic | not started | | |
| S3 Crypto core | not started | | |
| S4 Proof of knowledge | not started | | |
| S5 Partition builder | not started | | Apply G-1 (seed mod 2^32) |
| S6 Groups, exact deletion | not started | | |
| S7 Routing, spawning | not started | | |
| S8 Search | not started | | |
| S9 Merkle log | not started | | |
| S10 Checkpoints, witnesses | not started | | Needs G-4 decision |
| S11 Certificate encoding | not started | | |
| S12 Vault, crypto-shredding | not started | | Apply G-2 |
| S13 Client | not started | | |
| S14 Engine | not started | | |
| S15 Verifier | not started | | |
| S16 Presentation | not started | | |
| S17 Self-check | not started | | |

## Open questions

- (none yet)

## Session log

- **27 Sep 2026** — Specification, overview, demo plan and CLAUDE.md written. P0 encode running.
