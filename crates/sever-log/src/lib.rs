//! `sever-log`: the transparency log (Build 3-4 §1.4; spec §10).
//!
//! - [`merkle`]: the RFC 9162 §2.1 tree, its inclusion and consistency proofs and their verifiers,
//!   with every level of the complete subtrees kept in memory (§10.5).

#![forbid(unsafe_code)]

pub mod merkle;

#[cfg(test)]
mod tests;
