/*-
 * Copyright (c) 2026 Mridul Khanal
 * Copyright (c) 2015, Nicholas Waples (RAR 2.0 decoder, see below)
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR(S) ``AS IS'' AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
 * OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
 * IN NO EVENT SHALL THE AUTHOR(S) BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
 * NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
 * THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*
 * RAR 1.5 and RAR 2.0 decompression (unpack versions 15, 20 and 26).
 *
 * Provenance:
 * - The RAR 2.0 LZ, table and audio decoding follows the Go implementation
 *   in github.com/nwaples/rardecode (decode20.go, decode20_lz.go,
 *   decode20_audio.go), BSD-2-Clause, Copyright (c) 2015 Nicholas Waples,
 *   whose notice is reproduced above.
 * - The RAR 1.5 decoder was written for this file from the RAR 1.5 format.
 *   No RARLAB unRAR source, nor code derived from it, was read while
 *   writing it.
 * - The edge behaviour of both decoders (Huffman decoding of incomplete
 *   code tables, data past the end of the packed stream, the tables read at
 *   the end of a solid entry) was established by differential testing
 *   against RARLAB unRAR used as a black box.
 */

#include "archive_platform.h"

#ifdef HAVE_STDLIB_H
#include <stdlib.h>
#endif
#ifdef HAVE_STRING_H
#include <string.h>
#endif

#include "archive_rar_unpack1520.h"

#define WIN_SIZE	0x400000U
#define WIN_MASK	(WIN_SIZE - 1)

/*
 * Packed input goes through a fixed buffer that lives as long as the
 * decoder, like unRAR's. A corrupt or truncated stream may be decoded past
 * the end of its data; the bytes read there are whatever the buffer held
 * before, as with unRAR, so such streams decode identically.
 */
#define IN_SIZE		0x8000
#define IN_EXTRA	64
/* The decoders refill when fewer than this many bytes are buffered. */
#define IN_BORDER	30

/* RAR 2.0 table sizes. */
#define NC20	298	/* literals, lengths and control codes */
#define DC20	48	/* distances */
#define RC20	28	/* repeated distance lengths */
#define BC20	19	/* bit length code */
#define MC20	257	/* audio, per channel */

#define QUICK_BITS_MAX	10

struct huff_table {
	uint32_t	len[16];	/* left aligned upper limit per length */
	uint32_t	pos[16];	/* first symbol index per length */
	uint16_t	num[NC20];	/* symbols ordered by code */
	uint32_t	size;
	uint32_t	quick_bits;
	uint8_t		quick_len[1 << QUICK_BITS_MAX];
	uint16_t	quick_num[1 << QUICK_BITS_MAX];
};

struct audio_var {
	int		k[5];
	int		d[4];
	int		last_delta;
	unsigned int	dif[11];
	unsigned int	byte_count;
	int		last_char;
};

struct rar_unpack1520 {
	uint8_t		*window;
	uint32_t	unp_ptr;	/* next byte the decoder writes */
	uint32_t	wr_ptr;		/* next byte returned to the caller */

	/* Packed input. */
	uint8_t		*in;
	int32_t		in_addr;
	uint32_t	in_bit;
	int32_t		in_top;

	/* Current entry. */
	int		version;
	int		solid;
	int		started;
	int		finished;
	int		status;
	int64_t		dest;		/* bytes still to decode, minus one */

	/* State shared by both methods. */
	uint32_t	old_dist[4];
	uint32_t	old_dist_ptr;
	uint32_t	last_dist;
	uint32_t	last_length;

	/* RAR 1.5. */
	uint16_t	ch_set[256], ch_set_a[256], ch_set_b[256], ch_set_c[256];
	uint8_t		place[256], place_b[256], place_c[256];
	unsigned int	avr_plc, avr_plc_b, avr_ln1, avr_ln2, avr_ln3;
	unsigned int	num_huf, nhfb, nlzb, max_dist3, buf60;
	unsigned int	flag_buf;
	int		flags_cnt;
	int		st_mode;
	int		l_count;

	/* RAR 2.0. */
	int		tables_read;
	int		audio_block;
	int		channels;
	int		cur_channel;
	int		channel_delta;
	struct audio_var audio[4];
	uint8_t		old_table[MC20 * 4];
	struct huff_table ld, dd, rd, md[4];
};

/* ------------------------------------------------------------------ */
/* Input. */

/* Reads up to `want` bytes of packed data. Returns the count or < 0. */
static int32_t
read_packed(uint8_t *dst, int32_t want, rar_unpack1520_read_cb cb,
    void *ctx)
{
	const uint8_t *chunk;
	size_t avail;
	int32_t got = 0;

	while (got < want) {
		if (cb(ctx, (size_t)(want - got), &chunk, &avail) < 0)
			return (RAR_UNPACK1520_EIO);
		if (avail == 0)
			break;
		if (avail > (size_t)(want - got))
			avail = (size_t)(want - got);
		memcpy(dst + got, chunk, avail);
		got += (int32_t)avail;
	}
	return (got);
}

