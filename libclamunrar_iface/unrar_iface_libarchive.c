/*
 * libclamunrar_iface backed by libarchive instead of RARLAB unRAR.
 *
 * Copyright (C) 2026 Mridul Khanal. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice,
 * this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 * this list of conditions and the following disclaimer in the documentation
 * and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its contributors
 * may be used to endorse or promote products derived from this software without
 * specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

/*
 * The five unrar_iface functions, implemented with the vendored libarchive.
 *
 * libclamav drives them exactly as it drives the RARLAB implementation in
 * unrar_iface.cpp, so this file reproduces what that implementation returns
 * for every input: the same open, header, extract and skip results, the same
 * metadata (names converted the way unRAR converts them, sizes, CRC, method,
 * flags), the archive comment as unRAR hands it over, and the same handling of
 * volumes, links, encryption and damaged data.
 */

#if HAVE_CONFIG_H
#include "clamav-config.h"
#endif

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <wchar.h>

#ifdef HAVE_UNISTD_H
#include <unistd.h>
#endif

#ifdef _WIN32
#include <io.h>
#endif

#include <archive.h>
#include <archive_entry.h>
#include "archive_read_rar_info.h"

#include "unrar_iface.h"

#ifndef O_BINARY
#define O_BINARY 0
#endif

/* The size of the comment buffer unrar_iface.cpp hands to unRAR. */
#define UNRAR_COMMENT_BUFFER_SIZE (64 * 1024)

/* Names reach libclamav through a 1024 byte field, terminator included. */
#define UNRAR_NAME_BUFFER_SIZE 1024

/* unRAR reads comments of at most this many unpacked bytes. */
#define UNRAR_COMMENT_MAX_UNPACKED (16 * 1024 * 1024)

/* unRAR looks this far into a file for the RAR signature. */
#define UNRAR_SFX_SEARCH_SIZE (4 * 1024 * 1024)

#define RAR4_MAIN_VOLUME 0x0001
#define RAR4_MAIN_NEW_NUMBERING 0x0010
#define RAR4_FILE_UNICODE 0x0200
#define RAR4_CMT_UNICODE 0x0001
#define RAR4_HOST_WINDOWS_MAX 2
#define RAR5_HOST_WINDOWS 0
#define RAR4_METHOD_STORE 0x30
#define RAR4_UNPACK_VERSION_MAX 36
#define RAR5_UNPACK_VERSION_MAX 1
#define RAR_METHOD_INDEX_MAX 5

#define VOLUMES_MAX 100000

static uint8_t unrar_debug = 0;

static void unrar_dbgmsg(const char *str, ...)
{
    va_list ap;

    if (!unrar_debug) {
        return;
    }
    va_start(ap, str);
    vfprintf(stderr, str, ap);
    va_end(ap);
}

typedef enum header_state_tag {
    HEADER_NONE = 0, /* No header read since the last extract or skip. */
    HEADER_READY,    /* A header was read and not yet consumed. */
    HEADER_DONE      /* The reader has stopped; status says why. */
} header_state_t;

typedef struct unrar_handle_tag {
    struct archive *archive;
    struct archive_entry *entry;
    header_state_t state;
    cl_unrar_error_t status; /* For HEADER_DONE and for a failed header read. */
    char **volumes;
    size_t volume_count;
    uint32_t rar5_hash32; /* unRAR's RAR5 hash field keeps its last value. */
} unrar_handle_t;

/*
 * Volume names, as unRAR derives the next volume's name from the current one.
 */

static int is_digit(char c)
{
    return c >= '0' && c <= '9';
}

static const char *base_name(const char *path)
{
    const char *base = path;
    const char *p;

    for (p = path; *p != '\0'; p++) {
        if (*p == '/'
#ifdef _WIN32
            || *p == '\\' || *p == ':'
#endif
        ) {
            base = p + 1;
        }
    }
    return base;
}

static char *extension(char *path)
{
    char *base = (char *)base_name(path);
    return strrchr(base, '.');
}

static int ext_is(const char *ext, const char *want)
{
    size_t i;

    for (i = 0; ext[i] != '\0' && want[i] != '\0'; i++) {
        char c = ext[i];
        if (c >= 'A' && c <= 'Z') {
            c = (char)(c - 'A' + 'a');
        }
        if (c != want[i]) {
            return 0;
        }
    }
    return ext[i] == '\0' && want[i] == '\0';
}

/* Points to the digit that numbers a "name.partN.rar" style volume. */
static char *volume_number_digit(char *path)
{
    char *name = (char *)base_name(path);
    char *last;
    char *num;
    char *dot;

    if (*name == '\0') {
        return name;
    }
    last = name + strlen(name) - 1;
    while (!is_digit(*last) && last > name) {
        last--;
    }
    num = last;
    while (is_digit(*num) && num > name) {
        num--;
    }
    while (num > name && *num != '.') {
        if (is_digit(*num)) {
            dot = strchr(name, '.');
            if (dot != NULL && dot < num) {
                last = num;
            }
            break;
        }
        num--;
    }
    return last;
}

