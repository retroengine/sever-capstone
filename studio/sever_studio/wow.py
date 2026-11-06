"""The attack lab, as plain functions (the window only draws them).

- ``parse``: a certificate parsed again from the spec (§11.1–11.2), with Studio's own code.
- ``attacks``: forgery attempts on a receipt, each judged by ``sever-verify``.
- ``operator_forgeries``: Part 3's register of forgeries made with the operator's own keys.
"""

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import tools
from .config import Config

# -- §11.1 – 11.2: the certificate, parsed again from the spec ------------------------------------

INSERT_LEAF = (
    209  # §10.2: 0x01 ‖ collection_id 16 ‖ scrambled_id 64 ‖ C_t 32 ‖ user key 32 ‖ signature 64
)
USER_KEY = slice(1 + 16 + 64 + 32, 1 + 16 + 64 + 32 + 32)


class CertificateError(ValueError):
    """Not a certificate as §11.1 defines one."""


@dataclass
class Certificate:
    tags: dict[int, bytes]
    leaf: bytes
    leaf_index: int
    tree_size: int
    root: bytes
    path: list[bytes]
    witnesses: int

    @property
    def user_key(self) -> bytes:
        return self.leaf[USER_KEY]

    @property
    def database_lsn(self) -> int:
        return int.from_bytes(self.tags[10], "big")

    @property
    def from_holding(self) -> bool:
        return self.tags[12] == b"\x01"


def parse(cert: bytes) -> Certificate:
    """Tags 1 … 13 in order, each ``u8 tag ‖ u32be length ‖ value``, then the 0xFF trailer."""
    tags: dict[int, bytes] = {}
    at = 0
    for want in [*range(1, 14), 0xFF]:
        if at + 5 > len(cert):
            raise CertificateError(f"cut off before tag {want}")
        tag, length = cert[at], int.from_bytes(cert[at + 1 : at + 5], "big")
        if tag != want:
            raise CertificateError(f"tag {tag} where {want} belongs")
        tags[tag] = cert[at + 5 : at + 5 + length]
        if len(tags[tag]) != length:
            raise CertificateError(f"tag {tag} is cut off")
        at += 5 + length
    if at != len(cert):
        raise CertificateError("bytes after the trailer")
    inc = tags[6]
    if not inc or inc[0] != 1:
        raise CertificateError("tag 6 is not version 1")
    leaf = inc[1 : 1 + INSERT_LEAF]
    p = 1 + INSERT_LEAF
    leaf_index = int.from_bytes(inc[p : p + 8], "big")
    tree_size = int.from_bytes(inc[p + 8 : p + 16], "big")
    root = inc[p + 16 : p + 48]
    p += 8 + 116  # leaf_index, then the 116-byte log checkpoint
    count = inc[p]
    path = [inc[p + 1 + 32 * i : p + 33 + 32 * i] for i in range(count)]
    if p + 1 + 32 * count != len(inc):
        raise CertificateError("tag 6 has the wrong length")
    return Certificate(tags, leaf, leaf_index, tree_size, root, path, tags[7][0] if tags[7] else 0)


@dataclass
class Attack:
    name: str
    did: str
    expect: str
    verdict: str = ""
    caught: bool = False
    by: str = ""


def _verify(cfg: Config, folder: Path, cert: bytes, anchors: str) -> tuple[int, str, str]:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "certificate.bin").write_bytes(cert)
    (folder / "anchors.json").write_text(anchors, "utf-8")
    t = tools.of(cfg)
    code, out = tools.run(
        [t.verify, "certificate.bin", "--anchors", "anchors.json", "--explain"], folder
    )
    steps, verdict = tools.explain_steps(out)
    del steps
    return code, verdict, out


def judged(code: int, verdict: str) -> tuple[bool, int | None]:
    """sever-verify's answer (§16.3): rejected (exit 1) at a named step of §11.3, and which."""
    m = re.match(r"REJECT \(step (\d+)", verdict)
    if code == 1 and m:
        return True, int(m[1])
    return False, None


