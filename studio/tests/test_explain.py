"""Studio's words carry the engine's own numbers, and nothing it did not observe (audit 2, H4).

Oracle A: §4.2 (x̃ = round(x·2²⁴), ties to even), §7.1–7.3 (the record's group is where routing put
it), §11.1 (the certificate's TLV layout, walked again here by hand: u8 tag ‖ u32be length ‖ value,
tags 1 … 13 then 0xFF and the signature). Oracle E: the engine's events and receipts.
"""

from collections.abc import Iterator

import pytest
from conftest import CFG, WORK

from sever_studio import explain
from sever_studio.actions import Studio


@pytest.fixture(scope="module")
def studio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Studio]:
    work = WORK / f"test-explain-{tmp_path_factory.getbasetemp().name}"
    s = Studio(CFG, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    yield s
    s.backend.close()
    s.backend.wipe()


def test_explain_the_deleted_line_states_only_the_engines_n_and_receipt(studio: Studio) -> None:
    b = studio.backend
    rid = next(r for r, v in b.index.records.items() if v.group.startswith("frozen-"))
    g = b.index.records[rid].group
    n = dict(b.live.group_sizes(b.cid))[g]  # the engine's own count before (§5.2)
    d = studio.delete([rid])
    line = explain.deleted_line(d)
    assert f"{g} n {n} → {n - 1}" in line  # §5.3: n − 1, exactly
    assert f"#{d.lsns[0]}" in line
    for unobserved in ("key", "overwritten", "witness", "C_S"):  # audit 2, H4
        assert unobserved not in line


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
