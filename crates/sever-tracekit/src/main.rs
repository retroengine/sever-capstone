//! `sever-tracekit replay <trace.jsonl>... [--root DIR]`: replays traces written by the reference
//! model and prints one JSON summary line per trace. Exit status 1 on any mismatch (gate P1-T2) or
//! any deleted record returned by search (gate P1-T5).

use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    if args.next().as_deref() != Some("replay") {
        eprintln!("usage: sever-tracekit replay <trace.jsonl>... [--root DIR]");
        return ExitCode::from(2);
    }
    let mut root = PathBuf::from(".");
    let mut traces = Vec::new();
    while let Some(a) = args.next() {
        if a == "--root" {
            root = args.next().map(PathBuf::from).unwrap_or(root);
        } else {
            traces.push(PathBuf::from(a));
        }
    }
    let mut ok = true;
    for t in traces {
        let start = std::time::Instant::now();
        match sever_tracekit::replay(&t, &root) {
            Ok(r) => {
                let pass = r.mismatches == 0 && r.deleted_returned == 0;
                ok &= pass;
                println!(
                    "{{\"trace\":\"{}\",\"ops\":{},\"compared\":{},\"mismatches\":{},\"deleted_returned\":{},\"seconds\":{:.1},\"result\":\"{}\"}}",
                    t.display(),
                    r.ops,
                    r.compared,
                    r.mismatches,
                    r.deleted_returned,
                    start.elapsed().as_secs_f64(),
                    if pass { "PASS" } else { "FAIL" }
                );
                for m in r.first {
                    eprintln!("  mismatch: {m}");
                }
            }
            Err(e) => {
                ok = false;
                eprintln!("{}: {}", t.display(), e.0);
            }
        }
    }
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}
