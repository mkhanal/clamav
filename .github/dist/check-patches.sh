#!/usr/bin/env bash
# usage: check-patches.sh <upstream tag> <release ref>
# Generates the release patches (split-changes.sh), applies them in order to the upstream tree and fails unless
#   1. every commit is owned by a change (split-changes.sh),
#   2. the result is exactly the release tree without .github,
#   3. no patch adds a file or a line that is not in the release tree.
set -euo pipefail
upstream=$1 release=$2
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

"$here/split-changes.sh" "$upstream" "$release" check "$work/patches"
cat "$work/patches/release-notes-patches.md"

mkdir "$work/applied"
GIT_INDEX_FILE="$work/index-upstream" git read-tree "$upstream^{tree}"
GIT_INDEX_FILE="$work/index-upstream" git -c core.autocrlf=false checkout-index -a --prefix="$work/applied/"
rm -rf "$work/applied/.github"
for patch in "$work"/patches/*.patch; do
  (cd "$work/applied" && git apply --binary --whitespace=nowarn -p1 "$patch")
  echo "applied $(basename "$patch") ($(wc -c < "$patch" | tr -d ' ') bytes)"
done

mkdir "$work/expected"
GIT_INDEX_FILE="$work/index-release" git read-tree "$release^{tree}"
GIT_INDEX_FILE="$work/index-release" git -c core.autocrlf=false checkout-index -a --prefix="$work/expected/"
rm -rf "$work/expected/.github"
if ! diff -r -q "$work/applied" "$work/expected" > "$work/differences"; then
  echo "applying the patches in order does not give the release tree:"; head -20 "$work/differences"; exit 1
fi
(cd "$work/applied" && find . \( -type l -o -perm -u+x \) ! -type d | sort) > "$work/modes-applied"
(cd "$work/expected" && find . \( -type l -o -perm -u+x \) ! -type d | sort) > "$work/modes-expected"
if ! diff -q "$work/modes-applied" "$work/modes-expected" > /dev/null; then
  echo "executable bits or symbolic links differ from the release tree:"; diff "$work/modes-applied" "$work/modes-expected" | head -20; exit 1
fi
echo "apply-equals-tree: ok, the patches applied in order to $upstream give exactly the tree of $release without .github ($(find "$work/applied" -type f | wc -l | tr -d ' ') files)"

violations=0
for patch in "$work"/patches/*.patch; do
  report=$(awk -v root="$work/applied" '
    /^diff --git / { file = substr($4, 3); binary = 0; fresh = 0; loaded = 0; next }
    /^GIT binary patch/ { binary = 1 }
    /^new file mode/ { fresh = 1; if (system("test -e \"" root "/" file "\"") != 0) print file ": added file is not in the release tree" }
    binary || /^\+\+\+ / || !/^\+/ { next }
    {
      if (!loaded) { while ((getline text < (root "/" file)) > 0) present[file SUBSEP text] = 1; close(root "/" file); loaded = 1 }
      line = substr($0, 2)
      if (!((file SUBSEP line) in present)) print file ": added line is not in the release tree: " line
    }' "$patch" | head -20)
  if [ -n "$report" ]; then echo "$(basename "$patch"):"; echo "$report"; violations=1; fi
done
[ "$violations" -eq 0 ] || exit 1
echo "no-removed-code: ok, every added line and file of every patch is in the release tree"