/*
 * Refills the input buffer. Returns 1, 0 once the read position has passed
 * the end of the data read so far, or a negative error.
 */
static int
fill_input(struct rar_unpack1520 *u, rar_unpack1520_read_cb cb, void *ctx)
{
	int32_t left = u->in_top - u->in_addr;
	int32_t got;

	if (left < 0)
		return (0);
	if (u->in_addr > IN_SIZE / 2) {
		if (left > 0)
			memmove(u->in, u->in + u->in_addr, (size_t)left);
		u->in_addr = 0;
		u->in_top = left;
	} else
		left = u->in_top;
	if (left != IN_SIZE) {
		got = read_packed(u->in + left, IN_SIZE - left, cb, ctx);
		if (got < 0)
			return (got);
		u->in_top += got;
	}
	return (1);
}

/*
 * Makes sure at least `border` bytes are buffered past the read position
 * when more packed data exists. Returns 1 to continue, 0 once the read
 * position has passed the end of the packed data, or a negative error.
 */
static int
ensure_input(struct rar_unpack1520 *u, int32_t border,
    rar_unpack1520_read_cb cb, void *ctx)
{
	if (u->in_addr > u->in_top - border)
		return (fill_input(u, cb, ctx));
	return (1);
}

static inline uint32_t
getbits(const struct rar_unpack1520 *u)
{
	const uint8_t *p = u->in + u->in_addr;
	uint32_t v = ((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2];
	return ((v >> (8 - u->in_bit)) & 0xffff);
}

static inline void
addbits(struct rar_unpack1520 *u, uint32_t bits)
{
	bits += u->in_bit;
	u->in_addr += (int32_t)(bits >> 3);
	u->in_bit = bits & 7;
	/* Corrupt input never reads past the buffer. */
	if (u->in_addr > IN_SIZE + IN_EXTRA / 2)
		u->in_addr = IN_SIZE + IN_EXTRA / 2;
}

/* ------------------------------------------------------------------ */
/* Output helpers. */

static inline void
put_byte(struct rar_unpack1520 *u, uint8_t b)
{
	u->window[u->unp_ptr] = b;
	u->unp_ptr = (u->unp_ptr + 1) & WIN_MASK;
}

static void
copy_match(struct rar_unpack1520 *u, uint32_t distance, uint32_t length)
{
	u->dest -= length;
	while (length-- > 0) {
		u->window[u->unp_ptr] =
		    u->window[(u->unp_ptr - distance) & WIN_MASK];
		u->unp_ptr = (u->unp_ptr + 1) & WIN_MASK;
	}
}

/* ------------------------------------------------------------------ */
/* RAR 1.5. */

/*
 * The RAR 1.5 static codes. A code word's value range selects its bit
 * length (start + index); the position table maps it to a symbol index.
 */
struct code15 {
	uint32_t start;
	const uint32_t *limit;
	const uint32_t *pos;
};

static const uint32_t lim_l1[] = { 0x8000, 0xa000, 0xc000, 0xd000, 0xe000,
    0xea00, 0xee00, 0xf000, 0xf200, 0xf200, 0xffff };
static const uint32_t pos_l1[] = { 0, 0, 0, 2, 3, 5, 7, 11, 16, 20, 24, 32,
    32 };
static const uint32_t lim_l2[] = { 0xa000, 0xc000, 0xd000, 0xe000, 0xea00,
    0xee00, 0xf000, 0xf200, 0xf240, 0xffff };
static const uint32_t pos_l2[] = { 0, 0, 0, 0, 5, 7, 9, 13, 18, 22, 26, 34,
    36 };
static const uint32_t lim_hf0[] = { 0x8000, 0xc000, 0xe000, 0xf200, 0xf200,
    0xf200, 0xf200, 0xf200, 0xffff };
static const uint32_t pos_hf0[] = { 0, 0, 0, 0, 0, 8, 16, 24, 33, 33, 33,
    33, 33 };
static const uint32_t lim_hf1[] = { 0x2000, 0xc000, 0xe000, 0xf000, 0xf200,
    0xf200, 0xf7e0, 0xffff };
static const uint32_t pos_hf1[] = { 0, 0, 0, 0, 0, 0, 4, 44, 60, 76, 80, 80,
    127 };
static const uint32_t lim_hf2[] = { 0x1000, 0x2400, 0x8000, 0xc000, 0xfa00,
    0xffff, 0xffff, 0xffff };
static const uint32_t pos_hf2[] = { 0, 0, 0, 0, 0, 0, 2, 7, 53, 117, 233, 0,
    0 };
static const uint32_t lim_hf3[] = { 0x800, 0x2400, 0xee00, 0xfe80, 0xffff,
    0xffff, 0xffff };
static const uint32_t pos_hf3[] = { 0, 0, 0, 0, 0, 0, 0, 2, 16, 218, 251, 0,
    0 };
static const uint32_t lim_hf4[] = { 0xff00, 0xffff, 0xffff, 0xffff, 0xffff,
    0xffff };
static const uint32_t pos_hf4[] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0,
    0 };

