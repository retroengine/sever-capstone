"""Lists kind-1 bucket-block records (domain, version) found in files: metadata only (§13.2)."""

import struct
import sys
from collections import defaultdict
from pathlib import Path

db = Path(sys.argv[1])
keys = (db / "keys/KEYS").read_bytes()
cid = keys[4096 + 52 : 4096 + 68]
for sub in ("data/wrapped", "data/wal"):
    for f in sorted((db / sub).iterdir()):
        b = f.read_bytes()
        best = defaultdict(list)
        i = b.find(cid)
        while i >= 0:
            if i > 0 and b[i - 1] == 1 and i + 56 <= len(b):
                g = b[i + 16 : i + 48].rstrip(b"\0").decode("ascii", "replace")
                v = struct.unpack(">Q", b[i + 48 : i + 56])[0]
                if v < 10**6:
                    best[g].append(v)
            i = b.find(cid, i + 1)
        print(f"{sub}/{f.name} ({len(b)} B):")
        for g, vs in sorted(best.items()):
            print(f"   {g:<24} versions seen {vs[:3]}…{vs[-5:]}  max {max(vs)}  count {len(vs)}")
