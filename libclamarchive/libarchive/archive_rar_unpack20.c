/*-
 * Copyright (c) 2015, Nicholas Waples
 * All rights reserved.
 *
 * C port Copyright (c) 2026 Mridul Khanal
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * * Redistributions of source code must retain the above copyright notice, this
 *   list of conditions and the following disclaimer.
 *
 * * Redistributions in binary form must reproduce the above copyright notice,
 *   this list of conditions and the following disclaimer in the documentation
 *   and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*
 * A C port of the RAR 2.0 / 2.6 decoder of github.com/nwaples/rardecode
 * (BSD-2-Clause), commit f557bc97578a96c9196330d7ba642a8599a2ebd6:
 * decode20.go, decode20_lz.go, decode20_audio.go, huffman.go,
 * bit_reader.go and the length / offset tables of decode29_lz.go. The
 * structure and the names follow those files (converted to C style).
 * No other source was used.
 */

#include "archive_platform.h"

#include <stdlib.h>
#include <string.h>

#include "archive_rar_unpack20.h"

#define MAX_CODE_LENGTH 15	/* maximum code length in bits */
#define MAX_QUICK_BITS 10
#define MAX_QUICK_SIZE (1 << MAX_QUICK_BITS)

#define MAIN20_SIZE 298
#define OFFSET20_SIZE 48
#define LENGTH20_SIZE 28
#define AUDIO_SIZE 257
#define AUDIO_CHANNELS 4

#define MAX_HUFFMAN_SYMBOLS MAIN20_SIZE

static const int length_base[28] = {
	0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20,
	24, 28, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224
};
static const uint8_t length_extra_bits[28] = {
	0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2,
	2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5
};

static const int offset_base[60] = {
	0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96,
	128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096,
	6144, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 98304,
	131072, 196608, 262144, 327680, 393216, 458752, 524288,
	589824, 655360, 720896, 786432, 851968, 917504, 983040,
	1048576, 1310720, 1572864, 1835008, 2097152, 2359296, 2621440,
	2883584, 3145728, 3407872, 3670016, 3932160
};
static const uint8_t offset_extra_bits[60] = {
	0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6,
	6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14,
	15, 15, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16,
	18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18
};

static const int short_offset_base[8] = {0, 4, 8, 16, 32, 64, 128, 192};
static const uint8_t short_offset_extra_bits[8] = {2, 2, 3, 4, 5, 6, 6, 6};

/*
 * rar_bit_reader: reads bits, most significant first, from a byte source.
 */
struct rar20_bit_reader {
	rar20_byte_fn next_byte;
	void *ctx;
	uint64_t v;	/* cache of bits read from the byte source */
	uint8_t n;	/* number of unread bits in v */
};

static void
bit_reader_reset(struct rar20_bit_reader *r)
{
	r->v = 0;
	r->n = 0;
}

/* Reads n bits (n <= 24). */
static int
read_bits(struct rar20_bit_reader *r, unsigned n, int *out)
{
	while (n > r->n) {
		int b = r->next_byte(r->ctx);

		if (b < 0)
			return (RAR20_ERR_EOF);
		r->v = (r->v << 8) | (uint64_t)b;
		r->n += 8;
	}
	r->n -= n;
	*out = (int)((r->v >> r->n) & ((1u << n) - 1));
	return (RAR20_OK);
}

static void
unread_bits(struct rar20_bit_reader *r, unsigned n)
{
	r->n += n;
}

/*
 * huffman_decoder
 */
struct rar20_huffman {
	uint16_t limit[MAX_CODE_LENGTH + 1];
	uint16_t pos[MAX_CODE_LENGTH + 1];
	uint16_t symbol[MAX_HUFFMAN_SYMBOLS];
	unsigned nsymbol;
	uint8_t min;
	uint8_t quickbits;
	uint8_t quicklen[MAX_QUICK_SIZE];
	uint16_t quicksym[MAX_QUICK_SIZE];
};

