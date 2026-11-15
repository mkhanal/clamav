#!/usr/bin/env bash
# usage: split-changes.sh <upstream tag> <release tag> <name prefix, e.g. clamcove-1.5.4.2> <output dir>
#
# Writes one patch file per shipped change and release-notes-patches.md.
#
# Every patch is the NET diff of its change, never a series of the commits that built it: code that a later commit
# removed (a decoder dropped for licence reasons, say) is in no patch, because it is not in the release.
#
# How the net diffs are cut. Tests, test inputs, fuzz targets, tooling and the README are edited by every change, at
# the same places (a test file ends with the tests of all of them), so they cannot be assigned to one change; they are
# the paths of the kind paths line of .github/clamcove-changes.txt and ship as the last patch, as the sum of all
# changes to them. Every other path is cut per change: the release tree is the last state; going back from it, the
# commits owned by the last change of the series are reverted, newest first, which gives the state without that change;
# the same for the change before it, and so on. State 0 is the upstream tree. Patch N is the diff from state N-1 to
# state N, so applying patches 1..N in order to the upstream source gives exactly state N, and applying all of them
# gives exactly the release tree (without .github). Nothing is replayed, so nothing depends on the order in which
# commits of different changes were made.
#
# Deleted files. A patch records a deletion as a header with no removed text (git diff --irreversible-delete), so no patch
# carries the text of a file the release does not contain; apply-patch.sh applies such a patch.
#
# Interdependent changes. Changes whose commits cannot be reverted cleanly one without the other, because they edit the
# same lines, cannot be split: they become one patch whose title says so ("<title> + <title>; one patch, the changes
# edit the same lines"). The patches come in series order: the merged ones first, the independent ones after them.
#
# Not shipped: .github (CI and release inputs) is left out of every state. A commit owned by a kind none change may touch
# only those paths, and a commit owned by no change fails the run.
set -euo pipefail
upstream=$1 release=$2 prefix=$3 out=$4
here=$(cd "$(dirname "$0")" && pwd)
map="$here/../clamcove-changes.txt"
not_shipped=(.github)
mkdir -p "$out"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export GIT_AUTHOR_NAME=ClamCove GIT_AUTHOR_EMAIL=clamcove@localhost GIT_COMMITTER_NAME=ClamCove GIT_COMMITTER_EMAIL=clamcove@localhost
export GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z

bucket_order="" bucket_slug="" bucket_title="" bucket_paths=()
while IFS=$'\t' read -r order slug kind title regex; do
  case "$order" in ''|\#*) continue ;; esac
  if [ "$kind" = paths ]; then bucket_order=$order bucket_slug=$slug bucket_title=$title; read -r -a bucket_paths <<< "$regex"; fi
done < "$map"

tree_without() {
  GIT_INDEX_FILE="$work/index" git read-tree "$1"
  shift
  GIT_INDEX_FILE="$work/index" git rm -r -q -f --cached --ignore-unmatch "$@" > /dev/null
  GIT_INDEX_FILE="$work/index" git write-tree
}
whole_tree() { tree_without "$1" "${not_shipped[@]}"; }
shipped_tree() { tree_without "$1" "${not_shipped[@]}" "${bucket_paths[@]}"; }
as_commit() { git commit-tree -m state "$1"; }
reverse() { awk '{ line[NR] = $0 } END { for (i = NR; i > 0; i--) print line[i] }'; }

change_of() {
  local subject=$1 order slug kind title regex
  while IFS=$'\t' read -r order slug kind title regex; do
    case "$order" in ''|\#*) continue ;; esac
    [ "$kind" = paths ] && continue
    if [[ "$subject" =~ $regex ]]; then echo "$order"; return; fi
  done < "$map"
}
field_of() {
  local want=$1 col=$2 order slug kind title regex
  while IFS=$'\t' read -r order slug kind title regex; do
    case "$order" in ''|\#*) continue ;; esac
    if [ "$order" = "$want" ]; then
      case "$col" in slug) echo "$slug" ;; kind) echo "$kind" ;; title) echo "$title" ;; esac
      return
    fi
  done < "$map"
}

: > "$work/owners"
unowned=()
while read -r sha; do
  subject=$(git log -1 --format=%s "$sha")
  owner=$(change_of "$subject")
  if [ -z "$owner" ]; then unowned+=("$sha $subject"); continue; fi
  printf '%s\t%s\n' "$sha" "$owner" >> "$work/owners"
done < <(git log --no-merges --topo-order --reverse --format=%H "$upstream^{commit}..$release^{commit}")
if [ "${#unowned[@]}" -gt 0 ]; then
  echo "commits owned by no change in .github/clamcove-changes.txt:"; printf '  %s\n' "${unowned[@]}"; exit 1
fi

while IFS=$'\t' read -r sha owner; do
  [ "$(field_of "$owner" kind)" = none ] || continue
  if [ "$(whole_tree "$sha^{tree}")" != "$(whole_tree "$sha^")" ]; then
    echo "commit $sha changes shipped paths but its change ships no patch (kind none): $(git log -1 --format=%s "$sha")"; exit 1
  fi
done < "$work/owners"

groups=()
while IFS=$'\t' read -r order slug kind title regex; do
  case "$order" in ''|\#*) continue ;; esac
  [ "$kind" = patch ] && groups+=("$order")
