"""An application backend on SEVER-DB: the patterns a real service needs.

1. Account keys live in the backend's own key store (never in the database, never printed).
2. The backend remembers which record IDs belong to which account: the database stores only
   scrambled IDs, so "delete everything of this person" starts from the backend's own index.
3. An insert whose acknowledgement was lost is retried with the same request (``Receipt.retried``).
4. Errors are typed (§17) and carry no ID, vector or key, so they can be logged as they are.
5. "Forget me" deletes all of a person's records in one transaction and hands back a receipt
   bundle (certificates and trust anchors) that the person can check without the database.

Run it: ``demo-engine/demo.sh examples``. Offline, on the golden fixture (``d = 16``).
"""

import json
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

from sever_db import (
    Database,
    InsertRequest,
    PlatformUnsafe,
    Receipt,
    SeverError,
    UserKey,
    prepare_insert,
)

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "demo-engine/work/backend"


class KeyStore:
    """Account keys, one JSON line each, in a file only this service can read (mode 0600)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.keys: dict[str, UserKey] = {}
        if path.exists():
            for line in path.read_text("utf-8").splitlines():
                account, secret = json.loads(line)
                self.keys[account] = UserKey.from_secret_bytes(bytes.fromhex(secret))

    def key(self, account: str) -> UserKey:
        if account not in self.keys:
            key = UserKey.generate()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write(json.dumps([account, key.secret_bytes().hex()]) + "\n")
                f.flush()
                os.fsync(f.fileno())  # stored before it signs anything
            self.keys[account] = key
        return self.keys[account]


class NotesService:
    def __init__(self, db: Database, cid: str, keys: KeyStore) -> None:
        self.db, self.cid, self.keys = db, cid, keys
        self.owner: dict[str, list[str]] = {}  # account -> its record IDs (the backend's index)

    def add_note(self, account: str, note_id: str, vector: list[float], text: str) -> Receipt:
        request = prepare_insert(self.cid, note_id, vector, self.keys.key(account))
        receipt = self._insert_with_retry(request, text.encode("utf-8"))
        self.owner.setdefault(account, []).append(note_id)
        return receipt

    def _insert_with_retry(self, request: InsertRequest, passage: bytes) -> Receipt:
        try:
            return self.db.insert(self.cid, request, passage=passage)
        except TimeoutError:  # e.g. the acknowledgement was lost on its way back to us
            return self.db.insert(self.cid, request, passage=passage)  # same request: safe

    def search(self, vector: list[float], k: int = 5) -> list[tuple[str, float]]:
        return self.db.search(self.cid, vector, k)

    def forget(self, account: str, bundle: Path) -> int:
        """Deletes every record of the account (all or nothing, §12.5); writes the receipts."""
        ids = self.owner.pop(account, [])
        deletions = self.db.delete_user(self.cid, ids)
        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("anchors.json", self.db.anchors())
            for d in deletions:
                if d.certificate is not None:
                    z.writestr(f"{d.database_lsn}.cert", d.certificate)
        return sum(d.outcome == "deleted" for d in deletions)


def main() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    doc = json.loads((ROOT / "golden/p1_fixture_vectors.json").read_text("utf-8"))
    vecs = [list(struct.unpack("<16f", bytes.fromhex(h))) for h in doc["ref"][:9]]
    try:
        db = Database.open(WORK / "data", WORK / "keys", d=16)
    except PlatformUnsafe:
        db = Database.open(WORK / "data", WORK / "keys", d=16, allow_unsafe_memory=True)
    print("startup overrides:", db.startup[0] or "none")
    with db:
        cid = db.create_collection(ROOT / "golden/p1_partition_small.svp", spawn_target=8)
        svc = NotesService(db, cid, KeyStore(WORK / "accounts.keys"))
        for i, v in enumerate(vecs):
            svc.add_note(["alice", "bob", "carol"][i % 3], f"note-{i}", v, f"note {i}")
        print("bob's note-1 is found:", svc.search(vecs[1], 1))

        try:
            svc.add_note("bob", "note-1", vecs[0], "again")
        except SeverError as e:  # typed, and safe to log: no ID, vector or key inside (§17)
            print("refused:", type(e).__name__)

        bundle = WORK / "bob-receipts.zip"
        print("forgot bob:", svc.forget("bob", bundle), "records; receipts in", bundle.name)
        print("bob's note-1 now:", [h for h in svc.search(vecs[1], 3) if h[0] == "note-1"])

    # Bob, later, on his own machine: unzip and check every receipt, with no database access.
    mine = WORK / "bob"
    zipfile.ZipFile(bundle).extractall(mine)
    verifier = ROOT / "verifier/target/release/sever-verify"
    for cert in sorted(mine.glob("*.cert")):
        args = [str(verifier), cert.name, "--anchors", "anchors.json"]
        ok = subprocess.run(args, cwd=mine, capture_output=True, check=False).returncode == 0
        print(f"  {cert.name}: {'accepted' if ok else 'REJECTED'}")


if __name__ == "__main__":
    main()
