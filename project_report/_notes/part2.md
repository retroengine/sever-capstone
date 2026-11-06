# Part 2 "The Database" - reading notes

Claim of Part 2 (CLAUDE.md s6.1): exactness survives a crash at any point; no acknowledged operation is lost; a multi-group deletion is all-or-nothing.
Tags: [CODE: path:Lx-Ly] verified in code; [DOC: path s] doc/spec only; [INFERRED: why]; [NOT FOUND: what searched].
All crate paths are under /home/saiki/sever-db/. Part 2 is a plaintext database: sealer_id 0, no confidentiality claim [CODE: crates/sever-txn/src/sealer.rs:98-100], [DOC: spec s14 "Sealer marker"].

## 0. Crate map (Part 2)

- sever-vfs: file-system trait `Vfs`/`VfsFile` (EP-5), `PosixVfs`, `SimVfs` (crash simulator), `durable` helpers [CODE: crates/sever-vfs/src/lib.rs:1-25].
- sever-format: byte layouts and strict parsers: file headers, MANIFEST, SECRETS, WAL records, store records, group header, slot, paged files, checkpoint streams, `DbImage` (in-memory stored form) [CODE: crates/sever-format/src/lib.rs:12-32].
- sever-wal: write-ahead log, segments, commit, recovery [CODE: crates/sever-wal/src/lib.rs].
- sever-appendstore: EP-8 `AppendStore` trait and `FileStore` (used for `payloads/`) [CODE: crates/sever-appendstore/src/lib.rs:27-35].
- sever-checkpoint: write/load storage checkpoints and MANIFEST install [CODE: crates/sever-checkpoint/src/lib.rs].
- sever-txn: EP-6 `Sealer`, EP-7 `TxnParticipant`, EP-9 `Clock`, record builders, and the commit protocol [CODE: crates/sever-txn/src/lib.rs:1-29].
- sever-engine: `Engine<E,S>`: collections, insert/delete/search, checkpoints, create/recover [CODE: crates/sever-engine/src/lib.rs:1-24].
- sever-p2: composition root `Engine<NoExtension, PlaintextSealer>` + CLI `sever-db-p2` + demo `sever-demo-p2` [CODE: crates/sever-p2/src/lib.rs:1-24].
- sever-py-p2: PyO3 module `sever_db_p2_native` [CODE: crates/sever-py-p2/src/lib.rs:1-7].
- sever-crashkit: crash campaign tool [CODE: crates/sever-crashkit/src/lib.rs:1-12].
- Python: python/sever_db_p2 (SDK wrapper, 156 lines), python/sever_refmodel_durable/oracle.py (durable oracle, 276 lines), python/sever_testkit_p2/{gates,oracle_check,proofs,spec_trace}.py.
- Part 1 is reused as frozen: sever-index (`Index`, `ChangeSet`, `GroupExtension`, `NoExtension`), sever-search, sever-quant, sever-partition, sever-types. [CODE: crates/sever-engine/src/engine.rs:13-27 imports].

## 1. VFS (EP-5)

### 1.1 Trait
- `Vfs` (Send+Sync) methods: `open(path, OpenMode)`, `fsync_dir(dir)`, `rename(from,to)` (atomically replaces a file at `to`), `unlink`, `list(dir)` (ascending by bytes), `create_dir`, `remove_dir` [CODE: crates/sever-vfs/src/lib.rs:141-157].
- `VfsFile` (Send) methods: `read_at(offset,buf)`, `write_at(offset,data)` (extends with zero gap), `append(data)->offset`, `truncate(len)`, `len()`, `is_empty()`, `fsync()`. No file position; explicit offsets only [CODE: crates/sever-vfs/src/lib.rs:116-134].
- `OpenMode`: `Existing`, `Create`, `CreateNew` [CODE: crates/sever-vfs/src/lib.rs:31-38].
- Spec s12.2 lists the same set; `create_dir`/`remove_dir` are extras for checkpoint directories (overview DB-65) [DOC: spec s12.2] [CODE: lib.rs:138-140 comment].
- `VfsError` variants: NotFound, AlreadyExists, NotADirectory, IsADirectory, DirectoryNotEmpty, InvalidPath, Crashed (SimVfs only), Io{op,kind}. No variant carries a path or content (spec s17) [CODE: crates/sever-vfs/src/lib.rs:71-96]; test `p2_vfs_errors_carry_no_path` [CODE: lib.rs:232-250].
- Path rules `check_path`: relative, `/`-separated; root is `""`; rejects leading/trailing `/`, empty component, `.`, `..`, NUL [CODE: crates/sever-vfs/src/lib.rs:162-175].
- Helpers: `read_all`, `read_exact_at` (short file -> Io UnexpectedEof), `parent(path)` [CODE: lib.rs:178-205].

### 1.2 PosixVfs
- Real files under a root dir; uses `pread/pwrite` (`FileExt::read_at / write_all_at`) and `sync_all`; never mmap (a failed write through a mapping kills the process by signal) [CODE: crates/sever-vfs/src/posix.rs:1-6,165-213].
- `fsync_dir` opens the dir and calls `sync_all` [CODE: posix.rs:84-91].
- `rename` refuses moving a dir into itself and refuses a dir replacing an existing entry [CODE: posix.rs:93-112].
- `list` sorts names by bytes and skips non-UTF-8 names [CODE: posix.rs:126-138].
- `append` = `len()` then `write_at` (relies on one writer per file, s12.5) [CODE: posix.rs:188-193].
- fsync error returned once; layer never retries [CODE: posix.rs:208-213].

### 1.3 SimVfs (crash simulator)
- Two views per file: `current` (what reads see = page cache) and `durable` (certainly on disk), plus a `pending` queue of unsynced `DataOp`s (Write/SetLen) [CODE: crates/sever-vfs/src/sim.rs:73-89]. Directories likewise: `current`, `durable`, `pending` DirOps (Put/Remove/Rename) [CODE: sim.rs:91-104].
- `fsync` on a file moves its pending writes into `durable` (`f.durable = f.current` when not diverged) [CODE: sim.rs:763-792]. `fsync_dir` applies the directory's pending ops to its durable map [CODE: sim.rs:578-601]. So: a file is only certainly there if its data was fsynced AND its directory entry was fsync_dir'd [CODE: sim.rs:9-13 comment; restart step 1 uses dir durable map: sim.rs:345-361].
- Crash policies (`CrashPolicy`): `DropAll` (nothing unsynced survives), `KeepAll` (everything unsynced survives in order, except writes lost to a failed fsync), `Random(seed)` (each unsynced write kept/dropped 1 in 2, kept ones shuffled, each may be torn at a random byte with 1-in-4 chance, each directory keeps a random prefix of its pending changes) [CODE: sim.rs:32-42, restart 340-420 (random branch 372-392)].
- Restart: `restart(policy)` rebuilds nodes = durable + policy-chosen pending; keeps only what is reachable from root; clears `crashed`, bumps `generation` (every handle from before the crash then returns `Crashed`) [CODE: sim.rs:340-450 incl. `self.generation += 1` near 436; `handle_alive` 203-211].
- Fault plan `FaultPlan {crash_at_op, tear_bytes, fail_sync_at}`, counted from `set_faults`. Crash happens DURING the n-th mutating op (write_at, append, truncate, fsync, fsync_dir, rename, unlink, create_dir, remove_dir, creating open); the op does not complete; later calls return `Crashed`. For a write, the first `tear_bytes` bytes reach the page cache (unsynced) first [CODE: sim.rs:44-57, 213-225, 299-338].
- Failed fsync: n-th fsync/fsync_dir fails with `Io`; like Linux after a write-back error, pending writes are DROPPED from the durable path but stay visible to reads, and a retried fsync "succeeds" without saving them (`diverged = true`). This is why a failed fsync must abort, never retry (SB-14) [CODE: sim.rs:15-17 comment; fsync fail branch 770-781; fsync_dir fail branch 588-596].
- `fork()` clones the disk cheaply (file contents `Arc` copy-on-write) so a campaign can fork once per crash point [CODE: sim.rs:79-81, 481].
- Stats: mutating_ops, fsyncs, dir_fsyncs, bytes_written (overview T-11) [CODE: sim.rs:59-71]. `write_log()` gives (path,size) of each mutating op, used for the 512-byte tear campaign [CODE: sim.rs:133-135, 506].
- `MAX_FILE` = 1<<32 (SimVfs refuses larger) [CODE: sim.rs:27].
- EP-5 contract suite (feature `contract-tests`): `ep5_functional_contract` and `ep5_crash_contract`; a backend that loses nothing fails the crash part (NeverDrops/NeverTears/NeverReorders) [CODE: crates/sever-vfs/src/contract.rs:1-12, 40-60, 86, 321].
- `FailingVfs` (sever-p2, feature `demo`): wraps a Vfs, n-th fsync/fsync_dir fails (env `SEVER_TEST_FAIL_FSYNC_AT`) for E2E-2.5 [CODE: crates/sever-p2/src/fault.rs:1-94; crates/sever-p2/src/bin/sever-db-p2.rs:103-113].

