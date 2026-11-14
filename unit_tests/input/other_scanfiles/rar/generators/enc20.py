"""A small RAR 2.0 (unpack version 20/26) encoder for test fixtures.

It emits valid streams using every RAR 2.0 construct: literals, long
matches with all distance ranges, short-distance matches, repeated
distances (symbols 256..260), block switches (symbol 269) between LZ and
multimedia (audio) blocks with 1..4 channels, table updates relative to the
previous tables, and solid continuation across entries. Compression ratio
is not a goal. Written for this project from the decoding rules; output is
checked against RARLAB unRAR used as a black box.
"""

LEN_BASE = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224]
LEN_BITS = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5]
DIST_BASE = [0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 3072,
             4096, 6144, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 98304, 131072, 196608, 262144, 327680,
             393216, 458752, 524288, 589824, 655360, 720896, 786432, 851968, 917504, 983040]
DIST_BITS = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14,
             15, 15, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16]
SHORT_BASE = [0, 4, 8, 16, 32, 64, 128, 192]
SHORT_BITS = [2, 2, 3, 4, 5, 6, 6, 6]
NC, DC, RC, MC, BC = 298, 48, 28, 257, 19


class BitWriter:
    def __init__(self):
        self.out = bytearray(); self.acc = 0; self.n = 0

    def put(self, value, bits):
        for i in range(bits - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> i) & 1); self.n += 1
            if self.n == 8:
                self.out.append(self.acc); self.acc = 0; self.n = 0

    def data(self):
        out = bytearray(self.out)
        if self.n:
            out.append(self.acc << (8 - self.n))
        return bytes(out) + b"\0" * 8  # slack so the decoder's look-ahead stays inside the data


def canonical(lengths):
    """Canonical codes: ordered by length, then by symbol."""
    codes = {}; code = 0
    for l in range(1, 16):
        for s, sl in enumerate(lengths):
            if sl == l:
                codes[s] = (code, l); code += 1
        code <<= 1
    return codes


def find_len_code(base_len):
    for i in range(27, -1, -1):
        if LEN_BASE[i] <= base_len and base_len - LEN_BASE[i] < (1 << LEN_BITS[i]):
            return i
    return None


def find_dist_code(d):
    for i in range(47, -1, -1):
        if DIST_BASE[i] + 1 <= d and d - DIST_BASE[i] - 1 < (1 << DIST_BITS[i]):
            return i
    return None


