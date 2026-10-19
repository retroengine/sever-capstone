//! The `sever-verify` command line (spec §16.3), run as a program on the golden d = 16
//! certificates of `golden/p3_attacks.json` (B-shared, `sever_refmodel_certs`): the exit codes
//! and output its header promises (0 accepted, 1 rejected naming the step, 2 usage, 3 refused),
//! `--hex`, `--explain` and `--batch`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use std::path::{Path, PathBuf};
use std::process::{Command, Output};

const ATTACKS: &str = include_str!("../../golden/p3_attacks.json");

fn golden() -> serde_json::Value {
    serde_json::from_str(ATTACKS).unwrap()
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

fn dir(name: &str) -> PathBuf {
    let d = PathBuf::from(env!("CARGO_TARGET_TMPDIR")).join(name);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn file(d: &Path, name: &str, bytes: &[u8]) -> String {
    let p = d.join(name);
    std::fs::write(&p, bytes).unwrap();
    p.to_string_lossy().into_owned()
}

fn run(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_sever-verify"))
        .args(args)
        .output()
        .unwrap()
}

fn out(o: &Output) -> String {
    String::from_utf8_lossy(&o.stdout).into_owned()
}

#[test]
fn p3_verify_cli_accepts_and_rejects_with_its_exit_codes() {
    let g = golden();
    let d = dir("cli-single");
    let anchors = file(&d, "anchors.json", g["anchors"].to_string().as_bytes());
    let group = file(
        &d,
        "group.bin",
        &unhex(g["honest"]["group"].as_str().unwrap()),
    );
    let holding_hex = file(
        &d,
        "holding.hex",
        g["honest"]["holding"].as_str().unwrap().as_bytes(),
    );
    let attack = &g["attacks"][0];
    let bad = file(
        &d,
        "attack.bin",
        &unhex(attack["certificate"].as_str().unwrap()),
    );

    let o = run(&[&group, "--anchors", &anchors]);
    assert_eq!(o.status.code(), Some(0), "{}", out(&o));
    assert!(out(&o).contains("\"accepted\":true"));

    let o = run(&[&holding_hex, "--anchors", &anchors, "--hex"]);
    assert_eq!(o.status.code(), Some(0), "{}", out(&o));

    let o = run(&[&group, "--anchors", &anchors, "--explain"]);
    assert_eq!(o.status.code(), Some(0));
    assert!(out(&o).contains("ACCEPT") && out(&o).contains("step 1"));

    let o = run(&[&bad, "--anchors", &anchors]);
    assert_eq!(o.status.code(), Some(1), "{}", out(&o));
    let v: serde_json::Value = serde_json::from_str(out(&o).trim()).unwrap();
    assert_eq!(v["accepted"], false);
    assert_eq!(v["step"], attack["model_step"]);

    let o = run(&[&bad, "--anchors", &anchors, "--explain"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(out(&o).contains("REJECT (step"));
}

#[test]
fn p3_verify_cli_batch_gives_one_verdict_per_line() {
    let g = golden();
    let d = dir("cli-batch");
    let mut lines = vec![g["anchors"].to_string()];
    lines.push(serde_json::json!({"cert": g["honest"]["group"], "kind": "honest"}).to_string());
    for a in g["attacks"].as_array().unwrap().iter().take(5) {
        lines.push(serde_json::json!({"cert": a["certificate"], "kind": a["id"]}).to_string());
    }
    let batch = file(&d, "batch.jsonl", lines.join("\n").as_bytes());
    let o = run(&["--batch", &batch]);
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    let verdicts: Vec<serde_json::Value> = out(&o)
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert_eq!(verdicts.len(), 6);
    assert_eq!(verdicts[0]["accepted"], true);
    assert_eq!(verdicts[0]["kind"], "honest");
    assert!(verdicts[1..].iter().all(|v| v["accepted"] == false));

    for (name, body) in [
        ("empty.jsonl", String::new()),
        ("notjson.jsonl", format!("{}\nnot json", lines[0])),
        ("nocert.jsonl", format!("{}\n{{\"kind\": 1}}", lines[0])),
        ("array.jsonl", format!("{}\n[1, 2]", lines[0])),
    ] {
        let o = run(&["--batch", &file(&d, name, body.as_bytes())]);
        assert_eq!(o.status.code(), Some(2), "{name}");
    }
    let o = run(&["--batch", &file(&d, "badanchors.jsonl", b"{\"d\": 16}\n")]);
    assert_eq!(o.status.code(), Some(3));
    let o = run(&["--batch", "/nonexistent/batch.jsonl"]);
    assert_eq!(o.status.code(), Some(2));
}

#[test]
fn p3_verify_cli_usage_and_refusals() {
    let g = golden();
    let d = dir("cli-usage");
    let anchors = file(&d, "anchors.json", g["anchors"].to_string().as_bytes());
    let group = file(
        &d,
        "group.bin",
        &unhex(g["honest"]["group"].as_str().unwrap()),
    );
    for args in [
        vec![],
        vec![group.as_str()],
        vec![
            group.as_str(),
            "--anchors",
            anchors.as_str(),
            "--frobnicate",
        ],
        vec![
            group.as_str(),
            group.as_str(),
            "--anchors",
            anchors.as_str(),
        ],
        vec!["/nonexistent", "--anchors", anchors.as_str()],
        vec![group.as_str(), "--anchors", "/nonexistent"],
        vec![group.as_str(), "--anchors", anchors.as_str(), "--hex"],
    ] {
        assert_eq!(run(&args).status.code(), Some(2), "{args:?}");
    }
    let bad = file(&d, "bad.json", b"{\"d\": 16}");
    assert_eq!(run(&[&group, "--anchors", &bad]).status.code(), Some(3));
    let mut a = g["anchors"].clone();
    a["gdigest"] = serde_json::Value::String("00".repeat(64));
    let wrong = file(&d, "wrong-gdigest.json", a.to_string().as_bytes());
    assert_eq!(run(&[&group, "--anchors", &wrong]).status.code(), Some(3));
    let mut a = g["anchors"].clone();
    a["d"] = serde_json::Value::from(0);
    let zero = file(&d, "zero-d.json", a.to_string().as_bytes());
    assert_eq!(run(&[&group, "--anchors", &zero]).status.code(), Some(3));
}
