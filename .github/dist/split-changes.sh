#!/usr/bin/env bash
# usage: split-changes.sh <upstream tag> <release tag> <name prefix, e.g. clamcove-1.5.4.1> <output dir>
# Writes one patch file per shipped change and release-notes-patches.md; fails on a commit no change owns.
set -euo pipefail
upstream=$1 release=$2 prefix=$3 out=$4
map="$(dirname "$0")/../clamcove-changes.txt"
mkdir -p "$out"
work=$(mktemp -d)
unowned=()
while read -r sha; do
  subject=$(git log -1 --format=%s "$sha")
  owner=""
  while IFS=$'\t' read -r order slug kind title regex; do
    case "$order" in ''|\#*) continue ;; esac
    if [[ "$subject" =~ $regex ]]; then owner="$order"; echo "$sha" >> "$work/$order"; break; fi
  done < "$map"
  [ -n "$owner" ] || unowned+=("$sha $subject")
done < <(git log --no-merges --reverse --format=%H "$upstream^{commit}..$release^{commit}")
if [ "${#unowned[@]}" -gt 0 ]; then
  echo "commits owned by no change in .github/clamcove-changes.txt:"; printf '  %s\n' "${unowned[@]}"; exit 1
fi
notes="$out/release-notes-patches.md"
: > "$notes"
while IFS=$'\t' read -r order slug kind title regex; do
  case "$order" in ''|\#*) continue ;; esac
  [ "$kind" = patch ] || continue
  shas=$(cat "$work/$order" 2>/dev/null || true)
  if [ -z "$shas" ]; then echo "no commits for $slug in this release"; continue; fi
  file="$prefix-$order-$slug.patch"
  count=$(echo "$shas" | wc -l | tr -d " "); i=0; : > "$out/$file"
  for sha in $shas; do
    i=$((i + 1))
    git format-patch -1 --stdout --subject-prefix="PATCH $i/$count" "$sha" >> "$out/$file"
  done
  echo "- \`$file\`: $title" >> "$notes"
done < <(sort "$map")
