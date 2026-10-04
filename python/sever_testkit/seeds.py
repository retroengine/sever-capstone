"""Run seeds and sub-seed derivation (overview §10.6).

Sub-seeds feed only data order, synthetic data and k-means. Keys, ``r_t``, nonces and
``collection_id`` never come from a seed (overview DB-17; CLAUDE.md §6.2).
"""

import hashlib
import struct
from typing import Final

#: Overview §10.6: every experiment runs all five seeds.
SEEDS: Final = (42, 123, 777, 2024, 9999)

#: Overview §10.6: the labels sub-seeds are derived for.
LABELS: Final = ("kmeans", "stream", "cohort-order", "corpus")


def sub_seed(seed: int, label: str) -> int:
    """Overview §10.6: u64 from the first 8 bytes of SHA-256(u64be(seed) ‖ label), big-endian."""
    if label not in LABELS:
        raise ValueError("unknown sub-seed label")
    digest = hashlib.sha256(struct.pack(">Q", seed) + label.encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")
