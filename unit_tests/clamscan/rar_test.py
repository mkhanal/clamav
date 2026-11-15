# Copyright (C) 2026 Mridul Khanal. All rights reserved.

"""
Run clamscan RAR tests.

The same expectations hold for both RAR backends (RARLAB unRAR and
libarchive), except where noted: every expected hash below is what unRAR
extracts.
"""

import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import rar5_craft
import testcase

MARKER = b'ClamAV-RAR-backend-test-marker-6f1c2e'

# What the entry of each RAR5 fixture extracts to: (size, SHA-256).
COMPRESSED_ENTRY = (15136, '9b1cfc324fbe01ca57464a1429548edace6ce6d4efaf722702aefa132975d3e2')
STORED_ENTRY = (4000, 'c98ce101b24950ffda930e9bb352eb2caf478ba84b56648fe80528ba71f7eab0')

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
    # RAR 2.0 and 2.6 compression, including multimedia (audio) blocks and
    # solid streams.
    'rar20-lz-text.rar': [
        (20000, '8f026544474ace34d7c3c1744620611d32f9eb9d533521f948f1c9f75367538e')],
    'rar20-audio-1ch.rar': [
        (6000, 'ad1d689c1feca9b72b958fc9d07cf91b0c659ee4c6b1bc41b7b17f0f0fc2a9bf')],
    'rar20-audio-4ch.rar': [
        (6000, '081202b2c7e6e24cee2ffe0c106f2167f742d89bb8253bc96c8471d6e8e0d176')],
    'rar20-block-switches.rar': [
        (12000, '2e073b467b48ed65da8cc07906a96c4b069b1060808f2fe9c5c6a3183dde8000')],
    'rar26-lz-audio.rar': [
        (9998, 'f0bc83e91397965891393014c78cf130fa4a6265e9aa2e3d5fe5644e57018c9c')],
    # RAR5 filters.
    'rar5-filter-delta.rar': [
        (48000, '283fea56571bf5b805b7d3c3fefa48eb24f44ce9f2c8d031df4a8b8239ae4109')],
    'rar5-filter-e8.rar': [
        (9044, '42ad3a48597bf100702812ad1c18b57dba1fab10f35401b6d6070b335b26057f')],
}

# RAR 1.5 compression, as RARLAB unRAR extracts it. The libarchive backend has
# no decoder for it.
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
}

