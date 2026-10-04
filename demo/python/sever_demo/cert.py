"""Deletion certificates (spec §11.1), Part 3 preview.

A certificate is the TLV sequence of tags 1-13 followed by the operator's Ed25519 signature over
DST_CERT ‖ all preceding bytes. Preview simplifications, stated:
- tags 5-7 (user insert signature, log inclusion, witness cosignatures) are empty: the transparency
  log (§10) is not built, so the verifier reports §11.3 steps 3-5 as NOT CHECKED;
- tag 8 (key epoch) is 0: one operator key per demo session;
- tag 10 (database_lsn) is this session's deletion counter, not a log leaf index.
"""

import struct
from dataclasses import dataclass

from sever_demo.crypto import ed25519_sign

DST_CERT = b"SEVERDB-CERT-V1"  # §2.3


@dataclass(frozen=True)
class DeletionFacts:
    """The public values one group deletion produces."""

    c_t: bytes
    c_s_pre: bytes
    c_s_post: bytes
    proof: bytes
    scrambled_id: bytes
    database_lsn: int
    group_emptied: bool
    collection_id: bytes


def tlv(tag: int, value: bytes) -> bytes:
    """§11.1: u8 tag ‖ u32be length ‖ value."""
    return struct.pack(">BI", tag, len(value)) + value


def body(f: DeletionFacts, epoch: int = 0) -> bytes:
    values = {
        1: f.c_t,
        2: f.c_s_pre,
        3: f.c_s_post,
        4: f.proof,
        5: b"",  # preview: no user insert signature (needs the log)
        6: b"",  # preview: no insert inclusion proof
        7: b"",  # preview: no witness cosignatures
        8: struct.pack(">I", epoch),
        9: f.scrambled_id,
        10: struct.pack(">Q", f.database_lsn),
        11: bytes([1 if f.group_emptied else 0]),
        12: bytes([0]),  # deletion_kind 0: from a group (no holding area in the demo)
        13: f.collection_id,
    }
    return b"".join(tlv(tag, values[tag]) for tag in range(1, 14))  # ascending, each once


def issue(f: DeletionFacts, operator_secret_key: bytes, epoch: int = 0) -> bytes:
    """The signed certificate: body ‖ 0xFF ‖ u32be 64 ‖ Ed25519(DST_CERT ‖ body)."""
    b = body(f, epoch)
    return b + tlv(0xFF, ed25519_sign(operator_secret_key, DST_CERT + b))
