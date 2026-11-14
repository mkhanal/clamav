#!/usr/bin/env python3
"""Write RAR 2.9 (RAR 3.x format) archives whose data is coded with
literal-only LZ blocks and one standard VM filter, for filters no tool
we can run emits (Itanium, E8E9).

The filter is identified by the reader from the length and CRC32 of its
VM code, so the code bytes are synthesised: a valid XOR check byte, no
static data, and the last bytes chosen so the CRC32 hits the standard
filter's value. The stored data is the encoder-side transform of the
payload, and the file CRC is that of the payload, so a reader that
applies the filter correctly extracts with a matching CRC.
"""
import hashlib, random, struct, sys, zlib

STANDARD = {"itanium": (120, 0x3769893F), "e8e9": (57, 0x3CD7E57E), "e8": (53, 0xAD576887)}


class Bits:
    def __init__(self):
        self.out = bytearray(); self.acc = 0; self.n = 0
    def put(self, value, count):
        for i in range(count - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> i) & 1); self.n += 1
            if self.n == 8:
                self.out.append(self.acc); self.acc = 0; self.n = 0
    def data(self):
        b = bytearray(self.out)
        if self.n:
            b.append(self.acc << (8 - self.n))
        return bytes(b) + b"\0" * 8


def vm_number(bits, value):
    if value < 16:
        bits.put(0, 2); bits.put(value, 4)
    elif value < 0x10000:
        bits.put(2, 2); bits.put(value, 16)
    else:
        bits.put(3, 2); bits.put(value, 32)


def forge_code(length, crc_target, seed):
    """length bytes: byte0 = XOR of the rest, byte1 bit7 clear (no static
    data), CRC32 of all = crc_target. Solve the last 8 bytes over GF(2)."""
    rnd = random.Random(seed)
    base = bytearray(rnd.getrandbits(8) for _ in range(length))
    base[1] &= 0x7F
    free = list(range((length - 8) * 8, length * 8))  # bit positions of last 8 bytes

    def constraints(buf):
        b = bytearray(buf)
        x = 0
        for v in b[1:]:
            x ^= v
        b[0] = x  # byte0 follows the XOR of the rest
        c = zlib.crc32(bytes(b))
        return c | (x << 32)  # 40 constraint bits (byte0 enters crc)

    def setbit(buf, pos, val):
        i, k = divmod(pos, 8)
        buf[i] = (buf[i] & ~(1 << (7 - k))) | (val << (7 - k))

    for p in free:
        setbit(base, p, 0)
    c0 = constraints(base)
    cols = []
    for p in free:
        t = bytearray(base); setbit(t, p, 1)
        cols.append(constraints(t) ^ c0)  # affine -> linear part
    target = (crc_target ^ c0) & 0xFFFFFFFF  # want crc = target, xor byte unconstrained
    # Only the CRC must hit; byte0 is derived. Solve 32 equations.
    rows = []
    for bit in range(32):
        row = 0
        for j, col in enumerate(cols):
            if (col >> bit) & 1:
                row |= 1 << j
        rows.append([row, (target >> bit) & 1])
    sol = 0; pivots = []
    r = 0
    for j in range(len(cols)):
        piv = next((i for i in range(r, 32) if (rows[i][0] >> j) & 1), None)
        if piv is None:
            continue
        rows[r], rows[piv] = rows[piv], rows[r]
        for i in range(32):
            if i != r and (rows[i][0] >> j) & 1:
                rows[i][0] ^= rows[r][0]; rows[i][1] ^= rows[r][1]
        pivots.append((r, j)); r += 1
    for i in range(r, 32):
        assert rows[i][1] == 0, "unsolvable"
    for row_i, j in pivots:
        if rows[row_i][1]:
            sol |= 1 << j
    for j, p in enumerate(free):
        setbit(base, p, (sol >> j) & 1)
    x = 0
    for v in base[1:]:
        x ^= v
    base[0] = x
    assert zlib.crc32(bytes(base)) == crc_target and len(base) == length and not base[1] & 0x80
    return bytes(base)


