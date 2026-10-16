//! `sever-verify` (C-16): verifies a SEVER-DB deletion certificate offline, with no database
//! access, from the certificate and the trust anchors alone (spec §11.3, §16.3). It shares no code
//! with the engine (Build 3-4 §1.6): every check is written here from the spec.

pub mod anchors;
pub mod cert;
pub mod dst;
pub mod gens;
pub mod hex;
pub mod merkle;
pub mod posk;
pub mod verify;
pub mod xmd;

pub use anchors::Anchors;
pub use gens::{GOLDEN_GENERATORS, Generators, SelfCheckFailed, self_check};
pub use verify::{Accepted, Rejection, verify};

#[cfg(test)]
mod tests;
