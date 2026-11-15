# rar-parity

Evidence that ClamCove reaches everything the official ClamAV build, which reads RAR with RARLAB unRAR code, reaches.
The official build is made from the verified Cisco source release in CI and is never shipped.
It lives under `tools/` rather than `unit_tests/` because it compares two installed builds (prefixes or Docker
images) and needs neither the `check` suite nor the `clamav-unit-tests` download.

## Run

Build the reference, the official ClamAV source release, and the build under test, from the same Dockerfile. The
release is fetched and verified by `.github/dist/fetch-official-source.sh <version> <directory>` (SHA-256 and the Talos
signature); the reference image exists only to compare against and is never shipped:

    .github/dist/fetch-official-source.sh 1.5.4 official
    tar -xzf official/clamav-1.5.4.tar.gz
    docker build -f tools/rar-parity/Dockerfile -t clamav-rar-official clamav-1.5.4
    docker build -f tools/rar-parity/Dockerfile -t clamav-rar-libarchive .

Compare:

    python3 tools/rar-parity/compare.py --a docker:clamav-rar-official --b docker:clamav-rar-libarchive
    python3 tools/rar-parity/compare.py --a prefix:/opt/clamav-official --b prefix:/opt/clamav-libarchive

The exit status is non-zero when build B detects less than A, reports clean where A alerted or errored, or differs
from the manifest's expected outcome. `--report-only` prints the table and exits 0 (baseline); `--only REGEX`
selects rows; `--no-runtime` skips the large archives generated at scan time. `--extra-options="FLAGS"` adds clamscan
flags (shell-quoted, e.g. `--extra-options="--alert-incomplete-rar=yes"`) to the command for both builds, so the two
verdicts stay comparable. `selftest.sh` proves the comparison fails when it should. `baseline-unrar.txt` is the official build's table.

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