/* Returns a new string with the name of the volume after path, or NULL. */
static char *next_volume_name(const char *path, int new_numbering)
{
    size_t len = strlen(path);
    char *next = malloc(len + 8);
    char *ext;
    char *digit;

    if (next == NULL) {
        return NULL;
    }
    memcpy(next, path, len + 1);

    ext = extension(next);
    if (ext == NULL) {
        strcat(next, ".rar");
        ext = extension(next);
    } else if (ext[1] == '\0' || ext_is(ext, ".exe") || ext_is(ext, ".sfx")) {
        strcpy(ext, ".rar");
    }

    if (new_numbering) {
        digit = volume_number_digit(next);
        for (;;) {
            (*digit)++;
            if (*digit != '9' + 1) {
                break;
            }
            *digit = '0';
            if (digit == next || !is_digit(*(digit - 1))) {
                /* "name.part9.rar" becomes "name.part10.rar". */
                memmove(digit + 1, digit, strlen(digit) + 1);
                *digit = '1';
                break;
            }
            digit--;
        }
    } else if (!is_digit(ext[2]) || !is_digit(ext[3])) {
        /* "name.rar" becomes "name.r00". */
        strcpy(ext + 2, "00");
    } else {
        digit = ext + strlen(ext) - 1;
        for (;;) {
            (*digit)++;
            if (*digit != '9' + 1) {
                break;
            }
            if (digit <= next || *(digit - 1) == '.') {
                *digit = 'a';
                break;
            }
            *digit = '0';
            digit--;
        }
    }
    return next;
}

static int file_exists(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0 && !S_ISDIR(st.st_mode);
}

static void free_volumes(unrar_handle_t *h)
{
    size_t i;

    for (i = 0; i < h->volume_count; i++) {
        free(h->volumes[i]);
    }
    free(h->volumes);
    h->volumes      = NULL;
    h->volume_count = 0;
}

/* A RAR5 variable-length integer. */
static int read_vint(const unsigned char *buf, size_t len, size_t *pos, uint64_t *value)
{
    int shift = 0;

    *value = 0;
    while (*pos < len && shift < 64) {
        unsigned char b = buf[(*pos)++];
        *value |= (uint64_t)(b & 0x7f) << shift;
        if (!(b & 0x80)) {
            return 1;
        }
        shift += 7;
    }
    return 0;
}

/*
 * Reads the main archive header to learn whether the archive is a volume and
 * how its volumes are numbered.
 */
static void read_volume_flags(const char *filename, int *is_volume, int *new_numbering)
{
    static const unsigned char sig[6] = {'R', 'a', 'r', '!', 0x1a, 0x07};
    unsigned char *buf                = NULL;
    size_t len                        = 0;
    size_t i;
    FILE *f;

    *is_volume     = 0;
    *new_numbering = 0;

    if ((f = fopen(filename, "rb")) == NULL) {
        return;
    }
    if ((buf = malloc(UNRAR_SFX_SEARCH_SIZE + 64)) != NULL) {
        len = fread(buf, 1, UNRAR_SFX_SEARCH_SIZE + 64, f);
    }
    fclose(f);
    if (buf == NULL) {
        return;
    }

    for (i = 0; i + 8 <= len && i <= UNRAR_SFX_SEARCH_SIZE; i++) {
        if (memcmp(buf + i, sig, sizeof(sig)) != 0) {
            continue;
        }
        if (buf[i + 6] == 0x00 && i + 7 + 7 <= len && buf[i + 7 + 2] == 0x73) {
            unsigned flags = buf[i + 7 + 3] | (buf[i + 7 + 4] << 8);
            *is_volume     = (flags & RAR4_MAIN_VOLUME) != 0;
            *new_numbering = (flags & RAR4_MAIN_NEW_NUMBERING) != 0;
            break;
        }
        if (buf[i + 6] == 0x01 && i + 8 <= len && buf[i + 7] == 0x00) {
            /* RAR5 main header: CRC32, size, type, flags, [extra size],
             * [data size], archive flags. Volumes are always numbered the
             * new way. */
            size_t p      = i + 8 + 4;
            uint64_t size = 0, type = 0, hflags = 0, skip = 0, aflags = 0;
            int ok = read_vint(buf, len, &p, &size) &&
                     read_vint(buf, len, &p, &type) &&
                     read_vint(buf, len, &p, &hflags) &&
                     (!(hflags & 0x0001) || read_vint(buf, len, &p, &skip)) &&
                     (!(hflags & 0x0002) || read_vint(buf, len, &p, &skip)) &&
                     read_vint(buf, len, &p, &aflags);
            if (ok && type == 1) {
                *is_volume = (aflags & 0x0001) != 0;
            }
            *new_numbering = 1;
            break;
        }
    }
    free(buf);
}

