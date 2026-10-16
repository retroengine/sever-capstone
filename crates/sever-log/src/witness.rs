//! EP-10 `Witness` (Build 3-4 §1.5; spec §10.4, DB-53): receives a new log checkpoint and the
//! consistency proof from the last checkpoint it cosigned, and cosigns only if the proof verifies.
//! [`SimulatedWitness`] is the default; v1's five witnesses are simulated by the project (§9.8).

use sever_crypto::cosign_message;

use crate::checkpoint::{Cosignature, LogCheckpoint};
use crate::keys::{EpochSigner, Keyring};
use crate::merkle::{Hash, verify_consistency};

/// Why a witness refused to cosign.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// The operator signature does not verify for the checkpoint's epoch.
    OperatorSignature,
    /// The new checkpoint is smaller than the last one cosigned.
    Shrunk,
    /// Same size, different root: a fork.
    Fork,
    /// The consistency proof does not verify.
    Inconsistent,
    /// No key for the cosigning time (before genesis).
    NoEpoch,
    /// The witness could not keep its state (its key or its memory), so it does not cosign.
    Unavailable,
}

/// EP-10.
pub trait Witness: Send {
    /// This witness's index, `0 … 4`.
    fn index(&self) -> u8;
    /// The last checkpoint it cosigned (the genesis checkpoint at first, DB-79).
    fn last(&self) -> &LogCheckpoint;
    /// Cosign `new` at time `now_ms` if `proof` (RFC 9162 `PROOF(last.tree_size, new.tree_size)`)
    /// shows `new` extends [`Witness::last`]; on success `new` becomes the last cosigned.
    fn cosign(
        &mut self,
        new: &LogCheckpoint,
        proof: &[Hash],
        now_ms: u64,
    ) -> Result<Cosignature, Refusal>;
    /// The public keys of this witness by epoch.
    fn keyring(&self) -> &Keyring;
}

/// The consistency rule every honest witness applies (§10.4).
pub fn extends(last: &LogCheckpoint, new: &LogCheckpoint, proof: &[Hash]) -> Result<(), Refusal> {
    if new.tree_size < last.tree_size {
        return Err(Refusal::Shrunk);
    }
    if new.tree_size == last.tree_size {
        return if new.root == last.root {
            Ok(())
        } else {
            Err(Refusal::Fork)
        };
    }
    if last.tree_size == 0 {
        return Ok(()); // every tree extends the empty one (RFC 9162 proofs need 0 < first)
    }
    if verify_consistency(last.tree_size, new.tree_size, &last.root, &new.root, proof) {
        Ok(())
    } else {
        Err(Refusal::Inconsistent)
    }
}

/// A project-run witness: its own keys by epoch, the operator's public keys, and its memory.
#[derive(Debug)]
pub struct SimulatedWitness {
    index: u8,
    signer: EpochSigner,
    operators: Keyring,
    last: LogCheckpoint,
}

impl SimulatedWitness {
    /// Witness `index`, trusting `operators`, starting from the genesis checkpoint.
    pub fn new(index: u8, genesis_ms: u64, operators: Keyring, genesis: LogCheckpoint) -> Self {
        Self {
            index,
            signer: EpochSigner::new(genesis_ms),
            operators,
            last: genesis,
        }
    }

    /// The operator keyring this witness trusts (updated as operator epochs advance).
    pub fn trust_operator(&mut self, epoch: u32, public: [u8; 32]) -> bool {
        self.operators.insert(epoch, public)
    }

    /// A witness restored from its stored state: its keys by epoch and the last checkpoint it
    /// cosigned.
    pub fn restore(
        index: u8,
        signer: EpochSigner,
        operators: Keyring,
        last: LogCheckpoint,
    ) -> Self {
        Self {
            index,
            signer,
            operators,
            last,
        }
    }

    /// Adds this witness's key of `epoch` from a stored secret (false if it already has one), so
    /// a key it first uses can be kept before it signs with it.
    pub fn add_key(&mut self, epoch: u32, secret: &[u8; 32]) -> bool {
        self.signer.insert_secret(epoch, secret)
    }

    /// The epoch of time `t_ms` for this witness's keys.
    pub fn epoch_at(&self, t_ms: u64) -> Option<u32> {
        self.signer.epoch_at(t_ms)
    }
}

impl Witness for SimulatedWitness {
    fn index(&self) -> u8 {
        self.index
    }

