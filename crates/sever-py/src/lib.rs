//! `sever_db_native`: PyO3 bindings of the final engine (Part 4) and of the application-backend helpers
//! (spec §16.2; Build 3-4 §1.4). The SDK (`python/sever_db_p3`) wraps this module; nothing here is
//! used directly.
//!
//! Every §17 error becomes a Python exception of the same name, subclass of `SeverError`, whose
//! message is the engine's fixed text (no record ID, vector value, key or `r_t`, §17). The engine
//! mutex is taken only with the GIL released (erratum E-1), so Python threads can search while
//! another thread writes (§12.5).
//!
//! Randomness (§9.4, §9.6, §9.8): `r_t` and account keys come from the OS here, and the deletion
//! proof's nonces from `StrictProofRng` inside the engine. No function takes a generator, seed or
//! nonce; `r_t` never crosses into Python (DB-84).

// pyo3's macros expand to code that clippy's restriction lints flag; the crate's own code follows
// the workspace rules.
#![allow(clippy::useless_conversion)]

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
#[cfg(feature = "inspect")]
use pyo3::types::PyDict;
use rand_core::{OsRng, RngCore};
use sever_commit::InsertCredential;
use sever_crypto::{
    Generators, KeyPair, Scalar, commit_record, encode_point, insert_message, self_check,
};
use sever_db::{Deleted, OpenOptions, Opened, cid_hex, open, parse_cid};
use sever_engine::{CollectionOptions, InsertRequest};
use sever_types::{CollectionId, Error};
use zeroize::Zeroizing;

create_exception!(
    sever_db_native,
    SeverError,
    PyException,
    "Every SEVER-DB error (§17)."
);
create_exception!(sever_db_native, WrongDimension, SeverError, "§4.1 step 0.");
create_exception!(sever_db_native, NonFinite, SeverError, "§4.1 step 1.");
create_exception!(sever_db_native, NotNormalised, SeverError, "§4.1 step 3.");
create_exception!(
    sever_db_native,
    InvalidRecordId,
    SeverError,
    "§3.2 rules 1–2."
);
create_exception!(
    sever_db_native,
    DuplicateRecord,
    SeverError,
    "§3.2 rule 3; args[0] is same_commitment."
);
create_exception!(
    sever_db_native,
    CommitmentMismatch,
    SeverError,
    "§15.1 step 2: the supplied C_t is not the recomputed one."
);
create_exception!(
    sever_db_native,
    BadUserSignature,
    SeverError,
    "§15.1 step 2: the insert signature fails."
);
create_exception!(sever_db_native, GroupCapacityExceeded, SeverError, "§5.6.");
create_exception!(
    sever_db_native,
    UnknownCollection,
    SeverError,
    "No such collection."
);
create_exception!(
    sever_db_native,
    SeededNonceForbidden,
    SeverError,
    "§9.6, §16.2: randomness cannot be supplied."
);
create_exception!(sever_db_native, PlatformUnsafe, SeverError, "§12.8, §12.9.");
create_exception!(
    sever_db_native,
    IntegrityViolation,
    SeverError,
    "§21; the engine stops serving."
);
create_exception!(sever_db_native, DurabilityFailure, SeverError, "§12.7.");

fn py_err(e: Error) -> PyErr {
    let msg = e.to_string();
    match e {
        Error::WrongDimension => WrongDimension::new_err(msg),
        Error::NonFinite => NonFinite::new_err(msg),
        Error::NotNormalised => NotNormalised::new_err(msg),
        Error::InvalidRecordId(_) => InvalidRecordId::new_err(msg),
        Error::DuplicateRecord { same_commitment } => DuplicateRecord::new_err((same_commitment,)),
        Error::CommitmentMismatch => CommitmentMismatch::new_err(msg),
        Error::BadUserSignature => BadUserSignature::new_err(msg),
        Error::GroupCapacityExceeded => GroupCapacityExceeded::new_err(msg),
        Error::UnknownCollection => UnknownCollection::new_err(msg),
        Error::SeededNonceForbidden => SeededNonceForbidden::new_err(msg),
        Error::PlatformUnsafe { .. } => PlatformUnsafe::new_err(msg),
        Error::IntegrityViolation { .. } => IntegrityViolation::new_err(msg),
        Error::DurabilityFailure => DurabilityFailure::new_err(msg),
    }
}

