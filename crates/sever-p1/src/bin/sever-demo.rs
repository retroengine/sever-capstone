//! `sever-demo idea --data nq-10k|nq-100k|synthetic [--seed N] [--root DIR] [--json PATH]`
//! (Build §4.9). Prints the demo as tables and writes the whole run as JSON (default
//! `artefacts/demo/idea-<data>-seed<seed>.json`), which `sever_demo` renders as a report.

use std::path::PathBuf;
use std::process::ExitCode;

use sever_p1::data::{load_nq, load_synthetic};
use sever_p1::{DemoError, Report, run};

const USAGE: &str =
    "usage: sever-demo idea --data nq-10k|nq-100k|synthetic [--seed N] [--root DIR] [--json PATH]";

struct Args {
    data: String,
    seed: u64,
    root: PathBuf,
    json: Option<PathBuf>,
}

fn parse(mut it: impl Iterator<Item = String>) -> Result<Args, String> {
    if it.next().as_deref() != Some("idea") {
        return Err(USAGE.to_owned());
    }
    let mut a = Args {
        data: "nq-10k".to_owned(),
        seed: 42,
        root: PathBuf::from("."),
        json: None,
    };
    while let Some(flag) = it.next() {
        let mut val = || {
            it.next()
                .ok_or_else(|| format!("{flag} needs a value\n{USAGE}"))
        };
        match flag.as_str() {
            "--data" => a.data = val()?,
            "--seed" => a.seed = val()?.parse().map_err(|_| "--seed must be an integer")?,
            "--root" => a.root = PathBuf::from(val()?),
            "--json" => a.json = Some(PathBuf::from(val()?)),
            _ => return Err(format!("unknown flag {flag}\n{USAGE}")),
        }
    }
    Ok(a)
}

fn short(h: &str) -> String {
    match (h.get(..4), h.get(h.len().saturating_sub(4)..)) {
        (Some(a), Some(b)) if h.len() > 8 => format!("{a}…{b}"),
        _ => h.to_owned(),
    }
}

fn mark(ok: bool) -> &'static str {
    if ok { "✓" } else { "✗" }
}

fn print(r: &Report) {
    let b = &r.build;
    println!(
        "SEVER-DB · Part 1, The Idea · data {} · seed {} · d = {}",
        r.data, r.seed, r.d
    );
    println!(
        "partition artefact sha256 {} · spawn size {} · stream {}",
        short(&r.artefact_sha256),
        r.spawn_target,
        r.stream_order
    );
    println!();
    println!("1. Build");
    println!(
        "   {} records streamed, {} accepted in {:.1} s{}",
        b.records,
        b.accepted,
        b.seconds,
        if b.rejected.is_empty() {
            String::new()
        } else {
            format!(", rejected {:?}", b.rejected)
        }
    );
    println!(
        "   groups: {} frozen + {} spawned = k {} · N {} · holding area {} · out of distribution {} ({:.2} %)",
        b.frozen,
        b.spawned,
        b.k,
        b.big_n,
        b.holding,
        b.out_of_distribution,
        100.0 * b.ood_rate
    );
    println!();
    println!(
        "2. Target: cohort {:?} ({} records), in {}",
        r.target.cohort,
        r.target.record_ids.len(),
        r.target.groups.join(", ")
    );
    println!("   records: {}", r.target.record_ids.join(", "));
    println!();
    println!("3–5. Before and after one delete_user");
    println!(
        "   {:<24} {:>8} {:>7}  {:<11} {:<11} {:<11} {:<15} exact",
        "group", "n_before", "n_after", "S before", "S after", "blob after", "survivors-only"
    );
    for g in &r.groups {
        println!(
            "   {:<24} {:>8} {:>7}  {:<11} {:<11} {:<11} {:<15} {}",
            g.group,
            g.n_before,
            g.n_after,
            short(&g.s_sha_before),
            short(&g.s_sha_after),
            short(&g.blob_sha_after),
            short(&g.survivors_blob_sha),
            mark(g.exact)
        );
    }
    if r.holding.cohort_members > 0 {
        println!(
            "   {:<24} {:>8} {:>7}  (no accumulator: {} record(s) excised, no sum changed)",
            "holding", r.holding.n_before, r.holding.n_after, r.holding.cohort_members
        );
    }
    println!(
        "   N {} → {} · outcomes: {}",
        r.big_n[0],
        r.big_n[1],
        r.outcomes.join("; ")
    );
    println!(
        "   untouched groups unchanged: {}/{} {} · second delete: already absent {} , state unchanged {}",
        r.untouched.unchanged,
        r.untouched.groups,
        mark(r.untouched.unchanged == r.untouched.groups),
        mark(r.second_delete.all_already_absent),
        mark(r.second_delete.state_unchanged)
    );
    println!();
    println!("6. The ghost (P1-T14, measured)");
    println!(
        "   {:<20} {:<30} summary distance from survivors-only",
        "system", "deleted record still stored"
    );
    for s in &r.ghost.summary {
        println!(
            "   {:<20} {:<30} {:.3e}  ({})",
            s.system,
            if s.deleted_record_still_stored {
                "yes"
            } else {
                "no"
            },
            s.distance,
            s.measure
        );
    }
    println!();
    println!("7. Search (top {})", r.search.k);
    println!(
        "   {} real queries; {} returned a cohort record before; searches returning a deleted record after: {} {}",
        r.search.queries,
        r.search.queries_hit_before,
        r.search.deleted_returned_after,
        mark(r.search.deleted_returned_after == 0)
    );
    if let Some(ex) = &r.search.example {
        let fmt = |v: &[(String, f32)]| {
            v.iter()
                .take(3)
                .map(|(id, _)| id.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        };
        println!(
            "   {}: before, {} at rank {} (top 3: {})",
            ex.query,
            ex.deleted_record,
            ex.rank_before,
            fmt(&ex.before)
        );
        println!("   {}: after, top 3: {}", ex.query, fmt(&ex.after));
    }
    println!();
    println!("invariants INV-4 … INV-9: {}", r.invariants);
}

fn main() -> ExitCode {
    let args = match parse(std::env::args().skip(1)) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    let result = (|| -> Result<Report, DemoError> {
        let ds = if args.data == "synthetic" {
            load_synthetic(&args.root)?
        } else {
            load_nq(&args.root, &args.data, args.seed)?
        };
        run(&ds)
    })();
    let report = match result {
        Ok(r) => r,
        Err(e) => {
            eprintln!("sever-demo: {e}");
            return ExitCode::from(1);
        }
    };
    print(&report);
    let path = args.json.unwrap_or_else(|| {
        args.root.join(format!(
            "artefacts/demo/idea-{}-seed{}.json",
            report.data, report.seed
        ))
    });
    let written = path
        .parent()
        .map_or(Ok(()), std::fs::create_dir_all)
        .and_then(|()| {
            serde_json::to_vec_pretty(&report)
                .map_err(std::io::Error::other)
                .and_then(|j| std::fs::write(&path, j))
        });
    match written {
        Ok(()) => println!("report: {}", path.display()),
        Err(e) => {
            eprintln!("sever-demo: writing {}: {e}", path.display());
            return ExitCode::from(1);
        }
    }
    let ok = report.groups.iter().all(|g| g.exact)
        && report.search.deleted_returned_after == 0
        && report.untouched.unchanged == report.untouched.groups
        && report.second_delete.all_already_absent
        && report.second_delete.state_unchanged
        && report.invariants == "ok";
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}
