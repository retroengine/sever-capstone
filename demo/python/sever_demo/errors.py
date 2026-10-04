# ruff: noqa: N818 - the names are the spec's (§17); an "Error" suffix would hide them
"""Typed errors (§17) and the delete outcome (§5.4).

§17: no message may contain a record ID, a vector value, a key, r_t or passage text. Group sizes may
appear. Each error subclasses ValueError so callers that only know "bad input" still catch it.
"""

from enum import Enum


class InvalidRecordId(ValueError):
    """§3.2 rules 1-2 fail."""


class DuplicateRecord(ValueError):
    """§3.2 rule 3 fails: the ID is already live."""


class NotNormalised(ValueError):
    """§4.1 fails."""


class GroupCapacityExceeded(ValueError):
    """§5.6 hard cap: an insert would make n > 1,000,000."""


class IntegrityViolation(ValueError):
    """An invariant failed (§21); state can no longer be trusted."""


class Outcome(Enum):
    """Result of a delete. AlreadyAbsent is not an error (§5.4, idempotent deletion)."""

    DELETED = "Deleted"
    ALREADY_ABSENT = "AlreadyAbsent"
