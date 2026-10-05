"""L5 model-based stateful tests (Build §4.7) at the small fixture size.

Random operation sequences run by the reference model C-18 and replayed by the Rust engine, compared
after every step (placements, outcomes, errors, the blob hash of every touched group), with the
survivors check after every deletion, and stats, every blob and the top-k of 24 queries at each
checkpoint.
"""

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sever_testkit import streams

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def replayer() -> Path:
    subprocess.run(
        ["cargo", "build", "-q", "--release", "-p", "sever-tracekit"], cwd=ROOT, check=True
    )
    return ROOT / "target/release/sever-tracekit"


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("small-fixture")
    streams.write_fixture(ROOT, d)
    return d


def replay(replayer: Path, fixture: Path, ops: list[streams.Op], name: str) -> dict[str, object]:
    trace = fixture / f"{name}.jsonl"
    with trace.open("w", encoding="utf-8") as f:
        streams.write_stream_trace(fixture, f, ops)
    out = subprocess.run(
        [str(replayer), "replay", str(trace), "--root", str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout.strip(), out.stderr
    result: dict[str, object] = json.loads(out.stdout.strip().splitlines()[-1])
    result["stderr"] = out.stderr[-1500:]
    return result


ID = st.integers(0, 30).map(lambda i: f"s{i}")
OP = st.one_of(
    st.tuples(st.just("i"), st.integers(0, 119), ID),  # in distribution
    st.tuples(st.just("i"), st.integers(120, 239), ID),  # out of distribution
    st.tuples(st.just("d"), st.lists(ID, min_size=1, max_size=1)),  # delete (maybe absent)
    st.tuples(st.just("d"), st.lists(ID, min_size=2, max_size=6)),  # delete_user, repeats allowed
    st.tuples(st.just("c")),  # search checkpoint
)


@pytest.mark.spec(
    "SR-5.3-1", "SR-5.4-1", "SR-5.4-2", "SR-3.2-3", "SR-3.2-4", "SR-7.3-1", "SR-7.4-2", "SR-8.1-3"
)
@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(ops=st.lists(OP, min_size=1, max_size=160))
def test_p1_stateful_engine_matches_model(
    replayer: Path, fixture_dir: Path, ops: list[streams.Op]
) -> None:
    r = replay(replayer, fixture_dir, ops, "stateful")
    assert r["result"] == "PASS", r


def test_p1_stateful_long_seeded_stream(replayer: Path, fixture_dir: Path) -> None:
    """One long stream (2,000 operations): many flushes, empty groups and re-inserts."""
    ops = streams.random_ops(np.random.Generator(np.random.PCG64(20261005)), 2_000)
    r = replay(replayer, fixture_dir, ops, "long")
    assert r["result"] == "PASS", r
    assert int(str(r["survivor_groups_checked"])) > 100
