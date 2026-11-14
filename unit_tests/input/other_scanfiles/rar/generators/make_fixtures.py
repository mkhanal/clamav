"""Builds the RAR 1.5 / 2.0 / 2.6 fixtures.

RAR 2.0 fixtures are encoded with enc20.py from deterministic content.
RAR 1.5 fixtures (no encoder exists) are built in two passes: pass 1 writes
archives whose packed data is pseudo-random, unRAR decodes them, and pass 2
rewrites each header with the decoded size and CRC, giving valid archives.
"""
import math, os, random, struct, sys, zlib
sys.path.insert(0, os.path.dirname(__file__))
import rar4, enc20

out = sys.argv[1]; phase = sys.argv[2]
os.makedirs(out, exist_ok=True)


def wave(n, chans, seed):
    rnd = random.Random(seed); b = bytearray()
    for i in range(n // chans):
        for c in range(chans):
            v = 128 + 60 * math.sin(i * (0.05 + 0.02 * c)) + 30 * math.sin(i * 0.31 + c) + rnd.randint(-3, 3)
            b.append(max(0, min(255, int(v))))
    return bytes(b)


def text(n, seed):
    rnd = random.Random(seed)
    words = "the quick brown fox jumps over lazy dog clamav rar archive scanner signature virus heuristic".split()
    s = []
    while sum(map(len, s)) < n:
        s.append(rnd.choice(words) + rnd.choice([" ", " ", ", ", ".\n"]))
    return "".join(s).encode()[:n]


def far(n, seed):
    """Repeats of one block at distances in every distance range up to 1 MB."""
    rnd = random.Random(seed)
    blk = rnd.randbytes(1500)
    b = bytearray(blk)
    for d in [0x1800, 0x2000, 0x2400, 0x10000, 0x3ff00, 0x40000, 0x48000, 0xc0000, 0xfff00]:
        while len(b) < len(blk) + d - 1500:
            b += bytes(4096)
        b = b[:len(blk) + d - 1500] if len(b) > len(blk) + d - 1500 else b
        b += b[len(b) - d:len(b) - d + 1500]
    return bytes(b[:n]) if n else bytes(b)


def entry(name, data, packed, ver, solid):
    return dict(name=name, packed=packed, unp_size=len(data), crc=zlib.crc32(data), unp_ver=ver, solid=solid)


def write(name, entries, solid=False):
    with open(os.path.join(out, name), "wb") as fh:
        fh.write(rar4.archive(entries, solid))


if phase == "v20":
    # Plain LZ: text, literals, all match kinds.
    e = enc20.Encoder(); d = text(20000, 1)
    write("rar20_lz_text.rar", [entry("text.txt", d, e.encode(d, [("lz", len(d), 0)], False), 20, False)])
    # Distances in every range up to 1 MB (length bonuses at 0x2000 / 0x40000).
    e = enc20.Encoder(); d = far(0, 2)
    write("rar20_lz_far_distances.rar", [entry("far.bin", d, e.encode(d, [("lz", len(d), 0)], False), 20, False)])
    # Multimedia blocks, 1..4 channels, with switches LZ <-> audio inside one file.
    for ch in (1, 2, 3, 4):
        e = enc20.Encoder(); d = wave(6000, ch, ch)
        write("rar20_audio_%dch.rar" % ch, [entry("wave%d.raw" % ch, d, e.encode(d, [("audio", len(d), ch)], False), 20, False)])
    e = enc20.Encoder(); d = text(3000, 5) + wave(4000, 2, 6) + text(2000, 7) + wave(3000, 4, 8)
    plan = [("lz", 3000, 0), ("audio", 4000, 2), ("lz", 2000, 1), ("audio", 3000, 4)]
    write("rar20_block_switches.rar", [entry("mixed.bin", d, e.encode(d, plan, False), 20, False)])
    # Unpack version 26 (RAR 2.0 method, large-file era) decodes the same way.
    e = enc20.Encoder(); d = text(8000, 9) + wave(2000, 3, 10)
    write("rar26_lz_audio.rar", [entry("v26.bin", d, e.encode(d, [("lz", 8000, 0), ("audio", 2000, 3)], False), 26, False)])
    # Solid: window, tables, distance history and audio state carry over;
    # a block switch after the last byte of an entry applies to the next.
    e = enc20.Encoder(); ents = []
    parts = [(text(4000, 11), [("lz", 4000, 0)], ("audio", 2)),
             (wave(3000, 2, 12), [("audio", 3000, 2)], ("lz", 1)),
             (text(4000, 11)[:2500] + text(1000, 13), [("audio", 0, 2), ("lz", 3500, 1)], ("lz", 0)),
             (text(4000, 11), [("lz", 4000, 0)], None)]
    for i, (d, plan, trail) in enumerate(parts):
        plan = [p for p in plan if p[1] > 0] or plan
        ents.append(entry("solid%d.bin" % i, d, e.encode(d, plan, i > 0, trail), 20, i > 0))
    write("rar20_solid.rar", ents, solid=True)

if phase in ("v15pass1", "v15pass2"):
    specs = [("rar15_single.rar", [(15, 12000, 1.0)]),
             ("rar15_small.rar", [(15, 300, 2.0)]),
             ("rar15_low_freq_tables.rar", [(15, 8000, ("p", 0.05))]),
             ("rar15_high_freq_tables.rar", [(15, 8000, ("p", 0.95))]),
             ("rar15_solid.rar", [(15, 6000, 0.5), (15, 5000, 1.0), (15, 3000, 0.3)]),
             ("rar15_rar20_solid.rar", [(15, 4000, 1.0), (20, 6000, 1.0)])]
    for name, files in specs:
        rnd = random.Random(name)
        ents = []
        for i, (ver, unp, f) in enumerate(files):
            if ver == 20:
                e = enc20.Encoder(); d = text(unp, 99)
                ents.append(entry("f%d.bin" % i, d, e.encode(d, [("lz", unp, 0)], False), 20, i > 0))
                continue
            if isinstance(f, tuple):
                packed = bytes(sum((rnd.random() < f[1]) << b for b in range(8)) for _ in range(unp + 64))
            else:
                packed = rnd.randbytes(int(unp * f) + 64)
            ents.append(dict(name="f%d.bin" % i, packed=packed, unp_size=unp, crc=0, unp_ver=ver, solid=i > 0))
        if phase == "v15pass2":
            # decoded outputs from unRAR, written by pass 1 as <name>.<i>
            for i, e2 in enumerate(ents):
                if e2["unp_ver"] == 15:
                    dec = open(os.path.join(out, "oracle", name + ".%d" % i), "rb").read()
                    e2["unp_size"] = len(dec); e2["crc"] = zlib.crc32(dec)
        write(name, ents, solid=len(files) > 1)

if phase == "manifest":
    import glob, hashlib
    for f in sorted(glob.glob(os.path.join(out, "*.rar"))):
        b = open(f, "rb").read()
        pos = 7
        while pos + 7 <= len(b):
            t = b[pos + 2]; fl, hs = struct.unpack_from("<HH", b, pos + 3)
            add = struct.unpack_from("<I", b, pos + 7)[0] if fl & 0x8000 else 0
            if t == 0x74:
                unp, = struct.unpack_from("<I", b, pos + 11); crc, = struct.unpack_from("<I", b, pos + 16)
                nl, = struct.unpack_from("<H", b, pos + 26)
                print(os.path.basename(f), b[pos + 32:pos + 32 + nl].decode(), "unp=%d crc=%08x" % (unp, crc))
            if t == 0x7b: break
            pos += hs + add