static const struct code15 code_l1 = { 2, lim_l1, pos_l1 };
static const struct code15 code_l2 = { 3, lim_l2, pos_l2 };
static const struct code15 code_hf0 = { 4, lim_hf0, pos_hf0 };
static const struct code15 code_hf1 = { 5, lim_hf1, pos_hf1 };
static const struct code15 code_hf2 = { 5, lim_hf2, pos_hf2 };
static const struct code15 code_hf3 = { 6, lim_hf3, pos_hf3 };
static const struct code15 code_hf4 = { 8, lim_hf4, pos_hf4 };

/* Short match codes; entry 1 (table 1) or 3 (table 2) varies in length. */
static const uint8_t short_len1[] = { 1, 3, 4, 4, 5, 6, 7, 8, 8, 4, 4, 5, 6,
    6, 4, 0 };
static const uint8_t short_code1[] = { 0x00, 0xa0, 0xd0, 0xe0, 0xf0, 0xf8,
    0xfc, 0xfe, 0xff, 0xc0, 0x80, 0x90, 0x98, 0x9c, 0xb0, 0x00 };
static const uint8_t short_len2[] = { 2, 3, 3, 3, 4, 4, 5, 6, 6, 4, 4, 5, 6,
    6, 4, 0 };
static const uint8_t short_code2[] = { 0x00, 0x40, 0x60, 0xa0, 0xd0, 0xe0,
    0xf0, 0xf8, 0xfc, 0xc0, 0x80, 0x90, 0x98, 0x9c, 0xb0, 0x00 };

static uint32_t
decode15(struct rar_unpack1520 *u, uint32_t bits, const struct code15 *c)
{
	uint32_t i, len = c->start;
	uint32_t prev;

	bits &= 0xfff0;
	for (i = 0; c->limit[i] <= bits; i++)
		len++;
	addbits(u, len);
	prev = i ? c->limit[i - 1] : 0;
	return (((bits - prev) >> (16 - len)) + c->pos[len]);
}

/* Re-ranks an adaptive symbol set once a counter overflows. */
static void
rerank15(uint16_t *set, uint8_t *place)
{
	int i, j;

	for (i = 7; i >= 0; i--)
		for (j = 0; j < 32; j++, set++)
			*set = (uint16_t)((*set & ~0xff) | i);
	memset(place, 0, 256);
	for (i = 6; i >= 0; i--)
		place[i] = (uint8_t)((7 - i) * 32);
}

static void
init_sets15(struct rar_unpack1520 *u)
{
	unsigned int i;

	for (i = 0; i < 256; i++) {
		u->ch_set[i] = u->ch_set_b[i] = (uint16_t)(i << 8);
		u->ch_set_a[i] = (uint16_t)i;
		u->ch_set_c[i] = (uint16_t)(((~i + 1) & 0xff) << 8);
	}
	memset(u->place, 0, sizeof(u->place));
	memset(u->place_b, 0, sizeof(u->place_b));
	memset(u->place_c, 0, sizeof(u->place_c));
	rerank15(u->ch_set_b, u->place_b);
}

static void
read_flags15(struct rar_unpack1520 *u)
{
	uint32_t flags, idx, nidx;

	idx = decode15(u, getbits(u), &code_hf2);
	if (idx >= 256)
		return;
	for (;;) {
		flags = u->ch_set_c[idx];
		u->flag_buf = flags >> 8;
		nidx = u->place_c[flags++ & 0xff]++;
		if ((flags & 0xff) != 0)
			break;
		rerank15(u->ch_set_c, u->place_c);
	}
	u->ch_set_c[idx] = u->ch_set_c[nidx];
	u->ch_set_c[nidx] = (uint16_t)flags;
}

static void
push_dist(struct rar_unpack1520 *u, uint32_t distance, uint32_t length)
{
	/*
	 * The RAR 2.0 decoder leaves the pointer unmasked; a solid RAR 1.5
	 * entry following a RAR 2.0 one must not index past the history.
	 */
	u->old_dist[u->old_dist_ptr++ & 3] = distance;
	u->old_dist_ptr &= 3;
	u->last_length = length;
	u->last_dist = distance;
	copy_match(u, distance, length);
}

