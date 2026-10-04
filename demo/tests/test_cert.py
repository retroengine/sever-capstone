"""Deletion certificates (spec §11.1, §11.3), Part 3 preview.

Certificates come from real deletions in a synthetic index (engine code) and are checked by the
independent verifier (python/sever_verify). Attacks must be rejected.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from sever_demo import cert as engine_cert
from sever_demo import group as group_module
from sever_demo.crypto import ed25519_keypair, scalar_bytes
from sever_demo.index import Index
from sever_demo.partition import route
from sever_verify.certificate import FAIL, NOT_CHECKED, PASS, ParseError, parse, verify
from sever_verify.ristretto import IDENTITY
from synthetic import D, K, quantised_rows, record_ids, unit_rows

N_ROWS = 60
REPO = Path(__file__).resolve().parents[1]


def committed_index() -> Index:
    vectors = quantised_rows(N_ROWS)
    centroids = unit_rows(K, seed=7).astype(np.float64)
    index = Index(vectors, record_ids(N_ROWS), route(vectors, centroids), K)
    for rid in record_ids(N_ROWS):
        index.insert(rid)
    index.enable_commitments()
    return index


def one_certificate() -> tuple[bytes, dict, Index]:
    index = committed_index()
    index.delete("doc5")
    assert index.last_certificate is not None
    return index.last_certificate, index.anchors(), index


def statuses(report) -> dict[str, str]:
    return {step.split(" ")[0]: status for step, status, _ in report.steps}


def test_certificate_from_a_real_deletion_verifies() -> None:
    data, anchors, _ = one_certificate()
    report = verify(data, anchors)
    assert report.accepted
    assert statuses(report) == {
        "1": PASS,
        "2": PASS,
        "3": NOT_CHECKED,
        "4": NOT_CHECKED,
        "5": NOT_CHECKED,
        "6a": PASS,
        "6b": PASS,
        "6c": PASS,
    }


def test_certificate_layout_section_11_1() -> None:
    # Tags 1..13 in order, then 0xFF ‖ u32be 64 ‖ signature; size = fixed fields + proof.
    data, _, _ = one_certificate()
    fields, signed, sig = parse(data, D)
    assert sorted(fields) == list(range(1, 14))
    assert len(fields[4]) == 64 + 32 * D
    assert fields[5] == fields[6] == fields[7] == b""  # preview: no log
    assert data[len(signed)] == 0xFF
    assert len(sig) == 64
    assert len(data) == 13 * 5 + 32 * 3 + (64 + 32 * D) + 4 + 64 + 8 + 1 + 1 + 16 + 5 + 64


def test_engine_tlv_matches_the_spec_encoding() -> None:
    assert engine_cert.tlv(9, b"\xaa\xbb") == b"\x09\x00\x00\x00\x02\xaa\xbb"


@pytest.mark.mustfail
@pytest.mark.parametrize(
    "attack", ["missing", "repeated", "out_of_order", "wrong_length", "trailing", "no_trailer"]
)
def test_strict_parse_rejects(attack: str) -> None:
    # §11.1: a parser MUST reject missing, repeated or out-of-order tags, wrong fixed lengths and
    # trailing bytes.
    data, anchors, _ = one_certificate()
    fields, signed, sig = parse(data, D)
    parts = [engine_cert.tlv(t, fields[t]) for t in range(1, 14)]
    trailer = b"\xff" + (64).to_bytes(4, "big") + sig
    bad = {
        "missing": b"".join(parts[:-1]) + trailer,
        "repeated": parts[0] + b"".join(parts) + trailer,
        "out_of_order": parts[1] + parts[0] + b"".join(parts[2:]) + trailer,
        "wrong_length": b"".join(parts[:8])
        + engine_cert.tlv(9, fields[9][:63])
        + b"".join(parts[9:])
        + trailer,
        "trailing": data + b"\x00",
        "no_trailer": signed,
    }[attack]
    with pytest.raises(ParseError):
        parse(bad, D)
    assert not verify(bad, anchors).accepted


@pytest.mark.mustfail
def test_any_single_byte_flip_is_rejected() -> None:
    # Every field is covered by the signature, the proof or the strict parser.
    data, anchors, _ = one_certificate()
    positions = sorted(set(range(0, len(data), 37)) | {len(data) - 1, len(data) - 64})
    for pos in positions:
        bad = bytearray(data)
        bad[pos] ^= 0x01
        assert not verify(bytes(bad), anchors).accepted, f"flip at byte {pos} accepted"


@pytest.mark.mustfail
def test_wrong_operator_key_is_rejected() -> None:
    data, anchors, _ = one_certificate()
    other_pk, _ = ed25519_keypair()
    forged = dict(anchors, operator_public_keys={"0": other_pk.hex()})
    report = verify(data, forged)
    assert statuses(report)["2"] == FAIL
    assert not report.accepted


def sign_facts(index: Index, **changes) -> bytes:
    """Re-issue the index's own deletion facts with some changed fields, signed by a key the test
    holds: shows that the verifier's other checks catch it even when the signature is valid."""
    data = index.last_certificate
    assert data is not None
    f, _, _ = parse(data, D)
    facts = engine_cert.DeletionFacts(
        c_t=f[1],
        c_s_pre=f[2],
        c_s_post=f[3],
        proof=f[4],
        scrambled_id=f[9],
        database_lsn=int.from_bytes(f[10], "big"),
        group_emptied=f[11] == b"\x01",
        collection_id=f[13],
    )
    facts = engine_cert.DeletionFacts(**{**facts.__dict__, **changes})
    pk, sk = ed25519_keypair()
    index.operator_public_key = pk
    return engine_cert.issue(facts, sk)