    fn last(&self) -> &LogCheckpoint {
        &self.last
    }

    fn cosign(
        &mut self,
        new: &LogCheckpoint,
        proof: &[Hash],
        now_ms: u64,
    ) -> Result<Cosignature, Refusal> {
        if !new.verify(&self.operators) {
            return Err(Refusal::OperatorSignature);
        }
        extends(&self.last, new, proof)?;
        let epoch = self.signer.epoch_at(now_ms).ok_or(Refusal::NoEpoch)?;
        let signature = self.signer.key(epoch).sign(&cosign_message(&new.message()));
        self.last = *new;
        Ok(Cosignature {
            witness_index: self.index,
            witness_epoch: epoch,
            signature,
        })
    }

    fn keyring(&self) -> &Keyring {
        self.signer.keyring()
    }
}

/// Why a witness failed the EP-10 contract (P3-T12).
#[cfg(any(test, feature = "contract-tests"))]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ep10Violation {
    /// It refused an honest extension of the log.
    RefusedHonest,
    /// Its cosignature does not verify with its own key.
    BadCosignature,
    /// It cosigned a checkpoint that is not consistent with its last one (a fork or rewrite).
    CosignedInconsistent,
    /// It cosigned a smaller tree than its last one.
    CosignedShrink,
    /// It cosigned a checkpoint whose operator signature is bad.
    CosignedBadOperator,
}

/// EP-10 contract: `make(operators, genesis)` builds a fresh witness. It must cosign honest
/// growth, and refuse a forked tree, a shrink and a bad operator signature.
#[cfg(any(test, feature = "contract-tests"))]
pub fn ep10_contract<W: Witness>(
    make: impl Fn(Keyring, LogCheckpoint) -> W,
) -> Result<(), Ep10Violation> {
    use crate::merkle::MerkleTree;
    let t0 = 1_700_000_000_000u64;
    let mut op = EpochSigner::new(t0);
    let Ok(genesis) = LogCheckpoint::genesis(&mut op) else {
        return Err(Ep10Violation::RefusedHonest);
    };
    let mut honest = MerkleTree::new();
    let mut forked = MerkleTree::new();
    for i in 0u64..9 {
        honest.push(&i.to_be_bytes());
        forked.push(&(if i == 2 { 99u64 } else { i }).to_be_bytes());
    }
    let cp = |op: &mut EpochSigner, t: &MerkleTree, n: u64, at: u64| {
        t.root(n)
            .and_then(|r| LogCheckpoint::sign(op, n, r, t0 + at).ok())
    };
    let (Some(c3), Some(c7), Some(f8), Some(c2)) = (
        cp(&mut op, &honest, 3, 1),
        cp(&mut op, &honest, 7, 2),
        cp(&mut op, &forked, 8, 3),
        cp(&mut op, &honest, 2, 4),
    ) else {
        return Err(Ep10Violation::RefusedHonest);
    };
    let mut w = make(op.keyring().clone(), genesis);
    let ok = |w: &mut W, c: &LogCheckpoint, proof: &[Hash]| -> Result<(), Ep10Violation> {
        let s = w
            .cosign(c, proof, t0 + 10)
            .map_err(|_| Ep10Violation::RefusedHonest)?;
        let rings = vec![w.keyring().clone(); usize::from(w.index()) + 1];
        if s.verify(c, &rings) {
            Ok(())
        } else {
            Err(Ep10Violation::BadCosignature)
        }
    };
    ok(&mut w, &c3, &[])?; // from genesis
    ok(
        &mut w,
        &c7,
        &honest.consistency_proof(3, 7).unwrap_or_default(),
    )?;
    // A forked tree of size 8, with its own (valid for the fork) proof from size 7.
    if w.cosign(
        &f8,
        &forked.consistency_proof(7, 8).unwrap_or_default(),
        t0 + 11,
    )
    .is_ok()
    {
        return Err(Ep10Violation::CosignedInconsistent);
    }
    if w.cosign(&c2, &[], t0 + 12).is_ok() {
        return Err(Ep10Violation::CosignedShrink);
    }
    let mut bad = c7;
    bad.operator_signature[0] ^= 1;
    if w.cosign(&bad, &[], t0 + 13).is_ok() {
        return Err(Ep10Violation::CosignedBadOperator);
    }
    Ok(())
}
