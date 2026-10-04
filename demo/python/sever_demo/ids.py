import re

from sever_demo.errors import InvalidRecordId

MAX_ID_BYTES = 256  # §3.2 rule 1

# §3.2 rule 2: a bare decimal integer, with or without sign or leading zeros.
# [0-9], not \d: \d also matches other scripts' digits (for example Arabic-Indic), which the spec's
# pattern does not. Used with fullmatch, never match or search (CLAUDE.md §7).
_BARE_INTEGER = re.compile(r"[+-]?[0-9]+")


def validate_record_id(rid: str) -> None:
    """§3.2 rules 1 and 2. Rule 3 (not already live) is the index's job.

    Raises InvalidRecordId. The message never contains the ID (§17).
    """
    # §3.2 rule 1: 1 to 256 UTF-8 *bytes*, not characters. A lone surrogate has no UTF-8 form.
    try:
        size = len(rid.encode("utf-8"))
    except UnicodeEncodeError:
        raise InvalidRecordId("record ID is not valid UTF-8") from None
    if not 1 <= size <= MAX_ID_BYTES:
        raise InvalidRecordId(f"record ID must be 1 to {MAX_ID_BYTES} UTF-8 bytes")

    # §3.2 rule 2. fullmatch, so "12\n" is not a bare integer ("$" would match before the "\n").
    if _BARE_INTEGER.fullmatch(rid):
        raise InvalidRecordId("record ID must not be a bare decimal integer")
