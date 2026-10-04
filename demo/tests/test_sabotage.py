"""Must-fail tests (Build §2.6, Overview §9.2): each deliberate bug must turn a named test red.

A sabotage is switched on in exactly one place (sever_demo.group.SABOTAGE). The named test is then
called directly; this test passes only if that test FAILS with the bug in place.
"""

from collections.abc import Callable

import pytest

import test_group
import test_group_commitments
import test_index
import test_stress
from sever_demo import group

CASES: list[tuple[str, Callable[[], None]]] = [
    ("SB-1", test_group.test_insert_then_delete_restores_empty_group),  # bit flip in S
    ("SB-1", test_group.test_survivors_check_after_random_deletes),
    ("SB-2", test_group.test_insert_then_delete_restores_state),  # n not decremented
    ("SB-2", test_group.test_survivors_check_after_random_deletes),
    ("SB-3", test_group.test_delete_absent_is_idempotent),  # no membership check
    ("SB-1", test_index.test_delete_user_multi_group),  # caught at index level too
    ("SB-2", test_index.test_delete_user_multi_group),
    ("SB-1", test_stress.test_stress_random_ops),
    ("SB-2", test_stress.test_stress_random_ops),
    ("SB-1", test_group_commitments.test_committed_random_deletes_match_survivors),
    ("SB-2", test_group_commitments.test_committed_random_deletes_match_survivors),
    ("SB-4", test_group_commitments.test_committed_random_deletes_match_survivors),  # r_agg
    ("SB-4", test_group_commitments.test_committed_insert_then_delete_restores_state),
]


@pytest.mark.mustfail
@pytest.mark.parametrize(
    ("sabotage", "named_test"), CASES, ids=[f"{sb}-{t.__name__}" for sb, t in CASES]
)
def test_sabotage_turns_named_test_red(
    monkeypatch: pytest.MonkeyPatch, sabotage: str, named_test: Callable[[], None]
) -> None:
    monkeypatch.setattr(group, "SABOTAGE", sabotage)
    with pytest.raises(AssertionError):
        named_test()


def test_sabotage_is_off_by_default() -> None:
    assert group.SABOTAGE is None
