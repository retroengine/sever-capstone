//! `sever-audit` (C-17): with access to a log export, checks what a certificate cannot prove by
//! itself (spec §11.3 "what it does not prove", §16.3; DB-86). The certificate checks are the
//! verifier's own code, copied file by file (Build 3-4 §1.4: copying, not a path dependency).

pub mod anchors;
pub mod audit;
pub mod cert;
pub mod dst;
pub mod gens;
pub mod hex;
pub mod merkle;
pub mod posk;
pub mod verify;
pub mod xmd;

pub use anchors::Anchors;
pub use audit::{Export, Finding, audit};
pub use gens::{GOLDEN_GENERATORS, Generators, self_check};

#[cfg(test)]
mod tests;
