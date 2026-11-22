#!/usr/bin/env bash
# Bundle the small, submission-ready result files from the server into one archive:
# reports, per-batch manifests/summaries/official verdicts/predictions/run statuses,
# the gold self-test report and the sample traces. No API keys, no repository checkouts.
#
#   bash scripts/export_results.sh            # -> /data/patchloop-final-results.tar.gz
set -euo pipefail
DATA=${DATA:-/data}
STAGE=$(mktemp -d)
OUT=$STAGE/final_results
mkdir -p "$OUT/analysis" "$OUT/runs" "$OUT/samples" "$OUT/eval-selftest"

cp "$DATA"/analysis/*.md "$DATA"/analysis/*.json "$DATA"/analysis/*.txt "$OUT/analysis/" 2>/dev/null || true
cp "$DATA"/eval-selftest/*.json "$OUT/eval-selftest/" 2>/dev/null || true
cp "$DATA"/results/samples/* "$OUT/samples/" 2>/dev/null || true

for batch in "$DATA"/runs/final-ds* "$DATA"/runs/final-t4*; do
  [ -d "$batch" ] || continue
  name=$(basename "$batch"); dest="$OUT/runs/$name"; mkdir -p "$dest"
  for f in manifest.json summary.json official_eval.json results.jsonl all_preds.jsonl; do
    [ -f "$batch/$f" ] && cp "$batch/$f" "$dest/"
  done
  for task in "$batch"/*/run_status.json; do
    [ -f "$task" ] || continue
    t=$(basename "$(dirname "$task")"); case "$t" in *.interrupted-*) continue ;; esac
    mkdir -p "$dest/$t"; cp "$task" "$dest/$t/"
  done
done
# Safety: nothing that looks like a key may leave the server.
if grep -rIl "sk-[A-Za-z0-9]\{20,\}" "$OUT" >/dev/null 2>&1; then
  echo "ERROR: something that looks like an API key is in the bundle; aborting" >&2; exit 1
fi
tar czf "$DATA/patchloop-final-results.tar.gz" -C "$STAGE" final_results
rm -rf "$STAGE"
echo "batches: $(ls -d "$DATA"/runs/final-ds* "$DATA"/runs/final-t4* 2>/dev/null | grep -vc '\.')  samples: $(ls "$DATA"/results/samples 2>/dev/null | wc -l)"
ls -lh "$DATA/patchloop-final-results.tar.gz"