### 1.4 durable.rs (durability discipline, spec s12.7)
- `sync`, `sync_dir`: fsync once, never retry (SB-14 would retry) [CODE: crates/sever-vfs/src/durable.rs:9-26].
- `create` (open CreateNew then fsync parent dir), `create_dir`, `rename` (rename then fsync_dir of dest parent, and of source parent if different), `unlink` (then fsync parent) [CODE: durable.rs:28-59].
- `replace_file(path, bytes)`: unlink stale `path.tmp`, create `.tmp`, write, fsync, drop, durable rename -> crash leaves old or new, never mix [CODE: durable.rs:60-83 (fn begins at the "replace_file" definition near line 70)] [DOC: spec s15.6 step 3].
- Spec s12.7: every create/rename/unlink followed by fsync of containing dir; an fsync error aborts the process [DOC: spec s12.7]; engine implements abort via `FailurePolicy::Abort` -> `std::process::abort()` [CODE: crates/sever-engine/src/engine.rs:150-159].

## 2. sever-format: on-disk formats

General: all integers big-endian fixed width; CRC-32C (Castagnoli, `crc32c` crate) [CODE: crates/sever-format/src/codec.rs:11-14]. Version `FORMAT_VERSION = 1`; `SEALER_PLAINTEXT = 0`, `SEALER_AES_GCM_SIV = 1` [CODE: lib.rs:34-40]. Strict parsers return `IntegrityViolation{invariant: <fixed text>}` via `bad(check)`; trailing bytes rejected (`Reader::end`) [CODE: codec.rs:6-9; 83-172]. Check order for a header: CRC -> magic -> version -> sealer_id -> fields -> no trailing bytes [CODE: crates/sever-format/src/file.rs:10-40].

Magics (8 ASCII bytes) [CODE: crates/sever-format/src/lib.rs:43-64]:
MANIFEST "SVDBMANI"; WAL segment "SVDBWALS"; store "SVDBSTOR"; SECRETS "SVDBSECR"; checkpoint meta "SVDBMETA"; collections "SVDBCOLL"; groups "SVDBGRPS"; slots "SVDBSLOT"; locator "SVDBLOCA"; payload refs "SVDBPREF".

### 2.1 File header (append store), 16 bytes
`magic(8) | u16 version | u16 sealer_id | u32 crc32c` [CODE: file.rs:42-76], matches [DOC: spec s14.9].

### 2.2 WAL segment header, 32 bytes
`"SVDBWALS"(8) | u16 version | u16 sealer_id | u64 segment_seq | u64 first_wal_seq | u32 crc32c` [CODE: file.rs:78-125]. File named `wal/<segment_seq as 20 zero-padded digits>.wal` [CODE: crates/sever-wal/src/lib.rs:45-57]; spec s14.9 also says 20 digits [DOC: spec s14.9] (spec s12.3/s14.1 shorthand `wal/<seq>.wal`).

### 2.3 MANIFEST, 32 bytes
`"SVDBMANI"(8) | u16 version | u16 sealer_id | u64 checkpoint_id | u64 first_wal_seq | u32 crc32c` [CODE: file.rs:127-170]. `first_wal_seq` = replay starts at the record with this wal_seq.

### 2.4 SECRETS
`"SVDBSECR" | u16 version | u16 sealer_id | u32 entry_count | entries (u16 kind | u32 len | bytes)* | u32 crc32c`; kind 1 = k_scramble, exactly one, exactly 64 bytes (else `§9.7 k_scramble`); Debug redacted [CODE: file.rs:172-232]. Lives in the KEY directory, not data dir; written with `durable::replace_file`, chmod 0600 by sever-p2 [CODE: engine.rs:568-578; sever-p2/src/lib.rs:126-134]. k_scramble comes from the OS RNG (`OsRng`) [CODE: engine.rs:90-96, 570-571].

### 2.5 WAL record
`u32 len | u8 type | u64 wal_seq | u64 txn_id | payload | u32 crc32c`; `len` = whole record = 25 + payload; CRC covers every byte before it (including len) [CODE: crates/sever-format/src/wal.rs:1-3, 18-19, 140-153]. `RECORD_OVERHEAD = 25`; `MAX_RECORD = 64 MiB - 32` [CODE: wal.rs:19,22].
Type codes [CODE: wal.rs:27-62]: BEGIN 1, GROUP_CREATE 2, GROUP_HEADER 3, BUCKET_BLOCK 4, SLOT_PUT 5, SLOT_TRUNCATE 6, LOCATOR_PUT 7, LOCATOR_DEL 8, LOG_LEAF 9, LOG_CHECKPOINT 10, CERT_REF 11, PAYLOAD_REF 12, COUNTERS 13, EXTENSION 14, COMMIT 15, COLLECTION_CREATE 16, COLLECTION_DROP 17. Same as [DOC: spec s14.6].
Participant-owned (carried verbatim, never interpreted): 4, 9, 10, 11, 14 [CODE: wal.rs:90-100].
`parse_next(buf)` never errors: returns `End` (no bytes), `Record(rec,len)` or `Invalid` (len outside 25..=MAX_RECORD, short buffer, CRC mismatch, unknown type, torn/zeroed) [CODE: wal.rs:129-195].
Payloads of core records (all change payloads begin with 16-byte collection_id; group_id = 32 bytes zero-padded; scrambled_id = 64 bytes) [CODE: wal.rs:198-300 doc comments; encode_payload 347-415]:
- COLLECTION_CREATE: collection meta | u32 len | artefact bytes.
- COLLECTION_DROP: collection_id.
- GROUP_CREATE: collection_id | group header | u32 len | bucket block (empty in Part 2).
- GROUP_HEADER: collection_id | header.
- SLOT_PUT: collection_id | group_id | u64 slot index | slot.
- SLOT_TRUNCATE: collection_id | group_id | u64 new count.
- LOCATOR_PUT: collection_id | scrambled_id | group_id | u64 slot index. LOCATOR_DEL: collection_id | scrambled_id (also drops the payload reference).
- PAYLOAD_REF: collection_id | scrambled_id | u64 segment | u64 offset | u32 length.
- COUNTERS: collection_id | u64 N | u64 k.
- EXTENSION (participant): u16 participant_id | bytes.
- BEGIN / COMMIT: empty payload.
Collection meta (used in COLLECTION_CREATE and collections.bin): `collection_id(16) | u16 d | u32 spawn_target | u8 spawning_enabled | u8 store_passages | sha256_artefact(32)`; flags must be 0/1; d must be positive multiple of 8; spawn_target > 0 [CODE: crates/sever-format/src/image.rs:18-72].

### 2.6 Append-store record
`u64 key | u32 len | bytes | u32 crc32c`; overhead 16; value <= 16 MiB (`MAX_VALUE`); `parse_next` returns `None` for torn/invalid [CODE: crates/sever-format/src/store.rs:1-66].

### 2.7 Group header (spec s14.3)
`group_id(32 zero-padded) | u8 kind (0 frozen,1 spawned,2 holding) | u64 seal_version | u64 n | ext_public | centroid d x f64 big-endian bits | sealed accumulator (absent for holding)`. Kind byte must match what the ID implies; holding centroid must be all-zero bits [CODE: crates/sever-format/src/group.rs:1-120].
Accumulator plaintext: `S as d x i64be | extension group secret` [CODE: crates/sever-format/src/lib.rs:114-117].
Part 2 sizes: `Layout::plain(384)`: payload 1,794, slot 1,864, header 6,193 (holding 32+1+8+8+3072) [CODE: lib.rs:160-168 test]; released layout (Part 4): payload 1,835, slot 1,992, accumulator 3,104(+28), header 6,285 [CODE: lib.rs:147-157 test] [DOC: spec Appendix A].

### 2.8 Slot (spec s14.4)
`scrambled_id(64) | envelope | sealed payload | zero padding to multiple of 8`; slot_len = ceil((64+envelope+payload_len+seal_overhead)/8)*8. Padding must be zero (`§14.4 slot padding`). Payload plaintext: `u16 id_len | id zero-padded to 256 | x~ as d x i32be | extension record secret` [CODE: crates/sever-format/src/slot.rs:1-68; lib.rs:66-112].