def itanium_transform(buf, pos, encode):
    masks = [4, 4, 6, 6, 0, 0, 7, 7, 4, 4, 0, 0, 4, 4, 0, 0]
    b = bytearray(buf); off = pos >> 4; i = 0
    while len(b) - i > 21:
        t = (b[i] & 0x1F) - 0x10
        if t >= 0 and masks[t]:
            for slot in range(3):
                if not masks[t] & (1 << slot):
                    continue
                bp = slot * 41 + 18
                word = int.from_bytes(b[i:i + 17], "little")
                if (word >> (bp + 24)) & 0xF == 5:
                    tgt = (word >> bp) & 0xFFFFF
                    tgt = (tgt + off if encode else tgt - off) & 0xFFFFF
                    word = (word & ~(0xFFFFF << bp)) | (tgt << bp)
                    b[i:i + 17] = word.to_bytes(17, "little")
        i += 16; off += 1
    return bytes(b)


def e8_transform(buf, pos, e9, encode):
    b = bytearray(buf); size = 0x1000000; i = 0
    while i <= len(b) - 5:
        if b[i] == 0xE8 or (e9 and b[i] == 0xE9):
            cur = (pos + i + 1) & 0xFFFFFFFF
            a = int.from_bytes(b[i + 1:i + 5], "little", signed=True)
            if encode:
                # inverse of the decoder: absolute -> relative
                if 0 <= (a + cur) < size or True:
                    pass
                v = a + cur
                if -cur <= a < 0:
                    nv = a + cur  # decoder maps negative a with cur>=-a: a+size
                    nv = a + size
                    raise ValueError
            i += 5
        else:
            i += 1
    raise NotImplementedError


def e8_decode(buf, pos, e9):
    b = bytearray(buf); size = 0x1000000; i = 0
    while i <= len(b) - 5:
        if b[i] == 0xE8 or (e9 and b[i] == 0xE9):
            cur = (pos + i + 1) & 0xFFFFFFFF
            a = int.from_bytes(b[i + 1:i + 5], "little", signed=True)
            if a < 0:
                if cur >= -a:
                    b[i + 1:i + 5] = ((a + size) & 0xFFFFFFFF).to_bytes(4, "little")
            elif a < size:
                b[i + 1:i + 5] = ((a - cur) & 0xFFFFFFFF).to_bytes(4, "little")
            i += 5
        else:
            i += 1
    return bytes(b)


def header(htype, flags, body):
    size = 7 + len(body)
    h = bytes([htype]) + struct.pack("<HH", flags, size) + body
    return struct.pack("<H", zlib.crc32(h) & 0xFFFF) + h


def archive(name, payload, packed):
    out = b"Rar!\x1a\x07\x00"
    out += header(0x73, 0, b"\0" * 6)
    nb = name.encode()
    body = struct.pack("<IIBIIBBHI", len(packed), len(payload), 3, zlib.crc32(payload), 0x5A2E6000,
                       29, 0x33, len(nb), 0x81A4) + nb
    out += header(0x74, 0x8000, body) + packed
    out += header(0x7B, 0x4000, b"")
    return out


