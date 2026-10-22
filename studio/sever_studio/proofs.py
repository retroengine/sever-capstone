"""The engine's own proof programs, run from Studio and read back.

Some claims cannot be seen through the SDK, by design: the database never hands out a group's sum
or blinding total, and a forensic scan needs what only the engine holds. Each part ships a
program that shows its claim from inside (Build §4.9, §5.9; Build 3-4 §1.10, §2.11). Studio runs
them and draws what they report:

- ``idea``: Part 1, ``sever-demo idea``. A cohort is deleted; each touched group's state equals the
  state rebuilt from its survivors alone (§5), and the float and soft-delete baselines do not.
- ``durable``: Part 2, ``sever-demo-p2 durable``. A crash before or after the commit point, then a
  real SIGKILL: every multi-group deletion is all or nothing (§12).
- ``receipt``: Part 3, ``sever_demo_p3.receipt``. The certificate checked offline, a flipped byte,
  what it does not prove, the chained certificates and the audit (§11).
- ``erase``: Part 4, ``scripts/demo-p4.sh``. A scanner holding the whole disk recovers a live
  record but nothing deleted; the build that skips group-key rotation (SB-24) leaks (§13).

A run is live (``synthetic`` takes seconds, ``nq-10k`` minutes) or the recorded nq-10k run
in ``artefacts/demo/`` that the same program wrote.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROOFS = ("idea", "durable", "receipt", "erase")


@dataclass
class Proof:
    name: str
    source: str  # "live synthetic", "live nq-10k" or "recorded nq-10k (<file>)"
    ok: bool
    checks: list[tuple[str, bool]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    text: str = ""


def recorded(root: Path, name: str) -> Path | None:
    p = root / f"artefacts/demo/{name}-nq-10k-seed42.json"
    return p if p.exists() else None


def run(root: Path, name: str, data: str, work: Path) -> Proof:
    """Runs one proof program live and reads its report."""
    work.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONPATH": str(root / "python")}
    out = work / f"{name}-{data}.json"
    cmd: list[str]
    if name == "idea":
        cmd = ["cargo", "run", "-q", "--release", "-p", "sever-p1", "--bin", "sever-demo", "--"]
        cmd += ["idea", "--data", data, "--seed", "42", "--json", str(out)]
    elif name == "durable":
        cmd = ["cargo", "run", "-q", "--release", "-p", "sever-p2", "--features", "demo"]
        cmd += ["--bin", "sever-demo-p2", "--", "durable", "--data", data, "--seed", "42"]
        cmd += ["--work", str(work / f"durable-{data}"), "--out", str(out)]
    elif name == "receipt":
        cmd = [sys.executable, "-m", "sever_demo_p3.receipt", "receipt", "--data", data]
        cmd += ["--work", str(work / f"receipt-{data}")]
        out = work / f"receipt-{data}" / f"receipt-{data}-seed42.json"
    elif name == "erase":
        cmd = ["bash", "scripts/demo-p4.sh"]
    else:
        raise ValueError(name)
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env, check=False)
    text = (p.stdout + p.stderr).strip()
    report: dict[str, Any] = {}
    if name != "erase" and out.exists():
        report = json.loads(out.read_text("utf-8"))
    proof = read(name, report, text, f"live {data}")
    if p.returncode != 0:
        proof.ok = False
        proof.checks.append((f"the program exited {p.returncode}", False))
    return proof


def load_recorded(root: Path, name: str) -> Proof | None:
    path = recorded(root, name)
    if path is None:
        return None
    return read(name, json.loads(path.read_text("utf-8")), "", f"recorded nq-10k ({path.name})")


def read(name: str, report: dict[str, Any], text: str, source: str) -> Proof:
    checks = {"idea": _idea, "durable": _durable, "receipt": _receipt, "erase": _erase}[name](
        report, text
    )
    if name == "erase":
        report = erase_report(text)
    return Proof(name, source, bool(checks) and all(ok for _, ok in checks), checks, report, text)


def _idea(r: dict[str, Any], _: str) -> list[tuple[str, bool]]:
    groups = r.get("groups", [])
    ghost = r.get("ghost", {}).get("per_group", [])
    search = r.get("search", {})
    return [
        (
            f"every touched group equals its survivors-only rebuild ({len(groups)} groups)",
            bool(groups) and all(g["exact"] for g in groups),
        ),
        (
            "no untouched group changed",
            r.get("untouched", {}).get("groups") == r.get("untouched", {}).get("unchanged"),
        ),
        ("deleting again: already absent, nothing changed", all(r["second_delete"].values())),
        (
            "SEVER's sum is bit-identical to the survivors-only sum",
            bool(ghost) and all(g["sever_max_abs_diff"] == 0 for g in ghost),
        ),
        (
            "the float running mean is not (its bits differ)",
            bool(ghost) and all(g["float_mean_max_abs_diff"] > 0 for g in ghost),
        ),
        (
            "soft delete still holds the record (its centroid still carries it)",
            bool(ghost) and all(g["soft_delete_distance"] > 0 for g in ghost),
        ),
        ("no search returns a deleted record", search.get("deleted_returned_after") == 0),
        ("invariants INV-4 … INV-9 hold", r.get("invariants") == "ok"),
    ]


def _durable(r: dict[str, Any], _: str) -> list[tuple[str, bool]]:
    rows = [*r.get("simulated", []), *r.get("sigkill", [])]
    return [
        *(
            (
                f"crash {row.get('crash') or 'SIGKILL at ' + row.get('paused_at', '?')}: "
                f"{row['verdict']}, survivors check passes",
                row["verdict"] in ("none deleted", "all deleted")
                and not row["survivors_check"]["failed"],
            )
            for row in rows
        ),
        ("all or nothing in every case", r.get("all_or_nothing") is True),
        (
            "before the commit point nothing, after it everything",
            r.get("commit_point_respected") is True,
        ),
    ]


def _receipt(r: dict[str, Any], _: str) -> list[tuple[str, bool]]:
    du = r.get("delete_user", {})
    return [
        ("the certificate verifies offline: ACCEPT", r.get("verify", {}).get("accepted") is True),
        (
            "one flipped byte: REJECT",
            str(r.get("flipped", {}).get("verdict", "")).startswith("REJECT"),
        ),
        ("the limits are stated", len(r.get("does_not_prove", [])) >= 2),
        (
            f"delete_user: {du.get('certificates', 0)} certificates, {du.get('chained', 0)} chained"
            " to the one before",
            du.get("certificates", 0) > 0 and du.get("chained", 0) > 0,
        ),
        (
            "sever-audit over the exported log: 0 findings",
            "audit" in du and du["audit"]["findings"] == [],
        ),
    ]


_STEP = re.compile(r"^(\d)\. ", re.M)


def erase_report(text: str) -> dict[str, Any]:
    """Splits ``demo-p4.sh``'s output into the normal build and the SB-24 build, step by step."""
    parts = text.split("SEVER-DB Part 4: the erasure")
    out: dict[str, Any] = {}
    for part in parts[1:]:
        build = "sb24" if part.lstrip().startswith("(SB-24") else "normal"
        steps: dict[str, str] = {}
        for chunk in re.split(r"\n(?=\d\. )", part):
            m = _STEP.match(chunk.strip())
            if m:
                steps[m[1]] = " ".join(chunk.strip()[3:].split())
        out[build] = steps
    return out


def _findings(step: str) -> int:
    m = re.search(r"(\d+) findings", step)
    return int(m[1]) if m else -1


def _erase(_: dict[str, Any], text: str) -> list[tuple[str, bool]]:
    r = erase_report(text)
    n, s = r.get("normal", {}), r.get("sb24", {})
    return [
        ("positive control: the scanner recovers a live record", "RECOVERS" in n.get("1", "")),
        ("every certificate of the deletion verifies", "verify" in n.get("2", "")),
        ("after the deletion: 0 findings", _findings(n.get("3", "")) == 0),
        (
            "crash in phase C: recovery erases the old key, 0 findings",
            _findings(n.get("5", "")) == 0,
        ),
        (
            "SB-24 build (key rotation skipped): the scan finds the deleted data",
            _findings(s.get("3", "")) > 0,
        ),
    ]