static cl_unrar_error_t collect_volumes(unrar_handle_t *h, const char *filename)
{
    int is_volume     = 0;
    int new_numbering = 0;
    size_t allocated  = 4;

    h->volumes = calloc(allocated, sizeof(char *));
    if (h->volumes == NULL) {
        return UNRAR_EMEM;
    }
    if ((h->volumes[0] = strdup(filename)) == NULL) {
        return UNRAR_EMEM;
    }
    h->volume_count = 1;

    read_volume_flags(filename, &is_volume, &new_numbering);
    if (!is_volume) {
        return UNRAR_OK;
    }

    while (h->volume_count < VOLUMES_MAX) {
        char *next = next_volume_name(h->volumes[h->volume_count - 1], new_numbering);
        if (next == NULL) {
            return UNRAR_EMEM;
        }
        if (!file_exists(next)) {
            free(next);
            break;
        }
        if (h->volume_count + 1 >= allocated) {
            char **grown = realloc(h->volumes, allocated * 2 * sizeof(char *));
            if (grown == NULL) {
                free(next);
                return UNRAR_EMEM;
            }
            memset(grown + allocated, 0, allocated * sizeof(char *));
            h->volumes = grown;
            allocated *= 2;
        }
        h->volumes[h->volume_count++] = next;
    }
    unrar_dbgmsg("unrar_open: %zu volume(s) found.\n", h->volume_count);
    return UNRAR_OK;
}

/*
 * Text conversion, as unRAR converts names and comments for its char API.
 */

/*
 * Bytes that are not valid text in the locale travel through unRAR's wide
 * strings as U+E080..U+E0FF, marked by a U+FFFE somewhere in the string.
 */
#define MAP_AREA_START 0xE000
#define MAPPED_STRING_MARK 0xFFFE

/* The mapped form back to bytes; other characters to the locale, '_' if not. */
static void wide_to_char_mapped(const wchar_t *src, char *dest, size_t dest_size)
{
    size_t in  = 0;
    size_t out = 0;

    memset(dest, 0, dest_size);
    while (src[in] != 0 && out + MB_CUR_MAX < dest_size) {
        unsigned c = (unsigned)src[in];
        if (c == MAPPED_STRING_MARK) {
            in++;
            continue;
        }
        if (c >= MAP_AREA_START + 0x80 && c < MAP_AREA_START + 0x100) {
            dest[out++] = (char)(c - MAP_AREA_START);
            in++;
        } else {
            mbstate_t ps;
            int len;
            memset(&ps, 0, sizeof(ps));
            if (wcrtomb(dest + out, src[in], &ps) == (size_t)-1) {
                dest[out] = '_';
            }
            in++;
            memset(&ps, 0, sizeof(ps));
            len = (int)mbrlen(dest + out, MB_CUR_MAX, &ps);
            out += len > 1 ? (size_t)len : 1;
        }
    }
    dest[out < dest_size ? out : dest_size - 1] = '\0';
}

/* As unRAR's WideToChar(): on an unconvertible character keep what precedes it. */
static void wide_to_char(const wchar_t *src, char *dest, size_t dest_size)
{
    mbstate_t ps;
    const wchar_t *s = src;
    size_t n;

    if (dest_size == 0) {
        return;
    }
    if (wcschr(src, (wchar_t)MAPPED_STRING_MARK) != NULL) {
        wide_to_char_mapped(src, dest, dest_size);
        return;
    }
    memset(dest, 0, dest_size);
    memset(&ps, 0, sizeof(ps));
    n = wcsrtombs(dest, &s, dest_size, &ps);
    if (n == (size_t)-1 && errno == EILSEQ) {
        memset(&ps, 0, sizeof(ps));
        s = src;
        memset(dest, 0, dest_size);
        (void)wcsrtombs(dest, &s, dest_size, &ps);
    }
    dest[dest_size - 1] = '\0';
}

/* As unRAR's CharToWide(): bytes the locale cannot read are mapped. */
static wchar_t *char_to_wide(const char *src)
{
    size_t size = strlen(src) + 2;
    wchar_t *w  = calloc(size, sizeof(wchar_t));
    mbstate_t ps;
    const char *s = src;
    size_t n;
    size_t in = 0, out = 0;
    int marked = 0;

    if (w == NULL) {
        return NULL;
    }
    memset(&ps, 0, sizeof(ps));
    n = mbsrtowcs(w, &s, size, &ps);
    if (n != (size_t)-1 && !(n == 0 && *src != '\0')) {
        return w;
    }
    memset(w, 0, size * sizeof(wchar_t));
    while (out < size - 1 && src[in] != '\0') {
        size_t res;
        memset(&ps, 0, sizeof(ps));
        res = mbrtowc(&w[out], src + in, MB_CUR_MAX, &ps);
        if (res == (size_t)-1 || res == (size_t)-2) {
            if ((unsigned char)src[in] < 0x80) {
                break;
            }
            if (!marked) {
                w[out++] = (wchar_t)MAPPED_STRING_MARK;
                marked   = 1;
                if (out >= size - 1) {
                    break;
                }
            }
            w[out++] = (wchar_t)((unsigned char)src[in++] + MAP_AREA_START);
        } else {
            int len;
            memset(&ps, 0, sizeof(ps));
            len = (int)mbrlen(src + in, MB_CUR_MAX, &ps);
            in += len > 1 ? (size_t)len : 1;
            out++;
        }
    }
    w[out] = 0;
    return w;
}

/* Converts locale text the way unRAR's CharToWide followed by WideToChar does. */
static void char_to_char(const char *src, char *dest, size_t dest_size)
{
    wchar_t *w = char_to_wide(src);

    if (dest_size == 0) {
        return;
    }
    if (w == NULL) {
        dest[0] = '\0';
        return;
    }
    wide_to_char(w, dest, dest_size);
    free(w);
}

