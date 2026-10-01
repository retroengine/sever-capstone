import numpy as np
import pytest

from sever_demo.data import check_norms

# Written out here on purpose (spec section 4.1), NOT imported from the code under test.
# If the code's tolerance were loosened, these tests must still catch it.
SPEC_TOL = 8 * 2**-23


def make_unit_rows(n_rows=6, d=16, seed=0):
    """n_rows random vectors of length 1, stored as float32 (like the real data)."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n_rows, d))
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    return X.astype(np.float32)


def test_norm_accepts_good_rows():
    result = check_norms(make_unit_rows())
    assert result["non_finite"] == 0
    assert result["bad_length"] == 0
    assert result["first_bad_rows"] == []


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_norm_rejects_non_finite(bad_value):
    X = make_unit_rows()
    X[2, 5] = bad_value
    result = check_norms(X)
    assert result["non_finite"] == 1
    assert result["bad_length"] == 0          # counted once, not twice
    assert result["first_bad_rows"] == [2]


def test_norm_rejects_just_outside_tolerance():
    X = make_unit_rows()
    X[3] = (X[3].astype(np.float64) * (1 + 2 * SPEC_TOL)).astype(np.float32)
    result = check_norms(X)
    assert result["bad_length"] == 1
    assert result["first_bad_rows"] == [3]


def test_norm_accepts_just_inside_tolerance():
    X = make_unit_rows()
    X[3] = (X[3].astype(np.float64) * (1 + 0.5 * SPEC_TOL)).astype(np.float32)
    result = check_norms(X)
    assert result["bad_length"] == 0
    assert result["first_bad_rows"] == []


def test_norm_row_numbers_correct_across_chunks():
    X = make_unit_rows(n_rows=10)
    X[7] *= 2                                   # clearly wrong row
    result = check_norms(X, chunk_rows=3)       # 7 sits in the third chunk
    assert result["first_bad_rows"] == [7]