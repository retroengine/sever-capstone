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

/// A campaign interrupted after any saved operation and resumed in a new run writes exactly the
/// results of an uninterrupted one (only the summary's wall-clock seconds may differ). This is
/// what lets a long gate survive WSL being shut down without changing what it measures.
#[test]
fn p2_crashkit_a_resumed_campaign_equals_an_uninterrupted_one() {
    let oracle = Oracle::read(&root().join("golden/p2_oracle_small.jsonl")).unwrap();
    let rows = FixtureRows::read(&root().join("golden/p1_fixture_vectors.json")).unwrap();
    let artefact = std::fs::read(root().join("golden/p1_partition_small.svp")).unwrap();
    let s = Settings {
        limit_ops: Some(120),
        ..settings(5)
    };
    // The uninterrupted run, saving its progress after every operation.
    let mut whole = Vec::new();
    let mut saves: Vec<campaign::Progress> = Vec::new();
    let mut len = 0usize;
    {
        let mut tracked = Tracked(&mut whole, &mut len);
        campaign::run_resumable(
            &oracle,
            &rows,
            &artefact,
            &s,
            &mut tracked,
            campaign::Checkpointing {
                from: None,
                every: std::time::Duration::ZERO,
                save: &mut |p, _| {
                    saves.push(p.clone());
                    Ok(())
                },
            },
        )
        .unwrap();
    }
    // Each save's results end after one line per crash point so far.
    let lines: Vec<&[u8]> = whole.split_inclusive(|&b| b == b'\n').collect();
    let crash_lines = |p: &campaign::Progress| (p.sum.step + p.sum.offset + p.sum.random) as usize;
    let without_seconds = |b: &[u8]| {
        let mut v: Vec<serde_json::Value> = b
            .split(|&c| c == b'\n')
            .filter(|l| !l.is_empty())
            .map(|l| serde_json::from_slice(l).unwrap())
            .collect();
        if let Some(last) = v.last_mut() {
            last.as_object_mut().unwrap().remove("seconds");
        }
        v
    };
    assert!(saves.len() >= 100, "{} saves", saves.len());
    for p in saves.iter().step_by(17) {
        let kept: Vec<u8> = lines[..crash_lines(p)].concat();
        let mut resumed = kept.clone();
        campaign::run_resumable(
            &oracle,
            &rows,
            &artefact,
            &s,
            &mut resumed,
            campaign::Checkpointing {
                from: Some(p.clone()),
                every: std::time::Duration::from_secs(3600),
                save: &mut |_, _| Ok(()),
            },
        )
        .unwrap();
        assert_eq!(
            without_seconds(&resumed),
            without_seconds(&whole),
            "resumed after operation {}",
            p.done
        );
    }
    let _ = len;
}

/// A writer that also counts its bytes.
struct Tracked<'a>(&'a mut Vec<u8>, &'a mut usize);
impl std::io::Write for Tracked<'_> {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        *self.1 += b.len();
        self.0.extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
