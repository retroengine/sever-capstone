"""ristretto255, expand_message and Ed25519 against published test vectors (spec §9.1-9.3, §4.5).

Both implementations, the demo engine's (sever_demo.crypto) and the independent verifier's
(sever_verify.ristretto), are checked against the same RFC vectors, and against each other.
"""

import json
import random
from pathlib import Path

import pytest

from sever_demo import crypto as ec
from sever_verify import ristretto as vr

VECTORS = Path(__file__).parent / "vectors"
R9496 = json.loads((VECTORS / "rfc9496_ristretto255.json").read_text(encoding="utf-8"))
R9380 = json.loads((VECTORS / "rfc9380_expand_xmd_sha512.json").read_text(encoding="utf-8"))
R8032 = json.loads((VECTORS / "rfc8032_ed25519.json").read_text(encoding="utf-8"))

# Spec §2.1, written out here, not imported.
ELL = 2**252 + 27742317777372353535851937790883648493
B = bytes.fromhex(R9496["multiples_of_generator"][1])


def test_group_order_matches_spec() -> None:
    assert ec.L == ELL
    assert vr.ORDER == ELL


@pytest.mark.parametrize("k", range(16))
def test_multiples_of_generator_rfc9496_a1(k: int) -> None:
    want = bytes.fromhex(R9496["multiples_of_generator"][k])
    assert ec.mul(k, B) == want
    assert vr.times(k, B) == want


def test_addition_walks_the_multiples_rfc9496_a1() -> None:
    # A.1: B[i+1] = B[i] + B[1], starting from the identity.
    acc_e, acc_v = ec.IDENTITY, vr.IDENTITY
    for want in R9496["multiples_of_generator"]:
        assert acc_e.hex() == want
        assert acc_v.hex() == want
        acc_e, acc_v = ec.point_add(acc_e, B), vr.add(acc_v, B)


@pytest.mark.parametrize("enc", R9496["invalid_encodings"])
def test_invalid_encodings_rejected_rfc9496_a2(enc: str) -> None:
    # §9.9: non-canonical encodings MUST be rejected.
    p = bytes.fromhex(enc)
    assert not ec.is_valid_point(p)
    assert not vr.is_point(p)
    with pytest.raises(ValueError, match="invalid point"):
        ec.point_add(p, B)
    with pytest.raises(ValueError, match="not a valid point"):
        vr.add(p, B)


@pytest.mark.parametrize("pair", R9496["from_uniform_bytes"])
def test_from_uniform_bytes_rfc9496_a3(pair: dict[str, str]) -> None:
    b = bytes.fromhex(pair["input"])
    assert ec.from_uniform_bytes(b).hex() == pair["output"]
    assert vr.from_uniform(b).hex() == pair["output"]


def test_from_uniform_bytes_same_output_rfc9496_a3() -> None:
    same = R9496["from_uniform_bytes_same_output"]
    assert len(same["inputs"]) == 4
    for inp in same["inputs"]:
        assert ec.from_uniform_bytes(bytes.fromhex(inp)).hex() == same["output"]
        assert vr.from_uniform(bytes.fromhex(inp)).hex() == same["output"]


@pytest.mark.parametrize(
    "vec", R9380["vectors"], ids=lambda v: f"{len(v['msg'])}-{v['len_in_bytes']}"
)
def test_expand_message_xmd_sha512_rfc9380_k3(vec: dict) -> None:
    msg, dst = vec["msg"].encode(), R9380["dst"].encode()
    assert ec.expand_message_xmd_sha512(msg, dst, vec["len_in_bytes"]).hex() == vec["uniform_bytes"]
    assert vr.expand_xmd_sha512(msg, dst, vec["len_in_bytes"]).hex() == vec["uniform_bytes"]


@pytest.mark.parametrize("t", R8032["tests"], ids=["test1", "test2", "test3"])
def test_ed25519_rfc8032_7_1(t: dict[str, str]) -> None:
    seed, msg = bytes.fromhex(t["secret"]), bytes.fromhex(t["message"])
    pk, sk = ec.ed25519_public_from_seed(seed)
    assert pk.hex() == t["public"]
    sig = ec.ed25519_sign(sk, msg)
    assert sig.hex() == t["signature"]  # Ed25519 is deterministic
    assert vr.ed25519_verify(pk, msg, sig)
    bad = bytes([sig[0] ^ 1]) + sig[1:]
    assert not vr.ed25519_verify(pk, msg, bad)
    assert not vr.ed25519_verify(pk, msg + b"x", sig)


def test_zero_scalar_gives_identity() -> None:
    # CLAUDE.md §7: scalar multiplication must accept the zero scalar (libsodium alone refuses).
    assert ec.mul(0, B) == bytes(32)
    assert vr.times(0, B) == bytes(32)
    assert ec.mul(ELL, B) == bytes(32)  # ℓ·B = identity
    assert ec.point_sub(B, B) == bytes(32)
    assert ec.point_add(bytes(32), B) == B
    assert ec.is_valid_point(bytes(32))


def test_scalar_mapping_appendix_b4() -> None:
    # §4.5 and Appendix B item 4: v in {0, 1, -1, 2^44, -2^44}.
    expected = {0: 0, 1: 1, -1: ELL - 1, 2**44: 2**44, -(2**44): ELL - 2**44}
    for v, want in expected.items():
        assert ec.scalar(v) == want
        assert vr.to_scalar(v) == want


def test_generators_section_9_2() -> None:
    # §9.2: H and G_0..G_383 are valid, distinct, not the identity, and both implementations agree.
    h, g = ec.generators(384)
    vh, vg = vr.generator_table(384)
    assert (h, g) == (vh, vg)
    points = [h, *g]
    assert len(set(points)) == 385
    assert all(ec.is_valid_point(p) and p != bytes(32) for p in points)


def test_commitment_is_additive() -> None:
    # §9.3: C(x1, r1) + C(x2, r2) = C(x1 + x2, r1 + r2); the basis of C_S = sum of C_t.
    rng = random.Random(42)  # test data only; no key or blinding value is ever seeded (§9.4)
    x1 = [rng.randint(-(2**24), 2**24) for _ in range(16)]
    x2 = [rng.randint(-(2**24), 2**24) for _ in range(16)]
    r1, r2 = rng.randrange(ELL), rng.randrange(ELL)
    total = ec.commit([a + b for a, b in zip(x1, x2, strict=True)], (r1 + r2) % ELL)
    assert ec.point_add(ec.commit(x1, r1), ec.commit(x2, r2)) == total
    assert vr.commitment([a + b for a, b in zip(x1, x2, strict=True)], (r1 + r2) % ELL) == total
    negated = ec.commit([-a for a in x1], (-r1) % ELL)
    assert ec.point_add(ec.commit(x1, r1), negated) == bytes(32)


def test_empty_commitment_is_identity() -> None:
    # §5.4: an empty group has S = 0 and r_agg = 0, so C_S is the identity.
    assert ec.commit([0] * 16, 0) == bytes(32)
    assert vr.commitment([0] * 16, 0) == bytes(32)


def test_random_scalars_come_from_the_os() -> None:
    a, b = ec.random_scalar(), ec.random_scalar()
    assert 0 <= a < ELL
    assert 0 <= b < ELL
    assert a != b
    many = ec.random_scalars(100)
    assert len(set(many)) == 100
