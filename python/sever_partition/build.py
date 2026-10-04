"""The partition builder C-15 (spec §6.2), and its command line ``sever-partition build`` (§16.3).

    uv run python -m sever_partition.build --seed 42            # one seed
    uv run python -m sever_partition.build --all-seeds          # the five overview seeds

Writes ``artefacts/partition-seed<seed>.svp`` and a summary ``.json`` next to it, and refuses to
write either unless the independent Ledoit–Wolf oracle agrees (step 7).

Sabotage SB-10 (Build §2.6): with ``SEVER_SABOTAGE=SB-10`` in the environment, step 4 averages
per-group Ledoit–Wolf fits instead of one pooled fit. The oracle must then refuse the artefact.
"""

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import scipy.linalg
from numpy.typing import NDArray
from sklearn.cluster import KMeans
from sklearn.covariance import LedoitWolf
from threadpoolctl import threadpool_limits

from sever_partition import arith, artefact, lw_oracle
from sever_testkit.seeds import SEEDS, sub_seed

#: §6.2 step 7: oracle tolerances (spec §18.2 ``independent_oracle_tolerance``).
SHRINKAGE_TOL: Final = 1e-12
THRESHOLD_TOL: Final = 1e-9
#: §6.2: v1 frozen groups.
K_FROZEN_V1: Final = 128
#: §6.2 step 6: the 99th percentile, linear interpolation.
PERCENTILE: Final = 99.0


class OracleDisagreementError(RuntimeError):
    """§6.2 step 7: the builder and the independent oracle disagree; nothing is written."""


@dataclass(frozen=True)
class BuildResult:
    """A built partition and the evidence that it may be written."""

    artefact: artefact.Artefact
    labels: NDArray[np.int64]
    oracle_shrinkage: float
    oracle_tau: float


def _sabotage(item: str) -> bool:
    return os.environ.get("SEVER_SABOTAGE", "") == item


def _precision(sigma: NDArray[np.float64]) -> NDArray[np.float64]:
    """§6.2 step 5: P = Σ⁻¹ by Cholesky factorisation, float64."""
    factor = scipy.linalg.cho_factor(sigma, lower=True)
    p: NDArray[np.float64] = scipy.linalg.cho_solve(factor, np.eye(sigma.shape[0]))
    return p


def _tau(
    xhat: NDArray[np.float64],
    centroids: NDArray[np.float64],
    labels: NDArray[np.int64],
    precision: NDArray[np.float64],
) -> float:
    """§6.2 step 6: P99 (linear) of each reference row's §7.2 distance to its own centroid."""
    dists = arith.mahalanobis(xhat, centroids[labels], precision)
    return float(np.percentile(dists, PERCENTILE, method="linear"))


