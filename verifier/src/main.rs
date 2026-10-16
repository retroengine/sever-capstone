//! `sever-verify <certificate> --anchors FILE [--hex]` (spec §16.3, §11.3): verifies one
//! certificate offline. It first runs the §9.2 self-check with its own code and refuses to run on a
//! mismatch. Prints one JSON line; exit 0 accepted, 1 rejected (naming the failed step), 2 usage,
//! 3 self-check or anchors refused.

use std::process::ExitCode;

use serde_json::json;
use sever_verify::{Anchors, GOLDEN_GENERATORS, Generators, hex, self_check, verify};

fn usage(msg: &str) -> ExitCode {
    eprintln!("sever-verify: {msg}");
    eprintln!("usage: sever-verify <certificate> --anchors FILE [--hex]");
    ExitCode::from(2)
}

fn refuse(msg: &str) -> ExitCode {
    println!("{}", json!({"accepted": false, "refused": msg}));
    ExitCode::from(3)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut cert_path = None;
    let mut anchors_path = None;
    let mut hex_input = false;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--anchors" => anchors_path = it.next(),
            "--hex" => hex_input = true,
            s if s.starts_with("--") => return usage(&format!("unknown option {s}")),
            _ if cert_path.is_none() => cert_path = Some(a),
            _ => return usage("one certificate at a time"),
        }
    }
    let (Some(cert_path), Some(anchors_path)) = (cert_path, anchors_path) else {
        return usage("a certificate and --anchors are required");
    };
    let Ok(text) = std::fs::read_to_string(anchors_path) else {
        return usage("cannot read the anchors file");
    };
    let anchors = match Anchors::from_json(&text) {
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
        return refuse("the anchors' gdigest is not this verifier's (§9.6)");
    }
    let Ok(raw) = std::fs::read(cert_path) else {
        return usage("cannot read the certificate");
    };
    let bytes = if hex_input {
        match std::str::from_utf8(&raw).ok().and_then(hex::decode) {
            Some(b) => b,
            None => return usage("--hex: the certificate file is not hex"),
        }
    } else {
        raw
    };
    match verify(&bytes, &anchors, &gens) {
        Ok(a) => {
            println!(
                "{}",
                json!({
                    "accepted": true,
                    "deletion_kind": a.deletion_kind,
                    "database_lsn": a.database_lsn,
                    "leaf_index": a.leaf_index,
                    "group_emptied": a.group_emptied,
                    "collection_id": hex::encode(&a.collection_id),
                })
            );
            ExitCode::SUCCESS
        }
        Err(r) => {
            println!(
                "{}",
                json!({"accepted": false, "step": r.step, "reason": r.reason})
            );
            ExitCode::from(1)
        }
    }
}
