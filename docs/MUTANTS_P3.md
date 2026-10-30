# Part 3 mutation survivors (P3-T9)

P3-T9 (Build 3-4 §1.9) asks for a mutation score of at least 90 % over `sever-crypto` and the
verifier and at least 85 % over `sever-cert` and `sever-log`, with **every surviving mutant
triaged** here; `gates p3-mutants` fails if a survivor's text is missing from this file. The text of
each survivor is `path:line:col: replacement`; the verifier's carry the prefix `verifier/`.

Where the numbers come from (DB-114): the first laptop run (30 Oct 2026, commit 7c445b5) left
83 survivors outside the verifier and tested no verifier mutant (its scratch copy lacked the files it
includes). The fixes: the verifier's scratch mirror; seven `sever-cert` mutants killed by tests from
the spec (red proofs PR3-K01 to K04); the lines only the sabotage builds compile (one in
`builder.rs`, four in `nonce.rs`) left out of the mutant sets and recorded in each result. The
survivors below are those still alive after these changes: the groups give the reason, each exact
text is in a code block.

## Equivalent: a capacity hint

`INCLUSION_FIXED` only sizes a `Vec::with_capacity`; a wrong value changes no byte of the encoding.

```
crates/sever-cert/src/encoding.rs:62:34: replace + with *
crates/sever-cert/src/encoding.rs:62:52: replace + with *
crates/sever-cert/src/encoding.rs:62:52: replace + with -
crates/sever-cert/src/encoding.rs:62:56: replace + with *
crates/sever-cert/src/encoding.rs:62:56: replace + with -
crates/sever-cert/src/encoding.rs:62:73: replace + with *
crates/sever-cert/src/encoding.rs:62:73: replace + with -
```

## Equivalent: a path over 64 hashes never verifies

The check `path.len() > 255` at `builder.rs:96`: tree sizes are `u64`, so a path over 64 hashes never verifies, and `verify_inclusion` right after it refuses it with the same error; moving the bound changes no reachable result.

```
crates/sever-cert/src/builder.rs:96:29: replace > with ==
crates/sever-cert/src/builder.rs:96:29: replace > with >=
```

## Equivalent: the participant's `id()`

The log participant's `id()` is compared only with itself: the log keeps its records in its own owned types and its outputs use the constant. The spec does not fix the value 3 (a note for after v1.0).

```
crates/sever-cert/src/participant.rs:459:9: replace <impl TxnParticipant<CommitmentExtension> for LogParticipant>::id -> u16 with 0
crates/sever-cert/src/participant.rs:459:9: replace <impl TxnParticipant<CommitmentExtension> for LogParticipant>::id -> u16 with 1
```

## Equivalent: a deletion always has a fresh witnessed checkpoint at `size`

A deletion issues only after a fresh witnessed checkpoint at `size` (line 228, §10.3), so the newest checkpoint covers every leaf and is witnessed; the search at lines 367 and 368 for the newest witnessed checkpoint beyond the insert leaf finds that same checkpoint under either `>`/`>=` or `&&`/`||`.

```
crates/sever-cert/src/participant.rs:367:44: replace > with >=
crates/sever-cert/src/participant.rs:368:25: replace && with ||
```

## Equivalent: the new record's `Put` is first

Part 1's frozen ChangeSet puts the new record's `Put` first, and a flush moves every holding record into the one new group, so the guards at lines 256 and 283 are true whenever they are reached.

```
crates/sever-cert/src/participant.rs:256:45: replace match guard slot.ext.insert_leaf_index == index with true
crates/sever-cert/src/participant.rs:283:52: replace match guard slot.ext.insert_leaf_index == index with true
```

## Defensive checks the engine cannot trip through its API

Only a corrupted transaction reaches these: `check_invariants` (reached by tests directly on `LogStore`, never through a broken log) and `abort` (on every refusal path nothing is staged in the log before it). Risk: low; a test that builds a corrupted participant state would kill them.

```
crates/sever-cert/src/participant.rs:317:32: replace < with >
crates/sever-cert/src/participant.rs:317:42: replace || with &&
crates/sever-cert/src/participant.rs:357:17: replace || with &&
crates/sever-cert/src/participant.rs:358:17: replace || with &&
crates/sever-cert/src/participant.rs:440:17: replace || with &&
crates/sever-cert/src/participant.rs:441:17: replace || with &&
crates/sever-cert/src/participant.rs:488:9: replace <impl TxnParticipant<CommitmentExtension> for LogParticipant>::abort with ()
crates/sever-cert/src/participant.rs:529:9: replace <impl TxnParticipant<CommitmentExtension> for LogParticipant>::check_invariants -> Result<(), Error> with Ok(())
```

