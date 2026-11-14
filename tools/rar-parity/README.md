# rar-parity

Evidence that a ClamAV build with the libarchive RAR backend reaches everything a build with RARLAB unRAR reaches.
It lives under `tools/` rather than `unit_tests/` because it compares two installed builds (prefixes or Docker
images) and needs neither the `check` suite nor the `clamav-unit-tests` download.

## Run

Build the reference (unRAR) image, and the build under test, from the same Dockerfile:

    docker build -f tools/rar-parity/Dockerfile -t clamav-rar-unrar .
    docker build -f tools/rar-parity/Dockerfile -t clamav-rar-libarchive \
        --build-arg EXTRA_CMAKE=-DENABLE_UNRAR_LIBARCHIVE=ON <path to a checkout with the libarchive backend>

Compare:

    python3 tools/rar-parity/compare.py --a docker:clamav-rar-unrar --b docker:clamav-rar-libarchive
    python3 tools/rar-parity/compare.py --a prefix:/opt/clamav-unrar --b prefix:/opt/clamav-libarchive

The exit status is non-zero when build B detects less than A, reports clean where A alerted or errored, or differs
from the manifest's expected outcome. `--report-only` prints the table and exits 0 (baseline); `--only REGEX`
selects rows; `--no-runtime` skips the large archives generated at scan time. `--extra-options="FLAGS"` adds clamscan
flags (shell-quoted, e.g. `--extra-options="--alert-incomplete-rar=yes"`) to the command for both builds, so the two
verdicts stay comparable. `selftest.sh` proves the comparison fails when it should. `baseline-unrar.txt` is the unRAR build's table.

## Contents

- `manifest.json`: one row per scan (fixture, options, expected outcome, origin, licence, format, what RARLAB's
  reference `unrar` made of it). Outcomes: `detect` (inner-content signatures fire), `encrypted`
  (`Heuristics.Encrypted.RAR`), `limits` (`Heuristics.Limits.Exceeded.*`), `error` (never clean), `clean`
  (nothing scannable inside).
- `signatures/rar-parity.hdb`: SHA-256 hash signatures of the files inside the archives, so a detection proves the
  file was extracted. Only files that `clamscan` detects when scanned on their own are used.
- `fixtures/libarchive/`: libarchive's RAR test archives (BSD-2-Clause, licence beside them), uudecoded.
- `fixtures/generated/`: made by `make-fixtures.sh` with RARLAB rar 6.24 trial (throwaway container, not shipped).
- `fixtures/derived/`: nesting in zip and RAR, truncated and corrupted copies; made by `build-fixtures.py`.
- The two ClamAV files `clam-v2.rar.xor` and `clam-v3.rar.xor` are used in place from `unit_tests/input`.
- Large and many-file archives are written at scan time by `rarwrite.py` (a stored-RAR writer), never committed.

`build-fixtures.py` regenerates the manifest and signatures (it extracts every fixture with RARLAB's `unrar` in a
throwaway container to learn the true contents); the comparison itself needs only the committed files.