static void
short_match15(struct rar_unpack1520 *u)
{
	uint32_t bits, code, len, saved, distance, place, prev;

	u->num_huf = 0;
	bits = getbits(u);
	if (u->l_count == 2) {
		addbits(u, 1);
		if (bits >= 0x8000) {
			copy_match(u, u->last_dist, u->last_length);
			return;
		}
		bits <<= 1;
		u->l_count = 0;
	}
	bits = (bits >> 8) & 0xff;

	for (code = 0;; code++) {
		uint32_t n;
		if (u->avr_ln1 < 37) {
			n = code == 1 ? u->buf60 + 3 : short_len1[code];
			if (((bits ^ short_code1[code]) & ~(0xffU >> n) &
			    0xff) == 0)
				break;
		} else {
			n = code == 3 ? u->buf60 + 3 : short_len2[code];
			if (((bits ^ short_code2[code]) & ~(0xffU >> n) &
			    0xff) == 0)
				break;
		}
	}
	if (u->avr_ln1 < 37)
		addbits(u, code == 1 ? u->buf60 + 3 : short_len1[code]);
	else
		addbits(u, code == 3 ? u->buf60 + 3 : short_len2[code]);
	len = code;

	if (len >= 9) {
		if (len == 9) {
			u->l_count++;
			copy_match(u, u->last_dist, u->last_length);
			return;
		}
		if (len == 14) {
			u->l_count = 0;
			len = decode15(u, getbits(u), &code_l2) + 5;
			distance = (getbits(u) >> 1) | 0x8000;
			addbits(u, 15);
			u->last_length = len;
			u->last_dist = distance;
			copy_match(u, distance, len);
			return;
		}
		u->l_count = 0;
		saved = len;
		distance = u->old_dist[(u->old_dist_ptr - (len - 9)) & 3];
		len = decode15(u, getbits(u), &code_l1) + 2;
		if (len == 0x101 && saved == 10) {
			u->buf60 ^= 1;
			return;
		}
		if (distance > 256)
			len++;
		if (distance >= u->max_dist3)
			len++;
		push_dist(u, distance, len);
		return;
	}

	u->l_count = 0;
	u->avr_ln1 += len;
	u->avr_ln1 -= u->avr_ln1 >> 4;

	place = decode15(u, getbits(u), &code_hf2) & 0xff;
	distance = u->ch_set_a[place];
	if (place > 0) {
		prev = u->ch_set_a[place - 1];
		u->ch_set_a[place] = (uint16_t)prev;
		u->ch_set_a[place - 1] = (uint16_t)distance;
	}
	len += 2;
	push_dist(u, distance + 1, len);
}

static void
long_match15(struct rar_unpack1520 *u)
{
	uint32_t bits, len, distance, place, nplace, avr2, avr3;

	u->num_huf = 0;
	u->nlzb += 16;
	if (u->nlzb > 0xff) {
		u->nlzb = 0x90;
		u->nhfb >>= 1;
	}
	avr2 = u->avr_ln2;

	bits = getbits(u);
	if (u->avr_ln2 >= 122)
		len = decode15(u, bits, &code_l2);
	else if (u->avr_ln2 >= 64)
		len = decode15(u, bits, &code_l1);
	else if (bits < 0x100) {
		len = bits;
		addbits(u, 16);
	} else {
		for (len = 0; ((bits << len) & 0x8000) == 0; len++)
			;
		addbits(u, len + 1);
	}
	u->avr_ln2 += len;
	u->avr_ln2 -= u->avr_ln2 >> 5;

	bits = getbits(u);
	if (u->avr_plc_b > 0x28ff)
		place = decode15(u, bits, &code_hf2);
	else if (u->avr_plc_b > 0x6ff)
		place = decode15(u, bits, &code_hf1);
	else
		place = decode15(u, bits, &code_hf0);
	u->avr_plc_b += place;
	u->avr_plc_b -= u->avr_plc_b >> 8;

	for (;;) {
		distance = u->ch_set_b[place & 0xff];
		nplace = u->place_b[distance++ & 0xff]++;
		if ((distance & 0xff) != 0)
			break;
		rerank15(u->ch_set_b, u->place_b);
	}
	u->ch_set_b[place & 0xff] = u->ch_set_b[nplace];
	u->ch_set_b[nplace] = (uint16_t)distance;

	distance = ((distance & 0xff00) | (getbits(u) >> 8)) >> 1;
	addbits(u, 7);

	avr3 = u->avr_ln3;
	if (len != 1 && len != 4) {
		if (len == 0 && distance <= u->max_dist3) {
			u->avr_ln3++;
			u->avr_ln3 -= u->avr_ln3 >> 8;
		} else if (u->avr_ln3 > 0)
			u->avr_ln3--;
	}
	len += 3;
	if (distance >= u->max_dist3)
		len++;
	if (distance <= 256)
		len += 8;
	if (avr3 > 0xb0 || (u->avr_plc >= 0x2a00 && avr2 < 0x40))
		u->max_dist3 = 0x7f00;
	else
		u->max_dist3 = 0x2001;
	push_dist(u, distance, len);
}

