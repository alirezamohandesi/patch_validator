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

echo
git -C "$REPO" --no-pager log --format='  %h %ad %s' --date=short -1 "$BASE_COMMIT"
git -C "$REPO" --no-pager log --format='  %h %ad %s' --date=short -1 "$PATCHED_COMMIT"
echo
echo "diff between them:"
git -C "$REPO" --no-pager diff --stat "$BASE_COMMIT".."$PATCHED_COMMIT" | sed 's/^/  /'