# RARLAB RAR 2.50 for DOS archives: size and SHA-256 of every entry of 3 bytes or more,
# as the RARLAB backend extracts it. Provenance and command lines: README.md.
RAR_250 = {
    'rar250-m3.rar': [
        ('TEXT.TXT', 30000, 'ad04f3359e61af141c54b2ac82a53e01c43c525f653d317e0352ce87d9f72f32'),
        ('S00.TXT', 19, 'caa269687e00dee0fd0c061aa3860dfcdc75c90229db2b93d2a5edcba639a3e8'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('S03.TXT', 596, '28638542b2aa0649c3d2e23bb34171b6590cd77cfd23a2c965f277300093fb01'),
        ('S04.TXT', 1639, 'c45822f85fce60efc6cfa973c31a32ed0b3903d58b8688c95d14be6a1b24a8e0'),
        ('S05.TXT', 155, 'c2a9fcf3205dd032ffb938b09f686c98a374a625ea8bbcc8f9b0831467e0bb06'),
        ('S06.TXT', 1185, '35b5787ea78e464309b02da9f1660015997d4073349a4210a97169f180b0cfcf'),
    ],
    'rar250-solid-m1.rar': [
        ('TEXT.TXT', 30000, 'ad04f3359e61af141c54b2ac82a53e01c43c525f653d317e0352ce87d9f72f32'),
        ('S00.TXT', 19, 'caa269687e00dee0fd0c061aa3860dfcdc75c90229db2b93d2a5edcba639a3e8'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('S03.TXT', 596, '28638542b2aa0649c3d2e23bb34171b6590cd77cfd23a2c965f277300093fb01'),
        ('S04.TXT', 1639, 'c45822f85fce60efc6cfa973c31a32ed0b3903d58b8688c95d14be6a1b24a8e0'),
        ('S05.TXT', 155, 'c2a9fcf3205dd032ffb938b09f686c98a374a625ea8bbcc8f9b0831467e0bb06'),
        ('S06.TXT', 1185, '35b5787ea78e464309b02da9f1660015997d4073349a4210a97169f180b0cfcf'),
    ],
    'rar250-solid-m2.rar': [
        ('TEXT.TXT', 30000, 'ad04f3359e61af141c54b2ac82a53e01c43c525f653d317e0352ce87d9f72f32'),
        ('S00.TXT', 19, 'caa269687e00dee0fd0c061aa3860dfcdc75c90229db2b93d2a5edcba639a3e8'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('S03.TXT', 596, '28638542b2aa0649c3d2e23bb34171b6590cd77cfd23a2c965f277300093fb01'),
        ('S04.TXT', 1639, 'c45822f85fce60efc6cfa973c31a32ed0b3903d58b8688c95d14be6a1b24a8e0'),
        ('S05.TXT', 155, 'c2a9fcf3205dd032ffb938b09f686c98a374a625ea8bbcc8f9b0831467e0bb06'),
        ('S06.TXT', 1185, '35b5787ea78e464309b02da9f1660015997d4073349a4210a97169f180b0cfcf'),
    ],
    'rar250-solid-m3.rar': [
        ('TEXT.TXT', 30000, 'ad04f3359e61af141c54b2ac82a53e01c43c525f653d317e0352ce87d9f72f32'),
        ('S00.TXT', 19, 'caa269687e00dee0fd0c061aa3860dfcdc75c90229db2b93d2a5edcba639a3e8'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('S03.TXT', 596, '28638542b2aa0649c3d2e23bb34171b6590cd77cfd23a2c965f277300093fb01'),
        ('S04.TXT', 1639, 'c45822f85fce60efc6cfa973c31a32ed0b3903d58b8688c95d14be6a1b24a8e0'),
        ('S05.TXT', 155, 'c2a9fcf3205dd032ffb938b09f686c98a374a625ea8bbcc8f9b0831467e0bb06'),
        ('S06.TXT', 1185, '35b5787ea78e464309b02da9f1660015997d4073349a4210a97169f180b0cfcf'),
    ],
    'rar250-solid-m5.rar': [
        ('TEXT.TXT', 30000, 'ad04f3359e61af141c54b2ac82a53e01c43c525f653d317e0352ce87d9f72f32'),
        ('S00.TXT', 19, 'caa269687e00dee0fd0c061aa3860dfcdc75c90229db2b93d2a5edcba639a3e8'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('S03.TXT', 596, '28638542b2aa0649c3d2e23bb34171b6590cd77cfd23a2c965f277300093fb01'),
        ('S04.TXT', 1639, 'c45822f85fce60efc6cfa973c31a32ed0b3903d58b8688c95d14be6a1b24a8e0'),
        ('S05.TXT', 155, 'c2a9fcf3205dd032ffb938b09f686c98a374a625ea8bbcc8f9b0831467e0bb06'),
        ('S06.TXT', 1185, '35b5787ea78e464309b02da9f1660015997d4073349a4210a97169f180b0cfcf'),
    ],
    'rar250-solid-mm.rar': [
        ('MONO8.WAV', 24000, 'bd2bef53c0e089b2be0c4f17665cfe62f6b493edaa529fb3e4577351a8ef601d'),
        ('QUAD.RAW', 20000, 'f4c3c4e77735bad89fd780401e5c7028a7762aaf52ca20c8914ebe40ba49ca08'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('RAND.BIN', 12000, '0bb8ce60776d61f4e23c42ef81b8ea60a08fe60d06d582aebd93b0bb7d7cf90a'),
    ],
    'rar250-mm-m5.rar': [
        ('MONO8.WAV', 24000, 'bd2bef53c0e089b2be0c4f17665cfe62f6b493edaa529fb3e4577351a8ef601d'),
        ('QUAD.RAW', 20000, 'f4c3c4e77735bad89fd780401e5c7028a7762aaf52ca20c8914ebe40ba49ca08'),
        ('TEXT.TXT', 30000, 'ad04f3359e61af141c54b2ac82a53e01c43c525f653d317e0352ce87d9f72f32'),
    ],
    'rar250-solid-small.rar': [
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('S03.TXT', 596, '28638542b2aa0649c3d2e23bb34171b6590cd77cfd23a2c965f277300093fb01'),
        ('S04.TXT', 1639, 'c45822f85fce60efc6cfa973c31a32ed0b3903d58b8688c95d14be6a1b24a8e0'),
    ],
    'rar250-solid-volumes.rar': [
        ('RAND.BIN', 12000, '0bb8ce60776d61f4e23c42ef81b8ea60a08fe60d06d582aebd93b0bb7d7cf90a'),
        ('TEXT.TXT', 30000, 'ad04f3359e61af141c54b2ac82a53e01c43c525f653d317e0352ce87d9f72f32'),
        ('S00.TXT', 19, 'caa269687e00dee0fd0c061aa3860dfcdc75c90229db2b93d2a5edcba639a3e8'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
        ('S02.TXT', 2076, 'f18aeddb63f95eb3cba920265dde81fd8cdacf984d40e81e3bed9322103666ff'),
        ('S03.TXT', 596, '28638542b2aa0649c3d2e23bb34171b6590cd77cfd23a2c965f277300093fb01'),
        ('S04.TXT', 1639, 'c45822f85fce60efc6cfa973c31a32ed0b3903d58b8688c95d14be6a1b24a8e0'),
        ('S05.TXT', 155, 'c2a9fcf3205dd032ffb938b09f686c98a374a625ea8bbcc8f9b0831467e0bb06'),
        ('S06.TXT', 1185, '35b5787ea78e464309b02da9f1660015997d4073349a4210a97169f180b0cfcf'),
    ],
    'rar250-split.rar': [
        ('MONO8.WAV', 24000, 'bd2bef53c0e089b2be0c4f17665cfe62f6b493edaa529fb3e4577351a8ef601d'),
        ('S01.TXT', 1028, '711b45042255cd1101053800d87991c20e78cc00040a6f4b623162a1c43be097'),
    ],
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

    def scan(self, testfile, options='', path_db=None, memory_limit_kb=None):
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
        if memory_limit_kb is not None:
            command = 'ulimit -v {} && {}'.format(memory_limit_kb, command)
        return self.execute_command(command)

    def test_every_compression_version_and_filter_extracts_exactly(self):
        self.step_name('Test RAR 2.0 / 2.6 compression, RAR 2.9 filters and RAR5 filters extract byte for byte')

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

    def test_rar_1_5_compression_is_extracted_by_unrar_only(self):
        self.step_name('Test RAR 1.5 entries: extracted by unRAR, an extraction error without it')

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
                    self.verify_output(output.out, expected=['{}: OK'.format(testfile.name)])
                    assert (output.out + output.err).count('RAR: Error extracting file') >= len(entries)

                    # Without the alert the archive is clean; with it, it is not.
                    self.assert_incomplete_alert_only_when_enabled(testfile)

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

                # unRAR hands over data whose checksum does not match, and it
                # is scanned; so is it with the libarchive backend.
                damaged = TC.path_tmp / ('damaged-' + archive)
                data = bytearray(intact.read_bytes())
                data[len(data) // 2] ^= 0x01
                damaged.write_bytes(data)

                output = self.scan(damaged, '--debug')
                assert output.ec == 0  # clean
                assert 'RAR: Extraction complete' in output.out + output.err
                assert 'RAR: Error extracting file' not in output.out + output.err

                self.assert_incomplete_alert_only_when_enabled(damaged)

    def scan_damaged_copy(self, archive, offset, size, sha256, name):
        damaged = TC.path_tmp / name
        data = bytearray((TC.path_rar / archive).read_bytes())
        data[offset] ^= 0xFF
        damaged.write_bytes(data)

        path_db = TC.path_tmp / (name + '.hsb')
        path_db.write_text('{}:{}:RAR_ENTRY\n'.format(sha256, size))

        output = self.scan(damaged, path_db=path_db)
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_ENTRY.UNOFFICIAL FOUND'.format(damaged.name)])

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
        self.verify_output(output.out, expected=['{}: Heuristics.Limits.Exceeded.MaxScanSize FOUND'.format(damaged.name)])

    def test_rar4_data_decoded_before_damage_is_extracted(self):
        self.step_name('Test a RAR 2.9 entry with damaged data yields what was decoded before the damage')

        # Byte 69 is in the compressed data of the only entry: unRAR writes the first 2203 bytes before the damage stops it, and so does this backend.
        for offset, name, (size, sha256) in (
            (69, 'data', (2203, '0d6115a71f5b48e5653d632a76d307f6690ce14184fde7910995cecd52fc1a43')),
        ):
            with self.subTest(byte=name):
                self.scan_damaged_copy('rar4-compressed-checked.rar', offset, size, sha256, 'rar4-compressed-checked.rar-' + name)

    def test_solid_entry_after_one_failing_its_checksum(self):
        self.step_name('Test the entry after one that fails its checksum in a solid RAR 2.9 archive')

        # Byte 36 is the CRC32 of d/1-text.txt. Its data is intact, so the
        # stream carries on and d/2-marker.txt, which holds the marker, is
        # extracted.
        damaged = TC.path_tmp / 'rar4-solid-ppmd-damaged-crc.rar'
        data = bytearray((TC.path_rar / 'rar4-solid-ppmd.rar').read_bytes())
        data[36] ^= 0xFF
        damaged.write_bytes(data)

        output = self.scan(damaged)
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(damaged.name)])

    def test_rar5_entry_with_damaged_tables_yields_what_was_decoded(self):
        self.step_name('Test a RAR5 entry that stops at bad Huffman tables yields what was decoded before them')

        # Libarchive's rar5-bad-tables.rar declares 64 bytes and stops after 34. It is
        # extracted by unRAR the same way.
        path_db = TC.path_tmp / 'rar5-bad-tables.hsb'
        path_db.write_text('eb142b0cae0baa72a767ebc0823d1be94e14c5bfc52d8e417fc4302fceb6240c:34:RAR_ENTRY\n')

        testfile = TC.path_rar / 'rar5-bad-tables.rar'
        output = self.scan(testfile, path_db=path_db)
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_ENTRY.UNOFFICIAL FOUND'.format(testfile.name)])

    def test_rar5_data_decoded_before_damage_is_extracted(self):
        self.step_name('Test a RAR5 entry with damaged data yields what was decoded before the damage')

        # Byte 77 is in the compressed data of the only entry: unRAR writes the first 4727 bytes before the damage stops it, and so does this backend.
        for offset, name, (size, sha256) in (
            (77, 'data', (4727, '627951f5d4a5f0a3e6219fbbf6ab91b6c2ebfae079a6daa1aa896c6e9a0eadcf')),
        ):
            with self.subTest(byte=name):
                self.scan_damaged_copy('rar5-compressed-checked.rar', offset, size, sha256, 'rar5-compressed-checked.rar-' + name)

    def test_archive_whose_header_failed_its_check_ends_in_an_error(self):
        self.step_name('Test the entry of an archive whose header checksum is wrong is scanned and the archive ends in an error')

        # unRAR extracts the entry, then reports an error at the end of the
        # archive; so does this backend.
        for archive, offset in (('rar4-compressed-checked.rar', 20), ('rar5-compressed-checked.rar', 24)):
            with self.subTest(archive=archive):
                damaged = TC.path_tmp / ('damaged-header-' + archive)
                data = bytearray((TC.path_rar / archive).read_bytes())
                data[offset] ^= 0xFF
                damaged.write_bytes(data)

                output = self.scan(damaged, '--debug')
                assert output.ec == 0  # clean
                assert 'RAR: Extraction complete' in output.out + output.err
                assert re.search(r'RAR: Error \(\d+\) reading file header', output.out + output.err)

    def test_archive_without_a_valid_header_is_not_a_clean_end(self):
        self.step_name('Test an archive with a signature but no valid header is an error, an empty archive is not')

        # The libarchive backend reports an archive that has a signature and
        # no valid main header, or a header it cannot read, as an error
        # reading the header; an empty archive, with a valid main header and
        # no entries, is read to its end.
        for archive in ('rar4-signature-only.rar', 'rar5-signature-only.rar', 'rar5-truncated-header.rar'):
            with self.subTest(archive=archive):
                output = self.scan(TC.path_rar / archive, '--debug')
                assert output.ec == 0  # clean
                if TC.backend == 'rarlab':
                    assert 'RAR: No more files in archive' in output.out + output.err
                else:
                    assert re.search(r'RAR: Error \(\d+\) reading file header', output.out + output.err)

        for archive in ('rar4-empty.rar', 'rar5-empty.rar'):
            with self.subTest(archive=archive):
                output = self.scan(TC.path_rar / archive, '--debug')
                assert output.ec == 0  # clean
                assert 'RAR: No more files in archive' in output.out + output.err
                assert 'reading file header' not in output.out + output.err

    def test_rar_2_50_archives_extract_exactly(self):
        self.step_name('Test archives written by RAR 2.50 extract byte for byte, solid or not, in every method')

        for archive, entries in RAR_250.items():
            with self.subTest(archive=archive):
                path_db = TC.path_tmp / (archive + '.hsb')
                path_db.write_text(''.join(
                    '{}:{}:RAR250_{}\n'.format(sha256, size, name.replace('.', '_'))
                    for name, size, sha256 in entries))

                output = self.scan(TC.path_rar / archive, '--allmatch', path_db=path_db)

                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=[
                    'RAR250_{}.UNOFFICIAL FOUND'.format(name.replace('.', '_')) for name, _, _ in entries])
                assert 'RAR: Error extracting file' not in output.out + output.err

    def test_solid_entry_with_an_oversized_unpacked_size_is_rejected_without_overflow(self):
        self.step_name('Test a solid RAR 2.0 entry declaring an unpacked size near INT64_MAX is rejected cleanly')

        testfile = TC.path_rar / 'rar250-solid-size-overflow.rar'
        output = self.scan(testfile, '--debug')

        assert output.ec in (0, 1)
        assert 'runtime error' not in output.out + output.err

    def test_damaged_rar_2_0_data_is_not_extracted_as_intact(self):
        self.step_name('Test RAR 2.0 / 2.6 data with one flipped byte never yields the intact entry')

        # Like unRAR, a damaged stream that still decodes is handed over and scanned
        # without an error, and one that cannot be decoded keeps what came before.
        for archive in ('rar20-lz-text.rar', 'rar20-audio-1ch.rar', 'rar20-audio-4ch.rar',
                        'rar20-block-switches.rar', 'rar26-lz-audio.rar'):
            with self.subTest(archive=archive):
                data = bytearray((TC.path_rar / archive).read_bytes())
                data[len(data) // 2] ^= 0x01
                damaged = TC.path_tmp / ('damaged-' + archive)
                damaged.write_bytes(data)

                path_db = TC.path_tmp / ('damaged-' + archive + '.hsb')
                path_db.write_text(''.join(
                    '{}:{}:RAR_ENTRY_{}\n'.format(sha256, size, index)
                    for index, (size, sha256) in enumerate(EXTRACTED[archive])))

                output = self.scan(damaged, '--debug', path_db=path_db)
                assert output.ec == 0  # clean: the damaged entry is not the intact one
                assert 'runtime error' not in output.out + output.err

    def test_solid_ppmd_stream_continues_across_entries(self):
        self.step_name('Test a solid RAR 2.9 PPMd stream is decoded entry after entry')

        testfile = TC.path_rar / 'rar4-solid-ppmd.rar'
        output = self.scan(testfile)

        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile.name)])

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
                    self.verify_output(output.out, expected=['{}: OK'.format(testfile.name)])
                else:
                    assert output.ec == 1  # virus
                    self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile.name)])

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
        self.verify_output(output.out, expected=['{}: PendingFilterMarker.UNOFFICIAL FOUND'.format(testfile.name)])

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
                    '{}: Heuristics.Limits.Exceeded.MaxFileSize FOUND'.format(testfile.name)])

                # Exceeding the limit is reported as that, never as an incomplete archive.
                if TC.backend == 'libarchive':
                    output = self.scan(testfile, '--max-filesize=1M --max-scansize=3M --alert-exceeds-max=yes --alert-incomplete-rar=yes')
                    assert output.ec == 1  # virus
                    assert 'Heuristics.Incomplete.RAR' not in output.out
                    assert 'Heuristics.Limits.Exceeded' in output.out

                    output = self.scan(testfile, '--max-filesize=1M --max-scansize=3M --alert-incomplete-rar=yes')
                    assert 'Heuristics.Incomplete.RAR' not in output.out

    def test_archive_comment_is_scanned(self):
        self.step_name('Test RAR 2.9 (packed) and RAR5 archive comments are scanned')

        for archive in ('rar4-comment.rar', 'rar5-comment.rar'):
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive
                output = self.scan(testfile, path_db=TC.path_marker_start_db)

                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER_AT_START.UNOFFICIAL FOUND'.format(testfile.name)])

    def test_encrypted_data_and_headers(self):
        self.step_name('Test encrypted entries and encrypted headers alert as encrypted archives')

        for archive in ('rar4-encrypted-data.rar', 'rar4-encrypted-headers.rar',
                        'rar5-encrypted-data.rar', 'rar5-encrypted-headers.rar'):
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive

                output = self.scan(testfile, '--alert-encrypted-archive=yes')
                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=['{}: Heuristics.Encrypted.RAR FOUND'.format(testfile.name)])

                output = self.scan(testfile)
                assert output.ec == 0  # clean
                self.verify_output(output.out, expected=['{}: OK'.format(testfile.name)])

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
                self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile.name)])

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
                self.verify_output(output.out, expected=['{}: OK'.format(testfile.name)])

    def scan_incomplete(self, testfile, enabled):
        return self.scan(testfile, '--alert-incomplete-rar=yes' if enabled else '')

    def assert_incomplete_alert_only_when_enabled(self, testfile):
        output = self.scan_incomplete(testfile, True)
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: Heuristics.Incomplete.RAR FOUND'.format(testfile.name)])

        output = self.scan_incomplete(testfile, False)
        assert output.ec == 0  # clean
        self.verify_output(output.out, expected=['{}: OK'.format(testfile.name)])

    def test_incomplete_alert_for_a_lone_volume(self):
        self.step_name('Test the first volume of a set alone alerts as incomplete only when enabled')

        for prefix in ('rar4-volume', 'rar5-volume'):
            with self.subTest(volumes=prefix):
                path_lone = TC.path_tmp / (prefix + '-lone-incomplete')
                path_lone.mkdir()
                shutil.copy(str(TC.path_rar / (prefix + '.part1.rar')), str(path_lone))

                self.assert_incomplete_alert_only_when_enabled(path_lone / (prefix + '.part1.rar'))

    def test_incomplete_alert_for_a_truncated_archive(self):
        self.step_name('Test a truncated archive alerts as incomplete only when enabled')

        for archive in ('rar20-lz-text.rar', 'rar4-filter-e8.rar', 'rar5-filter-delta.rar'):
            with self.subTest(archive=archive):
                data = (TC.path_rar / archive).read_bytes()
                testfile = TC.path_tmp / ('truncated-' + archive)
                testfile.write_bytes(data[:len(data) // 2])

                self.assert_incomplete_alert_only_when_enabled(testfile)

    def test_incomplete_alert_for_a_corrupt_archive(self):
        self.step_name('Test an archive without a readable header alerts as incomplete only when enabled')

        signatures = {
            'rar4': b'Rar!\x1a\x07\x00',
            'rar5': b'Rar!\x1a\x07\x01\x00',
        }
        for name, signature in signatures.items():
            with self.subTest(archive=name):
                testfile = TC.path_tmp / (name + '-garbage-after-signature.rar')
                testfile.write_bytes(signature + b'\xaa' * 64)

                self.assert_incomplete_alert_only_when_enabled(testfile)

    def test_incomplete_alert_for_damaged_data(self):
        self.step_name('Test an entry whose data is damaged alerts as incomplete only when enabled')

        for archive in ('rar4-filter-e8.rar', 'rar5-filter-delta.rar'):
            with self.subTest(archive=archive):
                data = bytearray((TC.path_rar / archive).read_bytes())
                data[len(data) // 2] ^= 0xff
                testfile = TC.path_tmp / ('damaged-' + archive)
                testfile.write_bytes(bytes(data))

                self.assert_incomplete_alert_only_when_enabled(testfile)

    def test_no_incomplete_alert_for_a_complete_archive(self):
        self.step_name('Test archives whose contents were all scanned are not reported as incomplete')

        archives = ['rar4-solid-ppmd.rar', 'rar5-filter-delta.rar', 'rar4-comment.rar', 'rar5-comment.rar']
        if TC.backend == 'rarlab':
            archives += ['rar15-small.rar', 'rar20-solid.rar']
        for archive in archives:
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive

                output = self.scan(testfile, '--alert-incomplete-rar=yes')
                assert 'Heuristics.Incomplete.RAR' not in output.out

        path_set = TC.path_tmp / 'rar5-volume-complete-set'
        path_set.mkdir()
        for part in ('part1', 'part2'):
            shutil.copy(str(TC.path_rar / 'rar5-volume.{}.rar'.format(part)), str(path_set))
        output = self.scan(path_set / 'rar5-volume.part1.rar', '--alert-incomplete-rar=yes')
        assert 'Heuristics.Incomplete.RAR' not in output.out

    def test_incomplete_alert_does_not_report_encrypted_archives(self):
        self.step_name('Test encrypted archives are left to the encrypted archive alert')

        testfile = TC.path_rar / 'rar4-encrypted-data.rar'
        output = self.scan(testfile, '--alert-incomplete-rar=yes')
        assert output.ec == 0  # clean
        self.verify_output(output.out, expected=['{}: OK'.format(testfile.name)])

        output = self.scan(testfile, '--alert-incomplete-rar=yes --alert-encrypted-archive=yes')
        self.verify_output(output.out, expected=['{}: Heuristics.Encrypted.RAR FOUND'.format(testfile.name)])

    def write_rar5(self, name, archive):
        path = TC.path_tmp / name
        path.write_bytes(archive.build())
        return path

    def assert_entry_found(self, testfile, entry, options=''):
        size, sha256 = entry
        path_db = TC.path_tmp / (sha256 + '.hsb')
        path_db.write_text('{}:{}:RAR_ENTRY\n'.format(sha256, size))

        output = self.scan(testfile, options, path_db=path_db)
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_ENTRY.UNOFFICIAL FOUND'.format(testfile.name)])

    def test_malformed_redirect_record_does_not_make_the_entry_a_link(self):
        self.step_name('Test an entry whose redirect record is malformed is extracted and scanned, not skipped as a link')

        # unRAR takes any redirect record with a type for a link and does not
        # unpack the entry. This backend only does when the record is whole,
        # so what a malformed one is attached to is scanned.
        if TC.backend != 'libarchive':
            self.skipTest('The RARLAB backend skips the entry')

        symlink = rar5_craft.vint(1)
        for name, record in (
            ('empty-target', symlink + rar5_craft.vint(0) + rar5_craft.vint(0)),
            ('target-beyond-record', symlink + rar5_craft.vint(0) + rar5_craft.vint(40) + b'abc'),
            ('target-too-long', symlink + rar5_craft.vint(0) + rar5_craft.vint(5000) + b'a' * 5000),
            ('without-target', symlink + rar5_craft.vint(0)),
            ('type-only', symlink),
        ):
            with self.subTest(record=name):
                archive = rar5_craft.Archive((TC.path_rar / 'rar5-compressed-checked.rar').read_bytes())
                header = archive.files()[0].header()
                header.set_records(header.records() + [(rar5_craft.EXTRA_REDIR, record)])
                archive.files()[0].body = header.build()

                self.assert_entry_found(self.write_rar5('redirect-' + name + '.rar', archive), COMPRESSED_ENTRY)

    def assert_both_entries_found(self, name, archive, complete):
        testfile = self.write_rar5(name, archive)
        for entry in (COMPRESSED_ENTRY, STORED_ENTRY):
            self.assert_entry_found(testfile, entry)

        if complete:
            output = self.scan(testfile, '--alert-incomplete-rar=yes')
            assert 'Heuristics.Incomplete.RAR' not in output.out

    def split_zeros_entry(self, name, declared_size, continuation_size, continuation_unknown, pieces=2):
        """The 600 MB entry of zeros, its data cut in two pieces, as the volumes of a set hold it."""
        archive = rar5_craft.Archive((TC.path_rar / 'rar5-unknown-size-600m.rar').read_bytes())
        block = archive.files()[0]
        data = block.data
        cut = len(data) // pieces

        first = block.header()
        first.flags |= rar5_craft.HFL_SPLIT_AFTER
        first.data_size = cut
        first.unpacked_size = declared_size
        first.file_flags &= ~(rar5_craft.FILE_CRC32 | rar5_craft.FILE_UNKNOWN_SIZE)
        first.crc = None

        second = block.header()
        second.flags |= rar5_craft.HFL_SPLIT_BEFORE
        second.data_size = len(data) - cut
        second.unpacked_size = continuation_size
        second.file_flags &= ~(rar5_craft.FILE_CRC32 | rar5_craft.FILE_UNKNOWN_SIZE)
        second.crc = None
        if continuation_unknown:
            second.file_flags |= rar5_craft.FILE_UNKNOWN_SIZE

        index = archive.blocks.index(block)
        archive.blocks[index:index + 1] = [
            rar5_craft.Block(first.build(), data[:cut]),
            rar5_craft.Block(second.build(), data[cut:])]
        return self.write_rar5(name, archive)

    def test_continuation_header_does_not_change_what_the_entry_declared(self):
        self.step_name('Test a continuation header cannot lift the declared size of an entry past the scan limits')

        # The first header declares 1000 bytes; the header of the piece in the
        # next volume says the size is unknown. Decoding stops at 1000 bytes,
        # as unRAR writes no more, instead of running on through 600 MB.
        if TC.backend != 'libarchive':
            self.skipTest('The RARLAB backend is not bounded by this')

        testfile = self.split_zeros_entry('continuation-unknown-size.rar', 1000, 629145600, True)

        start = time.monotonic()
        output = self.scan(testfile, '--max-filesize=2000M --max-scansize=4000M --max-scantime=100 --alert-exceeds-max=yes')
        elapsed = time.monotonic() - start

        assert output.ec == 0, output.out  # clean: nothing exceeded a limit
        self.verify_output(output.out, expected=['{}: OK'.format(testfile.name)])
        assert elapsed < 5, 'decoding ran on for {:.1f} s past a scan time limit of 100 ms'.format(elapsed)

    def test_block_spanning_two_volumes_is_decoded_in_full(self):
        self.step_name('Test a compressed block that spans two volumes is decoded to the end of the entry')

        # Each cut of the data lands inside a block of this entry. The 600 MB
        # of zeros are found only when the whole entry is decoded; an entry
        # that ended early and cleanly would not be, nor would it be reported
        # as incomplete.
        if TC.backend != 'libarchive':
            self.skipTest('The RARLAB backend reads volumes with its own reader')

        digest = hashlib.sha256()
        zeros = bytes(1 << 20)
        for _ in range(600):
            digest.update(zeros)
        path_db = TC.path_tmp / 'zeros-600m.hsb'
        path_db.write_text('{}:629145600:RAR_ZEROS\n'.format(digest.hexdigest()))

        for pieces in (2, 3, 5, 7):
            with self.subTest(pieces=pieces):
                testfile = self.split_zeros_entry('split-block-{}.rar'.format(pieces), 629145600, 629145600, False, pieces)

                output = self.scan(testfile, '--max-filesize=2000M --max-scansize=4000M --alert-incomplete-rar=yes', path_db=path_db)
                assert output.ec == 1, output.out  # virus
                self.verify_output(output.out, expected=['{}: RAR_ZEROS.UNOFFICIAL FOUND'.format(testfile.name)])

    def test_rar5_entry_data_starts_at_the_end_of_its_header(self):
        self.step_name('Test the data of a RAR5 entry and the headers after it are read from the end of its header')

        # The data follows the header block, wherever the fields in it end.
        # unRAR reads both entries of each archive; so does this backend. A
        # record that does not hold what its kind needs is left out of the
        # entry by this backend, while unRAR reads the bytes after it: the
        # archive is then not reported as complete by unRAR, but is by this
        # backend only for the records it understood.
        zeros = bytes(16)
        for name, complete, edit in (
            ('padding-after-name', True, lambda h: setattr(h, 'padding', zeros)),
            ('padding-after-extra', True, lambda h: setattr(h, 'trailer', zeros)),
            ('padding-around-extra', True, lambda h: (setattr(h, 'padding', zeros), setattr(h, 'trailer', zeros))),
            ('hash-record-too-short', False, lambda h: h.set_records([(2, rar5_craft.vint(0) + bytes(10))] + h.records())),
            ('time-record-too-short', False, lambda h: h.set_records([(3, rar5_craft.vint(0x0b))] + h.records())),
            ('record-longer-than-area', False, lambda h: setattr(h, 'extra', h.extra + rar5_craft.vint(50) + rar5_craft.vint(7))),
        ):
            with self.subTest(header=name):
                archive = rar5_craft.Archive.join(
                    (TC.path_rar / 'rar5-compressed-checked.rar').read_bytes(),
                    (TC.path_rar / 'rar5-stored-checked.rar').read_bytes())
                archive.edit_file(0, edit)
                self.assert_both_entries_found('header-' + name + '.rar', archive, complete)

    def entry_is_found(self, testfile, entry):
        size, sha256 = entry
        path_db = TC.path_tmp / (sha256 + '.hsb')
        path_db.write_text('{}:{}:RAR_ENTRY\n'.format(sha256, size))

        output = self.scan(testfile, path_db=path_db)
        return 'FOUND' in output.out

    def test_rar5_entry_with_a_header_the_reader_refuses_does_not_end_the_archive(self):
        self.step_name('Test the entries after one whose RAR5 header is refused are still scanned')

        # What unRAR extracts, this backend extracts, whatever the header of the
        # first entry declares: a solid entry with no window before it, a
        # dictionary of up to 4 GB or a name of any length. Where unRAR cannot
        # extract the entry (no name, no data declared), the entry after it is
        # still scanned and the archive is not reported as complete.
        both = (COMPRESSED_ENTRY, STORED_ENTRY)
        for name, main_flags, edit, found, complete in (
            ('solid-without-window', None, lambda h: h.set_compression(solid=True), both, True),
            ('solid-without-window-in-solid-archive', 4, lambda h: h.set_compression(solid=True), both, True),
            ('dictionary-128M', None, lambda h: h.set_compression(dictionary=10), both, True),
            ('dictionary-1G', None, lambda h: h.set_compression(dictionary=13), both, True),
            ('dictionary-4G', None, lambda h: h.set_compression(dictionary=15), both, True),
            ('solid-dictionary-1G', 4, lambda h: h.set_compression(dictionary=13), both, True),
            ('name-of-3000-bytes', None, lambda h: setattr(h, 'name', b'a' * 3000), both, True),
            ('no-name', None, lambda h: setattr(h, 'name', b''), (STORED_ENTRY,), False),
            ('no-data-declared', None, lambda h: (setattr(h, 'has_data', False), setattr(h, 'data_size', 0)), (STORED_ENTRY,), False),
        ):
            with self.subTest(header=name):
                archive = rar5_craft.Archive.join(
                    (TC.path_rar / 'rar5-compressed-checked.rar').read_bytes(),
                    (TC.path_rar / 'rar5-stored-checked.rar').read_bytes())
                if main_flags is not None:
                    archive.set_main_flags(main_flags)
                archive.edit_file(0, edit)
                if name == 'no-data-declared':
                    archive.files()[0].data = b''
                testfile = self.write_rar5('refused-' + name + '.rar', archive)

                for entry in both:
                    assert self.entry_is_found(testfile, entry) == (entry in found)

                output = self.scan(testfile, '--alert-incomplete-rar=yes')
                assert ('Heuristics.Incomplete.RAR' in output.out) == (not complete)

    def test_rar5_solid_entry_declaring_a_larger_dictionary_than_its_stream(self):
        self.step_name('Test a solid RAR5 entry that declares another dictionary size than the entries before it is extracted')

        archive = rar5_craft.Archive.join(
            (TC.path_rar / 'rar5-compressed-checked.rar').read_bytes(),
            (TC.path_rar / 'rar5-compressed-checked.rar').read_bytes())
        archive.set_main_flags(4)
        for dictionary in (1, 6):
            with self.subTest(dictionary=dictionary):
                archive.edit_file(1, lambda h: h.set_compression(solid=True, dictionary=dictionary))
                testfile = self.write_rar5('solid-dictionary-{}.rar'.format(dictionary), archive)

                self.assert_entry_found(testfile, COMPRESSED_ENTRY)
                output = self.scan(testfile, '--alert-incomplete-rar=yes')
                assert 'Heuristics.Incomplete.RAR' not in output.out

    def test_rar5_dictionary_beyond_what_is_allocated_is_reported(self):
        self.step_name('Test a RAR5 solid stream that needs a window larger than 1 GB is reported incomplete and the entries after it are scanned')

        # unRAR on a 64-bit system extracts it; this backend allocates 1 GB of
        # window at most.
        if TC.backend != 'libarchive':
            self.skipTest('The RARLAB backend extracts the entry')

        archive = rar5_craft.Archive.join(
            (TC.path_rar / 'rar5-compressed-checked.rar').read_bytes(),
            (TC.path_rar / 'rar5-stored-checked.rar').read_bytes())
        archive.set_main_flags(4)

        def declare_a_stream_of_1500_megabytes(header):
            header.set_compression(dictionary=15)
            header.unpacked_size = 1500 << 20

        archive.edit_file(0, declare_a_stream_of_1500_megabytes)
        testfile = self.write_rar5('solid-window-beyond-1G.rar', archive)

        limits = '--max-filesize=2000M --max-scansize=4000M'
        self.assert_entry_found(testfile, STORED_ENTRY, limits)
        output = self.scan(testfile, limits + ' --alert-incomplete-rar=yes')
        assert 'Heuristics.Incomplete.RAR' in output.out

    def solid_skip_archive(self, edit):
        archive = rar5_craft.Archive((TC.path_rar / 'rar5-solid-skip.rar').read_bytes())
        archive.edit_file(0, edit)
        return archive

    def test_rar5_solid_entry_declaring_a_dictionary_of_4_gigabytes_is_decoded(self):
        self.step_name('Test the entries after a solid RAR5 entry that declares a dictionary of 4 GB are scanned')

        # marker.txt is coded against big.txt before it, so it is found only
        # if big.txt is decoded as part of the stream. The dictionary is
        # larger than anything the stream writes; unRAR extracts both.
        archive = self.solid_skip_archive(lambda h: h.set_compression(dictionary=15))
        testfile = self.write_rar5('solid-dictionary-4G-in-stream.rar', archive)

        output = self.scan(testfile, '--alert-incomplete-rar=yes')
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile.name)])

    def test_rar5_window_is_sized_to_what_the_stream_writes(self):
        self.step_name('Test a solid RAR5 stream that declares a dictionary of 1 GB does not need 1 GB of address space')

        # The window is sized to the data the stream writes, not to the
        # dictionary a 200-byte header declares: a few kilobytes of archive
        # do not allocate a gigabyte.
        if TC.backend != 'libarchive':
            self.skipTest('The RARLAB backend allocates the dictionary')
        if not sys.platform.startswith('linux') or TC.valgrind != '':
            self.skipTest('The address space is limited with ulimit -v on Linux, without valgrind')
        if os.getenv('ASAN_OPTIONS') is not None or os.getenv('UBSAN_OPTIONS') is not None:
            self.skipTest('A sanitizer reserves address space the limit does not leave')

        archive = self.solid_skip_archive(lambda h: h.set_compression(dictionary=13))
        testfile = self.write_rar5('solid-dictionary-1G-in-stream.rar', archive)

        output = self.scan(testfile, '--alert-incomplete-rar=yes', memory_limit_kb=1000000)
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile.name)])

    def test_rar5_entry_without_a_name_does_not_break_its_solid_stream(self):
        self.step_name('Test the entries after a nameless entry of a solid RAR5 archive are scanned')

        # marker.txt is coded against big.txt before it, so it is found only
        # if big.txt is decoded as part of the stream, though big.txt itself
        # cannot be extracted without a name. unRAR extracts marker.txt.
        archive = self.solid_skip_archive(lambda h: setattr(h, 'name', b''))
        testfile = self.write_rar5('solid-no-name.rar', archive)

        output = self.scan(testfile, '--alert-incomplete-rar=yes')
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile.name)])

        output = self.scan(testfile, '--alert-incomplete-rar=yes --allmatch')
        self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile.name), '{}: Heuristics.Incomplete.RAR FOUND'.format(testfile.name)])

    WINDOW_SIZE = 256 << 20

    def window_scan(self, tempdir):
        """Start a scan of the RAR5 archive whose window is above the file-backed threshold."""
        digest = hashlib.sha256()
        zeros = bytes(1 << 20)
        for _ in range(400):
            digest.update(zeros)
        digest.update(b'ClamAV-RAR-window-marker-3b9d71\n')
        path_db = TC.path_tmp / 'large-window.hsb'
        path_db.write_text('{}:419430432:RAR_WINDOW_ENTRY\n'.format(digest.hexdigest()))

        tempdir.mkdir()
        command = [str(TC.clamscan), '--max-filesize=2000M', '--max-scansize=4000M',
                   '--tempdir={}'.format(tempdir), '-d', str(path_db),
                   str(TC.path_rar / 'rar5-large-window.rar')]
        return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def window_mapping(self, process):
        """The address range of the process' window mapping and its description, or None."""
        try:
            with open('/proc/{}/maps'.format(process.pid)) as maps:
                for line in maps:
                    fields = line.split()
                    start, end = (int(x, 16) for x in fields[0].split('-'))
                    if end - start == self.WINDOW_SIZE and 'rw-s' == fields[1] and line.rstrip().endswith('(deleted)'):
                        return fields[0], line.rstrip()
        except OSError:
            pass
        return None

    def wait_for_window_mapping(self, process):
        deadline = time.monotonic() + 120
        while process.poll() is None and time.monotonic() < deadline:
            mapping = self.window_mapping(process)
            if mapping is not None:
                return mapping
        return None

    def skip_unless_window_files_observable(self):
        if TC.backend != 'libarchive':
            self.skipTest('The RARLAB backend keeps its window in memory')
        if not sys.platform.startswith('linux') or TC.valgrind != '':
            self.skipTest('The mapping is read from /proc on Linux, without valgrind')

    def test_large_rar5_window_is_an_unnamed_file_with_mode_0600(self):
        self.step_name('Test a RAR5 window above the threshold is a mapping of an unnamed 0600 file')

        self.skip_unless_window_files_observable()
        tempdir = TC.path_tmp / 'window-tmp'
        process = self.window_scan(tempdir)
        try:
            mapping = self.wait_for_window_mapping(process)
            assert mapping is not None, 'no deleted file mapping of the window size was seen'
            address_range, description = mapping
            assert str(tempdir) in description, description

            try:
                inode = os.stat('/proc/{}/map_files/{}'.format(process.pid, address_range))
            except PermissionError:
                inode = None
            if inode is not None:
                assert inode.st_mode & 0o777 == 0o600, oct(inode.st_mode)
                assert inode.st_nlink == 0
                assert inode.st_uid == os.getuid()
            assert not [name for _, _, names in os.walk(tempdir) for name in names if 'window' in name or name.startswith('#')]
        finally:
            process.kill()
            process.communicate()

    def test_large_rar5_window_gives_the_same_verdict(self):
        self.step_name('Test the entry of a RAR5 archive with a file-backed window is extracted byte for byte')

        self.skip_unless_window_files_observable()
        process = self.window_scan(TC.path_tmp / 'window-verdict-tmp')
        out, _ = process.communicate(timeout=300)
        assert process.returncode == 1, out
        assert 'RAR_WINDOW_ENTRY.UNOFFICIAL FOUND' in out, out

    def test_killed_scan_leaves_no_window_file(self):
        self.step_name('Test no window file survives a scan killed with SIGKILL')

        self.skip_unless_window_files_observable()
        tempdir = TC.path_tmp / 'window-kill-tmp'
        process = self.window_scan(tempdir)
        try:
            assert self.wait_for_window_mapping(process) is not None, 'no window mapping was seen'
        finally:
            process.send_signal(signal.SIGKILL)
            process.communicate()

        leftovers = [name for _, _, names in os.walk(tempdir) for name in names
                     if 'window' in name or name.startswith('#')]
        assert leftovers == []
