//! Keys by epoch (§9.8): operator and witness keys change every 90 days from genesis, and every old
//! public key stays resolvable forever so old certificates keep verifying.

use std::collections::BTreeMap;

use sever_crypto::{KeyPair, epoch_of};
use sever_types::Error;

/// Public keys by epoch: what a verifier or a witness trusts (an anchor set, §11.3).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Keyring {
    keys: BTreeMap<u32, [u8; 32]>,
}

impl Keyring {
    /// The empty keyring.
    pub fn new() -> Self {
        Self::default()
    }

    /// Adds (or confirms) the key of `epoch`; returns false if a different key is already there.
    pub fn insert(&mut self, epoch: u32, public: [u8; 32]) -> bool {
        *self.keys.entry(epoch).or_insert(public) == public
    }

    /// The key of `epoch`, if known (§11.3 step 2: unknown epochs are rejected).
    pub fn get(&self, epoch: u32) -> Option<&[u8; 32]> {
        self.keys.get(&epoch)
    }

    /// Every `(epoch, key)`, ascending.
    pub fn iter(&self) -> impl Iterator<Item = (&u32, &[u8; 32])> {
        self.keys.iter()
    }
}

/// Signing keys by epoch for one signer (the operator or a simulated witness). A key is created on
/// first use in its epoch, from OS entropy; its public half joins the [`Keyring`] and stays there.
#[derive(Debug)]
pub struct EpochSigner {
    genesis_ms: u64,
    keys: BTreeMap<u32, KeyPair>,
    ring: Keyring,
}

impl EpochSigner {
    /// A signer whose epochs count from `genesis_ms` (the database creation time, §9.8).
    pub fn new(genesis_ms: u64) -> Self {
        Self {
            genesis_ms,
            keys: BTreeMap::new(),
            ring: Keyring::new(),
        }
    }

    /// A signer restored from stored secrets by epoch.
    pub fn from_secrets(
        genesis_ms: u64,
        secrets: impl IntoIterator<Item = (u32, [u8; 32])>,
    ) -> Self {
        let mut s = Self::new(genesis_ms);
        for (e, secret) in secrets {
            let k = KeyPair::from_secret(&secret);
            s.ring.insert(e, k.public());
            s.keys.insert(e, k);
        }
        s
    }

    /// Adds the key of `epoch` from its stored secret; false if `epoch` already has a key.
    pub fn insert_secret(&mut self, epoch: u32, secret: &[u8; 32]) -> bool {
        if self.keys.contains_key(&epoch) {
            return false;
        }
        let k = KeyPair::from_secret(secret);
        self.ring.insert(epoch, k.public());
        self.keys.insert(epoch, k);
        true
    }

    /// The epoch of time `t_ms`, or `None` before genesis.
    pub fn epoch_at(&self, t_ms: u64) -> Option<u32> {
        epoch_of(self.genesis_ms, t_ms)
    }

    /// The key of `epoch`, created if this is its first use.
    pub fn key(&mut self, epoch: u32) -> &KeyPair {
        let ring = &mut self.ring;
        self.keys.entry(epoch).or_insert_with(|| {
            let k = KeyPair::generate();
            ring.insert(epoch, k.public());
            k
        })
    }

    /// Every public key so far.
    pub fn keyring(&self) -> &Keyring {
        &self.ring
    }

    /// The genesis time.
    pub fn genesis_ms(&self) -> u64 {
        self.genesis_ms
    }
}

/// The operator's signing keys as the log and the certificate builder use them (§9.8). The
/// composition root implements it over a durable key store that saves each new epoch's secret
/// before its first signature (and tells the simulated witnesses its public key); [`EpochSigner`]
/// implements it in memory.
pub trait OperatorKeys: Send {
    /// The database creation time, from which epochs count.
    fn genesis_ms(&self) -> u64;
    /// The epoch of time `t_ms`, or `None` before genesis.
    fn epoch_at(&self, t_ms: u64) -> Option<u32>;
    /// Signs `msg` with the key of `epoch`, creating and keeping that key first if it is new.
    fn sign(&mut self, epoch: u32, msg: &[u8]) -> Result<[u8; 64], Error>;
    /// Every public key so far, by epoch.
    fn keyring(&self) -> &Keyring;
}

impl OperatorKeys for EpochSigner {
    fn genesis_ms(&self) -> u64 {
        self.genesis_ms
    }

    fn epoch_at(&self, t_ms: u64) -> Option<u32> {
        epoch_of(self.genesis_ms, t_ms)
    }

    fn sign(&mut self, epoch: u32, msg: &[u8]) -> Result<[u8; 64], Error> {
        Ok(self.key(epoch).sign(msg))
    }

    fn keyring(&self) -> &Keyring {
        &self.ring
    }
}
