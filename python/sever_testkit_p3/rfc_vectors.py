"""Test vectors taken mechanically from the official RFC texts in ``spec/rfc/`` (oracle B, CLAUDE.md
§6.3): nothing is retyped, so a vector cannot carry a transcription error or this project's reading.

    PYTHONPATH=python uv run python -m sever_testkit_p3.rfc_vectors write    # golden/p3_rfc*.json
    PYTHONPATH=python uv run python -m sever_testkit_p3.rfc_vectors check    # golden == extraction

The RFC files are the rfc-editor.org plain texts, pinned by SHA-256 below (re-download:
``curl -O https://www.rfc-editor.org/rfc/rfc<N>.txt``). Extracted:

- RFC 9380 Appendix K.3, ``expand_message_xmd(SHA-512)``: every ``(msg, len_in_bytes,
  uniform_bytes)``. Each vector's printed ``DST_prime`` and ``msg_prime`` are checked against the
  layout of RFC 9380 §5.3.1 (``Z_pad ‖ msg ‖ I2OSP(len, 2) ‖ I2OSP(0, 1) ‖ DST_prime``), which
  proves the parse without computing a hash.
- RFC 9496 Appendix A.1 (multiples of the generator), A.2 (encodings that MUST be rejected) and A.3
  (``from_uniform_bytes`` inputs and outputs) for ristretto255.
- RFC 8032 §7.1, Ed25519 (secret key, public key, message, signature). The text is paginated: page
  headers, footers and form feeds are dropped, and each message is checked against its printed
  length.

``check`` (Fast tier) re-extracts and compares with the committed golden files.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

RFC_DIR: Final = Path("spec/rfc")
PINNED: Final = {
    "rfc9380.txt": "a2e6ab02b2117d6f52ac293020857752972b2e23ae005c33f612e40436ff4b6d",
    "rfc9496.txt": "d875c6e703827da487eae8f0656fd25e4a278f1dcb0f06041669adad27c03ff3",
    "rfc9162.txt": "a0e432ce7580c99fcc8faf0cf3f6191f9ce6b4864f949158e020d4ecb295081f",
    "rfc8032.txt": "ed63657ff389301282b169b0abde9b5dd2c7e4d524fdfa5da6ff3094fc93c4c3",
}
OUT_9380: Final = Path("golden/p3_rfc9380_k3_expand_xmd_sha512.json")
OUT_9496: Final = Path("golden/p3_rfc9496_ristretto255.json")
OUT_8032: Final = Path("golden/p3_rfc8032_ed25519.json")
HEX: Final = re.compile(r"^[0-9a-f]+$")


def _text(root: Path, name: str) -> list[str]:
    raw = (root / RFC_DIR / name).read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != PINNED[name]:
        raise ValueError(f"{name}: SHA-256 {got} is not the pinned {PINNED[name]}")
    return raw.decode("utf-8").splitlines()


def _section(lines: list[str], start: str, end: str) -> list[str]:
    """Lines strictly between the heading that starts with ``start`` and the one with ``end``
    (headings start at column 0; the table of contents is indented and skipped)."""
    i = next(n for n, ln in enumerate(lines) if ln.startswith(start))
    j = next(n for n, ln in enumerate(lines) if n > i and ln.startswith(end))
    return lines[i + 1 : j]


def _fields(block: list[str]) -> dict[str, str]:
    """``name = value`` with continuation lines (deeper indent, no ``=``) appended to the value."""
    out: dict[str, str] = {}
    key = ""
    for ln in block:
        m = re.match(r"^   (\w+)\s*=\s?(.*)$", ln)
        if m:
            key = m.group(1)
            out[key] = m.group(2).strip()
        elif key and ln.strip():
            out[key] += ln.strip()
    return out


def rfc9380_k3(root: Path) -> dict[str, Any]:
    sec = _section(_text(root, "rfc9380.txt"), "K.3.  ", "K.4.  ")
    head = _fields(sec[: next(n for n, ln in enumerate(sec) if ln.startswith("   msg"))])
    dst = head["DST"].encode("ascii")
    starts = [n for n, ln in enumerate(sec) if ln.startswith("   msg     =")]
    vectors = []
    for a, b in zip(starts, [*starts[1:], len(sec)], strict=True):
        f = _fields(sec[a:b])
        msg = f["msg"].encode("ascii")
        n = int(f["len_in_bytes"], 16)
        out = bytes.fromhex(f["uniform_bytes"])
        # RFC 9380 §5.3.1, layout only: DST_prime = DST ‖ I2OSP(len(DST), 1); msg_prime =
        # Z_pad (128 zero bytes for SHA-512) ‖ msg ‖ I2OSP(n, 2) ‖ I2OSP(0, 1) ‖ DST_prime.
        dst_prime = dst + bytes([len(dst)])
        msg_prime = bytes(128) + msg + n.to_bytes(2, "big") + b"\x00" + dst_prime
        if bytes.fromhex(f["DST_prime"]) != dst_prime or bytes.fromhex(f["msg_prime"]) != msg_prime:
            raise ValueError(f"K.3 vector msg={f['msg'][:12]!r}: parse disagrees with §5.3.1")
        if len(out) != n:
            raise ValueError(f"K.3 vector msg={f['msg'][:12]!r}: {len(out)} bytes, not {n}")
        vectors.append({"msg": f["msg"], "len_in_bytes": n, "uniform_bytes": out.hex()})
    return {
        "source": "RFC 9380 Appendix K.3, expand_message_xmd(SHA-512)",
        "source_file": "spec/rfc/rfc9380.txt",
        "source_sha256": PINNED["rfc9380.txt"],
        "dst": head["DST"],
        "vectors": vectors,
    }


def _hex32_blocks(sec: list[str]) -> list[str]:
    """Blank-line-separated blocks of hex groups (``#`` comment lines skipped), 32 bytes each."""
    out: list[str] = []
    cur = ""
    for ln in [*sec, ""]:
        s = ln.strip()
        if s.startswith("#"):
            continue
        if not s:
            if cur:
                out.append(cur)
                cur = ""
            continue
        if HEX.match(s.replace(" ", "")):
            cur += s.replace(" ", "")
    for h in out:
        if len(h) != 64:
            raise ValueError(f"RFC 9496 A.2: block {h[:16]}… is {len(h) // 2} bytes, not 32")
    return out


def rfc9496(root: Path) -> dict[str, Any]:
    lines = _text(root, "rfc9496.txt")
    a1 = _section(lines, "A.1.  ", "A.2.  ")
    multiples: list[str] = []
    for ln in a1:
        m = re.match(r"^   B\[\s*(\d+)\]:\s*(.*)$", ln)
        if m:
            if int(m.group(1)) != len(multiples):
                raise ValueError(f"RFC 9496 A.1: B[{m.group(1)}] out of order")
            multiples.append(m.group(2).replace(" ", ""))
        elif multiples and ln.strip() and HEX.match(ln.strip().replace(" ", "")):
            multiples[-1] += ln.strip().replace(" ", "")
    a2 = _section(lines, "A.2.  ", "A.3.  ")
    invalid = _hex32_blocks(a2[next(n for n, ln in enumerate(a2) if ln.strip().startswith("#")) :])
    # A.3 lists "I:" inputs, each followed by its "O:" output, except a final group of several
    # inputs that all produce the one "O:" after them: an output belongs to every input before it.
    a3 = _section(lines, "A.3.  ", "A.4.  ")
    pairs: list[dict[str, str]] = []
    pending: list[str] = []
    out = ""
    key = ""
    for ln in [*a3, ""]:
        m = re.match(r"^   ([IO]):\s*(.*)$", ln)
        h = ln.strip().replace(" ", "")
        if m:
            if out:  # the previous output is complete
                pairs += [{"input": i, "output": out} for i in pending]
                pending, out = [], ""
            key = m.group(1)
            if key == "I":
                pending.append(m.group(2).replace(" ", ""))
            else:
                out = m.group(2).replace(" ", "")
        elif key and h and HEX.match(h):
            if key == "I":
                pending[-1] += h
            else:
                out += h
        else:
            key = ""
    pairs += [{"input": i, "output": out} for i in pending] if out else []
    if pending and not out:
        raise ValueError("RFC 9496 A.3: inputs without an output")
    for p in pairs:
        if len(p["input"]) != 128 or len(p["output"]) != 64:
            raise ValueError(f"RFC 9496 A.3: pair {p['input'][:16]}… has the wrong sizes")
    if any(len(h) != 64 for h in multiples):
        raise ValueError("RFC 9496 A.1: a multiple is not 32 bytes")
    return {
        "source": "RFC 9496 Appendix A.1-A.3, ristretto255",
        "source_file": "spec/rfc/rfc9496.txt",
        "source_sha256": PINNED["rfc9496.txt"],
        "generator_multiples": multiples,
        "invalid_encodings": invalid,
        "from_uniform_bytes": pairs,
    }


PAGE_LINE: Final = re.compile(r"^RFC 8032 |\[Page \d+\]$")


def rfc8032_ed25519(root: Path) -> dict[str, Any]:
    lines = [
        ln
        for ln in _text(root, "rfc8032.txt")
        if "\f" not in ln and not PAGE_LINE.search(ln.strip())
    ]
    sec = _section(lines, "7.1.  ", "7.2.  ")
    starts = [n for n, ln in enumerate(sec) if ln.strip().startswith("-----TEST")]
    vectors = []
    for a, b in zip(starts, [*starts[1:], len(sec)], strict=True):
        block = sec[a:b]
        name = block[0].strip().removeprefix("-----TEST ").strip()
        fields: dict[str, str] = {}
        length = -1
        key = ""
        for ln in block[1:]:
            s = ln.strip()
            m = re.match(r"^MESSAGE \(length (\d+) bytes?\):$", s)
            if m:
                key, length = "message", int(m.group(1))
                fields[key] = ""
            elif s.endswith(":") and s[:-1] in (
                "ALGORITHM",
                "SECRET KEY",
                "PUBLIC KEY",
                "SIGNATURE",
            ):
                key = s[:-1].lower().replace(" ", "_")
                fields[key] = ""
            elif s and key == "algorithm":
                fields[key] += s
            elif s and key and HEX.match(s.replace(" ", "")):
                fields[key] += s.replace(" ", "")
            elif s:  # anything else (the closing "-----") ends the current field
                key = ""
        msg = fields["message"]
        if fields["algorithm"] != "Ed25519" or len(msg) != 2 * length or not HEX.match(msg or "0"):
            raise ValueError(f"RFC 8032 TEST {name}: message is not {length} bytes of hex")
        sizes = (len(fields["secret_key"]), len(fields["public_key"]), len(fields["signature"]))
        if sizes != (64, 64, 128):
            raise ValueError(f"RFC 8032 TEST {name}: wrong key or signature size")
        vectors.append({"name": name, "secret_key": fields["secret_key"],
                        "public_key": fields["public_key"], "message": msg,
                        "signature": fields["signature"]})  # fmt: skip
    return {
        "source": "RFC 8032 §7.1, Ed25519",
        "source_file": "spec/rfc/rfc8032.txt",
        "source_sha256": PINNED["rfc8032.txt"],
        "vectors": vectors,
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rfc-vectors", description=__doc__)
    ap.add_argument("command", choices=["write", "check"])
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    root: Path = args.root
    want = {
        OUT_9380: _dump(rfc9380_k3(root)),
        OUT_9496: _dump(rfc9496(root)),
        OUT_8032: _dump(rfc8032_ed25519(root)),
    }
    bad = 0
    for path, text in want.items():
        if args.command == "write":
            (root / path).write_text(text, encoding="utf-8")
            print(path)
        elif not (root / path).is_file() or (root / path).read_text(encoding="utf-8") != text:
            print(f"{path}: differs from the extraction of the pinned RFC text", file=sys.stderr)
            bad += 1
    if args.command == "check":
        print(f"RFC vectors: {len(want) - bad}/{len(want)} golden files match the RFC texts")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