static void
literal15(struct rar_unpack1520 *u)
{
	uint32_t bits, cur, nplace, len, distance;
	int place;

	bits = getbits(u);
	if (u->avr_plc > 0x75ff)
		place = (int)decode15(u, bits, &code_hf4);
	else if (u->avr_plc > 0x5dff)
		place = (int)decode15(u, bits, &code_hf3);
	else if (u->avr_plc > 0x35ff)
		place = (int)decode15(u, bits, &code_hf2);
	else if (u->avr_plc > 0x0dff)
		place = (int)decode15(u, bits, &code_hf1);
	else
		place = (int)decode15(u, bits, &code_hf0);
	place &= 0xff;

	if (u->st_mode) {
		if (place == 0 && bits > 0xfff)
			place = 0x100;
		if (--place == -1) {
			bits = getbits(u);
			addbits(u, 1);
			if (bits & 0x8000) {
				u->num_huf = 0;
				u->st_mode = 0;
				return;
			}
			len = (bits & 0x4000) ? 4 : 3;
			addbits(u, 1);
			distance = decode15(u, getbits(u), &code_hf2);
			distance = (distance << 5) | (getbits(u) >> 11);
			addbits(u, 5);
			copy_match(u, distance, len);
			return;
		}
	} else if (u->num_huf++ >= 16 && u->flags_cnt == 0)
		u->st_mode = 1;

	u->avr_plc += place;
	u->avr_plc -= u->avr_plc >> 8;
	u->nhfb += 16;
	if (u->nhfb > 0xff) {
		u->nhfb = 0x90;
		u->nlzb >>= 1;
	}

	put_byte(u, (uint8_t)(u->ch_set[place] >> 8));
	u->dest--;

	for (;;) {
		cur = u->ch_set[place];
		nplace = u->place[cur++ & 0xff]++;
		if ((cur & 0xff) <= 0xa1)
			break;
		rerank15(u->ch_set, u->place);
	}
	u->ch_set[place] = u->ch_set[nplace];
	u->ch_set[nplace] = (uint16_t)cur;
}

static void
next_flag15(struct rar_unpack1520 *u)
{
	if (--u->flags_cnt < 0) {
		read_flags15(u);
		u->flags_cnt = 7;
	}
}

static void
step15(struct rar_unpack1520 *u)
{
	if (u->st_mode) {
		literal15(u);
		return;
	}
	next_flag15(u);
	if (u->flag_buf & 0x80) {
		u->flag_buf <<= 1;
		if (u->nlzb > u->nhfb)
			long_match15(u);
		else
			literal15(u);
		return;
	}
	u->flag_buf <<= 1;
	next_flag15(u);
	if (u->flag_buf & 0x80) {
		u->flag_buf <<= 1;
		if (u->nlzb > u->nhfb)
			literal15(u);
		else
			long_match15(u);
		return;
	}
	u->flag_buf <<= 1;
	short_match15(u);
}

/* ------------------------------------------------------------------ */
/* RAR 2.0. */

static const uint8_t len_base20[28] = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12,
    14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224 };
static const uint8_t len_bits20[28] = { 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1,
    2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5 };
static const uint32_t dist_base20[DC20] = { 0, 1, 2, 3, 4, 6, 8, 12, 16,
    24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 3072,
    4096, 6144, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 98304,
    131072, 196608, 262144, 327680, 393216, 458752, 524288, 589824, 655360,
    720896, 786432, 851968, 917504, 983040 };
static const uint8_t dist_bits20[DC20] = { 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4,
    4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14,
    15, 15, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16 };
static const uint8_t short_base20[8] = { 0, 4, 8, 16, 32, 64, 128, 192 };
static const uint8_t short_bits20[8] = { 2, 2, 3, 4, 5, 6, 6, 6 };

/*
 * Builds a canonical Huffman table from code lengths. Over-subscribed or
 * incomplete length sets are accepted; decoding them yields symbol 0
 * where no symbol fits.
 */
static void
make_table(struct huff_table *t, const uint8_t *lengths, uint32_t size)
{
	uint32_t count[16], next[16];
	uint32_t i, upper, code, cur;

	memset(count, 0, sizeof(count));
	for (i = 0; i < size; i++)
		count[lengths[i] & 0xf]++;
	count[0] = 0;
	memset(t->num, 0, sizeof(t->num));
	t->size = size;
	t->pos[0] = 0;
	t->len[0] = 0;
	upper = 0;
	for (i = 1; i < 16; i++) {
		upper += count[i];
		t->len[i] = upper << (16 - i);
		upper *= 2;
		t->pos[i] = t->pos[i - 1] + count[i - 1];
	}
	memcpy(next, t->pos, sizeof(next));
	for (i = 0; i < size; i++) {
		uint32_t l = lengths[i] & 0xf;
		if (l != 0)
			t->num[next[l]++] = (uint16_t)i;
	}

	t->quick_bits = size == NC20 ? QUICK_BITS_MAX : QUICK_BITS_MAX - 3;
	cur = 1;
	for (code = 0; code < (1U << t->quick_bits); code++) {
		uint32_t bits = code << (16 - t->quick_bits);
		uint32_t dist, p;

		while (cur < 16 && bits >= t->len[cur])
			cur++;
		t->quick_len[code] = (uint8_t)cur;
		if (cur < 16) {
			dist = (bits - t->len[cur - 1]) >> (16 - cur);
			p = t->pos[cur] + dist;
			t->quick_num[code] = p < size ? t->num[p] : 0;
		} else
			t->quick_num[code] = 0;
	}
}