static void
huffman_init(struct rar20_huffman *h, const uint8_t *code_lengths, size_t n)
{
	uint16_t count[MAX_CODE_LENGTH + 1];
	uint8_t i;
	size_t k;
	unsigned bits;
	unsigned q;

	memset(count, 0, sizeof(count));
	for (k = 0; k < n; k++) {
		if (code_lengths[k] == 0)
			continue;
		count[code_lengths[k]]++;
	}

	h->pos[0] = 0;
	h->limit[0] = 0;
	h->min = 0;
	for (i = 1; i <= MAX_CODE_LENGTH; i++) {
		h->limit[i] = (uint16_t)(h->limit[i - 1] +
		    (count[i] << (MAX_CODE_LENGTH - i)));
		h->pos[i] = (uint16_t)(h->pos[i - 1] + count[i - 1]);
		if (h->min == 0 && h->limit[i] > 0)
			h->min = i;
	}

	h->nsymbol = (unsigned)n;
	memset(h->symbol, 0, sizeof(h->symbol));

	memcpy(count, h->pos, sizeof(count));
	for (k = 0; k < n; k++) {
		if (code_lengths[k] != 0) {
			h->symbol[count[code_lengths[k]]] = (uint16_t)k;
			count[code_lengths[k]]++;
		}
	}

	if (n >= 298)
		h->quickbits = MAX_QUICK_BITS;
	else
		h->quickbits = MAX_QUICK_BITS - 3;

	bits = 1;
	for (q = 0; q < (1u << h->quickbits); q++) {
		uint16_t v = (uint16_t)(q << (MAX_CODE_LENGTH - h->quickbits));
		uint16_t dist;
		unsigned pos;

		while (v >= h->limit[bits] && bits < MAX_CODE_LENGTH)
			bits++;
		h->quicklen[q] = (uint8_t)bits;

		dist = (uint16_t)(v - h->limit[bits - 1]);
		dist >>= (MAX_CODE_LENGTH - bits);

		pos = (unsigned)h->pos[bits] + dist;
		if (pos < h->nsymbol)
			h->quicksym[q] = h->symbol[pos];
		else
			h->quicksym[q] = 0;
	}
}

static int
huffman_read_sym(struct rar20_huffman *h, struct rar20_bit_reader *r, int *sym)
{
	unsigned bits;
	uint16_t v = 0;
	uint16_t dist;
	unsigned pos;
	int n, err;

	err = read_bits(r, MAX_CODE_LENGTH, &n);
	if (err != RAR20_OK) {
		if (err != RAR20_ERR_EOF)
			return (err);
		/* fall back to 1 bit at a time if we read past EOF */
		for (bits = 1; bits <= MAX_CODE_LENGTH; bits++) {
			int b;

			err = read_bits(r, 1, &b);
			if (err != RAR20_OK)
				return (err);
			v |= (uint16_t)(b << (MAX_CODE_LENGTH - bits));
			if (v < h->limit[bits])
				break;
		}
		if (bits > MAX_CODE_LENGTH)
			return (RAR20_ERR_HUFF_DECODE);
	} else {
		v = (uint16_t)n;
		if (v < h->limit[h->quickbits]) {
			unsigned i = v >> (MAX_CODE_LENGTH - h->quickbits);

			unread_bits(r, MAX_CODE_LENGTH - h->quicklen[i]);
			*sym = h->quicksym[i];
			return (RAR20_OK);
		}

		for (bits = h->min; bits < MAX_CODE_LENGTH; bits++) {
			if (v < h->limit[bits]) {
				unread_bits(r, MAX_CODE_LENGTH - bits);
				break;
			}
		}
	}

	dist = (uint16_t)(v - h->limit[bits - 1]);
	dist >>= MAX_CODE_LENGTH - bits;

	pos = (unsigned)h->pos[bits] + dist;
	if (pos >= h->nsymbol)
		return (RAR20_ERR_HUFF_DECODE);

	*sym = h->symbol[pos];
	return (RAR20_OK);
}

/*
 * Reads a new code length table into table (len bytes) from br; the old
 * table is added to the new one.
 */
static int
read_code_length_table20(struct rar20_bit_reader *br, uint8_t *table,
    size_t len)
{
	uint8_t bitlength[19];
	struct rar20_huffman bl;
	size_t i, n;
	int v, l, err;

	for (i = 0; i < sizeof(bitlength); i++) {
		err = read_bits(br, 4, &v);
		if (err != RAR20_OK)
			return (err);
		bitlength[i] = (uint8_t)v;
	}

	huffman_init(&bl, bitlength, sizeof(bitlength));

	for (i = 0; i < len;) {
		err = huffman_read_sym(&bl, br, &l);
		if (err != RAR20_OK)
			return (err);
		if (l < 16) {
			table[i] = (uint8_t)((table[i] + l) & 0xf);
			i++;
			continue;
		}
		if (l == 16) {
			uint8_t prev;

			if (i == 0)
				return (RAR20_ERR_LENGTH_TABLE);
			err = read_bits(br, 2, &v);
			if (err != RAR20_OK)
				return (err);
			n = (size_t)v + 3;
			if (i + n > len)
				n = len;
			else
				n = i + n;
			prev = table[i - 1];
			while (i < n) {
				table[i] = prev;
				i++;
			}
			continue;
		}
		if (l == 17) {
			err = read_bits(br, 3, &v);
			if (err != RAR20_OK)
				return (err);
			n = (size_t)v + 3;
		} else {
			err = read_bits(br, 7, &v);
			if (err != RAR20_OK)
				return (err);
			n = (size_t)v + 11;
		}
		if (i + n > len)
			n = len;
		else
			n = i + n;
		memset(table + i, 0, n - i);
		i = n;
	}
	return (RAR20_OK);
}

