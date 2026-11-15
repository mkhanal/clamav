#!/bin/sh
# Proves compare.py fails when it should. Needs the reference image (default clamav-rar-unrar).
#   selftest.sh [reference-image]
# 1. B = a fake build whose clamscan reports every file clean: compare.py must exit non-zero and
#    name "B detects less than A" and "B clean where A alerted".
# 2. B = the reference build itself: compare.py must report no A-versus-B difference.
set -u
IMAGE=${1:-clamav-rar-unrar}
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
mkdir -p "$T/bin" "$T/lib"
printf '#!/bin/sh\nexit 0\n' > "$T/bin/clamscan"
chmod +x "$T/bin/clamscan"
fail=0

out=$(PYTHONDONTWRITEBYTECODE=1 python3 -I "$HERE/compare.py" --a "docker:$IMAGE" --b "prefix:$T" --no-runtime --only 'gen-rar|clam-v')
rc=$?
echo "$out" | tail -3
[ "$rc" -ne 0 ] || { echo "SELFTEST FAIL: all-clean build passed"; fail=1; }
echo "$out" | grep -q "B detects less than A" || { echo "SELFTEST FAIL: no 'detects less' message"; fail=1; }
echo "$out" | grep -q "B clean where A alerted" || { echo "SELFTEST FAIL: no 'clean where alerted' message"; fail=1; }

out=$(PYTHONDONTWRITEBYTECODE=1 python3 -I "$HERE/compare.py" --a "docker:$IMAGE" --b "docker:$IMAGE" --no-runtime --only 'gen-rar|clam-v' --report-only)
echo "$out" | tail -2
echo "$out" | grep -q "B detects less than A\|B clean where A" && { echo "SELFTEST FAIL: identical builds differ"; fail=1; }

rm -r "$T"
[ "$fail" -eq 0 ] && echo "selftest ok"
exit "$fail"
