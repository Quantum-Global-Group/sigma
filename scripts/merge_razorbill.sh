#!/usr/bin/env bash
# merge_razorbill.sh
#
# Imports razorBill into this repo via `git subtree`, preserving its history
# under _legacy_razorbill/. After this lands, follow up with the per-area
# port commits enumerated in plans/let-s-go-over-this-reactive-fern.md
# (steps 5-9 of the migration sequencing).
#
# Run from sigma repo root with a CLEAN working tree:
#   ./scripts/merge_razorbill.sh /path/to/razorBill
#
# Or with a remote:
#   ./scripts/merge_razorbill.sh git@github.com:owner/razorBill.git main
#
# This script does not delete _legacy_razorbill/ — that's a separate cleanup
# commit after every module has been moved into its final sigma location.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <path-or-url> [branch=main]" >&2
  exit 1
fi

SOURCE="$1"
BRANCH="${2:-main}"
PREFIX="_legacy_razorbill"

if [[ -d "$PREFIX" ]]; then
  echo "ERROR: $PREFIX already exists. Did this script run already? Aborting." >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: working tree is dirty. Commit or stash before running." >&2
  exit 1
fi

REMOTE_NAME="razorbill-import-tmp"

# A local path source has to be wrapped as a remote so subtree can fetch it.
# No --squash: every razorBill commit is preserved in sigma's history under
# the _legacy_razorbill/ prefix.
if [[ -d "$SOURCE/.git" ]]; then
  git remote add "$REMOTE_NAME" "$SOURCE"
  trap 'git remote remove "$REMOTE_NAME" 2>/dev/null || true' EXIT
  git fetch "$REMOTE_NAME" "$BRANCH"
  git subtree add --prefix="$PREFIX" "$REMOTE_NAME" "$BRANCH"
else
  # URL — let subtree fetch directly
  git subtree add --prefix="$PREFIX" "$SOURCE" "$BRANCH"
fi

echo
echo "✓ razorBill imported under $PREFIX/"
echo "  Next: port modules into apps/api/ per plan, then delete $PREFIX/."