static uint32_t
decode_symbol(struct rar_unpack1520 *u, const struct huff_table *t)
{
	uint32_t bits = getbits(u) & 0xfffe;
	uint32_t n, i, dist, p;

	if (bits < t->len[t->quick_bits]) {
		uint32_t code = bits >> (16 - t->quick_bits);
		addbits(u, t->quick_len[code]);
		return (t->quick_num[code]);
	}
	n = 15;
	for (i = t->quick_bits + 1; i < 15; i++) {
		if (bits < t->len[i]) {
			n = i;
			break;
		}
	}
	addbits(u, n);
	dist = (bits - t->len[n - 1]) >> (16 - n);
	p = t->pos[n] + dist;
	if (p >= t->size)
		p = 0;
	return (t->num[p]);
}

static void
reset_tables20(struct rar_unpack1520 *u)
{
	static const uint8_t zero[NC20];
	int i;

	make_table(&u->ld, zero, NC20);
	make_table(&u->dd, zero, DC20);
	make_table(&u->rd, zero, RC20);
	for (i = 0; i < 4; i++)
		make_table(&u->md[i], zero, MC20);
}

/* Reads a block header and its code tables. Returns 1, or 0 to stop. */
static int
read_tables20(struct rar_unpack1520 *u, rar_unpack1520_read_cb cb,
    void *ctx)
{
	uint8_t bit_len[BC20];
	uint8_t table[MC20 * 4];
	struct huff_table bt;
	uint32_t bits, size, i, n;
	int r;

	if ((r = ensure_input(u, 25, cb, ctx)) <= 0)
		return (r);
	bits = getbits(u);
	u->audio_block = (bits & 0x8000) != 0;
	if (!(bits & 0x4000))
		memset(u->old_table, 0, sizeof(u->old_table));
	addbits(u, 2);
	if (u->audio_block) {
		u->channels = (int)((bits >> 12) & 3) + 1;
		if (u->cur_channel >= u->channels)
			u->cur_channel = 0;
		addbits(u, 2);
		size = MC20 * (uint32_t)u->channels;
	} else
		size = NC20 + DC20 + RC20;

	for (i = 0; i < BC20; i++) {
		bit_len[i] = (uint8_t)(getbits(u) >> 12);
		addbits(u, 4);
	}
	make_table(&bt, bit_len, BC20);
	for (i = 0; i < size;) {
		if ((r = ensure_input(u, 5, cb, ctx)) <= 0)
			return (r);
		n = decode_symbol(u, &bt);
		if (n < 16) {
			table[i] = (uint8_t)((n + u->old_table[i]) & 0xf);
			i++;
		} else if (n == 16) {
			n = (getbits(u) >> 14) + 3;
			addbits(u, 2);
			if (i == 0)
				return (0);
			while (n-- > 0 && i < size) {
				table[i] = table[i - 1];
				i++;
			}
		} else {
			if (n == 17) {
				n = (getbits(u) >> 13) + 3;
				addbits(u, 3);
			} else {
				n = (getbits(u) >> 9) + 11;
				addbits(u, 7);
			}
			while (n-- > 0 && i < size)
				table[i++] = 0;
		}
	}
	u->tables_read = 1;
	if (u->in_addr > u->in_top)
		return (0);
	if (u->audio_block) {
		for (i = 0; i < (uint32_t)u->channels; i++)
			make_table(&u->md[i], table + i * MC20, MC20);
	} else {
		make_table(&u->ld, table, NC20);
		make_table(&u->dd, table + NC20, DC20);
		make_table(&u->rd, table + NC20 + DC20, RC20);
	}
	memcpy(u->old_table, table, size);
	return (1);
}

static uint8_t
decode_audio20(struct rar_unpack1520 *u, int delta)
{
	struct audio_var *v = &u->audio[u->cur_channel];
	unsigned int min_dif;
	int pch, d, i, num_min;
	unsigned int ch;

	v->byte_count++;
	v->d[3] = v->d[2];
	v->d[2] = v->d[1];
	v->d[1] = v->last_delta - v->d[0];
	v->d[0] = v->last_delta;
	pch = 8 * v->last_char + v->k[0] * v->d[0] + v->k[1] * v->d[1] +
	    v->k[2] * v->d[2] + v->k[3] * v->d[3] + v->k[4] * u->channel_delta;
	pch = (pch >> 3) & 0xff;
	ch = (unsigned int)(pch - delta);

	d = (signed char)delta;
	d *= 8;
	v->dif[0] += (unsigned int)abs(d);
	v->dif[1] += (unsigned int)abs(d - v->d[0]);
	v->dif[2] += (unsigned int)abs(d + v->d[0]);
	v->dif[3] += (unsigned int)abs(d - v->d[1]);
	v->dif[4] += (unsigned int)abs(d + v->d[1]);
	v->dif[5] += (unsigned int)abs(d - v->d[2]);
	v->dif[6] += (unsigned int)abs(d + v->d[2]);
	v->dif[7] += (unsigned int)abs(d - v->d[3]);
	v->dif[8] += (unsigned int)abs(d + v->d[3]);
	v->dif[9] += (unsigned int)abs(d - u->channel_delta);
	v->dif[10] += (unsigned int)abs(d + u->channel_delta);

	u->channel_delta = v->last_delta = (signed char)(ch - v->last_char);
	v->last_char = (int)ch;

	if ((v->byte_count & 0x1f) == 0) {
		min_dif = v->dif[0];
		num_min = 0;
		v->dif[0] = 0;
		for (i = 1; i < 11; i++) {
			if (v->dif[i] < min_dif) {
				min_dif = v->dif[i];
				num_min = i;
			}
			v->dif[i] = 0;
		}
		if (num_min > 0) {
			int k = (num_min - 1) / 2;
			if ((num_min - 1) % 2 == 0) {
				if (v->k[k] >= -16)
					v->k[k]--;
			} else if (v->k[k] < 16)
				v->k[k]++;
		}
	}
	return ((uint8_t)ch);
}

