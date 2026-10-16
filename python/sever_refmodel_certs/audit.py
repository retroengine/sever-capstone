"""The auditor's checks (spec §11.3 "what it does not prove"; C-17; DB-86), modelled from the spec
text, and the fault-injection suite AF-1 … AF-5 (Build 3-4 §1.8). The Rust auditor (``audit/``) is
checked against ``golden/p3_audit.json``, which this module writes.

A log export (DB-86) is ``{"version": 1, "leaves": [hex], "placements": [{"group", "flush"}],
"checkpoints": [hex]}``: every leaf (the 209-byte insert leaf, or ``0x02 ‖ certificate``, §10.2),
the group each leaf's record joined or left (and the spawned group a flush created), and every log
checkpoint as ``checkpoint (116) ‖ u8 count ‖ count × cosignature (69)``.

The audit, given the export, the anchors and any certificates users hold:

* every delete leaf's certificate verifies (§11.3) and names its own leaf index as
  ``database_lsn``; a checkpoint larger than the log means leaves are missing (AF-1);
* a group's commitment is the sum of its members' ``C_t`` (§5.3, §9.3: commitments add), so
  replaying the placements gives every group's ``C_S`` before each deletion: a group certificate's
  ``C_S_pre`` must equal it, and the record must be a member (AF-2; this subsumes "consecutive
  certificates chain", §11.3);
* consecutive checkpoints are consistent (RFC 9162 §2.1.4, proofs computed from the leaves), and two
  checkpoints of one size have one root (AF-3);
* the leaf at a held certificate's ``database_lsn`` is ``0x02 ‖`` that certificate (AF-4);
* every checkpoint's root is the root of the leaves at its size, and it is signed and witnessed
  (AF-5).
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Final

from sever_refmodel_certs import cert, ed25519, merkle, posk, spec
from sever_refmodel_certs.ristretto import IDENTITY, L, decode, encode

D: Final = 16
GENESIS_MS: Final = 1_790_000_000_000
COSIG_LEN: Final = cert.COSIGNATURE_LEN


@dataclass(frozen=True)
class Finding:
    """One problem: its kind (``AF-1`` … ``AF-5``, or ``leaf``, ``certificate``, ``checkpoint``),
    the leaf or checkpoint index it concerns, and why."""

    kind: str
    at: int
    why: str


def _anchors(a: dict[str, Any]) -> cert.Anchors:
    return cert.Anchors(
        {int(e): bytes.fromhex(k) for e, k in a["operator"].items()},
        {
            (i, int(e)): bytes.fromhex(k)
            for i, ring in enumerate(a["witnesses"])
            for e, k in ring.items()
        },
        a["d"],
    )


def _witnessed(b: bytes) -> tuple[cert.Checkpoint, list[cert.Cosig]]:
    cp = cert.Checkpoint.parse(b[: cert.CHECKPOINT_LEN])
    rest = b[cert.CHECKPOINT_LEN :]
    if not rest or len(rest) != 1 + COSIG_LEN * rest[0]:
        raise ValueError("cosignature count")
    cos = [
        cert.Cosig(
            rest[1 + COSIG_LEN * i],
            int.from_bytes(rest[2 + COSIG_LEN * i : 6 + COSIG_LEN * i], "big"),
            rest[6 + COSIG_LEN * i : 70 + COSIG_LEN * i],
        )
        for i in range(rest[0])
    ]
    return cp, cos


def audit(
    export: dict[str, Any], anchors: dict[str, Any], held: list[bytes] | None = None
) -> list[Finding]:
    """The findings of an audit; empty for an honest log."""
    a = _anchors(anchors)
    out: list[Finding] = []
    leaves = [bytes.fromhex(h) for h in export["leaves"]]
    placements = export["placements"]
    if len(placements) != len(leaves):
        out.append(Finding("leaf", len(leaves), "placements and leaves differ in number"))
    # Group membership, by (collection, group): scrambled_id → C_t (the latest insert leaf).
    members: dict[tuple[bytes, str], dict[bytes, bytes]] = {}
    for i, leaf in enumerate(leaves):
        pl = placements[i] if i < len(placements) else {"group": "", "flush": None}
        where = str(pl["group"])
        if leaf[:1] == b"\x01" and len(leaf) == cert.INSERT_LEAF_LEN:
            coll, sid, c_t = leaf[1:17], leaf[17:81], leaf[81:113]
            if pl["flush"] is not None:
                held_now = members.pop((coll, "holding"), {})
                held_now[sid] = c_t
                members.setdefault((coll, pl["flush"]), {}).update(held_now)
                if pl["group"] != pl["flush"]:
                    out.append(Finding("AF-2", i, "a flushed record is not in the new group"))
            else:
                members.setdefault((coll, where), {})[sid] = c_t
            continue
        if leaf[:1] != b"\x02":
            out.append(Finding("leaf", i, "neither an insert leaf nor a delete leaf"))
            continue
        crt = leaf[1:]
        try:
            cert.verify(crt, a)
        except (cert.VerifyError, ValueError) as e:
            out.append(Finding("certificate", i, f"does not verify: {e}"))
            continue
        p = cert.parse(crt, a.d)
        if p.u(10) != i:
            out.append(
                Finding(
                    "AF-1",
                    i,
                    f"its certificate names leaf {p.u(10)}: a leaf is missing or out of place",
                )
            )
        coll, sid, c_t = p.values[13], p.values[9], p.values[1]
        group = members.get((coll, where), {})
        if group.get(sid) != c_t:
            out.append(Finding("AF-2", i, "the record is not a member of the group it left"))
        elif p.u(12) == 0:
            total = IDENTITY
            for m in group.values():
                total = total + decode(m)
            if pl["group"] == "holding" or encode(total) != p.values[2]:
                out.append(Finding("AF-2", i, "C_S_pre is not the group's commitment"))
        elif pl["group"] != "holding":
            out.append(Finding("AF-2", i, "a holding-area certificate for a group record"))
        group.pop(sid, None)
    # Checkpoints: roots, signatures, witnesses, consistency.
    hashes = leaves
    seen: dict[int, bytes] = {}
    prev: cert.Checkpoint | None = None
    for j, h in enumerate(export["checkpoints"]):
        try:
            cp, cos = _witnessed(bytes.fromhex(h))
        except (cert.VerifyError, ValueError):
            out.append(Finding("checkpoint", j, "malformed"))
            continue
        key = a.operators.get(cp.epoch)
        if key is None or not ed25519.verify(key, cp.message(), cp.signature):
            out.append(Finding("checkpoint", j, "operator signature"))
        if j > 0:  # the genesis checkpoint is not cosigned (DB-79)
            msg = cert.cosign_message(cp.message())
            good = {
                c.index
                for c in cos
                if (k := a.witnesses.get((c.index, c.epoch))) is not None
                and ed25519.verify(k, msg, c.signature)
            }
            if len(good) < cert.THRESHOLD:
                out.append(Finding("checkpoint", j, "fewer than four witnesses"))
        if cp.tree_size > len(hashes):
            out.append(Finding("AF-1", j, "a checkpoint covers leaves the export lacks"))
        elif merkle.mth(hashes[: cp.tree_size]) != cp.root:
            out.append(Finding("AF-5", j, "the root is not the tree's at its size"))
        if seen.get(cp.tree_size, cp.root) != cp.root:
            out.append(Finding("AF-3", j, "two roots for one size"))
        seen[cp.tree_size] = cp.root
        if prev is not None and 0 < prev.tree_size < cp.tree_size <= len(hashes):
            proof = merkle.proof(prev.tree_size, hashes[: cp.tree_size])
            if not merkle.verify_consistency(
                prev.tree_size, cp.tree_size, prev.root, cp.root, proof
            ):
                out.append(Finding("AF-3", j, "not consistent with the previous checkpoint"))
        prev = cp
    # Certificates users hold: the leaf at their database_lsn must be theirs.
    for crt in held or []:
        lsn = cert.parse(crt, a.d).u(10)
        if lsn >= len(leaves) or leaves[lsn] != b"\x02" + crt:
            out.append(Finding("AF-4", lsn, "the leaf at database_lsn is not this certificate"))
    return out


# ---------------------------------------------------------------------------------------------
# A scripted log and its faults
# ---------------------------------------------------------------------------------------------


def _secret(label: str) -> bytes:
    return cert.secret(f"SEVER-DB p3 audit {label}")


def _blind(label: str) -> int:
    return (
        int.from_bytes(hashlib.sha512(f"SEVER-DB p3 audit {label}".encode()).digest(), "little") % L
    )


@dataclass
class Log:
    """A model log: what the engine would write, from fixed test keys (never a database's)."""

    d: int = D
    coll: bytes = hashlib.sha512(b"SEVER-DB p3 audit collection").digest()[:16]
    leaves: list[bytes] = field(default_factory=list)
    placements: list[dict[str, str | None]] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    certs: list[bytes] = field(default_factory=list)
    #: name → (x, r_t, C_t, scrambled_id, leaf index, group)
    records: dict[str, tuple[list[int], int, bytes, bytes, int, str]] = field(default_factory=dict)
    witnessed: list[tuple[cert.Checkpoint, list[cert.Cosig]]] = field(default_factory=list)
    #: database_lsn of a group deletion → the opening of C_S_post (S_post, r_post)
    openings: dict[int, tuple[list[int], int]] = field(default_factory=dict)
    clock: int = GENESIS_MS

    def anchors(self) -> dict[str, Any]:
        return {
            "d": self.d,
            "operator": {"0": ed25519.public_key(_secret("operator 0")).hex()},
            "witnesses": [
                {"0": ed25519.public_key(_secret(f"witness {i}")).hex()} for i in range(5)
            ],
        }

    def sign_checkpoint(self, size: int, root: bytes) -> tuple[cert.Checkpoint, list[cert.Cosig]]:
        self.clock += 1000
        msg = cert.checkpoint_message(size, root, self.clock, 0)
        cp = cert.Checkpoint(size, root, self.clock, 0, ed25519.sign(_secret("operator 0"), msg))
        cos = [
            cert.Cosig(i, 0, ed25519.sign(_secret(f"witness {i}"), cert.cosign_message(msg)))
            for i in range(5)
        ]
        return cp, cos

    def checkpoint(self) -> None:
        cp, cos = self.sign_checkpoint(len(self.leaves), merkle.mth(self.leaves))
        self.checkpoints.append(_entry(cp, cos))
        self.witnessed.append((cp, cos))

    def insert(self, name: str, group: str, flush: str | None = None) -> None:
        k = len(self.records) + 1
        x = [((k * 7919 * (i + 3)) % 2**21) - 2**20 for i in range(self.d)]
        r = _blind(f"r_t {name}")
        c_t = encode(spec.commit(x, r))
        sid = hashlib.sha512(f"SEVER-DB p3 audit scrambled_id {name}".encode()).digest()
        usk = _secret("user")
        usig = ed25519.sign(usk, cert.insert_message(self.coll, c_t))
        leaf = cert.insert_leaf(self.coll, sid, c_t, ed25519.public_key(usk), usig)
        if flush is not None:
            for n, rec in self.records.items():
                if rec[5] == "holding":
                    self.records[n] = (*rec[:5], flush)
            group = flush
        self.records[name] = (x, r, c_t, sid, len(self.leaves), group)
        self.leaves.append(leaf)
        self.placements.append({"group": group, "flush": flush})

    def delete(self, name: str) -> bytes:
        _, _, c_t, sid, li, group = self.records.pop(name)
        cp, cos = next(w for w in reversed(self.witnessed) if w[0].tree_size > li)
        inc = cert.Inclusion(self.leaves[li], li, cp, merkle.path(li, self.leaves[: cp.tree_size]))
        lsn = len(self.leaves)
        values = {
            1: c_t,
            5: self.leaves[li][145:209],
            6: inc.to_bytes(),
            7: cert.cosignatures_value(cos),
            8: (0).to_bytes(4, "big"),
            9: sid,
            10: lsn.to_bytes(8, "big"),
            13: self.coll,
        }
        if group == "holding":
            values |= {2: b"", 3: b"", 4: b"", 11: b"\x00", 12: b"\x01"}
        else:
            rest = [rec for rec in self.records.values() if rec[5] == group]
            s_post = (
                [sum(t) for t in zip(*(rec[0] for rec in rest), strict=True)]
                if rest
                else [0] * self.d
            )
            r_post = sum(rec[1] for rec in rest) % L
            post = spec.commit(s_post, r_post)
            pre = encode(post + decode(c_t))
            ctx = posk.ctx_bytes(pre, c_t, sid, lsn, self.coll)
            nonces = [_blind(f"k {lsn} {i}") for i in range(self.d)]
            proof = posk.prove(s_post, r_post, ctx, _blind(f"k_r {lsn}"), nonces)
            emptied = b"\x01" if post.equals(IDENTITY) else b"\x00"
            self.openings[lsn] = (s_post, r_post)
            values |= {2: pre, 3: encode(post), 4: proof, 11: emptied, 12: b"\x00"}
        crt = cert.sign_certificate(values, _secret("operator 0"))
        self.leaves.append(b"\x02" + crt)
        self.placements.append({"group": group, "flush": None})
        self.certs.append(crt)
        return crt

    def export(self) -> dict[str, Any]:
        return {
            "version": 1,
            "leaves": [x.hex() for x in self.leaves],
            "placements": [dict(p) for p in self.placements],
            "checkpoints": list(self.checkpoints),
        }


def honest() -> Log:
    """Groups frozen-0000 (a, b, c) and frozen-0001 (d, e); the holding area fills (f, g, h) and h
    flushes it into spawn-00000000000000aa; i waits in the holding area. A checkpoint, then a
    delete_user of b, a, d (b and a chain), a deletion from the spawned group (f), from the holding
    area (i), an insert, another deletion (c) and a final checkpoint."""
    log = Log()
    log.checkpoints.append(_genesis(log))
    for n, g in [
        ("a", "frozen-0000"),
        ("b", "frozen-0000"),
        ("c", "frozen-0000"),
        ("d", "frozen-0001"),
        ("e", "frozen-0001"),
        ("f", "holding"),
        ("g", "holding"),
    ]:
        log.insert(n, g)
    log.insert("h", "holding", flush="spawn-00000000000000aa")
    log.insert("i", "holding")
    log.checkpoint()
    for n in ("b", "a", "d", "f", "i"):
        log.delete(n)
    log.insert("j", "frozen-0001")
    log.checkpoint()
    log.delete("c")
    log.checkpoint()
    return log


def _genesis(log: Log) -> str:
    msg = cert.checkpoint_message(0, hashlib.sha256(b"").digest(), log.clock, 0)
    cp = cert.Checkpoint(
        0, hashlib.sha256(b"").digest(), log.clock, 0, ed25519.sign(_secret("operator 0"), msg)
    )
    return (cp.to_bytes() + b"\x00").hex()


def _rebuild(
    log: Log, leaves: list[bytes], placements: list[dict[str, str | None]]
) -> dict[str, Any]:
    """A dishonest operator's export: the given leaves, with every checkpoint re-signed and
    re-cosigned over them at its own size (so roots and witnesses are not what gives it away)."""
    cps = [log.checkpoints[0]]
    for cp, _ in log.witnessed:
        size = min(cp.tree_size, len(leaves))
        new, cos = log.sign_checkpoint(size, merkle.mth(leaves[:size]))
        cps.append(_entry(new, cos))
    return {
        "version": 1,
        "leaves": [x.hex() for x in leaves],
        "placements": placements,
        "checkpoints": cps,
    }


def _entry(cp: cert.Checkpoint, cos: list[cert.Cosig]) -> str:
    return (cp.to_bytes() + bytes([len(cos)]) + b"".join(c.to_bytes() for c in cos)).hex()


def faults() -> dict[str, tuple[dict[str, Any], list[bytes]]]:
    """Each fault of the register (AF-1 … AF-5): an export and the certificates users hold. The
    operator is dishonest and holds every key, so each faulty export is otherwise well signed."""
    log = honest()
    e = log.export()
    leaves, pl = list(log.leaves), [dict(p) for p in log.placements]
    first = next(i for i, x in enumerate(leaves) if x[:1] == b"\x02")  # b, then a, then d
    op = _secret("operator 0")
    out: dict[str, tuple[dict[str, Any], list[bytes]]] = {}
    # AF-1: the first deletion's leaf was never appended (later leaves move down by one).
    out["AF-1"] = (
        _rebuild(log, leaves[:first] + leaves[first + 1 :], pl[:first] + pl[first + 1 :]),
        [],
    )
    # AF-2: a's certificate (after b's, same group) re-issued with C_S_pre and C_S_post both moved
    # by t·H, with a valid proof of the moved state: it verifies, but does not follow from b's.
    i_a = first + 1
    p = cert.parse(leaves[i_a][1:], D)
    s_post, r_post = log.openings[p.u(10)]
    t = _blind("AF-2 shift")
    shift = spec.commit([0] * D, t)
    pre2, post2 = encode(decode(p.values[2]) + shift), encode(decode(p.values[3]) + shift)
    ctx = posk.ctx_bytes(pre2, p.values[1], p.values[9], p.u(10), p.values[13])
    nonces = [_blind(f"AF-2 k {i}") for i in range(D)]
    proof = posk.prove(s_post, (r_post + t) % L, ctx, _blind("AF-2 k_r"), nonces)
    forged = cert.sign_certificate(p.values | {2: pre2, 3: post2, 4: proof}, op)
    cert.verify(forged, _anchors(log.anchors()))
    out["AF-2"] = (_rebuild(log, [*leaves[:i_a], b"\x02" + forged, *leaves[i_a + 1 :]], pl), [])
    # AF-3: a second checkpoint at the first one's size over another history (a forked log).
    cp0, _ = log.witnessed[0]
    other = list(leaves[: cp0.tree_size])
    other[0] = other[1]
    fork, cos = log.sign_checkpoint(cp0.tree_size, merkle.mth(other))
    out["AF-3"] = (
        {**e, "checkpoints": [*e["checkpoints"][:2], _entry(fork, cos), *e["checkpoints"][2:]]},
        [],
    )
    # AF-4: the user holds d's certificate; the log holds another valid one for that deletion
    # (four of the five cosignatures), so the leaf at its database_lsn is not the user's.
    i_d = first + 2
    held = leaves[i_d][1:]
    p = cert.parse(held, D)
    swapped = cert.sign_certificate(p.values | {7: cert.cosignatures_value(p.cosigs[:4])}, op)
    cert.verify(swapped, _anchors(log.anchors()))
    out["AF-4"] = (
        _rebuild(log, [*leaves[:i_d], b"\x02" + swapped, *leaves[i_d + 1 :]], pl),
        [held],
    )
    # AF-5: the last checkpoint signs (and the witnesses cosign) a root the tree does not have.
    bad, cos = log.sign_checkpoint(len(leaves), hashlib.sha256(b"not the root").digest())
    out["AF-5"] = ({**e, "checkpoints": [*e["checkpoints"][:-1], _entry(bad, cos)]}, [])
    return out


def audit_vector() -> dict[str, Any]:
    """``golden/p3_audit.json``: the anchors, the honest export (no findings), the certificates
    issued, and each fault's export, held certificates and the kinds this model reports."""
    log = honest()
    anchors = log.anchors()
    e = log.export()
    assert audit(e, anchors, log.certs) == [], audit(e, anchors, log.certs)
    rows = []
    for fid, (fe, held) in faults().items():
        found = audit(fe, anchors, held)
        kinds = sorted({f.kind for f in found})
        assert fid in kinds, (fid, found)
        rows.append(
            {"id": fid, "export": fe, "held": [h.hex() for h in held], "model_kinds": kinds}
        )
    return {
        "source": "sever_refmodel_certs.audit (spec §11.3 'what it does not prove'; DB-86; "
        "register spec/registers_p3.yaml)",
        "d": D,
        "anchors": anchors,
        "honest": e,
        "certificates": [c.hex() for c in log.certs],
        "faults": rows,
    }
