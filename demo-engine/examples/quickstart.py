"""Quick start: open a database, store records, search, delete one, and check its receipt.

Run it: ``demo-engine/demo.sh examples`` (or ``PYTHONPATH=python uv run --no-sync python
demo-engine/examples/quickstart.py``). It runs offline on the golden fixture (``d = 16``); for real
use, open with ``d=384`` and create the collection over ``artefacts/partition-seed42.svp``, with
vectors from the encoder that artefact names (all-MiniLM-L6-v2, §3.3).
"""

import json
import shutil
import struct
import subprocess
from pathlib import Path

from sever_db import Database, PlatformUnsafe, UserKey, prepare_insert

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "demo-engine/work/quickstart"  # on ext4: the database refuses tmpfs (§12.9)

# Six unit-length vectors (the fixture's; any float32 vectors of length 1 will do).
doc = json.loads((ROOT / "golden/p1_fixture_vectors.json").read_text("utf-8"))
vectors = [list(struct.unpack("<16f", bytes.fromhex(h))) for h in doc["ref"][:6]]

shutil.rmtree(WORK, ignore_errors=True)
user = UserKey.generate()  # one per account; keep user.secret_bytes() in your own key store

try:
    db = Database.open(WORK / "data", WORK / "keys", d=16)
except PlatformUnsafe as refused:
    # A development machine (plain swap, no mlock): open with the recorded override instead.
    print(f"refused ({refused}); opening with the development override")
    db = Database.open(WORK / "data", WORK / "keys", d=16, allow_unsafe_memory=True)

with db:
    cid = db.create_collection(ROOT / "golden/p1_partition_small.svp", spawn_target=8)
    for i, v in enumerate(vectors):
        db.insert(cid, prepare_insert(cid, f"note-{i}", v, user), passage=f"note {i}".encode())

    print("search:", db.search(cid, vectors[2], k=3))  # [(record_id, distance), ...]

    deletion = db.delete(cid, "note-2")
    print("deleted:", deletion.outcome, "at log position", deletion.database_lsn)
    print("search again:", db.search(cid, vectors[2], k=3))
    print("delete again:", db.delete(cid, "note-2").outcome)  # "absent": retrying is safe

    # The receipt: the certificate and the public trust anchors, checked with no database access.
    assert deletion.certificate is not None
    (WORK / "note-2.cert").write_bytes(deletion.certificate)
    (WORK / "anchors.json").write_text(db.anchors(), "utf-8")

verifier = ROOT / "verifier/target/release/sever-verify"
if verifier.exists():
    check = [str(verifier), "note-2.cert", "--anchors", "anchors.json"]
    print("sever-verify:", subprocess.run(check, cwd=WORK, capture_output=True, text=True).stdout)
else:
    print("build the verifier to check the receipt: cd verifier && cargo build --release")
