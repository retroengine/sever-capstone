"""Vector validation on insert (§4.1, through §15.1 step 1) and its errors (§17)."""

import math

import numpy as np
import pytest
import sever_db_p3 as sdk

import helpers as h
import sevlib

ULP_ABOVE_1 = 2.0**-23  # float32 spacing in [1, 2)
ULP_BELOW_1 = 2.0**-24  # float32 spacing in [0.5, 1)


def axis(a: float, d: int = 16) -> list[float]:
    """(a, 0, …, 0): its §4.1 norm is exactly |a|, so the tolerance boundary is exact."""
    assert float(np.float32(a)) == a  # a is a float32 value
    return [a] + [0.0] * (d - 1)


@pytest.mark.req("SR-4.1-0", "SR-17-1")
@pytest.mark.parametrize("n", [1, 15, 17, 384])
def test_wrong_dimension_is_rejected(db16, user, n):
    """§4.1 step 0: "The input MUST have exactly `d` components. Otherwise reject with
    `WrongDimension`." §16.2: "the engine refuses another (`WrongDimension`)." """
    # The database has d = 16; n ≠ 16. A unit vector of length n is otherwise valid, so neither
    # the SDK (which takes d from the vector, §16.2) nor the engine has another reason to refuse.
    vec = [1.0] + [0.0] * (n - 1)
    with pytest.raises(sdk.WrongDimension):
        h.prepare_and_insert(db16.db, db16.cid, "doc-dim", vec, user)


@pytest.mark.req("SR-4.1-1", "SR-17-1")
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("pos", [0, 7, 15])
def test_non_finite_component_is_rejected(db16, user, bad, pos):
    """§4.1 step 1: "Every component MUST be finite. Otherwise reject with `NonFinite`." """
    vec = [0.25] * 16  # norm exactly 1 (16 × 1/16) before the bad value replaces one component
    vec[pos] = bad
    with pytest.raises(sdk.NonFinite):
        h.prepare_and_insert(db16.db, db16.cid, "doc-nf", vec, user)


@pytest.mark.req("SR-4.1-0", "SR-4.1-1")
def test_dimension_is_checked_before_finiteness(db16):
    """§4.1 lists the checks as numbered steps 0, 1, 3: the dimension comes first. A search query
    is "checked per §4.1 steps 0–3" by the engine itself (§8.1), which knows d."""
    # 15 components including a NaN: step 0 fails before step 1 is reached.
    with pytest.raises(sdk.WrongDimension):
        db16.db.search(db16.cid, [math.nan] + [0.0] * 14, k=1)


@pytest.mark.req("SR-4.1-1", "SR-4.1-3")
def test_finiteness_is_checked_before_the_norm(db16, user):
    """§4.1 step 1 (finite) precedes step 3 (norm)."""
    # An infinite component also makes the norm infinite, but step 1 decides first: NonFinite.
    with pytest.raises(sdk.NonFinite):
        h.prepare_and_insert(db16.db, db16.cid, "doc-order2", [math.inf] + [0.0] * 15, user)


@pytest.mark.req("SR-4.1-2", "SR-4.1-3")
@pytest.mark.parametrize("a", [1.0 + 8 * ULP_ABOVE_1, 1.0 - 16 * ULP_BELOW_1, 1.0,
                               1.0 + 7 * ULP_ABOVE_1, 1.0 - 15 * ULP_BELOW_1])
def test_norm_within_eight_ulps_is_accepted(db16, user, a):
    """§4.1 step 3: "|norm − 1| ≤ 8 · 2^−23 MUST hold." The bound itself is inside (≤)."""
    # norm((a,0,…)) = |a| exactly; |a − 1| is 8·2^−23 (= 16·2^−24 below 1) or less: accepted.
    assert abs(a - 1.0) <= 8 * 2.0**-23
    _, rec = h.insert(db16.db, db16.cid, "doc-edge", axis(a), user)
    assert rec.database_lsn == 0


