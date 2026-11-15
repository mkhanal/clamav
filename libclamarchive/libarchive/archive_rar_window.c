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
#include <time.h>

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

#if defined(__linux__) || defined(__FreeBSD__) || defined(__NetBSD__) || \
    defined(__DragonFly__)
#define RAR_WINDOW_POSIX_FALLOCATE 1
#endif

#if defined(__linux__) || defined(__FreeBSD__) || defined(__NetBSD__) || \
    defined(__OpenBSD__) || defined(__DragonFly__)
#define RAR_WINDOW_MKOSTEMP 1
#endif

/* Writes zeros through the whole file, so every block is allocated. */
static int
write_through(int fd, size_t size)
{
	static const char zeros[65536];
	size_t done = 0;

	while (done < size) {
		size_t chunk = size - done;
		ssize_t written;

		if (chunk > sizeof(zeros))
			chunk = sizeof(zeros);
		written = pwrite(fd, zeros, chunk, (off_t)done);
		if (written < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (written == 0) {
			errno = ENOSPC;
			return -1;
		}
		done += (size_t)written;
	}
	return 0;
}

/*
 * Reserves the disk space of the whole file now, so that a full disk fails
 * here and not as SIGBUS when a page of the mapping is first written.
 */
static int
reserve_space(int fd, size_t size)
{
#if defined(__APPLE__)
	fstore_t store;

	memset(&store, 0, sizeof(store));
	store.fst_flags = F_ALLOCATECONTIG | F_ALLOCATEALL;
	store.fst_posmode = F_PEOFPOSMODE;
	store.fst_length = (off_t)size;
	if (fcntl(fd, F_PREALLOCATE, &store) != 0) {
		store.fst_flags = F_ALLOCATEALL;
		if (fcntl(fd, F_PREALLOCATE, &store) != 0)
			return write_through(fd, size);
	}
	return ftruncate(fd, (off_t)size);
#elif defined(RAR_WINDOW_POSIX_FALLOCATE)
	int error = posix_fallocate(fd, 0, (off_t)size);

	if (error != 0) {
		errno = error;
		return -1;
	}
	return 0;
#else
	if (ftruncate(fd, (off_t)size) != 0)
		return -1;
	return write_through(fd, size);
#endif
}

static void *
map_file(int fd, size_t size)
{
	if (fchmod(fd, 0600) != 0 || reserve_space(fd, size) != 0)
		return MAP_FAILED;
	return mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
}

#ifndef RAR_WINDOW_MKOSTEMP
/*
 * Creates a unique file with close-on-exec set by open() itself, for systems
 * without mkostemp(): mkstemp() followed by fcntl() would leave a moment in
 * which a forked process inherits the descriptor.
 */
static int
create_cloexec(char *path, size_t prefix)
{
	static unsigned counter;
	int attempt;

	for (attempt = 0; attempt < 100; attempt++) {
		struct timespec now;
		unsigned long value;
		int fd;

		clock_gettime(CLOCK_MONOTONIC, &now);
		value = (unsigned long)now.tv_nsec ^
		    ((unsigned long)now.tv_sec << 20) ^
		    ((unsigned long)getpid() << 10) ^ counter++;
		snprintf(path + prefix, 7, "%06lx", value & 0xffffff);
		fd = open(path, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
		if (fd >= 0 || errno != EEXIST)
			return fd;
	}
	return -1;
}
#endif

static void *
map_unnamed_file(size_t size, const char *tmpdir)
{
	void *window;
	int fd;

#ifdef O_TMPFILE
	fd = open(tmpdir, O_TMPFILE | O_RDWR | O_EXCL | O_CLOEXEC, 0600);
	if (fd >= 0) {
		window = map_file(fd, size);
		if (window == MAP_FAILED)
			window_log("RAR window: unnamed file in %s failed: %s",
			    tmpdir, strerror(errno));
		close(fd);
		if (window != MAP_FAILED)
			return window;
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
#ifdef RAR_WINDOW_MKOSTEMP
		fd = mkostemp(path, O_CLOEXEC);
#else
		fd = create_cloexec(path, strlen(tmpdir) + 1 +
		    sizeof("clamav-rar-window-") - 1);
#endif
		if (fd < 0) {
			window_log("RAR window: temporary file in %s failed: %s",
			    tmpdir, strerror(errno));
			free(path);
			return MAP_FAILED;
		}
		unlink(path);
		free(path);
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