def build(
    x_ref: NDArray[np.float32],
    seed: int,
    sha256_reference: bytes,
    encoder: str,
    k_frozen: int = K_FROZEN_V1,
) -> BuildResult:
    """Spec §6.2 steps 1–7 on the reference rows ``x_ref`` (float32, m × d)."""
    arith.check_rows_normalised(x_ref)  # §6.2 inputs: every row normalised per §4.1
    m, d = x_ref.shape

    # Step 1: quantise and dequantise; every later step uses X̂.
    xhat = arith.dequantise(arith.quantise(x_ref))

    # Step 2: k-means. One thread for BLAS and OpenMP, so reruns are bit-identical (overview §9.3).
    # random_state is seed_kmeans mod 2^32 (DB-57).
    with threadpool_limits(limits=1):
        km = KMeans(
            n_clusters=k_frozen,
            init="k-means++",
            n_init=10,
            max_iter=300,
            tol=1e-4,
            algorithm="lloyd",
            random_state=sub_seed(seed, "kmeans") % 2**32,
        ).fit(xhat)
    centroids = np.asarray(km.cluster_centers_, dtype=np.float64)
    labels = np.asarray(km.labels_, dtype=np.int64)

    # Step 3: pooled residuals R_j = x̂_j − μ_{c(j)}, stacked.
    residuals = xhat - centroids[labels]

    # Step 4: ONE Ledoit–Wolf fit over all residual rows (assume_centered = False).
    if _sabotage("SB-10"):
        # SB-10: average per-group fits instead (Build §2.6). Must be refused by step 7.
        fits = [
            LedoitWolf(assume_centered=False).fit(residuals[labels == g])
            for g in range(k_frozen)
            if (labels == g).sum() > 1
        ]
        sigma = np.mean([f.covariance_ for f in fits], axis=0)
        shrinkage = float(np.mean([f.shrinkage_ for f in fits]))
    else:
        lw = LedoitWolf(assume_centered=False).fit(residuals)
        sigma = np.asarray(lw.covariance_, dtype=np.float64)
        shrinkage = float(lw.shrinkage_)

    # Step 5: precision by Cholesky; stored and used as stored.
    precision = _precision(sigma)

    # Step 6: τ, with the engine's summation order.
    tau = _tau(xhat, centroids, labels, precision)

    # Step 7: the independent oracle; refuse to write unless it agrees.
    o_sigma, o_shrinkage = lw_oracle.ledoit_wolf(residuals)
    o_tau = _tau(xhat, centroids, labels, _precision(o_sigma))
    if abs(o_shrinkage - shrinkage) > SHRINKAGE_TOL or abs(o_tau - tau) > THRESHOLD_TOL:
        raise OracleDisagreementError(
            f"shrinkage differs by {abs(o_shrinkage - shrinkage):.3e}, "
            f"tau by {abs(o_tau - tau):.3e}; artefact not written"
        )

    art = artefact.Artefact(
        d=d,
        k_frozen=k_frozen,
        seed=seed,  # §6.3: the run seed, not the derived k-means seed
        tau=tau,
        lw_shrinkage=shrinkage,
        m=m,
        sha256_reference=sha256_reference,
        encoder=encoder,
        centroids=centroids,
        precision=precision,
    )
    return BuildResult(art, labels, o_shrinkage, o_tau)


def sha256_rows(x: NDArray[np.float32]) -> bytes:
    """§6.3 ``sha256_reference``: SHA-256 of the raw little-endian float32 rows, in file order."""
    return hashlib.sha256(np.ascontiguousarray(x, dtype="<f4").tobytes()).digest()


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sever-partition build", description=__doc__)
    ap.add_argument("--seed", type=int, action="append", help="run seed (repeatable)")
    ap.add_argument("--all-seeds", action="store_true", help="the five overview seeds")
    ap.add_argument("--root", type=Path, default=Path("."), help="repository root")
    ap.add_argument("--out", type=Path, default=Path("artefacts"))
    args = ap.parse_args(argv)
    seeds = list(SEEDS) if args.all_seeds else (args.seed or [42])

    root: Path = args.root
    meta = json.loads((root / "datasets/processed/meta.json").read_text(encoding="utf-8"))
    enc = meta["pins"]["repos"]["encoder"]
    encoder = f"{enc['repo_id']}@{enc['revision']}"
    x_ref = np.load(root / "datasets/processed/sciq_reference/embeddings.npy")
    sha_ref = sha256_rows(x_ref)
    if sha_ref.hex() != meta["encode"]["sciq"]["sha256_rows"]:
        print("reference embeddings do not match meta.json; refusing", file=sys.stderr)
        return 2

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        res = build(x_ref, seed, sha_ref, encoder)
        blob = artefact.encode(res.artefact)
        path = out / f"partition-seed{seed}.svp"
        path.write_bytes(blob)
        counts = np.bincount(res.labels, minlength=res.artefact.k_frozen)
        summary = {
            "seed": seed,
            "file": path.name,
            "sha256_artefact": blob[-32:].hex(),
            "bytes": len(blob),
            "tau": res.artefact.tau,
            "lw_shrinkage": res.artefact.lw_shrinkage,
            "oracle_tau_diff": abs(res.oracle_tau - res.artefact.tau),
            "oracle_shrinkage_diff": abs(res.oracle_shrinkage - res.artefact.lw_shrinkage),
            "m": res.artefact.m,
            "group_sizes": {"min": int(counts.min()), "max": int(counts.max())},
            "encoder": encoder,
            "sabotage": os.environ.get("SEVER_SABOTAGE", ""),
        }
        path.with_suffix(".json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
