"""The sever-demo report renderer."""

from pathlib import Path
from typing import Any

from sever_demo import render

H = "ab" * 32


def report(exact: bool = True) -> dict[str, Any]:
    return {
        "format": "sever-demo-idea-1",
        "data": "synthetic",
        "seed": 42,
        "d": 16,
        "artefact_sha256": H,
        "spawn_target": 8,
        "stream_order": "interleaved",
        "build": {
            "records": 240,
            "accepted": 240,
            "rejected": {},
            "frozen": 4,
            "spawned": 2,
            "big_n": 238,
            "k": 6,
            "holding": 2,
            "out_of_distribution": 121,
            "ood_rate": 0.5,
            "seconds": 0.01,
        },
        "target": {
            "cohort": "<Culture & Australia>",
            "record_ids": ["a", "b"],
            "groups": ["frozen-0001"],
            "rule": "r",
        },
        "groups": [
            {
                "group": "frozen-0001",
                "n_before": 27,
                "n_after": 25,
                "s_sha_before": H,
                "s_sha_after": H,
                "blob_sha_before": H,
                "blob_sha_after": H,
                "survivors_blob_sha": H,
                "exact": exact,
            }
        ],
        "holding": {"n_before": 2, "n_after": 2, "cohort_members": 0},
        "untouched": {"groups": 5, "unchanged": 5},
        "big_n": [238, 236],
        "outcomes": ["deleted from frozen-0001"],
        "second_delete": {"all_already_absent": True, "state_unchanged": True},
        "ghost": {
            "per_group": [
                {
                    "group": "frozen-0001",
                    "soft_delete_distance": 5e-3,
                    "float_mean_max_abs_diff": 2e-8,
                    "float_mean_components_differing": 12,
                    "sever_max_abs_diff": 0,
                }
            ],
            "summary": [
                {
                    "system": "soft-delete IVF",
                    "deleted_record_still_stored": True,
                    "distance": 5e-3,
                    "measure": "m",
                },
                {
                    "system": "SEVER (Part 1)",
                    "deleted_record_still_stored": False,
                    "distance": 0.0,
                    "measure": "m",
                },
            ],
        },
        "search": {
            "queries": 0,
            "k": 10,
            "queries_hit_before": 0,
            "deleted_returned_after": 0,
            "example": {
                "query": "own vector of a",
                "deleted_record": "a",
                "rank_before": 1,
                "before": [["a", 0.0]],
                "after": [["c", 0.1]],
            },
        },
        "invariants": "ok",
    }


def test_p1_demo_render_escapes_and_marks() -> None:
    page = render.render(report())
    assert "&lt;Culture &amp; Australia&gt;" in page
    assert "<Culture" not in page
    assert "frozen-0001" in page
    assert "<svg" in page
    assert '<span class="bad">' not in page


def test_p1_demo_render_shows_a_failed_check() -> None:
    assert '<span class="bad">✗</span>' in render.render(report(exact=False))


def test_p1_demo_render_cli_writes_html(tmp_path: Path) -> None:
    import json

    src = tmp_path / "r.json"
    src.write_text(json.dumps(report()), encoding="utf-8")
    assert render._main([str(src)]) == 0
    assert (tmp_path / "r.html").read_text(encoding="utf-8").startswith("<!doctype html>")
