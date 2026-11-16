#!/bin/sh
# usage: make-rar.sh <rar 6.24 dir> <rar 7.23 dir> <corpus dir>
#
# Writes the RAR archives of docs/DIFFERENCES.md into <corpus dir>/rar with RARLAB rar in a throwaway container. rar is a
# tool of the measurement only: fetched, run, never committed or shipped. Each directory holds the rar binary of the
# release from rarlab.com (rarlinux-x64-624.tar.gz, rarlinux-x64-723.tar.gz): 6.24 is the last release that writes RAR4,
# 7.23 writes the large dictionary archive. <corpus dir>/pay comes from make-corpus.py.
#
# Outputs: rar4.rar, rar5.rar, rar4-solid.rar, rar5-solid.rar (about 8.5 MB each) and dict1g-800m.rar (RAR5, solid,
# 1 GiB dictionary, 800 MiB of zeros, about 34 KB).
set -eu
rar6=$(cd "$1" && pwd)
rar7=$(cd "$2" && pwd)
corpus=$(cd "$3" && pwd)
mkdir -p "$corpus/rar"
docker run --rm --platform linux/amd64 -v "$rar6:/r6:ro" -v "$rar7:/r7:ro" -v "$corpus/pay:/pay:ro" -v "$corpus/rar:/out" \
    debian:trixie-slim sh -c '
  cd /tmp
  for v in 4 5; do
    /r6/rar a -idq -y -ep1 -ma$v -m3 /out/rar$v.rar /pay/*
    /r6/rar a -idq -y -ep1 -ma$v -m3 -s /out/rar$v-solid.rar /pay/*
  done
  dd if=/dev/zero of=/tmp/zeros.bin bs=1M count=800 2>/dev/null
  /r7/rar a -idq -y -ep1 -ma5 -s -m3 -md1g /out/dict1g-800m.rar /tmp/zeros.bin
'
