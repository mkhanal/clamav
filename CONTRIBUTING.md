# Contributing to ClamCove

ClamCove's changes are meant to be accepted by ClamAV, and a maintainer can only
judge a change that is a series of thought-through steps. Every pull request
here, and every series offered upstream, meets this standard. CI checks it
(`.github/dist/check-commits.sh <base> <head>` runs the same check locally).

## Commits

- One logical change per commit. Each commit builds and passes the tests on its
  own.
- Subject in ClamAV's style, `component: Summary`, at most 72 characters, for
  example `libclamarchive: Hand a RAR5 entry its declared bytes`. The only
  exception is the version commit, `ClamCove <major>.<minor>.<patch>.<release>`.
- A body that says what changes and why.
- No fix-up, squash, work-in-progress, review-round or merge commits.
- No `Co-Authored-By` trailers and no mention of tools that helped write the
  change. Commits are attributed to a person with an email address.
- Each commit subject is owned by a line in `.github/clamcove-changes.txt`;
  `.github/dist/check-patches.sh` verifies it.

## Working on a change

1. One branch per change, started from the release branch it targets.
2. Rebase onto the base branch; never merge it into yours.
3. Fold a review fix into the commit it fixes: `git commit --fixup <commit>`,
   then `git rebase -i --autosquash <base>`.
4. Force-push your own pull request's branch as needed (`--force-with-lease`).
   Never force-push a release branch.
5. A pull request to a release branch is merged with a merge commit, so its
   series stays visible in the history.

## Offering a change to ClamAV

Build the series on a fresh branch from upstream
[Cisco-Talos/clamav](https://github.com/Cisco-Talos/clamav) `main`. It carries
only the change that matters to ClamAV: no ClamCove naming, version or release
machinery. ClamAV's own guidance is in its
[contribution guide](https://docs.clamav.net/manual/Development/Contribute.html)
and [pull request basics](https://docs.clamav.net/manual/Development/github-pr-basics.html).