/*
 * lz20_decoder
 */
struct rar20_lz {
	int length;	/* previous length */
	int offset[4];	/* history of previous offsets */

	struct rar20_huffman main_decoder;
	struct rar20_huffman offset_decoder;
	struct rar20_huffman length_decoder;
};

/*
 * audio20_decoder
 */
struct rar20_audio_var {
	int k[5];
	int d[4];
	int last_delta;
	int dif[11];
	uint32_t byte_count;
	int last_char;
};

struct rar20_audio {
	int chans;	/* number of audio channels */
	int cur_chan;	/* current audio channel */
	int chan_delta;

	struct rar20_huffman decoders[AUDIO_CHANNELS];
	struct rar20_audio_var vars[AUDIO_CHANNELS];
};

/*
 * decoder20
 */
struct rar20_decoder {
	struct rar20_bit_reader br;
	int hdr_read;	/* block header has been read */
	int is_audio;	/* current block is Audio */

	uint8_t code_length[AUDIO_SIZE * 4];

	struct rar20_lz lz;
	struct rar20_audio audio;
};

static int
rar20_abs(int x)
{
	return (x < 0 ? -x : x);
}

/* The value of the low 8 bits of x as a signed byte. */
static int
rar20_int8(int x)
{
	x &= 0xff;
	return (x >= 128 ? x - 256 : x);
}

static void
window_write_byte(unsigned char *win, size_t mask, int64_t *position,
    unsigned char c)
{
	win[(size_t)*position & mask] = c;
	(*position)++;
}

static void
window_copy_bytes(unsigned char *win, size_t mask, int64_t *position,
    int length, int offset)
{
	int i;

	for (i = 0; i < length; i++) {
		win[(size_t)*position & mask] =
		    win[(size_t)(*position - offset) & mask];
		(*position)++;
	}
}

static void
audio20_reset(struct rar20_audio *d)
{
	d->chans = 1;
	d->cur_chan = 0;
	d->chan_delta = 0;

	memset(d->vars, 0, sizeof(d->vars));
}

static int
audio20_init(struct rar20_audio *d, struct rar20_bit_reader *br,
    uint8_t *table)
{
	int n, i, err;

	err = read_bits(br, 2, &n);
	if (err != RAR20_OK)
		return (err);
	d->chans = n + 1;
	if (d->cur_chan >= d->chans)
		d->cur_chan = 0;
	err = read_code_length_table20(br, table, (size_t)AUDIO_SIZE * d->chans);
	if (err != RAR20_OK)
		return (err);
	for (i = 0; i < d->chans; i++) {
		huffman_init(&d->decoders[i], table, AUDIO_SIZE);
		table += AUDIO_SIZE;
	}
	return (RAR20_OK);
}

