"""The certificate model (§11) against the spec: Ed25519 against RFC 8032's own vectors, the §11.1
layout and Appendix A size worked out by hand, and §11.3: the honest certificates verify, and every
attack of the register (``spec/registers_p3.yaml``) is rejected at one of the steps it lists."""

import json
import re
from pathlib import Path

import pytest

from sever_refmodel_certs import cert, ed25519, golden, merkle, posk
from sever_refmodel_certs.attacks import D, anchors, attacks, resign, scenario, tags
from sever_refmodel_certs.ristretto import L, P

ROOT = Path(__file__).resolve().parents[3]
RFC8032 = json.loads((ROOT / "golden/p3_rfc8032_ed25519.json").read_text(encoding="utf-8"))


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


def test_p3_model_every_registered_attack_is_rejected_at_a_listed_step() -> None:
    text = (ROOT / "spec/registers_p3.yaml").read_text(encoding="utf-8")
    register = {m[1]: [int(x) for x in m[2].split(",")]
                for m in re.finditer(r"\{id: (AT-\d+),.*?steps: \[([\d, ]+)\]", text)}  # fmt: skip
    assert len(register) == 20
    built = attacks()
    assert sorted(built) == sorted(register)
    for aid, steps in register.items():
        assert built[aid], aid
        for k, c in enumerate(built[aid]):
            step = rejected_at(c)
            assert step in steps, f"{aid} variant {k} rejected at step {step}"
    assert len(built["AT-4"]) == 14  # tags 1–13 and the trailer


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
