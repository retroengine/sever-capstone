#!/usr/bin/env python3
"""Live progress of the Part 3 gate runs. Read-only: it only reads the gates' output files.

Run in a WSL terminal:  python3 scripts/ops/progress.py      (Ctrl-C to quit; refreshes every 30 s)
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path.home() / "sever-db"
SEEDS = [42, 123, 777, 2024, 9999]
# Relative cost of one operation of the crash campaign, measured on 17 Oct (an insert's crash
# points are the cheapest; a deletion's cost about three times as much).
WEIGHT = {"i": 1.0, "d": 3.0, "x": 1.5}
REFRESH = 30

_weights: dict[int, list[float]] = {}


def bar(frac: float, width: int = 32) -> str:
    frac = max(0.0, min(1.0, frac))
    full = int(frac * width)
    part = " ▏▎▍▌▋▊▉"[int((frac * width - full) * 8)] if full < width else ""
    return "█" * full + part + " " * (width - full - len(part))


def hms(secs: float) -> str:
    secs = int(max(0, secs))
    return f"{secs // 3600}h{secs % 3600 // 60:02d}m"


def cumulative(seed: int) -> list[float]:
    """Cumulative cost after each operation of the seed's oracle stream."""
    if seed not in _weights:
        acc, out = 0.0, [0.0]
        with open(ROOT / f"traces/p2-oracle-nq-10k-seed{seed}.jsonl") as f:
            next(f)
            for line in f:
                acc += WEIGHT.get(json.loads(line).get("t", "i"), 1.0)
                out.append(acc)
        _weights[seed] = out
    return _weights[seed]


