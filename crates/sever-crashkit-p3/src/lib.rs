//! `sever-crashkit-p3`: the Part 3 gate kit (Build 3-4 §1.8–1.9). Test tooling: it reads files and
//! drives the Part 3 engine on `SimVfs`; it is never linked into the engine.
//!
//! - [`replay`]: P3-T5, Part 1's frozen traces through the Part 3 engine, with the five-field
//!   equivalence and the certificate arithmetic checked against a model of the commitments.
//! - [`campaign`]: P3-T4, Part 2's oracle stream with a crash at every VFS operation, checking the
//!   log and the certificates after every recovery; [`snap`] takes its crash points from the main
//!   line's own execution (DB-88).
//! - [`attacks`]: P3-T1/T2, honest certificates and the register's attacks on each, written for
//!   the independent verifier to judge.
//! - [`measure`]: P3-T13, proof time, verification time and certificate size.

pub mod attacks;
pub mod campaign;
pub mod check;
pub mod core;
pub mod measure;
pub mod replay;
pub mod snap;
pub mod world;
