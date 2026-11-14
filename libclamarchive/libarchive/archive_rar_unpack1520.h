/*-
 * Copyright (c) 2026 Mridul Khanal
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

#ifndef ARCHIVE_RAR_UNPACK1520_H_INCLUDED
#define ARCHIVE_RAR_UNPACK1520_H_INCLUDED

#ifndef __LIBARCHIVE_BUILD
#error This header is only to be used internally to libarchive.
#endif

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

/*
 * Decompression of the RAR 1.5 and RAR 2.0 methods (unpack versions 15,
 * 20 and 26, the latter being RAR 2.0 with large files), including the
 * RAR 2.0 multimedia (audio) blocks.
 *
 * The decoder pulls packed data through a callback and keeps its window,
 * tables and adaptive state between entries, so a solid entry continues
 * where the previous one stopped.
 */

struct rar_unpack1520;

/*
 * Provides the next chunk of the entry's packed data, at most `want`
 * bytes. Set *avail to 0 at the end of the packed data. Returns 0, or a
 * negative value on an I/O error. The decoder copies the chunk before
 * calling again.
 */
typedef int (*rar_unpack1520_read_cb)(void *ctx, size_t want,
    const uint8_t **buf, size_t *avail);

/* Results of rar_unpack1520_read() besides a byte count. */
#define RAR_UNPACK1520_DONE		0	/* entry complete */
#define RAR_UNPACK1520_CORRUPT		(-1)	/* stopped on corrupt data */
#define RAR_UNPACK1520_TRUNCATED	(-2)	/* packed data ran out */
#define RAR_UNPACK1520_EIO		(-3)	/* callback failed */
#define RAR_UNPACK1520_ENOMEM		(-4)

struct rar_unpack1520 *rar_unpack1520_new(void);
void rar_unpack1520_free(struct rar_unpack1520 *);

/*
 * Starts an entry. unp_ver 13 to 15 selects RAR 1.5 and 20 or 26 RAR 2.0;
 * the versions between them decode to nothing, as with unRAR. When solid
 * is nonzero the window, tables and adaptive state of the previous entry
 * are kept. Returns 0, or RAR_UNPACK1520_CORRUPT for a version outside
 * 13 to 28.
 */
int rar_unpack1520_begin(struct rar_unpack1520 *, int unp_ver, int solid,
    uint64_t unpacked_size);

/*
 * Decodes up to out_size bytes. Returns the number of bytes produced
 * (> 0), RAR_UNPACK1520_DONE once all of unpacked_size has been returned,
 * or a negative result. The data decoded before a negative result has
 * already been returned by earlier calls; after a negative result every
 * further call returns the same result.
 */
ssize_t rar_unpack1520_read(struct rar_unpack1520 *, uint8_t *out,
    size_t out_size, rar_unpack1520_read_cb, void *ctx);

#endif
