"""``sever-demo-p3 receipt`` (Build 3-4 §1.10): the receipt, end to end, as an application backend
would run it through the SDK (spec §16.2), with the verifier and the auditor as separate processes.

    PYTHONPATH=python uv run python -m sever_demo_p3.receipt --data nq-10k --seed 42
    PYTHONPATH=python uv run python -m sever_demo_p3.receipt --data synthetic   # offline

1. The backend inserts records, one account key per account (here: one per cohort), after checking
   that the vectors come from the encoder the partition artefact names (§3.3); one insert leaf is
   shown.
2. It deletes one of an account's records; the certificate is saved as a file.
3. ``sever-verify --explain`` runs in a separate directory holding only the certificate and the
   anchors: each §11.3 step, then ACCEPT.
4. One byte of the certificate is flipped: REJECT, naming the failed step.
5. What the certificate does not prove (overview L-2, L-27; §11.3).
6. ``delete_user`` on the rest of the account's records: certificates of one group chain, and
   ``sever-audit`` confirms the log (§11.3, DB-86).

Writes ``<work>/receipt-<data>-seed<seed>.json``. Exits non-zero if any step fails.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np

from sever_db_p3 import Database, Deletion, UserKey, prepare_insert

SYNTHETIC_ARTEFACT: Final = "golden/p1_partition_small.svp"
SYNTHETIC_VECTORS: Final = "golden/p1_fixture_vectors.json"
NQ_SIZE: Final = 10_000
LIMITS: Final = [
    "that the operator kept no copy of the deleted data: no cryptography can prove that "
    "(overview L-2; spec §11.3)",
    "that the user personally authorised the deletion: the application backend holds the account "
    "key and decides who may delete (overview L-27; spec §3.3)",
    "that the deletion leaf itself was appended, that a group's certificates chain, and that the "
    "log is consistent: the auditor checks these with log access (spec §11.3)",
]


class DemoError(RuntimeError):
    """A step of the demo did not do what it must."""


def say(line: str = "") -> None:
    print(line, flush=True)


def encoder_of_data(root: Path, data: str) -> str:
    """The encoder that produced the vectors: ``repo@revision`` from the pinned data (P0)."""
    if data == "synthetic":
        return "test-encoder@0"
    meta = json.loads((root / "datasets/processed/meta.json").read_text(encoding="utf-8"))
    enc = meta["pins"]["repos"]["encoder"]
    return f"{enc['repo_id']}@{enc['revision']}"


def check_encoder(artefact_json: Path, data_encoder: str) -> str:
    """§3.3: the backend MUST embed with the encoder named in the artefact's ``encoder`` field."""
    named = str(json.loads(artefact_json.read_text(encoding="utf-8"))["encoder"])
    if named != data_encoder:
        raise DemoError(
            f"§3.3: the artefact names encoder {named!r}, the vectors come from {data_encoder!r}"
        )
    return named


def load(root: Path, data: str, seed: int) -> tuple[Path, Path, int, list[str], list[str], Any]:
    """Artefact, its JSON, spawn target, record IDs, accounts (cohorts) and the vectors."""
    if data == "synthetic":
        doc = json.loads((root / SYNTHETIC_VECTORS).read_text(encoding="utf-8"))
        rows = [bytes.fromhex(h) for h in doc["ref"] + doc["live"]]
        vecs = np.frombuffer(b"".join(rows), dtype="<f4").reshape(len(rows), 16)[:60]
        ids = [f"rec-{i:03d}" for i in range(len(vecs))]
        accounts = [f"account-{i % 7}" for i in range(len(vecs))]
        art = root / SYNTHETIC_ARTEFACT
        return art, art.with_suffix(".json"), 8, ids, accounts, vecs
    from sever_testkit.traces import load_slice

    s = load_slice(root, "nq-10k")
    vecs = np.load(root / s.vectors_path, mmap_mode="r")[:NQ_SIZE]
    art = root / f"artefacts/partition-seed{seed}.svp"
    return art, art.with_suffix(".json"), 200, s.ids, s.cohorts, vecs