@pytest.mark.mustfail
def test_identity_commitment_rejected() -> None:
    # §9.9 / §11.3 step 1: C_t MUST NOT be the identity.
    _, _, index = one_certificate()
    bad = sign_facts(index, c_t=IDENTITY)
    report = verify(bad, index.anchors())
    assert statuses(report)["1"] == FAIL


@pytest.mark.mustfail
def test_operator_who_just_subtracts_is_caught() -> None:
    # The trap the proof closes: publish C_S_post' = some other point with a valid signature.
    # The public check 6a or the proof 6b must fail.
    _, _, index = one_certificate()
    f, _, _ = parse(index.last_certificate or b"", D)
    bad = sign_facts(index, c_s_post=f[2])  # claim nothing changed
    st = statuses(verify(bad, index.anchors()))
    assert st["6a"] == FAIL or st["6b"] == FAIL


@pytest.mark.mustfail
def test_proof_replayed_with_another_lsn_fails() -> None:
    _, _, index = one_certificate()
    bad = sign_facts(index, database_lsn=999)
    assert statuses(verify(bad, index.anchors()))["6b"] == FAIL


@pytest.mark.mustfail
def test_false_emptied_flag_fails() -> None:
    _, _, index = one_certificate()
    bad = sign_facts(index, group_emptied=True)  # the group still has members
    assert statuses(verify(bad, index.anchors()))["6c"] == FAIL


def test_emptying_a_group_is_disclosed() -> None:
    # §11.1 tag 11 and §11.3 step 6: emptied = 1 iff C_S_post is the identity.
    index = committed_index()
    gid = min((g for g in range(K) if index.groups[g].n), key=lambda g: index.groups[g].n)
    members = list(index.groups[gid].members)
    for rid in members:
        index.delete(rid)
    data = index.last_certificate
    assert data is not None
    f, _, _ = parse(data, D)
    assert f[3] == IDENTITY
    assert f[11] == b"\x01"
    assert verify(data, index.anchors()).accepted


@pytest.mark.mustfail
def test_sabotage_sb4_breaks_the_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    # SB-4: r_agg is not reduced on delete. C_S still moves by C_t (so 6a passes), but the operator
    # no longer knows the opening of C_S_post, so the proof (6b) fails.
    index = committed_index()
    monkeypatch.setattr(group_module, "SABOTAGE", "SB-4")
    index.delete("doc5")
    st = statuses(verify(index.last_certificate or b"", index.anchors()))
    assert st["6a"] == PASS
    assert st["6b"] == FAIL


def test_certificate_holds_no_secret() -> None:
    # §13.2 / CLAUDE.md §8: a certificate is public; it must not contain r_t or r_agg.
    index = committed_index()
    row = index.row_of["doc5"]
    r_t = index.groups[0].blinding[row]  # type: ignore[index]
    gid = index.locator["doc5"]
    index.delete("doc5")
    data = index.last_certificate or b""
    assert scalar_bytes(r_t) not in data
    assert scalar_bytes(index.groups[gid].r_agg) not in data
    assert b"doc5" not in data  # only the scrambled ID (§9.7)


def test_command_line_verifier_runs_without_engine_code(tmp_path: Path) -> None:
    # "Anyone with the file": the verifier as its own process, which must never load engine code.
    data, anchors, _ = one_certificate()
    (tmp_path / "c.cert").write_bytes(data)
    (tmp_path / "anchors.json").write_text(json.dumps(anchors), encoding="utf-8")
    # The wrapper runs the verifier's command line, then fails if any engine module was loaded.
    env = {**os.environ, "PYTHONPATH": str(REPO / "python")}
    wrapper = (
        "import runpy, sys\n"
        "sys.argv = ['sever_verify', *sys.argv[1:]]\n"
        "code = 0\n"
        "try:\n    runpy.run_module('sever_verify', run_name='__main__', alter_sys=True)\n"
        "except SystemExit as e:\n    code = e.code\n"
        "assert not [m for m in sys.modules if m.startswith('sever_demo')], 'engine code loaded'\n"
        "sys.exit(code)\n"
    )
    run = [sys.executable, "-c", wrapper, "anchors.json", "c.cert"]
    ok = subprocess.run(run, env=env, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "ACCEPTED" in ok.stdout
    bad = bytearray(data)
    bad[100] ^= 1
    (tmp_path / "c.cert").write_bytes(bytes(bad))
    rejected = subprocess.run(
        run, env=env, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert rejected.returncode == 1
    assert "REJECTED" in rejected.stdout
