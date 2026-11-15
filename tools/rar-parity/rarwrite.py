"""Minimal writer for stored (method 0) RAR4 and RAR5 archives.

Used to wrap other archives for nesting fixtures and to generate the large
bomb archives at test time; it needs no RARLAB tool.
"""
import struct
import zlib

RAR4_MARKER = b"Rar!\x1a\x07\x00"
RAR5_MARKER = b"Rar!\x1a\x07\x01\x00"


def _vint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _rar5_block(htype: int, hflags: int, data_size: int | None, body: bytes) -> bytes:
    inner = _vint(htype) + _vint(hflags | (0x02 if data_size is not None else 0))
    if data_size is not None:
        inner += _vint(data_size)
    inner += body
    sized = _vint(len(inner)) + inner
    return struct.pack("<I", zlib.crc32(sized) & 0xFFFFFFFF) + sized


def rar5_header(name: str, size: int, crc: int) -> bytes:
    nm = name.encode()
    body = _vint(0x04) + _vint(size) + _vint(0x20) + struct.pack("<I", crc) + _vint(0) + _vint(1) + _vint(len(nm)) + nm
    return _rar5_block(2, 0, size, body)


def rar5_archive(entries: list[tuple[str, bytes]]) -> bytes:
    out = bytearray(RAR5_MARKER)
    out += _rar5_block(1, 0, None, _vint(0))
    for name, data in entries:
        out += rar5_header(name, len(data), zlib.crc32(data) & 0xFFFFFFFF)
        out += data
    out += _rar5_block(5, 0, None, _vint(0))
    return bytes(out)


def _crc16(b: bytes) -> int:
    return zlib.crc32(b) & 0xFFFF


def _rar4_block(htype: int, flags: int, body: bytes) -> bytes:
    size = 7 + len(body)
    rest = struct.pack("<BHH", htype, flags, size) + body
    return struct.pack("<H", _crc16(rest)) + rest


def rar4_archive(entries: list[tuple[str, bytes]]) -> bytes:
    out = bytearray(RAR4_MARKER)
    out += _rar4_block(0x73, 0, b"\0" * 6)
    for name, data in entries:
        nm = name.encode()
        body = struct.pack("<IIBIIBBHI", len(data), len(data), 3, zlib.crc32(data) & 0xFFFFFFFF, 0x5A210000, 29, 0x30, len(nm), 0o100644) + nm
        out += _rar4_block(0x74, 0x8000, body)
        out += data
    out += _rar4_block(0x7B, 0x4000, b"")
    return bytes(out)