/* Decodes UTF-8 up to the first invalid sequence. */
static wchar_t *utf8_to_wide(const char *src, size_t size)
{
    wchar_t *w = calloc(size + 1, sizeof(wchar_t));
    size_t i   = 0;
    size_t o   = 0;

    if (w == NULL) {
        return NULL;
    }
    while (i < size && src[i] != '\0') {
        unsigned c = (unsigned char)src[i++];
        unsigned d;
        if (c < 0x80) {
            d = c;
        } else if ((c >> 5) == 6) {
            if (i + 1 > size || ((unsigned char)src[i] & 0xc0) != 0x80) {
                break;
            }
            d = ((c & 0x1f) << 6) | ((unsigned char)src[i] & 0x3f);
            i += 1;
        } else if ((c >> 4) == 14) {
            if (i + 2 > size || ((unsigned char)src[i] & 0xc0) != 0x80 ||
                ((unsigned char)src[i + 1] & 0xc0) != 0x80) {
                break;
            }
            d = ((c & 0xf) << 12) | (((unsigned char)src[i] & 0x3f) << 6) |
                ((unsigned char)src[i + 1] & 0x3f);
            i += 2;
        } else if ((c >> 3) == 30) {
            if (i + 3 > size || ((unsigned char)src[i] & 0xc0) != 0x80 ||
                ((unsigned char)src[i + 1] & 0xc0) != 0x80 ||
                ((unsigned char)src[i + 2] & 0xc0) != 0x80) {
                break;
            }
            d = ((c & 7) << 18) | (((unsigned char)src[i] & 0x3f) << 12) |
                (((unsigned char)src[i + 1] & 0x3f) << 6) | ((unsigned char)src[i + 2] & 0x3f);
            i += 3;
            if (d > 0x10ffff) {
                continue;
            }
        } else {
            break;
        }
        if (sizeof(wchar_t) == 2 && d > 0xffff) {
            w[o++] = (wchar_t)(((d - 0x10000) >> 10) + 0xd800);
            w[o++] = (wchar_t)(((d - 0x10000) & 0x3ff) + 0xdc00);
        } else {
            w[o++] = (wchar_t)d;
        }
    }
    w[o] = 0;
    return w;
}

/*
 * A RAR 3.x Unicode name: the OEM name, a NUL, then the Unicode form packed
 * against the OEM bytes.
 */
static wchar_t *rar4_unicode_name(const unsigned char *name, size_t size)
{
    size_t oem_len           = strnlen((const char *)name, size);
    const unsigned char *enc = name + oem_len + 1;
    size_t enc_size          = size - oem_len - 1;
    size_t max               = size * 2 + 1;
    wchar_t *w               = calloc(max + 1, sizeof(wchar_t));
    size_t in                = 0;
    size_t out               = 0;
    unsigned high;
    unsigned flags     = 0;
    unsigned flag_bits = 0;

    if (w == NULL) {
        return NULL;
    }
    if (enc_size == 0) {
        return w;
    }
    high = enc[in++];
    while (in < enc_size && out < max) {
        if (flag_bits == 0) {
            flags     = enc[in++];
            flag_bits = 8;
        }
        switch (flags >> 6) {
            case 0:
                if (in >= enc_size) {
                    goto done;
                }
                w[out++] = enc[in++];
                break;
            case 1:
                if (in >= enc_size) {
                    goto done;
                }
                w[out++] = (wchar_t)(enc[in++] + (high << 8));
                break;
            case 2:
                if (in + 1 >= enc_size) {
                    goto done;
                }
                w[out++] = (wchar_t)(enc[in] + (enc[in + 1] << 8));
                in += 2;
                break;
            case 3: {
                unsigned length;
                if (in >= enc_size) {
                    goto done;
                }
                length = enc[in++];
                if (length & 0x80) {
                    unsigned correction;
                    if (in >= enc_size) {
                        goto done;
                    }
                    correction = enc[in++];
                    for (length = (length & 0x7f) + 2; length > 0 && out < max && out < size; length--, out++) {
                        w[out] = (wchar_t)(((name[out] + correction) & 0xff) + (high << 8));
                    }
                } else {
                    for (length += 2; length > 0 && out < max && out < size; length--, out++) {
                        w[out] = name[out];
                    }
                }
                break;
            }
        }
        flags = (flags << 2) & 0xff;
        flag_bits -= 2;
    }
done:
    if (out > max) {
        out = max;
    }
    w[out] = 0;
    return w;
}

