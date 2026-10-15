//! `sever_db_p2_native`: PyO3 bindings of Part 2's engine (spec §16.2 without commitments; Build
//! §5.5). The SDK (`python/sever_db_p2`) wraps this module; nothing here is used directly.
//!
//! Every §17 error becomes a Python exception of the same name, subclass of `SeverError`, whose
//! message is the engine's fixed text (no record ID, vector value or key, §17). The GIL is released
//! for every engine call, so Python threads can search while another thread writes (§12.5).

// pyo3's macros expand to code that clippy's restriction lints flag; the crate's own code follows
// the workspace rules.
#![allow(clippy::useless_conversion)]

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Mutex;

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use sever_engine::{CollectionOptions, DeleteOutcome, InsertRequest};
use sever_p2::{OpenOptions, Opened, cid_hex, open, parse_cid};
use sever_types::{CollectionId, Error};

create_exception!(
    sever_db_p2_native,
    SeverError,
    PyException,
    "Every SEVER-DB error (§17)."
);
create_exception!(
    sever_db_p2_native,
    WrongDimension,
    SeverError,
    "§4.1 step 0."
);
create_exception!(sever_db_p2_native, NonFinite, SeverError, "§4.1 step 1.");
create_exception!(
    sever_db_p2_native,
    NotNormalised,
    SeverError,
    "§4.1 step 3."
);
create_exception!(
    sever_db_p2_native,
    InvalidRecordId,
    SeverError,
    "§3.2 rules 1–2."
);
create_exception!(
    sever_db_p2_native,
    DuplicateRecord,
    SeverError,
    "§3.2 rule 3; args[0] is same_commitment."
);
create_exception!(
    sever_db_p2_native,
    GroupCapacityExceeded,
    SeverError,
    "§5.6."
);
create_exception!(
    sever_db_p2_native,
    UnknownCollection,
    SeverError,
    "No such collection."
);
create_exception!(
    sever_db_p2_native,
    PlatformUnsafe,
    SeverError,
    "§12.8, §12.9."
);
create_exception!(
    sever_db_p2_native,
    IntegrityViolation,
    SeverError,
    "§21; the engine stops serving."
);
create_exception!(sever_db_p2_native, DurabilityFailure, SeverError, "§12.7.");

fn py_err(e: Error) -> PyErr {
    let msg = e.to_string();
    match e {
        Error::WrongDimension => WrongDimension::new_err(msg),
        Error::NonFinite => NonFinite::new_err(msg),
        Error::NotNormalised => NotNormalised::new_err(msg),
        Error::InvalidRecordId(_) => InvalidRecordId::new_err(msg),
        Error::DuplicateRecord { same_commitment } => DuplicateRecord::new_err((same_commitment,)),
        Error::GroupCapacityExceeded => GroupCapacityExceeded::new_err(msg),
        Error::UnknownCollection => UnknownCollection::new_err(msg),
        Error::PlatformUnsafe { .. } => PlatformUnsafe::new_err(msg),
        Error::IntegrityViolation { .. } => IntegrityViolation::new_err(msg),
        Error::DurabilityFailure => DurabilityFailure::new_err(msg),
        other => SeverError::new_err(other.to_string()),
    }
}

fn cid(s: &str) -> PyResult<CollectionId> {
    parse_cid(s).ok_or_else(|| UnknownCollection::new_err("unknown collection"))
}

/// An open database (`ENGINE.lock` held until `close`).
#[pyclass(name = "Engine", module = "sever_db_p2_native")]
struct PyEngine {
    inner: Mutex<Option<Opened>>,
}

impl PyEngine {
    fn with<T: Send>(
        &self,
        py: Python<'_>,
        f: impl FnOnce(&Opened) -> Result<T, Error> + Send,
    ) -> PyResult<T> {
        // Erratum E-1 (§12.5): the engine mutex is taken only after the GIL is released. Taking it
        // while holding the GIL deadlocks: a thread holding the mutex waits for the GIL to return
        // its result while the GIL holder waits for the mutex.
        let out = py.detach(|| {
            let guard = self.inner.lock().unwrap_or_else(|p| p.into_inner());
            guard.as_ref().map(f)
        });
        match out {
            Some(r) => r.map_err(py_err),
            None => Err(SeverError::new_err("the engine is closed")),
        }
    }
}

#[pymethods]
impl PyEngine {
    /// Opens (recovering, or creating) the database in `data_dir`, with `SECRETS` in `key_dir`.
    #[staticmethod]
    #[pyo3(signature = (data_dir, key_dir, allow_unsafe_fs = false))]
    fn open(
        py: Python<'_>,
        data_dir: PathBuf,
        key_dir: PathBuf,
        allow_unsafe_fs: bool,
    ) -> PyResult<Self> {
        let mut o = OpenOptions::new(data_dir, key_dir);
        o.allow_unsafe_fs = allow_unsafe_fs;
        let opened = py.detach(|| open(&o)).map_err(py_err)?;
        Ok(Self {
            inner: Mutex::new(Some(opened)),
        })
    }

    /// `create_collection` (§16.1); returns the collection ID as 32 hex characters.
    #[pyo3(signature = (artefact, spawn_target = 200, spawning_enabled = true, store_passages = true))]
    fn create_collection(
        &self,
        py: Python<'_>,
        artefact: PathBuf,
        spawn_target: usize,
        spawning_enabled: bool,
        store_passages: bool,
    ) -> PyResult<String> {
        let bytes = std::fs::read(&artefact)
            .map_err(|_| IntegrityViolation::new_err("§6.3 artefact unreadable"))?;
        self.with(py, move |o| {
            o.engine
                .create_collection(
                    &bytes,
                    CollectionOptions {
                        spawn_target,
                        spawning_enabled,
                        store_passages,
                    },
                )
                .map(|c| cid_hex(&c))
        })
    }

