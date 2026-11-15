#!/usr/bin/env bash
# Evaluate an existing prediction, without making any model API requests.
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "Usage: bash scripts/evaluate_saved_swebench.sh /absolute/predictions.jsonl unique-run-id" >&2
  exit 2
fi
PREDICTIONS="$(realpath "$1")"
RUN_ID="$2"
if [ ! -s "$PREDICTIONS" ]; then echo "Missing predictions.jsonl" >&2; exit 2; fi
case "$RUN_ID" in *[!A-Za-z0-9_.-]*|"") echo "Unsafe run ID" >&2; exit 2;; esac

MODEL_LABEL="$(python - "$PREDICTIONS" <<'PY'
import json,re,sys
from pathlib import Path
rows=Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
assert len(rows)==1, "One task per run for this experiment"
data=json.loads(rows[0])
assert data.get("instance_id")=="sqlfluff__sqlfluff-4764", "Wrong instance"
assert data.get("model_patch","").startswith("diff --git a/"), "No diff"
name=data.get("model_name_or_path","")
assert re.fullmatch(r"[A-Za-z0-9._-]{1,100}",name), "Model label must be path-safe"
print(name)
PY
)"
if [ -e "${MODEL_LABEL}.${RUN_ID}.json" ]; then
  echo "Run ID already has results; choose a NEW ID to prevent stale cached evaluations" >&2
  exit 2
fi

echo "Official SWE-bench 3.0.0 evaluation: ${MODEL_LABEL} / sqlfluff__sqlfluff-4764"
echo "Environment override: types-pkg_resources -> types-setuptools, recorded and disclosed."
set +e
python -m experiments.swebench_eval_compat \
  --dataset_name princeton-nlp/SWE-bench \
  --split dev \
  --instance_ids sqlfluff__sqlfluff-4764 \
  --predictions_path "$PREDICTIONS" \
  --max_workers 1 \
  --timeout 900 \
  --run_id "$RUN_ID"
EVAL_EXIT="$?"
set -e
python -m experiments.swebench_report \
  --instance-id sqlfluff__sqlfluff-4764 \
  --run-id "$RUN_ID" \
  --model "$MODEL_LABEL" \
  --out "swebench-verdict-${RUN_ID}.json"
if [ "$EVAL_EXIT" -ne 0 ]; then
  echo "Official harness exited with error code $EVAL_EXIT" >&2
  exit "$EVAL_EXIT"
fi
