"""Minimal RAR 4.x archive writer for test fixtures (stdlib only)."""
import struct, zlib

MARK = b"Rar!\x1a\x07\x00"

def _block(htype, flags, body, add=b""):
    size = 7 + len(body)
    hdr = struct.pack("<BHH", htype, flags, size) + body
    crc = zlib.crc32(hdr) & 0xffff
    return struct.pack("<H", crc) + hdr + add

def main_header(solid=False):
    return _block(0x73, 0x0008 if solid else 0, b"\0" * 6)

def file_header(name, packed, unp_size, crc, unp_ver, method=0x33, solid=False, dict_bits=4, host=0, attr=0x20, ftime=0x5a8e0000):
    flags = 0x8000 | (dict_bits << 5) | (0x10 if solid else 0)
    nm = name.encode()
    body = struct.pack("<IIBIIBBHI", len(packed), unp_size, host, crc, ftime, unp_ver, method, len(nm), attr) + nm
    return _block(0x74, flags, body, packed)

def end_header():
    return _block(0x7b, 0x4000, b"")

def archive(entries, solid=False):
    """entries: list of dicts(name, packed, unp_size, crc, unp_ver, method, solid)"""
    out = MARK + main_header(solid)
    for e in entries:
        out += file_header(e["name"], e["packed"], e["unp_size"], e.get("crc", 0), e["unp_ver"], e.get("method", 0x33), e.get("solid", False), e.get("dict_bits", 4))
    return out + end_header()
