//! The verifier on arbitrary bytes (§11.1 parser and every §11.3 step, d = 16, the anchors of
//! golden/p3_attacks.json): never panics.
#![no_main]

use std::sync::OnceLock;

use libfuzzer_sys::fuzz_target;
use sever_verify::{Anchors, Generators, verify};

const ATTACKS: &str = include_str!("../../../golden/p3_attacks.json");

fn setup() -> &'static Option<(Anchors, Generators)> {
    static S: OnceLock<Option<(Anchors, Generators)>> = OnceLock::new();
    S.get_or_init(|| {
        let v: serde_json::Value = serde_json::from_str(ATTACKS).ok()?;
        let a = Anchors::from_json(&v.get("anchors")?.to_string()).ok()?;
        let g = Generators::derive(a.d)?;
        Some((a, g))
    })
}

fuzz_target!(|data: &[u8]| {
    if let Some((a, g)) = setup() {
        let _ = verify(data, a, g);
    }
});