fn cid(s: &str) -> PyResult<CollectionId> {
    parse_cid(s).ok_or_else(|| UnknownCollection::new_err("unknown collection"))
}

fn bytes<'py>(py: Python<'py>, b: &[u8]) -> Bound<'py, PyBytes> {
    PyBytes::new(py, b)
}

/// 32 bytes from the OS (§9.4, §9.8: never from a seed).
fn os_secret() -> Zeroizing<[u8; 32]> {
    let mut s = Zeroizing::new([0u8; 32]);
    OsRng.fill_bytes(s.as_mut());
    s
}

/// The generators of dimension `d`, derived once and checked against the golden values (§9.2).
fn generators(d: usize) -> Result<Arc<Generators>, Error> {
    static CACHE: OnceLock<Mutex<BTreeMap<usize, Arc<Generators>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(BTreeMap::new()));
    let mut c = cache.lock().unwrap_or_else(|p| p.into_inner());
    if let Some(g) = c.get(&d) {
        return Ok(Arc::clone(g));
    }
    let g = Arc::new(Generators::derive(d).map_err(|_| Error::WrongDimension)?);
    self_check(&g).map_err(|_| Error::IntegrityViolation {
        invariant: "§9.2 generator self-check",
    })?;
    c.insert(d, Arc::clone(&g));
    Ok(g)
}

/// An account's Ed25519 key (§9.8; never rotates). The backend keeps it in its own key store.
#[pyclass(name = "UserKey", module = "sever_db_native", frozen)]
struct PyUserKey {
    secret: Zeroizing<[u8; 32]>,
    public: [u8; 32],
}

impl PyUserKey {
    fn from(secret: Zeroizing<[u8; 32]>) -> Self {
        let public = KeyPair::from_secret(&secret).public();
        Self { secret, public }
    }
}

#[pymethods]
impl PyUserKey {
    /// A new account key from the OS random source (§16.2 `UserKey.generate()`).
    #[staticmethod]
    fn generate() -> Self {
        Self::from(os_secret())
    }

    /// A stored key, from the 32-byte secret that `secret_bytes` returned.
    #[staticmethod]
    fn from_secret_bytes(secret: &[u8]) -> PyResult<Self> {
        let s: [u8; 32] = secret
            .try_into()
            .map_err(|_| SeverError::new_err("a user key secret is 32 bytes"))?;
        Ok(Self::from(Zeroizing::new(s)))
    }

    /// The 32-byte secret, for the backend's key store.
    fn secret_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        bytes(py, self.secret.as_ref())
    }

    /// The 32-byte public key (published in every insert leaf, §10.2).
    #[getter]
    fn public_key<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        bytes(py, &self.public)
    }

    fn __repr__(&self) -> String {
        "UserKey(<secret>)".into() // §17: never print a key
    }
}

/// A prepared insert (§16.2): the record, `C_t`, `r_t` and the user signature. `r_t` is not
/// readable from Python; the engine stores it (§9.4). Reusable for a retry (§15.1).
#[pyclass(name = "InsertRequest", module = "sever_db_native", frozen)]
struct PyInsertRequest {
    collection_id: [u8; 16],
    record_id: String,
    vector: Vec<f32>,
    c_t: [u8; 32],
    r_t: Zeroizing<[u8; 32]>,
    user_public_key: [u8; 32],
    signature: [u8; 64],
}

