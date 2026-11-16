#!/bin/sh
# usage: run-bench.sh <image> <database dir> <corpus dir> [file...]
#
# Runs bench-clamd.py in a container of <image> (any image with clamd and python3 and the build in /opt/clamav) over the
# corpus of make-corpus.py and make-rar.sh. <database dir> is a copy of /var/lib/clamav of clamav/clamav-debian:1.5.4 (the
# official databases). With no file names it scans the eight files of docs/DIFFERENCES.md.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
image=$1
db=$(cd "$2" && pwd)
corpus=$(cd "$3" && pwd)
shift 3
if [ $# -eq 0 ]; then
  set -- /c/doc9.docx /c/nested9.zip /c/plain9.zip /c/pdf9.pdf /c/rar/rar4.rar /c/rar/rar5.rar /c/rar/rar4-solid.rar /c/rar/rar5-solid.rar
fi
exec docker run --rm -v "$db:/db:ro" -v "$corpus:/c:ro" -v "$here:/g:ro" -e RUNS="${RUNS:-7}" "$image" python3 /g/bench-clamd.py "$@"
