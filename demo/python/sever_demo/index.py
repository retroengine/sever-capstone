"""The index: k frozen groups, a locator, insert / delete / delete_user (§3.2, §5, §7).

Each record ID belongs to one dataset row. Routing labels are computed once for every row (routing
is a pure function of x̃ and the frozen centroids, §7), so insert just looks the label up.

Part 3 preview (`enable_commitments`): every record gets a blinding value r_t, every group a C_S,
and every group deletion produces a signed certificate with a proof of knowledge (§9.3-§9.5, §11).
The secrets (r_t, the operator's signing key, k_scramble) exist only in this process's memory.
"""

import hashlib
import hmac
import os
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from sever_demo import cert, posk
from sever_demo.crypto import ed25519_keypair, random_scalars
from sever_demo.errors import DuplicateRecord, Outcome
from sever_demo.group import Group, Snapshot, survivors_check, survivors_report
from sever_demo.ids import validate_record_id


class Index:
    def __init__(
        self,
        vectors: npt.NDArray[np.int32],
        ids: Sequence[str],
        labels: npt.NDArray[np.int64],
        k: int,
    ) -> None:
        if not len(ids) == len(labels) == vectors.shape[0]:
            raise ValueError("vectors, ids and labels must have the same number of rows")
        self.vectors = vectors
        self.labels = labels
        # The dataset: which row holds each record's vector (the record a client would present).
        self.row_of = {rid: row for row, rid in enumerate(ids)}
        if len(self.row_of) != len(ids):
            raise ValueError("dataset record IDs are not unique")
        self.groups = [Group(vectors) for _ in range(k)]  # §5.1: groups are never removed
        self.locator: dict[str, int] = {}  # live record ID -> group
        # Part 3 preview state (empty until enable_commitments).
        self.committed = False
        self.collection_id = b""
        self._signing_key = b""
        self._k_scramble = b""
        self.operator_public_key = b""
        self.next_lsn = 0
        self.last_certificate: bytes | None = None
        self.issued: list[bytes] = []  # every certificate issued, in lsn order (public data)

    def enable_commitments(self) -> None:
        """Blinding values, keys and every group's commitment (§3.1, §9.4, §9.7, §9.8).

        All randomness comes from the OS. Nothing secret is printed, logged or written.
        """
        blinding = random_scalars(self.vectors.shape[0])  # r_t for every record (§9.4)
        self.collection_id = os.urandom(16)  # §3.1
        self._k_scramble = os.urandom(64)  # §9.7
        self.operator_public_key, self._signing_key = ed25519_keypair()  # §9.8, epoch 0
        for g in self.groups:
            g.blinding = blinding
            g.start_commitments()
        self.committed = True

    def scrambled_id(self, rid: str) -> bytes:
        """§9.7: HMAC-SHA-512(k_scramble, collection_id ‖ record ID bytes), 64 bytes."""
        msg = self.collection_id + rid.encode("utf-8")
        return hmac.new(self._k_scramble, msg, hashlib.sha512).digest()

    def anchors(self) -> dict[str, Any]:
        """The public trust anchors a verifier needs (§11.3 inputs, preview subset)."""
        return {
            "format": "sever-demo-anchors-v1",
            "d": int(self.vectors.shape[1]),
            "operator_public_keys": {"0": self.operator_public_key.hex()},
            "note": "Part 3 preview: no log checkpoints or witness keys (no transparency log)",
        }

    def _certify(self, gid: int, rid: str) -> bytes:
        """§9.5 proof + §11.1 certificate for the deletion the group just recorded."""
        t = self.groups[gid].last_transition
        assert t is not None
        self.groups[gid].last_transition = None  # r_post and S_post are used once, then dropped
        sid = self.scrambled_id(rid)
        lsn = self.next_lsn
        self.next_lsn += 1
        ctx = posk.context(t.c_s_pre, t.c_t, sid, lsn, self.collection_id)
        facts = cert.DeletionFacts(
            c_t=t.c_t,
            c_s_pre=t.c_s_pre,
            c_s_post=t.c_s_post,
            proof=posk.prove(t.r_post, t.s_post, t.c_s_post, ctx),
            scrambled_id=sid,
            database_lsn=lsn,
            group_emptied=t.emptied,
            collection_id=self.collection_id,
        )
        return cert.issue(facts, self._signing_key)

    def insert(self, rid: str) -> int:
        validate_record_id(rid)  # §3.2 rules 1-2
        if rid in self.locator:  # §3.2 rule 3
            raise DuplicateRecord("record ID is already live")
        row = self.row_of[rid]
        gid = int(self.labels[row])  # §7.1 nearest frozen group
        self.groups[gid].insert(rid, row)
        self.locator[rid] = gid
        return gid

    def delete(self, rid: str) -> tuple[Outcome, int | None]:
        gid = self.locator.get(rid)
        if gid is None:
            return Outcome.ALREADY_ABSENT, None  # §5.4 idempotent
        outcome = self.groups[gid].delete(rid, self.row_of[rid])
        self.last_certificate = None
        if outcome is Outcome.DELETED:
            del self.locator[rid]
            if self.committed:
                self.last_certificate = self._certify(gid, rid)
                self.issued.append(self.last_certificate)
        return outcome, gid

    def delete_user(self, rids: Iterable[str]) -> list[tuple[str, Outcome, int | None]]:
        """Delete a cohort (§3.5): many records, possibly many groups. One outcome per record."""
        return [(rid, *self.delete(rid)) for rid in rids]

    def group_hashes(self, gids: Iterable[int] | None = None) -> dict[int, str]:
        chosen = range(len(self.groups)) if gids is None else gids
        return {gid: self.groups[gid].blob_hash() for gid in chosen}

    def state_hash(self) -> str:
        """SHA-256 over every group's blob hash, in group order: one value for the whole index."""
        h = hashlib.sha256()
        for blob_hash in self.group_hashes().values():
            h.update(bytes.fromhex(blob_hash))
        return h.hexdigest()

    def survivors_check(self, gid: int, rng: np.random.Generator) -> dict[str, bool]:
        return survivors_check(self.groups[gid], rng)

    def survivors_report(
        self, gid: int, rng: np.random.Generator
    ) -> tuple[Snapshot, Snapshot, dict[str, bool]]:
        return survivors_report(self.groups[gid], rng)

    def sizes(self) -> list[int]:
        return [g.n for g in self.groups]
