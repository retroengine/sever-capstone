"""Appendix B golden vectors that Part 3 owns, written by this model (Build 3-4 §3.4: the build part
that owns a vector generates it once, from an implementation independent of the engine).

    PYTHONPATH=python uv run python -m sever_refmodel_certs.golden write   # once; then committed
    PYTHONPATH=python uv run python -m sever_refmodel_certs.golden check   # Fast tier

Files: ``p3_generators.json`` (Appendix B vectors 1 and 2: ``H``, ``G_0``, ``G_383``, §9.2;
``gdigest``, §9.6), ``p3_commitments.json`` (§9.3 record and group commitments and the transition
check), ``p3_scalar_map.json`` (Appendix B vector 4, §4.5), ``p3_full_blob.json`` (Appendix B
vector 8, full form), ``p3_group_stream.json`` (a scripted insert/delete stream and every state,
§5.3–5.5), ``p3_merkle_7.json`` (Appendix B vector 9, RFC 9162 proofs of a 7-leaf tree) and
``p3_posk.json`` (Appendix B vector 3: a fixed challenge, §9.5; and one complete proof at d = 16
with fixed nonces) and ``p3_certificates.json`` (Appendix B vector 6: an honest group-deletion
certificate and a holding-area certificate at d = 384 with every intermediate value, §10–§11) and
``p3_attacks.json`` (the attack suite AT-1 … AT-20 at d = 16 with the §11.3 step at which this model
rejects each variant, for the verifier, C-16) and ``p3_audit.json`` (a scripted log export and the
faults AF-1 … AF-5 with the kinds this model's auditor reports, for ``sever-audit``, C-17).
Once committed, a golden file changes only with a recorded reason (CLAUDE.md §6.2).

The blinding values, nonces and signing keys in these files are fixed test data (SHA-512 of a
label), never a database's ``r_t`` or key: production ``r_t``, nonces and keys come only from the
OS CSPRNG (§9.4, §9.6, §9.8).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

from sever_refmodel_certs import cert, ed25519, merkle, posk, spec
from sever_refmodel_certs.group import CertGroup
from sever_refmodel_certs.ristretto import IDENTITY, L, encode, encode_scalar

OUT_GENERATORS: Final = Path("golden/p3_generators.json")
OUT_COMMITMENTS: Final = Path("golden/p3_commitments.json")
OUT_POSK: Final = Path("golden/p3_posk.json")
OUT_SCALARS: Final = Path("golden/p3_scalar_map.json")
OUT_FULL_BLOB: Final = Path("golden/p3_full_blob.json")
OUT_STREAM: Final = Path("golden/p3_group_stream.json")
OUT_MERKLE: Final = Path("golden/p3_merkle_7.json")
OUT_CERTS: Final = Path("golden/p3_certificates.json")
OUT_ATTACKS: Final = Path("golden/p3_attacks.json")
OUT_AUDIT: Final = Path("golden/p3_audit.json")


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


def _state(g: CertGroup) -> dict[str, Any]:
    return {"n": g.n, "S": g.s, "r_agg": encode_scalar(g.r_agg).hex(), "C_S": encode(g.c_s).hex(),
            "blob": g.full_blob().hex()}  # fmt: skip


def full_blob_vector(root: Path) -> dict[str, Any]:
    """Appendix B vector 8, full form: Part 1's three-member group (golden/p1_core_blob.json) with
    fixed test blinding values."""
    core = json.loads((root / "golden/p1_core_blob.json").read_text(encoding="utf-8"))
    g = CertGroup(core["d"])
    members = []
    for k, (rid, x) in enumerate(core["members"].items()):
        r = _blind(f"SEVER-DB p3 full blob r_t {k}")
        g.insert(rid, tuple(x), r)
        members.append({"id": rid, "x": x, "r_t": encode_scalar(r).hex()})
    return {"source": "sever_refmodel_certs (DB-51); spec §5.5 full form (DB-47); Appendix B 8",
            "d": core["d"], "members": members, **_state(g)}  # fmt: skip


def stream_vector() -> dict[str, Any]:
    """A scripted stream at d = 8 and the full state after each step (§5.3, §5.4, §5.5)."""
    big = 2**24 + 16
    xs = {
        "a": (1, -2, 3, -4, 5, -6, 7, -8),
        "Z": (big, -big, 0, 0, big, -big, 1, -1),
        "é": (-(2**24), 2**24, 9, 9, 9, 9, -9, 0),
        "a2": (0, 0, 0, 0, 0, 0, 0, 1),
    }
    script = [("insert", "a", "a"), ("insert", "Z", "Z"), ("insert", "é", "é"), ("delete", "Z", ""),
              ("delete", "Z", ""), ("insert", "Z", "a2"), ("delete", "a", ""), ("delete", "é", ""),
              ("delete", "Z", "")]  # fmt: skip
    g = CertGroup(8)
    steps: list[dict[str, Any]] = []
    for k, (op, rid, xkey) in enumerate(script):
        step: dict[str, Any] = {"op": op, "id": rid}
        if op == "insert":
            r = _blind(f"SEVER-DB p3 stream r_t {k}")
            step |= {"x": list(xs[xkey]), "r_t": encode_scalar(r).hex()}
            step["C_t"] = g.insert(rid, xs[xkey], r).hex()
        else:
            rem = g.delete(rid)
            step["absent"] = rem is None
            if rem is not None:
                step |= {"C_S_pre": rem.c_s_pre.hex(), "C_t": rem.c_t.hex(),
                         "C_S_post": rem.c_s_post.hex(),
                         "group_emptied": rem.group_emptied}  # fmt: skip
        step["after"] = _state(g)
        steps.append(step)
    return {"source": "sever_refmodel_certs (DB-51); spec §5.3-5.5, §9.3-9.4", "d": 8,
            "steps": steps}  # fmt: skip


def merkle_vector() -> dict[str, Any]:
    """Appendix B vector 9: RFC 9162 roots, inclusion and consistency proofs of a 7-leaf tree."""
    d = [f"d{i}".encode() for i in range(7)]
    return {
        "source": "sever_refmodel_certs (RFC 9162 §2.1 definitions); spec §10.1; Appendix B 9",
        "leaves": [x.hex() for x in d],
        "roots": [merkle.mth(d[:n]).hex() for n in range(8)],
        "inclusion": [
            {"index": i, "size": n, "path": [h.hex() for h in merkle.path(i, d[:n])]}
            for n in range(1, 8)
            for i in range(n)
        ],
        "consistency": [
            {"first": a, "second": n, "proof": [h.hex() for h in merkle.proof(a, d[:n])]}
            for n in range(2, 8)
            for a in range(1, n)
        ],
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


GENESIS_MS: Final = 1_790_000_000_000
EPOCH_MS: Final = 90 * 24 * 60 * 60 * 1000  # §9.8


def _key(label: str) -> dict[str, str]:
    sk = cert.secret(label)
    return {"secret": sk.hex(), "public": ed25519.public_key(sk).hex()}


def certificate_vector(d: int = spec.D_V1) -> dict[str, Any]:
    """Appendix B vector 6 (at d = 384; tests use a smaller d): five records inserted under one user
    key (leaves 0–4), a checkpoint at tree size 5 in operator epoch 0 with all five cosignatures,
    then record ``C`` (leaf 2) deleted from its group (``A``, ``B``, ``C``) at ``database_lsn`` 5
    and record ``D`` (leaf 3) deleted from the holding area at 6, both certified in operator epoch
    1 (old keys stay resolvable, §9.8)."""
    operators = {e: _key(f"SEVER-DB p3 cert operator epoch {e}") for e in (0, 1)}
    witnesses = [_key(f"SEVER-DB p3 cert witness {i} epoch 0") for i in range(5)]
    user = _key("SEVER-DB p3 cert user")
    usk = bytes.fromhex(user["secret"])
    coll = hashlib.sha512(b"SEVER-DB p3 cert collection_id").digest()[:16]
    records: list[dict[str, Any]] = []
    for k, name in enumerate("ABCDE"):
        x = [((k + 1) * 7919 * (i + 5)) % 2**25 - 2**24 for i in range(d)]
        r = _blind(f"SEVER-DB p3 cert r_t {name}")
        c_t = encode(spec.commit(x, r))
        sid = hashlib.sha512(f"SEVER-DB p3 cert scrambled_id {name}".encode()).digest()
        usig = ed25519.sign(usk, cert.insert_message(coll, c_t))
        leaf = cert.insert_leaf(coll, sid, c_t, bytes.fromhex(user["public"]), usig)
        records.append(
            {
                "name": name,
                "x": x,
                "r_t": encode_scalar(r).hex(),
                "C_t": c_t.hex(),
                "scrambled_id": sid.hex(),
                "user_signature": usig.hex(),
                "leaf_index": k,
                "leaf": leaf.hex(),
                "leaf_hash": merkle.leaf_hash(leaf).hex(),
            }
        )
    leaves = [bytes.fromhex(r["leaf"]) for r in records]
    root = merkle.mth(leaves)
    ts = GENESIS_MS + 1000
    cp_msg = cert.checkpoint_message(len(leaves), root, ts, 0)
    cp = cert.Checkpoint(
        len(leaves), root, ts, 0, ed25519.sign(bytes.fromhex(operators[0]["secret"]), cp_msg)
    )
    cosigs = [
        cert.Cosig(i, 0, ed25519.sign(bytes.fromhex(w["secret"]), cert.cosign_message(cp_msg)))
        for i, w in enumerate(witnesses)
    ]
    anchors = cert.Anchors(
        {e: bytes.fromhex(k["public"]) for e, k in operators.items()},
        {(i, 0): bytes.fromhex(w["public"]) for i, w in enumerate(witnesses)},
        d,
    )
    op1 = bytes.fromhex(operators[1]["secret"])
    certified_ms = GENESIS_MS + EPOCH_MS + 5000

    def common(rec: dict[str, Any], lsn: int) -> tuple[dict[int, bytes], cert.Inclusion]:
        inc = cert.Inclusion(
            bytes.fromhex(rec["leaf"]),
            rec["leaf_index"],
            cp,
            merkle.path(rec["leaf_index"], leaves),
        )
        values = {
            1: bytes.fromhex(rec["C_t"]),
            5: bytes.fromhex(rec["user_signature"]),
            6: inc.to_bytes(),
            7: cert.cosignatures_value(cosigs),
            8: (1).to_bytes(4, "big"),
            9: bytes.fromhex(rec["scrambled_id"]),
            10: lsn.to_bytes(8, "big"),
            13: coll,
        }
        return values, inc

    # Group deletion of C from the group {A, B, C}.
    a, b, c = records[0], records[1], records[2]
    s_pre = [sum(t) for t in zip(a["x"], b["x"], c["x"], strict=True)]
    s_post = [sum(t) for t in zip(a["x"], b["x"], strict=True)]
    rs = [int.from_bytes(bytes.fromhex(r["r_t"]), "little") for r in (a, b, c)]
    r_pre, r_post = sum(rs) % L, (rs[0] + rs[1]) % L
    c_s_pre, c_s_post = encode(spec.commit(s_pre, r_pre)), encode(spec.commit(s_post, r_post))
    lsn_g = 5
    ctx = posk.ctx_bytes(
        c_s_pre, bytes.fromhex(c["C_t"]), bytes.fromhex(c["scrambled_id"]), lsn_g, coll
    )
    k_r = _blind("SEVER-DB p3 cert posk k_r")
    nonces = [_blind(f"SEVER-DB p3 cert posk k_{i}") for i in range(d)]
    proof = posk.prove(s_post, r_post, ctx, k_r, nonces)
    gv, g_inc = common(c, lsn_g)
    gv |= {2: c_s_pre, 3: c_s_post, 4: proof, 11: b"\x00", 12: b"\x00"}
    group_cert = cert.sign_certificate(gv, op1)
    # Holding-area deletion of D.
    lsn_h = 6
    hv, h_inc = common(records[3], lsn_h)
    hv |= {2: b"", 3: b"", 4: b"", 11: b"\x00", 12: b"\x01"}
    holding_cert = cert.sign_certificate(hv, op1)
    for crt in (group_cert, holding_cert):
        cert.verify(crt, anchors)  # the model's own §11.3 check; raises on failure

    def out(values: dict[int, bytes], crt: bytes, inc: cert.Inclusion) -> dict[str, Any]:
        return {
            "tags": {str(t): values[t].hex() for t in cert.TAGS},
            "inclusion": {"leaf_index": inc.leaf_index, "path": [h.hex() for h in inc.path]},
            "body": crt[:-69].hex(),
            "operator_signature": crt[-64:].hex(),
            "certificate": crt.hex(),
            "size": len(crt),
        }

    return {
        "source": "sever_refmodel_certs (DB-51; pure-Python RFC 8032 Ed25519); spec §9.8, §10, "
        "§11.1-11.3; Appendix B vector 6",
        "d": d,
        "genesis_ms": GENESIS_MS,
        "certified_ms": certified_ms,
        "collection_id": coll.hex(),
        "keys": {
            "operator": {str(e): k for e, k in operators.items()},
            "witness_epoch0": witnesses,
            "user": user,
        },
        "records": records,
        "tree": {"size": len(leaves), "root": root.hex()},
        "checkpoint": {
            "tree_size": cp.tree_size,
            "root": root.hex(),
            "timestamp_ms": ts,
            "epoch": 0,
            "message": cp_msg.hex(),
            "operator_signature": cp.signature.hex(),
            "encoded": cp.to_bytes().hex(),
            "cosign_message": cert.cosign_message(cp_msg).hex(),
        },
        "cosignatures": [
            {"witness_index": x.index, "witness_epoch": x.epoch, "signature": x.signature.hex()}
            for x in cosigs
        ],
        "group_deletion": {
            "record": "C",
            "S_pre": s_pre,
            "r_agg_pre": encode_scalar(r_pre).hex(),
            "C_S_pre": c_s_pre.hex(),
            "S_post": s_post,
            "r_agg_post": encode_scalar(r_post).hex(),
            "C_S_post": c_s_post.hex(),
            "database_lsn": lsn_g,
            "ctx": ctx.hex(),
            "k_r": encode_scalar(k_r).hex(),
            "k": [encode_scalar(x).hex() for x in nonces],
            "challenge": encode_scalar(posk.challenge(c_s_post, proof[:32], ctx)).hex(),
            **out(gv, group_cert, g_inc),
        },
        "holding_deletion": {"record": "D", "database_lsn": lsn_h, **out(hv, holding_cert, h_inc)},
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="refmodel-certs-golden", description=__doc__)
    ap.add_argument("command", choices=["write", "check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    from sever_refmodel_certs.attacks import attacks_vector  # it builds on this module
    from sever_refmodel_certs.audit import audit_vector

    bad = 0
    for rel, data in (
        (OUT_GENERATORS, generators_vector()),
        (OUT_COMMITMENTS, commitments_vector()),
        (OUT_POSK, posk_vector()),
        (OUT_SCALARS, scalar_vector()),
        (OUT_FULL_BLOB, full_blob_vector(args.root)),
        (OUT_STREAM, stream_vector()),
        (OUT_MERKLE, merkle_vector()),
        (OUT_CERTS, certificate_vector()),
        (OUT_ATTACKS, attacks_vector()),
        (OUT_AUDIT, audit_vector()),
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