impl PyInsertRequest {
    fn request(&self, passage: Option<Vec<u8>>) -> InsertRequest<InsertCredential> {
        InsertRequest {
            record_id: self.record_id.clone(),
            vector: self.vector.clone(),
            credential: InsertCredential {
                collection_id: self.collection_id,
                c_t: self.c_t,
                r_t: *self.r_t,
                user_public_key: self.user_public_key,
                signature: self.signature,
            },
            passage,
        }
    }
}

#[pymethods]
impl PyInsertRequest {
    /// The collection the signature binds (32 hex characters).
    #[getter]
    fn collection_id(&self) -> String {
        self.collection_id
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect()
    }

    #[getter]
    fn record_id(&self) -> String {
        self.record_id.clone()
    }

    /// `C_t` (32 bytes, §9.3).
    #[getter]
    fn c_t<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        bytes(py, &self.c_t)
    }

    #[getter]
    fn user_public_key<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        bytes(py, &self.user_public_key)
    }

    /// The user signature over `DST_INSERT ‖ collection_id ‖ C_t` (§9.8).
    #[getter]
    fn signature<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        bytes(py, &self.signature)
    }

    fn __repr__(&self) -> String {
        "InsertRequest(<record>)".into() // §17: no record ID, vector or r_t
    }
}

/// `prepare_insert` (§16.2): quantise (§4.2, the engine's quantiser), draw `r_t` from the OS
/// (§9.4), compute `C_t` (§9.3), sign (§9.8). The dimension is the vector's length (DB-84); the
/// engine refuses another one (§4.1 step 0).
#[pyfunction]
fn prepare_insert(
    py: Python<'_>,
    collection_id: &str,
    record_id: String,
    vector: Vec<f32>,
    user: &Bound<'_, PyUserKey>,
) -> PyResult<PyInsertRequest> {
    let c = cid(collection_id)?;
    let user = user.get();
    let secret = Zeroizing::new(*user.secret);
    let public = user.public;
    py.detach(move || {
        let d = vector.len();
        let x = sever_quant::quantise(&vector, d)?;
        let mut wide = Zeroizing::new([0u8; 64]);
        OsRng.fill_bytes(wide.as_mut());
        let r_t = Scalar::from_bytes_mod_order_wide(&wide);
        let c_t = encode_point(
            &commit_record(generators(d)?.as_ref(), x.as_slice(), &r_t)
                .map_err(|_| Error::WrongDimension)?,
        );
        let signature = KeyPair::from_secret(&secret).sign(&insert_message(c.as_bytes(), &c_t));
        Ok(PyInsertRequest {
            collection_id: *c.as_bytes(),
            record_id,
            vector,
            c_t,
            r_t: Zeroizing::new(r_t.to_bytes()),
            user_public_key: public,
            signature,
        })
    })
    .map_err(py_err)
}

/// One deletion's result: `("deleted", database_lsn, certificate)` or `("absent", None, None)`.
type Outcome = (String, Option<u64>, Option<Vec<u8>>);

fn outcome(d: Deleted) -> Outcome {
    match d {
        Deleted::AlreadyAbsent => ("absent".into(), None, None),
        Deleted::Deleted {
            database_lsn,
            certificate,
        } => ("deleted".into(), Some(database_lsn), Some(certificate)),
    }
}

/// [`Outcome`] with the certificate as Python bytes.
type PyOutcome<'py> = (String, Option<u64>, Option<Bound<'py, PyBytes>>);

fn outcome_py<'py>(py: Python<'py>, (o, lsn, cert): Outcome) -> PyOutcome<'py> {
    (o, lsn, cert.map(|c| bytes(py, &c)))
}

/// `(tree_size, root, timestamp_ms, epoch, operator_signature, [(witness, epoch, signature)])`.
type CheckpointTuple<'py> = (
    u64,
    Bound<'py, PyBytes>,
    u64,
    u32,
    Bound<'py, PyBytes>,
    Vec<(u8, u32, Bound<'py, PyBytes>)>,
);