static void
match20(struct rar_unpack1520 *u, uint32_t length, uint32_t distance)
{
	u->old_dist[u->old_dist_ptr++ & 3] = distance;
	u->last_dist = distance;
	u->last_length = length;
	copy_match(u, distance, length);
}

static inline uint32_t
extra_bits(struct rar_unpack1520 *u, uint32_t n)
{
	uint32_t v;

	if (n == 0)
		return (0);
	v = getbits(u) >> (16 - n);
	addbits(u, n);
	return (v);
}

/* One decoding step. Returns 1, or 0 when the tables could not be read. */
static int
step20(struct rar_unpack1520 *u, rar_unpack1520_read_cb cb, void *ctx)
{
	uint32_t n, length, distance;

	if (u->audio_block) {
		n = decode_symbol(u, &u->md[u->cur_channel]);
		if (n == 256)
			return (read_tables20(u, cb, ctx));
		put_byte(u, decode_audio20(u, (int)n));
		if (++u->cur_channel == u->channels)
			u->cur_channel = 0;
		u->dest--;
		return (1);
	}

	n = decode_symbol(u, &u->ld);
	if (n < 256) {
		put_byte(u, (uint8_t)n);
		u->dest--;
		return (1);
	}
	if (n > 269) {
		n -= 270;
		length = len_base20[n] + 3 + extra_bits(u, len_bits20[n]);
		n = decode_symbol(u, &u->dd);
		distance = dist_base20[n] + 1 + extra_bits(u, dist_bits20[n]);
		if (distance >= 0x2000) {
			length++;
			if (distance >= 0x40000)
				length++;
		}
		match20(u, length, distance);
		return (1);
	}
	if (n == 269)
		return (read_tables20(u, cb, ctx));
	if (n == 256) {
		match20(u, u->last_length, u->last_dist);
		return (1);
	}
	if (n < 261) {
		distance = u->old_dist[(u->old_dist_ptr - (n - 256)) & 3];
		n = decode_symbol(u, &u->rd);
		length = len_base20[n] + 2 + extra_bits(u, len_bits20[n]);
		if (distance >= 0x101) {
			length++;
			if (distance >= 0x2000) {
				length++;
				if (distance >= 0x40000)
					length++;
			}
		}
		match20(u, length, distance);
		return (1);
	}
	n -= 261;
	distance = short_base20[n] + 1 + extra_bits(u, short_bits20[n]);
	match20(u, 2, distance);
	return (1);
}

/*
 * After the last byte of an entry, a block switch that follows it is
 * applied, so the next solid entry starts with the new tables.
 */
static int
read_last_tables20(struct rar_unpack1520 *u, rar_unpack1520_read_cb cb,
    void *ctx)
{
	if (u->in_top >= u->in_addr + 5) {
		if (u->audio_block) {
			if (decode_symbol(u, &u->md[u->cur_channel]) == 256)
				return (read_tables20(u, cb, ctx));
		} else if (decode_symbol(u, &u->ld) == 269)
			return (read_tables20(u, cb, ctx));
	}
	return (1);
}

/* ------------------------------------------------------------------ */
/* Public interface. */

struct rar_unpack1520 *
rar_unpack1520_new(void)
{
	struct rar_unpack1520 *u = calloc(1, sizeof(*u));

	if (u == NULL)
		return (NULL);
	u->window = calloc(1, WIN_SIZE);
	u->in = calloc(1, IN_SIZE + IN_EXTRA);
	if (u->window == NULL || u->in == NULL) {
		rar_unpack1520_free(u);
		return (NULL);
	}
	return (u);
}

void
rar_unpack1520_free(struct rar_unpack1520 *u)
{
	if (u == NULL)
		return;
	free(u->window);
	free(u->in);
	free(u);
}

