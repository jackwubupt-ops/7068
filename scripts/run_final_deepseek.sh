#!/usr/bin/env bash
# Final comparison experiment on the DeepSeek API (deepseek-flash), end to end:
#
#   0. preflight: one tiny real DeepSeek call (fails fast on a bad key/model)
#   1. generation: SWE-bench Lite dev, identical settings everywhere:
#        RQ3  P-C-R and single agent, reasoning effort none
#        RQ1  P-C-R at reasoning effort low / high (RQ1_EFFORTS; add "max" if budget allows)
#   2. official evaluation of every batch (local Docker, swebench==4.1.0)
#   3. (optional) re-evaluate the earlier Qwen-7B batches on the SAME repaired images,
#      keeping their old verdicts as official_eval.pre-repair.json
#   4. final_report: per-config table + paired McNemar/bootstrap comparisons,
#      restricted to the tasks whose gold patch resolves in this environment
#
# No GPU and no vLLM are needed. Docker + the swebench venv are needed for steps 2-3.
# Rerunning the script resumes: finished batches/evaluations are skipped.
#
#   cd /data/7068 && source .venv-patchloop-client/bin/activate
#   QWEN_PCR=/data/runs/lite-pilot-v3-pcr QWEN_SINGLE=/data/runs/lite-pilot-v3-single \
#     bash scripts/run_final_deepseek.sh
set -euo pipefail

RUNS=${RUNS:-/data/runs}
TAG=${TAG:-final-ds}                       # batch dirs: $RUNS/$TAG-pcr, $TAG-single, $TAG-pcr-<effort>
RQ1_EFFORTS=${RQ1_EFFORTS:-low high}       # P-C-R reasoning efforts besides none ("" = skip RQ1)
PY=${PY:-python}                           # client venv python (has the repo deps)
HARNESS_PY=${HARNESS_PY:-/data/venvs/swebench/bin/python}
WORKERS=${WORKERS:-4}                      # same for every batch of the comparison
EVAL_WORKERS=${EVAL_WORKERS:-8}
RETRIEVAL_K=${RETRIEVAL_K:-10}
EDIT_FORMAT=${EDIT_FORMAT:-search_replace}
GOLD_REPORT=${GOLD_REPORT:-/data/eval-selftest/gold.gold-all-dev-fixed.json}
QWEN_PCR=${QWEN_PCR:-}                     # earlier Qwen-7B batch dirs (optional)
QWEN_SINGLE=${QWEN_SINGLE:-}
OUT=${OUT:-/data/analysis/final-comparison}
SKIP_EVAL=${SKIP_EVAL:-0}                  # 1 = generation only (no Docker on this machine)
EVAL_SUFFIX=${EVAL_SUFFIX:-}               # e.g. -r2 to retry an incomplete evaluation (run ids are single-use)

cd "$(dirname "$0")/.."
mkdir -p "$RUNS" "$(dirname "$OUT")"
log() { printf '\n=== %s ===\n' "$*"; }

# config = agent:effort ; batch dir suffix and report label follow from it
configs=("pcr:none" "single:none")
for effort in $RQ1_EFFORTS; do configs+=("pcr:$effort"); done
suffix() { [ "$2" = none ] && echo "$1" || echo "$1-$2"; }

log "0. DeepSeek preflight (efforts: none $RQ1_EFFORTS)"
"$PY" - none $RQ1_EFFORTS <<'EOF'
import sys
from patchloop_task2.backends import load_settings, make_backend
for effort in sys.argv[1:]:
    s = load_settings("deepseek", reasoning_effort=effort)
    r = make_backend("deepseek", s).verify()
    print({k: r[k] for k in ("status", "model", "reasoning_effort", "endpoint")})
    if s.model != "deepseek-flash":
        print(f"NOTE: DEEPSEEK_MODEL={s.model}; the final experiment is specified for deepseek-flash")
EOF