static uint8_t
audio20_decode(struct rar20_audio *d, int delta)
{
	struct rar20_audio_var *v = &d->vars[d->cur_chan];
	int pch, ch, num_min_dif, min_dif, i;

	v->byte_count++;
	v->d[3] = v->d[2];
	v->d[2] = v->d[1];
	v->d[1] = v->last_delta - v->d[0];
	v->d[0] = v->last_delta;
	pch = 8 * v->last_char + v->k[0] * v->d[0] + v->k[1] * v->d[1] +
	    v->k[2] * v->d[2] + v->k[3] * v->d[3] + v->k[4] * d->chan_delta;
	pch = (pch >> 3) & 0xFF;
	ch = pch - delta;
	delta = rar20_int8(delta) * 8;

	v->dif[0] += rar20_abs(delta);
	v->dif[1] += rar20_abs(delta - v->d[0]);
	v->dif[2] += rar20_abs(delta + v->d[0]);
	v->dif[3] += rar20_abs(delta - v->d[1]);
	v->dif[4] += rar20_abs(delta + v->d[1]);
	v->dif[5] += rar20_abs(delta - v->d[2]);
	v->dif[6] += rar20_abs(delta + v->d[2]);
	v->dif[7] += rar20_abs(delta - v->d[3]);
	v->dif[8] += rar20_abs(delta + v->d[3]);
	v->dif[9] += rar20_abs(delta - d->chan_delta);
	v->dif[10] += rar20_abs(delta + d->chan_delta);

	d->chan_delta = rar20_int8(ch - v->last_char);
	v->last_delta = d->chan_delta;
	v->last_char = ch;

	if ((v->byte_count & 0x1F) != 0)
		return ((uint8_t)ch);

	num_min_dif = 0;
	min_dif = v->dif[0];
	v->dif[0] = 0;
	for (i = 1; i < 11; i++) {
		if (v->dif[i] < min_dif) {
			min_dif = v->dif[i];
			num_min_dif = i;
		}
		v->dif[i] = 0;
	}
	if (num_min_dif > 0) {
		num_min_dif--;
		i = num_min_dif / 2;
		if (num_min_dif % 2 == 0) {
			if (v->k[i] >= -16)
				v->k[i]--;
		} else if (v->k[i] < 16)
			v->k[i]++;
	}
	return ((uint8_t)ch);
}

static int
audio20_fill(struct rar20_audio *d, struct rar20_bit_reader *br,
    unsigned char *win, size_t mask, int64_t *position, int64_t end)
{
	while (*position < end) {
		int sym, err;

		err = huffman_read_sym(&d->decoders[d->cur_chan], br, &sym);
		if (err != RAR20_OK)
			return (err);
		if (sym == 256)
			return (RAR20_END_OF_BLOCK);
		window_write_byte(win, mask, position,
		    audio20_decode(d, sym));
		d->cur_chan++;
		if (d->cur_chan >= d->chans)
			d->cur_chan = 0;
	}
	return (RAR20_OK);
}

static int
lz20_init(struct rar20_lz *d, struct rar20_bit_reader *br, uint8_t *table)
{
	int err;

	err = read_code_length_table20(br, table,
	    MAIN20_SIZE + OFFSET20_SIZE + LENGTH20_SIZE);
	if (err != RAR20_OK)
		return (err);
	huffman_init(&d->main_decoder, table, MAIN20_SIZE);
	table += MAIN20_SIZE;
	huffman_init(&d->offset_decoder, table, OFFSET20_SIZE);
	table += OFFSET20_SIZE;
	huffman_init(&d->length_decoder, table, LENGTH20_SIZE);
	return (RAR20_OK);
}

static void
lz20_push_offset(struct rar20_lz *d)
{
	d->offset[3] = d->offset[2];
	d->offset[2] = d->offset[1];
	d->offset[1] = d->offset[0];
}

static int
lz20_decode_offset(struct rar20_lz *d, struct rar20_bit_reader *br, int i)
{
	int bits, n, offset, err;

	d->length = length_base[i] + 3;
	bits = length_extra_bits[i];
	if (bits > 0) {
		err = read_bits(br, bits, &n);
		if (err != RAR20_OK)
			return (err);
		d->length += n;
	}

	err = huffman_read_sym(&d->offset_decoder, br, &i);
	if (err != RAR20_OK)
		return (err);
	offset = offset_base[i] + 1;
	bits = offset_extra_bits[i];
	if (bits > 0) {
		err = read_bits(br, bits, &n);
		if (err != RAR20_OK)
			return (err);
		offset += n;
	}

	if (offset >= 0x2000) {
		d->length++;
		if (offset >= 0x40000)
			d->length++;
	}
	lz20_push_offset(d);
	d->offset[0] = offset;
	return (RAR20_OK);
}

static int
lz20_decode_length(struct rar20_lz *d, struct rar20_bit_reader *br, int i)
{
	int offset = d->offset[i];
	int bits, n, err;

	lz20_push_offset(d);
	d->offset[0] = offset;

	err = huffman_read_sym(&d->length_decoder, br, &i);
	if (err != RAR20_OK)
		return (err);
	d->length = length_base[i] + 2;
	bits = length_extra_bits[i];
	if (bits > 0) {
		err = read_bits(br, bits, &n);
		if (err != RAR20_OK)
			return (err);
		d->length += n;
	}
	if (offset >= 0x101) {
		d->length++;
		if (offset >= 0x2000) {
			d->length++;
			if (offset >= 0x40000)
				d->length++;
		}
	}
	return (RAR20_OK);
}

