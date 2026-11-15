#!/usr/bin/env bash
# usage: check-no-rarlab.sh tree <directory> | patches <patch>... | image <docker image>
# Fails when what it is given contains RARLAB unRAR source or licence: a libclamunrar path, COPYING.unrar, a file named like an
# unRAR source file, a file holding the RARLAB licence text, or (patches) a deletion that carries the deleted text.
#   tree     a source tree, such as the unpacked release tarball
#   patches  release patches
#   image    every layer of a docker image, from docker save
set -euo pipefail

signatures=(
  'UnRAR source code may be used'
  'unRAR sources may be used'
  'cannot be used to re-create the RAR compression algorithm'
  'Alexander Roshal'
)
name_tests=(
  -name libclamunrar -o -name 'libclamunrar.*' -o -name COPYING.unrar -o -name unrar.hpp -o -name rar.hpp -o -name rarvm.cpp
  -o -name rarvm.hpp -o -name unpack.cpp -o -name unpack.hpp -o -name unpack15.cpp -o -name unpack20.cpp -o -name unpack30.cpp
  -o -name unpack50.cpp -o -name unpackinline.cpp -o -name dll.hpp -o -name rijndael.cpp -o -name rdwrfn.cpp -o -name arcread.cpp
)

check_tree() {
  local dir=$1 found
  found=$( { find "$dir" \( "${name_tests[@]}" \) -print
             grep -rlaF --exclude=check-no-rarlab.sh "${signatures[@]/#/-e}" "$dir" || true; } | sort -u)
  if [ -n "$found" ]; then
    echo "RARLAB files in $dir:"; echo "$found" | head -20; return 1
  fi
}

check_patches() {
  local patch status=0
  for patch in "$@"; do
    if grep -qaF "${signatures[@]/#/-e}" "$patch"; then echo "$patch holds RARLAB licence text"; status=1; fi
    if ! awk '
      function flush() { if (path ~ /(^|\/)(libclamunrar\/|COPYING\.unrar$)/ && !deleted) { print path ": adds or changes a RARLAB path"; bad = 1 }
                         if (deleted && text) { print path ": a deleted file carries its text"; bad = 1 } }
      /^diff --git / { flush(); path = $0; sub(/^diff --git a\//, "", path); path = substr(path, 1, (length(path) - 3) / 2); deleted = 0; text = 0; next }
      /^deleted file mode/ { deleted = 1; next }
      /^(@@|GIT binary patch)/ { text = 1 }
      END { flush(); exit bad }' "$patch"; then
      echo "in $patch"; status=1
    fi
  done
  return $status
}

check_image() {
  local image=$1 work layer status=0
  work=$(mktemp -d)
  trap 'rm -rf "$work"' RETURN
  docker save "$image" -o "$work/image.tar"
  mkdir "$work/image"
  tar -xf "$work/image.tar" -C "$work/image"
  python3 - "$work/image" > "$work/layers" <<'P'
import json, os, sys
root = sys.argv[1]
for image in json.load(open(os.path.join(root, 'manifest.json'))):
    for layer in image['Layers']:
        print(os.path.join(root, layer))
P
  [ -s "$work/layers" ] || { echo "no layers found in $image"; return 1; }
  n=0
  while IFS= read -r layer; do
    n=$((n + 1))
    mkdir "$work/layer$n"
    tar -xf "$layer" -C "$work/layer$n"
    check_tree "$work/layer$n" || status=1
    rm -rf "$work/layer$n"
  done < "$work/layers"
  echo "checked $n layers of $image"
  return $status
}

mode=${1:?usage: check-no-rarlab.sh tree|patches|image ...}
shift
case "$mode" in
  tree) check_tree "$1" ;;
  patches) check_patches "$@" ;;
  image) check_image "$1" ;;
  *) echo "unknown mode $mode"; exit 2 ;;
esac
echo "no RARLAB files: $mode ok"
