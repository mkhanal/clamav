# Copyright (C) 2026 Mridul Khanal. All rights reserved.

"""
Run clamscan RAR tests.

The same expectations hold for both RAR backends (RARLAB unRAR and
libarchive), except where noted: every expected hash below is what unRAR
extracts.
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import testcase

MARKER = b'ClamAV-RAR-backend-test-marker-6f1c2e'

# Archive -> what every entry must extract to: (size, SHA-256).
EXTRACTED = {
    # RAR 2.9 (RAR 3.x / 4.x format) standard filters, and a filter over
    # PPMd-coded data.
    'rar4-filter-e8.rar': [
        (9044, '42ad3a48597bf100702812ad1c18b57dba1fab10f35401b6d6070b335b26057f')],
    'rar4-filter-e8e9.rar': [
        (8000, '815934886151360cff53369052cab8be55fcdca7168f88cdfcd29481628305d6')],
    'rar4-filter-delta.rar': [
        (48000, '283fea56571bf5b805b7d3c3fefa48eb24f44ce9f2c8d031df4a8b8239ae4109')],
    'rar4-filter-rgb.rar': [
        (18486, '1981c9d2d85226d003f413b0fbf13733b33a2aa151b03c6c281aa6d8aa9ac9e8')],
    'rar4-filter-audio.rar': [
        (48044, '6ce068910efc77af2d618bf035c6348b13d9fcf828bf3e69b5d068b55a530ab3')],
    'rar4-filter-itanium.rar': [
        (11200, '6b7a6404e2e03a3e5fc8d512f3ac85c9a5f18f0b590011077840c829d44798c4')],
    'rar4-ppmd-e8.rar': [
        (9044, '42ad3a48597bf100702812ad1c18b57dba1fab10f35401b6d6070b335b26057f')],
    # RAR5 filters.
    'rar5-filter-delta.rar': [
        (48000, '283fea56571bf5b805b7d3c3fefa48eb24f44ce9f2c8d031df4a8b8239ae4109')],
    'rar5-filter-e8.rar': [
        (9044, '42ad3a48597bf100702812ad1c18b57dba1fab10f35401b6d6070b335b26057f')],
}

# RAR 1.5, 2.0 and 2.6 compression, including multimedia (audio) blocks and
# solid streams, as RARLAB unRAR extracts it. The libarchive backend has no
# decoder for it.
EXTRACTED_BY_UNRAR_ONLY = {
    'rar15-small.rar': [
        (302, '6905378fc71be9665755071e77d712963f14a9e3ccab8a62fb30d42023ba8947')],
    'rar15-solid.rar': [
        (6002, '18c49e88aca59a47bbf4f9f773ddd1e7ff6554de06964b23fb0e98cbf8dd31b2'),
        (5004, 'c55d6dcbbd23bb2ba40e95afd05fe54050a0cabf8e024b7d9452cc4d83b822f5'),
        (3089, '5e4faafd9828d55b42d887e992cf84125a5b39154955f09c1f44625cc0c8a745')],
    'rar15-rar20-solid.rar': [
        (4001, '0ae02de111812f78bede44113962aa88c9634ec3d6d087a4b5a06f6f22a10e2d'),
        (6000, '3a4be01ed3ebfe1169661947d6e0c690afd41d79bfd83a36187edc5c89ae323f')],
    'rar20-lz-text.rar': [
        (20000, '8f026544474ace34d7c3c1744620611d32f9eb9d533521f948f1c9f75367538e')],
    'rar20-audio-1ch.rar': [
        (6000, 'ad1d689c1feca9b72b958fc9d07cf91b0c659ee4c6b1bc41b7b17f0f0fc2a9bf')],
    'rar20-audio-4ch.rar': [
        (6000, '081202b2c7e6e24cee2ffe0c106f2167f742d89bb8253bc96c8471d6e8e0d176')],
    'rar20-block-switches.rar': [
        (12000, '2e073b467b48ed65da8cc07906a96c4b069b1060808f2fe9c5c6a3183dde8000')],
    'rar20-solid.rar': [
        (4000, '3b18236852cb7dd43d027e87b7e11ca793e4a608df15f09a9bbb5a119af652c3'),
        (3000, '8733a7dae580602b5bbf2c199265f5bf884ea542618801372c1bd5ac7b03ac2c'),
        (3500, '445ec62ce9e27c9f752dddc1d906350720012014261072dee5dc7cec435a0cd9')],
    'rar26-lz-audio.rar': [
        (9998, 'f0bc83e91397965891393014c78cf130fa4a6265e9aa2e3d5fe5644e57018c9c')],
}


class TC(testcase.TestCase):
    @classmethod
    def setUpClass(cls):
        super(TC, cls).setUpClass()

        cls.backend = os.getenv('UNRAR_BACKEND', 'none')
        cls.path_rar = TC.path_source / 'unit_tests' / 'input' / 'other_scanfiles' / 'rar'

        cls.path_marker_db = TC.path_tmp / 'rar-marker.ndb'
        cls.path_marker_db.write_text('RAR_TEST_MARKER:0:*:{}\n'.format(MARKER.hex()))

        # Matches only at the start of a scanned object, so not in the raw
        # archive: proves the comment was handed to the scanner on its own.
        cls.path_marker_start_db = TC.path_tmp / 'rar-marker-start.ndb'
        cls.path_marker_start_db.write_text('RAR_TEST_MARKER_AT_START:0:0:{}\n'.format(MARKER.hex()))

    @classmethod
    def tearDownClass(cls):
        super(TC, cls).tearDownClass()

    def setUp(self):
        super(TC, self).setUp()
        if TC.backend == 'none':
            self.skipTest('Built without RAR support')

    def tearDown(self):
        super(TC, self).tearDown()
        self.verify_valgrind_log()

    def scan(self, testfile, options='', path_db=None):
        if path_db is None:
            path_db = TC.path_marker_db

        command = '{valgrind} {valgrind_args} {clamscan} {options} -d {path_db} {testfile}'.format(
            valgrind=TC.valgrind,
            valgrind_args=TC.valgrind_args,
            clamscan=TC.clamscan,
            options=options,
            path_db=path_db,
            testfile=testfile,
        )
        return self.execute_command(command)

    def test_every_compression_version_and_filter_extracts_exactly(self):
        self.step_name('Test RAR 2.9 filters and RAR5 filters extract byte for byte')

        for archive, entries in EXTRACTED.items():
            with self.subTest(archive=archive):
                path_db = TC.path_tmp / (archive + '.hsb')
                path_db.write_text(''.join(
                    '{}:{}:RAR_ENTRY_{}\n'.format(sha256, size, index)
                    for index, (size, sha256) in enumerate(entries)))

                output = self.scan(TC.path_rar / archive, '--allmatch', path_db=path_db)

                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=[
                    'RAR_ENTRY_{}.UNOFFICIAL FOUND'.format(index) for index in range(len(entries))])

    def test_compression_before_rar_2_9_is_extracted_by_unrar_only(self):
        self.step_name('Test RAR 1.5, 2.0 and 2.6 entries: extracted by unRAR, an extraction error without it')

        for archive, entries in EXTRACTED_BY_UNRAR_ONLY.items():
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive

                if TC.backend == 'rarlab':
                    path_db = TC.path_tmp / (archive + '.hsb')
                    path_db.write_text(''.join(
                        '{}:{}:RAR_ENTRY_{}\n'.format(sha256, size, index)
                        for index, (size, sha256) in enumerate(entries)))

                    output = self.scan(testfile, '--allmatch', path_db=path_db)

                    assert output.ec == 1  # virus
                    self.verify_output(output.out, expected=[
                        'RAR_ENTRY_{}.UNOFFICIAL FOUND'.format(index) for index in range(len(entries))])
                else:
                    # Nothing is extracted and nothing is reported as extracted:
                    # each entry fails with an error, never an empty success.
                    output = self.scan(testfile, '--debug')

                    assert output.ec == 0  # clean
                    self.verify_output(output.out, expected=['{}: OK'.format(testfile)])
                    assert (output.out + output.err).count('RAR: Error extracting file') >= len(entries)

    def test_entry_is_checked_against_its_checksum(self):
        self.step_name('Test an entry with one flipped data byte is not extracted as if it were intact')

        # One entry each: stored and compressed, RAR4 CRC32, RAR5 CRC32 and
        # RAR5 BLAKE2sp. The middle of each archive is entry data.
        archives = ('rar4-stored-checked.rar', 'rar4-compressed-checked.rar',
                    'rar5-stored-checked.rar', 'rar5-compressed-checked.rar',
                    'rar5-blake2-checked.rar', 'rar5-stored-blake2-checked.rar')
        for archive in archives:
            with self.subTest(archive=archive):
                intact = TC.path_rar / archive
                output = self.scan(intact, '--debug')
                assert output.ec == 0  # clean
                assert 'RAR: Extraction complete' in output.out + output.err
                assert 'RAR: Error extracting file' not in output.out + output.err

                if TC.backend == 'rarlab':
                    # unRAR hands over data whose checksum does not match, and it is scanned.
                    continue

                damaged = TC.path_tmp / ('damaged-' + archive)
                data = bytearray(intact.read_bytes())
                data[len(data) // 2] ^= 0x01
                damaged.write_bytes(data)

                output = self.scan(damaged, '--debug')
                assert output.ec == 0  # clean
                assert 'RAR: Error extracting file' in output.out + output.err
                assert 'RAR: Extraction complete' not in output.out + output.err

    def scan_damaged_copy(self, archive, offset, size, sha256, name):
        damaged = TC.path_tmp / name
        data = bytearray((TC.path_rar / archive).read_bytes())
        data[offset] ^= 0xFF
        damaged.write_bytes(data)

        path_db = TC.path_tmp / (name + '.hsb')
        path_db.write_text('{}:{}:RAR_ENTRY\n'.format(sha256, size))

        output = self.scan(damaged, path_db=path_db)
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_ENTRY.UNOFFICIAL FOUND'.format(damaged)])

    def test_rar5_entry_is_extracted_when_a_header_fails_its_check(self):
        self.step_name('Test the entry of a RAR5 archive is extracted when a header checksum or extra record is damaged')

        # rar5-compressed-checked.rar has one entry. Bytes 8 and 24 start the CRC32 of the main and the file header; byte 19 is in the main header's extra record. unRAR reads on past all three.
        for offset, name, (size, sha256) in (
            (8, 'main-crc', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
            (24, 'file-crc', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
            (19, 'main-extra', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
        ):
            with self.subTest(byte=name):
                self.scan_damaged_copy('rar5-compressed-checked.rar', offset, size, sha256, 'rar5-compressed-checked.rar-' + name)

    def test_rar4_entry_is_extracted_when_a_header_fails_its_check(self):
        self.step_name('Test the entry of a RAR 2.9 archive is extracted when a header field is damaged')

        # rar4-compressed-checked.rar has one entry. Bytes 7 and 20 start the CRC16 of the main and the file header, 35 is the file header's host OS, 45 its method and 46 the size of its name. unRAR reads on past all of them.
        for offset, name, (size, sha256) in (
            (7, 'main-crc', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
            (20, 'file-crc', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
            (35, 'host-os', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
            (45, 'method', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
            (46, 'name-size', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
        ):
            with self.subTest(byte=name):
                self.scan_damaged_copy('rar4-compressed-checked.rar', offset, size, sha256, 'rar4-compressed-checked.rar-' + name)

    def test_rar4_entry_ends_at_its_end_marker(self):
        self.step_name('Test a RAR 2.9 entry that declares more than it holds is extracted up to its end marker')

        # Byte 33 is part of the file header's unpacked size: flipped, the header declares 16 MB more than the entry holds. The data ends at its marker, as unRAR reads it, and its CRC32 still matches.
        for offset, name, (size, sha256) in (
            (33, 'size', (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')),
        ):
            with self.subTest(byte=name):
                self.scan_damaged_copy('rar4-compressed-checked.rar', offset, size, sha256, 'rar4-compressed-checked.rar-' + name)

    def test_rar4_header_declaring_an_impossible_size_reaches_the_limit(self):
        self.step_name('Test a RAR 2.9 file header that declares an impossible size is stopped by the size limit')

        # Byte 24 holds the high flags of the file header: flipped, they
        # declare a 64-bit size, a salt and extended flags that are not there,
        # so the unpacked size is read from the wrong bytes.
        damaged = TC.path_tmp / 'rar4-damaged-flags.rar'
        data = bytearray((TC.path_rar / 'rar4-compressed-checked.rar').read_bytes())
        data[24] ^= 0xFF
        damaged.write_bytes(data)

        output = self.scan(damaged, '--alert-exceeds-max=yes')
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: Heuristics.Limits.Exceeded.MaxScanSize FOUND'.format(damaged)])

    def test_rar4_data_decoded_before_damage_is_extracted(self):
        self.step_name('Test a RAR 2.9 entry with damaged data yields what was decoded before the damage')

        # Byte 69 is in the compressed data of the only entry: unRAR writes the first 2203 bytes before the damage stops it, and so does this backend.
        for offset, name, (size, sha256) in (
            (69, 'data', (2203, '0d6115a71f5b48e5653d632a76d307f6690ce14184fde7910995cecd52fc1a43')),
        ):
            with self.subTest(byte=name):
                self.scan_damaged_copy('rar4-compressed-checked.rar', offset, size, sha256, 'rar4-compressed-checked.rar-' + name)

    def test_solid_ppmd_stream_continues_across_entries(self):
        self.step_name('Test a solid RAR 2.9 PPMd stream is decoded entry after entry')

        testfile = TC.path_rar / 'rar4-solid-ppmd.rar'
        output = self.scan(testfile)

        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile)])

    def test_solid_entry_after_a_skipped_entry(self):
        self.step_name('Test the entry after one skipped for size in a solid archive')

        # big.txt exceeds --max-filesize and is skipped; marker.txt follows
        # it in the same solid stream. unRAR skips without decoding, so it
        # decodes marker.txt from the wrong window and misses the marker.
        # The libarchive backend decodes what it skips.
        for archive in ('rar4-solid-skip.rar', 'rar5-solid-skip.rar'):
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive
                output = self.scan(testfile, '--max-filesize=1M --max-scansize=10M')

                if TC.backend == 'rarlab':
                    assert output.ec == 0  # clean
                    self.verify_output(output.out, expected=['{}: OK'.format(testfile)])
                else:
                    assert output.ec == 1  # virus
                    self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile)])

    def test_pending_filter_does_not_reach_next_solid_entry(self):
        self.step_name('Test a filter pending at the end of a solid entry does not alter the next entry')

        # a.txt ends by defining the standard E8 filter for the range where
        # b.bin starts. Filters never span entries, so b.bin is extracted
        # unfiltered; applying the pending filter alters or fails it.
        path_db = TC.path_tmp / 'rar-pending-filter.hdb'
        path_db.write_text('1bfecfec1bd85b77b4fe53c6ec683d98:74:PendingFilterMarker\n')

        testfile = TC.path_rar / 'rar4-solid-pending-filter.rar'
        output = self.scan(testfile, path_db=path_db)

        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: PendingFilterMarker.UNOFFICIAL FOUND'.format(testfile)])

    def test_skipping_in_a_solid_archive_is_bounded(self):
        self.step_name('Test the work of skipping entries of a solid archive is bounded by the scan size')

        # big1.txt and big2.txt each exceed --max-filesize and are skipped;
        # marker.txt follows them in the same solid stream. The libarchive
        # backend decodes what it skips, which costs as much as scanning
        # it would, so --max-scansize bounds it: 3M leaves room for one of
        # them. The scan reports the limit instead of coming back clean.
        for archive in ('rar4-solid-skip-budget.rar', 'rar5-solid-skip-budget.rar'):
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive
                output = self.scan(testfile, '--max-filesize=1M --max-scansize=3M --alert-exceeds-max=yes')

                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=[
                    '{}: Heuristics.Limits.Exceeded.MaxFileSize FOUND'.format(testfile)])

    def test_archive_comment_is_scanned(self):
        self.step_name('Test RAR 2.9 (packed) and RAR5 archive comments are scanned')

        for archive in ('rar4-comment.rar', 'rar5-comment.rar'):
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive
                output = self.scan(testfile, path_db=TC.path_marker_start_db)

                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER_AT_START.UNOFFICIAL FOUND'.format(testfile)])

    def test_encrypted_data_and_headers(self):
        self.step_name('Test encrypted entries and encrypted headers alert as encrypted archives')

        for archive in ('rar4-encrypted-data.rar', 'rar4-encrypted-headers.rar',
                        'rar5-encrypted-data.rar', 'rar5-encrypted-headers.rar'):
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive

                output = self.scan(testfile, '--alert-encrypted-archive=yes')
                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=['{}: Heuristics.Encrypted.RAR FOUND'.format(testfile)])

                output = self.scan(testfile)
                assert output.ec == 0  # clean
                self.verify_output(output.out, expected=['{}: OK'.format(testfile)])

    def test_volume_set_is_read_across_volumes(self):
        self.step_name('Test a file split across volumes is scanned when the next volume is present')

        for prefix in ('rar4-volume', 'rar5-volume'):
            with self.subTest(volumes=prefix):
                path_set = TC.path_tmp / (prefix + '-set')
                path_set.mkdir()
                for part in ('part1', 'part2'):
                    shutil.copy(str(TC.path_rar / '{}.{}.rar'.format(prefix, part)), str(path_set))
                testfile = path_set / (prefix + '.part1.rar')

                output = self.scan(testfile)
                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile)])

    def test_lone_volume(self):
        self.step_name('Test the first volume alone: a file split into the missing volume is not scanned')

        # As with unRAR: extracting the split file fails with a volume open
        # error, libclamav does not scan the partial file and stops reading
        # the archive.
        for prefix in ('rar4-volume', 'rar5-volume'):
            with self.subTest(volumes=prefix):
                path_lone = TC.path_tmp / (prefix + '-lone')
                path_lone.mkdir()
                shutil.copy(str(TC.path_rar / (prefix + '.part1.rar')), str(path_lone))
                testfile = path_lone / (prefix + '.part1.rar')

                output = self.scan(testfile)
                assert output.ec == 0  # clean
                self.verify_output(output.out, expected=['{}: OK'.format(testfile)])
