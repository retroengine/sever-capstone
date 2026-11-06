"""The four live demonstrations (``wow.py``), offline on the fixture.

Expected values come from the definitions, not from the code under test: RFC 9162 §2.1.1 (the tree
hash) and §2.1.3.1 (the audit path) are written out again here, in their recursive form, to build
trees and paths the climb must accept; §11.1's must-reject rules give the parser's cases; §4.2's
ties-to-even gives the quantiser's.
"""

import hashlib
import shutil
from collections.abc import Iterator

import pytest
from conftest import CFG, WORK

from sever_studio import wow
from sever_studio.actions import Studio

# -- RFC 9162, written out again ---------------------------------------------------------------


def mth(leaves: list[bytes]) -> bytes:
    """§2.1.1: MTH({}) = SHA-256(); MTH({d0}) = SHA-256(0x00 ‖ d0); else split at the largest
    power of two below n."""
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return hashlib.sha256(b"\x00" + leaves[0]).digest()
    k = 1
    while k * 2 < n:
        k *= 2
    return hashlib.sha256(b"\x01" + mth(leaves[:k]) + mth(leaves[k:])).digest()


def path(m: int, leaves: list[bytes]) -> list[bytes]:
    """§2.1.3.1: PATH(m, D[n])."""
    n = len(leaves)
    if n <= 1:
        return []
    k = 1
    while k * 2 < n:
        k *= 2
    if m < k:
        return [*path(m, leaves[:k]), mth(leaves[k:])]
    return [*path(m - k, leaves[k:]), mth(leaves[:k])]


# -- on a real (fixture) database --------------------------------------------------------------


@pytest.fixture(scope="module")
def studio() -> Iterator[Studio]:
    work = WORK / "test-live"
    shutil.rmtree(work, ignore_errors=True)
    s = Studio(CFG, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    s.forget("account-2")
    s.forget("account-4")
    yield s
    s.backend.close()
    shutil.rmtree(work, ignore_errors=True)


def test_live_parser_reads_a_real_receipt_and_rejects_broken_ones(studio: Studio) -> None:
    lsn = studio.backend.index.receipts[-1]
    raw = (studio.backend.receipts / f"{lsn}.cert").read_bytes()
    cert = wow.parse(raw)
    assert cert.database_lsn == lsn  # tag 10 is this deletion's own leaf index (§11.1)
    assert cert.leaf[0] == 1  # an insert leaf (§10.2)
    assert cert.leaf_index < cert.tree_size
    assert len(cert.user_key) == 32
    # §11.1: a parser MUST reject missing or out-of-order tags, wrong lengths, trailing bytes
    with pytest.raises(wow.CertificateError):
        wow.parse(raw[: len(raw) // 2])
    with pytest.raises(wow.CertificateError):
        wow.parse(raw + b"\x00")
    swapped = bytearray(raw)
    swapped[0] = 2
    with pytest.raises(wow.CertificateError):
        wow.parse(bytes(swapped))


def test_live_every_attack_is_caught_where_expected(studio: Studio) -> None:
    out = studio.attack_lab(studio.backend.index.receipts[-1])
    by_name = {a.name: a for a in out}
    assert by_name["Change one byte"].verdict.startswith("REJECT (step 2")
    assert by_name["Cut it short"].verdict.startswith("REJECT (step 1")
    assert by_name["Bribe the witnesses"].verdict.startswith("REJECT (step 4")
    assert by_name["Another operator"].verdict.startswith("REJECT (step 2")
    other = by_name["Someone else's receipt"]
    assert other.verdict.startswith("ACCEPT")  # a valid receipt; the key inside is the catch
    assert other.caught
    assert all(a.caught for a in out)
    assert studio.checklist.verdicts["attacks"].ok


def test_live_operator_forgeries_are_each_rejected_at_their_register_step(studio: Studio) -> None:
    # oracle: A Part 3's attack register (spec/registers_p3.yaml, Build 3-4 §1.8) lists, for each
    # forgery made with the operator's own keys, the §11.3 step that must reject it; P Part 3's own
    # attack generator (P3-T2) and sever-verify
    out = studio.operator_forgeries()
    assert len(out) == 20
    assert all(f.caught for f in out), [f for f in out if not f.caught]
    reached = set().union(*(f.rejected_at for f in out))
    assert {3, 5, 6} <= reached