static void convert_name(const struct archive_rar_entry_info *info, char *dest, size_t dest_size)
{
    wchar_t *w = NULL;
    char *raw;
    size_t i;

    dest[0] = '\0';
    if (info->name == NULL) {
        return;
    }

    if (info->format == ARCHIVE_RAR_INFO_FORMAT_RAR4 && !(info->flags & RAR4_FILE_UNICODE)) {
        if ((raw = malloc(info->name_size + 1)) == NULL) {
            return;
        }
        memcpy(raw, info->name, info->name_size);
        raw[info->name_size] = '\0';
        for (i = 0; raw[i] != '\0'; i++) {
            if (raw[i] == '\\') {
                raw[i] = '/';
            }
        }
        char_to_char(raw, dest, dest_size);
        free(raw);
        return;
    }

    if (info->format == ARCHIVE_RAR_INFO_FORMAT_RAR4 &&
        strnlen(info->name, info->name_size) < info->name_size) {
        w = rar4_unicode_name((const unsigned char *)info->name, info->name_size);
    } else {
        w = utf8_to_wide(info->name, info->name_size);
    }
    if (w == NULL) {
        return;
    }
    for (i = 0; w[i] != 0; i++) {
        if (info->format == ARCHIVE_RAR_INFO_FORMAT_RAR5) {
#ifdef _WIN32
            if (w[i] == L'\\' || w[i] == L':') {
                w[i] = L'_';
            }
#else
            if (w[i] == L'\\' && info->host_os == RAR5_HOST_WINDOWS) {
                w[i] = L'_';
            }
#endif
        } else if (w[i] == L'\\') {
            w[i] = L'/';
        }
    }
    wide_to_char(w, dest, dest_size);
    free(w);
}

/*
 * Archive comment.
 */

/* Unpacks a compressed comment with a one-entry archive made around it. */
static unsigned char *unpack_comment(const struct archive_rar_comment_info *cmt, size_t *out_size)
{
    unsigned char *arc = NULL;
    unsigned char *out = NULL;
    struct archive *a  = NULL;
    struct archive_entry *e;
    size_t arc_size, pos, have = 0;
    uint64_t want                             = cmt->unpacked_size;
    uint32_t crc                              = cmt->in_main_header ? 0 : cmt->crc;
    static const unsigned char rar4_marker[7] = {0x52, 0x61, 0x72, 0x21, 0x1a, 0x07, 0x00};
    static const unsigned char rar4_main[13]  = {0, 0, 0x73, 0, 0, 13, 0, 0, 0, 0, 0, 0, 0};
    unsigned char file_head[7 + 25 + 3];
    unsigned long hcrc;

    *out_size = 0;
    if (cmt->format != ARCHIVE_RAR_INFO_FORMAT_RAR4 || cmt->size > UINT32_MAX - 64) {
        return NULL;
    }

    /* Marker, main header, a file header named "CMT", the data. */
    arc_size = sizeof(rar4_marker) + sizeof(rar4_main) + sizeof(file_head) + cmt->size;
    if ((arc = calloc(1, arc_size)) == NULL || (out = malloc(want + 1)) == NULL) {
        goto done;
    }
    pos = 0;
    memcpy(arc + pos, rar4_marker, sizeof(rar4_marker));
    pos += sizeof(rar4_marker);
    memcpy(arc + pos, rar4_main, sizeof(rar4_main));
    pos += sizeof(rar4_main);

    memset(file_head, 0, sizeof(file_head));
    file_head[2]  = 0x74;
    file_head[3]  = 0x00;
    file_head[4]  = 0x80; /* Header flags 0x8000: data size follows. */
    file_head[5]  = (unsigned char)(sizeof(file_head) & 0xff);
    file_head[6]  = (unsigned char)(sizeof(file_head) >> 8);
    file_head[7]  = (unsigned char)(cmt->size);
    file_head[8]  = (unsigned char)(cmt->size >> 8);
    file_head[9]  = (unsigned char)(cmt->size >> 16);
    file_head[10] = (unsigned char)(cmt->size >> 24);
    file_head[11] = (unsigned char)(want);
    file_head[12] = (unsigned char)(want >> 8);
    file_head[13] = (unsigned char)(want >> 16);
    file_head[14] = (unsigned char)(want >> 24);
    file_head[15] = 2; /* Host OS: Windows. */
    file_head[16] = (unsigned char)(crc);
    file_head[17] = (unsigned char)(crc >> 8);
    file_head[18] = (unsigned char)(crc >> 16);
    file_head[19] = (unsigned char)(crc >> 24);
    file_head[24] = (unsigned char)cmt->unp_ver;
    file_head[25] = (unsigned char)cmt->method;
    file_head[26] = 3;
    file_head[27] = 0;
    file_head[28] = 0x20; /* Archive attribute. */
    memcpy(file_head + 32, "CMT", 3);
    /* Dictionary bits stay 0: 64 KB, as unRAR uses for comments. */
    hcrc         = archive_rar_crc32(file_head + 2, sizeof(file_head) - 2);
    file_head[0] = (unsigned char)(hcrc & 0xff);
    file_head[1] = (unsigned char)((hcrc >> 8) & 0xff);
    memcpy(arc + pos, file_head, sizeof(file_head));
    pos += sizeof(file_head);
    memcpy(arc + pos, cmt->data, cmt->size);
    pos += cmt->size;

    hcrc   = archive_rar_crc32(arc + 7 + 2, sizeof(rar4_main) - 2);
    arc[7] = (unsigned char)(hcrc & 0xff);
    arc[8] = (unsigned char)((hcrc >> 8) & 0xff);

    if ((a = archive_read_new()) == NULL ||
        archive_read_support_format_rar(a) != ARCHIVE_OK ||
        archive_read_open_memory(a, arc, pos) != ARCHIVE_OK ||
        archive_read_next_header(a, &e) < ARCHIVE_WARN) {
        goto done;
    }
    while (have < want) {
        la_ssize_t n = archive_read_data(a, out + have, (size_t)(want - have));
        if (n <= 0) {
            break;
        }
        have += (size_t)n;
    }
    *out_size = have;

done:
    if (a != NULL) {
        archive_read_free(a);
    }
    free(arc);
    if (have == 0 && want != 0) {
        free(out);
        out = NULL;
    }
    return out;
}

