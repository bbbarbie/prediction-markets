"""Keccak-256, the hash Ethereum and Polygon contracts use.

Uses pycryptodome or eth-hash when one is installed and otherwise a small
pure-Python implementation (a few milliseconds per kilobyte), which is plenty
for the few thousand hashes this package computes. Note that hashlib's
``sha3_256`` is *not* Keccak-256: SHA-3 changed the padding byte.
"""
from __future__ import annotations

_M = (1 << 64) - 1
_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
# rotation offset of lane (x, y), stored at index x + 5y
_ROT = (0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39,
        41, 45, 15, 21, 8, 18, 2, 61, 56, 14)
# rho-pi: lane (x, y) moves to (y, 2x + 3y)
_DEST = tuple(y + 5 * ((2 * x + 3 * y) % 5) for y in range(5) for x in range(5))
_RATE = 136  # bytes, for a 256-bit output


def _permute(s: list[int]) -> list[int]:
    for rc in _RC:
        c = [s[x] ^ s[x + 5] ^ s[x + 10] ^ s[x + 15] ^ s[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & _M)
             for x in range(5)]
        b = [0] * 25
        for i in range(25):
            v = s[i] ^ d[i % 5]
            r = _ROT[i]
            b[_DEST[i]] = (((v << r) | (v >> (64 - r))) & _M) if r else v
        s = [b[i] ^ (~b[(i + 1) % 5 + i - i % 5] & b[(i + 2) % 5 + i - i % 5])
             for i in range(25)]
        s[0] ^= rc
    return s


def keccak256_py(data: bytes) -> bytes:
    """Pure-Python Keccak-256."""
    msg = bytearray(data)
    msg.append(0x01)
    msg.extend(b"\x00" * ((-len(msg)) % _RATE))
    msg[-1] |= 0x80
    s = [0] * 25
    for off in range(0, len(msg), _RATE):
        for i in range(_RATE // 8):
            s[i] ^= int.from_bytes(msg[off + 8 * i: off + 8 * i + 8], "little")
        s = _permute(s)
    return b"".join(s[i].to_bytes(8, "little") for i in range(4))


def _backend():
    try:
        from Crypto.Hash import keccak as _k  # pycryptodome

        def f(data: bytes) -> bytes:
            h = _k.new(digest_bits=256)
            h.update(data)
            return h.digest()
        return f
    except ImportError:
        pass
    try:
        from eth_hash.auto import keccak as _eth  # eth-hash
        _eth(b"")
        return _eth
    except Exception:
        return keccak256_py


keccak256 = _backend()


def keccak_hex(data: bytes | str) -> str:
    """0x-prefixed hex digest; str input is UTF-8 encoded."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "0x" + keccak256(data).hex()
