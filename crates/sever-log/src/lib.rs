//! `sever-log`: the transparency log (Build 3-4 §1.4; spec §10).
//!
//! - [`merkle`]: the RFC 9162 §2.1 tree, its inclusion and consistency proofs and their verifiers,
//!   with every level of the complete subtrees kept in memory (§10.5);
//! - [`leaf`]: insert and delete leaves (§10.2);
//! - [`keys`]: keys by 90-day epoch, old public keys kept forever (§9.8);
//! - [`checkpoint`]: log checkpoints, cadence, cosignatures, the 4-of-5 threshold, genesis
//!   (§10.3–10.4, DB-79);
//! - [`witness`]: EP-10 `Witness`, `SimulatedWitness` and the EP-10 contract (§10.4, DB-53).

#![forbid(unsafe_code)]

pub mod checkpoint;
pub mod keys;
pub mod leaf;
pub mod merkle;
pub mod witness;

#[cfg(test)]
mod tests;