/*
 * Produces the comment exactly as unRAR's RAROpenArchiveEx() fills the comment
 * buffer: converted to the locale, cut at 64 KB, NUL terminated, with
 * comment_size counting the terminator.
 */
static void read_comment(struct archive *a, char **comment, uint32_t *comment_size)
{
    struct archive_rar_comment_info cmt;
    unsigned char *data = NULL;
    size_t size         = 0;
    wchar_t *w          = NULL;
    char *text          = NULL;
    size_t text_size;
    size_t len;
    unsigned method_index;

    if (archive_read_rar_comment_info(a, &cmt) != ARCHIVE_OK || !cmt.present) {
        unrar_dbgmsg("unrar_open: Comments are not present in this archive.\n");
        return;
    }
    method_index = cmt.format == ARCHIVE_RAR_INFO_FORMAT_RAR4 ? cmt.method - RAR4_METHOD_STORE : cmt.method;
    if (cmt.is_encrypted || method_index > RAR_METHOD_INDEX_MAX ||
        (cmt.format == ARCHIVE_RAR_INFO_FORMAT_RAR4 ? cmt.unp_ver > RAR4_UNPACK_VERSION_MAX
                                                    : cmt.unp_ver > RAR5_UNPACK_VERSION_MAX) ||
        cmt.unpacked_size > UNRAR_COMMENT_MAX_UNPACKED) {
        unrar_dbgmsg("unrar_open: Archive comment cannot be read.\n");
        return;
    }
    if (cmt.in_main_header) {
        /* unRAR's RAROpenArchiveEx() hands over no RAR 1.5-2.x main header
         * comment, stored or packed. */
        unrar_dbgmsg("unrar_open: Comments are not present in this archive.\n");
        return;
    }

    if (method_index == 0) {
        size = cmt.in_main_header ? cmt.size : (size_t)(cmt.unpacked_size < cmt.size ? cmt.unpacked_size : cmt.size);
        if (size > 0 && (data = malloc(size + 1)) == NULL) {
            return;
        }
        if (size > 0) {
            memcpy(data, cmt.data, size);
        }
    } else {
        data = unpack_comment(&cmt, &size);
        if (data == NULL && cmt.unpacked_size != 0) {
            unrar_dbgmsg("unrar_open: Archive comment may be broken.\n");
            return;
        }
    }

    if (cmt.crc_present) {
        uint32_t crc = archive_rar_crc32(data, size);
        if (cmt.in_main_header ? ((crc & 0xffff) != cmt.crc) : (crc != cmt.crc)) {
            unrar_dbgmsg("unrar_open: Archive comment may be broken.\n");
            free(data);
            return;
        }
    }

    if (data == NULL) {
        data = malloc(1);
        if (data == NULL) {
            return;
        }
    }
    data[size] = '\0';

    if (cmt.format == ARCHIVE_RAR_INFO_FORMAT_RAR5) {
        w = utf8_to_wide((const char *)data, size);
    } else if (!cmt.in_main_header && (cmt.sub_flags & RAR4_CMT_UNICODE)) {
        size_t i;
        w = calloc(size / 2 + 1, sizeof(wchar_t));
        for (i = 0; w != NULL && i < size / 2; i++) {
            w[i] = (wchar_t)(data[2 * i] | (data[2 * i + 1] << 8));
        }
    }

    if (w != NULL) {
        text_size = wcslen(w) * 4 + 1;
        if ((text = calloc(1, text_size)) != NULL) {
            wide_to_char(w, text, text_size);
        }
    } else if (cmt.format == ARCHIVE_RAR_INFO_FORMAT_RAR4) {
        text_size = strlen((const char *)data) * 4 + 1;
        if ((text = calloc(1, text_size)) != NULL) {
            char_to_char((const char *)data, text, text_size);
        }
    }
    free(w);
    free(data);
    if (text == NULL) {
        return;
    }

    len = strlen(text);
    if (len == 0 && cmt.format == ARCHIVE_RAR_INFO_FORMAT_RAR4 && cmt.in_main_header) {
        free(text);
        return;
    }
    if (len + 1 > UNRAR_COMMENT_BUFFER_SIZE) {
        len = UNRAR_COMMENT_BUFFER_SIZE - 1;
    }
    text[len]     = '\0';
    *comment      = text;
    *comment_size = (uint32_t)(len + 1);
    unrar_dbgmsg("unrar_open: Archive Comments read completely.\n");
}

/*
 * The five functions.
 */

static cl_unrar_error_t header_error(unrar_handle_t *h, int r)
{
    if (r == ARCHIVE_EOF) {
        return UNRAR_BREAK;
    }
    if (archive_read_has_encrypted_entries(h->archive) > 0 && h->entry != NULL &&
        archive_entry_is_metadata_encrypted(h->entry)) {
        return UNRAR_ENCRYPTED;
    }
    if (archive_errno(h->archive) == ENOMEM) {
        return UNRAR_EMEM;
    }
    return UNRAR_ERR;
}

