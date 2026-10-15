//! The engine (§16.1): collections, inserts, deletions, search, storage checkpoints.
//!
//! **Isolation (§12.5).** One writer at a time (the writer mutex, held for a whole mutation);
//! searches take a shared lock; applying a committed transaction to memory takes the exclusive
//! lock briefly. A reader therefore sees the state before a transaction or after it, never a mix,
//! and there are no retained snapshots.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, RwLock, RwLockReadGuard, RwLockWriteGuard};

use rand_core::{OsRng, RngCore};
use sever_appendstore::{AppendStore, FileStore, StoreConfig};
use sever_checkpoint as checkpoint;
use sever_format::image::CheckpointMeta;
use sever_format::{CollectionMeta, CoreRecord, DbImage, Layout, Secrets};
use sever_index::{
    ChangeSet, DeleteRequest, HmacSha512Scrambler, Index, IndexConfig, Outcome, Placement,
};
use sever_partition::PartitionArtefact;
use sever_txn::{
    Durable, Participants, Sealer, Step, StoredExtension, TxnDraft, TxnKind, changeset_records,
    collection_records, commit, layout_for,
};
use sever_types::{CollectionId, Error};
use sever_vfs::{OpenMode, Vfs, VfsError, durable, read_all};
use sever_wal::Wal;
use zeroize::Zeroizing;

use crate::config::{
    CollectionOptions, DeleteOutcome, EngineConfig, EngineStats, FailurePolicy, Hit, InsertReceipt,
    InsertRequest,
};
use crate::recovery;

/// The payload store directory.
pub const PAYLOAD_DIR: &str = "payloads";
/// The secrets file in the key directory (§14.1, DB-68).
pub const SECRETS: &str = "SECRETS";

pub(crate) type Ix<E> = Index<E, HmacSha512Scrambler>;

/// The state readers see: the storage image and one index per collection.
pub(crate) struct State<E: StoredExtension> {
    pub(crate) image: DbImage,
    pub(crate) live: BTreeMap<CollectionId, Ix<E>>,
}

/// The state only the writer touches.
pub(crate) struct Writer<E: StoredExtension> {
    pub(crate) wal: Wal,
    pub(crate) store: FileStore,
    pub(crate) participants: Participants<E>,
    pub(crate) store_key: u64,
    pub(crate) checkpoint_id: u64,
    #[cfg(feature = "test-hooks")]
    pub(crate) hook: Option<Box<dyn FnMut(Step) + Send>>,
}

/// The engine: `Engine<E, S>` with participants `P` given at open (Build §5.5: `Engine<E, S, P>`).
pub struct Engine<E: StoredExtension, S: Sealer> {
    pub(crate) vfs: Arc<dyn Vfs>,
    pub(crate) sealer: S,
    pub(crate) ext: E,
    pub(crate) cfg: EngineConfig,
    pub(crate) k_scramble: Zeroizing<[u8; 64]>,
    pub(crate) state: RwLock<State<E>>,
    pub(crate) writer: Mutex<Writer<E>>,
    pub(crate) poisoned: AtomicBool,
    /// WAL bytes since the last checkpoint and the checkpoint ID, for `stats` without the writer
    /// mutex (a reader must never wait for a writer's I/O).
    pub(crate) wal_bytes: AtomicU64,
    pub(crate) checkpoint_id: AtomicU64,
}

impl<E: StoredExtension, S: Sealer> core::fmt::Debug for Engine<E, S> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "Engine(poisoned: {})",
            self.poisoned.load(Ordering::SeqCst)
        )
    }
}

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

fn os_fill(buf: &mut [u8]) -> Result<(), Error> {
    OsRng
        .try_fill_bytes(buf)
        .map_err(|_| Error::PlatformUnsafe {
            check: "OS random source",
        })
}

pub(crate) fn store_cfg(cfg: &EngineConfig, sealer_id: u16) -> StoreConfig {
    StoreConfig {
        dir: PAYLOAD_DIR.into(),
        sealer_id,
        segment_bytes: cfg.store_segment_bytes,
    }
}

