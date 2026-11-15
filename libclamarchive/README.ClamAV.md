# libarchive, vendored for libclamunrar_iface

This directory holds libarchive (BSD-2-Clause, see `COPYING`), the library
that reads RAR archives for ClamCove (`ENABLE_UNRAR`, on by default). It is built as a static library with no
optional dependencies and linked into `libclamunrar_iface`, so it adds no
runtime dependency. Nothing here is installed.

- Release: libarchive 3.8.11
- Source: https://github.com/libarchive/libarchive/releases/download/v3.8.11/libarchive-3.8.11.tar.xz
- SHA-256 of that tarball: `a3dc0872b1b39da34dc18ef1b944f0f11ffd37425d70ae04be679279f1cf43d2`

Kept from the release: `CMakeLists.txt`, `COPYING`, `NEWS`, `README.md`,
`build/cmake`, `build/pkgconfig`, `build/version`, and `libarchive/`
without its tests and man pages. libarchive's build always enters the
`cat`, `cpio`, `tar` and `unzip` directories and each `test` directory,
so only their `CMakeLists.txt` files are kept; the programs and tests
themselves are switched off and not vendored.

Every change ClamAV makes to the release is a separate commit touching
this directory. To see them, diff this tree against the release tarball.

## Code added to the release

`libarchive/archive_rar_unpack20.c` and `archive_rar_unpack20.h` are not part
of libarchive. They decode RAR 2.0 and 2.6 data (unpack versions 20 and 26,
including audio blocks and solid streams) and are a C port of the decoder in
[nwaples/rardecode](https://github.com/nwaples/rardecode) (BSD-2-Clause),
commit `f557bc97578a96c9196330d7ba642a8599a2ebd6`: `decode20.go`,
`decode20_lz.go`, `decode20_audio.go`, `huffman.go`, `bit_reader.go`, and the
length and offset tables of `decode29_lz.go`. The port keeps rardecode's
structure and names, converted to C style, and nothing else was used as a
source: RARLAB's unRAR code, and any earlier decoder written for this tree,
were not read. rardecode's licence, which the port carries at the top of both
files:

```
Copyright (c) 2015, Nicholas Waples
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

Where the port differs from rardecode:

- At the start of a non-solid entry the previous-length and previous-offset
  history is cleared as well as the tables and audio state; rardecode keeps
  them from the previous file.
- Matches are cut at the end of the entry's output instead of carried over.
- An empty entry of a solid stream still has its block header and tables read
  when its data starts a block (`rar20_decoder_read_header`). RAR 2.50 writes
  them there when an empty file comes first, and the next entry continues with
  them. rardecode reads nothing for an entry of no output, and cannot decode
  the entries after it (`rar250-solid-small.rar`).
- The window is libarchive's RAR window, shared with nothing else; the entries
  of one solid stream must all use the RAR 2.0 / 2.6 decoder (rardecode
  refuses mixed decoders as well), otherwise the entry is an error.
- A Huffman code that matches no symbol when fewer than 15 bits remain is a
  decode error (rardecode indexes past its position table there).
- Signed-byte conversions and shifts are written so they have no undefined
  behaviour in C.