def attacks(
    cfg: Config,
    work: Path,
    cert: bytes,
    anchors: str,
    claimant_key: bytes | None,
    other: bytes | None,
) -> list[Attack]:
    """Each attack forges or bends the receipt, or the trust anchors, in one way. ``claimant_key``
    is the public key of the person holding the receipt; ``other`` is someone else's receipt."""
    lab = work / "attack-lab"
    shutil.rmtree(lab, ignore_errors=True)
    a = json.loads(anchors)
    out: list[Attack] = []

    def run(att: Attack, folder: str, c: bytes, anc: str, expected: str) -> None:
        """``expected``: the step that should catch it; any named step that rejects it counts."""
        code, verdict, _ = _verify(cfg, lab / folder, c, anc)
        att.verdict = verdict or f"exit {code}"
        att.caught, step = judged(code, verdict)
        att.by = f"sever-verify, step {step}" if att.caught else "not caught"
        if att.caught and str(step) != expected:
            att.by += f" (expected step {expected})"
        out.append(att)

    flipped = bytearray(cert)
    flipped[len(cert) // 3] ^= 0x01
    run(
        Attack(
            "Change one byte",
            "flipped one bit in the middle of the receipt",
            "rejected: every byte is signed",
        ),
        "flip",
        bytes(flipped),
        anchors,
        "2",
    )
    run(
        Attack("Cut it short", "kept only the first two thirds", "rejected: it does not parse"),
        "cut",
        cert[: len(cert) * 2 // 3],
        anchors,
        "1",
    )
    weak = json.loads(anchors)
    for w in range(2, len(weak["witnesses"])):
        weak["witnesses"][w] = {}
    run(
        Attack(
            "Bribe the witnesses",
            "only 2 witnesses' keys are trusted, as if the others had colluded",
            "rejected: needs 4 of the 5 witnesses (simulated in v1, L-7)",
        ),
        "witnesses",
        cert,
        json.dumps(weak),
        "4",
    )
    fake = json.loads(anchors)
    witness_key = next(iter(a["witnesses"][0].values()))
    fake["operator"] = {e: witness_key for e in fake["operator"]}
    run(
        Attack(
            "Another operator",
            "checked with a different operator's key, as a receipt from another service would be",
            "rejected: not signed by this operator",
        ),
        "operator",
        cert,
        json.dumps(fake),
        "2",
    )
    if other is not None and claimant_key is not None:
        att = Attack(
            "Someone else's receipt",
            "handed over a real receipt that belongs to another account",
            "valid, but the key inside is not yours",
        )
        code, verdict, _ = _verify(cfg, lab / "other", other, anchors)
        theirs = parse(other).user_key
        att.verdict = (
            f"{verdict}; the leaf's key {'is' if theirs == claimant_key else 'is not'} yours"
        )
        att.caught = code == 0 and theirs != claimant_key
        att.by = "your own key check" if att.caught else "not caught"
        out.append(att)
    return out


@dataclass
class Forgery:
    """One attack of Part 3's register (AT-n), made with the operator's own keys."""

    id: str
    text: str
    steps: list[int]
    #: the steps sever-verify rejected it at, over every honest certificate it was made on
    rejected_at: set[int] = field(default_factory=set)
    tries: int = 0
    caught: bool = True

    @property
    def step(self) -> int | None:
        return min(self.rejected_at) if self.rejected_at else None


def register(path: Path) -> dict[str, tuple[str, list[int]]]:
    """Part 3's attack register (copied by setup): each attack's text and the §11.3 steps that may
    reject it."""
    text = path.read_text("utf-8")
    pattern = r'\{id: (AT-\d+), text: "([^"]*)".*?steps: \[([\d, ]+)\]'
    return {m[0]: (m[1], [int(x) for x in m[2].split(",")]) for m in re.findall(pattern, text)}


def operator_forgeries(cfg: Config, work: Path) -> list[Forgery]:
    """Part 3's own attack generator (P3-T2) makes every forgery of its register on five honest
    certificates of the fixture, re-signed with the operator's keys where the register says so;
    ``sever-verify --batch`` judges each. An attack is caught when every one of its forgeries is
    rejected at a step its register row lists. These reach the steps an outsider's edits cannot
    (3, 5, 6): the ones that guard against the operator itself."""
    lab = work / "forgeries"
    shutil.rmtree(lab, ignore_errors=True)
    lab.mkdir(parents=True)
    batch, verdicts = lab / "batch.jsonl", lab / "verdicts.jsonl"
    if not cfg.attacks.exists():
        raise tools.ToolMissingError("Part 3's attack generator is missing: run studio.sh setup")
    gen: list[str | Path] = [cfg.attacks, "attacks", "--root", cfg.data, "--data", "synthetic"]
    gen += ["--seed", "42", "--n", "5"]
    tools.run([*gen, "--out", batch], lab)
    _, out = tools.run([tools.of(cfg).verify, "--batch", batch], lab)
    verdicts.write_text(out, "utf-8")
    reg = register(cfg.register)
    found: dict[str, Forgery] = {}
    for line in out.splitlines():
        if not line.startswith("{"):
            continue
        v = json.loads(line)
        if v.get("kind") not in reg:
            continue
        text, steps = reg[v["kind"]]
        f = found.setdefault(v["kind"], Forgery(v["kind"], text, steps))
        step = v.get("step")
        f.tries += 1
        f.caught = f.caught and not v["accepted"] and step in steps
        if step is not None:
            f.rejected_at.add(int(step))
    return [found[k] for k in sorted(found, key=lambda a: int(a.split("-")[1]))]