/// An open database (`ENGINE.lock` held until `close`).
#[pyclass(name = "Engine", module = "sever_db_native")]
struct PyEngine {
    inner: Mutex<Option<Opened>>,
}

impl PyEngine {
    fn with<T: Send>(
        &self,
        py: Python<'_>,
        f: impl FnOnce(&Opened) -> Result<T, Error> + Send,
    ) -> PyResult<T> {
        // Erratum E-1 (§12.5): the engine mutex is taken only after the GIL is released.
        let out = py.detach(|| {
            let guard = self.inner.lock().unwrap_or_else(|p| p.into_inner());
            // §17, §12.9 (G-42): every call goes through `Opened::serve`.
            guard.as_ref().map(|o| o.serve(|_| f(o)))
        });
        match out {
            Some(r) => r.map_err(py_err),
            None => Err(SeverError::new_err("the engine is closed")),
        }
    }
}

#[pymethods]
impl PyEngine {
    /// Opens (recovering, or creating) the database in `data_dir`, with `SECRETS` and
    /// `WITNESSES` in `key_dir`. One dimension per database (DB-83).
    #[staticmethod]
    #[pyo3(signature = (data_dir, key_dir, d = 384, allow_unsafe_fs = false, allow_unsafe_memory = false))]
    fn open(
        py: Python<'_>,
        data_dir: PathBuf,
        key_dir: PathBuf,
        d: usize,
        allow_unsafe_fs: bool,
        allow_unsafe_memory: bool,
    ) -> PyResult<Self> {
        let mut o = OpenOptions::new(data_dir, key_dir);
        o.d = d;
        o.overrides.allow_unsafe_fs = allow_unsafe_fs;
        o.overrides.allow_unsafe_memory = allow_unsafe_memory;
        let opened = py.detach(|| open(&o)).map_err(py_err)?;
        Ok(Self {
            inner: Mutex::new(Some(opened)),
        })
    }

    /// The startup checks that failed and were overridden (§12.8–12.9), and whether the process's
    /// memory is locked (DB-93).
    fn startup(&self, py: Python<'_>) -> PyResult<(Vec<String>, bool)> {
        self.with(py, |o| {
            Ok((
                o.overridden.iter().map(|c| (*c).to_owned()).collect(),
                o.memory_locked,
            ))
        })
    }

    /// The database's dimension.
    fn d(&self, py: Python<'_>) -> PyResult<usize> {
        self.with(py, |o| Ok(o.db.d()))
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
            o.db.create_collection(
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

    /// `insert(collection_id, req)` (§16.2): `(database_lsn, placement)`.
    #[pyo3(signature = (collection, request, passage = None))]
    fn insert(
        &self,
        py: Python<'_>,
        collection: &str,
        request: &Bound<'_, PyInsertRequest>,
        passage: Option<Vec<u8>>,
    ) -> PyResult<(u64, String)> {
        let c = cid(collection)?;
        let req = request.get().request(passage);
        self.with(py, move |o| {
            o.db.insert(c, req)
                .map(|(lsn, p)| (lsn, sever_db::placement_text(&p)))
        })
    }

    /// `delete` (§16.2, no `r_t` argument): `(outcome, database_lsn, certificate)`.
    fn delete<'py>(
        &self,
        py: Python<'py>,
        collection: &str,
        record_id: String,
    ) -> PyResult<PyOutcome<'py>> {
        let c = cid(collection)?;
        let out = self.with(py, move |o| o.db.delete(c, &record_id).map(outcome))?;
        Ok(outcome_py(py, out))
    }

