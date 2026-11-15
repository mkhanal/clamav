#!/usr/bin/env bash
# usage: fetch-official-source.sh <clamav version> <directory>
# Downloads the official ClamAV source release into <directory>, and fails unless its SHA-256 is the one recorded in
# clamav-source-sha256.txt and its signature is a valid one of the Talos release key.
set -euo pipefail
version=$1 dir=$2
here=$(cd "$(dirname "$0")" && pwd)
fingerprint=5BADCA2665EF59DCF8A23D8B707F0DB480836771
mkdir -p "$dir"
cd "$dir"
base=https://www.clamav.net/downloads/production
curl -fsSL --retry 3 -O "$base/clamav-$version.tar.gz"
curl -fsSL --retry 3 -O "$base/clamav-$version.tar.gz.sig"
expected=$(awk -v f="clamav-$version.tar.gz" '$2 == f { print $1 }' "$here/clamav-source-sha256.txt")
if [ -z "$expected" ]; then
  echo "no SHA-256 for clamav-$version.tar.gz in .github/dist/clamav-source-sha256.txt"; exit 1
fi
echo "$expected  clamav-$version.tar.gz" | sha256sum -c -
gnupg=$(mktemp -d)
trap 'rm -rf "$gnupg"' EXIT
chmod 700 "$gnupg"
export GNUPGHOME=$gnupg
gpg --batch --import "$here/talos-clamav-release-key.asc"
gpg --batch --status-fd 1 --verify "clamav-$version.tar.gz.sig" "clamav-$version.tar.gz" | tee verify.status
grep -q "^\[GNUPG:\] VALIDSIG .* $fingerprint\$" verify.status
