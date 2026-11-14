# libarchive, vendored for libclamunrar_iface

This directory holds libarchive (BSD-2-Clause, see `COPYING`), the library
that reads RAR archives for ClamAV when it is configured with
`-DENABLE_UNRAR_LIBARCHIVE=ON`. It is built as a static library with no
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
