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
 * RAR 2.0 and 2.6 (unpack versions 20 and 26) decoder, a C port of the
 * decoder in github.com/nwaples/rardecode (decode20.go, decode20_lz.go,
 * decode20_audio.go, huffman.go, bit_reader.go), commit
 * f557bc97578a96c9196330d7ba642a8599a2ebd6.
 */

#ifndef ARCHIVE_RAR_UNPACK20_H_INCLUDED
#define ARCHIVE_RAR_UNPACK20_H_INCLUDED

#include <stddef.h>
#include <stdint.h>

#define RAR20_OK		0
#define RAR20_ERR_EOF		(-1)	/* the input has no more bytes */
#define RAR20_ERR_HUFF_DECODE	(-2)
#define RAR20_ERR_LENGTH_TABLE	(-3)
#define RAR20_ERR_OUT_OF_DATA	(-4)	/* the input ended inside the entry */
#define RAR20_END_OF_BLOCK	(-5)

/* Returns the next input byte, or -1 when there is none. */
typedef int (*rar20_byte_fn)(void *ctx);

struct rar20_decoder;

struct rar20_decoder *rar20_decoder_new(void);
void rar20_decoder_free(struct rar20_decoder *);

/*
 * Prepares the decoder for the data of a new entry. The bit reader starts
 * at a byte boundary of that data. With reset set, the block, the code
 * length tables and the audio state start empty; without it (the next entry
 * of a solid stream) they carry over from the previous entry.
 */
void rar20_decoder_begin_entry(struct rar20_decoder *, int reset);

/*
 * Decodes into the window (win, with size mask + 1, a power of two) from
 * *position until *position >= end. A match is cut at entry_end, the end of
 * the entry's output. Returns RAR20_OK or a negative RAR20_ERR_* code.
 */
int rar20_decoder_fill(struct rar20_decoder *, rar20_byte_fn next_byte,
    void *ctx, unsigned char *win, size_t mask, int64_t *position,
    int64_t end, int64_t entry_end);

/*
 * Reads the header and tables of the block the entry's data starts with, if
 * it starts one. An entry with no output (an empty file) can carry them for
 * the next entry of a solid stream. Returns RAR20_OK or a negative
 * RAR20_ERR_* code.
 */
int rar20_decoder_read_header(struct rar20_decoder *, rar20_byte_fn next_byte,
    void *ctx);

#endif
