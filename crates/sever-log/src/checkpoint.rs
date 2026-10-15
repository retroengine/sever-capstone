//! Log checkpoints (§10.3), cosignatures and the witness threshold (§10.4), and the genesis
//! checkpoint (DB-79).

use sever_crypto::{CHECKPOINT_MESSAGE_LEN, checkpoint_message, cosign_message, verify_signature};

use crate::keys::{EpochSigner, Keyring};
use crate::merkle::{Hash, empty_root};

/// Checkpoint cadence (§2.2, §10.3): one whenever `tree_size` reaches a multiple of this.
pub const CHECKPOINT_EVERY: u64 = 10_000;
/// Number of witnesses (§2.2, §10.4).
pub const WITNESSES: u8 = 5;
/// Cosignatures from distinct witnesses that make a checkpoint witnessed (§2.2, §10.4).
#[cfg(not(feature = "sabotage-SB-20"))]
pub const THRESHOLD: usize = 4;
/// SB-20 (Build §2.6): three of five accepted.
#[cfg(feature = "sabotage-SB-20")]
pub const THRESHOLD: usize = 3;
/// Encoded size of a checkpoint: `u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch ‖
/// operator_signature` (§11.2).
pub const CHECKPOINT_LEN: usize = 8 + 32 + 8 + 4 + 64;
/// Encoded size of one cosignature: `u8 witness_index ‖ u32be witness_epoch ‖ signature` (§11.1
/// tag 7).
pub const COSIGNATURE_LEN: usize = 1 + 4 + 64;

/// `(tree_size, root, timestamp_ms, epoch, operator_signature)` (§10.3).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LogCheckpoint {
    /// Leaves covered.
    pub tree_size: u64,
    /// The RFC 9162 root at `tree_size`.
    pub root: Hash,
    /// When it was issued.
    pub timestamp_ms: u64,
    /// The operator epoch that signed it.
    pub epoch: u32,
    /// The operator's signature over the §9.8 message.
    pub operator_signature: [u8; 64],
}

impl LogCheckpoint {
    /// The signed message `DST_STH ‖ u64be tree_size ‖ root ‖ u64be timestamp_ms ‖ u32be epoch`.
    pub fn message(&self) -> [u8; CHECKPOINT_MESSAGE_LEN] {
        checkpoint_message(self.tree_size, &self.root, self.timestamp_ms, self.epoch)
    }

    /// Signs a checkpoint with the operator's key for the epoch of `timestamp_ms`.
    pub fn sign(
        operator: &mut EpochSigner,
        tree_size: u64,
        root: Hash,
        timestamp_ms: u64,
    ) -> Option<Self> {
        let epoch = operator.epoch_at(timestamp_ms)?;
        let message = checkpoint_message(tree_size, &root, timestamp_ms, epoch);
        let operator_signature = operator.key(epoch).sign(&message);
        Some(Self {
            tree_size,
            root,
            timestamp_ms,
            epoch,
            operator_signature,
        })
    }

    /// DB-79: the genesis checkpoint, `(0, SHA-256(""), creation time, epoch 0)`, signed when the
    /// database is created; every witness starts from it.
    pub fn genesis(operator: &mut EpochSigner) -> Option<Self> {
        let t = operator.genesis_ms();
        Self::sign(operator, 0, empty_root(), t)
    }

    /// Verifies the operator signature with the key of the checkpoint's epoch (`verify_strict`).
    pub fn verify(&self, operators: &Keyring) -> bool {
        operators
            .get(self.epoch)
            .is_some_and(|k| verify_signature(k, &self.message(), &self.operator_signature).is_ok())
    }

