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
    q = quantise(halves)
    assert q.dtype == np.int32
    assert q.tolist() == [[0, 2, 2, 0]]


def test_quant_bound_at_tolerance_edge():
    # T2: the longest allowed row is length 1 + SPEC_TOL; its biggest number is that long.
    x = np.zeros((1, 16), dtype=np.float32)
    x[0, 0] = 1 + SPEC_TOL
    q = quantise(x)
    assert int(np.abs(q).max()) == BOUND  # sits exactly ON the bound, allowed
    assert int(np.abs(q).max()) <= BOUND


def test_quant_rejects_beyond_bound():
    # T2: one step past the edge must be refused, not silently accepted.
    x = np.zeros((1, 16), dtype=np.float32)
    x[0, 0] = 1 + SPEC_TOL + 2**-23
    with pytest.raises(ValueError, match="beyond"):
        quantise(x)


def test_dequantise_round_trip_error():
    # converting back loses at most half a step: 2**-25
    rng = np.random.default_rng(42)  # project seed (CLAUDE.md §6.2)
    x = rng.normal(size=(50, 16))
    x = (x / np.linalg.norm(x, axis=1, keepdims=True)).astype(np.float32)
    back = dequantise(quantise(x))
    assert back.dtype == np.float64
    assert np.abs(back - x.astype(np.float64)).max() <= 2**-25


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_quant_rejects_non_finite(bad_value):
    # NaN and infinity must be refused, never turned into some random integer.
    x = np.zeros((1, 16), dtype=np.float32)
    x[0, 3] = bad_value
    with pytest.raises(ValueError, match="non-finite"):
        quantise(x)


def test_quant_negative_ties_to_even():
    # §4.2 ties to even on the negative side too: -1.5 -> -2, -2.5 -> -2, -3.5 -> -4.
    halves = np.array([[-1.5, -2.5, -3.5]], dtype=np.float32) * 2.0**-24
    assert quantise(halves).tolist() == [[-2, -2, -4]]


def test_quant_keeps_shape():
    # One i32 per input number, same layout (rows stay rows).
    x = np.zeros((3, 16), dtype=np.float32)
    assert quantise(x).shape == (3, 16)