log "1. generation (Lite dev, $EDIT_FORMAT, retrieval top-$RETRIEVAL_K, workers $WORKERS)"
for config in "${configs[@]}"; do
  agent=${config%%:*} effort=${config#*:}
  dir="$RUNS/$TAG-$(suffix "$agent" "$effort")"
  resume=()
  [ -f "$dir/manifest.json" ] && resume=(--resume)
  "$PY" -m experiments.lite_batch --backend deepseek --agent "$agent" --reasoning-effort "$effort" \
    --out "$dir" ${resume[@]+"${resume[@]}"} \
    --edit-format "$EDIT_FORMAT" --retrieval-k "$RETRIEVAL_K" --workers "$WORKERS" \
    2>&1 | tee -a "$dir.log"
  "$PY" -c "import json,sys; s=json.load(open(sys.argv[1])); assert s['tasks_finished']==s['tasks_total'], s; print('finished', s['tasks_finished'], 'ready', s['prediction_ready'])" "$dir/summary.json"
done

if [ "$SKIP_EVAL" = 1 ]; then
  log "SKIP_EVAL=1: stopping after generation; run official evaluation on a Docker host"
  exit 0
fi

evaluate() {  # evaluate DIR RUN_ID  (skips a batch that already has a complete verdict for RUN_ID)
  local dir=$1 run_id=$2
  if "$PY" -c "import json,sys; e=json.load(open(sys.argv[1])); sys.exit(0 if e.get('complete') and e.get('run_id')==sys.argv[2] else 1)" \
       "$dir/official_eval.json" "$run_id" 2>/dev/null; then
    echo "$dir: already evaluated as $run_id"; return
  fi
  "$PY" -m experiments.official_eval --batch "$dir" --harness-python "$HARNESS_PY" \
    --max-workers "$EVAL_WORKERS" --run-id "$run_id" 2>&1 | tee -a "$dir.eval.log"
}

log "2. official evaluation (DeepSeek batches)"
batches=()
for config in "${configs[@]}"; do
  name=$(suffix "${config%%:*}" "${config#*:}")
  evaluate "$RUNS/$TAG-$name" "$TAG-$name-eval$EVAL_SUFFIX"
  batches+=(--batch "ds-$name=$RUNS/$TAG-$name")
done

log "3. re-evaluate Qwen-7B batches on the repaired images"
for pair in "pcr:$QWEN_PCR" "single:$QWEN_SINGLE"; do
  agent=${pair%%:*} dir=${pair#*:}
  [ -n "$dir" ] || { echo "QWEN_$(echo "$agent" | tr a-z A-Z) not set: skipping the Qwen $agent baseline"; continue; }
  [ -f "$dir/manifest.json" ] || { echo "ERROR: $dir is not a batch directory" >&2; exit 1; }
  if [ -f "$dir/official_eval.json" ] && [ ! -f "$dir/official_eval.pre-repair.json" ]; then
    cp "$dir/official_eval.json" "$dir/official_eval.pre-repair.json"
  fi
  evaluate "$dir" "$(basename "$dir")-repaired$EVAL_SUFFIX"
  batches+=(--batch "qwen-$agent=$dir")
done

log "4. final report"
tasks=()
if [ -f "$GOLD_REPORT" ]; then
  "$PY" -c "import json,sys; ids=json.load(open(sys.argv[1]))['resolved_ids']; open(sys.argv[2],'w').write('\n'.join(sorted(ids))+'\n'); print(len(ids),'gold-resolvable tasks')" \
    "$GOLD_REPORT" "$OUT.gold-tasks.txt"
  tasks=(--tasks-file "$OUT.gold-tasks.txt")
else
  echo "WARNING: $GOLD_REPORT missing; reporting over all tasks (run runbook stage 14 first)"
fi
"$PY" -m experiments.final_report "${batches[@]}" ${tasks[@]+"${tasks[@]}"} --out "$OUT"
"$PY" -m experiments.final_report "${batches[@]}" --out "$OUT.all-tasks" > /dev/null
echo "Wrote $OUT.md / $OUT.json (gold-resolvable tasks) and $OUT.all-tasks.md (all tasks)"
