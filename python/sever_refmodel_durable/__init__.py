"""sever_refmodel_durable: the durable oracle of Part 2 (Build §5.5).

After a crash, let A be the operations that were acknowledged. The one operation in flight may or
may not have reached its commit point. The recovered state MUST equal exactly one of two states
computed by ``sever_refmodel_core``: A applied, or A plus the in-flight operation; never anything in
between. This package computes those states (as canonical digests, one per operation of a stream)
and checks a crash campaign's results against them. It is written from the specification and the
build plan only, never from engine code (CLAUDE.md §7)."""