def last_op(path: Path) -> tuple[int | None, bool]:
    """The last operation a results file reached, and whether it holds the summary line."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read().decode(errors="replace")
    except OSError:
        return None, False
    if '"t":"summary"' in tail:
        return None, True
    ops = re.findall(r'"op":(\d+)', tail)
    return (int(ops[-1]) if ops else 0), False


def procs() -> list[tuple[int, str, int]]:
    """(pid, command line, seconds of run time) of every gate-kit process."""
    out = []
    try:
        pids = subprocess.run(
            ["pgrep", "-x", "sever-crashkit-"], capture_output=True, text=True
        ).stdout.split()
    except OSError:
        return out
    for p in pids:
        try:
            cmd = Path(f"/proc/{p}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            et = subprocess.run(
                ["ps", "-o", "etimes=", "-p", p], capture_output=True, text=True
            ).stdout.strip()
            out.append((int(p), cmd, int(et or 0)))
        except (OSError, ValueError):
            continue
    return out


def replay_pos(pid: int) -> tuple[int | None, float]:
    """The seed a replay process reads and how far through its trace it is (by bytes)."""
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            t = os.readlink(f"/proc/{pid}/fd/{fd}")
            m = re.search(r"p1-nq-100k-seed(\d+)\.jsonl$", t)
            if m:
                pos = int(
                    re.search(r"pos:\s*(\d+)", Path(f"/proc/{pid}/fdinfo/{fd}").read_text()).group(
                        1
                    )
                )
                return int(m.group(1)), pos / os.path.getsize(t)
    except (OSError, AttributeError):
        pass
    return None, 0.0


def gate_done(log: str) -> str | None:
    try:
        text = (ROOT / "traces" / log).read_text()
    except OSError:
        return None
    m = re.search(r"^rc=(\d+)", text, re.M)
    return None if not m else ("PASS" if m.group(1) == "0" else f"FAIL (rc={m.group(1)})")


def render() -> str:
    ps = procs()
    lines = [
        f"SEVER-DB Part 3 gate runs   {time.strftime('%H:%M:%S')}"
        f"   (refresh {REFRESH} s, Ctrl-C quits)",
        "",
    ]

    # Crash campaign (P3-T4).
    crash_rc = gate_done("gate-p3-crash.log")
    camp = [p for p in ps if " campaign " in p[1]]
    run_secs = max((p[2] for p in camp), default=0)
    lines.append(f"Crash campaign P3-T4 (5 seeds x 20,000 operations)   {crash_rc or 'running'}")
    fracs = []
    for s in SEEDS:
        op, done = last_op(ROOT / f"traces/p3-crash-nq-10k-seed{s}.jsonl")
        w = cumulative(s)
        f = 1.0 if done else (w[min(op or 0, len(w) - 1)] / w[-1])
        fracs.append(f)
        what = "done" if done else f"op {op or 0:>6,} / {len(w) - 1:,}"
        lines.append(f"  seed {s:<5} {bar(f)} {f * 100:5.1f}%  {what}")
    total = sum(fracs) / len(fracs)
    slowest = min(fracs)
    eta = run_secs * (1 - slowest) / slowest if slowest > 0.01 and not crash_rc else 0
    lines.append(f"  overall   {bar(total)} {total * 100:5.1f}%  (weighted by cost per operation)")
    if not crash_rc:
        lines.append(
            f"  running {hms(run_secs)}; slowest seed needs about {hms(eta)} more (estimate)"
        )
    lines.append("")

    # Trace replay (P3-T5).
    replay_rc = gate_done("gate-p3-replay.log")
    lines.append(f"Trace replay P3-T5 (5 seeds of nq-100k, 2 at a time)   {replay_rc or 'running'}")
    running = {}
    for pid, cmd, et in ps:
        if " replay " in cmd:
            seed, f = replay_pos(pid)
            if seed is not None:
                state = Path(f"/proc/{pid}/stat").read_text().split()[2]
                running[seed] = (f, et, state == "T")
    rfr = []
    for s in SEEDS:
        out = ROOT / f"traces/p3-replay-nq-100k-seed{s}-plain.json"
        if s in running:
            f, et, paused = running[s]
            rfr.append(f)
            note = f"running {hms(et)}" + ("  PAUSED (memory guard)" if paused else "")
            lines.append(f"  seed {s:<5} {bar(f)} {f * 100:5.1f}%  {note}")
        elif out.exists() and out.stat().st_size:
            try:
                ok = json.loads(out.read_text()).get("passed")
            except ValueError:
                ok = None
            rfr.append(1.0)
            lines.append(f"  seed {s:<5} {bar(1.0)} 100.0%  {'PASS' if ok else 'FAIL'}")
        else:
            rfr.append(0.0)
            lines.append(f"  seed {s:<5} {bar(0.0)}   0.0%  waiting")
    rt = sum(rfr) / len(rfr)
    lines.append(
        f"  overall   {bar(rt)} {rt * 100:5.1f}%"
        "  (by bytes of the trace; inserts are the first 7 %)"
    )
    lines.append("")

    # Everything left for Part 3.
    steps = [
        ("Code, tests, proofs, docs (modules 1-11)", "done"),
        ("Kit speed-ups (DB-88)", "done"),
        ("P3-T4 crash campaign", crash_rc or "running"),
        ("P3-T5 trace replay", replay_rc or "running"),
        ("P3-T1/T2 attacks", gate_done("gate-p3-attacks.log") or "waiting"),
        ("fuzz, mutants, coverage, checks, measures, spikes", "waiting"),
        ("Fair run (needs your go), freeze manifest, your tag", "waiting"),
    ]
    n_done = sum(1 for _, s in steps if s in ("done", "PASS"))
    lines.append(f"Part 3 checklist  {bar(n_done / len(steps), 20)} {n_done}/{len(steps)}")
    for name, st in steps:
        mark = (
            "✔"
            if st in ("done", "PASS")
            else ("…" if st == "running" else ("✘" if st.startswith("FAIL") else "·"))
        )
        lines.append(f"  {mark} {name:<52} {st}")
    lines.append("")

    try:
        with open("/proc/meminfo") as f:
            mem = {
                k: int(v.split()[0]) // 1024
                for k, v in (line.split(":", 1) for line in f)
                if k in ("MemTotal", "MemAvailable")
            }
        load = os.getloadavg()[0]
        lines.append(
            f"Memory free {mem['MemAvailable']:,} of {mem['MemTotal']:,} MB"
            f"   CPU load {load:.1f} of {os.cpu_count()} cores"
        )
    except (OSError, KeyError):
        pass
    return "\n".join(lines)


def main() -> None:
    once = "--once" in sys.argv
    try:
        while True:
            text = render()
            if not once:
                print("\033[2J\033[H", end="")
            print(text, flush=True)
            if once:
                return
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
