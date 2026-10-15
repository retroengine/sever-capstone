"""Appendix B golden vectors that Part 3 owns, written by this model (Build 3-4 §3.4: the build part
that owns a vector generates it once, from an implementation independent of the engine).

    PYTHONPATH=python uv run python -m sever_refmodel_certs.golden write   # once; then committed
    PYTHONPATH=python uv run python -m sever_refmodel_certs.golden check   # Fast tier

Vectors so far: 1 (``H``, ``G_0``, ``G_383``, §9.2) and 2 (``gdigest``, §9.6), at d = 384. Once
committed, a golden file changes only with a recorded reason (CLAUDE.md §6.2).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

from sever_refmodel_certs import spec
from sever_refmodel_certs.ristretto import encode

OUT_GENERATORS: Final = Path("golden/p3_generators.json")


def generators_vector() -> dict[str, Any]:
    h, gs = spec.generators(spec.D_V1)
    return {
        "source": "sever_refmodel_certs (pure-Python RFC 9496 / RFC 9380, DB-51); spec §9.2, §9.6",
        "appendix_b": [1, 2],
        "d": spec.D_V1,
        "dst_gen": spec.DST_GEN.decode("ascii"),
        "H": encode(h).hex(),
        "G_0": encode(gs[0]).hex(),
        "G_383": encode(gs[383]).hex(),
        "gdigest": spec.gdigest(spec.D_V1).hex(),
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="refmodel-certs-golden", description=__doc__)
    ap.add_argument("command", choices=["write", "check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    path = args.root / OUT_GENERATORS
    text = _dump(generators_vector())
    if args.command == "write":
        path.write_text(text, encoding="utf-8")
        print(path)
        return 0
    ok = path.is_file() and path.read_text(encoding="utf-8") == text
    print(f"{OUT_GENERATORS}: {'matches the model' if ok else 'DIFFERS from the model'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
