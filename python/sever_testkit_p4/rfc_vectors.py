"""RFC 8452 AES-256-GCM-SIV test vectors taken mechanically from the official text in ``spec/rfc/``
(oracle B, CLAUDE.md §6.3; spec §20.3 check 3): nothing is retyped, so a vector cannot carry a
transcription error or this project's reading.

    PYTHONPATH=python uv run python -m sever_testkit_p4.rfc_vectors write  # golden/p4_rfc8452_*
    PYTHONPATH=python uv run python -m sever_testkit_p4.rfc_vectors check  # golden == extraction

The RFC file is the rfc-editor.org plain text, pinned by SHA-256 below (re-download:
``curl -O https://www.rfc-editor.org/rfc/rfc8452.txt``). Extracted: every vector of Appendix C.2
(``AEAD_AES_256_GCM_SIV``) and C.3 (counter-wrap tests, also AES-256-GCM-SIV): plaintext, AAD, key,
nonce, tag and result. The text is paginated: page headers and footers are dropped. Each value is
checked against its printed byte count, the key is 32 bytes and the nonce 12, and the result is the
ciphertext followed by the printed tag (``len(result) = len(plaintext) + 16``, its last 16 bytes
equal ``Tag``), which proves the parse without computing AES. C.1 (AES-128) is not used (§13.2).

``check`` (Fast tier) re-extracts and compares with the committed golden file.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Final

RFC: Final = Path("spec/rfc/rfc8452.txt")
PINNED: Final = "ca48ec466b401ce5d68d6d1628127a1800adcc16f2573646aaa3d7df284d3c17"
OUT: Final = Path("golden/p4_rfc8452_aes256gcmsiv.json")
FIELD: Final = re.compile(r"^   (\S.*?)(?: \((\d+) bytes\))? =(?:\s+([0-9a-f]+))?$")
MORE: Final = re.compile(r"^ {20,}([0-9a-f]+)$")
PAGE: Final = re.compile(r"^(Gueron, et al\. .*\[Page \d+\]|RFC 8452 .*April 2019)$")
KEEP: Final = {"Plaintext", "AAD", "Key", "Nonce", "Tag", "Result"}


def _lines(root: Path) -> list[str]:
    raw = (root / RFC).read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != PINNED:
        raise ValueError(f"{RFC}: SHA-256 {got} is not the pinned {PINNED}")
    return [ln for ln in raw.decode("utf-8").splitlines() if not PAGE.match(ln.strip("\f"))]


def _section(lines: list[str], start: str, end: str) -> list[str]:
    """Lines strictly between the column-0 headings ``start`` and ``end`` (the table of contents
    is indented and skipped)."""
    i = next(n for n, ln in enumerate(lines) if ln.startswith(start))
    j = next(n for n, ln in enumerate(lines) if n > i and ln.startswith(end))
    return lines[i + 1 : j]


def _vectors(body: list[str], section: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    sizes: dict[str, int] = {}
    last = ""
    for ln in body:
        if m := FIELD.match(ln):
            name, size, hexpart = m.group(1), m.group(2), m.group(3) or ""
            if name == "Plaintext":
                if cur:
                    out.append(_finish(cur, sizes, section, len(out)))
                cur, sizes = {}, {}
            last = name
            if name in KEEP:
                cur[name] = hexpart
                if size is not None:
                    sizes[name] = int(size)
        elif (m := MORE.match(ln)) and last in KEEP:
            cur[last] += m.group(1)
        elif ln.strip():
            last = ""
    if cur:
        out.append(_finish(cur, sizes, section, len(out)))
    return out


def _finish(v: dict[str, str], sizes: dict[str, int], section: str, i: int) -> dict[str, str]:
    where = f"RFC 8452 {section} vector {i}"
    missing = KEEP - v.keys()
    if missing:
        raise ValueError(f"{where}: missing {sorted(missing)}")
    for name, n in sizes.items():
        if len(v[name]) != 2 * n:
            raise ValueError(f"{where}: {name} is {len(v[name]) // 2} bytes, printed {n}")
    if len(v["Key"]) != 64 or len(v["Nonce"]) != 24 or len(v["Tag"]) != 32:
        raise ValueError(f"{where}: key, nonce or tag has the wrong length")
    if len(v["Result"]) != len(v["Plaintext"]) + 32 or not v["Result"].endswith(v["Tag"]):
        raise ValueError(f"{where}: the result is not the ciphertext followed by the tag")
    return {
        "source": f"{section} #{i}",
        "key": v["Key"],
        "nonce": v["Nonce"],
        "aad": v["AAD"],
        "plaintext": v["Plaintext"],
        "result": v["Result"],
    }


def extract(root: Path) -> dict[str, object]:
    lines = _lines(root)
    vectors = _vectors(_section(lines, "C.2.", "C.3."), "C.2")
    vectors += _vectors(_section(lines, "C.3.", "Acknowledgements"), "C.3")
    return {
        "source_file": str(RFC),
        "source_sha256": PINNED,
        "algorithm": "AEAD_AES_256_GCM_SIV",
        "note": "result = ciphertext ‖ tag (16 bytes), in hex; extracted by sever_testkit_p4",
        "vectors": vectors,
    }


def _dump(obj: object) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rfc-vectors-p4", description=__doc__)
    ap.add_argument("command", choices=["write", "check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    root: Path = args.root
    want = _dump(extract(root))
    path = root / OUT
    if args.command == "write":
        path.write_text(want, encoding="utf-8")
        print(path)
        return 0
    if not path.is_file() or path.read_text(encoding="utf-8") != want:
        print(f"{OUT} differs from the extraction of {RFC}", file=sys.stderr)
        return 1
    n = len(json.loads(want)["vectors"])
    print(f"RFC 8452: {n} AES-256-GCM-SIV vectors match {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
