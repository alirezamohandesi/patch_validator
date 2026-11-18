#!/usr/bin/env bash
# Fetch the cJSON repository at the two revisions this target validates.
#
# Unlike the toy target, this one is a real upstream project, so the history
# is cloned rather than constructed.  Both commits are pinned by full hash and
# verified after cloning: a validation whose "before" and "after" are not
# exactly these two commits is not the validation this configuration
# describes.
#
# Needs network access the first time; afterwards it is a no-op.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$HERE/repo"
UPSTREAM="${CJSON_REMOTE:-https://github.com/DaveGamble/cJSON.git}"

# Parent of the fix: contains the heap buffer over-read.
BASE_COMMIT="826cd6f842ae7e46ee38bbc097f9a34f2947388d"
# "Fix heap buffer overflow" — adds the bounds check in parse_object().
PATCHED_COMMIT="3ef4e4e730e5efd381be612df41e1ff3f5bb3c32"

if [ ! -d "$REPO/.git" ]; then
    echo "cloning $UPSTREAM into $REPO"
    git clone --quiet "$UPSTREAM" "$REPO"
else
    echo "repository already present at $REPO"
fi

missing=0
for commit in "$BASE_COMMIT" "$PATCHED_COMMIT"; do
    if ! git -C "$REPO" cat-file -e "${commit}^{commit}" 2>/dev/null; then
        echo "commit $commit is not present; fetching" >&2
        git -C "$REPO" fetch --quiet origin || true
        if ! git -C "$REPO" cat-file -e "${commit}^{commit}" 2>/dev/null; then
            echo "ERROR: commit $commit is still missing from $REPO" >&2
            missing=1
        fi
    fi
done

if [ "$missing" -ne 0 ]; then
    echo "ERROR: the pinned revisions are unavailable; cannot validate" >&2
    exit 1
fi

# Local names for the pinned commits, so the configuration and the reports
# read as something other than two bare hashes.
git -C "$REPO" tag -f pv-base "$BASE_COMMIT" >/dev/null
git -C "$REPO" tag -f pv-patched "$PATCHED_COMMIT" >/dev/null

# The two remaining scenarios required for every target (incomplete fix and
# functional regression) do not exist upstream, so they are built here from
# patches/<name>.patch on top of the base commit.  Plumbing commands are used
# so the user's checkout of the repository is never touched, and author and
# dates are pinned so the resulting hashes are identical on every machine.
#   pv-incomplete   check only for top-level objects       -> expected exit 10
#   pv-regression   correct check + nesting limit 1000->64  -> expected exit 20
export GIT_AUTHOR_NAME="patch-validator scenarios" GIT_AUTHOR_EMAIL="scenarios@patch-validator.invalid"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
export GIT_AUTHOR_DATE="2026-02-11T09:30:00+00:00" GIT_COMMITTER_DATE="2026-02-11T09:30:00+00:00"
make_scenario() {
    local tag="$1" patch="$HERE/patches/$2.patch" subject="$3"
    local index tree commit
    index="$(mktemp)"
    GIT_INDEX_FILE="$index" git -C "$REPO" read-tree "$BASE_COMMIT"
    GIT_INDEX_FILE="$index" git -C "$REPO" apply --cached "$patch"
    tree="$(GIT_INDEX_FILE="$index" git -C "$REPO" write-tree)"
    rm -f "$index"
    commit="$(git -C "$REPO" commit-tree "$tree" -p "$BASE_COMMIT" -m "$subject")"
    git -C "$REPO" tag -f "$tag" "$commit" >/dev/null
}
make_scenario pv-incomplete incomplete-patch \
    "parse_object: reject a top-level object that ends after a comma"
make_scenario pv-regression regression-patch \
    "parse_object: check the byte after a comma; lower the nesting limit to 64"

echo
git -C "$REPO" --no-pager log --format='  %h %ad %s' --date=short -1 "$BASE_COMMIT"
git -C "$REPO" --no-pager log --format='  %h %ad %s' --date=short -1 "$PATCHED_COMMIT"
git -C "$REPO" --no-pager log --format='  %h %ad %s' --date=short -1 pv-incomplete
git -C "$REPO" --no-pager log --format='  %h %ad %s' --date=short -1 pv-regression
echo
echo "diff between them:"
git -C "$REPO" --no-pager diff --stat "$BASE_COMMIT".."$PATCHED_COMMIT" | sed 's/^/  /'
