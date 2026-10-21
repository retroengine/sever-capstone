"""``python -m sever_tour tour | shell | crash-child`` (run through ``demo-engine/demo.sh``)."""

import argparse
import sys
from pathlib import Path

from .data import DataMissingError, load
from .session import WorkInUseError, lock_work

ROOT = Path(__file__).resolve().parents[2]
#: The tour inserts ``--rows`` records and keeps this many more for the crash test.
SPARE = 200


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sever_tour")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("tour", "shell", "crash-child"):
        s = sub.add_parser(name)
        s.add_argument("--data", choices=["nq", "synthetic"], default="nq")
        s.add_argument("--rows", type=int, default=None)
        s.add_argument("--work", type=Path, default=None)
        s.add_argument(
            "--dev",
            action="store_true",
            help="open with the development override when the platform is refused",
        )
        if name == "shell":
            s.add_argument(
                "-c", dest="script", default=None, help="run these ;-separated commands and exit"
            )
        if name == "crash-child":
            s.add_argument("--start", type=int, required=True)
            s.add_argument("--count", type=int, required=True)
    a = p.parse_args(argv)
    default_rows = {"tour": 5000, "shell": 20000}.get(a.cmd, 0) if a.data == "nq" else 40
    rows = a.rows if a.rows is not None else default_rows
    work = a.work or ROOT / "demo-engine/work" / f"{a.cmd}-{a.data}"
    try:
        if a.cmd != "crash-child":
            lock_work(work)
        if a.cmd == "crash-child":
            from .tour import crash_child

            return crash_child(load(ROOT, a.data, rows), work, a.start, a.count, a.dev)
        if a.cmd == "shell":
            from . import shell

            corpus = load(ROOT, a.data, rows if a.data == "nq" else 240)
            return shell.run(ROOT, corpus, work, a.dev, a.script)
        from .tour import Tour

        corpus = load(ROOT, a.data, rows + SPARE)
        return Tour(ROOT, corpus, work, rows, a.dev).run()
    except WorkInUseError as e:
        print(f"{e}; wait for it to finish, or use another --work directory")
        return 2
    except DataMissingError as e:
        print(f"{e}. The data is not in git: see demo-engine/README.md, or use --data synthetic")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
