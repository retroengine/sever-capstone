"""Proof of knowledge of the group state (spec §9.5; Appendix B item 3).

The prover is the engine's (sever_demo.posk); the checker is the independent verifier's
(sever_verify.certificate.verify_proof). The challenge formula is written out here from §9.5.
"""

import hashlib
import os
import random

import pytest

from sever_demo import posk
from sever_verify.certificate import verify_proof
from sever_verify.ristretto import ORDER, commitment

D = 16


def statement() -> tuple[int, list[int], bytes, bytes]:
    """A random group state (r_post, S_post), its commitment, and a deletion context."""
    rng = random.Random(7)  # test data only, never key or nonce material (§9.6)
    s_post = [rng.randint(-(2**40), 2**40) for _ in range(D)]
    r_post = rng.randrange(ORDER)
    c_s_post = commitment(s_post, r_post)
    ctx = posk.context(os.urandom(32), os.urandom(32), os.urandom(64), 17, os.urandom(16))
    return r_post, s_post, c_s_post, ctx


def test_context_is_152_bytes_in_spec_order() -> None:
    a, b, sid, cid = b"\x01" * 32, b"\x02" * 32, b"\x03" * 64, b"\x04" * 16
    ctx = posk.context(a, b, sid, 9, cid)
    assert ctx == a + b + sid + (9).to_bytes(8, "big") + cid
    assert len(ctx) == 152
    with pytest.raises(ValueError, match="wrong length"):
        posk.context(a, b, sid[:63], 9, cid)


def test_challenge_formula() -> None:
    # §9.5: c = SHA-512(DST_POSK ‖ C_S_post ‖ A ‖ ctx) read little-endian, mod ℓ.
    c_s_post, a, ctx = os.urandom(32), os.urandom(32), os.urandom(152)
    digest = hashlib.sha512(b"SEVERDB_POSK_V1" + c_s_post + a + ctx).digest()
    assert posk.challenge(c_s_post, a, ctx) == int.from_bytes(digest, "little") % ORDER


@pytest.mark.mustfail
def test_challenge_changes_when_a_and_statement_swap() -> None:
    # Appendix B item 3: swapping A and C_S_post must change c.
    x, y, ctx = os.urandom(32), os.urandom(32), os.urandom(152)
    assert posk.challenge(x, y, ctx) != posk.challenge(y, x, ctx)


def test_honest_proof_verifies() -> None:
    r_post, s_post, c_s_post, ctx = statement()
    proof = posk.prove(r_post, s_post, c_s_post, ctx)
    assert len(proof) == 32 + 32 + 32 * D
    assert verify_proof(proof, c_s_post, ctx, D)


def test_honest_proof_verifies_at_d_384() -> None:
    # §9.5: 12,352 bytes at d = 384.
    rng = random.Random(3)
    s_post = [rng.randint(-(2**40), 2**40) for _ in range(384)]
    r_post = rng.randrange(ORDER)
    c_s_post = commitment(s_post, r_post)
    ctx = os.urandom(152)
    proof = posk.prove(r_post, s_post, c_s_post, ctx)
    assert len(proof) == 12_352
    assert verify_proof(proof, c_s_post, ctx, 384)


def test_two_proofs_of_one_statement_differ() -> None:
    # Fresh nonces each time (§9.6's purpose: a repeated nonce vector would leak S).
    r_post, s_post, c_s_post, ctx = statement()
    assert posk.prove(r_post, s_post, c_s_post, ctx) != posk.prove(r_post, s_post, c_s_post, ctx)


@pytest.mark.mustfail
@pytest.mark.parametrize("part", ["A", "z_r", "z_0", "z_last"])
def test_tampered_proof_fails(part: str) -> None:
    r_post, s_post, c_s_post, ctx = statement()
    proof = bytearray(posk.prove(r_post, s_post, c_s_post, ctx))
    offset = {"A": 0, "z_r": 32, "z_0": 64, "z_last": 32 + 32 * D}[part]
    proof[offset] ^= 1
    assert not verify_proof(bytes(proof), c_s_post, ctx, D)


@pytest.mark.mustfail
def test_proof_is_bound_to_its_context() -> None:
    # The context binds C_S_pre, C_t, the record, the lsn and the collection: no replay elsewhere.
    r_post, s_post, c_s_post, ctx = statement()
    proof = posk.prove(r_post, s_post, c_s_post, ctx)
    for i in (0, 40, 100, 130, 140):  # a byte inside each of the five context fields
        other = bytearray(ctx)
        other[i] ^= 1
        assert not verify_proof(proof, c_s_post, bytes(other), D)


@pytest.mark.mustfail
def test_wrong_witness_cannot_prove() -> None:
    # Soundness in practice: an operator who does not know the opening of C_S_post fails.
    r_post, s_post, c_s_post, ctx = statement()
    assert not verify_proof(posk.prove(r_post + 1, s_post, c_s_post, ctx), c_s_post, ctx, D)
    s_bad = [s_post[0] + 1, *s_post[1:]]
    assert not verify_proof(posk.prove(r_post, s_bad, c_s_post, ctx), c_s_post, ctx, D)


@pytest.mark.mustfail
def test_non_canonical_scalar_rejected() -> None:
    # §9.9: z values must be < ℓ.
    r_post, s_post, c_s_post, ctx = statement()
    proof = bytearray(posk.prove(r_post, s_post, c_s_post, ctx))
    z_r = int.from_bytes(proof[32:64], "little") + ORDER  # same value mod ℓ, non-canonical
    proof[32:64] = z_r.to_bytes(32, "little")  # fits: z_r + ℓ < 2^253
    assert not verify_proof(bytes(proof), c_s_post, ctx, D)