### 2.9 Paged checkpoint files (spec s14.2)
Page = 16,384 bytes: `u32 page_type | u64 page_no | u64 wal_seq | payload | u32 crc32c`; payload bytes per page = 16384-24 = 16,360. Page 0 (type 1) payload: `magic | u16 version | u16 sealer_id | u64 stream_len` then zeros; pages 1.. (type 2) carry the stream, last page zero-padded. Decoder checks: size multiple of 16384 and non-empty, per-page CRC, page number equals position, page type, magic/version/sealer, stream_len consistent with page count, zero header padding; every page carries the covered `wal_seq` so a page from another checkpoint is rejected [CODE: crates/sever-format/src/paged.rs:1-90 (rest of decode is below line 90)].

### 2.10 Checkpoint streams (inside the paged files)
[CODE: crates/sever-format/src/image.rs:270-304 (struct docs), to_streams 311-364, from_streams 367+]
- meta.bin ("SVDBMETA"): `u64 checkpoint_id | u64 next_wal_seq | u64 next_txn_id | config SHA-256 (32) | u32 collection_count | collection ids (ascending)`.
- collections.bin ("SVDBCOLL"): per collection `meta | u64 N | u64 k`.
- groups.bin ("SVDBGRPS"): per collection `collection_id | u64 count | headers in creation order`.
- slots.bin ("SVDBSLOT"): per collection and group `collection_id | group_id | u64 count | slots`.
- locator.bin ("SVDBLOCA"): per collection `collection_id | u64 count | (scrambled_id | group_id | u64 slot index)*` ascending by scrambled_id.
- payloads.bin ("SVDBPREF"): per collection `collection_id | u64 count | (scrambled_id | segment | offset | len)*`.
- partitions/<32 hex of collection id>.svp: the partition artefact verbatim [CODE: crates/sever-checkpoint/src/lib.rs:35-39].
Matches [DOC: spec s14.9]. Loader: collections must be strictly ascending (`§14.1 meta.bin collection order`), counts bounded by `MAX_COUNT = 1<<32` so a corrupt count cannot force a huge allocation, every stream read to its last byte [CODE: image.rs:305-310, from_streams 367-420].

### 2.11 DbImage (the stored form in memory)
`DbImage { collections: BTreeMap<CollectionId, CollectionImage> }`; a `CollectionImage` has meta, artefact, groups (creation order: frozen groups, holding area, then spawned), locator, payload_refs, N, k [CODE: image.rs:109-130, 168-175]. `DbImage::apply(&CoreRecord)` is the ONE function used both at commit (apply phase) and at WAL replay; it is strict (unknown group, bad slot index, growing truncate, missing locator entry -> `IntegrityViolation`) and Begin/Commit/Participant records change nothing [CODE: image.rs:186-262].

## 3. WAL (sever-wal)

- Directory `wal/`; segment 64 MiB default (`DEFAULT_SEGMENT_BYTES`), segment closed when next record would exceed `segment_bytes` [CODE: crates/sever-wal/src/lib.rs:22-33].
- Identifiers: `wal_seq` = position of each record (u64, starts at 1 for a new DB: `Wal::create(..., 1, 1)`); `txn_id` per transaction; "LSN" in this code base = `wal_seq`. `database_lsn` is a different, Part-3 notion (leaf index) [CODE: crates/sever-engine/src/recovery.rs:83-91; wal.rs:282-283 comment] [DOC: spec s12.3 "WAL positions are called wal_seq. They are unrelated to database_lsn"].
- Transaction layout: BEGIN, change records, COMMIT. A transaction is committed exactly when its COMMIT record, with a valid CRC, is durable [CODE: sever-wal/src/lib.rs:5-7] [DOC: spec s12.3].
- `Wal::commit(records)`: builds the whole transaction in a buffer; one `append` per segment; `fsync` before returning; returns `Committed{txn_id, first_wal_seq, commit_wal_seq}`. If the transaction would overflow the segment mid-way, the part written so far is appended and fsynced, then a new segment is created (header written and fsynced, dir entry fsynced) and the rest continues there; so one transaction can span segments (uncommitted until COMMIT, so safe) [CODE: lib.rs:170-227, esp. 206-214 and 219].
- A single record larger than a segment body is refused (`§12.3 record larger than a segment`) [CODE: lib.rs:174-180].
- Any I/O failure while writing sets `failed = true`; the log then refuses all writes with `DurabilityFailure` (caller must abort) [CODE: lib.rs:171-185].
- Append offset sanity: `append` returns offset must equal `seg_len` else DurabilityFailure [CODE: lib.rs:229-240].
- `remove_covered(wal_seq)`: after a checkpoint, unlink oldest segments whose NEXT segment begins at or before `wal_seq`; never the current segment; fsync dir [CODE: lib.rs:242-259].
- New segment: `durable::create` (dir entry fsynced), write 32-byte header at 0, fsync [CODE: lib.rs:467-483].

