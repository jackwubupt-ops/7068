#!/usr/bin/env bash
# Mirror SWE-bench task repositories locally so batch runs don't depend on a
# flaky GitHub connection (e.g. the AutoDL academic proxy).
#
#   python -m experiments.lite_batch --list-repos | bash scripts/mirror_repos.sh
#
# For each owner/name on stdin: `git clone --mirror` (or `git remote update` if
# it already exists) into $MIRROR_ROOT, then add a per-URL git setting
#   url.<mirror>.insteadOf https://github.com/<owner>/<name>.git
# Only those exact URLs are redirected. Undo one with:
#   git config --global --unset url.<mirror>.insteadOf
set -euo pipefail
MIRROR_ROOT="${MIRROR_ROOT:-/root/autodl-tmp/git-mirrors}"
RETRIES="${MIRROR_RETRIES:-3}"
failed=()

while read -r repo; do
  [ -z "$repo" ] && continue
  case "$repo" in */*) ;; *) echo "skip invalid repo: $repo" >&2; continue ;; esac
  url="https://github.com/${repo}.git"
  dest="${MIRROR_ROOT}/${repo}.git"
  ok=0
  for attempt in $(seq 1 "$RETRIES"); do
    if [ -d "$dest" ]; then
      GIT_CONFIG_GLOBAL=/dev/null git -C "$dest" remote update --prune && ok=1 && break
    else
      mkdir -p "$(dirname "$dest")"
      # Ignore global config so an existing insteadOf can't point the clone at itself.
      GIT_CONFIG_GLOBAL=/dev/null git clone --mirror "$url" "$dest" && ok=1 && break
      rm -rf "$dest"
    fi
    echo "retry $attempt/$RETRIES for $repo" >&2
    sleep 5
  done
  if [ "$ok" = 1 ]; then
    git config --global "url.${dest}.insteadOf" "$url"
    echo "mirrored $repo -> $dest"
  else
    failed+=("$repo")
  fi
done

if [ "${#failed[@]}" -gt 0 ]; then
  echo "FAILED: ${failed[*]}" >&2
  exit 1
fi
