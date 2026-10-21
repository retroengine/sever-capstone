"""Prints KEYS slot metadata (§14.7) without any key byte: pair, slot, state, version, group."""

import struct
import sys

T = []
for i in range(256):
    c = i
    for _ in range(8):
        c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
    T.append(c)


def crc32c(b):
    c = 0xFFFFFFFF
    for x in b:
        c = T[(c ^ x) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


with open(sys.argv[1], "rb") as fh:
    b = fh.read()
print("header ok:", b[:8] == b"SVDBKEYS", "pairs:", (len(b) - 4096) / 1024)
for pair in range((len(b) - 4096) // 1024):
    for slot in (0, 1):
        s = b[4096 + 1024 * pair + 512 * slot : 4096 + 1024 * pair + 512 * (slot + 1)]
        if not any(s):
            print(f"pair {pair} slot {slot}: erased")
            continue
        ok = (
            s[:4] == b"SVKS"
            and struct.unpack(">I", s[-4:])[0] == crc32c(s[:-4])
            and not any(s[100:-4])
        )
        di, ver = struct.unpack(">QQ", s[4:20])
        gid = s[68:100].rstrip(b"\0").decode("ascii", "replace")
        state = "valid" if ok else "TORN"
        print(f"pair {pair} slot {slot}: {state} domain_index={di} version={ver} group={gid}")
