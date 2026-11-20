# Equivalence check

This check owns the evidence that ClamCove detects exactly what the official ClamAV release of the
same version detects, and that its regex changes keep the documented speedups. It runs in
`.github/workflows/equivalence.yml` on pull requests, pushes to `main`/`rel/*`/`dev/*`, and on each
published or prereleased release. The release job attaches `equivalence-report.md` to that release.

Run it locally on a Debian/Ubuntu machine with the same packages the workflow installs:

```bash
rustup toolchain install 1.99.1 --profile minimal
cargo run --locked --manifest-path ci/equivalence/generator/Cargo.toml -- ci/equivalence/samples
ci/equivalence/run.sh --report ci/equivalence/report.md ci/equivalence/samples
```

`run.sh` checks the pinned official tarball's SHA-256, builds the official release and this checkout
with identical CMake options, runs ClamAV's `ctest` suite on both, then starts one `clamd` per build
with the same `main`, `daily` and `bytecode` databases plus the three test signatures in `signatures/`.
It scans each generated sample five times, alternating builds, and once more per build with
`--allmatch`. Caching and all scan-size limits are disabled so the comparison measures the regex
work rather than a truncated scan.

The check fails when:

- any sample's verdict or `--allmatch` signature set differs between the two builds, or either
  build's verdict changes between runs;
- `report-12-images.docx`, `archive-12-images.zip` or `report-nested.zip` is less than 3 times
  faster on ClamCove;
- any other sample is more than 15 % slower on ClamCove, plus 10 ms of timer jitter.

The samples contain no RAR: the official build carries RARLAB's unRAR and ClamCove uses vendored
libarchive, so the two cannot be compared on RAR input. RAR behaviour is covered by ClamCove's own
`ctest` suite (`rar_test.py` and its fixtures).

The baseline is ClamAV 1.5.4, tarball SHA-256
`1af1117a228f1b5bc7fa91a0dabc37848a99e7d25188e9be8043332ce721dfd3`. Its detached signature was
checked against the Talos release key `5BAD CA26 65EF 59DC F8A2 3D8B 707F 0DB4 8083 6771` when the
pin was set. Update the pin, the CMake options and the speedup list together when rebasing onto a new
ClamAV version, and keep the generated report with the release notes.
