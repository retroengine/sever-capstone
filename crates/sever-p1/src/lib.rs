//! `sever-p1`: Part 1's composition root (Build §4.4).
//!
//! It wires the frozen core together as `Index<NoExtension, HmacSha512Scrambler>`, supplies Part 1's
//! only entropy (the scrambling key and the collection ID, from the OS, §9.7, §3.1), loads the demo
//! data, and runs the `sever-demo idea` demonstration (Build §4.9) with its two ghost baselines
//! (P1-T14). Unlike the core crates, this crate may read files and the clock.

pub mod data;
pub mod demo;
pub mod ghost;
pub mod root;

pub use data::{Dataset, DemoError};
pub use demo::{Report, run};
pub use root::{P1Index, new_index};
