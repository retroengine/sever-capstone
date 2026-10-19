//! The operator's signing keys by epoch, kept in `SECRETS` (spec §14.1: "k_scramble and operator
//! signing keys by epoch"; §14.9: later parts add entry kinds; DB-83). Each new epoch's secret is
//! drawn from the OS and written durably **before** its first signature, so a restart can never
//! make a second key for an epoch whose first key already signed something (§9.8: old keys stay
//! resolvable).

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use rand_core::{OsRng, RngCore};
use sever_crypto::epoch_of;
use sever_format::Secrets;
use sever_log::keys::{EpochSigner, Keyring, OperatorKeys};
use sever_types::Error;
use sever_vfs::{OpenMode, Vfs, VfsError, durable, read_all};
use zeroize::Zeroizing;

/// `SECRETS` entry kind of an operator signing key: `u32be epoch ‖ secret (32)` (DB-83).
pub const K_OPERATOR_KEY: u16 = 2;
/// `SECRETS` entry kind of the database creation time: `u64be ms` (DB-83).
pub const K_GENESIS_MS: u16 = 3;
/// The file (§14.1), owned by the engine; Part 3 adds entries to it.
pub const SECRETS: &str = sever_engine::SECRETS;

fn bad(rule: &'static str) -> Error {
    Error::IntegrityViolation { invariant: rule }
}

/// 32 bytes from the OS (§9.8 keys come from the OS, never from a seed).
pub(crate) fn os_secret() -> Zeroizing<[u8; 32]> {
    let mut s = Zeroizing::new([0u8; 32]);
    OsRng.fill_bytes(s.as_mut());
    s
}

fn read_secrets(keys: &dyn Vfs, sealer_id: u16) -> Result<Option<Secrets>, Error> {
    match keys.open(SECRETS, OpenMode::Existing) {
        Ok(f) => {
            let bytes = Zeroizing::new(read_all(f.as_ref()).map_err(|_| Error::DurabilityFailure)?);
            Secrets::parse(&bytes, sealer_id).map(Some)
        }
        Err(VfsError::NotFound) => Ok(None),
        Err(_) => Err(Error::DurabilityFailure),
    }
}

/// Called after every rewrite of `SECRETS` (the posix root sets mode 0600, §14.1).
pub type AfterWrite = Box<dyn Fn() -> Result<(), Error> + Send>;

/// The operator's keys, durable in `SECRETS`.
pub struct OperatorStore {
    keys: Arc<dyn Vfs>,
    signer: EpochSigner,
    secrets: BTreeMap<u32, Zeroizing<[u8; 32]>>,
    genesis_ms: u64,
    sealer_id: u16,
    published: Arc<Mutex<Keyring>>,
    after_write: Option<AfterWrite>,
}

impl core::fmt::Debug for OperatorStore {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "OperatorStore({} epochs)", self.secrets.len()) // §17: no key
    }
}

impl OperatorStore {
    /// Loads the operator's keys and the creation time from `SECRETS` in `keys`; a database
    /// without them (a new one) starts at `now_ms`, written with its first key.
    pub fn load(
        keys: Arc<dyn Vfs>,
        now_ms: u64,
        after_write: Option<AfterWrite>,
    ) -> Result<Self, Error> {
        Self::load_sealed(keys, sever_format::SEALER_PLAINTEXT, now_ms, after_write)
    }

