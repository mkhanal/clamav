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

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "archive_platform.h"

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "archive_rar_window.h"

#if !defined(_WIN32) || defined(__CYGWIN__)
#define RAR_WINDOW_MAPPED 1
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#endif

#ifdef RAR_WINDOW_MAPPED

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

#define RAR_WINDOW_TEMPLATE "/clamav-rar-window-XXXXXX"

static void (*window_logger)(const char *);

void
__archive_rar_window_set_logger(void (*logger)(const char *))
{
	window_logger = logger;
}

static void
window_log(const char *format, ...)
{
	char message[512];
	va_list ap;

	if (window_logger == NULL)
		return;
	va_start(ap, format);
	vsnprintf(message, sizeof(message), format, ap);
	va_end(ap);
	window_logger(message);
}

static int
use_mapping(size_t size)
{
	return size > RAR_WINDOW_FILE_THRESHOLD;
}

static void *
map_file(int fd, size_t size)
{
	void *window;

	if (fchmod(fd, 0600) != 0 || ftruncate(fd, (off_t)size) != 0)
		return MAP_FAILED;
#ifdef __linux__
	/* Reserve the disk space now: a full disk then fails here and not as
	 * SIGBUS when a page of the mapping is first written. */
	if (fallocate(fd, 0, 0, (off_t)size) != 0)
		return MAP_FAILED;
#endif
	window = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	return window;
}

static void *
map_unnamed_file(size_t size, const char *tmpdir)
{
	void *window;
	int fd;

#ifdef O_TMPFILE
	fd = open(tmpdir, O_TMPFILE | O_RDWR | O_EXCL | O_CLOEXEC, 0600);
	if (fd >= 0) {
		window = map_file(fd, size);
		close(fd);
		if (window != MAP_FAILED)
			return window;
		window_log("RAR window: unnamed file in %s failed: %s",
		    tmpdir, strerror(errno));
	} else
		window_log("RAR window: O_TMPFILE in %s failed: %s",
		    tmpdir, strerror(errno));
#endif

	{
		size_t length = strlen(tmpdir) + sizeof(RAR_WINDOW_TEMPLATE);
		char *path = malloc(length);

		if (path == NULL)
			return MAP_FAILED;
		snprintf(path, length, "%s%s", tmpdir, RAR_WINDOW_TEMPLATE);
		fd = mkstemp(path);
		if (fd < 0) {
			window_log("RAR window: mkstemp in %s failed: %s",
			    tmpdir, strerror(errno));
			free(path);
			return MAP_FAILED;
		}
		unlink(path);
		free(path);
		(void)fcntl(fd, F_SETFD, FD_CLOEXEC);
		window = map_file(fd, size);
		if (window == MAP_FAILED)
			window_log("RAR window: file in %s failed: %s",
			    tmpdir, strerror(errno));
		close(fd);
	}
	return window;
}

void *
__archive_rar_window_alloc(size_t size, const char *tmpdir)
{
	void *window;

	if (!use_mapping(size))
		return calloc(1, size);

	if (tmpdir != NULL && tmpdir[0] != '\0') {
		window = map_unnamed_file(size, tmpdir);
		if (window != MAP_FAILED) {
			window_log("RAR window: %zu bytes in an unnamed file in %s",
			    size, tmpdir);
			return window;
		}
	}

	window = mmap(NULL, size, PROT_READ | PROT_WRITE,
	    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (window == MAP_FAILED)
		return NULL;
	window_log("RAR window: %zu bytes in anonymous memory", size);
	return window;
}

void
__archive_rar_window_free(void *window, size_t size)
{
	if (window == NULL)
		return;
	if (use_mapping(size))
		munmap(window, size);
	else
		free(window);
}

#else

void
__archive_rar_window_set_logger(void (*logger)(const char *))
{
	(void)logger;
}

void *
__archive_rar_window_alloc(size_t size, const char *tmpdir)
{
	(void)tmpdir;
	return calloc(1, size);
}

void
__archive_rar_window_free(void *window, size_t size)
{
	(void)size;
	free(window);
}

#endif
