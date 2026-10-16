//! `sever-audit <export> --anchors FILE [--certificate FILE]…` (spec §16.3; DB-86): audits a log
//! export, with the certificates users hold. Runs the §9.2 self-check first. Prints one JSON line;
//! exit 0 nothing found, 1 findings, 2 usage, 3 self-check, anchors or export refused.

use std::process::ExitCode;

use serde_json::json;
use sever_audit::{Anchors, Export, GOLDEN_GENERATORS, Generators, audit, self_check};

fn usage(msg: &str) -> ExitCode {
    eprintln!("sever-audit: {msg}");
    eprintln!("usage: sever-audit <export> --anchors FILE [--certificate FILE]...");
    ExitCode::from(2)
}

fn refuse(msg: &str) -> ExitCode {
    println!("{}", json!({"refused": msg}));
    ExitCode::from(3)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (mut export_path, mut anchors_path, mut held) = (None, None, Vec::new());
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--anchors" => anchors_path = it.next(),
            "--certificate" => match it.next() {
                Some(p) => held.push(p),
                None => return usage("--certificate needs a file"),
            },
            s if s.starts_with("--") => return usage(&format!("unknown option {s}")),
            _ if export_path.is_none() => export_path = Some(a),
            _ => return usage("one export at a time"),
        }
    }
    let (Some(export_path), Some(anchors_path)) = (export_path, anchors_path) else {
        return usage("an export and --anchors are required");
    };
    let (Ok(e), Ok(a)) = (
        std::fs::read_to_string(export_path),
        std::fs::read_to_string(anchors_path),
    ) else {
        return usage("cannot read the export or the anchors");
    };
    let anchors = match Anchors::from_json(&a) {
        Ok(a) => a,
        Err(e) => return refuse(e.0),
    };
    let Some(gens) = Generators::derive(anchors.d) else {
        return refuse("cannot derive the generators");
    };
    if let Err(e) = self_check(&gens, GOLDEN_GENERATORS) {
        return refuse(e.0);
    }
    if anchors.gdigest.is_some_and(|g| g != gens.gdigest) {
        return refuse("the anchors' gdigest is not this auditor's (§9.6)");
    }
    let export = match Export::from_json(&e) {
        Ok(x) => x,
        Err(e) => return refuse(e),
    };
    let mut certs = Vec::new();
    for p in held {
        match std::fs::read(p) {
            Ok(b) => certs.push(b),
            Err(_) => return usage("cannot read a certificate"),
        }
    }
    let found = audit(&export, &anchors, &gens, &certs);
    println!(
        "{}",
        json!({
            "leaves": export.leaves.len(),
            "checkpoints": export.checkpoints.len(),
            "findings": found
                .iter()
                .map(|f| json!({"kind": f.kind, "at": f.at, "why": f.why}))
                .collect::<Vec<_>>(),
        })
    );
    if found.is_empty() {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}
