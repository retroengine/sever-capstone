"""The id/cohort export for the Rust demo (sever_testkit.slices)."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from sever_testkit import slices


def test_p1_slices_export_keeps_order_and_never_the_text(tmp_path: Path) -> None:
    src = tmp_path / "passages.parquet"
    pq.write_table(
        pa.table(
            {
                "id": ["doc0", "doc1", "doc6"],
                "cohort": ["Minority interest", "Minority interest", "Chicago Fire (season 4)"],
                "text": ["secret passage one", "secret passage two", "secret passage three"],
            }
        ),
        src,
    )
    out = tmp_path / "out" / "ids.jsonl"
    assert slices.export(tmp_path, src, out, "ab" * 32) == 3
    lines = out.read_text(encoding="utf-8").splitlines()
    header = {"format": "sever-ids-1", "passages_sha256": "ab" * 32, "rows": 3}
    assert json.loads(lines[0]) == header
    assert [json.loads(x) for x in lines[1:]] == [
        ["doc0", "Minority interest"],
        ["doc1", "Minority interest"],
        ["doc6", "Chicago Fire (season 4)"],
    ]
    assert "secret" not in out.read_text(encoding="utf-8")


def test_p1_slices_manifest_sha(tmp_path: Path) -> None:
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets/MANIFEST.sha256").write_text(
        "11  processed/meta.json\n22  processed/nq_1m/passages.parquet\n", encoding="utf-8"
    )
    assert slices.manifest_sha(tmp_path, slices.PASSAGES) == "22"
