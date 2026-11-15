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
 * The decompression window of a RAR archive. A window larger than
 * RAR_WINDOW_FILE_THRESHOLD is a MAP_SHARED mapping of an unnamed temporary
 * file, so the kernel can write its pages to disk under memory pressure;
 * smaller ones, and every window on Windows, are ordinary memory.
 */

#ifndef ARCHIVE_RAR_WINDOW_H_INCLUDED
#define ARCHIVE_RAR_WINDOW_H_INCLUDED

#include <stddef.h>

/* Windows up to this size (64 MiB) stay in anonymous memory. */
#define RAR_WINDOW_FILE_THRESHOLD ((size_t)64 << 20)

/*
 * Returns zero-filled memory of `size` bytes, or NULL. `tmpdir` is the
 * directory for the unnamed file of a window above the threshold; NULL
 * selects anonymous memory.
 */
void *__archive_rar_window_alloc(size_t size, const char *tmpdir);

/* Releases memory from __archive_rar_window_alloc() given its `size`. */
void __archive_rar_window_free(void *window, size_t size);

/* Receives a description of how a window was backed, or why a way failed. */
void __archive_rar_window_set_logger(void (*logger)(const char *));

#endif
