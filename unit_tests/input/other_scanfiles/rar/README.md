# RAR test fixtures

Archives for `unit_tests/clamscan/rar_test.py`. Every file here is data: a fixed
byte string with the SHA-256 recorded in `MANIFEST.sha256`. The repository holds
no code that compresses data into RAR format; re-creating RAR compression is what
the RARLAB licence forbids. The one script, `generators/make_rarlab_fixtures.sh`,
drives RARLAB's own `rar` binary (not part of this repository) and nothing else.

## Made by RARLAB `rar`

Run `generators/make_rarlab_fixtures.sh` (rar 6.24 for RAR 2.9 archives, rar 7.20
or later for RAR5 archives; the `*-skip-budget.rar` and `*-checked.rar` archives were made with
rar 6.24 and 7.23).

| Fixture | Covers |
|---|---|
| `rar4-solid-ppmd.rar` | solid RAR 2.9 PPMd stream |
| `rar4-solid-skip.rar`, `rar5-solid-skip.rar` | an entry over `--max-filesize` followed by one in the same solid stream |
| `rar4-solid-skip-budget.rar`, `rar5-solid-skip-budget.rar` | two entries over `--max-filesize` followed by one in the same solid stream |
| `rar4-comment.rar`, `rar5-comment.rar` | archive comment |
| `rar4-encrypted-data.rar`, `rar4-encrypted-headers.rar`, `rar5-encrypted-data.rar`, `rar5-encrypted-headers.rar` | encrypted entries and headers |
| `rar4-volume.part1.rar`, `rar4-volume.part2.rar`, `rar5-volume.part1.rar`, `rar5-volume.part2.rar` | a file split across volumes |
| `rar4-stored-checked.rar`, `rar4-compressed-checked.rar`, `rar5-stored-checked.rar`, `rar5-compressed-checked.rar`, `rar5-blake2-checked.rar`, `rar5-stored-blake2-checked.rar` | one entry each, stored and compressed, with a CRC32 or a BLAKE2sp checksum; the tests flip a data byte |
| `rar4-filter-audio.rar`, `rar4-filter-delta.rar`, `rar4-filter-e8.rar`, `rar4-filter-rgb.rar`, `rar4-ppmd-e8.rar` | RAR 2.9 standard filters, and a filter over PPMd data |
| `rar5-filter-delta.rar`, `rar5-filter-e8.rar` | RAR5 filters |
| `rar5-large-window.rar` | one RAR5 entry of 419430432 bytes (zeros and a marker line) in 17 KB with a 256 MB dictionary (`rar a -ma5 -m3 -md256m`, rar 7.23): its decompression window is above the 64 MiB threshold for a file-backed window |

The last two rows were written by a `rar` binary (RAR 2.9 archives: Unix host,
real timestamps; RAR5: no other writer exists), but their exact commands were not
recorded.

## Derived from a RARLAB fixture

| Fixture | Covers |
|---|---|
| `rar5-unknown-size-600m.rar` | one RAR5 entry of 629145600 zero bytes in 26 KB (`rar a -ma5 -m3`, rar 7.23) with the unknown unpacked size flag (0x08 of the file flags) set and the header checksum recomputed: nothing but its data ends the entry |

## Taken from libarchive

| Fixture | Covers |
|---|---|
| `rar5-bad-tables.rar` | libarchive's `test_read_format_rar5_bad_tables.rar` (BSD-2-Clause, see `libclamarchive/COPYING`): a RAR5 entry that stops at Huffman tables that cannot be built; unRAR extracts the 34 bytes decoded before them |

## Made by RARLAB RAR 2.50 for DOS

Written by RARLAB's own `RAR.EXE` 2.50 (SHA-256
`426b45982a6a675d149f7ef3cbd3ad3171234c187cb633891c066aa819259651`, from
rarlab.com), run under the `emu2` DOS emulator in a Debian container. The inputs
are synthetic: `TEXT.TXT` (30000 bytes of seeded pseudo-random words), `S00.TXT`
to `S06.TXT` (lines `line N of file 1: x...`, 19 to 2076 bytes), `RAND.BIN`
(12000 pseudo-random bytes), `MONO8.WAV` (24000 bytes) and `QUAD.RAW` (20000
bytes) of 8-bit audio-like data, and `EMPTY.DAT`, `ONE.DAT` and `TWO.DAT` of 0, 1
and 2 bytes. DOS RAR 2.50 accepts `-md` only on OS/2, so every archive uses its
default dictionary. The glob was expanded by RAR (`set -f` in the shell). The
expected SHA-256 of each entry in `rar_test.py` is what the RARLAB backend
extracts (black box), and it equals the SHA-256 of the input file. Entries of
fewer than 3 bytes are not listed there: no signature matches them.

