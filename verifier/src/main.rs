//! `sever-verify <certificate> --anchors FILE [--hex] [--explain]` (spec §16.3, §11.3): verifies
//! one certificate offline. It first runs the §9.2 self-check with its own code and refuses to run
//! on a mismatch. Prints one JSON line, or with `--explain` each §11.3 step and ACCEPT or REJECT;
//! exit 0 accepted, 1 rejected (naming the failed step), 2 usage, 3 self-check or anchors refused.

use std::process::ExitCode;

use serde_json::json;
use sever_verify::{Anchors, GOLDEN_GENERATORS, Generators, hex, self_check, verify};

fn usage(msg: &str) -> ExitCode {
    eprintln!("sever-verify: {msg}");
    eprintln!("usage: sever-verify <certificate> --anchors FILE [--hex] [--explain]");
    ExitCode::from(2)
}

fn refuse(msg: &str) -> ExitCode {
    println!("{}", json!({"accepted": false, "refused": msg}));
    ExitCode::from(3)
}

/// The §11.3 steps, as `--explain` prints them.
const STEPS: [&str; 8] = [
    "parse strictly; every point and scalar canonical; C_t is not the identity",
    "operator signature, with the key of tag 8's epoch",
    "insert leaf matches tags 13, 9, 1, 5; user signature; inclusion path; checkpoint signature",
    "at least four cosignatures from distinct witnesses",
    "database_lsn is after the insert leaf",
    "from a group: C_S_post + C_t = C_S_pre; proof of knowledge; group emptied iff C_S_post = 0",
    "from the holding area: tags 2, 3, 4 empty and tag 11 = 0",
    "every step passed",
];

/// `--explain`: each step with its result, then the verdict.
fn explain(kind: Option<u8>, failed: Option<(u8, &str)>) {
    for (i, name) in STEPS.iter().enumerate() {
        let step = u8::try_from(i + 1).unwrap_or(u8::MAX);
        let status = match failed {
            Some((f, why)) if f == step => format!("FAILED: {why}"),
            Some((f, _)) if step > f => "not reached".to_owned(),
            _ if step == 6 && kind == Some(1) => "n/a (holding area)".to_owned(),
            _ if step == 7 && kind == Some(0) => "n/a (group)".to_owned(),
            Some(_) if step == 8 => "no".to_owned(),
            _ => "ok".to_owned(),
        };
        println!("step {step}  {name:<92} {status}");
    }
    match failed {
        None => println!("ACCEPT"),
        Some((f, why)) => println!("REJECT (step {f}: {why})"),
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut cert_path = None;
    let mut anchors_path = None;
    let mut hex_input = false;
    let mut explain_steps = false;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--anchors" => anchors_path = it.next(),
            "--hex" => hex_input = true,
            "--explain" => explain_steps = true,
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
    let result = verify(&bytes, &anchors, &gens);
    if explain_steps {
        match &result {
            Ok(a) => explain(Some(a.deletion_kind), None),
            Err(r) => explain(None, Some((r.step, r.reason))),
        }
        return if result.is_ok() {
            ExitCode::SUCCESS
        } else {
            ExitCode::from(1)
        };
    }
    match result {
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
