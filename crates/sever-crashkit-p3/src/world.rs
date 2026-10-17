//! A Part 3 database on simulated disks, and the application backend's side (§16.2).

use std::sync::Arc;

use rand_core::{OsRng, RngCore};
use sever_commit::InsertCredential;
use sever_crypto::{Generators, KeyPair, Scalar, commit_record, encode_point, insert_message};
use sever_engine::{EngineConfig, FailurePolicy};
use sever_p3::{Db, Settings, open_on};
use sever_txn::SimClock;
use sever_types::{CollectionId, Error};
use sever_vfs::{CrashPolicy, SimVfs, Vfs};

/// The fixed simulated time: one epoch, so every run signs with the same operator epoch.
pub const T0: u64 = 1_790_000_000_000;

/// The two disks of one database.
#[derive(Clone)]
pub struct Disks {
    /// The data directory.
    pub data: SimVfs,
    /// The key directory.
    pub keys: SimVfs,
}

impl Disks {
    /// Empty disks.
    pub fn new() -> Self {
        Self {
            data: SimVfs::new(),
            keys: SimVfs::new(),
        }
    }
    /// A copy of both disks.
    pub fn fork(&self) -> Self {
        Self {
            data: self.data.fork(),
            keys: self.keys.fork(),
        }
    }
    /// A crash of both disks.
    pub fn restart(&self, p: CrashPolicy) {
        self.data.restart(p);
        self.keys.restart(p);
    }
}

impl Default for Disks {
    fn default() -> Self {
        Self::new()
    }
}

/// An insert credential that can be used again for a retry (§15.1: the same request).
#[derive(Clone, Copy, Debug)]
pub struct Cred {
    /// The collection.
    pub collection_id: [u8; 16],
    /// `C_t`.
    pub c_t: [u8; 32],
    /// `r_t` (test harness only; never logged).
    pub r_t: [u8; 32],
    /// The account's key.
    pub user_public_key: [u8; 32],
    /// The insert signature.
    pub signature: [u8; 64],
}

impl Cred {
    /// The engine's credential type.
    pub fn credential(&self) -> InsertCredential {
        InsertCredential {
            collection_id: self.collection_id,
            c_t: self.c_t,
            r_t: self.r_t,
            user_public_key: self.user_public_key,
            signature: self.signature,
        }
    }
}

/// What every open of one run shares: generators, the account key, the clock, the settings.
pub struct World {
    /// The generators (derived once; the self-check still runs at every open).
    pub gens: Arc<Generators>,
    /// The account key (from the OS).
    pub user: KeyPair,
    /// The simulated clock.
    pub clock: Arc<SimClock>,
    /// Engine settings.
    pub cfg: EngineConfig,
    /// Segment size of the log's stores.
    pub log_segment: u64,
}

impl World {
    /// A world for dimension `d`.
    pub fn new(d: usize, cfg: EngineConfig, log_segment: u64) -> Result<Self, String> {
        Ok(Self {
            gens: Arc::new(Generators::derive(d).map_err(|e| format!("generators: {e:?}"))?),
            user: KeyPair::generate(),
            clock: Arc::new(SimClock::new(T0)),
            cfg: EngineConfig {
                on_failure: FailurePolicy::Poison,
                ..cfg
            },
            log_segment,
        })
    }

    /// The dimension.
    pub fn d(&self) -> usize {
        self.gens.d()
    }

    /// Opens (recovering, or creating) the database on `disks`.
    pub fn open(&self, disks: &Disks) -> Result<Db, Error> {
        self.open_vfs(Arc::new(disks.data.clone()), Arc::new(disks.keys.clone()))
    }

    /// Opens the database on any data and key directories (the main line's [`crate::snap`]).
    pub fn open_vfs(&self, data: Arc<dyn Vfs>, keys: Arc<dyn Vfs>) -> Result<Db, Error> {
        let mut s = Settings::new(self.d());
        s.clock = self.clock.clone();
        s.engine = self.cfg.clone();
        s.log_segment_bytes = self.log_segment;
        s.generators = Some(Arc::clone(&self.gens));
        open_on(data, keys, s)
    }

    /// What `prepare_insert` does (§16.2): quantise, `r_t` from the OS, `C_t`, sign.
    pub fn credential(&self, cid: CollectionId, v: &[f32]) -> Result<Cred, Error> {
        let x = sever_quant::quantise(v, self.d())?;
        let mut wide = [0u8; 64];
        OsRng.fill_bytes(&mut wide);
        let r_t = Scalar::from_bytes_mod_order_wide(&wide);
        let c_t = encode_point(
            &commit_record(&self.gens, x.as_slice(), &r_t).map_err(|_| Error::WrongDimension)?,
        );
        Ok(Cred {
            collection_id: *cid.as_bytes(),
            c_t,
            r_t: r_t.to_bytes(),
            user_public_key: self.user.public(),
            signature: self.user.sign(&insert_message(cid.as_bytes(), &c_t)),
        })
    }
}
