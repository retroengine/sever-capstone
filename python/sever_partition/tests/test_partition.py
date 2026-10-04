"""Tests for the partition builder C-15 (spec §6.2) and the artefact codec (§6.3)."""

import hashlib
import json
import math
import struct
from pathlib import Path

import numpy as np
import pytest
from sklearn.covariance import LedoitWolf

from sever_partition import arith, artefact, build, lw_oracle
from sever_testkit import synthetic
from sever_testkit.seeds import SEEDS, sub_seed

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "datasets/processed"


def small_build(seed: int = 42) -> build.BuildResult:
    """The small fixture (Build §2.7): d = 16, 4 frozen groups."""
    x = synthetic.clustered(600, 16, 4, seed=seed)
    return build.build(x, seed, build.sha256_rows(x), "test-encoder@0", k_frozen=4)


# --- seeds (overview §10.6) ------------------------------------------------------------------


@pytest.mark.spec("SR-OV-10.6-1")
def test_p1_seeds_sub_seed_reproduces_the_p0_corpus_seed() -> None:
    meta = json.loads((ROOT / "datasets/processed/meta.json").read_text(encoding="utf-8"))
    assert sub_seed(42, "corpus") == meta["build"]["nq"]["corpus_seed"]["value"]
    assert SEEDS == (42, 123, 777, 2024, 9999)
    with pytest.raises(ValueError, match="unknown"):
        sub_seed(42, "keys")  # never a seed for keys (DB-17)


# --- arithmetic (Python side of §4 and §7.2) ---------------------------------------------------


@pytest.mark.spec("SR-4.2-1")
def test_p1_partition_quantise_matches_golden_vector_5() -> None:
    doc = json.loads((ROOT / "golden/p1_quant_half_steps.json").read_text(encoding="utf-8"))
    for row in doc["rows"]:
        x = np.frombuffer(bytes.fromhex(row["x_f32_bits"]), dtype=">f4").astype(np.float32)
        assert int(arith.quantise(x.reshape(1, 1))[0, 0]) == row["q"]


@pytest.mark.spec("SR-7.2-1", "SR-6.2-6")
def test_p1_partition_mahalanobis_is_the_pinned_sequential_order() -> None:
    rng = np.random.Generator(np.random.PCG64(7))
    d = 16
    a = rng.standard_normal((d, d))
    p = a @ a.T + d * np.eye(d)
    xhat, mu = rng.standard_normal((5, d)), rng.standard_normal((5, d))
    got = arith.mahalanobis(xhat, mu, p, chunk=2)
    for r in range(5):
        delta = [float(xhat[r, i] - mu[r, i]) for i in range(d)]
        q = 0.0
        for i in range(d):
            y = 0.0
            for j in range(d):
                y += float(p[i, j]) * delta[j]
            q += delta[i] * y
        assert got[r] == math.sqrt(q)  # bit-identical, not approximately


@pytest.mark.spec("SR-7.2-2")
def test_p1_partition_negative_q_is_an_integrity_violation() -> None:
    p = -np.eye(8)  # not positive definite
    with pytest.raises(arith.IntegrityViolationError):
        arith.mahalanobis(np.ones((1, 8)), np.zeros((1, 8)), p)


# --- the independent oracle (§6.2 step 7) ------------------------------------------------------


@pytest.mark.spec("SR-6.2-7")
def test_p1_partition_oracle_agrees_with_sklearn() -> None:
    for seed in SEEDS:
        x = np.random.Generator(np.random.PCG64(seed)).standard_normal((300, 24)) * np.arange(1, 25)
        sigma, shrink = lw_oracle.ledoit_wolf(x)
        lw = LedoitWolf(assume_centered=False).fit(x)
        assert abs(shrink - lw.shrinkage_) <= 1e-12
        assert np.max(np.abs(sigma - lw.covariance_)) <= 1e-12 * np.max(np.abs(sigma))


# --- the builder (§6.2) -------------------------------------------------------------------------


@pytest.mark.spec("SR-6.2-1", "SR-6.2-2", "SR-6.2-3", "SR-6.2-4", "SR-6.2-5", "SR-6.2-6")
def test_p1_partition_small_build_is_consistent() -> None:
    res = small_build()
    a = res.artefact
    assert (a.d, a.k_frozen, a.m, a.seed) == (16, 4, 600, 42)
    assert sorted(set(res.labels.tolist())) == [0, 1, 2, 3]
    assert np.allclose(a.precision, a.precision.T, rtol=0, atol=1e-9)
    assert np.linalg.eigvalsh(a.precision).min() > 0  # positive definite
    assert 0.0 <= a.lw_shrinkage <= 1.0
    assert res.oracle_tau == pytest.approx(a.tau, abs=1e-9)
    # τ is the P99 of the reference distances: about 1 % of rows lie above it.
    xhat = arith.dequantise(arith.quantise(synthetic.clustered(600, 16, 4, seed=42)))
    dists = arith.mahalanobis(xhat, a.centroids[res.labels], a.precision)
    assert 0 < int((dists > a.tau).sum()) <= 7