static int
lz20_decode_short_offset(struct rar20_lz *d, struct rar20_bit_reader *br,
    int i)
{
	int offset, bits, n, err;

	lz20_push_offset(d);
	offset = short_offset_base[i] + 1;
	bits = short_offset_extra_bits[i];
	if (bits > 0) {
		err = read_bits(br, bits, &n);
		if (err != RAR20_OK)
			return (err);
		offset += n;
	}
	d->offset[0] = offset;
	d->length = 2;
	return (RAR20_OK);
}

static int
lz20_fill(struct rar20_lz *d, struct rar20_bit_reader *br,
    unsigned char *win, size_t mask, int64_t *position, int64_t end,
    int64_t entry_end)
{
	while (*position < end) {
		int sym, err, length;

		err = huffman_read_sym(&d->main_decoder, br, &sym);
		if (err != RAR20_OK)
			return (err);

		if (sym < 256) {	/* literal */
			window_write_byte(win, mask, position,
			    (unsigned char)sym);
			continue;
		} else if (sym > 269) {
			err = lz20_decode_offset(d, br, sym - 270);
		} else if (sym == 269) {
			return (RAR20_END_OF_BLOCK);
		} else if (sym == 256) {	/* use previous offset and length */
			lz20_push_offset(d);
		} else if (sym < 261) {
			err = lz20_decode_length(d, br, sym - 257);
		} else {
			err = lz20_decode_short_offset(d, br, sym - 261);
		}
		if (err != RAR20_OK)
			return (err);
		length = d->length;
		if (length > entry_end - *position)
			length = (int)(entry_end - *position);
		window_copy_bytes(win, mask, position, length, d->offset[0]);
	}
	return (RAR20_OK);
}

struct rar20_decoder *
rar20_decoder_new(void)
{
	struct rar20_decoder *d = calloc(1, sizeof(*d));

	if (d != NULL)
		audio20_reset(&d->audio);
	return (d);
}

void
rar20_decoder_free(struct rar20_decoder *d)
{
	free(d);
}

void
rar20_decoder_begin_entry(struct rar20_decoder *d, int reset)
{
	bit_reader_reset(&d->br);
	if (reset) {
		d->hdr_read = 0;
		d->is_audio = 0;
		audio20_reset(&d->audio);
		memset(d->code_length, 0, sizeof(d->code_length));
		d->lz.length = 0;
		memset(d->lz.offset, 0, sizeof(d->lz.offset));
	}
}

static int
read_block_header(struct rar20_decoder *d)
{
	int n, err;

	err = read_bits(&d->br, 1, &n);
	if (err != RAR20_OK)
		return (err);
	d->is_audio = n > 0;
	err = read_bits(&d->br, 1, &n);
	if (err != RAR20_OK)
		return (err);
	if (n == 0)
		memset(d->code_length, 0, sizeof(d->code_length));
	if (d->is_audio)
		err = audio20_init(&d->audio, &d->br, d->code_length);
	else
		err = lz20_init(&d->lz, &d->br, d->code_length);
	d->hdr_read = 1;
	return (err);
}

int
rar20_decoder_fill(struct rar20_decoder *d, rar20_byte_fn next_byte,
    void *ctx, unsigned char *win, size_t mask, int64_t *position,
    int64_t end, int64_t entry_end)
{
	d->br.next_byte = next_byte;
	d->br.ctx = ctx;

	while (*position < end) {
		int err;

		if (!d->hdr_read) {
			err = read_block_header(d);
			if (err != RAR20_OK)
				return (err == RAR20_ERR_EOF ?
				    RAR20_ERR_OUT_OF_DATA : err);
		}
		if (d->is_audio)
			err = audio20_fill(&d->audio, &d->br, win, mask,
			    position, end);
		else
			err = lz20_fill(&d->lz, &d->br, win, mask, position,
			    end, entry_end);
		switch (err) {
		case RAR20_OK:
			continue;
		case RAR20_END_OF_BLOCK:
			d->hdr_read = 0;
			continue;
		case RAR20_ERR_EOF:
			return (RAR20_ERR_OUT_OF_DATA);
		default:
			return (err);
		}
	}
	return (RAR20_OK);
}

int
rar20_decoder_read_header(struct rar20_decoder *d, rar20_byte_fn next_byte,
    void *ctx)
{
	int err;

	d->br.next_byte = next_byte;
	d->br.ctx = ctx;
	if (d->hdr_read)
		return (RAR20_OK);
	err = read_block_header(d);
	return (err == RAR20_ERR_EOF ? RAR20_ERR_OUT_OF_DATA : err);
}