@pytest.mark.req("SR-4.1-3", "SR-17-1")
@pytest.mark.parametrize("a", [1.0 + 9 * ULP_ABOVE_1, 1.0 - 17 * ULP_BELOW_1, 0.5, 1.5])
def test_norm_beyond_eight_ulps_is_rejected(db16, user, a):
    """§4.1 step 3: "|norm − 1| ≤ 8 · 2^−23 MUST hold. Otherwise reject with `NotNormalised`." """
    # |a − 1| = 9·2^−23, 17·2^−24 = 8.5·2^−23, 0.5, 0.5: all above 8·2^−23.
    assert abs(a - 1.0) > 8 * 2.0**-23
    with pytest.raises(sdk.NotNormalised):
        h.prepare_and_insert(db16.db, db16.cid, "doc-edge", axis(a), user)


@pytest.mark.req("SR-4.1-3")
def test_zero_vector_is_not_normalised(db16, user):
    """§4.1 step 3: the zero vector has norm 0, |0 − 1| = 1 > 8·2^−23: NotNormalised."""
    with pytest.raises(sdk.NotNormalised):
        h.prepare_and_insert(db16.db, db16.cid, "doc-zero", [0.0] * 16, user)


@pytest.mark.req("SR-4.1-2", "SR-4.1-3")
def test_norm_is_the_float64_sum_of_float32_squares(db16, user):
    """§4.1 step 2: "Compute norm = sqrt(Σ_{i=0}^{d−1} (f64)x_i²) in float64". Two vectors a few
    ULPs apart straddle the 8 · 2^−23 bound of step 3."""
    # Sixteen components 0.25 + 3·2^−24 (exact float32): norm = 4·(0.25 + 3·2^−24) = 1 + 12·2^−24
    # = 1 + 6·2^−23 in exact arithmetic; that is within 8·2^−23, so accepted.
    a = 0.25 + 3 * 2.0**-24
    assert float(np.float32(a)) == a
    ok = [a] * 16
    assert abs(sevlib.spec_norm(ok) - 1) <= 8 * 2.0**-23
    _, rec = h.insert(db16.db, db16.cid, "doc-f64", ok, user)
    assert rec.database_lsn == 0
    # 0.25 + 5·2^−24 per component: norm = 1 + 20·2^−24 = 1 + 10·2^−23 > 8·2^−23 → NotNormalised.
    b = 0.25 + 5 * 2.0**-24
    assert abs(sevlib.spec_norm([b] * 16) - 1) > 8 * 2.0**-23
    with pytest.raises(sdk.NotNormalised):
        h.prepare_and_insert(db16.db, db16.cid, "doc-f64b", [b] * 16, user)


@pytest.mark.req("SR-17-2", "SR-4.1-3")
def test_not_normalised_error_carries_no_vector_value(db16, user):
    """§17: "No error message may contain ... a vector value"."""
    vec = [0.123456789] * 16  # norm ≈ 0.494: NotNormalised
    with pytest.raises(sdk.NotNormalised) as ei:
        h.prepare_and_insert(db16.db, db16.cid, "doc-msg", vec, user)
    text = str(ei.value) + repr(ei.value.args)
    assert "0.12345" not in text and "1234567" not in text


@pytest.mark.req("SR-4.1-0")
def test_search_query_of_wrong_dimension_is_rejected(db16):
    """§8.1: the query is "checked per §4.1 steps 0–3"; step 0 fails with WrongDimension."""
    with pytest.raises(sdk.WrongDimension):
        db16.db.search(db16.cid, [1.0] + [0.0] * 16, k=3)


@pytest.mark.req("SR-4.1-3")
def test_search_query_not_normalised_is_rejected(db16):
    """§8.1: the query is "checked per §4.1 steps 0–3"; step 3 fails with NotNormalised."""
    with pytest.raises(sdk.NotNormalised):
        db16.db.search(db16.cid, [0.5] + [0.0] * 15, k=3)


@pytest.mark.req("SR-4.1-0", "SR-4.1-1", "SR-4.1-3")
def test_rejected_vectors_leave_no_log_leaf(db16, user, art16, rng):
    """§10.2: a leaf is appended on "Every insert"; a rejected insert (§4.1) is not an insert."""
    db, cid = db16.db, db16.cid
    for vec, err in [([1.0, 0.0, 0.0], sdk.WrongDimension), ([math.nan] * 16, sdk.NonFinite),
                     ([0.3] * 16, sdk.NotNormalised)]:
        with pytest.raises(err):
            h.prepare_and_insert(db, cid, "doc-x", vec, user)
    # Three rejections, zero leaves: the next insert is leaf 0.
    assert h.next_lsn(db, cid, user, art16, rng) == 0
