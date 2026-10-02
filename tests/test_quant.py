import numpy as np
import pytest

from sever_demo.quant import dequantise, quantise

# Spec values written out here on purpose (spec section 4.2), NOT imported from quant.py.
SCALE = 2**24
BOUND = 2**24 + 16
SPEC_TOL = 8 * 2**-23


def test_quant_ties_to_even():
    # T1: exact halves must round to the EVEN neighbour: 0.5->0, 1.5->2, 2.5->2, -0.5->0
    halves = np.array([[0.5, 1.5, 2.5, -0.5]], dtype=np.float32) * 2.0**-24
    Q = quantise(halves)
    assert Q.dtype == np.int32
    assert Q.tolist() == [[0, 2, 2, 0]]


def test_quant_bound_at_tolerance_edge():
    # T2: the longest allowed row is length 1 + SPEC_TOL; its biggest number is that long.
    X = np.zeros((1, 16), dtype=np.float32)
    X[0, 0] = 1 + SPEC_TOL
    Q = quantise(X)
    assert int(np.abs(Q).max()) == BOUND          # sits exactly ON the bound, allowed
    assert int(np.abs(Q).max()) <= BOUND


def test_quant_rejects_beyond_bound():
    # T2: one step past the edge must be refused, not silently accepted.
    X = np.zeros((1, 16), dtype=np.float32)
    X[0, 0] = 1 + SPEC_TOL + 2**-23
    with pytest.raises(ValueError):
        quantise(X)


def test_dequantise_round_trip_error():
    # converting back loses at most half a step: 2**-25
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 16))
    X = (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)
    back = dequantise(quantise(X))
    assert back.dtype == np.float64
    assert np.abs(back - X.astype(np.float64)).max() <= 2**-25
    
@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_quant_rejects_non_finite(bad_value):
    # NaN and infinity must be refused, never turned into some random integer.
    X = np.zeros((1, 16), dtype=np.float32)
    X[0, 3] = bad_value
    with pytest.raises(ValueError):
        quantise(X)