## Equivalent: negating zero

`scalar_from_i64` for `v = 0`: `-0 = 0`, so `<` and `<=` give the same scalar.

```
crates/sever-crypto/src/group.rs:54:10: replace < with <=
```

## Equivalent: the `StrictProofRng` generator methods

merlin 3.0.0 draws with `fill_bytes` (transcript.rs:329); `next_u32`, `next_u64` and `try_fill_bytes` of `StrictProofRng` are never called.

```
crates/sever-crypto/src/nonce.rs:76:9: replace <impl RngCore for StrictProofRng>::next_u32 -> u32 with 0
crates/sever-crypto/src/nonce.rs:76:9: replace <impl RngCore for StrictProofRng>::next_u32 -> u32 with 1
crates/sever-crypto/src/nonce.rs:79:9: replace <impl RngCore for StrictProofRng>::next_u64 -> u64 with 0
crates/sever-crypto/src/nonce.rs:79:9: replace <impl RngCore for StrictProofRng>::next_u64 -> u64 with 1
crates/sever-crypto/src/nonce.rs:85:9: replace <impl RngCore for StrictProofRng>::try_fill_bytes -> Result<(), rand_core::Error> with Ok(())
```

## Equivalent: diagnostic output only

A `Debug` implementation that prints nothing. Debug output is never part of a stored format or result; the redaction tests only check that no key or ID appears, which an empty output also satisfies.

```
crates/sever-crypto/src/sig.rs:52:9: replace <impl std::fmt::Debug for KeyPair>::fmt -> std::fmt::Result with Ok(Default::default())
crates/sever-log/src/store.rs:239:9: replace <impl core::fmt::Debug for LogStore>::fmt -> core::fmt::Result with Ok(Default::default())
```

## Test gap, low risk: a wrong-length input to `prove_with_nonces`

No test passes an `s_post` of the wrong length; the only caller passes `d` values.

```
crates/sever-crypto/src/posk.rs:139:26: replace || with &&
```

## Caught only by the timeout (an infinite loop)

The mutant never terminates; the gate counts a timeout as not caught. `merkle.rs:48` is `*=` to `/=` in `split`; `:213` and `:262` make the inner `while` loop endless when `fn = 0`. No test can assert on a hang.

```
crates/sever-log/src/merkle.rs:213:36: replace && with ||
crates/sever-log/src/merkle.rs:262:36: replace && with ||
crates/sever-log/src/merkle.rs:48:11: replace *= with /=
```

## Equivalent: `subtree` already returns `None` beyond the size

`MerkleTree::root` for `n` over the size: `subtree` itself returns `None`, so the guard at `merkle.rs:130` changes no result.

```
crates/sever-log/src/merkle.rs:130:18: replace match guard n <= self.size() with true
```

## Defensive argument checks, never violated by a caller

Range checks on arguments that every caller in the workspace has already bounded (`merkle.rs:137`, `:163`, `:236`).

```
crates/sever-log/src/merkle.rs:137:19: replace || with &&
crates/sever-log/src/merkle.rs:163:19: replace || with &&
crates/sever-log/src/merkle.rs:163:29: replace || with &&
crates/sever-log/src/merkle.rs:236:38: replace || with &&
```

## Test gap: `verify_consistency` right-shift

`merkle.rs:263` (`>>=` to `<<=`): no test proof takes this branch; an all-pairs consistency test over small trees would. Risk: low (the shift only runs for proofs whose first node is an even size ratio).

```
crates/sever-log/src/merkle.rs:263:25: replace >>= with <<=
```

## Test gap: `EpochSigner` inherent methods and `Keyring::insert`'s result

`EpochSigner::epoch_at` and `genesis_ms` have inherent copies beside the `OperatorKeys` trait implementation (keys.rs:122); the engine and the certificate builder call the trait methods, so the inherent ones are exercised by no test. `Keyring::insert`'s returned `bool` is used by no caller.

```
crates/sever-log/src/keys.rs:103:9: replace EpochSigner::genesis_ms -> u64 with 0
crates/sever-log/src/keys.rs:103:9: replace EpochSigner::genesis_ms -> u64 with 1
crates/sever-log/src/keys.rs:23:51: replace == with !=
crates/sever-log/src/keys.rs:83:9: replace EpochSigner::epoch_at -> Option<u32> with Some(0)
crates/sever-log/src/keys.rs:83:9: replace EpochSigner::epoch_at -> Option<u32> with Some(1)
```

