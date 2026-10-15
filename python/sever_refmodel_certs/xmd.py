"""``expand_message_xmd`` with SHA-512, from RFC 9380 §5.3.1 (b_in_bytes = 64, s_in_bytes = 128)."""

import hashlib


def expand_message_xmd_sha512(msg: bytes, dst: bytes, len_in_bytes: int) -> bytes:
    ell = -(-len_in_bytes // 64)  # step 1: ceil(len_in_bytes / b_in_bytes)
    if ell > 255 or len_in_bytes > 65535 or len(dst) > 255:  # step 2
        raise ValueError("expand_message_xmd: out of range")
    dst_prime = dst + len(dst).to_bytes(1, "big")  # step 3
    z_pad = bytes(128)  # step 4
    l_i_b_str = len_in_bytes.to_bytes(2, "big")  # step 5
    msg_prime = z_pad + msg + l_i_b_str + b"\x00" + dst_prime  # step 6
    b0 = hashlib.sha512(msg_prime).digest()  # step 7
    bs = [hashlib.sha512(b0 + b"\x01" + dst_prime).digest()]  # step 8
    for i in range(2, ell + 1):  # step 9
        x = bytes(a ^ b for a, b in zip(b0, bs[-1], strict=True))
        bs.append(hashlib.sha512(x + i.to_bytes(1, "big") + dst_prime).digest())
    return b"".join(bs)[:len_in_bytes]  # steps 10-11
