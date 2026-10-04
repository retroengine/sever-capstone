"""Part 1 demo: the full-data acceptance run (DEMO_PLAN §6.2).

    scripts/demo.sh run                                    # recommended (fast environment)
    PYTHONPATH=python uv run python -m sever_demo.demo --seed 42
    PYTHONPATH=python uv run python -m sever_demo.demo --rows 50000 --stress 200     # smoke run
    PYTHONPATH=python uv run python -m sever_demo.demo --rows 50000 --sabotage SB-2  # must FAIL
    ... --no-commitments                    # the Day 2 run: 4 of 5 fields, no certificates

Every run appends one line to docs/RUN_LEDGER.jsonl and writes its full results to results/.
With commitments (the default, Part 3 preview) every deletion also gets a signed certificate in
results/certs/<run>/, and every certificate is checked by the independent verifier, run as its own
process; tampered copies must be rejected.
"""

import sys
from pathlib import Path

if not __package__:
    # Run as a plain file (`python repl.py` inside python/sever_demo): put python/ on the import
    # path instead of this folder, so `import sever_demo` works from anywhere.
    sys.path[0] = str(Path(__file__).resolve().parents[1])

import argparse
import json
import time
from typing import Any

import numpy as np
import numpy.typing as npt
from numpy.lib.format import open_memmap
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from sever_demo import group as group_module
from sever_demo import guide
from sever_demo.baselines import ghost_report
from sever_demo.data import (
    DATASETS,
    PROCESSED,
    REPO,
    check_manifest,
    check_norms,
    load_ids_and_cohorts,
)
from sever_demo.errors import InvalidRecordId, Outcome
from sever_demo.group import fresh_sum
from sever_demo.ids import validate_record_id
from sever_demo.index import Index
from sever_demo.ledger import (
    LEDGER_PATH,
    append,
    describe,
    open_ledger,
    run_context,
    sha256_file,
)
from sever_demo.partition import K_FROZEN, fit_centroids, route, sub_seed
from sever_demo.quant import quantise
from sever_demo.receipts import run_verifier, tampered_copy, write_receipts

CACHE = Path.home() / ".cache" / "sever"  # never inside datasets/ (CLAUDE.md §8)
RESULTS = REPO / "results"
CERTS = RESULTS / "certs"  # per-run receipts (git-ignored: tied to one session's keys)
SCIQ = PROCESSED / "sciq_reference" / "embeddings.npy"
NQ = PROCESSED / "nq_1m" / "embeddings.npy"
NQ_PASSAGES = PROCESSED / "nq_1m" / "passages.parquet"
FULL_CHECK_EVERY = 50  # stress: full blob check every 50 ops (DEMO_PLAN §6.2 step 7)
ALL_TRUE = {"S": True, "n": True, "members": True, "blob": True}
FIELDS_5 = ["S", "n", "members", "C_S", "blob"]
TAMPERED = 10  # tampered certificate copies that must all be rejected
TICK, CROSS = "[green]✓[/green]", "[red]✗[/red]"

console = Console()


