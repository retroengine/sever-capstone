//! The five simulated witnesses (spec §10.4, §9.8: "in v1 the witnesses are simulated by the
//! project and their keys live in the test harness"; DB-53, DB-83). Each wraps `sever-log`'s
//! `SimulatedWitness` and keeps its keys by epoch and the last checkpoint it cosigned in the file
//! `WITNESSES` of the key directory, written before a new key signs and after every cosignature,
//! so its memory survives restarts (a witness that forgot would accept any later tree).
//!
//! `WITNESSES`: `magic "SVDBWITN" ‖ u16be version 1 ‖ u64be genesis_ms ‖ u8 count ‖ count ×
//! (u8 index ‖ last checkpoint (116) ‖ u32be n ‖ n × (u32be epoch ‖ secret 32)) ‖ SHA-256 of every
//! preceding byte`.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};

use sever_log::checkpoint::{CHECKPOINT_LEN, Cosignature, LogCheckpoint, WITNESSES};
use sever_log::keys::{EpochSigner, Keyring};
use sever_log::merkle::{Hash, empty_root};
use sever_log::witness::{Refusal, SimulatedWitness, Witness};
use sever_types::Error;
use sever_vfs::{OpenMode, Vfs, VfsError, durable, read_all};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

use crate::keys::os_secret;

/// The file in the key directory.
pub const WITNESS_FILE: &str = "WITNESSES";
const MAGIC: &[u8; 8] = b"SVDBWITN";

fn bad() -> Error {
    Error::IntegrityViolation {
        invariant: "DB-83 WITNESSES",
    }
}

type Keys = BTreeMap<u32, Zeroizing<[u8; 32]>>;
/// A witness's stored memory: its last checkpoint and its keys by epoch.
type Stored = (LogCheckpoint, Vec<(u32, [u8; 32])>);

struct State {
    genesis_ms: u64,
    witnesses: BTreeMap<u8, (LogCheckpoint, Keys)>,
}

/// The witnesses' shared file.
struct WitnessFile {
    keys: Arc<dyn Vfs>,
    state: Mutex<State>,
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    match m.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    }
}

impl WitnessFile {
    fn encode(s: &State) -> Zeroizing<Vec<u8>> {
        let mut out = Zeroizing::new(MAGIC.to_vec());
        out.extend_from_slice(&1u16.to_be_bytes());
        out.extend_from_slice(&s.genesis_ms.to_be_bytes());
        out.push(u8::try_from(s.witnesses.len()).unwrap_or(u8::MAX));
        for (i, (last, keys)) in &s.witnesses {
            out.push(*i);
            out.extend_from_slice(&last.to_bytes());
            out.extend_from_slice(&u32::try_from(keys.len()).unwrap_or(u32::MAX).to_be_bytes());
            for (e, k) in keys {
                out.extend_from_slice(&e.to_be_bytes());
                out.extend_from_slice(k.as_ref());
            }
        }
        let h = Sha256::digest(out.as_slice());
        out.extend_from_slice(&h);
        out
    }

    fn decode(b: &[u8]) -> Option<State> {
        let (body, h) = b.split_at_checked(b.len().checked_sub(32)?)?;
        if Sha256::digest(body).as_slice() != h {
            return None;
        }
        let rest = body.strip_prefix(MAGIC.as_slice())?;
        let (v, rest) = rest.split_first_chunk::<2>()?;
        let (g, rest) = rest.split_first_chunk::<8>()?;
        let (&n, mut rest) = rest.split_first()?;
        if u16::from_be_bytes(*v) != 1 {
            return None;
        }
        let mut witnesses = BTreeMap::new();
        for _ in 0..n {
            let (&i, r) = rest.split_first()?;
            let (cp, r) = r.split_first_chunk::<CHECKPOINT_LEN>()?;
            let (k, mut r) = r.split_first_chunk::<4>()?;
            let mut keys = BTreeMap::new();
            for _ in 0..u32::from_be_bytes(*k) {
                let (e, r2) = r.split_first_chunk::<4>()?;
                let (s, r3) = r2.split_first_chunk::<32>()?;
                keys.insert(u32::from_be_bytes(*e), Zeroizing::new(*s));
                r = r3;
            }
            witnesses.insert(i, (LogCheckpoint::parse(cp)?, keys));
            rest = r;
        }
        rest.is_empty().then_some(State {
            genesis_ms: u64::from_be_bytes(*g),
            witnesses,
        })
    }