@pytest.mark.spec("SR-6.2-1")
def test_p1_partition_build_refuses_unnormalised_reference_rows() -> None:
    x = synthetic.clustered(100, 16, 4, seed=1)
    x[3] *= 2
    with pytest.raises(arith.NotNormalisedError):
        build.build(x, 42, b"\0" * 32, "e", k_frozen=4)


@pytest.mark.spec("SR-6.2-2")
def test_p1_partition_build_is_deterministic() -> None:
    assert artefact.encode(small_build().artefact) == artefact.encode(small_build().artefact)
    assert artefact.encode(small_build(42).artefact) != artefact.encode(small_build(123).artefact)


@pytest.mark.mustfail
@pytest.mark.spec("SR-6.2-4", "SR-6.2-7")
def test_p1_partition_sb10_per_group_averaging_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """SB-10 (Build §2.6): averaging per-group fits changes the estimate; the oracle refuses."""
    monkeypatch.setenv("SEVER_SABOTAGE", "SB-10")
    with pytest.raises(build.OracleDisagreementError):
        small_build()


# --- the artefact codec (§6.3) -------------------------------------------------------------------


@pytest.mark.spec("SR-6.3-1")
def test_p1_partition_artefact_layout_by_offset() -> None:
    a = small_build().artefact
    blob = artefact.encode(a)
    enc = a.encoder.encode()
    assert blob[:8] == b"SVDBPART"
    assert struct.unpack_from(">HHHQ", blob, 8) == (1, 16, 4, 42)
    assert struct.unpack_from(">dd", blob, 22) == (a.tau, a.lw_shrinkage)
    assert struct.unpack_from(">Q", blob, 38) == (600,)
    assert blob[46:78] == a.sha256_reference
    assert struct.unpack_from(">H", blob, 78) == (len(enc),)
    assert blob[80 : 80 + len(enc)] == enc
    cen_at = 80 + len(enc)
    assert struct.unpack_from(">d", blob, cen_at) == (a.centroids[0, 0],)
    assert struct.unpack_from(">d", blob, cen_at + 8 * 4 * 16) == (a.precision[0, 0],)
    assert len(blob) == 80 + len(enc) + 8 * (4 * 16 + 16 * 16) + 32
    assert blob[-32:] == hashlib.sha256(blob[:-32]).digest()
    back = artefact.decode(blob)
    assert artefact.encode(back) == blob


@pytest.mark.spec("SR-6.3-2")
def test_p1_partition_artefact_decoder_rejects_bad_files() -> None:
    blob = bytearray(artefact.encode(small_build().artefact))

    def rehash(b: bytearray) -> bytes:
        return bytes(b[:-32]) + hashlib.sha256(bytes(b[:-32])).digest()

    flipped = bytearray(blob)
    flipped[100] ^= 1
    with pytest.raises(artefact.ArtefactError, match="sha256"):
        artefact.decode(bytes(flipped))
    bad_magic = bytearray(blob)
    bad_magic[0:1] = b"X"
    with pytest.raises(artefact.ArtefactError, match="magic"):
        artefact.decode(rehash(bad_magic))
    bad_d = bytearray(blob)
    struct.pack_into(">H", bad_d, 10, 12)  # not a multiple of 8
    with pytest.raises(artefact.ArtefactError):
        artefact.decode(rehash(bad_d))
    nan_p = bytearray(blob)
    struct.pack_into(">d", nan_p, len(blob) - 32 - 8, float("nan"))
    with pytest.raises(artefact.ArtefactError, match="non-finite"):
        artefact.decode(rehash(nan_p))
    with pytest.raises(artefact.ArtefactError):
        artefact.decode(rehash(bytearray(blob[:-40] + blob[-32:])))  # truncated


# --- real data (slow; needs datasets/processed) --------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not (DATA / "sciq_reference/embeddings.npy").exists(), reason="no data")
@pytest.mark.spec("SR-6.2-7")
def test_p1_partition_real_seed42_rebuild_is_byte_identical() -> None:
    """C-15 "proven by": oracle agreement and a stable artefact hash across reruns (P1-T6)."""
    x = np.load(DATA / "sciq_reference/embeddings.npy")
    sha = build.sha256_rows(x)
    first = artefact.encode(build.build(x, 42, sha, "e@0").artefact)
    second = artefact.encode(build.build(x, 42, sha, "e@0").artefact)
    assert first == second
