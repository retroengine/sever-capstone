"""The model's primitives against the RFC texts (``golden/p3_rfc*.json``, extracted mechanically by
``sever_testkit_p3.rfc_vectors``) and the RFCs' own definitions."""

import json
from pathlib import Path

import pytest

from sever_refmodel_certs import ristretto as r
from sever_refmodel_certs.xmd import expand_message_xmd_sha512

ROOT = Path(__file__).resolve().parents[3]
K3 = json.loads((ROOT / "golden/p3_rfc9380_k3_expand_xmd_sha512.json").read_text(encoding="utf-8"))
R9496 = json.loads((ROOT / "golden/p3_rfc9496_ristretto255.json").read_text(encoding="utf-8"))


def test_p3_model_constants_satisfy_their_rfc9496_definitions() -> None:
    p = r.P
    d = -121665 * pow(121666, p - 2, p) % p  # RFC 7748 §4.1: d = −121665/121666
    assert d == r.D
    assert r.SQRT_M1 * r.SQRT_M1 % p == p - 1
    assert r.SQRT_AD_MINUS_ONE**2 % p == (-d - 1) % p  # a·d − 1 with a = −1
    assert r.INVSQRT_A_MINUS_D**2 * ((-1 - d) % p) % p == 1  # 1/sqrt(a − d)
    assert (1 - d * d) % p == r.ONE_MINUS_D_SQ
    assert (d - 1) ** 2 % p == r.D_MINUS_ONE_SQ
    assert r.L == 2**252 + 27742317777372353535851937790883648493  # spec §2.1


def test_p3_model_expand_message_xmd_matches_rfc9380_k3() -> None:
    dst = K3["dst"].encode()
    for v in K3["vectors"]:
        got = expand_message_xmd_sha512(v["msg"].encode(), dst, v["len_in_bytes"])
        assert got.hex() == v["uniform_bytes"]


def test_p3_model_generator_multiples_match_rfc9496_a1() -> None:
    m = [bytes.fromhex(h) for h in R9496["generator_multiples"]]
    base = r.decode(m[1])
    for i, enc in enumerate(m):
        assert r.encode(base * i) == enc, f"B[{i}] = {i}·B"
        assert r.encode(r.decode(enc)) == enc
    assert r.encode(r.IDENTITY) == bytes(32)
    assert r.encode(base * r.L) == bytes(32)  # ℓ·B is the identity


def test_p3_model_decode_rejects_rfc9496_a2() -> None:
    for h in R9496["invalid_encodings"]:
        with pytest.raises(r.DecodeError):
            r.decode(bytes.fromhex(h))


def test_p3_model_element_derivation_matches_rfc9496_a3() -> None:
    for pair in R9496["from_uniform_bytes"]:
        assert r.encode(r.from_uniform_bytes(bytes.fromhex(pair["input"]))) == bytes.fromhex(
            pair["output"]
        )


def test_p3_model_scalars_reject_values_at_or_above_l() -> None:
    assert r.decode_scalar(r.encode_scalar(r.L - 1)) == r.L - 1
    for bad in (r.L, r.L + 1, 2**256 - 1):
        with pytest.raises(r.DecodeError):
            r.decode_scalar(bad.to_bytes(32, "little"))


def test_p3_model_group_laws_hold() -> None:
    b = r.decode(bytes.fromhex(R9496["generator_multiples"][1]))
    assert (b * 5 + b * 7).equals(b * 12)
    assert (b * 3 - b * 3).equals(r.IDENTITY)
    assert (b * 0).equals(r.IDENTITY)  # spec §9: a zero scalar gives the identity
    assert (b * (r.L - 1)).equals(-b)
