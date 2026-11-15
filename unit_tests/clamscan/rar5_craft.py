# Copyright (C) 2026 Mridul Khanal. All rights reserved.

"""
Take apart and put together RAR5 archives, to give the header of one entry a
shape the RAR writers never produce. The data of every entry is kept as it
was; the checksum of every header is recomputed.
"""

import struct
import zlib

SIGNATURE = bytes.fromhex('526172211a070100')

HEAD_FILE = 2

HFL_EXTRA = 0x01
HFL_DATA = 0x02
HFL_SPLIT_BEFORE = 0x08
HFL_SPLIT_AFTER = 0x10

FILE_UTIME = 0x02
FILE_CRC32 = 0x04
FILE_UNKNOWN_SIZE = 0x08

EXTRA_REDIR = 5


def read_vint(data, i):
    value = shift = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7f) << shift
        shift += 7
        if not byte & 0x80:
            return value, i


def vint(value):
    out = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


class FileHeader:
    """The body of a file header, field by field."""

    def __init__(self, body):
        self.type, k = read_vint(body, 0)
        flags, k = read_vint(body, k)
        self.flags = flags & ~(HFL_EXTRA | HFL_DATA)
        extra_size = 0
        if flags & HFL_EXTRA:
            extra_size, k = read_vint(body, k)
        self.has_data = bool(flags & HFL_DATA)
        self.data_size = 0
        if flags & HFL_DATA:
            self.data_size, k = read_vint(body, k)
        self.file_flags, k = read_vint(body, k)
        self.unpacked_size, k = read_vint(body, k)
        self.attributes, k = read_vint(body, k)
        self.mtime = None
        if self.file_flags & FILE_UTIME:
            self.mtime = body[k:k + 4]
            k += 4
        self.crc = None
        if self.file_flags & FILE_CRC32:
            self.crc = body[k:k + 4]
            k += 4
        self.compression, k = read_vint(body, k)
        self.host_os, k = read_vint(body, k)
        name_size, k = read_vint(body, k)
        self.name = body[k:k + name_size]
        k += name_size
        self.padding = body[k:len(body) - extra_size]
        self.extra = body[len(body) - extra_size:]
        self.trailer = b''
        self.declared_extra_size = None

    def records(self):
        """The extra area as a list of (id, content)."""
        out = []
        i = 0
        while i < len(self.extra):
            size, i = read_vint(self.extra, i)
            record = self.extra[i:i + size]
            i += size
            record_id, j = read_vint(record, 0)
            out.append((record_id, record[j:]))
        return out

    def set_records(self, records):
        self.extra = b''.join(
            vint(len(vint(i)) + len(content)) + vint(i) + content for i, content in records)

    def set_compression(self, solid=None, dictionary=None):
        if solid is not None:
            self.compression = (self.compression & ~0x40) | (0x40 if solid else 0)
        if dictionary is not None:
            self.compression = (self.compression & ~(0xf << 10)) | (dictionary << 10)

    def build(self):
        extra = self.extra + self.trailer
        extra_size = len(extra) if self.declared_extra_size is None else self.declared_extra_size
        flags = self.flags
        out = bytearray()
        if extra:
            flags |= HFL_EXTRA
        if self.has_data:
            flags |= HFL_DATA
        out += vint(self.type) + vint(flags)
        if extra:
            out += vint(extra_size)
        if self.has_data:
            out += vint(self.data_size)
        out += vint(self.file_flags) + vint(self.unpacked_size) + vint(self.attributes)
        if self.mtime is not None:
            out += self.mtime
        if self.crc is not None:
            out += self.crc
        out += vint(self.compression) + vint(self.host_os)
        out += vint(len(self.name)) + self.name + self.padding + extra
        return bytes(out)


class Block:
    def __init__(self, body, data):
        self.type, _ = read_vint(body, 0)
        self.body = body
        self.data = data

    def header(self):
        return FileHeader(self.body) if self.type == HEAD_FILE else None

    def pack(self):
        size = vint(len(self.body))
        crc = zlib.crc32(size + self.body) & 0xffffffff
        return struct.pack('<I', crc) + size + self.body + self.data


class Archive:
    def __init__(self, raw):
        assert raw[:8] == SIGNATURE
        self.blocks = []
        i = len(SIGNATURE)
        while i < len(raw):
            size, j = read_vint(raw, i + 4)
            body = raw[j:j + size]
            _, k = read_vint(body, 0)
            flags, k = read_vint(body, k)
            data_size = 0
            if flags & HFL_EXTRA:
                _, k = read_vint(body, k)
            if flags & HFL_DATA:
                data_size, k = read_vint(body, k)
            self.blocks.append(Block(body, raw[j + size:j + size + data_size]))
            i = j + size + data_size

    def files(self):
        return [b for b in self.blocks if b.type == HEAD_FILE]

    def edit_file(self, index, edit):
        block = self.files()[index]
        header = block.header()
        edit(header)
        block.body = header.build()

    def set_main_flags(self, flags):
        """Set the archive flags of the main header (0x04 is solid)."""
        block = self.blocks[0]
        _, k = read_vint(block.body, 0)
        header_flags, k = read_vint(block.body, k)
        if header_flags & HFL_EXTRA:
            _, k = read_vint(block.body, k)
        old, j = read_vint(block.body, k)
        block.body = block.body[:k] + vint(flags) + block.body[j:]

    def build(self):
        return SIGNATURE + b''.join(b.pack() for b in self.blocks)

    @staticmethod
    def join(first, second):
        """The entries of both archives, in one: main header and end marker of the first."""
        archive = Archive(first)
        other = Archive(second)
        end = archive.blocks.pop()
        archive.blocks.extend(other.files())
        archive.blocks.append(end)
        return archive
