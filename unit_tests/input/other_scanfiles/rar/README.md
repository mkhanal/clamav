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

The last two rows were written by a `rar` binary (RAR 2.9 archives: Unix host,
real timestamps; RAR5: no other writer exists), but their exact commands were not
recorded.

## Taken from libarchive

| Fixture | Covers |
|---|---|
| `rar5-bad-tables.rar` | libarchive's `test_read_format_rar5_bad_tables.rar` (BSD-2-Clause, see `libclamarchive/COPYING`): a RAR5 entry that stops at Huffman tables that cannot be built; unRAR extracts the 34 bytes decoded before them |

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
| `rar15-small.rar`, `rar15-solid.rar`, `rar15-rar20-solid.rar` | RAR 1.5 compression |
| `rar20-lz-text.rar`, `rar20-audio-1ch.rar`, `rar20-audio-4ch.rar`, `rar20-block-switches.rar`, `rar20-solid.rar`, `rar26-lz-audio.rar` | RAR 2.0 and 2.6 compression, including multimedia (audio) blocks and solid streams |

No reader in this repository decodes RAR 1.5, 2.0 or 2.6. With the libarchive
backend a scan reports an extraction error for each of their entries; with the
RARLAB backend they extract as recorded in `rar_test.py`.