static int read_next_header(unrar_handle_t *h)
{
    int r = archive_read_next_header(h->archive, &h->entry);

    if (r == ARCHIVE_OK || r == ARCHIVE_WARN) {
        h->state = HEADER_READY;
        return 1;
    }
    unrar_dbgmsg("unrar: header: %s\n", archive_error_string(h->archive) ? archive_error_string(h->archive) : "end of archive");
    h->status = header_error(h, r);
    h->state  = HEADER_DONE;
    return 0;
}

cl_unrar_error_t unrar_open(const char *filename, void **hArchive, char **comment, uint32_t *comment_size, uint8_t debug_flag)
{
    unrar_handle_t *h       = NULL;
    cl_unrar_error_t status = UNRAR_ERR;
    int fd;
    int r;

    if (NULL == filename || NULL == hArchive || NULL == comment || NULL == comment_size) {
        unrar_dbgmsg("unrar_open: Invalid arguments.\n");
        return UNRAR_ERR;
    }

    unrar_debug = debug_flag;

    fd = open(filename, O_RDONLY | O_BINARY);
    if (fd < 0) {
        unrar_dbgmsg("unrar_open: Failed to open archive: %s\n", filename);
        return UNRAR_EOPEN;
    }
    close(fd);

    if ((h = calloc(1, sizeof(*h))) == NULL) {
        return UNRAR_EMEM;
    }
    if ((status = collect_volumes(h, filename)) != UNRAR_OK) {
        goto done;
    }
    status = UNRAR_ERR;

    if ((h->archive = archive_read_new()) == NULL) {
        status = UNRAR_EMEM;
        goto done;
    }
    if (archive_read_support_format_rar(h->archive) != ARCHIVE_OK ||
        archive_read_support_format_rar5(h->archive) != ARCHIVE_OK) {
        goto done;
    }
    r = archive_read_open_filenames(h->archive, (const char **)h->volumes, 64 * 1024);
    if (r != ARCHIVE_OK) {
        unrar_dbgmsg("unrar_open: Failed to open archive: %s\n", archive_error_string(h->archive));
        status = archive_errno(h->archive) == ENOMEM ? UNRAR_EMEM : UNRAR_ERR;
        goto done;
    }

    /* The comment comes before the first file: read up to the first header. */
    (void)read_next_header(h);
    read_comment(h->archive, comment, comment_size);

    unrar_dbgmsg("unrar_open: Opened archive: %s\n", filename);
    *hArchive = h;
    h         = NULL;
    status    = UNRAR_OK;

done:
    if (h != NULL) {
        unrar_close(h);
    }
    return status;
}

cl_unrar_error_t unrar_peek_file_header(void *hArchive, unrar_metadata_t *file_metadata)
{
    unrar_handle_t *h = (unrar_handle_t *)hArchive;
    struct archive_rar_entry_info info;

    if (NULL == h || NULL == file_metadata) {
        unrar_dbgmsg("unrar_peek_file_header: Invalid arguments.\n");
        return UNRAR_ERR;
    }
    memset(file_metadata, 0, sizeof(unrar_metadata_t));

    if (h->state == HEADER_NONE) {
        (void)read_next_header(h);
    }
    if (h->state == HEADER_DONE) {
        return h->status;
    }
    if (archive_read_rar_entry_info(h->archive, &info) != ARCHIVE_OK) {
        return UNRAR_ERR;
    }

    file_metadata->unpack_size = info.unpacked_size_unknown ? (uint64_t)0x7fffffff7fffffffULL : info.unpacked_size;
    file_metadata->pack_size   = info.packed_size;
    if (info.format == ARCHIVE_RAR_INFO_FORMAT_RAR4) {
        file_metadata->crc = info.crc32;
    } else {
        /*
         * unRAR reports a RAR5 entry's CRC32 from a field it shares with the
         * BLAKE2sp hash and leaves as it was when the header has neither.
         */
        if (info.blake2sp_present) {
            h->rar5_hash32 = (uint32_t)info.blake2sp[0] | ((uint32_t)info.blake2sp[1] << 8) |
                             ((uint32_t)info.blake2sp[2] << 16) | ((uint32_t)info.blake2sp[3] << 24);
        } else if (info.crc32_present) {
            h->rar5_hash32 = info.crc32;
        }
        file_metadata->crc = h->rar5_hash32;
    }
    file_metadata->encrypted = info.is_encrypted ? 1 : 0;
    file_metadata->is_dir    = info.is_dir ? 1 : 0;
    file_metadata->method    = (uint8_t)(info.format == ARCHIVE_RAR_INFO_FORMAT_RAR5 ? info.method + RAR4_METHOD_STORE : info.method);
    convert_name(&info, file_metadata->filename, UNRAR_NAME_BUFFER_SIZE);

    unrar_dbgmsg("unrar_peek_file_header:   Name:          %s\n", file_metadata->filename);
    unrar_dbgmsg("unrar_peek_file_header:   Directory?:    %u\n", file_metadata->is_dir);
    unrar_dbgmsg("unrar_peek_file_header:   RAR Version:   %u\n", info.unp_ver);
    unrar_dbgmsg("unrar_peek_file_header:   Packed Size:   %llu\n", (unsigned long long)file_metadata->pack_size);
    unrar_dbgmsg("unrar_peek_file_header:   Unpacked Size: %llu\n", (unsigned long long)file_metadata->unpack_size);
    if (info.redir_type != ARCHIVE_RAR_REDIR_NONE) {
        unrar_dbgmsg("unrar_peek_file_header:   link type %d\n", info.redir_type);
    }
    return UNRAR_OK;
}