int
rar_unpack1520_begin(struct rar_unpack1520 *u, int unp_ver, int solid,
    uint64_t unpacked_size)
{
	if (unp_ver < 13 || unp_ver > 28)
		return (RAR_UNPACK1520_CORRUPT);
	if (unp_ver <= 15)
		unp_ver = 15;
	else if (unp_ver != 20 && unp_ver != 26) {
		/*
		 * Versions between the defined ones have no decoder: like unRAR,
		 * the entry decodes to nothing and leaves all state alone.
		 */
		u->version = 0;
		u->started = 1;
		u->finished = 1;
		u->status = 0;
		u->dest = -1;
		u->wr_ptr = u->unp_ptr;
		return (0);
	}

	if (!solid) {
		memset(u->old_dist, 0, sizeof(u->old_dist));
		u->old_dist_ptr = 0;
		u->last_dist = u->last_length = 0;
		u->unp_ptr = 0;

		/* RAR 1.5 adaptive state. */
		init_sets15(u);
		u->avr_plc_b = u->avr_ln1 = u->avr_ln2 = u->avr_ln3 = 0;
		u->num_huf = u->buf60 = 0;
		u->avr_plc = 0x3500;
		u->max_dist3 = 0x2001;
		u->nhfb = u->nlzb = 0x80;

		/* RAR 2.0 state. */
		u->tables_read = 0;
		u->audio_block = 0;
		u->channel_delta = 0;
		u->cur_channel = 0;
		u->channels = 1;
		memset(u->audio, 0, sizeof(u->audio));
		memset(u->old_table, 0, sizeof(u->old_table));
		reset_tables20(u);
	}
	u->flags_cnt = 0;
	u->flag_buf = 0;
	u->st_mode = 0;
	u->l_count = 0;

	u->wr_ptr = u->unp_ptr;
	u->in_addr = u->in_top = 0;
	u->in_bit = 0;

	u->version = unp_ver;
	u->solid = solid;
	u->started = 0;
	u->finished = 0;
	u->status = 0;
	u->dest = (int64_t)unpacked_size;
	return (0);
}

/*
 * Returns decoded bytes. The last match of an entry may run past the
 * declared size; those bytes are returned as well, as unRAR writes them.
 */
static ssize_t
deliver(struct rar_unpack1520 *u, uint8_t *out, size_t out_size)
{
	uint32_t pending = (u->unp_ptr - u->wr_ptr) & WIN_MASK;
	size_t n = pending, first;

	if (n > out_size)
		n = out_size;
	first = WIN_SIZE - u->wr_ptr;
	if (first > n)
		first = n;
	memcpy(out, u->window + u->wr_ptr, first);
	memcpy(out + first, u->window, n - first);
	u->wr_ptr = (u->wr_ptr + (uint32_t)n) & WIN_MASK;
	return ((ssize_t)n);
}

ssize_t
rar_unpack1520_read(struct rar_unpack1520 *u, uint8_t *out, size_t out_size,
    rar_unpack1520_read_cb cb, void *ctx)
{
	uint32_t limit;
	int r;

	if (out_size == 0)
		return (0);
	limit = out_size < WIN_SIZE / 2 ? (uint32_t)out_size : WIN_SIZE / 2;

	if (!u->started) {
		u->started = 1;
		if ((r = fill_input(u, cb, ctx)) < 0 ||
		    (r == 0 && u->version != 15)) {
			u->status = r;
			u->finished = 1;
		} else if (u->version == 15) {
			u->dest--;
			if (u->dest >= 0) {
				read_flags15(u);
				u->flags_cnt = 8;
			}
		} else {
			if ((!u->solid || !u->tables_read) &&
			    (r = read_tables20(u, cb, ctx)) <= 0) {
				u->status = r < 0 ? r : RAR_UNPACK1520_CORRUPT;
				u->finished = 1;
			}
			u->dest--;
		}
	}

	while (!u->finished &&
	    ((u->unp_ptr - u->wr_ptr) & WIN_MASK) < limit) {
		if (u->dest < 0) {
			if (u->version != 15 &&
			    (r = read_last_tables20(u, cb, ctx)) < 0)
				u->status = r;
			u->finished = 1;
			break;
		}
		u->unp_ptr &= WIN_MASK;
		if ((r = ensure_input(u, IN_BORDER, cb, ctx)) <= 0) {
			u->status = r < 0 ? r : RAR_UNPACK1520_TRUNCATED;
			u->finished = 1;
			break;
		}
		if (u->version == 15)
			step15(u);
		else if ((r = step20(u, cb, ctx)) <= 0) {
			u->status = r < 0 ? r : RAR_UNPACK1520_CORRUPT;
			u->finished = 1;
		}
	}

	if (((u->unp_ptr - u->wr_ptr) & WIN_MASK) > 0)
		return (deliver(u, out, out_size));
	if (u->finished && u->status == 0 && u->dest >= 0)
		u->status = RAR_UNPACK1520_TRUNCATED;
	return (u->status < 0 ? u->status : RAR_UNPACK1520_DONE);
}
