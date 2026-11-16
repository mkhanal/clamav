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

/*
 * RAR details that libarchive's generic archive_entry does not carry:
 * the raw header fields of the current entry and the archive comment.
 * Used by ClamAV's libclamunrar_iface; not part of libarchive's API.
 */

#ifndef ARCHIVE_READ_RAR_INFO_H_INCLUDED
#define ARCHIVE_READ_RAR_INFO_H_INCLUDED

#include <stddef.h>
#include <stdint.h>

struct archive;
struct archive_read;

#define ARCHIVE_RAR_INFO_FORMAT_RAR4 4
#define ARCHIVE_RAR_INFO_FORMAT_RAR5 5

struct archive_rar_entry_info {
	int		format;		/* ARCHIVE_RAR_INFO_FORMAT_* */
	uint64_t	packed_size;	/* Data size in this volume. */
	uint64_t	unpacked_size;
	int		unpacked_size_unknown;
	uint32_t	crc32;		/* Stored data CRC32. */
	int		crc32_present;
	uint8_t		blake2sp[32];	/* RAR5 BLAKE2sp data hash. */
	int		blake2sp_present;
	unsigned	method;		/* RAR4: method byte 0x30-0x35.
					 * RAR5: compression method 0-5. */
	unsigned	unp_ver;	/* RAR4: unpack version.
					 * RAR5: algorithm version 0 or 1. */
	unsigned	host_os;
	unsigned	flags;		/* RAR4 file header flags. */
	uint64_t	attributes;
	int		is_dir;
	int		is_encrypted;	/* Data is encrypted. */
	int		is_solid;	/* Data continues the previous one. */
	int		split_before;
	int		split_after;
	int		redir_type;	/* RAR5 redirection, RAR4 Unix symlink
					 * (ARCHIVE_RAR_REDIR_*). */
	const char	*name;		/* The name field as stored. */
	size_t		name_size;
};

#define ARCHIVE_RAR_REDIR_NONE		0
#define ARCHIVE_RAR_REDIR_UNIX_SYMLINK	1
#define ARCHIVE_RAR_REDIR_WIN_SYMLINK	2
#define ARCHIVE_RAR_REDIR_JUNCTION	3
#define ARCHIVE_RAR_REDIR_HARDLINK	4
#define ARCHIVE_RAR_REDIR_FILECOPY	5

struct archive_rar_comment_info {
	int		present;
	int		format;		/* ARCHIVE_RAR_INFO_FORMAT_* */
	int		in_main_header;	/* RAR 1.5-2.x comment block. */
	unsigned	method;		/* As archive_rar_entry_info. */
	unsigned	unp_ver;
	uint64_t	unpacked_size;
	uint32_t	crc;		/* CMT block: CRC32 of the unpacked
					 * data. Main header block: low 16
					 * bits of that CRC32. */
	int		crc_present;
	uint64_t	sub_flags;	/* RAR4 CMT block sub flags. */
	int		is_encrypted;
	const void	*data;		/* Packed comment data. */
	size_t		size;
	uint64_t	packed_size;	/* Declared packed size; larger than
					 * size when the data was truncated. */
};

/* Valid after archive_read_next_header() returned a RAR or RAR5 entry. */
int archive_read_rar_entry_info(struct archive *,
    struct archive_rar_entry_info *);

/*
 * The first archive comment the reader has passed so far. RAR writes it
 * before the first file, so it is known after the first
 * archive_read_next_header() call.
 */
int archive_read_rar_comment_info(struct archive *,
    struct archive_rar_comment_info *);

/*
 * True when a main or file header read so far failed its CRC. The reader goes
 * on past it, as unRAR does, and unRAR reports an error once it has read to
 * the end of such an archive.
 */
int archive_read_rar_header_damaged(struct archive *);

/*
 * Skipping an entry of a solid archive means decoding it, because the
 * entries after it continue its stream. archive_read_rar_skip_data() skips
 * the current entry's data like archive_read_data_skip(), but gives up with
 * ARCHIVE_FATAL and the errno ARCHIVE_RAR_ERRNO_SKIP_LIMIT once the data
 * decoded for it exceeds *budget bytes (when budget is not NULL; the bytes
 * decoded are taken off it) or stop(stop_ctx) returns non-zero (when stop is
 * not NULL; it is called before every block). Skipping that decodes nothing
 * is not limited.
 */
struct archive_rar_skip_limit {
	uint64_t	*budget;
	int		(*stop)(void *);
	void		*stop_ctx;
};

#define ARCHIVE_RAR_ERRNO_SKIP_LIMIT	0x5201

/* The entry's data uses a compression method that is not available. */
#define ARCHIVE_RAR_ERRNO_UNSUPPORTED	0x5202

/* The data was read, but its CRC32 or BLAKE2sp does not match the header. */
#define ARCHIVE_RAR_ERRNO_CHECKSUM	0x5203

/* The window the entry needs cannot be had: too large to address, or no
 * memory or temporary space to back it. */
#define ARCHIVE_RAR_ERRNO_WINDOW	0x5204

int archive_read_rar_skip_data(struct archive *,
    const struct archive_rar_skip_limit *);

/* Shared by both readers: true when `consumed` more bytes break the limit. */
int __archive_rar_skip_limit_hit(struct archive_read *,
    const struct archive_rar_skip_limit *, uint64_t consumed);

/* The RAR5 reader's half of archive_read_rar_skip_data(). */
int __archive_read_rar5_skip_data(struct archive *,
    const struct archive_rar_skip_limit *);

/*
 * Tell the reader the most bytes the caller will take from the archive (0:
 * no limit). A RAR5 window is sized to what its entries can write, so one
 * larger than this is never allocated. Ignored by the RAR 2.9 reader.
 */
int archive_read_rar_set_output_bound(struct archive *, uint64_t);

/* The RAR5 reader's half of archive_read_rar_set_output_bound(). */
int __archive_read_rar5_set_output_bound(struct archive *, uint64_t);

/*
 * Tell the reader the directory for the unnamed temporary file that backs a
 * decompression window above RAR_WINDOW_FILE_THRESHOLD (archive_rar_window.h);
 * NULL keeps every window in anonymous memory. Call after opening, before
 * reading entry data.
 */
int archive_read_rar_set_window_dir(struct archive *, const char *);

/* The RAR5 reader's half of archive_read_rar_set_window_dir(). */
int __archive_read_rar5_set_window_dir(struct archive *, const char *);

/* Receives how each large window was backed, and why a way failed. */
void __archive_rar_window_set_logger(void (*)(const char *));

/* CRC32 as RAR uses it for data and header checksums. */
uint32_t archive_rar_crc32(const void *, size_t);

/* Shared by both readers: unRAR's search for a self-extracting archive. */
struct archive_read;
int64_t __archive_rar_find_signature(struct archive_read *, int *);

/* The RAR5 reader's halves of the two functions above. */
int __archive_read_rar5_entry_info(struct archive *,
    struct archive_rar_entry_info *);
int __archive_read_rar5_comment_info(struct archive *,
    struct archive_rar_comment_info *);
int __archive_read_rar5_header_damaged(struct archive *);

/* Largest comment block, packed, the readers keep. */
#define ARCHIVE_RAR_COMMENT_MAX (16 * 1024 * 1024)

#endif /* ARCHIVE_READ_RAR_INFO_H_INCLUDED */