    /// `delete_user` (§15.3): one transaction; one outcome per ID; the certificates chain.
    fn delete_user<'py>(
        &self,
        py: Python<'py>,
        collection: &str,
        record_ids: Vec<String>,
    ) -> PyResult<Vec<PyOutcome<'py>>> {
        let c = cid(collection)?;
        let outs = self.with(py, move |o| {
            let refs: Vec<&str> = record_ids.iter().map(String::as_str).collect();
            o.db.delete_user(c, &refs)
                .map(|v| v.into_iter().map(outcome).collect::<Vec<_>>())
        })?;
        Ok(outs.into_iter().map(|x| outcome_py(py, x)).collect())
    }

    /// `certificate(database_lsn)` (§16.1), or `None`.
    fn certificate<'py>(
        &self,
        py: Python<'py>,
        database_lsn: u64,
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        let c = self.with(py, move |o| o.db.certificate(database_lsn))?;
        Ok(c.map(|c| bytes(py, &c)))
    }

    /// `latest_log_checkpoint` (§16.1) with its cosignatures.
    fn latest_log_checkpoint<'py>(&self, py: Python<'py>) -> PyResult<CheckpointTuple<'py>> {
        let w = self.with(py, |o| o.db.latest_log_checkpoint())?;
        let c = &w.checkpoint;
        Ok((
            c.tree_size,
            bytes(py, &c.root),
            c.timestamp_ms,
            c.epoch,
            bytes(py, &c.operator_signature),
            w.cosignatures
                .iter()
                .map(|s| (s.witness_index, s.witness_epoch, bytes(py, &s.signature)))
                .collect(),
        ))
    }

    /// `inclusion_proof(leaf_index, tree_size)` (§16.1, RFC 9162), or `None`.
    fn inclusion_proof<'py>(
        &self,
        py: Python<'py>,
        leaf_index: u64,
        tree_size: u64,
    ) -> PyResult<Option<Vec<Bound<'py, PyBytes>>>> {
        let p = self.with(py, move |o| o.db.inclusion_proof(leaf_index, tree_size))?;
        Ok(p.map(|p| p.iter().map(|h| bytes(py, h)).collect()))
    }

    /// `consistency_proof(old_size, new_size)` (§16.1, RFC 9162), or `None`.
    fn consistency_proof<'py>(
        &self,
        py: Python<'py>,
        old_size: u64,
        new_size: u64,
    ) -> PyResult<Option<Vec<Bound<'py, PyBytes>>>> {
        let p = self.with(py, move |o| o.db.consistency_proof(old_size, new_size))?;
        Ok(p.map(|p| p.iter().map(|h| bytes(py, h)).collect()))
    }

    /// DB-107: every committed change's public fields since event `since`, as dicts (the
    /// `inspect` build only; spec §16.1).
    #[cfg(feature = "inspect")]
    fn events<'py>(&self, py: Python<'py>, since: u64) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let evs = self.with(py, move |o| Ok(o.db.inspect.since(since)))?;
        evs.iter().map(|e| event_dict(py, e)).collect()
    }

    /// The committed log for an auditor, as JSON (DB-86).
    fn export_log(&self, py: Python<'_>) -> PyResult<String> {
        self.with(py, |o| o.db.export_log())
    }

    /// The verifier's trust anchors as JSON (§11.3).
    fn anchors(&self, py: Python<'_>) -> PyResult<String> {
        self.with(py, |o| Ok(o.db.anchors().to_json()))
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
            o.db.engine
                .search(c, &query, k)
                .map(|hits| hits.into_iter().map(|h| (h.record_id, h.score)).collect())
        })
    }

    /// `stats` (§16.1).
    fn stats(&self, py: Python<'_>, collection: &str) -> PyResult<BTreeMap<String, u64>> {
        let c = cid(collection)?;
        self.with(py, move |o| {
            o.db.engine.stats(c).map(|s| {
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
        self.with(py, move |o| o.db.engine.stats(c).map(|s| s.group_sizes))
    }

    /// The collection IDs.
    fn collections(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        self.with(py, |o| {
            Ok(o.db.engine.collections().iter().map(cid_hex).collect())
        })
    }

    /// `drop_collection` (§16.1).
    fn drop_collection(&self, py: Python<'_>, collection: &str) -> PyResult<()> {
        let c = cid(collection)?;
        self.with(py, move |o| o.db.engine.drop_collection(c))
    }

    /// `storage_checkpoint_now` (§16.1).
    fn checkpoint(&self, py: Python<'_>) -> PyResult<()> {
        self.with(py, |o| o.db.engine.storage_checkpoint_now())
    }

    /// Clean shutdown (a storage checkpoint) and release of `ENGINE.lock`.
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        // Erratum E-1: the mutex is taken with the GIL released, as in `with`.
        py.detach(|| {
            let taken = self.inner.lock().unwrap_or_else(|p| p.into_inner()).take();
            taken.map_or(Ok(()), sever_db::Opened::close)
        })
        .map_err(py_err)
    }
}

/// The module.
#[pymodule]
fn sever_db_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEngine>()?;
    m.add_class::<PyUserKey>()?;
    m.add_class::<PyInsertRequest>()?;
    m.add_function(wrap_pyfunction!(prepare_insert, m)?)?;
    let py = m.py();
    for (name, ty) in [
        ("SeverError", py.get_type::<SeverError>()),
        ("WrongDimension", py.get_type::<WrongDimension>()),
        ("NonFinite", py.get_type::<NonFinite>()),
        ("NotNormalised", py.get_type::<NotNormalised>()),
        ("InvalidRecordId", py.get_type::<InvalidRecordId>()),
        ("DuplicateRecord", py.get_type::<DuplicateRecord>()),
        ("CommitmentMismatch", py.get_type::<CommitmentMismatch>()),
        ("BadUserSignature", py.get_type::<BadUserSignature>()),
        (
            "GroupCapacityExceeded",
            py.get_type::<GroupCapacityExceeded>(),
        ),
        ("UnknownCollection", py.get_type::<UnknownCollection>()),
        (
            "SeededNonceForbidden",
            py.get_type::<SeededNonceForbidden>(),
        ),
        ("PlatformUnsafe", py.get_type::<PlatformUnsafe>()),
        ("IntegrityViolation", py.get_type::<IntegrityViolation>()),
        ("DurabilityFailure", py.get_type::<DurabilityFailure>()),
    ] {
        m.add(name, ty)?;
    }
    Ok(())
}

/// One event as a dict: the same fields as `sever_db::inspect::Event` (DB-107).
#[cfg(feature = "inspect")]
fn event_dict<'py>(py: Python<'py>, e: &sever_db::inspect::Event) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("seq", e.seq)?;
    d.set_item("kind", e.kind)?;
    d.set_item("collection", &e.collection)?;
    d.set_item("created", e.created.clone())?;
    let groups: Vec<Bound<'py, PyDict>> = e
        .groups
        .iter()
        .map(|g| {
            let m = PyDict::new(py);
            m.set_item("group", &g.group)?;
            m.set_item("n_before", g.n_before)?;
            m.set_item("n_after", g.n_after)?;
            m.set_item("c_s_before", bytes(py, &g.c_s_before))?;
            m.set_item("c_s_after", bytes(py, &g.c_s_after))?;
            Ok(m)
        })
        .collect::<PyResult<_>>()?;
    d.set_item("groups", groups)?;
    d.set_item("counters_before", e.counters_before)?;
    d.set_item("counters_after", e.counters_after)?;
    let side = |v: &[(String, [u8; 64])]| -> Vec<(String, Bound<'py, PyBytes>)> {
        v.iter().map(|(g, s)| (g.clone(), bytes(py, s))).collect()
    };
    d.set_item("arrivals", side(&e.arrivals))?;
    d.set_item("departures", side(&e.departures))?;
    d.set_item("outcomes", e.outcomes.clone())?;
    Ok(d)
}