def encode(stored, filters):
    """stored: bytes the LZ layer outputs. filters: list of (at, start, length, code, regs)."""
    bits = Bits()
    bits.put(0, 1)  # LZ block
    bits.put(0, 1)  # fresh tables
    pre = [0] * 20
    for s in (0, 9, 18, 19):
        pre[s] = 2
    for v in pre:
        bits.put(v, 4)
    precode = {0: 0, 9: 1, 18: 2, 19: 3}
    for _ in range(258):
        bits.put(precode[9], 2)
    zeros = 404 - 258
    while zeros:
        if zeros >= 11:
            n = min(zeros, 138); bits.put(precode[19], 2); bits.put(n - 11, 7)
        else:
            n = zeros; assert n >= 3; bits.put(precode[18], 2); bits.put(n - 3, 3)
        zeros -= n
    pending = sorted(filters)
    first = True
    for pos in range(len(stored) + 1):
        while pending and pending[0][0] == pos:
            at, start, length, code, regs = pending.pop(0)
            d = Bits()
            flags = 0x20
            if first:
                flags |= 0x80
                vm_number(d, 0)  # reset the program list, new program
            vm_number(d, start)
            vm_number(d, length)
            if regs:
                flags |= 0x10
                mask = 0
                for r in regs:
                    mask |= 1 << r
                d.put(mask, 7)
                for r in sorted(regs):
                    vm_number(d, regs[r])
            if first:
                vm_number(d, len(code))
                for c in code:
                    d.put(c, 8)
            body = bytes(d.data()[: (len(d.out) * 8 + d.n + 7) // 8])
            first = False
            fb = flags | 7  # length in the next two bytes
            bits.put(257, 9)
            for v in (fb, len(body) >> 8, len(body) & 0xFF):
                bits.put(v, 8)
            for c in body:
                bits.put(c, 8)
        if pos < len(stored):
            bits.put(stored[pos], 9)
    bits.put(256, 9)  # end of block:
    bits.put(0, 1)    # end of file,
    bits.put(0, 1)    # no new tables follow
    return bits.data()


def make(kind, path, payload, filters, seed=1):
    length, crc = STANDARD[kind]
    code = forge_code(length, crc, seed)
    stored = bytearray(payload)
    for at, start, flen in filters:
        a = at + start
        seg = bytes(stored[a:a + flen])
        if kind == "itanium":
            stored[a:a + flen] = itanium_transform(seg, a, True)
        else:
            raise SystemExit("only itanium needs an encoder transform; e8 variants use decode-direction data")
    packed = encode(bytes(stored), [(at, start, flen, code, {}) for at, start, flen in filters])
    open(path, "wb").write(archive(path.rsplit("/", 1)[-1].replace(".rar", ".bin"), payload, packed))
    print("expect", path.rsplit("/", 1)[-1], hashlib.sha256(payload).hexdigest())


def make_raw(kind, path, stored, filters, decode, seed=1):
    """Store `stored` as-is and declare the filter; payload = decode(stored)."""
    length, crc = STANDARD[kind]
    code = forge_code(length, crc, seed)
    payload = bytearray(stored)
    for at, start, flen in filters:
        a = at + start
        payload[a:a + flen] = decode(bytes(payload[a:a + flen]), a)
    packed = encode(bytes(stored), [(at, start, flen, code, {}) for at, start, flen in filters])
    open(path, "wb").write(archive(path.rsplit("/", 1)[-1].replace(".rar", ".bin"), bytes(payload), packed))
    print("expect", path.rsplit("/", 1)[-1], hashlib.sha256(bytes(payload)).hexdigest())
    return bytes(payload)


def ia64_bundles(n, rnd):
    out = bytearray()
    for i in range(n):
        tmpl = rnd.choice([0x10, 0x11, 0x12, 0x13, 0x16, 0x17, 0x18, 0x19, 0x1C, 0x1D, 0x08, 0x00])
        word = rnd.getrandbits(128) & ~0x1F | tmpl
        for slot in range(3):
            if rnd.random() < 0.7:
                bp = slot * 41 + 18
                word = (word & ~(0xF << (bp + 24))) | (5 << (bp + 24))
        out += word.to_bytes(16, "little")
    return bytes(out)


if __name__ == "__main__":
    outdir = sys.argv[1]
    rnd = random.Random(29)
    payload = ia64_bundles(700, rnd)  # 11200 bytes
    # two Itanium filter blocks; the second reuses the program and starts mid-file
    make("itanium", outdir + "/rar4-filter-itanium.rar", payload, [(0, 0, 4096), (5000, 120, 4096)])
    code = bytearray()
    while len(code) < 8000:
        if rnd.random() < 0.25:
            code += bytes([rnd.choice([0xE8, 0xE9])]) + rnd.randrange(-50000, 50000).to_bytes(4, "little", signed=True)
        else:
            code += bytes([rnd.choice([0x55, 0x89, 0xE5, 0x8B, 0x45, 0xC3, 0x90])])
    code = bytes(code[:8000])
    make_raw("e8e9", outdir + "/rar4-filter-e8e9.rar", code, [(0, 0, 4000), (4100, 0, 3900)],
             lambda s, a: e8_decode(s, a, True))
    for kind, n in (("itanium", 120), ("e8e9", 57)):
        pass