def manifest_hash(rel: str) -> str:
    for line in (DATASETS / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        h, path = line.split("  ", 1)
        if path == rel:
            return h
    raise KeyError(rel)


def cached_quantised(src: Path, rel: str) -> npt.NDArray[np.int32]:
    """Quantise a whole embedding file once (§4.2) and keep it in ~/.cache/sever.

    The cache name includes the source file's manifest hash, so changed data never reuses it. It is
    written to a temporary name first, so a crash never leaves a half-written cache behind.
    """
    path = CACHE / f"{src.parent.name}_q24_{manifest_hash(rel)[:16]}.npy"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        x = np.load(src, mmap_mode="r")
        tmp = path.with_name(path.stem + ".partial.npy")
        out = open_memmap(tmp, mode="w+", dtype=np.int32, shape=x.shape)
        for start in range(0, x.shape[0], 50_000):
            out[start : start + 50_000] = quantise(x[start : start + 50_000])
        out.flush()
        del out
        tmp.replace(path)
    q: npt.NDArray[np.int32] = np.load(path, mmap_mode="r")
    return q


def cached_centroids(seed: int) -> npt.NDArray[np.float64]:
    path = CACHE / f"centroids_k{K_FROZEN}_seed{seed}_{manifest_hash(SCIQ_REL)[:16]}.npy"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        np.save(path, fit_centroids(np.load(SCIQ, mmap_mode="r"), seed))
    c: npt.NDArray[np.float64] = np.load(path)
    return c


SCIQ_REL = "processed/sciq_reference/embeddings.npy"
NQ_REL = "processed/nq_1m/embeddings.npy"


class Run:
    """Collects timings, counts and results, and prints each step."""

    def __init__(self, stamp: str = "run") -> None:
        self.stamp = stamp  # the run's UTC time, used in result and certificate file names
        self.t0 = time.perf_counter()
        self.timings: dict[str, float] = {}
        self.results: dict[str, Any] = {}
        self._last = self.t0

    def step(self, name: str) -> None:
        """Prints the step's name and, under it, why the step exists (guide.RUN_WHY)."""
        now = time.perf_counter()
        console.print(f"[dim]{now - self.t0:7.1f}s[/dim]  [bold]{name}[/bold]")
        why = guide.RUN_WHY.get(name.split(".")[0])
        if why:
            console.print(f"          [cyan]{escape(why)}[/cyan]", highlight=False)
        self._last = now

    def done(self, key: str) -> None:
        self.timings[key] = round(time.perf_counter() - self._last, 2)


def size_table(sizes: list[int]) -> Table:
    a = np.array(sizes)
    t = Table(title="Group sizes")
    for col in ["groups", "records", "min", "median", "max", "empty"]:
        t.add_column(col, justify="right")
    t.add_row(
        str(len(a)),
        f"{int(a.sum()):,}",
        f"{int(a.min()):,}",
        f"{int(np.median(a)):,}",
        f"{int(a.max()):,}",
        str(int((a == 0).sum())),
    )
    return t


def ghost_table(report: dict[str, Any]) -> Table:
    t = Table(
        title=f"The ghost: one group, {report['members']:,} members, {report['deleted']} deleted"
    )
    for col in [
        "method",
        "deleted record still stored",
        "summary vs survivors-only",
        "bit-identical?",
    ]:
        t.add_column(col)
    t.add_row(
        "SEVER (integer S)",
        "no",
        f"{report['sever_max_abs_diff']} (S identical)",
        "yes" if report["sever_bit_identical"] else "NO",
    )
    t.add_row(
        "float32 running mean",
        "no",
        f"{report['float_max_abs_diff']:.3e} max abs",
        "yes" if report["float_bit_identical"] else "no",
    )
    t.add_row(
        "soft delete",
        f"yes ({report['soft_still_stored']})",
        f"{report['soft_distance']:.3e} L2",
        "no",
    )
    return t


def evidence_table(counts: dict[str, int], results: dict[str, Any], commitments: bool) -> Table:
    """What the run shows, in plain words: each claim, its evidence, and a verdict.

    ✓ / ✗ are gates (a ✗ fails the run); the ghost row is a measure, reported as found (Build §2.5).
    A step that did not run (the run stopped early) says so."""
    t = Table(title="What this run shows")
    for col in ["claim", "evidence", ""]:
        t.add_column(col)

    def row(claim: str, evidence: str, ok: bool | None) -> None:
        mark = "[dim]not run[/dim]" if ok is None else TICK if ok else CROSS
        t.add_row(claim, evidence, mark)

    row(
        "The data is exactly the pinned data",
        f"{counts['manifest_mismatches']} files differ from the committed manifest",
        counts["manifest_mismatches"] == 0,
    )
    norms = results.get("norms")
    if norms is None:
        row("Every vector and record ID is valid (§4.1, §3.2)", "-", None)
    else:
        rows = norms["sciq"]["rows"] + norms["nq"]["rows"]
        row(
            "Every vector and record ID is valid (§4.1, §3.2)",
            f"{counts['norm_failures']} bad vectors of {rows:,}; "
            f"{counts['id_rejections']} bad record IDs",
            counts["norm_failures"] == 0 and counts["id_rejections"] == 0,
        )
    survivors: dict[str, dict[str, bool]] | None = results.get("survivors")
    if survivors is None:
        for claim in ["Deleting is exact (§5.5)", "Nothing else moves", "A retry changes nothing"]:
            row(claim, "-", None)
    else:
        exact = sum(all(v.values()) for v in survivors.values())
        k = len(next(iter(survivors.values()))) if survivors else 0
        row(
            "Deleting is exact: each touched group equals its survivors-only rebuild (§5.5)",
            f"{exact} of {len(survivors)} groups exact, on {k} of 5 fields",
            exact == len(survivors),
        )
        row(
            "Nothing else moves",
            f"{counts['untouched_changed']} of {K_FROZEN - len(survivors)} untouched groups "
            "changed",
            counts["untouched_changed"] == 0,
        )
        row(
            "A retry changes nothing (§5.4)",
            "all AlreadyAbsent, groups unchanged"
            if results["retry_ok"]
            else "a retry changed state",
            bool(results["retry_ok"]),
        )
    ghost = results.get("ghost")
    if ghost is not None:
        t.add_row(
            "Floats and soft delete leave a ghost; SEVER does not",
            f"SEVER {ghost['sever_max_abs_diff']} · float32 {ghost['float_max_abs_diff']:.1e} · "
            f"soft delete still stores {ghost['soft_still_stored']}",
            "[dim]measure[/dim]",
        )
    stress = results.get("stress")
    row(
        "Every check in the run passes, random operations included",
        "-"
        if stress is None
        else f"{counts['mismatches']} mismatches in {counts['checks']:,} checks "
        f"({counts['ops']:,} operations, {sum(stress['kinds'].values()):,} of them random)",
        None if stress is None else counts["mismatches"] == 0,
    )
    if commitments:
        certs = results.get("certificates")
        if certs is None:
            row("Every receipt checks out offline (§11.3)", "-", None)
            row("A forged receipt is caught", "-", None)
        else:
            row(
                "Every receipt checks out offline (§11.3)",
                f"{certs['accepted']} of {certs['issued']} accepted by the separate verifier",
                certs["issued"] > 0 and certs["accepted"] == certs["issued"],
            )
            row(
                "A forged receipt is caught",
                f"{certs['tamper_rejected']} of {certs['tampered']} forged copies rejected",
                certs["tamper_rejected"] == certs["tampered"],
            )
    return t


def run(args: argparse.Namespace, entry: dict[str, Any], r: Run) -> dict[str, Any]:
    counts: dict[str, int] = {
        "manifest_mismatches": 0,
        "norm_failures": 0,
        "id_rejections": 0,
        "ops": 0,
        "checks": 0,
        "mismatches": 0,
        "untouched_changed": 0,
    }
    if args.commitments:
        counts.update(
            {"certs_issued": 0, "certs_verified": 0, "certs_rejected": 0, "tamper_caught": 0}
        )
    entry["counts"] = counts
    all_true = dict(ALL_TRUE, C_S=True) if args.commitments else ALL_TRUE
    fields = FIELDS_5 if args.commitments else ["S", "n", "members", "blob"]

    # 1. Phase 0 proof: every dataset file still has its committed hash.
    r.step("1. Manifest check (datasets/MANIFEST.sha256)")
    bad = check_manifest()
    counts["manifest_mismatches"] = len(bad)
    console.print(f"   {'PASS' if not bad else 'FAIL'}: {len(bad)} mismatches {bad}")
    r.done("manifest")
    if bad:
        return counts

    # 2. §4.1 on every row that will be used. Check, never fix.
    r.step("2. Norm check (§4.1)")
    sciq_norms = check_norms(np.load(SCIQ, mmap_mode="r"))
    nq_f32 = np.load(NQ, mmap_mode="r")
    n = nq_f32.shape[0] if args.rows is None else min(args.rows, nq_f32.shape[0])
    nq_norms = check_norms(nq_f32[:n])
    counts["norm_failures"] = sum(
        rep["non_finite"] + rep["bad_length"] for rep in (sciq_norms, nq_norms)
    )
    r.results["norms"] = {"sciq": sciq_norms, "nq": nq_norms}
    console.print(
        f"   SciQ {sciq_norms['rows']:,} rows, NQ {n:,} rows: "
        f"{counts['norm_failures']} failures, worst {nq_norms['worst_abs_diff']:.3e}"
    )
    r.done("norms")
    if counts["norm_failures"]:
        return counts

    # 3. §3.2 rules 1-2 on every record ID.
    r.step("3. Record ID check (§3.2)")
    ids, cohorts = load_ids_and_cohorts(NQ_PASSAGES, n)
    for rid in ids:
        try:
            validate_record_id(rid)
        except InvalidRecordId:
            counts["id_rejections"] += 1
    console.print(
        f"   {len(ids):,} IDs, {counts['id_rejections']} rejected, {len(set(ids)):,} unique"
    )
    r.done("ids")
    if counts["id_rejections"]:
        return counts

    # 4. Frozen partition (§6.2 steps 1-2), quantise (§4.2), route (§7.1), insert in stream order.
    r.step(f"4. Fit {K_FROZEN} centroids on SciQ, quantise NQ, route, insert")
    centroids = cached_centroids(args.seed)
    q = cached_quantised(NQ, NQ_REL)[:n]
    labels = route(q, centroids)
    index = Index(q, ids, labels, K_FROZEN)
    order = np.random.default_rng(sub_seed(args.seed, b"stream")).permutation(n)
    for row in order:
        index.insert(ids[row])
    console.print(size_table(index.sizes()))
    r.results["group_sizes"] = index.sizes()
    r.done("build")

    if args.commitments:
        # Part 3 preview (§9.3, §9.4): r_t for every record from the OS, C_S for every group.
        r.step("4b. Commitments: r_t for every record, C_S for every group (§9.3)")
        index.enable_commitments()
        console.print(
            f"   {n:,} blinding values from the OS (kept in memory only); "
            f"{K_FROZEN} group commitments C_S = r_agg·H + Σ S_i·G_i"
        )
        r.done("commitments")

    # 5. delete_user on whole cohorts (Overview §10.8), chosen in cohort-order sub-seed order.
    r.step(f"5. delete_user on {args.cohorts} cohorts")
    names = sorted(set(cohorts), key=lambda c: c.encode("utf-8"))
    pick = np.random.default_rng(sub_seed(args.seed, b"cohort-order")).permutation(len(names))
    chosen = [names[i] for i in pick[: args.cohorts]]
    members: dict[str, list[str]] = {c: [] for c in chosen}
    for rid, c in zip(ids, cohorts, strict=True):
        if c in members:
            members[c].append(rid)
    before = index.group_hashes()
    touched: set[int] = set()
    deleted: list[str] = []
    for c in chosen:
        for rid, outcome, gid in index.delete_user(members[c]):
            counts["ops"] += 1
            if outcome is Outcome.DELETED and gid is not None:
                touched.add(gid)
                deleted.append(rid)
            else:
                counts["mismatches"] += 1  # a live record must delete
    console.print(f"   {len(deleted)} records deleted from {len(touched)} groups")
    r.done("delete_user")

    # 6. Survivors check on every touched group; every other group byte-for-byte unchanged.
    r.step(f"6. Survivors check (§5.5, {len(fields)} of 5 fields) and untouched groups")
    rng = np.random.default_rng(sub_seed(args.seed, b"check"))
    survivors: dict[int, dict[str, bool]] = {}
    for gid in sorted(touched):
        survivors[gid] = index.survivors_check(gid, rng)
        counts["checks"] += 1
        counts["mismatches"] += survivors[gid] != all_true
    after = index.group_hashes()
    counts["untouched_changed"] = sum(
        after[g] != before[g] for g in range(K_FROZEN) if g not in touched
    )
    t = Table(title="Survivors check, touched groups")
    for col in ["group", "n", *(f if f != "n" else "n ok" for f in fields)]:
        t.add_column(col)
    for gid, res in survivors.items():
        t.add_row(
            str(gid),
            f"{index.groups[gid].n:,}",
            *(TICK if res[f] else CROSS for f in fields),
        )
    console.print(t)
    console.print(
        f"   untouched groups changed: {counts['untouched_changed']} of {K_FROZEN - len(touched)}"
    )

    # Idempotency on real data: retry the first cohort's deletion.
    retry_groups = sorted({index.labels[index.row_of[rid]] for rid in members[chosen[0]]})
    retry_before = index.group_hashes(int(g) for g in retry_groups)
    retry = index.delete_user(members[chosen[0]])
    retry_ok = all(o is Outcome.ALREADY_ABSENT for _, o, _ in retry) and (
        index.group_hashes(int(g) for g in retry_groups) == retry_before
    )
    counts["mismatches"] += not retry_ok
    console.print(
        f"   retry of cohort 1 ({len(retry)} records): "
        f"{'all AlreadyAbsent, groups unchanged' if retry_ok else 'FAILED'}"
    )
    r.results["survivors"] = {str(g): v for g, v in survivors.items()}
    r.results["retry_ok"] = retry_ok
    r.done("survivors")

    # 7. Ghost table on the largest touched group (a pure function of the data, so its place in
    # the run does not matter).
    r.step("7. Ghost table (DEMO_PLAN §5.7)")
    gid_g = max(touched, key=lambda g: index.groups[g].n)
    rows_g = order[labels[order] == gid_g]  # this group's rows, in insertion order
    deleted_set = set(deleted)
    mask = np.array([ids[row] in deleted_set for row in rows_g])
    report = ghost_report(
        np.asarray(nq_f32[rows_g]),
        np.asarray(q[rows_g]),
        mask,
        np.random.default_rng(sub_seed(args.seed, b"ghost")),
        cycles=1000,
    ).as_dict()
    report["group"] = gid_g
    console.print(ghost_table(report))
    console.print(
        f"   float32 error after N delete/re-insert cycles: {report['float_cycle_error']}"
    )
    r.results["ghost"] = report
    r.done("ghost")

    # 8. Stress: seeded random operations, a cheap check after each, a full check every 50.
    # "stress", "check" and "ghost" are demo sub-seed labels, not in Overview §10.6.
    r.step(f"8. Stress: {args.stress} random operations")
    srng = np.random.default_rng(sub_seed(args.seed, b"stress"))
    pool = list(deleted)
    stress_groups: set[int] = set()
    kinds = {"delete": 0, "delete_absent": 0, "reinsert": 0}
    for i in range(args.stress):
        u = srng.random()
        sgid: int | None
        if u < 0.2 and pool:
            rid = pool[int(srng.integers(len(pool)))]
            sgid = int(index.labels[index.row_of[rid]])
            g = index.groups[sgid]
            s_before, n_before = g.S.copy(), g.n
            outcome, _ = index.delete(rid)
            kinds["delete_absent"] += 1
            ok = (
                outcome is Outcome.ALREADY_ABSENT
                and np.array_equal(g.S, s_before)
                and g.n == n_before
            )
        elif u < 0.6 and pool:
            j = int(srng.integers(len(pool)))
            rid = pool[j]
            pool[j] = pool[-1]
            pool.pop()
            sgid = index.insert(rid)
            kinds["reinsert"] += 1
            ok = True
        else:
            rid = ids[int(srng.integers(n))]
            outcome, sgid = index.delete(rid)
            if outcome is Outcome.DELETED:
                pool.append(rid)
            kinds["delete"] += 1
            ok = True
        counts["ops"] += 1
        if sgid is not None:
            g = index.groups[sgid]
            stress_groups.add(sgid)
            ok = ok and np.array_equal(g.S, fresh_sum(q, g.members.values()))
            ok = ok and g.n == len(g.members)
            counts["checks"] += 1
            if (i + 1) % FULL_CHECK_EVERY == 0:
                ok = ok and index.survivors_check(sgid, rng) == all_true
                counts["checks"] += 1
        counts["mismatches"] += not ok
    end_fails = 0
    for gid in sorted(stress_groups):
        end_fails += index.survivors_check(gid, rng) != all_true
        counts["checks"] += 1
    counts["mismatches"] += end_fails
    console.print(
        f"   {kinds}; final full check on {len(stress_groups)} groups: {end_fails} failures"
    )
    r.results["stress"] = {"kinds": kinds, "groups": len(stress_groups), "end_failures": end_fails}
    r.done("stress")

    if args.commitments:
        check_certificates(args, index, counts, r)
    return counts


def check_certificates(
    args: argparse.Namespace, index: Index, counts: dict[str, int], r: Run
) -> None:
    """9. Every certificate to disk, verified by the independent verifier as its own process; then
    tampered copies (one bit flipped each) must all be rejected (§11.3)."""
    r.step("9. Certificates: write, verify offline (separate process), tamper")
    folder = CERTS / r.stamp
    paths = write_receipts(folder, index.anchors(), index.issued)
    counts["certs_issued"] = len(paths)
    accepted, _ = run_verifier(folder / "anchors.json", paths)
    counts["certs_verified"] = sum(accepted.values())
    counts["certs_rejected"] = len(paths) - counts["certs_verified"]
    sizes = sorted(p.stat().st_size for p in paths)
    console.print(
        f"   {len(paths)} certificates in {folder.relative_to(REPO)}/ "
        f"({sizes[0]:,} to {sizes[-1]:,} bytes): "
        f"{counts['certs_verified']} accepted, {counts['certs_rejected']} rejected"
    )
    trng = np.random.default_rng(sub_seed(args.seed, b"tamper"))
    chosen = trng.choice(len(paths), size=min(TAMPERED, len(paths)), replace=False)
    fakes = [
        tampered_copy(paths[i], folder / "tampered" / paths[i].name, int(trng.integers(1 << 20)))
        for i in chosen
    ]
    fake_ok, _ = run_verifier(folder / "anchors.json", fakes)
    counts["tamper_caught"] = sum(not ok for ok in fake_ok.values())
    console.print(
        f"   {len(fakes)} tampered copies (one bit flipped each): "
        f"{counts['tamper_caught']} rejected, {len(fakes) - counts['tamper_caught']} accepted"
    )
    r.results["certificates"] = {
        "folder": folder.relative_to(REPO).as_posix(),
        "issued": len(paths),
        "accepted": counts["certs_verified"],
        "size_bytes": [sizes[0], sizes[-1]],
        "tampered": len(fakes),
        "tamper_rejected": counts["tamper_caught"],
    }
    r.done("certificates")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sever_demo.demo", description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--rows", type=int, default=None, help="use only the first N NQ rows")
    p.add_argument("--cohorts", type=int, default=10)
    p.add_argument("--stress", type=int, default=2000)
    p.add_argument("--sabotage", choices=["none", "SB-1", "SB-2", "SB-3", "SB-4"], default="none")
    p.add_argument(
        "--no-commitments",
        dest="commitments",
        action="store_false",
        help="the Day 2 run: no commitments, no certificates (4 of 5 fields)",
    )
    p.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    args = p.parse_args(argv)

    # Overview §13.3: if the ledger cannot be opened, the run does not start.
    with open_ledger(args.ledger) as ledger:
        command = "sever_demo.demo " + " ".join(sys.argv[1:] if argv is None else argv)
        entry = run_context(command, args.seed, args.sabotage)
        entry["rows_loaded"] = args.rows or 1_000_000
        entry["k_groups"] = K_FROZEN
        entry["commitments"] = args.commitments
        entry["kind"] = "run"
        group_module.SABOTAGE = None if args.sabotage == "none" else args.sabotage
        if group_module.SABOTAGE:
            console.print(f"[red bold]SABOTAGE {args.sabotage} is ON: this run must FAIL[/]")
        stamp = entry["ts_utc"].replace(":", "").replace("+0000", "Z")
        r = Run(stamp)
        try:
            counts = run(args, entry, r)
            passed = (
                all(
                    counts[k] == 0
                    for k in [
                        "manifest_mismatches",
                        "norm_failures",
                        "id_rejections",
                        "mismatches",
                        "untouched_changed",
                    ]
                )
                and "stress" in r.results
                and (
                    not args.commitments
                    or (
                        counts["certs_issued"] > 0
                        and counts["certs_verified"] == counts["certs_issued"]
                        and counts["tamper_caught"] == min(TAMPERED, counts["certs_issued"])
                    )
                )
            )
            entry["outcome"] = "PASS" if passed else "FAIL"
        except Exception as exc:
            entry["outcome"] = "ERROR"
            entry["error"] = type(exc).__name__  # the type only: messages could hold data (§17)
            raise
        finally:
            entry["timings_s"] = r.timings
            entry["total_s"] = round(time.perf_counter() - r.t0, 1)
            RESULTS.mkdir(exist_ok=True)
            result_path = RESULTS / f"p1-demo-{stamp}.json"
            result_path.write_text(
                json.dumps(
                    {"ledger_entry": entry, "results": r.results},
                    indent=1,
                    sort_keys=True,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
            entry["result_file"] = result_path.relative_to(REPO).as_posix()
            entry["result_sha256"] = sha256_file(result_path)
            entry["summary"] = describe(entry)  # one plain sentence; never a record ID (§17)
            append(ledger, entry)
            group_module.SABOTAGE = None

    console.print()
    console.print(evidence_table(entry["counts"], r.results, args.commitments))
    colour = "green" if entry["outcome"] == "PASS" else "red"
    console.print(
        f"\n[bold {colour}]{entry['outcome']}[/]  counts={entry['counts']}  "
        f"total {entry['total_s']}s  ledger: {args.ledger.name}  "
        f"result: {entry['result_file']}"
    )
    console.print(f"  ledger line: {escape(entry['summary'])}", highlight=False)
    return 0 if entry["outcome"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
