"""The builder's command line on a tiny dataset root, and the rejection paths of arith/artefact."""

import dataclasses
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from sever_partition import arith, artefact, build
from sever_testkit import synthetic


def fake_root(tmp: Path, sha_ok: bool = True) -> Path:
    x = synthetic.clustered(600, 16, 4, seed=42)
    (tmp / "datasets/processed/sciq_reference").mkdir(parents=True)
    np.save(tmp / "datasets/processed/sciq_reference/embeddings.npy", x)
    sha = build.sha256_rows(x).hex() if sha_ok else "00" * 32
    meta = {
        "pins": {"repos": {"encoder": {"repo_id": "test/encoder", "revision": "0"}}},
        "encode": {"sciq": {"sha256_rows": sha}},
    }
    (tmp / "datasets/processed/meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp


@pytest.mark.spec("SR-6.2-7", "SR-6.3-1")
def test_p1_partition_cli_builds_a_valid_artefact(tmp_path: Path) -> None:
    root = fake_root(tmp_path)
    out = tmp_path / "out"
    assert build._main(["--root", str(root), "--out", str(out), "--seed", "42"]) == 0
    a = artefact.decode((out / "partition-seed42.svp").read_bytes())
    assert (a.d, a.k_frozen, a.seed, a.encoder) == (16, 128, 42, "test/encoder@0")
    summary = json.loads((out / "partition-seed42.json").read_text(encoding="utf-8"))
    assert summary["oracle_tau_diff"] <= 1e-9
    assert summary["oracle_shrinkage_diff"] <= 1e-12


def test_p1_partition_cli_refuses_reference_not_matching_meta(tmp_path: Path) -> None:
    root = fake_root(tmp_path, sha_ok=False)
    assert build._main(["--root", str(root), "--out", str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()


@pytest.mark.spec("SR-4.1-1", "SR-4.1-3")
def test_p1_partition_reference_rows_are_checked(tmp_path: Path) -> None:
    good = synthetic.clustered(20, 16, 2, seed=1)
    arith.check_rows_normalised(good)
    with pytest.raises(arith.NotNormalisedError):
        arith.check_rows_normalised(good.astype(np.float64))
    with pytest.raises(arith.NotNormalisedError):
        arith.check_rows_normalised(good[0])
    bad = good.copy()
    bad[3, 2] = np.nan
    with pytest.raises(arith.NotNormalisedError):
        arith.check_rows_normalised(bad)


@pytest.mark.spec("SR-6.3-1", "SR-6.3-2")
def test_p1_partition_artefact_encode_and_decode_reject_bad_input() -> None:
    a = build.build(synthetic.clustered(600, 16, 4, seed=42), 42, b"\0" * 32, "e", k_frozen=4)
    good = artefact.encode(a.artefact)
    assert artefact.decode(good).d == 16
    with pytest.raises(artefact.ArtefactError):
        artefact.encode(dataclasses.replace(a.artefact, sha256_reference=b"\0"))
    with pytest.raises(artefact.ArtefactError):
        artefact.encode(dataclasses.replace(a.artefact, centroids=a.artefact.centroids[:2]))
    with pytest.raises(artefact.ArtefactError):
        artefact.decode(good[:20])

    def rehash(body: bytes) -> bytes:
        return body + hashlib.sha256(body).digest()

    body = bytearray(good[:-32])
    body[0] ^= 1
    with pytest.raises(artefact.ArtefactError, match="magic"):
        artefact.decode(rehash(bytes(body)))
    body = bytearray(good[:-32])
    body[9] = 2  # u16be version at offset 8
    with pytest.raises(artefact.ArtefactError, match="version"):
        artefact.decode(rehash(bytes(body)))
