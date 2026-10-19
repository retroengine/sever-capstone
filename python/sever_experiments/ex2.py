"""Overview EX-2 (P4-T1, P4-T2): physical erasure on a raw ext4 image.

Per seed: a sparse ext4 image (16 GiB by default) is mounted with ``fuse2fs``; the engine
(``sever-ex2``, the ``forensics`` build: the measured engine plus DB-54's ``key-export``) ingests
the slice in the seed's stream order, then runs the five deletion rungs (overview §10.8). After the
ingest and after each rung: storage checkpoint, clean shutdown, unmount, and ``sever-scan`` reads
the **raw image, free space included**. Every scan must find nothing of what was deleted (P4-T1),
and every secret planted on the image just before it (P4-T2's positive controls, Build 3-4 §2.8:
the scanner can see). Live records the scanner recovers by carving the engine's own structures are
reported too; how many depends on what free space still holds. ``fuse2fs`` reports its mounts as
``fuseblk``-like FUSE mounts, which §12.9 does not list, so the engine runs with ``allow_unsafe_fs``
(G-35, DB-96; recorded in the result).

Scanner sensitivity (P4-T2): the same steps at ``nq-10k`` (ingest and the first rung, seed 42)
with each sabotage build whose register row says the scanner applies; each must produce at least
one finding.

The work directory holds instrumentation that must never leave it (each record's ``r_t``, every
generated key); it is deleted after the scans.
"""

import contextlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow.parquet as pq

from sever_testkit.seeds import sub_seed
from sever_testkit.traces import cohort_rungs, load_slice

#: Live records each scan must recover.
CONTROLS: Final = 20
#: The sabotage items the scanner applies to (spec/registers_p4.yaml, ``scanner: true``).
SENSITIVE: Final = ("SB-24", "SB-25", "SB-26", "SB-28", "SB-29", "SB-30")
#: The crate that owns each sabotage feature.
SB_CRATE: Final = {
    "SB-24": "sever-seal",
    "SB-25": "sever-erasure",
    "SB-26": "sever-erasure",
    "SB-28": "sever-seal",
    "SB-29": "sever-seal",
    "SB-30": "sever-seal",
}


def build(root: Path, sabotage: str | None = None) -> tuple[Path, Path]:
    """The ``sever-ex2`` driver (optionally with one sabotage feature) and ``sever-scan``."""
    feats = ["forensics"]
    tag = "ex2"
    if sabotage:
        feats.append(f"{SB_CRATE[sabotage]}/sabotage-{sabotage}")
        tag = f"ex2-{sabotage}"
    target = root / "target" / tag
    for b, f in (("sever-ex2", ",".join(feats)), ("sever-scan", "")):
        subprocess.run(
            [
                "cargo",
                "build",
                "-q",
                "--release",
                "-p",
                "sever-scan",
                "--bin",
                b,
                *(["--features", f] if f else []),
                "--target-dir",
                str(target),
            ],
            cwd=root,
            check=True,
        )
    return target / "release/sever-ex2", target / "release/sever-scan"


def prepare(root: Path, data: str, seed: int, work: Path) -> list[list[list[str]]]:
    """Writes the stream (``stream.f32``, ``stream.jsonl``) in the seed's order; returns the
    rungs."""
    sl = load_slice(root, data)
    n = len(sl.ids)
    vectors = np.load(root / sl.vectors_path, mmap_mode="r")
    text = pq.read_table(root / "datasets/processed/nq_1m/passages.parquet", columns=["text"])
    passages = text.column("text").to_pylist()[:n]
    order = np.random.Generator(np.random.PCG64(sub_seed(seed, "stream"))).permutation(n)
    np.ascontiguousarray(vectors[:n][order], dtype="<f4").tofile(work / "stream.f32")
    with (work / "stream.jsonl").open("w", encoding="utf-8") as f:
        for i in order:
            f.write(json.dumps({"id": sl.ids[i], "passage": passages[i]}) + "\n")
    return cohort_rungs(sl, seed)


