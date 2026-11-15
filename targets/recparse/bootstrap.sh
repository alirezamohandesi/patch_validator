#!/usr/bin/env bash
# Materialise the recparse target as a real git repository.
#
# The validator consumes two git revisions of a target and the real diff
# between them, so the toy target has to live in an actual repository.  Keeping
# a nested repository inside the deliverable would produce a broken gitlink, so
# the four version trees are committed as plain directories under versions/ and
# this script replays them into targets/recparse/repo/ (git-ignored).
#
# Author identity and commit dates are pinned, which makes the resulting commit
# hashes byte-for-byte reproducible on every machine.
#
# Layout produced:
#   branch base               — vulnerable baseline
#   branch correct-patch      — expected validator exit code 0
#   branch incomplete-patch   — expected validator exit code 10
#   branch regression-patch   — expected validator exit code 20
#
# Also regenerates patches/<name>.patch, the real diff of each branch
# against base.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$HERE/repo"
PATCHES="$HERE/patches"

export GIT_AUTHOR_NAME="recparse maintainer"
export GIT_AUTHOR_EMAIL="maintainer@recparse.invalid"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

# Pinned timestamps keep the commit hashes stable across machines and reruns.
BASE_DATE="2026-01-05T10:00:00+00:00"
PATCH_DATE="2026-02-11T09:30:00+00:00"

sync_tree() {
    # Replace the worktree contents with versions/$1, preserving .git.
    local version="$1"
    find "$REPO" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    cp -r "$HERE/versions/$version/." "$REPO/"
}

commit_as() {
    local date="$1" message="$2"
    GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" \
        git -C "$REPO" commit -q --author="$GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>" -m "$message"
}

make_branch() {
    # make_branch <branch> <version-dir> <commit subject> <commit body>
    local branch="$1" version="$2" subject="$3" body="$4"
    git -C "$REPO" checkout -q base
    git -C "$REPO" checkout -q -b "$branch"
    sync_tree "$version"
    git -C "$REPO" add -A
    commit_as "$PATCH_DATE" "$subject

$body"
}

rm -rf "$REPO"
mkdir -p "$REPO" "$PATCHES"

git -C "$REPO" init -q -b base
git -C "$REPO" config user.name "$GIT_AUTHOR_NAME"
git -C "$REPO" config user.email "$GIT_AUTHOR_EMAIL"
git -C "$REPO" config commit.gpgsign false

sync_tree base
git -C "$REPO" add -A
commit_as "$BASE_DATE" "recparse: initial RECV1 record parser

Parses the RECV1 container format and prints one line per record.
See SPECIFICATION.md for the format and the output contract."

make_branch correct-patch correct \
    "parser: bound payload copy by the destination buffer" \
    "copy_payload() compared the record length against the wire-format
maximum rather than the size of the destination buffer, so any TEXT or
RAW record of 32 bytes or more wrote past the end of a 32-byte stack
buffer.

Bound the copy by dst_size, leaving one byte for the NUL terminator.
The check lives in the shared helper so every record type is covered."

make_branch incomplete-patch incomplete \
    "parser: reject over-long text records" \
    "Long TEXT records overflowed the stack buffer used to hold the
payload. Reject them in handle_text() before the copy."

make_branch regression-patch regression \
    "parser: bound payload copy and tighten the text limit" \
    "copy_payload() did not bound the copy by the destination buffer.
Bound it, and additionally constrain text payloads to a conservative
length."

git -C "$REPO" checkout -q base

for branch in correct-patch incomplete-patch regression-patch; do
    git -C "$REPO" diff base.."$branch" > "$PATCHES/${branch}.patch"
done

echo "repository: $REPO"
git -C "$REPO" --no-pager log --all --oneline --decorate | sed 's/^/  /'
echo "patches:"
for p in "$PATCHES"/*.patch; do
    printf '  %-28s %s lines\n' "$(basename "$p")" "$(wc -l < "$p")"
done
