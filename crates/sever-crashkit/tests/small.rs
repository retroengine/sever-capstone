//! The crash campaign on the small fixture against the Python oracle's golden file
//! (`golden/p2_oracle_small.jsonl`): engine digests equal the model's, byte for byte, at every
//! operation, and every crash point recovers to an allowed state (Build §5.7 L10, fast form).

#![allow(clippy::unwrap_used)]

use std::path::Path;

use sever_crashkit::Oracle;
use sever_crashkit::campaign::{self, Settings};
use sever_crashkit::rows::FixtureRows;
use sever_spec::spec;

fn root() -> &'static Path {
    Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/../.."))
}

fn settings(step_every: usize) -> Settings {
    Settings {
        checkpoint_every: 64 * 1024,
        wal_segment: 32 * 1024,
        store_segment: 8 * 1024,
        spawn_target: 8,
        offset_samples: 10,
        random_points: 50,
        double_every: 9,
        seed: 42,
        step_every,
        limit_ops: None,
    }
}

#[test]
#[spec(
    "SR-12.3-2",
    "SR-12.3-3",
    "SR-15.7-1",
    "SR-15.1-2",
    "SR-15.4-1",
    "SR-12.4-2"
)]
fn p2_crashkit_small_campaign_against_the_python_oracle() {
    let oracle = Oracle::read(&root().join("golden/p2_oracle_small.jsonl")).unwrap();
    let rows = FixtureRows::read(&root().join("golden/p1_fixture_vectors.json")).unwrap();
    let artefact = std::fs::read(root().join("golden/p1_partition_small.svp")).unwrap();
    let mut out = Vec::new();
    let s = campaign::run(&oracle, &rows, &artefact, &settings(7), &mut out).unwrap();
    assert_eq!(s.ops, 400);
    assert!(
        s.step > 200 && s.offset > 0 && s.random == 50 && s.double > 10,
        "{s:?}"
    );
    assert_eq!(s.failures(), 0, "{s:?}");
}
