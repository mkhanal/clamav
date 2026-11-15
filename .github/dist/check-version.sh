#!/usr/bin/env bash
# usage: check-version.sh [<tag>]
# Fails unless the release number in the source (CMakeLists.txt) is the one named in README.md and NOTICE, and, given a
# tag clamcove-<version>.<n>, unless that tag names it too.
set -euo pipefail
cd "$(dirname "$0")/../.."
base=$(sed -n '/^project( *ClamAV/,/)/ s/.*VERSION *"\([0-9][0-9.]*\)".*/\1/p' CMakeLists.txt | head -1)
release=$(sed -n 's/^set(CLAMCOVE_RELEASE  *"\([0-9][0-9]*\)".*/\1/p' CMakeLists.txt)
if [ -z "$base" ] || [ -z "$release" ]; then
  echo "cannot read the project version and CLAMCOVE_RELEASE from CMakeLists.txt"; exit 1
fi
version="$base.$release"
status=0
grep -q "(ClamCove $version)" NOTICE || { echo "NOTICE does not name (ClamCove $version)"; status=1; }
grep -q "so ClamCove $version is ClamAV $base plus ClamCove release $release\." README.md \
  || { echo "README.md does not say: ClamCove $version is ClamAV $base plus ClamCove release $release"; status=1; }
grep -q "clamcove:$version\`" README.md || { echo "README.md does not name the image clamcove:$version"; status=1; }
if [ $# -gt 0 ] && [ "$1" != "clamcove-$version" ]; then
  echo "tag $1 differs from clamcove-$version, the version in the tagged source: bump CLAMCOVE_RELEASE in CMakeLists.txt first"
  status=1
fi
[ "$status" -eq 0 ] && echo "version $version: CMakeLists.txt, README.md and NOTICE agree"
exit $status