impl<E: StoredExtension, S: Sealer> Engine<E, S> {
    /// Opens the database in `vfs` (the data directory), with `SECRETS` in `keys` (the key
    /// directory), recovering it (§15.7); creates a new one if the data directory is empty.
    pub fn open(
        vfs: Arc<dyn Vfs>,
        keys: Arc<dyn Vfs>,
        sealer: S,
        ext: E,
        participants: Participants<E>,
        cfg: EngineConfig,
    ) -> Result<Self, Error> {
        let sid = sealer.sealer_id();
        let manifest = match checkpoint::read_manifest(vfs.as_ref(), sid)? {
            Some(m) => m,
            None => recovery::create(&vfs, keys.as_ref(), &cfg, sid)?,
        };
        recovery::open_existing(vfs, keys, sealer, ext, participants, cfg, manifest)
    }

    // --- helpers -------------------------------------------------------------------------------

    pub(crate) fn read(&self) -> RwLockReadGuard<'_, State<E>> {
        self.state.read().unwrap_or_else(|p| p.into_inner())
    }

    pub(crate) fn write(&self) -> RwLockWriteGuard<'_, State<E>> {
        self.state.write().unwrap_or_else(|p| p.into_inner())
    }

    fn writer(&self) -> Result<MutexGuard<'_, Writer<E>>, Error> {
        self.alive()?;
        let w = self.writer.lock().unwrap_or_else(|p| p.into_inner());
        self.alive()?;
        Ok(w)
    }

    fn alive(&self) -> Result<(), Error> {
        if self.poisoned.load(Ordering::SeqCst) {
            Err(Error::DurabilityFailure)
        } else {
            Ok(())
        }
    }

    /// §12.7: a durability failure aborts the process (or, in tests, poisons the engine).
    fn fail<T>(&self, r: Result<T, Error>) -> Result<T, Error> {
        if matches!(r, Err(Error::DurabilityFailure)) {
            match self.cfg.on_failure {
                FailurePolicy::Abort => std::process::abort(),
                FailurePolicy::Poison => self.poisoned.store(true, Ordering::SeqCst),
            }
        }
        r
    }

    pub(crate) fn layout(&self, d: usize) -> Layout {
        layout_for::<E>(d, &self.sealer)
    }

    fn new_index(&self, meta: &CollectionMeta, art: &PartitionArtefact) -> Result<Ix<E>, Error> {
        Index::new(
            art,
            IndexConfig {
                spawning_enabled: meta.spawning_enabled,
                spawn_target: meta.spawn_target as usize,
            },
            self.ext.clone(),
            HmacSha512Scrambler::new(&self.k_scramble),
            meta.cid,
        )
    }

    /// Runs one transaction through the protocol and installs it. `cs` is the index change (if
    /// any); `then` updates the live indexes under the same exclusive lock as the image.
    #[allow(clippy::too_many_arguments)] // one internal call shape for every transaction kind
    fn run(
        &self,
        w: &mut Writer<E>,
        kind: TxnKind,
        cid: CollectionId,
        layout: &Layout,
        cs: Option<&ChangeSet<E>>,
        records: Vec<CoreRecord>,
        then: impl FnOnce(&mut State<E>),
    ) -> Result<sever_txn::Acknowledged, Error> {
        // EP-7 pre-transactions (E-2; spec §15.3 step 3): after planning, so an absent record or a
        // failed integrity check touches nothing (steps 1–2); each is committed on its own, first.
        for p in w.participants.iter_mut() {
            if let Some(pre) = p.pre_transaction(kind, &cid)? {
                if let Err(e) = w.wal.commit(&pre.records) {
                    p.abort();
                    return Err(e);
                }
                p.after_commit()?;
            }
        }
        let draft = TxnDraft {
            kind,
            collection: cid,
            changeset: cs,
            records,
            participant_records: Vec::new(),
            outputs: Vec::new(),
        };
        let mut broken = false;
        let apply = |recs: &[CoreRecord]| {
            let mut st = self.write();
            for r in recs {
                // The records were built from this exact state; a failure is a bug, and the
                // engine stops serving rather than run on an image it cannot trust.
                if st.image.apply(r).is_err() {
                    broken = true;
                }
            }
            then(&mut st);
        };
        #[cfg(feature = "test-hooks")]
        let mut taken = w.hook.take();
        let mut hook = |_s: Step| {
            #[cfg(feature = "test-hooks")]
            if let Some(h) = taken.as_mut() {
                h(_s);
            }
        };
        let ack = commit(
            draft,
            layout,
            &mut w.participants,
            Durable {
                wal: &mut w.wal,
                store: &mut w.store,
            },
            apply,
            &mut hook,
        );
        #[cfg(feature = "test-hooks")]
        {
            w.hook = taken;
        }
        self.wal_bytes.store(w.wal.appended(), Ordering::SeqCst);
        if broken {
            self.poisoned.store(true, Ordering::SeqCst);
            return Err(Error::IntegrityViolation {
                invariant: "§12.3 after-image did not apply",
            });
        }
        let ack = ack?;
        self.maybe_checkpoint(w)?;
        Ok(ack)
    }

    fn maybe_checkpoint(&self, w: &mut Writer<E>) -> Result<(), Error> {
        if w.wal.appended() >= self.cfg.checkpoint_every_wal_bytes {
            self.checkpoint_locked(w)?;
        }
        Ok(())
    }

    /// §15.6: a storage checkpoint, with the writer mutex held.
    fn checkpoint_locked(&self, w: &mut Writer<E>) -> Result<(), Error> {
        let meta = CheckpointMeta {
            checkpoint_id: w.checkpoint_id + 1,
            next_wal_seq: w.wal.next_wal_seq(),
            next_txn_id: w.wal.next_txn_id(),
            config_hash: self.cfg.config_hash,
        };
        {
            let st = self.read();
            let layout_of = |m: &CollectionMeta| self.layout(usize::from(m.d));
            checkpoint::write(
                self.vfs.as_ref(),
                self.sealer.sealer_id(),
                &st.image,
                &meta,
                &layout_of,
            )?;
        }
        w.checkpoint_id = meta.checkpoint_id;
        checkpoint::remove_others(self.vfs.as_ref(), meta.checkpoint_id)?;
        w.wal.remove_covered(meta.next_wal_seq)?;
        w.wal.reset_appended();
        self.wal_bytes.store(0, Ordering::SeqCst);
        self.checkpoint_id
            .store(meta.checkpoint_id, Ordering::SeqCst);
        Ok(())
    }

    // --- API (§16.1) ---------------------------------------------------------------------------

    /// `create_collection`: verifies the artefact (§6.3), draws a `collection_id` from the OS
    /// (§3.1), and commits the collection with its frozen groups and holding area.
    pub fn create_collection(
        &self,
        artefact: &[u8],
        opts: CollectionOptions,
    ) -> Result<CollectionId, Error> {
        let art = PartitionArtefact::parse(artefact)?;
        let mut cid = [0u8; 16];
        os_fill(&mut cid)?;
        let cid = CollectionId::from_bytes(cid);
        let meta = CollectionMeta {
            cid,
            d: u16::try_from(art.d).map_err(|_| Error::IntegrityViolation {
                invariant: "§6.3 artefact d",
            })?,
            spawn_target: u32::try_from(opts.spawn_target).unwrap_or(u32::MAX),
            spawning_enabled: opts.spawning_enabled,
            store_passages: opts.store_passages,
            artefact_sha256: art.sha256_artefact,
        };
        let index = self.new_index(&meta, &art)?;
        let layout = self.layout(art.d);
        let records =
            collection_records::<E>(meta, artefact.to_vec(), &art.centroids, &self.sealer)?;
        let mut w = self.writer()?;
        let r = self.run(
            &mut w,
            TxnKind::CreateCollection,
            cid,
            &layout,
            None,
            records,
            |st| {
                st.live.insert(cid, index);
            },
        );
        self.fail(r).map(|_| cid)
    }

    /// `drop_collection` (§15.9 without the cryptographic erase, which is Part 4's): commits a
    /// WAL record removing the collection. Its bytes leave the disk with the next storage
    /// checkpoint.
    pub fn drop_collection(&self, cid: CollectionId) -> Result<(), Error> {
        let mut w = self.writer()?;
        let layout = {
            let st = self.read();
            let c = st.image.collection(&cid).ok_or(Error::UnknownCollection)?;
            self.layout(usize::from(c.meta.d))
        };
        for p in w.participants.iter_mut() {
            let r = p.on_drop_collection(&cid);
            self.fail(r)?;
        }
        let r = self.run(
            &mut w,
            TxnKind::DropCollection,
            cid,
            &layout,
            None,
            vec![CoreRecord::CollectionDrop { cid }],
            |st| {
                st.live.remove(&cid);
            },
        );
        self.fail(r).map(|_| ())
    }

    /// `insert` (§15.1). A retry of an insert that committed fails with `DuplicateRecord {
    /// same_commitment: true }`, which the SDK treats as success.
    pub fn insert(
        &self,
        cid: CollectionId,
        req: InsertRequest<E::Credential>,
    ) -> Result<InsertReceipt, Error> {
        let mut w = self.writer()?;
        let (cs, records, layout) = {
            let st = self.read();
            let ix = st.live.get(&cid).ok_or(Error::UnknownCollection)?;
            let coll = st.image.collection(&cid).ok_or(Error::UnknownCollection)?;
            let cs = ix.plan_insert(sever_index::InsertRequest {
                record_id: req.record_id,
                vector: req.vector,
                credential: req.credential,
            })?;
            let layout = self.layout(ix.d());
            let passage = req.passage.as_deref().filter(|_| coll.meta.store_passages);
            let Writer {
                store, store_key, ..
            } = &mut *w;
            let records =
                changeset_records(coll, &layout, &cs, &self.sealer, passage, &mut |bytes| {
                    *store_key += 1;
                    store.append(*store_key, bytes)
                });
            let records = self.fail(records)?;
            (cs, records, layout)
        };
        let placement = match cs.outcomes.first() {
            Some(Outcome::Placed(p)) => *p,
            _ => Placement::Holding,
        };
        let installed = cs.clone();
        let r = self.run(
            &mut w,
            TxnKind::Insert,
            cid,
            &layout,
            Some(&cs),
            records,
            |st| {
                if let Some(ix) = st.live.get_mut(&cid) {
                    ix.apply(installed);
                }
            },
        );
        let ack = self.fail(r)?;
        Ok(InsertReceipt {
            placement,
            outputs: ack.outputs.into_iter().map(|(p, _, b)| (p, b)).collect(),
        })
    }

    /// `delete` (§15.3).
    pub fn delete(&self, cid: CollectionId, record_id: &str) -> Result<DeleteOutcome, Error> {
        let mut out = self.delete_user(cid, &[record_id])?;
        out.pop().ok_or(Error::IntegrityViolation {
            invariant: "§15.3 outcome",
        })
    }

    /// `delete_user` (§15.3, §12.5): every record in list order, in **one** transaction.
    pub fn delete_user(
        &self,
        cid: CollectionId,
        record_ids: &[&str],
    ) -> Result<Vec<DeleteOutcome>, Error> {
        let mut w = self.writer()?;
        let (cs, records, layout) = {
            let st = self.read();
            let ix = st.live.get(&cid).ok_or(Error::UnknownCollection)?;
            let coll = st.image.collection(&cid).ok_or(Error::UnknownCollection)?;
            let cs = ix.plan_delete_many(
                record_ids
                    .iter()
                    .map(|id| DeleteRequest {
                        record_id: (*id).to_owned(),
                    })
                    .collect(),
            )?;
            if cs.is_noop() {
                // §15.3 step 1: nothing is live; touch nothing.
                return Ok(vec![DeleteOutcome::AlreadyAbsent; cs.outcomes.len()]);
            }
            let layout = self.layout(ix.d());
            let records = changeset_records(coll, &layout, &cs, &self.sealer, None, &mut |_| {
                Err(Error::IntegrityViolation {
                    invariant: "§15.3 a deletion stores nothing",
                })
            })?;
            (cs, records, layout)
        };
        let installed = cs.clone();
        let r = self.run(
            &mut w,
            TxnKind::Delete,
            cid,
            &layout,
            Some(&cs),
            records,
            |st| {
                if let Some(ix) = st.live.get_mut(&cid) {
                    ix.apply(installed);
                }
            },
        );
        let ack = self.fail(r)?;
        Ok(cs
            .outcomes
            .iter()
            .enumerate()
            .map(|(i, o)| match o {
                Outcome::Deleted { .. } => DeleteOutcome::Deleted {
                    outputs: ack
                        .outputs
                        .iter()
                        .filter(|(_, req, _)| *req == i)
                        .map(|(p, _, b)| (*p, b.clone()))
                        .collect(),
                },
                _ => DeleteOutcome::AlreadyAbsent,
            })
            .collect())
    }

    /// `search` (§15.5, §8.1): shared lock only; never writes.
    pub fn search(&self, cid: CollectionId, query: &[f32], k: usize) -> Result<Vec<Hit>, Error> {
        self.alive()?;
        let st = self.read();
        let ix = st.live.get(&cid).ok_or(Error::UnknownCollection)?;
        Ok(sever_search::search(ix, query, k)?
            .into_iter()
            .map(|h| Hit {
                record_id: h.record_id.as_str().to_owned(),
                score: h.score,
            })
            .collect())
    }

    /// `storage_checkpoint_now` (§15.6).
    pub fn storage_checkpoint_now(&self) -> Result<(), Error> {
        let mut w = self.writer()?;
        let r = self.checkpoint_locked(&mut w);
        self.fail(r)
    }

    /// `stats` (§16.1).
    pub fn stats(&self, cid: CollectionId) -> Result<EngineStats, Error> {
        self.alive()?;
        let wal_bytes = self.wal_bytes.load(Ordering::SeqCst);
        let checkpoint_id = self.checkpoint_id.load(Ordering::SeqCst);
        let st = self.read();
        let ix = st.live.get(&cid).ok_or(Error::UnknownCollection)?;
        let coll = st.image.collection(&cid).ok_or(Error::UnknownCollection)?;
        let s = ix.stats();
        Ok(EngineStats {
            frozen: s.frozen,
            spawned: s.spawned,
            big_n: s.big_n,
            k: s.k,
            holding: s.holding,
            group_sizes: coll
                .groups
                .iter()
                .filter(|g| g.header.group_id != sever_types::GroupId::Holding)
                .map(|g| (g.header.group_id.as_text(), g.header.n))
                .collect(),
            wal_bytes_since_checkpoint: wal_bytes,
            checkpoint_id,
        })
    }

    /// The collections, ascending by ID.
    pub fn collections(&self) -> Vec<CollectionId> {
        self.read().live.keys().copied().collect()
    }

    /// A clean shutdown: a storage checkpoint (§12.4), then the engine is gone.
    pub fn close(self) -> Result<(), Error> {
        self.storage_checkpoint_now()
    }

    /// True after a durability failure under [`FailurePolicy::Poison`].
    pub fn is_poisoned(&self) -> bool {
        self.poisoned.load(Ordering::SeqCst)
    }
}

/// Reads `SECRETS` from the key directory.
pub(crate) fn read_secrets(keys: &dyn Vfs, sealer_id: u16) -> Result<Zeroizing<[u8; 64]>, Error> {
    let f = keys
        .open(SECRETS, OpenMode::Existing)
        .map_err(|_| Error::IntegrityViolation {
            invariant: "§14.1 SECRETS missing",
        })?;
    let bytes = Zeroizing::new(read_all(f.as_ref()).map_err(|_| Error::IntegrityViolation {
        invariant: "§14.1 SECRETS",
    })?);
    Ok(Zeroizing::new(
        Secrets::parse(&bytes, sealer_id)?.k_scramble()?,
    ))
}

/// Writes a new `SECRETS` with a fresh `k_scramble` from the OS (§9.7).
pub(crate) fn write_secrets(keys: &dyn Vfs, sealer_id: u16) -> Result<(), Error> {
    let mut k = Zeroizing::new([0u8; 64]);
    os_fill(k.as_mut())?;
    let s = Secrets {
        sealer_id,
        entries: vec![(Secrets::K_SCRAMBLE, k.to_vec())],
    };
    let bytes = Zeroizing::new(s.encode());
    durable::replace_file(keys, SECRETS, &bytes).map_err(io)
}
