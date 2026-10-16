//! The `sever-db-p3` binary end to end on real files (ext4, under `target/`): a user key, a
//! collection, inserts, a deletion with its certificate, the certificate read back, the anchors.

// Test code (clippy.toml allows these in #[test] functions; the helpers here are test code too).
#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::expect_used,
    clippy::panic
)]

use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

fn dir() -> PathBuf {
    let d = Path::new(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../target/p3-tests"
    ))
    .join(format!("cli-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn run(d: &Path, args: &[&str]) -> (i32, Value) {
    let data = d.join("data");
    let keys = d.join("keys");
    let mut all = vec![
        args[0],
        "--data",
        data.to_str().unwrap(),
        "--keys",
        keys.to_str().unwrap(),
        "--d",
        "16",
    ];
    all.extend_from_slice(&args[1..]);
    let out = Command::new(env!("CARGO_BIN_EXE_sever-db-p3"))
        .args(&all)
        .output()
        .unwrap();
    let text = String::from_utf8(out.stdout).unwrap();
    (
        out.status.code().unwrap_or(-1),
        serde_json::from_str(text.trim()).unwrap_or(Value::Null),
    )
}

fn vectors() -> Vec<String> {
    let doc: Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc["ref"]
        .as_array()
        .unwrap()
        .iter()
        .take(3)
        .map(|h| {
            let h = h.as_str().unwrap();
            let v: Vec<f32> = (0..h.len() / 8)
                .map(|i| {
                    let b: Vec<u8> = (0..4)
                        .map(|j| {
                            u8::from_str_radix(&h[8 * i + 2 * j..8 * i + 2 * j + 2], 16).unwrap()
                        })
                        .collect();
                    f32::from_le_bytes(b.try_into().unwrap())
                })
                .collect();
            serde_json::to_string(&v).unwrap()
        })
        .collect()
}

#[test]
fn p3_cli_insert_delete_and_read_the_certificate_back() {
    let d = dir();
    let key = d.join("user.key");
    let out = Command::new(env!("CARGO_BIN_EXE_sever-db-p3"))
        .args(["user-key", "--out", key.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(out.status.success());
    let art = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../golden/p1_partition_small.svp"
    );
    let (code, v) = run(&d, &["create", "--artefact", art, "--spawn-target", "8"]);
    assert_eq!(code, 0, "{v}");
    let cid = v["cid"].as_str().unwrap().to_owned();
    for (i, vec) in vectors().iter().enumerate() {
        let (code, v) = run(
            &d,
            &[
                "insert",
                "--cid",
                &cid,
                "--id",
                &format!("r{i}"),
                "--vector",
                vec,
                "--user-key",
                key.to_str().unwrap(),
            ],
        );
        assert_eq!(code, 0, "{v}");
        assert_eq!(v["database_lsn"], i as u64);
    }
    let (code, v) = run(&d, &["delete", "--cid", &cid, "--id", "r1"]);
    assert_eq!(code, 0, "{v}");
    assert_eq!(v["outcome"], "deleted");
    assert_eq!(v["database_lsn"], 3);
    let cert = v["certificate"].as_str().unwrap().to_owned();
    let (_, v) = run(&d, &["certificate", "--lsn", "3"]);
    assert_eq!(
        v["certificate"].as_str(),
        Some(cert.as_str()),
        "retrievable by database_lsn"
    );
    let (_, v) = run(&d, &["delete", "--cid", &cid, "--id", "r1"]);
    assert_eq!(v["outcome"], "absent");
    let (_, v) = run(&d, &["anchors"]);
    assert_eq!(v["d"], 16);
    assert!(v["operator"]["0"].is_string());
    assert_eq!(v["witnesses"].as_array().unwrap().len(), 5);
    let (code, v) = run(&d, &["delete", "--cid", "00", "--id", "r0"]);
    assert_eq!(code, 2, "a usage error: {v}");
    let (code, v) = run(&d, &["delete", "--cid", &"0".repeat(32), "--id", "r0"]);
    assert_eq!((code, v["error"].as_str()), (1, Some("UnknownCollection")));
    let _ = std::fs::remove_dir_all(&d);
}
