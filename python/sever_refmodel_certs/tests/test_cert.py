"""The certificate model (§11) against the spec: Ed25519 against RFC 8032's own vectors, the §11.1
layout and Appendix A size worked out by hand, and §11.3: the honest certificates verify, and every
attack of the register (``spec/registers_p3.yaml``) is rejected at one of the steps it lists."""

import dataclasses
import json
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from sever_refmodel_certs import cert, ed25519, golden, merkle, posk
from sever_refmodel_certs.ristretto import L, P

ROOT = Path(__file__).resolve().parents[3]
RFC8032 = json.loads((ROOT / "golden/p3_rfc8032_ed25519.json").read_text(encoding="utf-8"))
D = 16


def test_p3_model_ed25519_matches_rfc8032_section_7_1() -> None:
    for v in RFC8032["vectors"]:
        sk, msg = bytes.fromhex(v["secret_key"]), bytes.fromhex(v["message"])
        pk, sig = bytes.fromhex(v["public_key"]), bytes.fromhex(v["signature"])
        assert ed25519.public_key(sk) == pk, v["name"]
        assert ed25519.sign(sk, msg) == sig, v["name"]
        assert ed25519.verify(pk, msg, sig)
        assert not ed25519.verify(pk, msg + b"\x00", sig)


def test_p3_model_ed25519_is_strict() -> None:
    v = RFC8032["vectors"][0]
    pk, sig = bytes.fromhex(v["public_key"]), bytes.fromhex(v["signature"])
    s = int.from_bytes(sig[32:], "little")
    # S + ℓ satisfies the equation but is not canonical (RFC 8032 §5.1.7 step 1, spec §9.8).
    assert not ed25519.verify(pk, b"", sig[:32] + (s + L).to_bytes(32, "little"))
    # The identity (y = 1) is a small-order key: its "signature" R = identity, S = 0 verifies under
    # the plain equation for every message, and must be refused.
    ident = (1).to_bytes(32, "little")
    assert not ed25519.verify(ident, b"any", ident + bytes(32))
    # y = p is a non-canonical encoding of y = 0.
    assert not ed25519.verify(P.to_bytes(32, "little"), b"", sig)


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


def rejected_at(c: bytes) -> int:
    with pytest.raises(cert.VerifyError) as e:
        cert.verify(c, anchors(scenario()))
    return e.value.step


def test_p3_model_golden_certificates_are_what_the_model_writes() -> None:
    assert golden.main(["check", "--root", str(ROOT)]) == 0


def test_p3_model_honest_certificates_verify() -> None:
    v = scenario()
    for which in ("group_deletion", "holding_deletion"):
        cert.verify(bytes.fromhex(v[which]["certificate"]), anchors(v))


def test_p3_model_layout_and_size_match_section_11_and_appendix_a() -> None:
    v = json.loads((ROOT / "golden/p3_certificates.json").read_text(encoding="utf-8"))
    c = bytes.fromhex(v["group_deletion"]["certificate"])
    # Walk the TLVs by hand (§11.1): tags 1…13 then 0xFF, each u8 tag ‖ u32be length.
    pos, seen = 0, []
    while pos < len(c):
        seen.append((c[pos], int.from_bytes(c[pos + 1 : pos + 5], "big")))
        pos += 5 + seen[-1][1]
    path = len(v["group_deletion"]["inclusion"]["path"])
    tag6 = 1 + 209 + 8 + 116 + 1 + 32 * path  # §11.2
    assert seen == [
        (1, 32),
        (2, 32),
        (3, 32),
        (4, 12_352),
        (5, 64),
        (6, tag6),
        (7, 1 + 5 * 69),
        (8, 4),
        (9, 64),
        (10, 8),
        (11, 1),
        (12, 1),
        (13, 16),
        (0xFF, 64),
    ]
    # Appendix A: 14,093 bytes with a 21-hash path and five cosignatures; this one has `path`.
    assert len(c) == 14_093 - 32 * (21 - path)
    h = bytes.fromhex(v["holding_deletion"]["certificate"])
    assert len(h) == len(c) - 2 * 32 - 12_352  # tags 2, 3 (32 each) and 4 empty (§11.1)
    assert v["group_deletion"]["tags"]["12"] == "00"
    assert v["holding_deletion"]["tags"]["12"] == "01"


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


def _attacks() -> dict[str, list[bytes]]:
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


def test_p3_model_every_registered_attack_is_rejected_at_a_listed_step() -> None:
    text = (ROOT / "spec/registers_p3.yaml").read_text(encoding="utf-8")
    register = {m[1]: [int(x) for x in m[2].split(",")]
                for m in re.finditer(r"\{id: (AT-\d+),.*?steps: \[([\d, ]+)\]", text)}  # fmt: skip
    assert len(register) == 20
    attacks = _attacks()
    assert sorted(attacks) == sorted(register)
    for aid, steps in register.items():
        assert attacks[aid], aid
        for k, c in enumerate(attacks[aid]):
            step = rejected_at(c)
            assert step in steps, f"{aid} variant {k} rejected at step {step}"
    assert len(attacks["AT-4"]) == 14  # tags 1–13 and the trailer


def test_p3_model_emptying_the_group_sets_tag_11() -> None:
    # A one-member group: deleting its only member leaves C_S_post = identity (§5.4), tag 11 = 1.
    v = scenario()
    g = tags("group_deletion")
    c_s_pre = bytes.fromhex(v["records"][2]["C_t"])  # the group held only this record
    ident = cert.identity_bytes()
    ctx = posk.ctx_bytes(c_s_pre, g[1], g[9], 5, g[13])
    proof = posk.prove([0] * D, 0, ctx, 11, list(range(2, D + 2)))
    emptied = g | {2: c_s_pre, 3: ident, 4: proof, 11: b"\x01"}
    cert.verify(resign(emptied), anchors(v))
    assert rejected_at(resign(emptied | {11: b"\x00"})) == 6


def test_p3_model_inclusion_path_matches_the_rfc9162_model() -> None:
    v = scenario()
    leaves = [bytes.fromhex(r["leaf"]) for r in v["records"]]
    for which in ("group_deletion", "holding_deletion"):
        inc = v[which]["inclusion"]
        assert [bytes.fromhex(h) for h in inc["path"]] == merkle.path(inc["leaf_index"], leaves)