## Test-support code: the simulated witness and the EP-10 contract suite

`SimulatedWitness::add_key` and `epoch_at` are the simulated witness's own helpers; `ep10_contract` is the contract suite that Part 3 runs against that witness, and the mutants change its timestamps and the construction of its forked tree. A mutated suite still passes against the witness it was written for; this checks the suite's arithmetic, not the log.

```
crates/sever-log/src/witness.rs:112:9: replace SimulatedWitness::add_key -> bool with false
crates/sever-log/src/witness.rs:112:9: replace SimulatedWitness::add_key -> bool with true
crates/sever-log/src/witness.rs:117:9: replace SimulatedWitness::epoch_at -> Option<u32> with Some(0)
crates/sever-log/src/witness.rs:117:9: replace SimulatedWitness::epoch_at -> Option<u32> with Some(1)
crates/sever-log/src/witness.rs:187:28: replace == with !=
crates/sever-log/src/witness.rs:191:60: replace + with *
crates/sever-log/src/witness.rs:204:34: replace + with *
crates/sever-log/src/witness.rs:223:12: replace + with *
crates/sever-log/src/witness.rs:229:30: replace + with *
crates/sever-log/src/witness.rs:229:30: replace + with -
crates/sever-log/src/witness.rs:233:31: replace ^= with &=
crates/sever-log/src/witness.rs:234:31: replace + with *
crates/sever-log/src/witness.rs:234:31: replace + with -
```

## Defensive integrity checks of a stored log (`LogStore`)

These refuse a store whose files disagree with each other (`load`, `insert_leaf`, `certificate`, `replay`, `check_invariants`) or check the order of checkpoints (`push_checkpoint`, `stage_checkpoint`: an equal size is allowed, so `<` to `<=` is a test gap: no test pushes two checkpoints of one size). No test corrupts these fields one at a time; the crash campaign (P3-T4) reaches the recovery paths at scale but is not run per mutant. Risk: low.

```
crates/sever-log/src/store.rs:411:40: replace || with &&
crates/sever-log/src/store.rs:449:39: replace < with <=
crates/sever-log/src/store.rs:449:39: replace < with ==
crates/sever-log/src/store.rs:484:29: replace || with &&
crates/sever-log/src/store.rs:498:27: replace || with &&
crates/sever-log/src/store.rs:592:60: replace < with <=
crates/sever-log/src/store.rs:658:67: replace && with ||
crates/sever-log/src/store.rs:671:32: replace match guard self .stores .leaves .read(&at) .is_ok_and(|rec| rec.bytes == bytes) with false
crates/sever-log/src/store.rs:671:32: replace match guard self .stores .leaves .read(&at) .is_ok_and(|rec| rec.bytes == bytes) with true
crates/sever-log/src/store.rs:675:60: replace == with !=
crates/sever-log/src/store.rs:699:35: replace || with &&
crates/sever-log/src/store.rs:752:58: replace || with &&
```

## Verifier (own workspace; forecast 30 Oct 2026 on this branch: 219 caught, 5 missed, 1 timeout, 13 unviable = 219 / 225 = 97.3 %)

Equivalent, in `--explain`: line 43 `step > f` to `>=` (the arm for `f == step` comes first, so `step == f` never reaches it); line 46 `step == 8` guard to `false` (the arm needs a failed step below 8 yet `step == 8` is already "not reached", so it is never taken).

Equivalent, in `expand_message_xmd_sha512`: the ABORT test `ell > 255 || len_in_bytes > 65535` is repeated by the `u8::try_from(ell)` and `u16::try_from(len_in_bytes)` lines right after it, which also return `None`; a longer output always has `ell > 255` first, so no input tells the variants apart.

Caught only by the timeout: `merkle.rs:50` `&&` to `||` makes the shift loop endless once `f` reaches 0.

```
verifier/src/main.rs:46:24: replace match guard step == 8 with false
verifier/src/main.rs:43:34: replace > with >=
verifier/src/xmd.rs:17:18: replace || with &&
verifier/src/xmd.rs:17:34: replace > with ==
verifier/src/xmd.rs:17:34: replace > with >=
verifier/src/merkle.rs:50:34: replace && with ||
```