### Recovery rules (`Wal::recover`) [CODE: crates/sever-wal/src/lib.rs:261-438]
1. List `wal/`; every name must be `<20 digits>.wal` else `§12.3 WAL file name`.
2. Read each segment header. Only the NEWEST segment may have a missing/torn header (crash while creating it): it is unlinked. A wrong sealer_id is always an error (`DB-48 sealer_id`). Any other bad header -> `§12.3 segment header` [lib.rs:279-306].
3. Find the segment containing `first_wal_seq` (from MANIFEST); older segments are covered leftovers and are unlinked. Segment numbers must be consecutive (`§12.3 segment sequence`) [lib.rs:308-323].
4. Scan records: each segment must start exactly at the expected wal_seq (`§12.3 wal_seq continuity`). TORN-TAIL vs CORRUPTION rule: if a record fails to parse (or has the wrong wal_seq) in the LAST segment AND no valid CRC-correct record with wal_seq >= expected starts anywhere later in that segment (`valid_record_after`), it is a torn tail -> stop and discard. If a valid record exists after the bad bytes in the last segment -> `IntegrityViolation "§12.3 corrupt record inside the log"` (discarding would silently lose acknowledged work). A bad record in a non-last segment -> `"§12.3 hole inside the log"` [lib.rs:345-358, 441-465].
5. Transaction structure: BEGIN with no open txn starts one (txn_id must be > previous and >= the checkpoint's `next_txn_id`, else `§12.3 transaction order`); COMMIT with matching txn_id closes and moves it to `committed`; other combos -> `§12.3 transaction structure`. Records with wal_seq < first_wal_seq are skipped (covered by the checkpoint) [lib.rs:361-391].
6. An open (uncommitted) transaction at the end is discarded (`discarded_txn = true`) - SB-13 would replay it instead [lib.rs:394-400].
7. Cut: everything after the end of the last complete transaction is cut: later segments unlinked, last segment truncated + fsynced (`truncated_bytes`) so the next transaction never follows garbage [lib.rs:402-424].
8. `next_wal_seq`/`next_txn_id` are set from the cut; `appended` (WAL bytes since last checkpoint, the trigger counter) is recomputed from disk so a restart does not forget it [lib.rs:425-437].
- Returned `Vec<Txn>` (txn_id + change records, no BEGIN/COMMIT) is replayed by the engine [CODE: crates/sever-engine/src/recovery.rs:120-142].
- The WAL "never repairs": it discards. Doc: spec s12.3 "discarded whole. It is never repaired." Consistent [DOC] [CODE: lib.rs:8-10].

## 4. Append store / payload store (EP-8)

- Trait `AppendStore: Send { append(key, bytes)->StoreRef; sync(); read(&StoreRef)->StoreRecord }`. `StoreRef = PayloadRef {segment, offset, len}` [CODE: crates/sever-appendstore/src/lib.rs:24-35].
- `FileStore`: directory of `<dir>/<20-digit seq>.store`; each segment = 16-byte file header (magic "SVDBSTOR") + records; 64 MiB default segment [CODE: lib.rs:37-64, 163-172].
- `append` encodes the record, rolls to a new segment (fsyncs the old one first) if it would exceed `segment_bytes`, appends, marks dirty; NOT durable until `sync()` [CODE: lib.rs:174-210]. Value > 16 MiB -> `§14.8 value too large`.
- `sync()` fsyncs the current segment if dirty; any failure marks the store failed [CODE: lib.rs:212-222].
- `read(at)`: opens the segment, reads `16 + len` bytes at offset, parses; must be exactly one valid record and offset >= 16; else `IntegrityViolation "§14.8 store reference" / "§14.8 store record"` [CODE: lib.rs:224-235].
- `open` after a restart: newest segment with an invalid header (when more than one segment) is unlinked; the tail after the last valid record is cut (truncate + fsync). "Unreferenced bytes after a crash are ignored and overwritten." [CODE: lib.rs:105-153] [DOC: spec s14.6 last paragraph, s14.8].
- Ordering rule: store bytes are fsynced BEFORE the WAL COMMIT that references them (protocol step 3 before step 5) [CODE: crates/sever-txn/src/protocol.rs:97-106] [DOC: spec s14.6].
- Part 2 uses one store: `payloads/` (passage text, plaintext since sealer 0). Key given to store records is an engine counter `store_key` (increments per append; starts at 0 each open) [CODE: engine.rs:386-389; recovery.rs:173]. A passage is stored only if the collection has `store_passages` [CODE: engine.rs:381].
- At recovery `check_payload_refs`: every payload ref must belong to a live record and be readable with a valid CRC [CODE: recovery.rs:294-304].
- Part 3/4 reuse the trait for log leaves, certificates and wrapped keys [DOC: spec s14.1 layout; sever-appendstore/src/lib.rs:10-11].
- Contract suite exists (feature `contract-tests`) [CODE: crates/sever-appendstore/src/contract.rs].

## 5. Storage checkpoints (sever-checkpoint)

What: a full serialisation of the `DbImage` into a new directory, installed atomically; bounded replay (spec s12.4, s15.6).
Steps in `write()` [CODE: crates/sever-checkpoint/src/lib.rs:97-138] (matches [DOC: spec s15.6]):
1. `img.to_streams(...)`. Remove any leftover `checkpoint/<id>.tmp`. `create_dir checkpoint/<id>.tmp`. For each of six files (meta.bin, collections.bin, groups.bin, slots.bin, locator.bin, payloads.bin) write the paged encoding (each carrying `next_wal_seq` in every page header) with `CreateNew`, write, fsync. Create `.tmp/partitions/` with one `.svp` per collection. fsync_dir on partitions/, .tmp/, checkpoint/.
2. `durable::rename(.tmp -> checkpoint/<id 20 digits>)` (fsync dir).
3. Install MANIFEST: `Manifest{sealer_id, checkpoint_id, first_wal_seq = meta.next_wal_seq}` via `durable::replace_file(MANIFEST)` (MANIFEST.tmp, fsync, rename, fsync dir). **MANIFEST is the commit point of a checkpoint**; crash earlier leaves the previous checkpoint named and whole [CODE: checkpoint lib.rs:12-13].
4. (engine) `remove_others(keep)` deletes other checkpoint dirs and `.tmp` leftovers (durably), then `wal.remove_covered(next_wal_seq)`, `reset_appended()` [CODE: crates/sever-engine/src/engine.rs:283-290; checkpoint lib.rs:140-155].
- `load(manifest)`: all six files strictly decoded with the manifest's sealer; each file's page wal_seq must equal `manifest.first_wal_seq` (`§15.6 checkpoint WAL position`); partitions listed, names must be 32 hex chars; meta's checkpoint_id and next_wal_seq must match the manifest (`§15.6 checkpoint does not match MANIFEST`) [CODE: lib.rs:169-223].
- `read_manifest` returns `None` if MANIFEST is absent ("no database here") [CODE: lib.rs:157-167].
- When taken: (a) `storage_checkpoint_now()` explicit; (b) automatically after a transaction when WAL bytes since last checkpoint >= `checkpoint_every_wal_bytes` (default 1 GiB = 1<<30); (c) `close()` (clean shutdown) [CODE: engine.rs:257-262, 504-509, 542-545; config.rs:46-47,59] [DOC: spec s12.4 "every 1 GiB of WAL and at clean shutdown"].
- First (empty) checkpoint at creation: id 1, next_wal_seq 1, next_txn_id 1 [CODE: recovery.rs:94-103].
- Checkpoint id for the next one = previous + 1 [CODE: engine.rs:266-268].
- Checkpoint directory name = id zero-padded to 20 digits [CODE: checkpoint lib.rs:30-33]; spec s14.1 only says `checkpoint/<id>/` [DOC].

## 6. Transaction protocol (sever-txn)

### 6.1 Extension-point traits
- `Sealer` (EP-6): `sealer_id()`, `seal_overhead()`, `envelope_len()`, `seal_record/open_record/rewrap_record`, `seal_passage/open_passage`, `next_version`, `seal_accumulator/open_accumulator` [CODE: crates/sever-txn/src/sealer.rs:34-96]. `PlaintextSealer`: sealer_id 0, overhead 0, envelope 0, "sealing" returns the bytes unchanged, seal_version always 0; non-empty envelope -> `DB-48 plaintext envelope` [CODE: sealer.rs:98-190 (start)].
- `TxnParticipant<E>` (EP-7), all hooks default to no-ops: `id()`, `owned_types()`, `pre_transaction(kind, collection)->Option<PreTxn>`, `prepare(&mut TxnDraft)`, `sync_stores()`, `phase_a()`, `abort()`, `after_commit()` (phase C), `replay(&WalRecord)`, `recover()`, `check_invariants()`, `on_drop_collection()`, `owns(record)` [CODE: crates/sever-txn/src/participant.rs:67-141]. `Participants<E> = Vec<Box<dyn TxnParticipant<E>>>`. Part 2 registers NONE (`Vec::new()`) [CODE: sever-p2/src/lib.rs:115].
- `TxnKind`: Insert, Delete (also delete_user), CreateCollection, DropCollection [CODE: participant.rs:15-24].
- `TxnDraft`: kind, collection, changeset (Option), `records` (core after-images in replay order), `participant_records`, `outputs` [CODE: participant.rs:27-45].
- `Clock` (EP-9): `now_ms()`; `SystemClock` (non-decreasing via `fetch_max`), `SimClock` (moves only with `advance`) [CODE: crates/sever-txn/src/clock.rs:7-51]. Nothing in Part 2 engine calls a clock (routing must be pure; spec s7) [INFERRED: engine.rs has no Clock import; grep]. 
- `StoredExtension` (DB-46): byte forms of an extension's public/secret state; `NoExtension` impl has all lengths 0 and rejects non-empty bytes (`DB-46 extension bytes`) [CODE: crates/sever-txn/src/ext.rs:1-67].
- Record builders: `changeset_records` turns Part 1's `ChangeSet` into after-image records in replay order (moves ciphertext slots without decrypting; flush re-wraps envelopes; every touched group gets a new header with re-sealed accumulator); `collection_records`; `layout_for::<E>(d, sealer)` [CODE: crates/sever-txn/src/records.rs:1-37,73,133]. `decode_collection`/`rebuild_changeset` rebuild an index from the image [CODE: decode.rs:31,87].

### 6.2 The exact sequence (`sever_txn::protocol::commit`) [CODE: crates/sever-txn/src/protocol.rs:1-143]
Header diagram in code (lines 3-12):
1 plan (caller: ChangeSet + after-image records; all validation here) -> 2 prepare (each participant) -> 3 append stores made durable (fsync) -> 4 phase A (participants' durable pre-commit actions) -> 5 WAL: BEGIN, core records, participant records, COMMIT; fsync = **COMMIT POINT** -> 6 apply to memory under the exclusive lock -> 7 phase C (`after_commit`) -> 8 acknowledge.
Detail:
- Step 2: each `prepare`; any error -> `abort()` on all, return (nothing written) [protocol.rs:74-84].
- Records are encoded before anything durable happens (an encode error is a plan error) [protocol.rs:85-96]; participant records appended after core records [protocol.rs:96].
- Step 3: `store.sync()` then each participant `sync_stores()` [protocol.rs:97-106].
- Step 4: `phase_a()` for each [protocol.rs:107-112].
- Step 5: `durable.wal.commit(&wal_records)`; on error -> abort participants and return error [protocol.rs:120-128]. The commit point is the moment this fsync returns (WAL COMMIT durable). Spec: "A transaction is committed exactly when its COMMIT record, with a valid CRC, is durable" [DOC: spec s12.3; s15.3 step 6 "This is the commit point"].
- Step 6: `apply(&draft.records)` is a closure from the engine that applies after-images to the image and the live index; it is called exactly once and "cannot fail" [protocol.rs:130-134]; nothing reaches memory before the commit point (memory never ahead of disk) [protocol.rs:14-16].
- Step 7: `after_commit()` for each participant; failure is a durability failure [protocol.rs:135-137].
- Step 8: return `Acknowledged{committed, outputs}` [protocol.rs:138-142].
- A `Step` hook is called at boundaries (Prepared, StoresSynced, PhaseA, WalWriting, Committed, Applied, PhaseC) for deterministic interleavings and the demo (feature `test-hooks`) [CODE: protocol.rs:26-44; engine.rs:222-229].
- Failure before the commit point changes nothing in memory; `DurabilityFailure` means the caller aborts [protocol.rs:14-16].

### 6.3 Multi-group all-or-nothing
- `delete_user(cid, ids)` plans every id in list order via `ix.plan_delete_many` into ONE ChangeSet, builds ONE record list, and runs ONE transaction. Since a transaction is committed iff its COMMIT is durable, recovery either replays all of it or discards all [CODE: crates/sever-engine/src/engine.rs:427-470] [DOC: spec s12.5 "delete_user ... in one transaction: all or nothing"].
- If no id is live (`cs.is_noop()`), the engine returns `AlreadyAbsent` for each and touches nothing (no WAL write) [CODE: engine.rs:445-448] [DOC: spec s15.3 step 1].
- Deletion stores nothing: the store-append closure returns `IntegrityViolation "§15.3 a deletion stores nothing"` if called [CODE: engine.rs:450-454].
- `delete(cid, id)` is `delete_user` with one id [CODE: engine.rs:419-424].

### 6.4 Isolation (spec s12.5)
- Writer `Mutex` (one writer, held for the whole mutation); state in `RwLock`: search takes a read lock; apply takes the write lock briefly; no snapshots [CODE: engine.rs:1-6, 61-74, 211-221, 491-502].

### 6.5 pre_transaction (erratum E-2)
- Hook: after planning, before `prepare`, a participant may return a `PreTxn{records}`; the engine commits it as its OWN WAL transaction first (`w.wal.commit(&pre.records)`), then calls the participant's `after_commit()`; on WAL failure calls `abort()` and returns the error [CODE: crates/sever-engine/src/engine.rs:191-201; participant.rs:59-86].
- The loop runs inside `Engine::run`, i.e. after `plan` has succeeded in `insert`/`delete_user`, so an absent record (no-op) or a failed integrity check never reaches it (spec s15.3 steps 1-2) [CODE: engine.rs:445-448 returns before `run`].
- Part 2 has no participants so the loop is empty; its purpose is Part 3's on-demand log checkpoint before a deletion (spec s15.3 step 3, SR-15.3-3) [DOC: ERRATA.md E-2].

## 7. Engine (sever-engine)

### 7.1 Types
- `Engine<E: StoredExtension, S: Sealer>` fields: vfs, sealer, ext, cfg, `k_scramble` (Zeroizing 64 bytes), `state: RwLock<State{image, live: BTreeMap<CollectionId, Index>}>`, `writer: Mutex<Writer{wal, store, participants, store_key, checkpoint_id, hook}>`, `poisoned: AtomicBool`, `wal_bytes`, `checkpoint_id` atomics (so `stats` never waits on a writer's I/O) [CODE: engine.rs:41-74].
- `EngineConfig`: wal_segment_bytes 64 MiB; store_segment_bytes 64 MiB; checkpoint_every_wal_bytes 1<<30; on_failure `FailurePolicy::Abort` default; config_hash [0;32] [CODE: crates/sever-engine/src/config.rs:40-64].
- `FailurePolicy`: `Abort` (production; `std::process::abort()`), `Poison` (tests/crashkit: refuse every later call with DurabilityFailure) [CODE: config.rs:29-37; engine.rs:150-159].
- `CollectionOptions{spawn_target (default 200 = SPAWN_TARGET_SIZE), spawning_enabled (true), store_passages (true)}` [CODE: config.rs:66-85; sever-types constants.rs:27].
- `InsertRequest<C>{record_id, vector: Vec<f32>, credential: C, passage: Option<Vec<u8>>}`; Part 2 credential is `()` [CODE: config.rs:87-99]. `InsertReceipt{placement, outputs}`. `DeleteOutcome::{AlreadyAbsent, Deleted{outputs}}`. `Hit{record_id, score}`. `EngineStats{frozen, spawned, big_n, k, holding, group_sizes, wal_bytes_since_checkpoint, checkpoint_id}` [CODE: config.rs:101-150].

### 7.2 Public API (Part 2 build) [CODE: crates/sever-engine/src/engine.rs]
- `Engine::open(vfs, keys, sealer, ext, participants, cfg)`: read MANIFEST; if none, `recovery::create`; then `open_existing` (recovery) [engine.rs:109-123].
- `create_collection(artefact_bytes, opts) -> CollectionId`: parses and verifies artefact (s6.3), draws a 16-byte `collection_id` from the OS, builds meta + index + records, one transaction `CreateCollection` [engine.rs:295-333].
- `drop_collection(cid)`: calls participants' `on_drop_collection`, commits a `COLLECTION_DROP` transaction; bytes leave disk with the next checkpoint; no cryptographic erase in Part 2 (Part 4) [engine.rs:335-361] [DOC: spec s15.9].
- `insert(cid, InsertRequest)`: under the writer mutex, `ix.plan_insert` (Part 1 validation: dimension, finite, normalised, record-id rules, duplicate), then builds records; passage bytes appended to payload store INSIDE the plan closure (before the commit; fsynced in step 3), then `run(...)` [engine.rs:363-416]. A retry of a committed insert fails with `DuplicateRecord{same_commitment:true}` (SDK treats as success) [engine.rs:363-364 doc; sever-db-p2 python SDK].
- `delete(cid, id)`, `delete_user(cid, ids)`: see 6.3.
- `search(cid, query, k)`: `alive()` check, read lock, calls frozen `sever_search::search`; never writes [engine.rs:490-502].
- `storage_checkpoint_now()`, `stats(cid)`, `collections()`, `close(self)` (= final checkpoint), `is_poisoned()` [engine.rs:504-550].
- There is no separate `delete_user` "by user" lookup: the caller supplies the list of record ids (cohort) [CODE: engine.rs:427-431].
- Test-hooks feature (never in measured builds): `set_step_hook`, `location`, `group_snapshot`, `survivors_snapshot`, `group_ids`, `canonical_state`, `passage` [CODE: crates/sever-engine/src/hooks.rs:29-107].

### 7.3 Recovery steps (every `open`) [CODE: crates/sever-engine/src/recovery.rs:1-182]
Creation (`recovery::create`, only when no MANIFEST): directory must contain only creation leftovers (`wal`, `payloads`, `checkpoint`, `MANIFEST.tmp`, `ENGINE.lock`) else `IntegrityViolation "§14.1 data directory holds files that are not a database"`; removes leftovers; writes SECRETS (key dir); `Wal::create`; `FileStore::create`; `checkpoint::create_root`; writes empty checkpoint id 1 which installs MANIFEST LAST - until MANIFEST exists there is no database [recovery.rs:40-104].
Recovery (`open_existing`):
1. read SECRETS -> k_scramble [recovery.rs:117].
2. load the storage checkpoint named by MANIFEST (strict) [recovery.rs:120].
3. `Wal::recover(first_wal_seq, next_txn_id)` -> committed txns [recovery.rs:121-129].
4. replay each record: participant-type records go to the participant that `owns` it (none registered => `§15.7 participant record without participant`); core records parsed with `CoreRecord::parse` then `image.apply` [recovery.rs:130-142].
5. each participant `recover()` [recovery.rs:143-145].
6. `FileStore::open` (cut torn tail of payload store); `checkpoint::remove_others` (delete stale checkpoint dirs) [recovery.rs:146-147].
7. For each collection: parse artefact, `rebuild_collection` (full invariant check), `check_payload_refs`; participants `check_invariants` [recovery.rs:150-159].
8. Serve (build `Engine`) [recovery.rs:162-181].
Invariants checked in `rebuild_collection` [recovery.rs:184-292]: artefact sha256 and d match the collection meta (`§6.3`); group order = frozen groups (label order, centroid bits equal artefact) then holding then spawned (`§5.1 group order`, `§5.1 frozen group`); `n == slot count` (INV-6); `n <= MAX_GROUP_MEMBERS` = 1,000,000 (INV-4); decode all groups; `S == sum of x~` with checked i64 add (`INV-6 S equals the sum of members`, `INV-6 sum overflow`); extension `check_group`; every `scramble(cid, record_id) == scrambled_id` (`§9.7`); one live record per ID (`§3.2`); derived locator == stored locator (INV-7); N and k recomputed == stored (INV-8); then Part 1's `ix.check_invariants()`.
Platform and lock are NOT inside the engine: sever-p2 does `create_dir_all`, `check_data_dir` (ext4/XFS `statfs` magic 0xEF53 / 0x58465342, override `allow_unsafe_fs`), `EngineLock::acquire` (`flock` NonBlockingLockExclusive on `ENGINE.lock`), config SHA-256, then `Engine::open`, then chmod 0600 SECRETS [CODE: crates/sever-p2/src/lib.rs:81-124; crates/sever-engine/src/platform.rs:187-227] [DOC: spec s15.7 step 1, s12.9].

### 7.4 IntegrityViolation behaviour
- A failed invariant during `open` returns `Err(IntegrityViolation{invariant})` - the engine is not built, so it refuses to serve (spec s15.7 step 6) [CODE: recovery.rs:153,287; CLI prints `{"error":"IntegrityViolation"}` sever-db-p2.rs:224-227].
- At runtime: if applying an after-image to the image fails after COMMIT (a bug) the engine sets `poisoned` and returns `IntegrityViolation "§12.3 after-image did not apply"` [CODE: engine.rs:210-251]. Only `DurabilityFailure` is routed through `fail()` (abort/poison) [CODE: engine.rs:150-159].
- Other `IntegrityViolation`s at runtime (e.g. from planning) do NOT stop the engine: it keeps serving and `close()` still writes a checkpoint. Spec s17 / G-42 says an IntegrityViolation must stop serving and not checkpoint; Part 2 does not do this: limit L-28 [CODE: engine.rs:150-159 (only DurabilityFailure handled), 543-545] [DOC: docs/SPEC_GAPS.md G-42 row "Part 2's builds keep the limit"; overview L-28].

### 7.5 fsync policy
- One fsync (WAL file) per committed transaction in `Wal::commit` (no group commit; txn spanning segments adds one fsync per extra segment) [CODE: sever-wal lib.rs:206-219]. Payload store fsync (`store.sync()`) once per transaction if dirty [CODE: appendstore lib.rs:212-222; protocol.rs:98-101].
- Every creation/rename/unlink followed by `fsync_dir` (durable helpers) [CODE: durable.rs]. fsync failure: never retried; engine aborts (production) or poisons (tests) [CODE: engine.rs:150-159].
- Mid-recovery truncation also fsyncs [CODE: sever-wal lib.rs:420-424].

### 7.6 File layout of a Part 2 database (names only)
Data dir: `ENGINE.lock`; `MANIFEST` (and transient `MANIFEST.tmp`); `checkpoint/<20-digit id>/{meta.bin, collections.bin, groups.bin, slots.bin, locator.bin, payloads.bin, partitions/<32hex>.svp}` (transient `checkpoint/<id>.tmp/`); `wal/<20-digit seq>.wal`; `payloads/<20-digit seq>.store`.
Key dir: `SECRETS` (mode 0600).
[CODE: checkpoint lib.rs:21-49; wal lib.rs:22,45-48; appendstore lib.rs:55-57; engine.rs:36-39; recovery.rs:40-47] [DOC: spec s14.1 lists more dirs (log/, certs/, wrapped/, KEYS, WITNESSES) that are Part 3/4].

## 8. CLI, demo, SDK

### 8.1 `sever-db-p2` (crates/sever-p2/src/bin/sever-db-p2.rs)
Usage: `sever-db-p2 <command> --data DIR --keys DIR [--allow-unsafe-fs] [--config FILE] ...`. Every command opens the database (recovery + invariant check), does one thing, prints ONE JSON line, closes (drops). Errors print `{"error":"<kind>"}` exit 1; usage errors exit 2 [CODE: sever-db-p2.rs:1-17, 217-233].
Commands [CODE: sever-db-p2.rs:122-214]:
- `create --artefact FILE [--spawn-target N (200)] [--frozen-only] [--no-passages]` -> `{"cid": hex32}`.
- `load --cid HEX --slice nq-10k|nq-100k|synthetic [--root DIR] [--seed S (42)] [--limit N]`: inserts a dataset slice one by one (no passages) -> stats JSON (uses `sever_p1::data`).
- `insert --cid --id ID --vector JSON [--passage TEXT]` -> `{"placement": ...}`.
- `delete --cid --id ID` -> `{"outcome":"deleted"|"absent"}`.
- `delete-user --cid --ids JSON` -> `{"outcomes":[...]}`.
- `search --cid --vector JSON [--k N (10)]` -> `{"hits":[[id,score],...]}`.
- `stats --cid` -> `{frozen, spawned, N, k, holding, checkpoint_id}`.
- `drop --cid`; `checkpoint`; `verify` -> `{"ok":true,"collections":[...],"platform_overridden":bool}`.
- Test-only: with feature `demo`, env `SEVER_TEST_FAIL_FSYNC_AT=n` makes the n-th fsync fail (E2E-2.5) [sever-db-p2.rs:103-113].
- Spec s16.3 command-line table lists only Part 3+ tools (sever-verify etc.); `sever-db-p2` is Part 2's own tool from Build s5.5 [DOC: spec s16.3; CODE header].

### 8.2 `sever-demo-p2 durable` (spec/Build s5.9)
`sever-demo-p2 durable --data nq-10k|synthetic [--seed 42] [--root .] [--work DIR(artefacts/demo)] [--out FILE]`; hidden `child-delete-user` subcommand [CODE: crates/sever-p2/src/bin/sever-demo-p2.rs:1-66]. Needs feature `demo` (enables engine `test-hooks`) [CODE: sever-p2/Cargo.toml:9-11].
Steps [CODE: crates/sever-p2/src/demo.rs:106-262]:
1. Load all passages into a database on SimVfs; checkpoint; pick the cohort (one article title) whose live records span the most groups.
2-3. Twice (with a step hook), run `delete_user(cohort)` and crash the simulated disk at (a) `Step::WalWriting` ("before the commit point") and (b) `Step::Committed` ("after"); `restart(DropAll)`; reopen (recovery + invariant check); verdict = "none deleted" / "all deleted" / "PARTIAL"; run Part 1's survivors check (`assert_state_equivalent` on `group_snapshot` vs `survivors_snapshot`) on each touched group.
4. Same on real files: spawn a child process that pauses inside delete_user (at "wal" or "committed") and SIGKILL it (`child.kill()`), restart, verify.
5. Report JSON with `all_or_nothing` and `commit_point_respected` (expected: before -> none deleted, after -> all deleted). Exit nonzero if a partial deletion is found [demo.rs:263-300; bin:38-50].
Report note: "plaintext database (DB-48): no confidentiality claim". The demo shows one deletion; evidence is the campaign [demo.rs:6].

### 8.3 Python SDK `sever_db_p2` (python/sever_db_p2/__init__.py + crates/sever-py-p2/src/lib.rs)
Native module `sever_db_p2_native`, class `Engine` [CODE: sever-py-p2/src/lib.rs:102-289]. `Database` wrapper [CODE: python/sever_db_p2/__init__.py:68-156]:
- `Database.open(data_dir, key_dir, allow_unsafe_fs=False)` (classmethod); context manager (`__exit__` calls `close`).
- `create_collection(artefact_path, spawn_target=200, spawning_enabled=True, store_passages=True) -> str` (32-hex cid).
- `insert(collection, record_id, vector, passage=None) -> Receipt(placement, retried=False)`; catches `DuplicateRecord` with `args[0] is True` -> `Receipt(None, retried=True)` (spec s15.1).
- `delete(collection, record_id) -> "deleted"|"absent"`; `delete_user(collection, record_ids) -> list[...]` (one transaction).
- `search(collection, query, k=10) -> [(record_id, score)]`; `stats(collection) -> dict` (frozen, spawned, N, k, holding, checkpoint_id); `group_sizes`; `collections`; `drop_collection`; `checkpoint`; `close` (clean shutdown checkpoint + release lock).
Exceptions: `SeverError` base + `WrongDimension, NonFinite, NotNormalised, InvalidRecordId, DuplicateRecord, GroupCapacityExceeded, UnknownCollection, PlatformUnsafe, IntegrityViolation, DurabilityFailure` (messages are fixed engine text, no ids/values) [CODE: sever-py-p2 lib.rs:23-95]. `CommitmentMismatch`, `BadUserSignature`, `SeededNonceForbidden` fall to generic `SeverError` (Part 3 concepts) [CODE: lib.rs:93].
Threading: every engine call runs through `PyEngine::with`, which takes the engine mutex INSIDE `py.detach` (GIL released) [CODE: lib.rs:107-125; close 281-288]. Because the Mutex is held for the whole call, calls from several Python threads are serialised against each other (a search waits for a running write); the module doc claim that "threads can search while another thread writes" is true only in the sense that the GIL is free, not that the engine runs them in parallel [CODE: lib.rs:6-7 vs 108-124] [INFERRED: Mutex<Option<Opened>> guards `f(&Opened)` for the full closure].
Python-side limit L-28(a): a record id with no UTF-8 encoding raises `UnicodeEncodeError` instead of `InvalidRecordId` [DOC: overview L-28] [NOT FOUND: no encode guard in __init__.py insert, grep].

## 9. Crash campaign (sever-crashkit, gates P2-T1..T3)

Goal (Build s5.7 L10, overview EX-1): crash on SimVfs at many points of a 20,000-operation stream and compare recovered states with an independent oracle [CODE: crates/sever-crashkit/src/lib.rs:1-12; campaign.rs:1-18] [DOC: Build s5.7 L10].
Targets [DOC: Build s5.8, docs/SEVER-DB_BUILD_PLAN_PART_1-2.md:912-914]: P2-T1 (5 seeds: 0 exactness violations, 0 lost acknowledged ops, 0 corrupt recoveries, 0 startup refusals after an honest crash), P2-T2 (100% recovered states equal an oracle-allowed state byte for byte), P2-T3 (0 partial `delete_user`).
Pipeline:
1. Python oracle `sever_refmodel_durable.oracle write` produces a JSONL: header with initial-state digest `s0` and one line per op with digest after it (`{"t":"i"|"d"|"x", ..., "s"}`) [CODE: python/sever_refmodel_durable/oracle.py:1-30]. The state digest = SHA-256("SEVERDB-STATE-1" | u64 N | u64 k | u32 group_count | per frozen/spawned group ascending by ID bytes: u16 id_len, id, u32 blob_len, canonical blob | u32 holding_count | each holding id) built from the Part 1 reference model `sever_refmodel_core` [oracle.py:46-62]. Stream = inserts of all passages, then each deletion-rung cohort as `delete_user`, then single `delete` of every remaining record ascending by ID bytes, then re-inserts until 20,000 ops (`TOTAL_OPS`) [oracle.py:65-87, 22-26].
2. Generic phase first (`generic.rs`): a key-value store on the WAL and a snapshot file without index code, so a durability bug has one home [CODE: crashkit lib.rs:3-5].
3. Index campaign (`campaign::run_resumable`): a "main" engine runs the stream on SimVfs; before each op the disks are forked (`base`); the op runs on main while recording how many VFS mutating ops it performs (`m = ops_since_plan`) and its write log. Then from `base` replay the op with a crash during the k-th VFS operation [CODE: campaign.rs:1-18, 478-502]:
   - **step** crashes: every k in 1..=m for every op (each protocol-step boundary lies between two VFS ops), crash policy rotating DropAll / KeepAll / Random(seed^rotate) [campaign.rs:484-494 area]. 
   - **offset** crashes: for a seeded sample of ops (`offset_samples`, Build s5.7: 200) every WAL write is torn at each 512-byte offset, with KeepAll so the torn prefix reaches the disk [campaign.rs:495-512 area].
   - **random** crashes: `random_points` (Build: 1,000) seeded (op, point, tear < 8192, policy) triples [campaign.rs:452-462 area].
   - **double** crash: every `double_every`-th crash point also crashes during recovery (crash at VFS op 1..4 of the first reopen), restarts with a random policy, recovers again; the digest must equal the single-recovery digest (recovery idempotent) [campaign.rs:211-220 area].
   After each crash: restart disks with the policy, open engine (recovery + full invariant check runs), compute digest of `canonical_state`, then RETRY the in-flight op: an insert retried after a commit must give `DuplicateRecord{same_commitment:true}`, uncommitted -> normal success; deletes retried after commit are all `AlreadyAbsent`, uncommitted -> at least one actually deletes; and the digest after the retry must equal the oracle's digest i+1 [campaign.rs:182-211 area].
   All seeded choices use `SplitMix64` from sever-vfs; keys/collection ids are NOT seeded (from the OS) [campaign.rs:20-36 (Settings.seed doc)].
   Settings use small checkpoint threshold and small WAL/store segments so checkpoints and segment rollovers happen inside the stream [campaign.rs:39-48].
   Resumable via progress files (every 30 s) [campaign.rs:392-404].
4. Verdict: `sever_refmodel_durable.oracle.check(oracle, results)`: for each crash result with `acked = a` (ops acknowledged before the in-flight op), allowed states = {digest[a], digest[a+1]}; `state == null` -> startup_refusal; state not allowed -> not_oracle_state; if it equals an earlier digest -> lost_acknowledged; if the in-flight op was a delete_user -> partial_delete_user; bad retry; double-crash mismatch. Every counter must be 0 [CODE: oracle.py:139-196].
5. Gate runner: `PYTHONHASHSEED=0 PYTHONPATH=python uv run python -m sever_testkit_p2.gates p2-crash --data nq-10k --all-seeds --jobs 3` (writes run ledger; ~7 h per CLAUDE.md s9) [CODE: python/sever_testkit_p2/gates.py:1-60,168-244]. Other gates there: p2-fuzz (P2-T6), p2-replay (P2-T5, Part 1 traces through the Part 2 engine in modes plain/close/crash), p2-sabotage (P2-T8), p2-measures (P2-T11), p2-coverage/p2-mutants (P2-T9), p2-checks, p2-spikes (P2-T7 proof spike `spikes/p2-proof`) [CODE: gates.py:3-45,610-640].
6. Other crashkit subcommands: `generic`, `campaign`, `replay-p1`, `measure` [CODE: crates/sever-crashkit/src/main.rs:1-13].
Other Part 2 tests (not exhaustively read): proofs in tests/proofs/p2 (141 files incl. MANIFEST.yaml), fuzz targets under fuzz/, e2e tests in tests/e2e, errata in tests/errata [INFERRED: ls output]. Test-oracle discipline for Part 2 (CLAUDE.md s6.3): `sever_testkit_p2.oracle_check`, `proofs` [CODE: python/sever_testkit_p2/].

## 10. Sabotage SB-11 .. SB-15 (Build s2.6, table at docs/SEVER-DB_BUILD_PLAN_PART_1-2.md:269-273)
Runner: tests/sabotage/run.sh builds with `--features sabotage-SB-N` and passes only if a test goes red [CODE: tests/sabotage/run.sh:36-56 (rust fn 30-38; SB-11..15 at lines 50-54)].
- SB-11 accept a WAL record with a bad CRC: `if crc(body) != stored && !cfg!(feature = "sabotage-SB-11") { return Invalid }` [CODE: crates/sever-format/src/wal.rs:175]; feature declared at crates/sever-format/Cargo.toml:11. Breaks: torn/corrupt records are accepted as valid on recovery.
- SB-12 skip the directory fsync after a rename: `durable::rename` returns early after `vfs.rename` [CODE: crates/sever-vfs/src/durable.rs:45-47]; feature crates/sever-vfs/Cargo.toml:13. Breaks: checkpoint/MANIFEST/.tmp installs may be lost on crash.
- SB-13 replay an uncommitted transaction: leftover open txn pushed into `committed` [CODE: crates/sever-wal/src/lib.rs:397-399]; feature crates/sever-wal/Cargo.toml:11.
- SB-14 retry a failed fsync: `durable::sync` and `sync_dir` retry once after an error [CODE: crates/sever-vfs/src/durable.rs:13-15, 22-24]; feature vfs Cargo.toml:14. With SimVfs the retry "succeeds" without saving the data.
- SB-15 apply a change to memory before COMMIT is durable: in `protocol::commit` the `apply` closure is run before `wal.commit` [CODE: crates/sever-txn/src/protocol.rs:113-119]; feature crates/sever-txn/Cargo.toml:13.
Gate P2-T8: each SB turns at least one test red [DOC: Build s5.8].

## 11. Errata (ERRATA.md)
Only E-1 and E-2 exist in the file [CODE: ERRATA.md:1-52]. (Overview mentions E-3..E-6 as dropped proposals: DB-112 [DOC: overview line ~1155-1161].)
- **E-1** (found by clean-room tester, fair run 20261008T164154Z-p2-42fc06df, test `test_concurrent_reader_sees_all_or_nothing`, s12.5): Python SDK deadlocked when one `Database` was used from several threads (searches during `delete_user` never returned). Root cause: sever-py-p2 took the engine mutex while holding the GIL, then released the GIL for the engine call; a thread holding the mutex waited for the GIL to return its result while the GIL holder waited for the mutex. Fix: take the mutex inside `py.detach` (GIL released) in `PyEngine::with` and `close` (commit 061d785, "erratum(E-1)"); files: crates/sever-py-p2/src/lib.rs [CODE: lib.rs:113-118, 282-283]. Regression test `tests/errata/test_p2_e1_sdk_threads.py::test_p2_errata_e1_sdk_searches_from_threads_during_delete_user` committed first at a494354 (red: timed out 60 s). Red proof PR-ERR1. Tag `part-2-frozen-e1` (exists) [CODE: git tag list].
- **E-2** (found 15 Oct 2026 building Part 3's LogParticipant): the engine never called a participant's `pre_transaction` (EP-7), so Part 3 could not commit its on-demand log checkpoint as its own transaction before a deletion (spec s15.3 step 3, SR-15.3-3). Root cause: hook declared in sever-txn but no engine path invoked it; Part 2 registers no participant so no test noticed. Fix (commit a244264): `Engine::run` calls each participant's `pre_transaction` after planning and commits a requested PreTxn as its own WAL transaction, confirmed by `after_commit` (abort on WAL failure), before the operation's transaction [CODE: engine.rs:191-201]; doc-comment-only change in sever-txn/participant.rs. Regression test `crates/sever-engine/tests/errata_e2.rs::p2_errata_e2_a_pre_transaction_commits_on_its_own_before_the_deletion` committed first at 8c314a5 (red: deletion prepared with no pre-transaction). Red proof PR-ERR2. Tag `part-2-frozen-e2` exists (ERRATA.md still says "left to the owner") [CODE: git tag; ERRATA.md:51].
- **L-28** (overview, DB-103/DB-112): the frozen Part 2 builds keep three known defects, no erratum planned: (1) SDK raises `UnicodeEncodeError` instead of `InvalidRecordId` for a record id with no UTF-8 encoding; (2) builds keep serving after an `IntegrityViolation` and checkpoint at close (G-42); (3) the frozen spec tracer misses a split `#[spec]` attribute. The v1 build (`sever-db`) has none of them [DOC: docs/SEVER-DB_PROJECT_OVERVIEW.md:2522-2525; docs/SPEC_GAPS.md G-42].

## 12. Doc-vs-code mismatches / observations
1. Spec s17 + G-42: "every IntegrityViolation stops the engine serving; close() writes nothing". Part 2 code: only the after-image-apply failure poisons; other IntegrityViolations leave the engine serving and close() checkpoints [CODE: engine.rs:150-159, 210-251, 543-545]. Acknowledged as L-28.
2. Spec s16.1 shows `Engine::open(&EngineConfig)`, `create_collection(artefact: &Path, ...)`, insert with r_t/c_t/signature, `InsertReceipt{database_lsn,...}`, `DeleteOutcome::Deleted{database_lsn, certificate}`. Part 2 code: `Engine::open(vfs, keys, sealer, ext, participants, cfg)`, `create_collection(&[u8], opts)`, credential `()`, `InsertReceipt{placement, outputs}`, `Deleted{outputs}` [CODE: engine.rs:109-116, 297-300; config.rs:87-120]. Expected: Part 2 scope (Build s5.5), the full API lands with Part 3/4 [INFERRED].
3. Spec s15.7 step 2 (re-derive and check generators, s9.2) and step 4 (key-file recovery) are not in the Part 2 engine [NOT FOUND: grep "generator" in crates/sever-engine/src returned nothing]. Part 2 scope excludes them (s9 is Part 3, s13.4 Part 4) [INFERRED].
4. Spec s15.7 step 1 (ENGINE.lock, platform checks, memory hygiene s12.8) is done in sever-p2, not in `Engine::open`; memory hygiene (s12.8) is Part 4 [CODE: sever-p2/src/lib.rs:81-124; platform.rs:1-3 comment].
5. Spec s14.1 checkpoint dir `checkpoint/<id>/` and `wal/<seq>.wal`: code pads ids to 20 digits (spec s14.9 states 20 digits for WAL only; checkpoint padding is not in spec) [CODE: checkpoint lib.rs:30-33; wal lib.rs:46-48] [DOC: spec s14.9]. Minor undocumented detail.
6. Spec s12.3 says the WAL discard is "never repaired"; code does cut/truncate the torn tail (not repair, but it modifies the file so that the next txn does not follow garbage) [CODE: wal lib.rs:402-424]. Consistent with the spirit.
7. Spec s14.6 mentions a transaction may carry participant records; code `EXTENSION` payload `u16 participant_id | bytes` [CODE: wal.rs:292-299]. Consistent.
8. ERRATA.md E-2 says tag `part-2-frozen-e2` "left to the owner" but the tag exists (git tag lists part-2-frozen-e1, part-2-frozen-e2) and PROGRESS.md lists it [CODE: git tag; docs/PROGRESS.md:13].
9. sever-py-p2 module doc says GIL release lets Python threads search while another writes (s12.5); the per-engine Mutex serialises all calls [CODE: sever-py-p2 lib.rs:6-7,108-124] - see 8.3.
10. sever-py-p2 maps only part of the s17 error list to named exceptions (no CommitmentMismatch, BadUserSignature, SeededNonceForbidden classes): Part 3 [CODE: lib.rs:80-95].
11. `sever-engine` `hooks.rs` contains `passage()` (spec s16.1 says passage read is under the `inspect` feature, DB-110, and "a read in the default build is deferred (G-46)"); in this Part 2 crate it is under `test-hooks`, not `inspect` [CODE: hooks.rs:107; engine Cargo features: only `test-hooks`] [DOC: spec s16.1 Inspection]. Relevant to the later frozen build; not a Part 2 issue.
12. CLAUDE.md s6.1 table says Part 2 covers spec "s12, s14 (not s14.5, s14.7), s15, s16.1, s17" - code honours: no bucket block (s14.5) or KEYS (s14.7) in Part 2 [CODE: GROUP_CREATE bucket_block empty, wal.rs:217-226 doc].

## 13. Glossary (one line each)
- WAL: write-ahead log; append-only record of committed changes (after-images), replayed after a crash.
- wal_seq: position number of each WAL record; unrelated to database_lsn.
- txn_id: id of one transaction (BEGIN..COMMIT).
- COMMIT point: the instant the WAL COMMIT record is durable (fsynced); before it nothing counts, after it everything does.
- After-image: the new value of a thing (slot, header, locator entry) logged by a change record; replay just applies it.
- Torn write / torn tail: a write only partly on disk; a partial last WAL record is discarded.
- fsync / fsync_dir: force file data / directory entries to stable storage; failed fsync is never retried.
- CRC-32C: 4-byte checksum (Castagnoli) closing every on-disk record.
- Magic number: 8 ASCII bytes at the start of every file identifying its type.
- sealer_id: u16 marker of how bytes are protected: 0 plaintext (Parts 2-3), 1 AES-256-GCM-SIV (Part 4).
- Storage checkpoint: full image of the database written atomically; lets old WAL segments be deleted.
- MANIFEST: tiny file naming the current checkpoint and first WAL position needed; installed by atomic rename.
- Segment: one WAL (or store) file, up to 64 MiB.
- Append store: append-only keyed record file (EP-8); here the passage store `payloads/`.
- VFS: virtual file system trait; `PosixVfs` real, `SimVfs` simulated with crashes.
- CrashPolicy: what unsynced data survives a simulated crash (DropAll/KeepAll/Random).
- EP-5..EP-9: extension points: VFS, Sealer, TxnParticipant, AppendStore, Clock.
- Participant: pluggable transaction member (Part 3 log, Part 4 key rotation); none in Part 2.
- Phase A / phase C: participant actions before / after the commit point.
- PreTxn: a separate transaction a participant asks to commit first (E-2).
- DbImage: the stored form of the whole database in memory; changed only by applying records.
- Invariant check: INV-4/6/7/8 etc. checked for every collection at every startup; failure refuses to start.
- Poison: test failure policy that makes the engine refuse all later calls instead of aborting.
- Oracle (crash campaign): Python reference model producing the expected state digest after each op.
- State digest: SHA-256 over canonical group blobs, holding ids, N and k.
- Double crash: a crash during recovery itself.
- delete_user: delete a cohort of record ids in one atomic transaction.
- Scrambled ID: HMAC-based pseudonym of a record id (k_scramble) used below the API; never the raw id.
- k_scramble: 64-byte secret in SECRETS used to compute scrambled IDs.
- L-28: stated limit: three known defects of the frozen Part 2 builds.