done < <(sort "$map")

sorted_orders() { printf '%s\n' $1 | sort | tr '\n' ' ' | sed 's/ $//'; }
commits_of_group() {
  local orders=$1 sha owner
  while IFS=$'\t' read -r sha owner; do
    case " $orders " in *" $owner "*) echo "$sha" ;; esac
  done < "$work/owners"
}

ensure_pair() {
  local sha=$1
  [ -f "$work/pair-$sha" ] && return
  echo "$(as_commit "$(shipped_tree "$sha^{tree}")") $(as_commit "$(shipped_tree "$sha^")")" > "$work/pair-$sha"
}
revert_group() {
  local tree=$1 orders=$2 cur sha after before merged
  cur=$(as_commit "$tree")
  for sha in $(commits_of_group "$orders" | reverse); do
    ensure_pair "$sha"
    read -r after before < "$work/pair-$sha"
    merged=$(git merge-tree --write-tree --merge-base="$after" "$cur" "$before" 2> /dev/null) || return 1
    cur=$(as_commit "$merged")
  done
  git rev-parse "$cur^{tree}"
}

subsets_by_size() {
  local n=$1 size mask i members
  for ((size = 1; size < n; size++)); do
    for ((mask = (1 << n) - 1; mask > 0; mask--)); do
      members=()
      for ((i = 0; i < n; i++)); do if (( (mask >> i) & 1 )); then members+=("$i"); fi; done
      if [ "${#members[@]}" -eq "$size" ]; then echo "${members[*]}"; fi
    done
  done
}

remaining=("${groups[@]}")
top_groups=()
top_pre_states=()
top_post_states=()
state=$(shipped_tree "$release^{tree}")
while [ "${#remaining[@]}" -gt 1 ]; do
  found=""
  while read -r picked; do
    orders=""
    for index in $picked; do orders="$orders ${remaining[$index]}"; done
    orders=$(sorted_orders "$orders")
    if tree=$(revert_group "$state" "$orders"); then found=$picked; break; fi
  done < <(subsets_by_size "${#remaining[@]}")
  if [ -z "$found" ]; then break; fi
  if [ "$(wc -w <<< "$found")" -gt 1 ]; then echo "changes $orders edit the same lines and cannot be split: one patch"; fi
  top_groups=("$orders" "${top_groups[@]+"${top_groups[@]}"}")
  top_post_states=("$state" "${top_post_states[@]+"${top_post_states[@]}"}")
  top_pre_states=("$tree" "${top_pre_states[@]+"${top_pre_states[@]}"}")
  next=()
  for ((index = 0; index < ${#remaining[@]}; index++)); do
    case " $found " in *" $index "*) ;; *) next+=("${remaining[$index]}") ;; esac
  done
  remaining=("${next[@]}")
  state=$tree
done
bottom=$(sorted_orders "${remaining[*]}")
if [ "$(wc -w <<< "$bottom")" -gt 1 ]; then echo "changes $bottom edit the same lines and cannot be split: one patch"; fi

series_groups=("$bottom" "${top_groups[@]+"${top_groups[@]}"}")
series_pre=("$(shipped_tree "$upstream^{tree}")" "${top_pre_states[@]+"${top_pre_states[@]}"}")
series_post=("$state" "${top_post_states[@]+"${top_post_states[@]}"}")

series_diff() {
  local i=$1; shift
  if [ "${series_groups[$i]}" = "$bucket_order" ]; then
    git diff "$@" "${series_pre[$i]}" "${series_post[$i]}" -- "${bucket_paths[@]}"
  else
    git diff "$@" "${series_pre[$i]}" "${series_post[$i]}"
  fi
}
series_groups+=("$bucket_order")
series_pre+=("")
series_post+=("")
shipped=()
for ((i = 0; i < ${#series_groups[@]}; i++)); do
  if [ -z "${series_pre[$i]}" ]; then
    series_pre[$i]=$(whole_tree "$upstream^{tree}"); series_post[$i]=$(whole_tree "$release^{tree}")
  fi
  if series_diff "$i" --quiet; then
    echo "no net change for ${series_groups[$i]} in this release"
  else
    shipped+=("$i")
  fi
done

notes="$out/release-notes-patches.md"
: > "$notes"
n=0
for i in "${shipped[@]+"${shipped[@]}"}"; do
  n=$((n + 1))
  orders=(${series_groups[$i]})
  title=""
  for order in "${orders[@]}"; do
    if [ -z "$title" ]; then title=$(field_of "$order" title); else title="$title + $(field_of "$order" title)"; fi
  done
  slug=$(field_of "${orders[0]}" slug)
  if [ "${#orders[@]}" -gt 1 ]; then
    title="$title; one patch, the changes edit the same lines"
    slug="$slug-and-$((${#orders[@]} - 1))-dependent-changes"
  fi
  file=$(printf '%s-%02d-%s.patch' "$prefix" "$n" "$slug")
  {
    echo "Subject: [PATCH $n/${#shipped[@]}] $title"
    echo
    series_diff "$i" --binary --no-renames --irreversible-delete
  } > "$out/$file"
  echo "- \`$file\`: $title" >> "$notes"
done
