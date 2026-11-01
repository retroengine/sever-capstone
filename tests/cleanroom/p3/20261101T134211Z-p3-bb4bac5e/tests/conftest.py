"""Shared fixtures for the SEVER-DB Part 3 clean-room tests.

Every test makes its own folders under $SEVER_SCRATCH (ext4); nothing is shared between tests.
"""

import os
import sys
import zlib

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))

import helpers as h  # noqa: E402
import sevlib  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "req(id, ...): the spec requirement IDs (SR-<section>-<n>) a test checks")


@pytest.fixture
def art16():
    """The d = 16, 4-group artefact, parsed per §6.3."""
    return sevlib.parse_artefact(h.SMALL)


@pytest.fixture
def rng(request):
    """A per-test generator for test vectors (never passed to the SDK)."""
    seed = zlib.crc32(request.node.nodeid.encode())
    return np.random.default_rng(seed)


@pytest.fixture
def env():
    """Fresh data and key folders on ext4."""
    return h.Env()


@pytest.fixture
def db16(env):
    """An open d = 16 database with one collection over the small artefact (spawn target 200)."""
    db = h.open_db(env)
    cid = db.create_collection(h.SMALL)
    yield h.Ctx(env, db, cid)
    h.quiet_close(db)


@pytest.fixture
def user():
    from sever_db_p3 import UserKey

    return UserKey.generate()
