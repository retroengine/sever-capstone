import pytest

from sever_demo.errors import InvalidRecordId
from sever_demo.ids import validate_record_id

# T4 (spec §3.2 rules 1 and 2). Limits written out here, not imported from ids.py.
EURO = "€"  # "€", 3 bytes in UTF-8


@pytest.mark.parametrize(
    "rid",
    [
        "doc0",
        "nq-1234",
        "123e4567-e89b-12d3-a456-426614174000",  # a UUID
        "a" * 256,  # exactly 256 bytes: the upper limit is allowed
        EURO * 85,  # 255 bytes
        "12\n",  # not a *bare* integer (fullmatch, not "^...$")
        "١٢",  # Arabic-Indic digits: the spec pattern is [0-9], not \d
        "1.5",
        "0x1F",
    ],
)
def test_ids_valid(rid: str) -> None:
    validate_record_id(rid)


@pytest.mark.parametrize(
    "rid",
    [
        "1",
        "007",
        "-3",
        "+3",
        "",  # 0 bytes
        "a" * 257,  # 257 bytes
        EURO * 100,  # 100 characters but 300 bytes: the limit counts bytes
        "\ud800",  # lone surrogate: no UTF-8 encoding
    ],
)
def test_ids_invalid(rid: str) -> None:
    with pytest.raises(InvalidRecordId):
        validate_record_id(rid)


def test_ids_error_never_contains_the_id() -> None:
    # §17: an error message must not leak the record ID.
    secret = "4815162342"
    with pytest.raises(InvalidRecordId) as caught:
        validate_record_id(secret)
    assert secret not in str(caught.value)
