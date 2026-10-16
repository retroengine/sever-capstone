"""The Part 3 demo (Build 3-4 §1.10), offline on the synthetic fixture."""

import json
from pathlib import Path

import pytest

from sever_demo_p3 import receipt

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.spec("SR-3.3-1")
@pytest.mark.oracle(
    "A",
    "§3.3 'The application backend MUST embed text with the encoder named in the partition "
    "artefact's encoder field'",
)
def test_p3_demo_backend_uses_the_artefacts_encoder(tmp_path: Path) -> None:
    art = tmp_path / "artefact.json"
    art.write_text(json.dumps({"encoder": "model-a@1"}), encoding="utf-8")
    assert receipt.check_encoder(art, "model-a@1") == "model-a@1"
    with pytest.raises(receipt.DemoError):
        receipt.check_encoder(art, "model-b@1")
    with pytest.raises(receipt.DemoError):
        receipt.check_encoder(art, "model-a@2")  # another revision of the same model


def test_p3_demo_receipt_runs_end_to_end_on_the_fixture() -> None:
    r = receipt.demo(ROOT, "synthetic", 42, ROOT / "target/demo-p3-test")
    assert r["verify"] == {"accepted": True, "files": ["anchors.json", "certificate.bin"]}
    assert r["flipped"]["verdict"].startswith("REJECT (step 2")
    assert r["delete_user"]["audit"]["findings"] == []
    assert r["delete_user"]["chained"] >= 1
    assert r["insert_leaf"]["type"] == 1
