//! Engine settings and the API's request and result types (spec §16.1, §18.1).

use sever_index::Placement;

/// What happens when a write or an `fsync` fails (§12.7).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailurePolicy {
    /// Abort the process (§12.7); recovery runs at the restart. The composition root uses this.
    Abort,
    /// Refuse every later call with `DurabilityFailure`, as if the process had died; tests then
    /// "restart" by opening the database again. Used only in tests and the crash kit.
    Poison,
}

/// Engine settings (§18.1 `durability`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EngineConfig {
    /// WAL segment size (§18.1 `wal_segment_bytes`, 64 MiB).
    pub wal_segment_bytes: u64,
    /// Payload store segment size.
    pub store_segment_bytes: u64,
    /// A storage checkpoint runs after this many WAL bytes (§12.4, 1 GiB).
    pub checkpoint_every_wal_bytes: u64,
    /// See [`FailurePolicy`].
    pub on_failure: FailurePolicy,
    /// SHA-256 of the configuration file, recorded in every storage checkpoint (§18).
    pub config_hash: [u8; 32],
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            wal_segment_bytes: 64 * 1024 * 1024,
            store_segment_bytes: 64 * 1024 * 1024,
            checkpoint_every_wal_bytes: 1 << 30,
            on_failure: FailurePolicy::Abort,
            config_hash: [0; 32],
        }
    }
}

/// `create_collection` options (§16.1).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CollectionOptions {
    /// §7.4: the holding area flushes at this many records (200 in v1; DB-62).
    pub spawn_target: usize,
    /// `false` only for the frozen-only control arm (overview §10.7).
    pub spawning_enabled: bool,
    /// §18.1 `store_passage_text`.
    pub store_passages: bool,
}

impl Default for CollectionOptions {
    fn default() -> Self {
        Self {
            spawn_target: sever_types::constants::SPAWN_TARGET_SIZE,
            spawning_enabled: true,
            store_passages: true,
        }
    }
}

/// An insert (§16.1). Part 2's credential is `()`; Part 3's carries `r_t`, `C_t`, the user key
/// and signature.
#[derive(Clone, Debug)]
pub struct InsertRequest<C> {
    /// §3.2.
    pub record_id: String,
    /// `d` normalised float32 values.
    pub vector: Vec<f32>,
    /// What the group extension needs to admit the insert (EP-1).
    pub credential: C,
    /// The passage text, stored if the collection stores passages.
    pub passage: Option<Vec<u8>>,
}

/// A successful insert.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InsertReceipt {
    /// Where the record landed after the whole transaction (§16.1).
    pub placement: Placement,
    /// Participant outputs `(participant ID, bytes)` (Part 3: `database_lsn`).
    pub outputs: Vec<(u16, Vec<u8>)>,
}

/// The outcome of one deletion request (§16.1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DeleteOutcome {
    /// §5.4: the record was not live; nothing changed. A retried deletion lands here.
    AlreadyAbsent,
    /// The record was removed.
    Deleted {
        /// Participant outputs for this request (Part 3: the certificate).
        outputs: Vec<(u16, Vec<u8>)>,
    },
}

/// One search result (§16.1).
#[derive(Clone, Debug, PartialEq)]
pub struct Hit {
    /// The record ID.
    pub record_id: String,
    /// The §8.2 score.
    pub score: f32,
}

/// `stats` (§16.1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EngineStats {
    /// Frozen groups.
    pub frozen: u64,
    /// Spawned groups.
    pub spawned: u64,
    /// `N`.
    pub big_n: u64,
    /// `k`.
    pub k: u64,
    /// Records in the holding area.
    pub holding: u64,
    /// `(group ID, n)` of every frozen and spawned group, in creation order.
    pub group_sizes: Vec<(String, u64)>,
    /// Bytes appended to the WAL since the last storage checkpoint.
    pub wal_bytes_since_checkpoint: u64,
    /// The current storage checkpoint.
    pub checkpoint_id: u64,
}
