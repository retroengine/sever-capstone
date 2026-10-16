"""The attack suite of the certificate model (Build 3-4 §1.8; overview EX-4; the register
``spec/registers_p3.yaml``): every attack AT-1 … AT-20 built from the honest certificates of the
d = 16 scenario (``golden.certificate_vector(16)``). The attacker is a dishonest operator who holds
the operator's key, so most attacks are re-signed (``resign``) and reach the rule under attack;
AT-4 is not, to show that the trailer covers every field. Written from the spec text; the verifier
(C-16) is checked against these certificates and the step the model rejects each one at."""

import dataclasses
from collections.abc import Callable
from functools import cache
from typing import Any, Final

from sever_refmodel_certs import cert, ed25519, golden, posk
from sever_refmodel_certs.ristretto import L, P

D: Final = 16


@cache
def scenario() -> dict[str, Any]:
    return golden.certificate_vector(D)


def anchors(v: dict[str, Any]) -> cert.Anchors:
    ops = {int(e): bytes.fromhex(k["public"]) for e, k in v["keys"]["operator"].items()}
    wit = {(i, 0): bytes.fromhex(w["public"]) for i, w in enumerate(v["keys"]["witness_epoch0"])}
    return cert.Anchors(ops, wit, v["d"])


def tags(which: str) -> dict[int, bytes]:
    return {int(t): bytes.fromhex(h) for t, h in scenario()[which]["tags"].items()}


def resign(values: dict[int, bytes]) -> bytes:
    """A dishonest operator holds the key: re-sign with operator epoch 1."""
    return cert.sign_certificate(
        values, bytes.fromhex(scenario()["keys"]["operator"]["1"]["secret"])
    )


def _flip(b: bytes, i: int = 0) -> bytes:
    return b[:i] + bytes([b[i] ^ 1]) + b[i + 1 :]


def _inclusion(values: dict[int, bytes]) -> cert.Inclusion:
    return cert.Inclusion.parse(values[6])


def _with_inclusion(values: dict[int, bytes], **kw: Any) -> dict[int, bytes]:
    return values | {6: dataclasses.replace(_inclusion(values), **kw).to_bytes()}


def _cosigs(
    values: dict[int, bytes],
    keep: list[int],
    edit: Callable[[cert.Cosig], cert.Cosig] = lambda c: c,
) -> dict[int, bytes]:
    v = values[7]
    cs = [
        cert.Cosig(
            v[1 + 69 * i],
            int.from_bytes(v[2 + 69 * i : 6 + 69 * i], "big"),
            v[6 + 69 * i : 70 + 69 * i],
        )
        for i in range(v[0])
    ]
    return values | {7: cert.cosignatures_value([edit(cs[i]) for i in keep])}


def _encode_raw(entries: list[tuple[int, bytes]]) -> bytes:
    return b"".join(cert.tlv(t, val) for t, val in entries)


