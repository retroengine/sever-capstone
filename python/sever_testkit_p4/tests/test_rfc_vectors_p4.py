"""``rfc_vectors`` (Part 4): the committed golden file is exactly what the pinned RFC 8452 text
contains."""

import hashlib
import shutil
from pathlib import Path

import pytest

from sever_testkit_p4 import rfc_vectors

ROOT = Path(__file__).resolve().parents[3]

# (plaintext bytes, AAD bytes) of every vector, read off the RFC 8452 text: Appendix C.2 lists 24,
# C.3 (counter wrap, AES-256-GCM-SIV) two more.
C2_SIZES = [(p, 0) for p in (0, 8, 12, 16, 32, 48, 64)]
C2_SIZES += [(p, 1) for p in (8, 12, 16, 32, 48, 64)]
C2_SIZES += [(4, 12), (20, 18), (18, 20)]
C2_SIZES += [(3 * i, 5 * i) for i in range(8)]
C3_SIZES = [(32, 0), (24, 0)]


def test_p4_rfc_vectors_golden_file_matches_the_rfc_text() -> None:
    assert rfc_vectors.main(["check", "--root", str(ROOT)]) == 0


def test_p4_rfc_vectors_sizes_match_the_appendix() -> None:
    v = rfc_vectors.extract(ROOT)["vectors"]
    assert isinstance(v, list)
    assert [(len(x["plaintext"]) // 2, len(x["aad"]) // 2) for x in v] == C2_SIZES + C3_SIZES
    assert [x["source"] for x in v][23:25] == ["C.2 #23", "C.3 #0"]
    # The first C.2 vector, read off the RFC by hand: key 01 00…, nonce 03 00…, empty input.
    assert v[0]["key"] == "01" + "00" * 31
    assert v[0]["nonce"] == "03" + "00" * 11
    assert v[0]["result"] == "07f5f4169bbf55a8400cd47ea6fd400f"


def _copy(tmp_path: Path) -> Path:
    (tmp_path / "spec/rfc").mkdir(parents=True)
    shutil.copy(ROOT / rfc_vectors.RFC, tmp_path / rfc_vectors.RFC)
    return tmp_path


def test_p4_rfc_vectors_an_altered_rfc_text_is_refused(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    f = root / rfc_vectors.RFC
    f.write_bytes(f.read_bytes().replace(b"07f5f4169bbf55a8", b"07f5f4169bbf55a9"))
    with pytest.raises(ValueError, match="is not the pinned"):
        rfc_vectors.extract(root)


def test_p4_rfc_vectors_a_wrong_parse_is_caught_by_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A result whose last line is lost no longer ends with the printed tag.
    root = _copy(tmp_path)
    f = root / rfc_vectors.RFC
    raw = f.read_bytes()
    c3 = raw.index(b"\nC.3.  Counter Wrap Tests")  # the heading, not the contents line
    last = b"\n" + b" " * 31 + b"ffffffff000000000000000000000000\n"
    tail = raw[c3:].replace(last, b"\n", 1)
    f.write_bytes(raw[:c3] + tail)
    monkeypatch.setattr(rfc_vectors, "PINNED", hashlib.sha256(f.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match=r"C\.3 vector 0"):
        rfc_vectors.extract(root)
