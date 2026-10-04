"""sever_refmodel_core: the reference model C-18 for Part 1 (spec §3–§8).

Slow, in-memory and obviously correct, written from the specification only and never from engine
code (overview DB-4; CLAUDE.md §7). It is the oracle the Rust index is compared against, byte for
byte, through trace files (Build §2.4)."""