def attacks() -> dict[str, list[bytes]]:
    v = scenario()
    g, h = tags("group_deletion"), tags("holding_deletion")
    keys = v["keys"]
    op0 = bytes.fromhex(keys["operator"]["0"]["secret"])
    w0 = bytes.fromhex(keys["witness_epoch0"][0]["secret"])
    cp = _inclusion(g).checkpoint
    other = cert.Checkpoint(
        cp.tree_size,
        cp.root,
        cp.timestamp_ms + 1,
        cp.epoch,
        ed25519.sign(op0, cert.checkpoint_message(cp.tree_size, cp.root, cp.timestamp_ms + 1, 0)),
    )

    def cosign_other(c: cert.Cosig) -> cert.Cosig:
        sk = bytes.fromhex(keys["witness_epoch0"][c.index]["secret"])
        return cert.Cosig(c.index, c.epoch, ed25519.sign(sk, cert.cosign_message(other.message())))

    # AT-2: a proof made for another context (the same group, deletion at another lsn).
    ctx_other = posk.ctx_bytes(g[2], g[1], g[9], 99, g[13])
    s_post = v["group_deletion"]["S_post"]
    r_post = int.from_bytes(bytes.fromhex(v["group_deletion"]["r_agg_post"]), "little")
    copied = posk.prove(s_post, r_post, ctx_other, 5, list(range(1, D + 1)))
    leaf = _inclusion(g).leaf
    other_coll = _flip(leaf, 1)  # leaf collection_id byte 0
    body_ok = cert.body(g)
    sig = bytes.fromhex(v["group_deletion"]["operator_signature"])
    good = body_ok + cert.tlv(0xFF, sig)
    entries = [(t, g[t]) for t in cert.TAGS]
    big_scalar = (L + 1).to_bytes(32, "little")
    return {
        "AT-1": [
            resign(g | {4: g[4][:32] + bytes(32) + g[4][64:]}),
            resign(g | {4: _flip(g[4], 40)}),
        ],
        "AT-2": [resign(g | {4: copied})],
        "AT-3": [resign(g | {1: bytes.fromhex(v["records"][0]["C_t"])})],
        "AT-4": [_flip(good, sum(5 + len(g[t]) for t in range(1, k)) + 5) for k in cert.TAGS]
        + [_flip(good, len(good) - 1)],
        "AT-5": [resign(g | {8: (7).to_bytes(4, "big")})],
        "AT-6": [resign(_with_inclusion(g, leaf=other_coll))],
        "AT-7": [
            resign(
                _with_inclusion(g, path=[_flip(_inclusion(g).path[0]), *_inclusion(g).path[1:]])
            ),
            resign(_with_inclusion(g, leaf_index=3)),
        ],
        "AT-8": [
            resign(
                _with_inclusion(
                    g,
                    checkpoint=cert.Checkpoint(
                        cp.tree_size,
                        cp.root,
                        cp.timestamp_ms,
                        cp.epoch,
                        ed25519.sign(w0, cp.message()),
                    ),
                )
            )
        ],
        "AT-9": [resign(_cosigs(g, [0, 1, 2]))],
        "AT-10": [
            resign(_cosigs(g, [0, 1, 2, 3, 4], cosign_other)),
            resign(_with_inclusion(g, checkpoint=other)),
        ],
        "AT-11": [
            resign(g | {3: P.to_bytes(32, "little")}),
            resign(g | {4: g[4][:64] + big_scalar + g[4][96:]}),
            resign(g | {4: g[4][:32] + big_scalar + g[4][64:]}),
        ],
        "AT-12": [resign(g | {1: bytes(32)})],
        "AT-13": [
            resign(h | {2: g[2]}),
            resign(h | {3: g[3]}),
            resign(h | {11: b"\x01"}),
            resign(h | {2: g[2], 3: g[3], 4: g[4]}),
        ],
        "AT-14": [resign(g | {11: b"\x01"})],
        "AT-15": [
            resign(g | {10: (2).to_bytes(8, "big")}),
            resign(g | {10: (1).to_bytes(8, "big")}),
        ],
        "AT-16": [
            _encode_raw(entries[:4] + entries[5:]) + cert.tlv(0xFF, sig),
            _encode_raw(entries[:5] + entries[4:]) + cert.tlv(0xFF, sig),
            _encode_raw([*entries[:3], entries[4], entries[3], *entries[5:]]) + cert.tlv(0xFF, sig),
            good + b"\x00",
            body_ok,
        ],
        "AT-17": [resign(_cosigs(g, [0, 1, 2, 2])), resign(_cosigs(g, [0, 0, 0, 0, 1]))],
        "AT-18": [
            resign(g | {9: g[9][:63]}),
            resign(g | {11: b"\x02"}),
            resign(g | {12: b"\x02"}),
            resign(g | {1: g[1] + b"\x00"}),
            resign(g | {10: g[10][1:]}),
            body_ok + bytes([0xFF]) + (63).to_bytes(4, "big") + sig[:63],
        ],
        "AT-19": [
            resign(_with_inclusion(g, leaf=b"\x02" + leaf[1:])),
            resign(g | {6: b"\x02" + g[6][1:]}),
        ],
        "AT-20": [
            resign(
                _with_inclusion(
                    g,
                    checkpoint=cert.Checkpoint(
                        cp.tree_size,
                        cp.root,
                        cp.timestamp_ms,
                        9,
                        ed25519.sign(
                            op0, cert.checkpoint_message(cp.tree_size, cp.root, cp.timestamp_ms, 9)
                        ),
                    ),
                )
            ),
            resign(
                _cosigs(
                    g,
                    [0, 1, 2, 3],
                    lambda c: cert.Cosig(7 if c.index == 3 else c.index, c.epoch, c.signature),
                )
            ),
            resign(
                _cosigs(
                    g,
                    [0, 1, 2, 3],
                    lambda c: cert.Cosig(c.index, 3 if c.index == 3 else c.epoch, c.signature),
                )
            ),
        ],
    }


def attacks_vector() -> dict[str, Any]:
    """``golden/p3_attacks.json``: the d = 16 anchors (as the engine publishes them), the honest
    certificates, a certificate that empties its group, and every attack variant with the §11.3
    step at which this model rejects it."""
    v = scenario()
    a = anchors(v)
    g = tags("group_deletion")
    c_s_pre = bytes.fromhex(v["records"][2]["C_t"])  # a group holding only this record
    ctx = posk.ctx_bytes(c_s_pre, g[1], g[9], 5, g[13])
    proof = posk.prove([0] * D, 0, ctx, 11, list(range(2, D + 2)))
    emptied = g | {2: c_s_pre, 3: cert.identity_bytes(), 4: proof, 11: b"\x01"}
    rows: list[dict[str, Any]] = []
    for aid, variants in attacks().items():
        for k, c in enumerate(
            variants + ([resign(emptied | {11: b"\x00"})] if aid == "AT-14" else [])
        ):
            try:
                cert.verify(c, a)
            except cert.VerifyError as e:
                rows.append({"id": aid, "variant": k, "certificate": c.hex(), "model_step": e.step,
                             "model_reason": e.reason})  # fmt: skip
                continue
            raise AssertionError(f"{aid} variant {k} is accepted by the model")
    return {
        "source": "sever_refmodel_certs.attacks (spec §11.3; register spec/registers_p3.yaml)",
        "d": D,
        "anchors": {
            "d": D,
            "operator": {str(e): k.hex() for e, k in sorted(a.operators.items())},
            "witnesses": [
                {str(e): k.hex() for (i, e), k in sorted(a.witnesses.items()) if i == w}
                for w in range(5)
            ],
        },
        "honest": {
            "group": v["group_deletion"]["certificate"],
            "holding": v["holding_deletion"]["certificate"],
            "emptied": resign(emptied).hex(),
        },
        "attacks": rows,
    }
