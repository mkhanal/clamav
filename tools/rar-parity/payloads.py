#!/usr/bin/env python3
"""Deterministic payload files used to generate the rar-parity fixtures.

Usage: payloads.py OUTDIR
"""
import math
import os
import random
import struct
import sys


def marker(case: str) -> bytes:
    return (f"RARPARITY-MARKER {case}\n" * 20).encode()


def x86_code(n: int = 48000) -> bytes:
    rnd = random.Random(1)
    out = bytearray()
    while len(out) < n:
        if rnd.random() < 0.18:
            op = rnd.choice([0xE8, 0xE9])
            out += bytes([op]) + struct.pack("<i", rnd.randint(-0x20000, 0x20000))
        else:
            out += bytes(rnd.choice([0x55, 0x89, 0xE5, 0x8B, 0x45, 0x08, 0x83, 0xC4, 0x10, 0xC3, 0x90]) for _ in range(rnd.randint(1, 6)))
    return bytes(out[:n])


def itanium_code(n: int = 32000) -> bytes:
    rnd = random.Random(2)
    out = bytearray()
    while len(out) < n:
        template = rnd.choice([0x10, 0x11, 0x16, 0x17, 0x1C, 0x1D])
        body = bytearray(rnd.getrandbits(8) for _ in range(15))
        out += bytes([template]) + bytes(body)
    return bytes(out[:n])


def delta_table(n: int = 32000) -> bytes:
    return bytes(int(127 + 100 * math.sin(i / 40.0) + (i // 3) % 7) & 0xFF for i in range(n))


def wav(n_frames: int = 12000) -> bytes:
    data = b"".join(struct.pack("<hh", int(9000 * math.sin(i / 17.0)), int(9000 * math.sin(i / 23.0))) for i in range(n_frames))
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 44100 * 4, 4, 16) + b"data" + struct.pack("<I", len(data))
    return hdr + data


def bmp(w: int = 96, h: int = 96) -> bytes:
    rows = []
    for y in range(h):
        row = b"".join(bytes([(x * 2 + y) & 0xFF, (y * 2) & 0xFF, (x + y) & 0xFF]) for x in range(w))
        rows.append(row + b"\0" * ((4 - len(row) % 4) % 4))
    px = b"".join(rows)
    return b"BM" + struct.pack("<IHHI", 54 + len(px), 0, 0, 54) + struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(px), 2835, 2835, 0, 0) + px


def text(n: int = 40000) -> bytes:
    rnd = random.Random(3)
    words = ["quality", "deviation", "capa", "change", "control", "record", "audit", "trail", "batch", "release", "signature", "review"]
    return (" ".join(rnd.choice(words) for _ in range(n // 6)) + "\n").encode()[:n]


def main() -> None:
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    files = {
        "marker.txt": marker("plain"),
        "marker2.txt": marker("second"),
        "text.txt": marker("text") + text(),
        "x86.bin": marker("x86") + x86_code(),
        "ia64.bin": marker("ia64") + itanium_code(),
        "delta.bin": marker("delta") + delta_table(),
        "audio.wav": wav(),
        "rgb.bmp": bmp(),
        "zeros.bin": marker("zeros") + b"\0" * 200000,
        "zeros4m.bin": marker("bomb") + b"\0" * 4000000,
    }
    os.makedirs(os.path.join(out, "many"), exist_ok=True)
    for i in range(400):
        with open(os.path.join(out, "many", f"f{i:03d}.txt"), "wb") as f:
            f.write(marker(f"many-{i:03d}"))
    for name, data in files.items():
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)


if __name__ == "__main__":
    main()
