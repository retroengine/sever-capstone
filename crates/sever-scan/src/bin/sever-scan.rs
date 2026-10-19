//! `sever-scan IMAGE --targets FILE [--chunk-mib N]`: the forensic scanner (spec §16.3, overview
//! EX-2). Prints one JSON report; exit 0 with no findings, 1 with findings, 2 on a usage error.

use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let value = |k: &str| {
        args.iter()
            .position(|a| a == k)
            .and_then(|i| args.get(i + 1))
    };
    let (Some(image), Some(targets)) = (args.first(), value("--targets")) else {
        eprintln!("usage: sever-scan IMAGE --targets FILE [--chunk-mib N]");
        return ExitCode::from(2);
    };
    let chunk = value("--chunk-mib")
        .and_then(|c| c.parse::<usize>().ok())
        .unwrap_or(256)
        << 20;
    let Some(t) = std::fs::read_to_string(targets)
        .ok()
        .and_then(|s| sever_scan::parse_targets(&s))
    else {
        eprintln!("sever-scan: unreadable targets file");
        return ExitCode::from(2);
    };
    match sever_scan::scan_file(&PathBuf::from(image), t, chunk) {
        Ok(r) => {
            println!("{}", r.to_json());
            if r.findings.is_empty() {
                ExitCode::SUCCESS
            } else {
                ExitCode::from(1)
            }
        }
        Err(e) => {
            eprintln!("sever-scan: {e}");
            ExitCode::from(2)
        }
    }
}
