"""Appendix B golden vectors that Part 3 owns, written by this model (Build 3-4 §3.4: the build part
that owns a vector generates it once, from an implementation independent of the engine).

    PYTHONPATH=python uv run python -m sever_refmodel_certs.golden write   # once; then committed
    PYTHONPATH=python uv run python -m sever_refmodel_certs.golden check   # Fast tier

Files: ``p3_generators.json`` (Appendix B vectors 1 and 2: ``H``, ``G_0``, ``G_383``, §9.2;
``gdigest``, §9.6), ``p3_commitments.json`` (§9.3 record and group commitments and the transition
check), ``p3_scalar_map.json`` (Appendix B vector 4, §4.5) and ``p3_posk.json`` (Appendix B
vector 3: a fixed challenge, §9.5; and one complete proof at d = 16 with fixed nonces). Once
committed, a golden file changes only with a recorded reason (CLAUDE.md §6.2).

The blinding values in ``p3_commitments.json`` are fixed test data (SHA-512 of a label, reduced mod
ℓ), never a database's ``r_t``: production ``r_t`` come only from the OS CSPRNG (§9.4).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

from sever_refmodel_certs import posk, spec
from sever_refmodel_certs.ristretto import IDENTITY, L, encode, encode_scalar

OUT_GENERATORS: Final = Path("golden/p3_generators.json")
OUT_COMMITMENTS: Final = Path("golden/p3_commitments.json")
OUT_POSK: Final = Path("golden/p3_posk.json")
OUT_SCALARS: Final = Path("golden/p3_scalar_map.json")


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


def _blind(label: str) -> int:
    """Fixed test blinding value: SHA-512(label) reduced mod ℓ (test data only)."""
    return int.from_bytes(hashlib.sha512(label.encode("ascii")).digest(), "little") % L


def _record(name: str, x: list[int], r: int) -> dict[str, Any]:
    return {"name": name, "d": len(x), "x": x, "r": encode_scalar(r).hex(),
            "C": encode(spec.commit(x, r)).hex()}  # fmt: skip


def commitments_vector() -> dict[str, Any]:
    big = 2**24 + 16  # the largest |x̃_i| (Appendix A)
    rec_a = [(i * 7919 % 33554433) - 16777216 for i in range(384)]
    rec_b = [big if i % 2 == 0 else -big for i in range(384)]
    # A group of three records at d = 16: S and r_agg before and after deleting the third (§5.3).
    xs = [[((k + 1) * 104729 * (i + 3)) % 2**25 - 2**24 for i in range(16)] for k in range(3)]
    rs = [_blind(f"SEVER-DB p3 commitments group r_t {k}") for k in range(3)]
    s_pre = [sum(c) for c in zip(*xs, strict=True)]
    s_post = [sum(c) for c in zip(*xs[:2], strict=True)]
    r_pre, r_post = sum(rs) % L, (rs[0] + rs[1]) % L
    wide = [(-1) ** i * (2**44 - i) for i in range(16)]
    r_wide = _blind("SEVER-DB p3 commitments wide")
    return {
        "source": "sever_refmodel_certs (pure-Python RFC 9496, DB-51); spec §9.3, §4.5, §5.3",
        "records": [
            _record("d384_spread", rec_a, _blind("SEVER-DB p3 commitments record a")),
            _record("d384_extremes", rec_b, L - 1),
        ],
        "transition": {
            "d": 16,
            "x": xs,
            "r": [encode_scalar(r).hex() for r in rs],
            "C_t": [encode(spec.commit(x, r)).hex() for x, r in zip(xs, rs, strict=True)],
            "S_pre": s_pre,
            "r_agg_pre": encode_scalar(r_pre).hex(),
            "C_S_pre": encode(spec.commit(s_pre, r_pre)).hex(),
            "S_post": s_post,
            "r_agg_post": encode_scalar(r_post).hex(),
            "C_S_post": encode(spec.commit(s_post, r_post)).hex(),
        },
        "groups": [
            {
                "name": "d16_wide_sums",
                "S": wide,
                "r_agg": encode_scalar(r_wide).hex(),
                "C_S": encode(spec.commit(wide, r_wide)).hex(),
            },
            {
                "name": "d16_empty",
                "S": [0] * 16,
                "r_agg": encode_scalar(0).hex(),
                "C_S": encode(spec.commit([0] * 16, 0)).hex(),
            },
        ],
        "identity": encode(IDENTITY).hex(),
    }


def scalar_vector() -> dict[str, Any]:
    """Appendix B vector 4: ``scalar(v)`` for ``v ∈ {0, 1, −1, 2^44, −2^44}`` (§4.5)."""
    vs = [0, 1, -1, 2**44, -(2**44)]
    return {
        "source": "sever_refmodel_certs (DB-51); spec §4.5; Appendix B vector 4",
        "scalars": [{"v": v, "scalar": encode_scalar(spec.scalar(v)).hex()} for v in vs],
    }


def posk_vector() -> dict[str, Any]:
    t = commitments_vector()["transition"]
    c_s_pre, c_t, c_s_post = (bytes.fromhex(t["C_S_pre"]), bytes.fromhex(t["C_t"][2]),
                              bytes.fromhex(t["C_S_post"]))  # fmt: skip
    scrambled_id = hashlib.sha512(b"SEVER-DB p3 posk scrambled_id").digest()
    collection_id = hashlib.sha512(b"SEVER-DB p3 posk collection_id").digest()[:16]
    lsn = 0x0102030405060708
    ctx = posk.ctx_bytes(c_s_pre, c_t, scrambled_id, lsn, collection_id)
    h, _ = spec.generators(16)
    a_fixed = encode(h * 7)  # Appendix B vector 3: any fixed point serves as A
    c = posk.challenge(c_s_post, a_fixed, ctx)
    c_swapped = posk.challenge(a_fixed, c_s_post, ctx)
    k_r = _blind("SEVER-DB p3 posk k_r")
    k = [_blind(f"SEVER-DB p3 posk k_{i}") for i in range(16)]
    r_post = int.from_bytes(bytes.fromhex(t["r_agg_post"]), "little")
    proof = posk.prove(t["S_post"], r_post, ctx, k_r, k)
    if not posk.verify(c_s_post, ctx, proof, 16) or c == c_swapped:
        raise RuntimeError("model self-check failed")
    return {
        "source": "sever_refmodel_certs (DB-51); spec §9.5; Appendix B vector 3",
        "ctx_fields": {
            "C_S_pre": t["C_S_pre"],
            "C_t": t["C_t"][2],
            "scrambled_id": scrambled_id.hex(),
            "database_lsn": lsn,
            "collection_id": collection_id.hex(),
        },
        "ctx": ctx.hex(),
        "vector3": {"C_S_post": t["C_S_post"], "A": a_fixed.hex(), "c": encode_scalar(c).hex()},
        "proof_d16": {
            "S_post": t["S_post"],
            "r_post": t["r_agg_post"],
            "C_S_post": t["C_S_post"],
            "k_r": encode_scalar(k_r).hex(),
            "k": [encode_scalar(x).hex() for x in k],
            "proof": proof.hex(),
        },
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="refmodel-certs-golden", description=__doc__)
    ap.add_argument("command", choices=["write", "check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    bad = 0
    for rel, data in (
        (OUT_GENERATORS, generators_vector()),
        (OUT_COMMITMENTS, commitments_vector()),
        (OUT_POSK, posk_vector()),
        (OUT_SCALARS, scalar_vector()),
    ):
        path, text = args.root / rel, _dump(data)
        if args.command == "write":
            path.write_text(text, encoding="utf-8")
            print(path)
            continue
        ok = path.is_file() and path.read_text(encoding="utf-8") == text
        bad += not ok
        print(f"{rel}: {'matches the model' if ok else 'DIFFERS from the model'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
