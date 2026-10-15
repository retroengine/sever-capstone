//! The certificate builder (Build 3-4 §1.4; spec §11, §15.3 step 4).

use sever_crypto::{
    CryptoError, DeletionContext, Generators, Scalar, StrictProofRng, commit_group, decode_point,
    decode_record_commitment, encode_point, prove, transition_holds,
};
use sever_log::checkpoint::{Cosignature, is_witnessed};
use sever_log::keys::{EpochSigner, Keyring};
use sever_log::merkle::{leaf_hash, verify_inclusion};

use crate::encoding::{Certificate, GroupFields, InsertInclusion};

/// Why the builder refused to issue a certificate: each is a certificate a verifier would reject
/// (§11.3), so none is ever signed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CertError {
    /// The path does not prove the leaf in the checkpoint's tree (§11.3 step 3), or it has more
    /// than 255 hashes (§11.2 `u8 path_len`).
    NotIncluded,
    /// The checkpoint's operator signature does not verify for its epoch (§11.3 step 3).
    CheckpointSignature,
    /// Fewer than four valid cosignatures from distinct witnesses (§10.4, §11.3 step 4).
    NotWitnessed,
    /// `database_lsn` is not after the insert leaf (§11.3 step 5).
    LsnNotAfterInsert,
    /// The time of issue is before genesis, so it has no epoch (§9.8).
    BeforeGenesis,
    /// `C_S_post + C_t ≠ C_S_pre`: the given state is not this record's removal (§5.3, §11.3
    /// step 6).
    TransitionBroken,
    /// A primitive refused its input (a non-canonical `C_t` or `C_S_pre`, a wrong dimension).
    Crypto(CryptoError),
}

impl From<CryptoError> for CertError {
    fn from(e: CryptoError) -> Self {
        Self::Crypto(e)
    }
}

/// Where the record was deleted from.
#[derive(Clone, Copy, Debug)]
pub enum Removal<'a> {
    /// From a group: its commitment before, and its state after (from the `ChangeSet`).
    Group {
        /// `C_S_pre`, the group's commitment before the deletion.
        c_s_pre: [u8; 32],
        /// `S` after the deletion.
        s_post: &'a [i64],
        /// `r_agg` after the deletion.
        r_post: &'a Scalar,
        /// `n` after the deletion.
        n_post: u64,
    },
    /// From the holding area: no accumulator moved (§11.3 step 7).
    Holding,
}

/// One deletion to certify.
#[derive(Clone, Debug)]
pub struct Deletion<'a> {
    /// The record's insert leaf, covered by a witnessed log checkpoint (§10.3, §11.2).
    pub inclusion: InsertInclusion,
    /// The checkpoint's cosignatures (tag 7).
    pub cosignatures: Vec<Cosignature>,
    /// The leaf index the deletion's own leaf will take (§10.2).
    pub database_lsn: u64,
    /// Group or holding area.
    pub removal: Removal<'a>,
}

/// Builds and signs the certificate of `deletion` at time `now_ms` (§15.3 step 4): tags 1, 5, 9
/// and 13 are taken from the insert leaf so they always agree with it (§11.3 step 3); for a group
/// deletion `C_S_post` is computed from the post-state, the transition is checked, and the proof
/// is made with hedged nonces (§9.5–9.6) under the context of the certificate's own fields; the
/// operator signs with its key of the epoch of `now_ms` (tag 8, §9.8). Refuses anything a verifier
/// would reject (other than the proof, which [`prove`] makes correctly).
pub fn build(
    gens: &Generators,
    deletion: Deletion<'_>,
    operator: &mut EpochSigner,
    witnesses: &[Keyring],
    now_ms: u64,
    rng: &mut StrictProofRng,
) -> Result<Certificate, CertError> {
    let Deletion {
        inclusion,
        cosignatures,
        database_lsn,
        removal,
    } = deletion;
    let cp = &inclusion.checkpoint;
    let leaf = &inclusion.leaf;
    if inclusion.path.len() > usize::from(u8::MAX)
        || !verify_inclusion(
            &leaf_hash(&leaf.to_bytes()),
            inclusion.leaf_index,
            cp.tree_size,
            &inclusion.path,
            &cp.root,
        )
    {
        return Err(CertError::NotIncluded);
    }
    if !cp.verify(operator.keyring()) {
        return Err(CertError::CheckpointSignature);
    }
    if !is_witnessed(cp, &cosignatures, witnesses) {
        return Err(CertError::NotWitnessed);
    }
    if database_lsn <= inclusion.leaf_index {
        return Err(CertError::LsnNotAfterInsert);
    }
    let key_period = operator.epoch_at(now_ms).ok_or(CertError::BeforeGenesis)?;
    let group = match removal {
        Removal::Holding => None,
        Removal::Group {
            c_s_pre,
            s_post,
            r_post,
            n_post,
        } => {
            let pre = decode_point(&c_s_pre)?;
            let c_t = decode_record_commitment(&leaf.c_t)?;
            let post = commit_group(gens, s_post, r_post)?;
            if !transition_holds(&post, &c_t, &pre) {
                return Err(CertError::TransitionBroken);
            }
            let c_s_post = encode_point(&post);
            let ctx = DeletionContext {
                c_s_pre,
                c_t: leaf.c_t,
                scrambled_id: leaf.scrambled_id,
                database_lsn,
                collection_id: leaf.collection_id,
            };
            let proof = prove(gens, s_post, r_post, &ctx, rng)?.to_bytes();
            #[cfg(not(feature = "sabotage-SB-22"))]
            let emptied = n_post == 0;
            #[cfg(feature = "sabotage-SB-22")]
            let emptied = n_post <= 1; // SB-22: tag 11 set wrongly
            Some(GroupFields {
                c_s_pre,
                c_s_post,
                proof,
                emptied,
            })
        }
    };
    let mut cert = Certificate {
        c_t: leaf.c_t,
        group,
        user_signature: leaf.user_signature,
        scrambled_id: leaf.scrambled_id,
        collection_id: leaf.collection_id,
        inclusion,
        cosignatures,
        key_period,
        database_lsn,
        operator_signature: [0; 64],
    };
    cert.sign(operator.key(key_period));
    Ok(cert)
}
