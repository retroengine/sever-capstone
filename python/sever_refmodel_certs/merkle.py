"""The transparency log's Merkle tree, from RFC 9162 §2.1 as written (spec §10.1): the recursive
definitions MTH, PATH and PROOF, and the verification algorithms of §2.1.3.2 and §2.1.4.2. Slow
(recomputes subtrees) and obviously correct; the engine keeps every complete subtree instead."""

import hashlib


def leaf_hash(d: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + d).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _k(n: int) -> int:
    """The largest power of two smaller than ``n`` (n > 1)."""
    k = 1
    while 2 * k < n:
        k *= 2
    return k


def mth(d: list[bytes]) -> bytes:
    """RFC 9162 §2.1.1 Merkle Tree Hash."""
    if not d:
        return hashlib.sha256(b"").digest()
    if len(d) == 1:
        return leaf_hash(d[0])
    k = _k(len(d))
    return node_hash(mth(d[:k]), mth(d[k:]))


def path(m: int, d: list[bytes]) -> list[bytes]:
    """RFC 9162 §2.1.3.1 ``PATH(m, D_n)``."""
    if len(d) == 1:
        return []
    k = _k(len(d))
    if m < k:
        return [*path(m, d[:k]), mth(d[k:])]
    return [*path(m - k, d[k:]), mth(d[:k])]


def _subproof(m: int, d: list[bytes], b: bool) -> list[bytes]:
    n = len(d)
    if m == n:
        return [] if b else [mth(d)]
    k = _k(n)
    if m <= k:
        return [*_subproof(m, d[:k], b), mth(d[k:])]
    return [*_subproof(m - k, d[k:], False), mth(d[:k])]


def proof(m: int, d: list[bytes]) -> list[bytes]:
    """RFC 9162 §2.1.4.1 ``PROOF(m, D_n)`` for ``0 < m < n``."""
    if not 0 < m < len(d):
        raise ValueError("PROOF needs 0 < m < n")
    return _subproof(m, d, True)


def verify_inclusion(
    h: bytes, leaf_index: int, tree_size: int, p: list[bytes], root: bytes
) -> bool:
    """RFC 9162 §2.1.3.2, step by step."""
    if leaf_index >= tree_size:  # 1
        return False
    fn, sn = leaf_index, tree_size - 1  # 2
    r = h  # 3
    for x in p:  # 4
        if sn == 0:  # a
            return False
        if fn & 1 or fn == sn:  # b
            r = node_hash(x, r)
            if not fn & 1:
                while not fn & 1 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, x)
        fn >>= 1  # c
        sn >>= 1
    return sn == 0 and r == root  # 5


def verify_consistency(
    first: int, second: int, first_hash: bytes, second_hash: bytes, p: list[bytes]
) -> bool:
    """RFC 9162 §2.1.4.2 for ``0 < first < second``, step by step."""
    if not p:  # 1
        return False
    if first & (first - 1) == 0:  # 2: first is a power of two
        p = [first_hash, *p]
    fn, sn = first - 1, second - 1  # 3
    while fn & 1:  # 4
        fn >>= 1
        sn >>= 1
    fr = sr = p[0]  # 5
    for c in p[1:]:  # 6
        if sn == 0:  # a
            return False
        if fn & 1 or fn == sn:  # b
            fr = node_hash(c, fr)
            sr = node_hash(c, sr)
            if not fn & 1:
                while not fn & 1 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            sr = node_hash(sr, c)
        fn >>= 1  # c
        sn >>= 1
    return fr == first_hash and sr == second_hash and sn == 0  # 7
