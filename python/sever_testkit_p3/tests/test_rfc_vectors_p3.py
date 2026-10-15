"""``rfc_vectors``: the committed golden files are exactly what the pinned RFC texts contain."""

import hashlib
import shutil
from pathlib import Path

import pytest

from sever_testkit_p3 import rfc_vectors

ROOT = Path(__file__).resolve().parents[3]


def test_p3_rfc_vectors_golden_files_match_the_rfc_texts() -> None:
    assert rfc_vectors.main(["check", "--root", str(ROOT)]) == 0


def test_p3_rfc_vectors_counts_match_the_appendices() -> None:
    # Counted by hand in the RFC texts: K.3 has five messages at two output lengths; RFC 9496 A.1
    # lists B[0]…B[15], A.2 has 29 rejected encodings, A.3 has 7 pairs and 4 inputs sharing an
    # output.
    k3 = rfc_vectors.rfc9380_k3(ROOT)
    assert k3["dst"] == "QUUX-V01-CS02-with-expander-SHA512-256"
    assert [(len(v["msg"]), v["len_in_bytes"]) for v in k3["vectors"]] == [
        (m, n) for n in (32, 128) for m in (0, 3, 16, 133, 517)
    ]
    r = rfc_vectors.rfc9496(ROOT)
    assert len(r["generator_multiples"]) == 16
    assert r["generator_multiples"][0] == "00" * 32  # the identity
    assert len(r["invalid_encodings"]) == 29
    assert len(r["from_uniform_bytes"]) == 11
    assert len({p["output"] for p in r["from_uniform_bytes"]}) == 8
    # RFC 8032 §7.1: TESTs 1, 2, 3, 1024 (a 1023-byte message across page breaks) and SHA(abc).
    e = rfc_vectors.rfc8032_ed25519(ROOT)
    assert [(v["name"], len(v["message"]) // 2) for v in e["vectors"]] == [
        ("1", 0),
        ("2", 1),
        ("3", 2),
        ("1024", 1023),
        ("SHA(abc)", 64),
    ]


def _copy(tmp_path: Path) -> Path:
    (tmp_path / "spec").mkdir()
    shutil.copytree(ROOT / rfc_vectors.RFC_DIR, tmp_path / rfc_vectors.RFC_DIR)
    return tmp_path


def test_p3_rfc_vectors_an_altered_rfc_text_is_refused(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    f = root / rfc_vectors.RFC_DIR / "rfc9380.txt"
    f.write_bytes(f.read_bytes().replace(b"6b9a7312411d92f9", b"6b9a7312411d92f8"))
    with pytest.raises(ValueError, match="is not the pinned"):
        rfc_vectors.rfc9380_k3(root)


def test_p3_rfc_vectors_a_wrong_parse_is_caught_by_the_msg_prime_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A message read one character short no longer matches the RFC's printed msg_prime.
    root = _copy(tmp_path)
    f = root / rfc_vectors.RFC_DIR / "rfc9380.txt"
    raw = f.read_bytes()
    k3 = raw.index(b"\nK.3.  expand_message_xmd(SHA-512)")  # the heading, not the contents line
    f.write_bytes(raw[:k3] + raw[k3:].replace(b"   msg     = abc\n", b"   msg     = ab\n", 1))
    digest = hashlib.sha256(f.read_bytes()).hexdigest()
    monkeypatch.setitem(rfc_vectors.PINNED, "rfc9380.txt", digest)
    with pytest.raises(ValueError, match="parse disagrees"):
        rfc_vectors.rfc9380_k3(root)