class Encoder:
    """State persists across entries for solid archives."""

    def __init__(self):
        self.old_table = [0] * (MC * 4)
        self.hist = bytearray()       # all output so far (window)
        self.old_dist = [0, 0, 0, 0]; self.ptr = 0
        self.last_dist = 0; self.last_len = 0
        self.audio = None; self.cur_chan = 0; self.chans = 1; self.chan_delta = 0
        self.av = [dict(k=[0]*5, d=[0]*4, last_delta=0, dif=[0]*11, byte_count=0, last_char=0) for _ in range(4)]
        self.codes = None

    # --- tables
    def write_tables(self, bw, audio, chans, lengths, keep_old):
        bw.put(1 if audio else 0, 1); bw.put(1 if keep_old else 0, 1)
        if not keep_old:
            self.old_table = [0] * (MC * 4)
        if audio:
            bw.put(chans - 1, 2)
        # Bit length code: give every value 0..15 a 5-bit code would exceed 19*... use lengths 4 for 0..15
        bl = [4] * 16 + [0, 0, 0]
        for v in bl:
            bw.put(v, 4)
        bcodes = canonical(bl)
        for i, l in enumerate(lengths):
            delta = (l - self.old_table[i]) & 0xf
            c, n = bcodes[delta]; bw.put(c, n)
        for i, l in enumerate(lengths):
            self.old_table[i] = l
        self.audio = audio; self.chans = chans
        if self.cur_chan >= chans:
            self.cur_chan = 0
        if audio:
            self.codes = [canonical(lengths[i*MC:(i+1)*MC]) for i in range(chans)]
        else:
            self.codes = (canonical(lengths[:NC]), canonical(lengths[NC:NC+DC]), canonical(lengths[NC+DC:]))

    def lz_lengths(self, variant):
        main = [9] * NC
        if variant:
            main = [9 + (i % 3 == 0) for i in range(NC)]
        return main + [6] * DC + [5] * RC

    def audio_lengths(self, chans):
        one = [8] * 255 + [9, 9]
        return one * chans

    # --- audio model (mirrors the decoder)
    def audio_predict(self):
        v = self.av[self.cur_chan]
        d = [v['last_delta'], v['last_delta'] - v['d'][0], v['d'][1], v['d'][2]]
        k = v['k']
        pch = 8 * v['last_char'] + k[0]*d[0] + k[1]*d[1] + k[2]*d[2] + k[3]*d[3] + k[4]*self.chan_delta
        return (pch >> 3) & 0xff

    def audio_update(self, delta):
        v = self.av[self.cur_chan]
        v['byte_count'] += 1
        v['d'][3] = v['d'][2]; v['d'][2] = v['d'][1]; v['d'][1] = v['last_delta'] - v['d'][0]; v['d'][0] = v['last_delta']
        pch = 8 * v['last_char'] + sum(a*b for a, b in zip(v['k'][:4], v['d'])) + v['k'][4]*self.chan_delta
        pch = (pch >> 3) & 0xff
        ch = pch - delta
        D = (delta - 256 if delta >= 128 else delta) * 8
        dif = v['dif']; dd = v['d']; cd = self.chan_delta
        for i, x in enumerate([D, D - dd[0], D + dd[0], D - dd[1], D + dd[1], D - dd[2], D + dd[2], D - dd[3], D + dd[3], D - cd, D + cd]):
            dif[i] = (dif[i] + abs(x)) & 0xffffffff
        t = (ch - v['last_char']) & 0xff
        self.chan_delta = v['last_delta'] = t - 256 if t >= 128 else t
        v['last_char'] = ch
        if v['byte_count'] & 0x1f == 0:
            mn = dif[0]; num = 0; dif[0] = 0
            for i in range(1, 11):
                if dif[i] < mn:
                    mn = dif[i]; num = i
                dif[i] = 0
            if num > 0:
                num -= 1; i = num // 2
                if num % 2 == 0:
                    if v['k'][i] >= -16: v['k'][i] -= 1
                elif v['k'][i] < 16: v['k'][i] += 1
        return ch & 0xff

    def put_sym(self, bw, codes, s):
        c, n = codes[s]; bw.put(c, n)

    # --- LZ
    def emit_match(self, bw, length, dist):
        main, dcodes, rcodes = self.codes
        # repeat of last match
        if dist == self.last_dist and length == self.last_len and self.last_len:
            self.put_sym(bw, main, 256); self.push(dist, length); return True
        # repeated distance 257..260
        for i in range(4):
            if self.old_dist[(self.ptr - 1 - i) & 3] == dist and dist:
                adj = (dist >= 0x101) + (dist >= 0x2000) + (dist >= 0x40000)
                lc = find_len_code(length - 2 - adj) if length - 2 - adj >= 0 else None
                if lc is not None:
                    self.put_sym(bw, main, 257 + i); self.put_sym(bw, rcodes, lc)
                    bw.put(length - 2 - adj - LEN_BASE[lc], LEN_BITS[lc]); self.push(dist, length); return True
        if length == 2 and dist <= 256:
            for i in range(8):
                if SHORT_BASE[i] + 1 <= dist < SHORT_BASE[i] + 1 + (1 << SHORT_BITS[i]):
                    self.put_sym(bw, main, 261 + i); bw.put(dist - SHORT_BASE[i] - 1, SHORT_BITS[i]); self.push(dist, 2); return True
        adj = (dist >= 0x2000) + (dist >= 0x40000)
        if length - 3 - adj < 0:
            return False
        lc = find_len_code(length - 3 - adj); dc = find_dist_code(dist)
        if lc is None or dc is None:
            return False
        self.put_sym(bw, main, 270 + lc); bw.put(length - 3 - adj - LEN_BASE[lc], LEN_BITS[lc])
        self.put_sym(bw, dcodes, dc); bw.put(dist - DIST_BASE[dc] - 1, DIST_BITS[dc])
        self.push(dist, length); return True

    def push(self, dist, length):
        self.old_dist[self.ptr & 3] = dist; self.ptr += 1
        self.last_dist = dist; self.last_len = length

    def start_block(self, bw, kind, arg, switch):
        if switch:
            self.put_sym(bw, self.codes[self.cur_chan] if self.audio else self.codes[0], 256 if self.audio else 269)
        lengths = self.audio_lengths(arg) if kind == 'audio' else self.lz_lengths(arg)
        self.write_tables(bw, kind == 'audio', arg if kind == 'audio' else 1, lengths, keep_old=switch)

    def same_block(self, kind, arg):
        return self.codes is not None and (kind == 'audio') == bool(self.audio) and (kind != 'audio' or arg == self.chans)

    def encode(self, data, plan, solid, trailing=None):
        """plan: list of (kind, nbytes, arg); kind 'lz' (arg: table variant) or
        'audio' (arg: channels). trailing: (kind, arg) block switch written after
        the last byte, which the decoder applies at the end of the entry."""
        bw = BitWriter()
        pos = 0
        for i, (kind, nbytes, arg) in enumerate(plan):
            if i == 0:
                if not solid or self.codes is None:
                    self.start_block(bw, kind, arg, switch=False)
                elif not self.same_block(kind, arg):
                    self.start_block(bw, kind, arg, switch=True)
            else:
                self.start_block(bw, kind, arg, switch=True)
            end = min(len(data), pos + nbytes)
            if kind == 'audio':
                while pos < end:
                    pch = self.audio_predict()
                    delta = (pch - data[pos]) & 0xff
                    self.put_sym(bw, self.codes[self.cur_chan], delta)
                    self.audio_update(delta)
                    self.hist.append(data[pos]); pos += 1
                    self.cur_chan = (self.cur_chan + 1) % self.chans
            else:
                while pos < end:
                    best = (0, 0)
                    h = self.hist
                    lim = min(257, end - pos)
                    cands = [d for d in self.old_dist if d] + [1, 2, 3, 4, 7, 100, 255, 256, 257, 300, 0x1fff, 0x2000, 0x2100, 0x3ffff, 0x40000, 0x40100, 0xfffff]
                    cands += [len(h) - j for j in range(max(0, len(h) - 4096), len(h)) if h[j] == data[pos]][-64:]
                    for d in set(cands):
                        if d <= 0 or d > len(h) or d > 0x100000:
                            continue
                        l = 0
                        while l < lim and (h[len(h) - d + l] if l < d else data[pos + l - d]) == data[pos + l]:
                            l += 1
                        if l > best[0]:
                            best = (l, d)
                    l, d = best
                    if l >= 2 and self.emit_match(bw, l, d):
                        for _ in range(l):
                            self.hist.append(self.hist[len(self.hist) - d])
                        pos += l
                    else:
                        self.put_sym(bw, self.codes[0], data[pos]); self.hist.append(data[pos]); pos += 1
        if trailing:
            self.start_block(bw, trailing[0], trailing[1], switch=True)
        return bw.data()
