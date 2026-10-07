//! `sever-crashkit`: the crash campaign of overview EX-1 on `SimVfs` (Part 2, Build §5.7 L10).
//!
//! 1. **Generic records first** ([`generic`]): a key–value store on the WAL and a snapshot file,
//!    with no index code, so a durability bug has one home.
//! 2. **Index records** ([`campaign`]): the oracle stream (`sever_refmodel_durable`) through the
//!    engine, with a crash at every VFS operation of every operation (every protocol step
//!    boundary lies between two of them), at every 512-byte offset of sampled large writes, at
//!    random points, and during recovery itself.
//! 3. After each crash: recover (the full invariant check runs at open), compare the recovered
//!    state's digest with the oracle's two allowed states, and retry the operation in flight.
//!
//! This is test tooling: it reads files, and it is never linked into the engine.

pub mod campaign;
pub mod generic;
pub mod oracle;
pub mod rows;

pub use oracle::{Oracle, OracleOp, state_digest};