    /// `insert` (§16.1); returns the placement (`Frozen(...)`, `Spawned(...)` or `Holding`).
    #[pyo3(signature = (collection, record_id, vector, passage = None))]
    fn insert(
        &self,
        py: Python<'_>,
        collection: &str,
        record_id: String,
        vector: Vec<f32>,
        passage: Option<Vec<u8>>,
    ) -> PyResult<String> {
        let c = cid(collection)?;
        self.with(py, move |o| {
            o.engine
                .insert(
                    c,
                    InsertRequest {
                        record_id,
                        vector,
                        credential: (),
                        passage,
                    },
                )
                .map(|r| format!("{:?}", r.placement))
        })
    }

    /// `delete` (§16.1): `"deleted"` or `"absent"`.
    fn delete(&self, py: Python<'_>, collection: &str, record_id: String) -> PyResult<String> {
        let c = cid(collection)?;
        self.with(py, move |o| {
            o.engine.delete(c, &record_id).map(|out| outcome(&out))
        })
    }

    /// `delete_user` (§16.1): one transaction; one outcome per ID.
    fn delete_user(
        &self,
        py: Python<'_>,
        collection: &str,
        record_ids: Vec<String>,
    ) -> PyResult<Vec<String>> {
        let c = cid(collection)?;
        self.with(py, move |o| {
            let refs: Vec<&str> = record_ids.iter().map(String::as_str).collect();
            o.engine
                .delete_user(c, &refs)
                .map(|outs| outs.iter().map(outcome).collect())
        })
    }

    /// `search` (§16.1): `(record_id, score)` pairs, closest first.
    #[pyo3(signature = (collection, query, k = 10))]
    fn search(
        &self,
        py: Python<'_>,
        collection: &str,
        query: Vec<f32>,
        k: usize,
    ) -> PyResult<Vec<(String, f32)>> {
        let c = cid(collection)?;
        self.with(py, move |o| {
            o.engine
                .search(c, &query, k)
                .map(|hits| hits.into_iter().map(|h| (h.record_id, h.score)).collect())
        })
    }

    /// `stats` (§16.1).
    fn stats(&self, py: Python<'_>, collection: &str) -> PyResult<BTreeMap<String, u64>> {
        let c = cid(collection)?;
        self.with(py, move |o| {
            o.engine.stats(c).map(|s| {
                BTreeMap::from([
                    ("frozen".to_owned(), s.frozen),
                    ("spawned".to_owned(), s.spawned),
                    ("N".to_owned(), s.big_n),
                    ("k".to_owned(), s.k),
                    ("holding".to_owned(), s.holding),
                    ("checkpoint_id".to_owned(), s.checkpoint_id),
                ])
            })
        })
    }

    /// `(group ID, n)` of every frozen and spawned group, in creation order.
    fn group_sizes(&self, py: Python<'_>, collection: &str) -> PyResult<Vec<(String, u64)>> {
        let c = cid(collection)?;
        self.with(py, move |o| o.engine.stats(c).map(|s| s.group_sizes))
    }

    /// The collection IDs.
    fn collections(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        self.with(py, |o| {
            Ok(o.engine.collections().iter().map(cid_hex).collect())
        })
    }

    /// `drop_collection` (§16.1).
    fn drop_collection(&self, py: Python<'_>, collection: &str) -> PyResult<()> {
        let c = cid(collection)?;
        self.with(py, move |o| o.engine.drop_collection(c))
    }

    /// `storage_checkpoint_now` (§16.1).
    fn checkpoint(&self, py: Python<'_>) -> PyResult<()> {
        self.with(py, |o| o.engine.storage_checkpoint_now())
    }

    /// Clean shutdown (a storage checkpoint) and release of `ENGINE.lock`.
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        // Erratum E-1: the mutex is taken with the GIL released, as in `with`.
        py.detach(|| {
            let taken = self.inner.lock().unwrap_or_else(|p| p.into_inner()).take();
            taken.map_or(Ok(()), |o| o.engine.close())
        })
        .map_err(py_err)
    }
}

fn outcome(o: &DeleteOutcome) -> String {
    match o {
        DeleteOutcome::AlreadyAbsent => "absent".into(),
        DeleteOutcome::Deleted { .. } => "deleted".into(),
    }
}

/// The module.
#[pymodule]
fn sever_db_p2_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEngine>()?;
    let py = m.py();
    for (name, ty) in [
        ("SeverError", py.get_type::<SeverError>()),
        ("WrongDimension", py.get_type::<WrongDimension>()),
        ("NonFinite", py.get_type::<NonFinite>()),
        ("NotNormalised", py.get_type::<NotNormalised>()),
        ("InvalidRecordId", py.get_type::<InvalidRecordId>()),
        ("DuplicateRecord", py.get_type::<DuplicateRecord>()),
        (
            "GroupCapacityExceeded",
            py.get_type::<GroupCapacityExceeded>(),
        ),
        ("UnknownCollection", py.get_type::<UnknownCollection>()),
        ("PlatformUnsafe", py.get_type::<PlatformUnsafe>()),
        ("IntegrityViolation", py.get_type::<IntegrityViolation>()),
        ("DurabilityFailure", py.get_type::<DurabilityFailure>()),
    ] {
        m.add(name, ty)?;
    }
    Ok(())
}
