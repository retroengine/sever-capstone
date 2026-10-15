"""The model's Merkle tree against the worked example of RFC 9162 §2.1.5 (node names by hand) and
its own verification algorithms."""

import hashlib

from sever_refmodel_certs import merkle as m

D = [f"d{i}".encode() for i in range(7)]
a, b, c, d, e, f, d6 = (m.leaf_hash(x) for x in D)
g, h, i, j = m.node_hash(a, b), m.node_hash(c, d), m.node_hash(e, f), d6
k, l = m.node_hash(g, h), m.node_hash(i, j)  # noqa: E741 (the RFC's node name)
ROOT = m.node_hash(k, l)


def test_p3_model_merkle_follows_the_rfc9162_example() -> None:
    # RFC 9162 §2.1.5: the tree, four inclusion proofs and PROOF(3, D[7]) = [c, d, g, l].
    assert m.mth(D) == ROOT
    assert m.mth([]) == hashlib.sha256(b"").digest()
    assert m.path(0, D) == [b, h, l]
    assert m.path(3, D) == [c, g, l]
    assert m.path(4, D) == [f, j, k]
    assert m.path(6, D) == [i, k]
    assert m.proof(3, D) == [c, d, g, l]
    hash0 = m.node_hash(g, c)
    assert m.mth(D[:3]) == hash0


def test_p3_model_every_proof_of_a_7_leaf_tree_verifies_and_tampering_fails() -> None:
    for n in range(1, 8):
        root = m.mth(D[:n])
        for idx in range(n):
            p = m.path(idx, D[:n])
            assert m.verify_inclusion(m.leaf_hash(D[idx]), idx, n, p, root)
            assert not m.verify_inclusion(m.leaf_hash(b"x"), idx, n, p, root)
            if n < 7:  # the root of a longer tree does not verify the shorter tree's proof
                longer = m.mth(D[: n + 1])
                assert not m.verify_inclusion(m.leaf_hash(D[idx]), idx, n + 1, p, longer)
        for first in range(1, n):
            p = m.proof(first, D[:n])
            assert m.verify_consistency(first, n, m.mth(D[:first]), root, p)
            assert not m.verify_consistency(first, n, m.mth(D[:first]), m.leaf_hash(b"x"), p)
            assert not m.verify_consistency(first, n, m.leaf_hash(b"y"), root, p)