/* Data that unRAR does not write to a file: links, copies, split pieces. */
static int entry_has_no_output(const struct archive_rar_entry_info *info)
{
    return info->split_before || info->redir_type != ARCHIVE_RAR_REDIR_NONE;
}

static cl_unrar_error_t skip_current(unrar_handle_t *h)
{
    int r = archive_read_data_skip(h->archive);

    h->state = HEADER_NONE;
    if (r < ARCHIVE_WARN) {
        unrar_dbgmsg("unrar_skip_file: %s\n", archive_error_string(h->archive));
        h->status = UNRAR_ERR;
        h->state  = HEADER_DONE;
        return UNRAR_ERR;
    }
    return UNRAR_OK;
}

cl_unrar_error_t unrar_extract_file(void *hArchive, const char *destPath, char *outputBuffer)
{
    unrar_handle_t *h = (unrar_handle_t *)hArchive;
    struct archive_rar_entry_info info;
    cl_unrar_error_t status = UNRAR_OK;
    int fd                  = -1;
    const void *buf;
    size_t size;
    la_int64_t offset;
    uint64_t remaining;
    int r;

    if (NULL == h || NULL == destPath) {
        unrar_dbgmsg("unrar_extract_file: Invalid arguments.\n");
        return UNRAR_ERR;
    }
    if (h->state == HEADER_NONE) {
        (void)read_next_header(h);
    }
    if (h->state == HEADER_DONE) {
        return h->status;
    }
    if (archive_read_rar_entry_info(h->archive, &info) != ARCHIVE_OK) {
        return UNRAR_ERR;
    }

    if (NULL != outputBuffer) {
        /* No caller asks for data in memory; its size would be unknown. */
        unrar_dbgmsg("unrar_extract_file: Extracting to a buffer is not supported.\n");
        return UNRAR_ERR;
    }

    if (entry_has_no_output(&info) || info.is_encrypted) {
        return skip_current(h);
    }

    fd = open(destPath, O_WRONLY | O_CREAT | O_TRUNC | O_BINARY, 0600);
    if (fd < 0) {
        unrar_dbgmsg("unrar_extract_file: Failed to create %s\n", destPath);
        (void)skip_current(h);
        return UNRAR_ERR;
    }

    /* unRAR writes at most the unpacked size the header declares. */
    remaining = info.unpacked_size_unknown ? UINT64_MAX : info.unpacked_size;

    for (;;) {
        r = archive_read_data_block(h->archive, &buf, &size, &offset);
        if (r == ARCHIVE_EOF) {
            break;
        }
        if (r < ARCHIVE_WARN) {
            unrar_dbgmsg("unrar_extract_file: %s\n", archive_error_string(h->archive));
            if (info.split_after) {
                status = UNRAR_EOPEN;
            }
            break;
        }
        if ((uint64_t)size > remaining) {
            size = (size_t)remaining;
        }
        remaining -= size;
        if (size > 0) {
            const char *p = buf;
            while (size > 0) {
                ssize_t n = write(fd, p, size);
                if (n <= 0) {
                    status = UNRAR_ERR;
                    break;
                }
                p += n;
                size -= (size_t)n;
            }
            if (status != UNRAR_OK) {
                break;
            }
        }
    }
    close(fd);

    if (status == UNRAR_OK) {
        h->state = HEADER_NONE;
        unrar_dbgmsg("unrar_extract_file: Extracted file to: %s\n", destPath);
    } else {
        h->status = status;
        h->state  = HEADER_DONE;
    }
    return status;
}

cl_unrar_error_t unrar_skip_file(void *hArchive)
{
    unrar_handle_t *h = (unrar_handle_t *)hArchive;

    if (NULL == h) {
        unrar_dbgmsg("unrar_skip_file: Invalid arguments.\n");
        return UNRAR_ERR;
    }
    if (h->state == HEADER_NONE) {
        (void)read_next_header(h);
    }
    if (h->state == HEADER_DONE) {
        /* An encrypted header is skipped; the reader cannot go past it. */
        if (h->status == UNRAR_ENCRYPTED) {
            h->status = UNRAR_ERR;
            return UNRAR_OK;
        }
        return h->status;
    }
    if (skip_current(h) != UNRAR_OK) {
        return UNRAR_ERR;
    }
    unrar_dbgmsg("unrar_skip_file: File skipped.\n");
    return UNRAR_OK;
}

void unrar_close(void *hArchive)
{
    unrar_handle_t *h = (unrar_handle_t *)hArchive;

    if (NULL == h) {
        return;
    }
    if (h->archive != NULL) {
        archive_read_free(h->archive);
    }
    free_volumes(h);
    free(h);
}