    /// [`OperatorStore::load`] for a database whose files name the sealer `sealer_id` (DB-48:
    /// `SECRETS` carries the database's sealer; Part 4's databases are AES-256-GCM-SIV).
    pub fn load_sealed(
        keys: Arc<dyn Vfs>,
        sealer_id: u16,
        now_ms: u64,
        after_write: Option<AfterWrite>,
    ) -> Result<Self, Error> {
        let mut secrets = BTreeMap::new();
        let mut genesis_ms = None;
        if let Some(s) = read_secrets(keys.as_ref(), sealer_id)? {
            for (kind, v) in &s.entries {
                match *kind {
                    K_OPERATOR_KEY => {
                        let (e, k) = v
                            .split_first_chunk::<4>()
                            .ok_or(bad("DB-83 operator key"))?;
                        let k: [u8; 32] = k.try_into().map_err(|_| bad("DB-83 operator key"))?;
                        if secrets
                            .insert(u32::from_be_bytes(*e), Zeroizing::new(k))
                            .is_some()
                        {
                            return Err(bad("DB-83 operator key"));
                        }
                    }
                    K_GENESIS_MS => {
                        let t: [u8; 8] =
                            v.as_slice().try_into().map_err(|_| bad("DB-83 genesis"))?;
                        genesis_ms = Some(u64::from_be_bytes(t));
                    }
                    _ => {}
                }
            }
        }
        if genesis_ms.is_none() && !secrets.is_empty() {
            return Err(bad("DB-83 genesis"));
        }
        let genesis_ms = genesis_ms.unwrap_or(now_ms);
        let signer = EpochSigner::from_secrets(genesis_ms, secrets.iter().map(|(e, k)| (*e, **k)));
        let published = Arc::new(Mutex::new(signer.keyring().clone()));
        Ok(Self {
            keys,
            signer,
            secrets,
            genesis_ms,
            sealer_id,
            published,
            after_write,
        })
    }

    /// The operator's public keys, shared with the simulated witnesses (who must trust each new
    /// epoch's key, §10.4).
    pub fn published(&self) -> Arc<Mutex<Keyring>> {
        Arc::clone(&self.published)
    }

    /// Rewrites `SECRETS` with every operator key and the creation time, keeping the entries of
    /// other kinds (`k_scramble`), atomically (§12.7).
    fn save(&self, new: Option<(u32, &[u8; 32])>) -> Result<(), Error> {
        let mut s = read_secrets(self.keys.as_ref(), self.sealer_id)?
            .ok_or(bad("§14.1 SECRETS missing"))?;
        s.entries
            .retain(|(k, _)| *k != K_OPERATOR_KEY && *k != K_GENESIS_MS);
        s.entries
            .push((K_GENESIS_MS, self.genesis_ms.to_be_bytes().to_vec()));
        let all = self.secrets.iter().map(|(e, k)| (*e, &**k)).chain(new);
        for (e, k) in all {
            let mut v = e.to_be_bytes().to_vec();
            v.extend_from_slice(k);
            s.entries.push((K_OPERATOR_KEY, v));
        }
        let bytes = Zeroizing::new(s.encode());
        for (_, v) in &mut s.entries {
            zeroize::Zeroize::zeroize(v);
        }
        durable::replace_file(self.keys.as_ref(), SECRETS, &bytes)
            .map_err(|_| Error::DurabilityFailure)?;
        match &self.after_write {
            Some(f) => f(),
            None => Ok(()),
        }
    }
}

impl OperatorKeys for OperatorStore {
    fn genesis_ms(&self) -> u64 {
        self.genesis_ms
    }

    fn epoch_at(&self, t_ms: u64) -> Option<u32> {
        epoch_of(self.genesis_ms, t_ms)
    }

    fn sign(&mut self, epoch: u32, msg: &[u8]) -> Result<[u8; 64], Error> {
        if self.signer.keyring().get(epoch).is_none() {
            let s = os_secret();
            self.save(Some((epoch, &s)))?; // durable before the key signs anything
            self.signer.insert_secret(epoch, &s);
            self.secrets.insert(epoch, s);
            let public = *self
                .signer
                .keyring()
                .get(epoch)
                .ok_or(bad("§9.8 epoch key"))?;
            match self.published.lock() {
                Ok(mut r) => r.insert(epoch, public),
                Err(p) => p.into_inner().insert(epoch, public),
            };
        }
        Ok(self.signer.key(epoch).sign(msg))
    }

    fn keyring(&self) -> &Keyring {
        self.signer.keyring()
    }
}