| Fixture | Command (`RAR.EXE`, `-y` omitted) | Covers |
|---|---|---|
| `rar250-m3.rar` | `a NSM3.RAR TEXT.TXT S0*.TXT` | non-solid, method 3 (default) |
| `rar250-solid-m1.rar`, `rar250-solid-m2.rar`, `rar250-solid-m3.rar`, `rar250-solid-m5.rar` | `a -s [-m1\|-m2\|-m5] SMn.RAR TEXT.TXT S0*.TXT` | solid, methods 1, 2, 3 (default) and 5 |
| `rar250-solid-mm.rar` | `a -s -mm SMM.RAR MONO8.WAV QUAD.RAW S01.TXT S02.TXT RAND.BIN` | solid multimedia: audio and LZ blocks alternate between entries |
| `rar250-mm-m5.rar` | `a -mm -m5 NSMM5.RAR MONO8.WAV QUAD.RAW TEXT.TXT` | non-solid multimedia, method 5 |
| `rar250-solid-small.rar` | `a -s SSMALL.RAR S01.TXT EMPTY.DAT S02.TXT ONE.DAT S03.TXT TWO.DAT S04.TXT` | solid with empty, 1-byte and 2-byte entries; RAR sorts by extension, so the empty entry comes first and carries the block header and tables of the entries after it |
| `rar250-solid-volumes.rar`, `.r00`, `.r01` | `a -s -m5 -v8 SVOL.RAR RAND.BIN TEXT.TXT S0*.TXT` | a solid set of 3 volumes, entries split across volumes |
| `rar250-split.rar`, `.r00`, `.r01`, `.r02` | `a -m3 -v6 SPLIT.RAR MONO8.WAV S01.TXT` | a compressed entry split across 4 volumes |

`rar250-solid-size-overflow.rar` is a RAR 2.50 solid archive whose second
entry's header was edited (header CRC fixed) to declare an unpacked size of
`0x7FFFFFFFFFFFFFF0` with the large-size flag. A decoder must reject it without
signed overflow; the sanitizer builds report one if it does not.

The crafted `rar20-solid.rar` is gone: its layout (an entry ending with the end
of the block and the next block's header) was written by the removed encoder and
no RAR 2.50 archive has it. `rar20-lz-text.rar`, `rar20-audio-1ch.rar`,
`rar20-audio-4ch.rar`, `rar20-block-switches.rar` and `rar26-lz-audio.rar` stay:
both backends extract them identically.

## Crafted

These were assembled byte by byte by scripts written for this project (RAR 2.9
literal-only blocks with a hand-made filter definition, and RAR 1.5 / 2.0 / 2.6
streams). Those scripts were removed together with the RAR 1.5 and RAR 2.0
decoders; the files are kept as data. unRAR 6.24 extracts every entry of every
one of them with a matching CRC. The RAR 1.5 archives carry pseudo-random packed
data; their headers record the size and CRC of what unRAR decodes from it.

| Fixture | Covers |
|---|---|
| `rar4-filter-e8e9.rar`, `rar4-filter-itanium.rar` | the E8E9 and Itanium filters, which no `rar` we can run writes |
| `rar4-solid-pending-filter.rar` | a filter defined at the end of `a.txt` for the range where `b.bin` starts: the filter must not reach `b.bin` |
| `rar4-empty.rar`, `rar5-empty.rar` | a valid main header, an end header and no entries: the archive is read to its end |
| `rar4-signature-only.rar`, `rar5-signature-only.rar` | the signature and nothing else: no valid main header |
| `rar5-truncated-header.rar` | the signature and a file header cut short: a header that cannot be read |
| `rar15-small.rar`, `rar15-solid.rar`, `rar15-rar20-solid.rar` | RAR 1.5 compression |
| `rar20-lz-text.rar`, `rar20-audio-1ch.rar`, `rar20-audio-4ch.rar`, `rar20-block-switches.rar`, `rar26-lz-audio.rar` | RAR 2.0 and 2.6 compression, including multimedia (audio) blocks |

Both backends extract the RAR 2.0 and 2.6 archives as recorded in
`rar_test.py`. No reader in this repository decodes RAR 1.5: with the libarchive
backend a scan reports an extraction error for each RAR 1.5 entry, and for the
RAR 2.0 entry of `rar15-rar20-solid.rar`, whose solid stream starts with RAR 1.5;
with the RARLAB backend they extract as recorded in `rar_test.py`.
