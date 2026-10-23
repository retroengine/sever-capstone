"""``python -m sever_studio prepare | run | crash-child`` (through ``studio/studio.sh``).

``prepare`` builds the demo database once: it stores ``--rows`` passages (default 10,000 on NQ)
through the SDK, writes where each landed (``prepare-events.jsonl``, for the replay), and lays out
the map. ``run`` opens the window on it. ``crash-child`` is the writer the crash demo kills.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROWS = {"nq": 10_000, "synthetic": 120}


def prepare(data: str, rows: int, work: Path, dev: bool, held: int) -> int:
    import shutil

    from .actions import Studio
    from .backend import note_lock

    print(f"Preparing {rows} {data} passages in {work}")
    t0 = time.perf_counter()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    studio = Studio(ROOT, data, work, dev, rows)
    print(f"  map laid out ({time.perf_counter() - t0:.0f} s)")
    studio.open()
    t1 = time.perf_counter()

    def progress(done: int, total: int) -> None:
        if done % 500 == 0 or done == total:
            rate = (time.perf_counter() - t1) / done
            print(f"  {done:>6} / {total} inserted ({rate * 1000:.1f} ms each)", flush=True)
            note_lock(held, "prepare", f"{done:,} / {total:,} stored")

    studio.store_first(progress)
    problems = studio.backend.mismatches()
    st = studio.backend.live.stats(studio.backend.cid)
    studio.backend.close()
    print(
        f"Done in {time.perf_counter() - t0:.0f} s: N {st['N']}, holding {st['holding']},"
        f" {st['frozen']} frozen + {st['spawned']} spawned groups;"
        " index "
        + ("agrees with the database" if not problems else "DIFFERS: " + "; ".join(problems))
    )
    return 0 if not problems else 1


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sever_studio")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "run", "crash-child", "delete-child"):
        s = sub.add_parser(name)
        s.add_argument("--data", choices=["nq", "synthetic"], default="nq")
        s.add_argument("--rows", type=int, default=None)
        s.add_argument("--work", type=Path, default=None)
        s.add_argument("--dev", action="store_true", help="use the development override if refused")
        if name == "run":
            s.add_argument("--smoke", action="store_true", help="walk everything, then quit")
        if name == "delete-child":
            s.add_argument("--ids", type=Path, required=True)
        if name == "crash-child":
            s.add_argument("--start", type=int, required=True)
            s.add_argument("--count", type=int, required=True)
    a = p.parse_args(argv)
    rows = a.rows if a.rows is not None else DEFAULT_ROWS[a.data]
    work = a.work or ROOT / "studio/work" / f"studio-{a.data}"
    from .backend import WorkInUseError, lock
    from .corpus import DataMissingError

    try:
        if a.cmd == "crash-child":
            from .actions import crash_child

            return crash_child(ROOT, a.data, rows, work, a.start, a.count, a.dev)
        if a.cmd == "delete-child":
            from .actions import Studio
            from .wow import delete_child

            return delete_child(Studio(ROOT, a.data, work, a.dev, rows), a.ids)
        held = lock(work, a.cmd)
        if a.cmd == "prepare":
            return prepare(a.data, rows, work, a.dev, held)
        from .ui.app import run

        return run(ROOT, a.data, rows, work, a.dev, a.smoke)
    except WorkInUseError as e:
        print(e)
        return 2
    except DataMissingError as e:
        print(f"{e}. The NQ data is not in git (see the top-level README), or use --data synthetic")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
