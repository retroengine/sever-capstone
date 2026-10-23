"""The beginner diagrams carry the engine's own numbers for the record shown (Phase 4).

Oracle A: §4.2 (x̃ = round(x·2²⁴), ties to even), §7.1–7.3 (the record's group is where routing put
it), §11.1 (the certificate's TLV layout, walked again here by hand: u8 tag ‖ u32be length ‖ value,
tags 1 … 13 then 0xFF and the signature). Oracle E: the engine's events and receipts.
"""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from sever_studio import explain
from sever_studio.actions import Studio

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = ROOT / "studio/work" / f"test-explain-{tmp_path_factory.getbasetemp().name}"
    s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def test_explain_the_insert_flow_is_the_records_own_route(studio: Studio) -> None:
    b = studio.backend
    rid = next(r for r, v in b.index.records.items() if v.group.startswith("frozen-"))
    flow = explain.insert_flow(studio, rid)
    text = "\n".join(f"{t}: {body}" for t, body in flow)
    xt = np.rint(b.vector_of(rid).astype(np.float64) * 2.0**24).astype(np.int64)
    assert f"{xt[0]:,}" in text
    assert b.index.records[rid].group in flow[-1][1]
    assert b.index.records[rid].group in flow[3][1]  # in distribution: its nearest frozen centre
    assert "≤ τ" in flow[4][1]


def test_explain_the_delete_flow_carries_the_engines_n_and_commitment(studio: Studio) -> None:
    b = studio.backend
    rid = next(r for r, v in b.index.records.items() if v.group.startswith("frozen-"))
    g = b.index.records[rid].group
    n = dict(b.live.group_sizes(b.cid))[g]
    d = studio.delete([rid])
    flow = explain.delete_flow(studio, d)
    text = "\n".join(f"{t}: {body}" for t, body in flow)
    assert f"n {n} → {n - 1}" in text
    cert = (b.receipts / f"{d.lsns[0]}.cert").read_bytes()
    at, tags = 0, {}
    while cert[at] != 0xFF:
        t, ln = cert[at], int.from_bytes(cert[at + 1 : at + 5], "big")
        tags[t] = cert[at + 5 : at + 5 + ln]
        at += 5 + ln
    assert tags[3].hex()[:12] in text
    assert f"#{d.lsns[0]}" in text


def test_explain_names_the_certificate_field_a_byte_is_in(studio: Studio) -> None:
    b = studio.backend
    lsn = b.index.receipts[-1]
    cert = (b.receipts / f"{lsn}.cert").read_bytes()
    assert explain.cert_field_at(cert, 0)[0] == 1
    assert explain.cert_field_at(cert, 5)[1] == "commitment_to_deleted_vector (C_t)"
    starts = []
    at = 0
    while cert[at] != 0xFF:
        starts.append((cert[at], at))
        at += 5 + int.from_bytes(cert[at + 1 : at + 5], "big")
    tag6 = dict(starts)[6]
    assert explain.cert_field_at(cert, tag6 + 10)[0] == 6
    assert explain.cert_field_at(cert, len(cert) - 1)[1] == "operator signature"


def test_explain_a_log_proof_is_one_hash_per_level() -> None:
    assert explain.levels(1) == 0
    assert explain.levels(2) == 1
    assert explain.levels(13_204) == 14