@contextlib.contextmanager
def mounted(image: Path, mnt: Path) -> Iterator[Path]:
    """Mounts ``image`` with ``fuse2fs`` in the foreground, single-threaded: the multi-threaded
    daemon does not exit after ``fusermount -u`` here (it waits on a futex), while ``-s -f`` writes
    the image back and exits, so the scan reads the final bytes."""
    mnt.mkdir(exist_ok=True)
    p = subprocess.Popen(
        ["fuse2fs", str(image), str(mnt), "-o", "fakeroot", "-s", "-f"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(200):
            if subprocess.run(["mountpoint", "-q", str(mnt)], check=False).returncode == 0:
                break
            if p.poll() is not None:
                raise RuntimeError(f"fuse2fs: {p.stderr.read() if p.stderr else ''}")
            time.sleep(0.05)
        yield mnt
    finally:
        for _ in range(60):
            if subprocess.run(["fusermount", "-u", str(mnt)], check=False).returncode == 0:
                break
            time.sleep(1)
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            # Some fuse2fs builds keep waiting on /dev/fuse after the unmount; SIGTERM runs
            # libfuse's clean exit (the image is written back and closed).
            p.terminate()
            p.wait(timeout=600)


def fs_clean(image: Path) -> bool:
    """``e2fsck -fn``: the image is a consistent ext4 filesystem (checked before every scan)."""
    return subprocess.run(["e2fsck", "-fn", str(image)], capture_output=True).returncode == 0


def _run(cmd: list[str]) -> dict[str, Any]:
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} {cmd[1]}: {r.stderr.strip()[-400:]}")
    out: dict[str, Any] = json.loads(r.stdout.strip().splitlines()[-1])
    return out


def scan(scanner: Path, image: Path, targets: Path) -> dict[str, Any]:
    t0 = time.time()
    r = subprocess.run(
        [str(scanner), str(image), "--targets", str(targets)],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode not in (0, 1):
        raise RuntimeError(f"sever-scan: {r.stderr.strip()[-400:]}")
    rep: dict[str, Any] = json.loads(r.stdout)
    rep["seconds"] = round(time.time() - t0, 1)
    rep["n_findings"] = rep.pop("findings")
    rep["findings_by_kind"] = rep.pop("by_kind")
    return rep


#: P4-T2's positive controls (Build 3-4 §2.8 "Planted secrets are found 100 % of the time"): one
#: of each kind is planted on the image before every scan, and every kind must be found.
PLANTED_KINDS: Final = ("plaintext_vector", "float_vector", "passage_text", "r_t", "retired_key")


def plant(mnt: Path, d: int, out: Path) -> None:
    """Writes fresh random secrets into a file on the mounted image, and their targets to ``out``
    (OS randomness: nothing here comes from a seed, CLAUDE.md §6.2)."""
    rnd = np.random.Generator(np.random.PCG64(int.from_bytes(os.urandom(16), "big")))
    x = rnd.integers(-(2**24), 2**24, size=d, dtype=np.int64).astype("<i4")
    v = rnd.standard_normal(d).astype("<f4")
    passage = os.urandom(48).hex().encode()
    r_t = os.urandom(32)
    key = os.urandom(32)
    blob = x.tobytes() + v.tobytes() + passage + r_t + key
    (mnt / "planted.bin").write_bytes(blob)
    t = {
        "sid": os.urandom(64).hex(),
        "x": [int(c) for c in x],
        "vector": [float(c) for c in v],
        "passage": passage.hex(),
        "r_t": r_t.hex(),
    }
    out.write_text(
        json.dumps({"d": d, "deleted": [t], "controls": [], "retired_keys": [key.hex()]}),
        encoding="utf-8",
    )


def run_seed(
    root: Path,
    data: str,
    seed: int,
    driver: Path,
    scanner: Path,
    image_gib: int,
    rungs: int = 5,
    unsafe_memory: bool = True,
) -> dict[str, Any]:
    """Ingest, then ``rungs`` deletion rungs; a scan after each. Returns the per-scan reports."""
    work = root / "target" / f"ex2-work-{data}-seed{seed}-{driver.parent.parent.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    os.chmod(work, 0o700)
    t0 = time.time()
    try:
        ladder = prepare(root, data, seed, work)
        image = work / "disk.img"
        with image.open("wb") as f:
            f.truncate(image_gib << 30)
        subprocess.run(["mkfs.ext4", "-q", "-F", str(image)], check=True)
        flags = ["--allow-unsafe-fs", *(["--allow-unsafe-memory"] if unsafe_memory else [])]
        art = root / f"artefacts/partition-seed{seed}.svp"
        mnt = work / "mnt"
        scans: list[dict[str, Any]] = []

        def after(label: str, step: dict[str, Any]) -> None:
            t = work / "targets.json"
            planted = work / "planted.json"
            with mounted(image, mnt):
                plant(mnt, 384, planted)
                tg = _run(
                    [
                        str(driver),
                        "targets",
                        "--dir",
                        str(mnt),
                        "--work",
                        str(work),
                        "--controls",
                        str(CONTROLS),
                        "--out",
                        str(t),
                    ]
                )
            clean = fs_clean(image)
            rep = scan(scanner, image, t)
            seen = scan(scanner, image, planted)["findings_by_kind"]
            t.unlink()
            planted.unlink()
            found = {k: seen.get(k, 0) > 0 for k in PLANTED_KINDS}
            # P4-T1: nothing deleted is found; P4-T2: every planted secret is. Live records
            # recovered by carving are reported (they depend on what free space still holds).
            ok = clean and rep["n_findings"] == 0 and all(found.values())
            scans.append(
                {
                    "after": label,
                    "step": step,
                    "targets": tg,
                    "fs_clean": clean,
                    "scan": rep,
                    "planted_found": found,
                    "live_records_recovered": sum(rep["controls_recovered"]),
                    "ok": ok,
                }
            )
            print(json.dumps({"seed": seed, "after": label, "ok": ok}), flush=True)

        base = ["--dir", str(mnt), "--work", str(work), *flags]
        with mounted(image, mnt):
            step = _run([str(driver), "ingest", *base, "--artefact", str(art)])
        after("ingest", step)
        for j, cohorts in enumerate(ladder[:rungs], start=1):
            cf = work / f"rung{j}.json"
            cf.write_text(json.dumps(cohorts), encoding="utf-8")
            with mounted(image, mnt):
                step = _run([str(driver), "rung", *base, "--cohorts", str(cf)])
            after(f"rung {j}", step)
        return {
            "seed": seed,
            "data": data,
            "image_gib": image_gib,
            "overrides": ["allow_unsafe_fs", *(["allow_unsafe_memory"] if unsafe_memory else [])],
            "scans": scans,
            "ok": all(s["ok"] for s in scans) and len(scans) == rungs + 1,
            "seconds": round(time.time() - t0),
        }
    finally:
        with contextlib.suppress(OSError):
            subprocess.run(["fusermount", "-u", str(work / "mnt")], check=False)
        shutil.rmtree(work, ignore_errors=True)


def sensitivity(root: Path, image_gib: int = 2, unsafe_memory: bool = True) -> dict[str, Any]:
    """P4-T2's sabotage half: each applicable SB build gives at least one finding (nq-10k, seed 42,
    the ingest and the first rung)."""
    out: dict[str, Any] = {}
    for sb in SENSITIVE:
        driver, scanner = build(root, sb)
        r = run_seed(root, "nq-10k", 42, driver, scanner, image_gib, 1, unsafe_memory)
        found = sum(s["scan"]["n_findings"] for s in r["scans"])
        kinds: dict[str, int] = {}
        for s in r["scans"]:
            for k, v in (s["scan"]["findings_by_kind"] or {}).items():
                kinds[k] = kinds.get(k, 0) + v
        out[sb] = {"findings": found, "by_kind": kinds, "ok": found > 0}
        print(json.dumps({"sabotage": sb, "findings": found}), flush=True)
    return {"items": out, "ok": all(v["ok"] for v in out.values())}
