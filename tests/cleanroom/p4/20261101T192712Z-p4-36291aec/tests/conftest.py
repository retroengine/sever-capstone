import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import helpers  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "req(*ids): the SR-<section>-<n> requirement(s) a test checks")


@pytest.fixture
def root():
    """One fresh ext4 folder per test (isolation; PROMPT)."""
    r = helpers.new_root()
    yield r
    helpers.rmtree(r)


@pytest.fixture
def dirs(root):
    return helpers.new_dirs(root)


@pytest.fixture
def user():
    from sever_db import UserKey

    return UserKey.generate()


@pytest.fixture
def small_db(dirs):
    """A d = 16 database (p1_partition_small.svp: 4 frozen groups) with one collection."""
    data, keys = dirs
    db = helpers.open_db(data, keys, d=16)
    cid = db.create_collection(helpers.SMALL_SVP)
    yield db, cid, data, keys
    try:
        db.close()
    except Exception:
        pass
