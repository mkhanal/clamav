/*
 * Fuzz target for the libclamunrar_iface functions with the libarchive backend:
 * unrar_open(), unrar_peek_file_header(), unrar_extract_file(),
 * unrar_skip_file() and unrar_close(), driven as cli_scanrar_file() drives them.
 *
 * The input is one archive file. If it holds further RAR signatures after the
 * first, each piece from a signature onward is written as the next volume of
 * the set (fuzz.part1.rar, fuzz.part2.rar, ...), so volume handling is reached.
 *
 * Copyright (C) 2025 Cisco Systems, Inc. and/or its affiliates. All rights reserved.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern "C" {
#include "unrar_iface.h"
}

namespace
{

constexpr size_t kMaxVolumes        = 8;
constexpr uint64_t kMaxExtractSize  = 64ull * 1024 * 1024;
constexpr unsigned kMaxHeaders      = 256;
constexpr size_t kPathMax           = 512;
constexpr uint8_t kRar4Signature[7] = {0x52, 0x61, 0x72, 0x21, 0x1a, 0x07, 0x00};
constexpr uint8_t kRar5Signature[8] = {0x52, 0x61, 0x72, 0x21, 0x1a, 0x07, 0x01, 0x00};

char g_dir[kPathMax];

bool write_file(const char *path, const uint8_t *data, size_t size)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) {
        return false;
    }
    while (size > 0) {
        ssize_t n = write(fd, data, size);
        if (n <= 0) {
            close(fd);
            return false;
        }
        data += n;
        size -= static_cast<size_t>(n);
    }
    return close(fd) == 0;
}

bool is_signature_at(const uint8_t *data, size_t size, size_t offset)
{
    if (offset + sizeof(kRar5Signature) <= size && memcmp(data + offset, kRar5Signature, sizeof(kRar5Signature)) == 0) {
        return true;
    }
    return offset + sizeof(kRar4Signature) <= size && memcmp(data + offset, kRar4Signature, sizeof(kRar4Signature)) == 0;
}

uint32_t fnv1a(const uint8_t *data, size_t size)
{
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < size; i++) {
        h = (h ^ data[i]) * 16777619u;
    }
    return h;
}

}

extern "C" int LLVMFuzzerInitialize(int *, char ***)
{
    const char *tmp = getenv("TMPDIR");
    snprintf(g_dir, sizeof(g_dir), "%s/unrar-iface-fuzz-XXXXXX", tmp != nullptr ? tmp : "/tmp");
    if (mkdtemp(g_dir) == nullptr) {
        perror("mkdtemp");
        abort();
    }
    return 0;
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    char volumes[kMaxVolumes][kPathMax];
    size_t volume_count = 0;
    size_t begin        = 0;

    while (volume_count < kMaxVolumes) {
        size_t end = size;
        for (size_t i = begin + 1; i < size && volume_count + 1 < kMaxVolumes; i++) {
            if (is_signature_at(data, size, i)) {
                end = i;
                break;
            }
        }
        snprintf(volumes[volume_count], kPathMax, "%s/fuzz.part%zu.rar", g_dir, volume_count + 1);
        if (!write_file(volumes[volume_count], data + begin, end - begin)) {
            perror("write_file");
            abort();
        }
        volume_count++;
        if (end == size) {
            break;
        }
        begin = end;
    }

    uint32_t choices = fnv1a(data, size);

    void *archive         = nullptr;
    char *comment         = nullptr;
    uint32_t comment_size = 0;

    cl_unrar_error_t ret = unrar_open(volumes[0], &archive, &comment, &comment_size, 0);
    if (ret == UNRAR_OK) {
        if (comment != nullptr && comment_size > 0) {
            volatile char sink = comment[comment_size - 1];
            (void)sink;
        }

        for (unsigned count = 0; count < kMaxHeaders; count++) {
            unrar_metadata_t metadata;
            memset(&metadata, 0, sizeof(metadata));

            ret = unrar_peek_file_header(archive, &metadata);
            if (ret == UNRAR_ENCRYPTED) {
                if (unrar_skip_file(archive) != UNRAR_OK) {
                    break;
                }
                continue;
            }
            if (ret != UNRAR_OK) {
                break;
            }
            if (memchr(metadata.filename, '\0', sizeof(metadata.filename)) == nullptr) {
                abort();
            }

            bool extract = (choices >> (count % 32)) & 1;
            if (metadata.is_dir || metadata.encrypted || metadata.unpack_size > kMaxExtractSize || !extract) {
                if (unrar_skip_file(archive) != UNRAR_OK) {
                    break;
                }
                continue;
            }
            (void)unrar_extract_file(archive, "/dev/null", nullptr);
        }
    }

    unrar_close(archive);
    free(comment);

    for (size_t i = 0; i < volume_count; i++) {
        unlink(volumes[i]);
    }
    return 0;
}
