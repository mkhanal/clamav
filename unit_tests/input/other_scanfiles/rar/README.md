# RAR test files

Archives for `unit_tests/clamscan/rar_test.py`. Every archive was made with
RARLAB rar 6.24 (RAR 2.9 / 4.x format, `-ma4`) or 7.20 (RAR5, `-ma5`), at
compression method 3 unless noted.

The marker is the text `ClamAV-RAR-backend-test-marker-6f1c2e`.

| File | Contents |
| --- | --- |
| `rar4-filter-e8.rar`, `rar5-filter-delta.rar` | One file compressed with an E8 or delta filter |
| `rar4-comment.rar`, `rar5-comment.rar` | An archive comment holding the marker |
| `rar4-encrypted-data.rar` | One file encrypted with the password `pw`, headers in the clear |
| `rar4-volume.part1.rar`, `rar4-volume.part2.rar`, `rar5-volume.part1.rar`, `rar5-volume.part2.rar` | A 12 KB random file with the marker inside it, and a file holding the marker, in 8 KB volumes (`-v8k`) |