    /// The 116-byte encoding (§11.2).
    pub fn to_bytes(&self) -> [u8; CHECKPOINT_LEN] {
        let mut out = [0u8; CHECKPOINT_LEN];
        let parts: [&[u8]; 5] = [
            &self.tree_size.to_be_bytes(),
            &self.root,
            &self.timestamp_ms.to_be_bytes(),
            &self.epoch.to_be_bytes(),
            &self.operator_signature,
        ];
        let mut rest = out.as_mut_slice();
        for p in parts {
            let (head, tail) = rest.split_at_mut(p.len());
            head.copy_from_slice(p);
            rest = tail;
        }
        out
    }

    /// Strict parse of exactly 116 bytes.
    pub fn parse(b: &[u8]) -> Option<Self> {
        let b: &[u8; CHECKPOINT_LEN] = b.try_into().ok()?;
        let (size, rest) = b.split_first_chunk::<8>()?;
        let (root, rest) = rest.split_first_chunk::<32>()?;
        let (ts, rest) = rest.split_first_chunk::<8>()?;
        let (epoch, rest) = rest.split_first_chunk::<4>()?;
        Some(Self {
            tree_size: u64::from_be_bytes(*size),
            root: *root,
            timestamp_ms: u64::from_be_bytes(*ts),
            epoch: u32::from_be_bytes(*epoch),
            operator_signature: rest.try_into().ok()?,
        })
    }
}

/// §10.3: a checkpoint is due when `tree_size` reaches a positive multiple of 10,000.
pub fn checkpoint_due(tree_size: u64) -> bool {
    tree_size > 0 && tree_size % CHECKPOINT_EVERY == 0
}

/// One witness cosignature (§10.4; §11.1 tag 7 entry).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Cosignature {
    /// Which witness, `0 … 4`.
    pub witness_index: u8,
    /// The witness's own key epoch.
    pub witness_epoch: u32,
    /// Its signature over `DST_COSIGN ‖` the checkpoint message (§9.8).
    pub signature: [u8; 64],
}

impl Cosignature {
    /// Does this cosignature verify over `cp` with the witness's key for its epoch?
    pub fn verify(&self, cp: &LogCheckpoint, witnesses: &[Keyring]) -> bool {
        witnesses
            .get(usize::from(self.witness_index))
            .and_then(|ring| ring.get(self.witness_epoch))
            .is_some_and(|k| {
                verify_signature(k, &cosign_message(&cp.message()), &self.signature).is_ok()
            })
    }

    /// `u8 witness_index ‖ u32be witness_epoch ‖ signature` (69 bytes).
    pub fn to_bytes(&self) -> [u8; COSIGNATURE_LEN] {
        let mut out = [0u8; COSIGNATURE_LEN];
        let (idx, rest) = out.split_at_mut(1);
        let (epoch, sig) = rest.split_at_mut(4);
        idx.copy_from_slice(&[self.witness_index]);
        epoch.copy_from_slice(&self.witness_epoch.to_be_bytes());
        sig.copy_from_slice(&self.signature);
        out
    }

    /// Strict parse of exactly 69 bytes.
    pub fn parse(b: &[u8]) -> Option<Self> {
        let b: &[u8; COSIGNATURE_LEN] = b.try_into().ok()?;
        let (idx, rest) = b.split_first()?;
        let (epoch, sig) = rest.split_first_chunk::<4>()?;
        Some(Self {
            witness_index: *idx,
            witness_epoch: u32::from_be_bytes(*epoch),
            signature: sig.try_into().ok()?,
        })
    }
}

/// §10.4: witnessed iff at least [`THRESHOLD`] cosignatures from distinct witnesses verify over
/// `cp`, each with its witness's key for its epoch (`witnesses[i]` is witness `i`'s keyring).
pub fn is_witnessed(cp: &LogCheckpoint, cosigs: &[Cosignature], witnesses: &[Keyring]) -> bool {
    let mut seen = [false; 256];
    let mut valid = 0usize;
    for c in cosigs {
        if c.verify(cp, witnesses) {
            if let Some(s) = seen.get_mut(usize::from(c.witness_index)) {
                if !*s {
                    *s = true;
                    valid += 1;
                }
            }
        }
    }
    valid >= THRESHOLD
}
