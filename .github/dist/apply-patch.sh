#!/usr/bin/env bash
# usage: apply-patch.sh <patch>   (run in the tree the patch is for)
# Applies a release patch. A patch records the deletion of a file as a header with no removed text (git diff
# --irreversible-delete), which git apply refuses, so the deleted files are removed here and git applies the rest.
set -euo pipefail
patch=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
: > "$work/removed"
: > "$work/rest.patch"
awk -v removed="$work/removed" -v rest="$work/rest.patch" '
  /^diff --git / {
    skip = 0
    header = $0
    if ((getline following) > 0) {
      if (following ~ /^deleted file mode/) {
        skip = 1
        path = header
        sub(/^diff --git a\//, "", path)
        print substr(path, 1, (length(path) - 3) / 2) > removed
        next
      }
      print header > rest
      print following > rest
      next
    }
  }
  !skip { print > rest }
' "$patch"
while IFS= read -r path; do
  [ -f "$path" ] || { echo "$path: deleted by $(basename "$patch") but is not a file here"; exit 1; }
  rm -f -- "$path"
  dir=$(dirname "$path")
  while [ "$dir" != . ] && rmdir "$dir" 2> /dev/null; do dir=$(dirname "$dir"); done
done < "$work/removed"
if [ -s "$work/rest.patch" ]; then git apply --binary --whitespace=nowarn -p1 "$work/rest.patch"; fi
