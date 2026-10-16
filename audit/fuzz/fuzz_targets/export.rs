//! The auditor on arbitrary exports (the anchors of golden/p3_audit.json): never panics.
#![no_main]

use std::sync::OnceLock;

use libfuzzer_sys::fuzz_target;
use sever_audit::{Anchors, Export, Generators, audit};

const AUDIT: &str = include_str!("../../../golden/p3_audit.json");

fn setup() -> &'static Option<(Anchors, Generators)> {
    static S: OnceLock<Option<(Anchors, Generators)>> = OnceLock::new();
    S.get_or_init(|| {
        let v: serde_json::Value = serde_json::from_str(AUDIT).ok()?;
        let a = Anchors::from_json(&v.get("anchors")?.to_string()).ok()?;
        let g = Generators::derive(a.d)?;
        Some((a, g))
    })
}

fuzz_target!(|data: &[u8]| {
    let (Some((a, g)), Ok(text)) = (setup(), std::str::from_utf8(data)) else {
        return;
    };
    if let Ok(e) = Export::from_json(text) {
        let _ = audit(&e, a, g, &[]);
    }
});
