"""The model auditor (§11.3 "what it does not prove", DB-86) on its own scripted log: nothing to
report on the honest export, and every fault of the register (AF-1 … AF-5) reported under its own
kind."""

import re
from pathlib import Path

from sever_refmodel_certs import audit

ROOT = Path(__file__).resolve().parents[3]


def test_p3_model_audit_honest_log_has_no_findings() -> None:
    log = audit.honest()
    assert audit.audit(log.export(), log.anchors(), log.certs) == []
    kinds = [p["group"] for p in log.placements]
    assert "spawn-00000000000000aa" in kinds
    assert "holding" in kinds


def test_p3_model_audit_reports_every_registered_fault() -> None:
    text = (ROOT / "spec/registers_p3.yaml").read_text(encoding="utf-8")
    register = set(re.findall(r"\{id: (AF-\d+),", text))
    found = audit.faults()
    assert set(found) == register
    anchors = audit.honest().anchors()
    for fid, (export, held) in found.items():
        kinds = {f.kind for f in audit.audit(export, anchors, held)}
        assert fid in kinds, (fid, kinds)