def tlv_value_offsets(cert: bytes) -> dict[int, tuple[int, int]]:
    """``tag → (start, end)`` of each value, walked from §11.1."""
    out, at = {}, 0
    while at < len(cert):
        n = int.from_bytes(cert[at + 1 : at + 5], "big")
        out[cert[at]] = (at + 5, at + 5 + n)
        at += 5 + n
    return out


def run_tool(args: Sequence[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout


def build_tools(root: Path) -> tuple[Path, Path]:
    for ws in ("verifier", "audit"):
        subprocess.run(
            ["cargo", "build", "-q", "--release", "--offline"],
            cwd=root / ws,
            check=True,
            env={**os.environ, "CARGO_TARGET_DIR": str(root / ws / "target")},
        )
    return root / "verifier/target/release/sever-verify", root / "audit/target/release/sever-audit"


def demo(root: Path, data: str, seed: int, work: Path) -> dict[str, Any]:
    verify_bin, audit_bin = build_tools(root)
    base = work / f"receipt-{data}-seed{seed}"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    art, art_json, spawn, ids, accounts, vecs = load(root, data, seed)
    report: dict[str, Any] = {"data": data, "seed": seed}

    say("1. The application backend inserts records through the SDK (§16.2)")
    report["encoder"] = check_encoder(art_json, encoder_of_data(root, data))
    say(f"   encoder checked against the artefact (§3.3): {report['encoder']}")
    keys: dict[str, UserKey] = {}
    placed: dict[str, tuple[int, str]] = {}
    with Database.open(base / "data", base / "keys", d=vecs.shape[1]) as db:
        cid = db.create_collection(art, spawn_target=spawn)
        for rid, acct, v in zip(ids, accounts, vecs, strict=False):
            user = keys.setdefault(acct, UserKey.generate())
            r = db.insert(cid, prepare_insert(cid, rid, [float(x) for x in v], user))
            if r.placement is None or r.database_lsn is None:
                raise DemoError("an insert was not acknowledged with its database_lsn")
            placed[rid] = (r.database_lsn, r.placement)
        # The account: the one with most records in one group (so its certificates can chain).
        by_acct: dict[str, list[str]] = {}
        for rid, acct in zip(ids, accounts, strict=False):
            if rid in placed and not placed[rid][1].startswith("Holding"):
                by_acct.setdefault(acct, []).append(rid)

        def best_group(a: str) -> int:
            groups = [placed[r][1] for r in by_acct[a]]
            return max(groups.count(g) for g in groups)

        account = max(sorted(by_acct), key=best_group)
        mine = by_acct[account]
        report["inserted"] = len(placed)
        report["account"] = {"records": len(mine), "most_in_one_group": best_group(account)}
        first = placed[mine[0]][0]
        leaf = bytes.fromhex(json.loads(db.export_log())["leaves"][first])
        say(f"   {len(placed)} records inserted; the account has {len(mine)}")
        say(
            f"   its first record's insert leaf, index {first} (§10.2): type {leaf[0]:#04x}, "
            f"collection {leaf[1:17].hex()}, scrambled_id {leaf[17:25].hex()}…, "
            f"C_t {leaf[81:89].hex()}…, user key {leaf[113:121].hex()}…"
        )
        report["insert_leaf"] = {
            "index": first,
            "type": leaf[0],
            "user_public_key": leaf[113:145].hex(),
        }

        say("2. The backend deletes one of the account's records")
        one: Deletion = db.delete(cid, mine[0])
        if one.outcome != "deleted" or one.certificate is None:
            raise DemoError("the deletion returned no certificate")
        cert_path = base / "certificate.bin"
        cert_path.write_bytes(one.certificate)
        anchors = db.anchors()
        say(
            f"   deleted at database_lsn {one.database_lsn}; "
            f"certificate {len(one.certificate)} bytes → {cert_path.name}"
        )
        report["certificate"] = {"database_lsn": one.database_lsn, "bytes": len(one.certificate)}

        say("3. sever-verify in a separate directory, with only the certificate and the anchors")
        alone = base / "verifier-only"
        alone.mkdir()
        shutil.copy(cert_path, alone / "certificate.bin")
        (alone / "anchors.json").write_text(anchors, encoding="utf-8")
        code, out = run_tool(
            [str(verify_bin), "certificate.bin", "--anchors", "anchors.json", "--explain"], alone
        )
        say("   " + out.strip().replace("\n", "\n   "))
        if code != 0 or not out.strip().endswith("ACCEPT"):
            raise DemoError("the verifier did not accept the honest certificate")
        report["verify"] = {"accepted": True, "files": sorted(p.name for p in alone.iterdir())}

        say("4. One byte flipped (the first byte of the scrambled record ID, tag 9)")
        start = tlv_value_offsets(one.certificate)[9][0]
        bad = bytearray(one.certificate)
        bad[start] ^= 0x01
        (alone / "flipped.bin").write_bytes(bytes(bad))
        code, out = run_tool(
            [str(verify_bin), "flipped.bin", "--anchors", "anchors.json", "--explain"], alone
        )
        verdict = out.strip().splitlines()[-1]
        say("   " + verdict)
        if code != 1 or not verdict.startswith("REJECT (step "):
            raise DemoError("the verifier did not reject the changed certificate")
        report["flipped"] = {"byte": start, "verdict": verdict}

        say("5. What this certificate does not prove")
        for line in LIMITS:
            say(f"   - {line}")
        report["does_not_prove"] = LIMITS

        say("6. delete_user on the rest of the account's records (one transaction, §15.3)")
        rest = mine[1:]
        outs = db.delete_user(cid, rest)
        certs = [o.certificate for o in outs if o.certificate is not None]
        chained = 0
        posts = set()
        for c in certs:
            t = tlv_value_offsets(c)
            pre, post = c[t[2][0] : t[2][1]], c[t[3][0] : t[3][1]]
            if pre and pre in posts:
                chained += 1
            if post:
                posts.add(post)
        say(
            f"   {len(certs)} certificates; {chained} start where an earlier one in the list "
            "ended (C_S_pre = previous C_S_post)"
        )
        if report["account"]["most_in_one_group"] >= 3 and chained == 0:
            raise DemoError("no certificates chained")
        held = []
        for k, c in enumerate([one.certificate, *certs]):
            held.append(base / f"held-{k}.cert")
            held[-1].write_bytes(c)
        (base / "export.json").write_text(db.export_log(), encoding="utf-8")
        (base / "anchors.json").write_text(db.anchors(), encoding="utf-8")
    args = [str(audit_bin), "export.json", "--anchors", "anchors.json"]
    for h in held:
        args += ["--certificate", h.name]
    code, out = run_tool(args, base)
    audit = json.loads(out.strip().splitlines()[-1])
    say(
        f"   sever-audit: {audit['leaves']} leaves, {audit['checkpoints']} checkpoints, "
        f"{len(audit['findings'])} findings"
    )
    if code != 0 or audit["findings"]:
        raise DemoError(f"the auditor found problems: {audit['findings']}")
    report["delete_user"] = {"certificates": len(certs), "chained": chained, "audit": audit}
    out_path = work / f"receipt-{data}-seed{seed}.json"
    out_path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    say(f"report: {out_path}")
    return report


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sever-demo-p3", description=__doc__)
    ap.add_argument("command", choices=["receipt"])
    ap.add_argument("--data", choices=["nq-10k", "synthetic"], default="nq-10k")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--work", type=Path, default=Path("artefacts/demo"))
    a = ap.parse_args(argv)
    try:
        demo(a.root.resolve(), a.data, a.seed, a.work.resolve())
    except DemoError as e:
        print(f"DEMO FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