    fn save(&self, s: &State) -> Result<(), Error> {
        durable::replace_file(self.keys.as_ref(), WITNESS_FILE, &Self::encode(s))
            .map_err(|_| Error::DurabilityFailure)
    }
}

/// One simulated witness with durable memory.
pub struct SimWitness {
    inner: SimulatedWitness,
    index: u8,
    operators: Arc<Mutex<Keyring>>,
    file: Arc<WitnessFile>,
}

impl core::fmt::Debug for SimWitness {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "SimWitness({})", self.index)
    }
}

/// Loads (or starts) the five simulated witnesses from `WITNESSES` in `keys`. A new witness starts
/// from the empty tree (DB-79: every witness accepts any first checkpoint as an extension of the
/// genesis one) and trusts the operator keys in `operators`, which grow as epochs advance.
pub fn load(
    keys: Arc<dyn Vfs>,
    genesis_ms: u64,
    operators: Arc<Mutex<Keyring>>,
) -> Result<Vec<Box<dyn Witness>>, Error> {
    let state = match keys.open(WITNESS_FILE, OpenMode::Existing) {
        Ok(f) => {
            let b = Zeroizing::new(read_all(f.as_ref()).map_err(|_| Error::DurabilityFailure)?);
            let s = WitnessFile::decode(&b).ok_or_else(bad)?;
            if s.genesis_ms != genesis_ms {
                return Err(bad());
            }
            s
        }
        Err(VfsError::NotFound) => State {
            genesis_ms,
            witnesses: BTreeMap::new(),
        },
        Err(_) => return Err(Error::DurabilityFailure),
    };
    let start = LogCheckpoint {
        tree_size: 0,
        root: empty_root(),
        timestamp_ms: genesis_ms,
        epoch: 0,
        operator_signature: [0; 64],
    };
    let ring = lock(&operators).clone();
    let stored: Vec<Stored> = (0..WITNESSES)
        .map(|i| {
            state
                .witnesses
                .get(&i)
                .map_or((start, Vec::new()), |(l, k)| {
                    (*l, k.iter().map(|(e, s)| (*e, **s)).collect())
                })
        })
        .collect();
    // One file for all five.
    let file = Arc::new(WitnessFile {
        keys,
        state: Mutex::new(state),
    });
    Ok((0..WITNESSES)
        .zip(stored)
        .map(|(i, (last, secrets))| {
            let signer = EpochSigner::from_secrets(genesis_ms, secrets);
            Box::new(SimWitness {
                inner: SimulatedWitness::restore(i, signer, ring.clone(), last),
                index: i,
                operators: Arc::clone(&operators),
                file: Arc::clone(&file),
            }) as Box<dyn Witness>
        })
        .collect())
}

impl SimWitness {
    /// Records this witness's keys and last checkpoint in the shared file.
    fn record(&self, last: LogCheckpoint, new_key: Option<(u32, &[u8; 32])>) -> Result<(), Error> {
        let mut s = lock(&self.file.state);
        let entry = s
            .witnesses
            .entry(self.index)
            .or_insert_with(|| (last, BTreeMap::new()));
        entry.0 = last;
        if let Some((e, k)) = new_key {
            entry.1.insert(e, Zeroizing::new(*k));
        }
        self.file.save(&s)
    }
}

impl Witness for SimWitness {
    fn index(&self) -> u8 {
        self.index
    }

    fn last(&self) -> &LogCheckpoint {
        self.inner.last()
    }

    fn cosign(
        &mut self,
        new: &LogCheckpoint,
        proof: &[Hash],
        now_ms: u64,
    ) -> Result<Cosignature, Refusal> {
        for (e, k) in lock(&self.operators).iter() {
            self.inner.trust_operator(*e, *k);
        }
        let epoch = self.inner.epoch_at(now_ms).ok_or(Refusal::NoEpoch)?;
        if self.inner.keyring().get(epoch).is_none() {
            let s = os_secret();
            self.record(*self.inner.last(), Some((epoch, &s)))
                .map_err(|_| Refusal::Unavailable)?;
            self.inner.add_key(epoch, &s);
        }
        let c = self.inner.cosign(new, proof, now_ms)?;
        self.record(*new, None).map_err(|_| Refusal::Unavailable)?;
        Ok(c)
    }

    fn keyring(&self) -> &Keyring {
        self.inner.keyring()
    }
}
