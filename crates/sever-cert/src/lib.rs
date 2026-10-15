//! `sever-cert`: deletion certificates (Build 3-4 §1.4; spec §11.1–11.2).
//!
//! - [`Certificate`]: the TLV encoding of §11.1 (tags 1 … 13 in order, each once, then the
//!   operator's signature over `DST_CERT ‖ body`), with the `insert_inclusion` field of §11.2, and
//!   a strict parser;
//! - [`build`]: the builder, which works from the deletion's values (the group's pre-state
//!   commitment and post-state, from the `ChangeSet`), the proof and the inclusion data, and signs
//!   with the operator's key for the epoch of issue (§9.8).
//!
//! The verifier (§11.3) is not here: it lives in its own workspace and shares no code with this
//! crate (Build 3-4 §1.6).

#![forbid(unsafe_code)]

mod builder;
mod encoding;

pub use builder::{CertError, Deletion, Removal, build};
pub use encoding::{
    Certificate, GroupFields, InsertInclusion, ParseError, TRAILER, TRAILER_LEN, VERSION,
};

#[cfg(test)]
mod tests;
