#!/usr/bin/env bash
# usage: check-commits.sh <base> <head>
# Fails unless every commit in <base>..<head> meets the commit standard in CONTRIBUTING.md.
set -uo pipefail
if [ $# -ne 2 ]; then echo "usage: check-commits.sh <base> <head>" >&2; exit 2; fi
base=$1 head=$2

subject_style='^[A-Za-z0-9_./, -]+: [^[:space:]]'
version_style='^ClamCove [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'
max_subject=72
unfinished_style='^(fixup|squash|amend)! |^wip([^[:alnum:]]|$)|oops|address(ed|ing)? review|review (feedback|round|comments)'
attribution_style='(^|[^[:alnum:]])(claude|chatgpt|codex|copilot|llm|ai[- ]generated)([^[:alnum:]]|$)'

commits=$(git rev-list --reverse "$base..$head") || exit 2
if [ -z "$commits" ]; then echo "no commits in $base..$head"; exit 0; fi

failures=0
fail() {
  echo "FAIL $short $subject"
  echo "     $1"
  failures=$((failures + 1))
}

for sha in $commits; do
  short=$(git rev-parse --short "$sha")
  subject=$(git log -1 --format=%s "$sha")
  body=$(git log -1 --format=%b "$sha")
  message=$(git log -1 --format=%B "$sha")
  email=$(git log -1 --format=%ae "$sha")
  parents=$(git rev-list --parents -n 1 "$sha" | wc -w | tr -d ' ')

  if [ "$parents" -gt 2 ]; then
    fail "merge commit: rebase onto the base branch instead of merging it"
    continue
  fi

  is_version=0
  if printf '%s' "$subject" | grep -Eq "$version_style"; then is_version=1; fi

  if [ "$is_version" -eq 0 ]; then
    if ! printf '%s' "$subject" | grep -Eq "$subject_style"; then
      fail "subject must read 'component: Summary'"
    fi
    if [ -z "$(printf '%s' "$body" | tr -d '[:space:]')" ]; then
      fail "body is empty: say what changes and why"
    fi
  fi
  if [ "${#subject}" -gt "$max_subject" ]; then
    fail "subject is ${#subject} characters, at most $max_subject"
  fi
  if printf '%s' "$subject" | grep -Eiq "$unfinished_style"; then
    fail "fix-up, work-in-progress or review-round commit: fold it into the commit it fixes (git rebase --autosquash)"
  fi
  if printf '%s\n' "$message" | grep -Eiq '^co-authored-by:'; then
    fail "Co-Authored-By trailer: commits are attributed to a person"
  fi
  if printf '%s\n' "$message" | grep -Eiq "$attribution_style"; then
    fail "message mentions a tool that helped write the change"
  fi
  if [ -z "$(printf '%s' "$email" | tr -d '[:space:]')" ]; then
    fail "author email is empty"
  fi
done

total=$(printf '%s\n' "$commits" | wc -l | tr -d ' ')
if [ "$failures" -gt 0 ]; then
  echo "commit standard: $failures problem(s) in $total commit(s) of $base..$head; see CONTRIBUTING.md"
  exit 1
fi
echo "commit standard: $total commit(s) of $base..$head ok"
