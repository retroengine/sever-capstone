"""The spec layer of the model: ``scalar(v)`` (§4.5), the generators (§9.2), the digest (§9.6), and
the model's independence (Build 3-4 §1.6: written from the spec, standard library only)."""

import ast
import sys
from pathlib import Path

from sever_refmodel_certs import ristretto as r
from sever_refmodel_certs import spec

PKG = Path(spec.__file__).parent


def test_p3_model_scalar_follows_section_4_5() -> None:
    l = r.L  # noqa: E741 (the spec's symbol)
    assert [spec.scalar(v) for v in (0, 1, -1, 2**44, -(2**44))] == [0, 1, l - 1, 2**44, l - 2**44]
    assert spec.scalar(-(2**63)) == l - 2**63


def test_p3_model_generators_are_distinct_valid_points() -> None:
    h, gs = spec.generators(8)
    encs = [r.encode(p) for p in (h, *gs)]
    assert len(set(encs)) == 9
    assert all(e != bytes(32) for e in encs)
    assert all(r.encode(r.decode(e)) == e for e in encs)


def test_p3_model_generator_inputs_follow_section_9_2() -> None:
    # One expand_message call per generator: msg b"H", and b"G" ‖ u32be(i), with DST_GEN.
    assert spec.generator_h().equals(spec.hash_to_group(b"H"))
    assert spec.generator_g(383).equals(spec.hash_to_group(b"G\x00\x00\x01\x7f"))
    assert not spec.generator_g(1).equals(spec.hash_to_group(b"G\x01\x00\x00\x00"))  # not LE


def test_p3_model_uses_only_the_standard_library() -> None:
    # Build 3-4 §1.6: the model shares nothing with the engine; it may import only the standard
    # library, itself, and pytest in its tests.
    allowed = set(sys.stdlib_module_names) | {"sever_refmodel_certs", "pytest"}
    for f in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for n in names:
                assert n.split(".")[0] in allowed, (f.name, n)


def test_p3_model_commitments_are_additive_and_empty_is_identity() -> None:
    # §9.3 and §5.3: C(S + x̃, r_agg + r_t) = C(S, r_agg) + C(x̃, r_t).
    # §5.4: S = 0 and r_agg = 0 give the identity.
    s, x = [5, -7, 2**40, -(2**40), 0, 1, -1, 3], [-(2**24), 2**24 + 16, 9, -9, 0, 0, 4, -4]
    pre = spec.commit([a + b for a, b in zip(s, x, strict=True)], (11 + 22) % r.L)
    assert pre.equals(spec.commit(s, 11) + spec.commit(x, 22))
    assert (pre - spec.commit(x, 22)).equals(spec.commit(s, 11))  # C_S_post + C_t = C_S_pre
    assert r.encode(spec.commit([0] * 8, 0)) == bytes(32)


def test_p3_model_proof_verifies_and_rejects_changes() -> None:
    # §9.5: an honest proof verifies; another context, statement or response does not.
    from sever_refmodel_certs import posk

    s, rr = [3, -1, 2**30, 0, -(2**24), 7, 8, -9], 12345
    ctx = posk.ctx_bytes(bytes(32), bytes(32), bytes(64), 9, bytes(16))
    proof = posk.prove(s, rr, ctx, 77, [i + 1 for i in range(8)])
    c_s_post = r.encode(spec.commit(s, rr))
    assert len(proof) == 32 + 32 + 32 * 8
    assert posk.verify(c_s_post, ctx, proof, 8)
    assert not posk.verify(c_s_post, ctx[:-1] + b"\x01", proof, 8)
    assert not posk.verify(r.encode(spec.commit(s, rr + 1)), ctx, proof, 8)
    z_r = (int.from_bytes(proof[32:64], "little") + 1) % r.L
    assert not posk.verify(c_s_post, ctx, proof[:32] + r.encode_scalar(z_r) + proof[64:], 8)
