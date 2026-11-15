# Copyright (C) 2026 Cisco Systems, Inc. and/or its affiliates. All rights reserved.

"""
Run clamscan RAR tests.
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import testcase

MARKER = b'ClamAV-RAR-backend-test-marker-6f1c2e'


class TC(testcase.TestCase):
    @classmethod
    def setUpClass(cls):
        super(TC, cls).setUpClass()

        cls.path_rar = TC.path_source / 'unit_tests' / 'input' / 'other_scanfiles' / 'rar'

        cls.path_marker_db = TC.path_tmp / 'rar-marker.ndb'
        cls.path_marker_db.write_text('RAR_TEST_MARKER:0:*:{}\n'.format(MARKER.hex()))

    @classmethod
    def tearDownClass(cls):
        super(TC, cls).tearDownClass()

    def setUp(self):
        super(TC, self).setUp()
        if os.getenv('ENABLE_UNRAR', 'OFF').upper() not in ('ON', '1', 'TRUE', 'YES'):
            self.skipTest('Built without RAR support')

    def tearDown(self):
        super(TC, self).tearDown()
        self.verify_valgrind_log()

    def scan(self, testfile, options=''):
        command = '{valgrind} {valgrind_args} {clamscan} {options} -d {path_db} {testfile}'.format(
            valgrind=TC.valgrind,
            valgrind_args=TC.valgrind_args,
            clamscan=TC.clamscan,
            options=options,
            path_db=TC.path_marker_db,
            testfile=testfile,
        )
        return self.execute_command(command)

    def assert_incomplete_alert_only_when_enabled(self, testfile):
        output = self.scan(testfile, '--alert-incomplete-rar=yes')
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: Heuristics.Incomplete.RAR FOUND'.format(testfile)])

        output = self.scan(testfile)
        assert output.ec == 0  # clean
        self.verify_output(output.out, expected=['{}: OK'.format(testfile)])

    def test_incomplete_alert_for_a_lone_volume(self):
        self.step_name('Test the first volume of a set alone alerts as incomplete only when enabled')

        for prefix in ('rar4-volume', 'rar5-volume'):
            with self.subTest(volumes=prefix):
                path_lone = TC.path_tmp / (prefix + '-lone')
                path_lone.mkdir()
                shutil.copy(str(TC.path_rar / (prefix + '.part1.rar')), str(path_lone))

                self.assert_incomplete_alert_only_when_enabled(path_lone / (prefix + '.part1.rar'))

    def test_incomplete_alert_for_a_truncated_archive(self):
        self.step_name('Test a truncated archive alerts as incomplete only when enabled')

        for archive in ('rar4-filter-e8.rar', 'rar5-filter-delta.rar'):
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

        for archive in ('rar4-filter-e8.rar', 'rar5-filter-delta.rar', 'rar4-comment.rar', 'rar5-comment.rar'):
            with self.subTest(archive=archive):
                testfile = TC.path_rar / archive

                output = self.scan(testfile, '--alert-incomplete-rar=yes')
                assert 'Heuristics.Incomplete.RAR' not in output.out

    def test_no_incomplete_alert_for_a_complete_volume_set(self):
        self.step_name('Test a volume set with every volume present is scanned and not reported as incomplete')

        for prefix in ('rar4-volume', 'rar5-volume'):
            with self.subTest(volumes=prefix):
                path_set = TC.path_tmp / (prefix + '-set')
                path_set.mkdir()
                for part in ('part1', 'part2'):
                    shutil.copy(str(TC.path_rar / '{}.{}.rar'.format(prefix, part)), str(path_set))
                testfile = path_set / (prefix + '.part1.rar')

                output = self.scan(testfile, '--alert-incomplete-rar=yes')
                assert output.ec == 1  # virus
                self.verify_output(output.out, expected=['{}: RAR_TEST_MARKER.UNOFFICIAL FOUND'.format(testfile)])
                assert 'Heuristics.Incomplete.RAR' not in output.out

    def test_incomplete_alert_does_not_report_encrypted_archives(self):
        self.step_name('Test encrypted archives are left to the encrypted archive alert')

        testfile = TC.path_rar / 'rar4-encrypted-data.rar'

        output = self.scan(testfile, '--alert-incomplete-rar=yes')
        assert output.ec == 0  # clean
        self.verify_output(output.out, expected=['{}: OK'.format(testfile)])

        output = self.scan(testfile, '--alert-incomplete-rar=yes --alert-encrypted-archive=yes')
        assert output.ec == 1  # virus
        self.verify_output(output.out, expected=['{}: Heuristics.Encrypted.RAR FOUND'.format(testfile)])
