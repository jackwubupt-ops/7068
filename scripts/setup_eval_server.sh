#!/usr/bin/env bash
# One-shot setup of a fresh CPU server (Ubuntu, root) for the final DeepSeek experiment:
# no GPU or vLLM. Every step is skipped when already done, so it can be rerun safely.
#
#   cd /data/7068 && bash scripts/setup_eval_server.sh 2>&1 | tee /data/setup.log
#
# Steps: base tools + Docker -> Python 3.11 (Miniforge) -> client and swebench venvs ->
# repository mirrors -> pull the 23 SWE-bench Lite dev eval images -> repair 8 of them
# (scripts/fix_eval_images.sh) -> gold self-test (must resolve 23/23).
# The DeepSeek key is NOT handled here: put DEEPSEEK_API_KEY in /data/7068/.env yourself.
set -euo pipefail

DATA=${DATA:-/data}
REPO=$(cd "$(dirname "$0")/.." && pwd)
PY311=$DATA/py311/bin/python
CLIENT=$REPO/.venv-patchloop-client/bin/python
HARNESS=$DATA/venvs/swebench/bin/python
GOLD=$DATA/eval-selftest/gold.gold-all-dev-fixed.json
step() { printf '\n=== %s ===\n' "$*"; }

step "0. directories and environment"
mkdir -p "$DATA"/{runs,analysis,eval-selftest,app-runs,.cache}
if ! grep -q "MIRROR_ROOT=$DATA/git-mirrors" ~/.bashrc 2>/dev/null; then
  cat >> ~/.bashrc <<EOF
export PIP_CACHE_DIR=$DATA/.cache/pip
export HF_HOME=$DATA/.cache/huggingface
export MIRROR_ROOT=$DATA/git-mirrors
export no_proxy=127.0.0.1,localhost NO_PROXY=127.0.0.1,localhost
EOF
fi
export PIP_CACHE_DIR=$DATA/.cache/pip HF_HOME=$DATA/.cache/huggingface MIRROR_ROOT=$DATA/git-mirrors
echo "cpus: $(nproc)  memory: $(free -g | awk '/Mem/ {print $2}') GiB  free disk: $(df -h "$DATA" | awk 'NR==2 {print $4}')"

step "1. git, screen, curl, Docker"
need=()
for tool in git screen curl; do command -v "$tool" >/dev/null || need+=("$tool"); done
command -v docker >/dev/null || need+=(docker.io)
if [ ${#need[@]} -gt 0 ]; then apt-get update -q && apt-get install -y -q "${need[@]}"; fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker run --rm hello-world >/dev/null && echo "docker ok: $(docker --version)"

step "2. Python 3.11"
if [ ! -x "$PY311" ]; then
  [ -x "$DATA/miniforge/bin/conda" ] || {
    curl -fsSL -o "$DATA/miniforge.sh" https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
    bash "$DATA/miniforge.sh" -b -p "$DATA/miniforge"; }
  "$DATA/miniforge/bin/conda" create -y -q -p "$DATA/py311" python=3.11
fi
"$PY311" --version

step "3. client venv"
if ! "$CLIENT" -c "import openai, flask, datasets" 2>/dev/null; then
  "$PY311" -m venv "$REPO/.venv-patchloop-client"
  "$CLIENT" -m pip install -q -U pip
  "$CLIENT" -m pip install -q -r "$REPO/requirements-lock.txt" "datasets>=3,<5"
fi
echo "client ok"

step "4. swebench venv"
if [ "$("$HARNESS" -c "import importlib.metadata as m; print(m.version('swebench'))" 2>/dev/null)" != "4.1.0" ]; then
  "$PY311" -m venv "$DATA/venvs/swebench"
  "$HARNESS" -m pip install -q -U pip
  "$HARNESS" -m pip install -q -r "$REPO/requirements-swebench-eval.txt"
fi
echo "swebench $("$HARNESS" -c "import importlib.metadata as m; print(m.version('swebench'))")"

step "5. repository mirrors"
cd "$REPO"
"$CLIENT" -m experiments.lite_batch --list-repos | bash scripts/mirror_repos.sh

step "6. evaluation images (pulled BEFORE any evaluation, so the harness keeps them)"
"$CLIENT" -c "
from swebench_dev import load_dev_tasks
for t in load_dev_tasks('princeton-nlp/SWE-bench_Lite'):
    print('swebench/sweb.eval.x86_64.' + t.instance_id.replace('__', '_1776_').lower() + ':latest')" > "$DATA/eval-images.txt"
missing=$(while read -r img; do docker image inspect "$img" >/dev/null 2>&1 || echo "$img"; done < "$DATA/eval-images.txt")
[ -z "$missing" ] || echo "$missing" | xargs -P 6 -n 1 docker pull -q
echo "eval images: $(docker images | grep -c sweb.eval) / $(wc -l < "$DATA/eval-images.txt")"

step "7. repair dependency drift in 8 images"
bash scripts/fix_eval_images.sh

step "8. gold self-test"
if [ ! -f "$GOLD" ]; then
  (cd "$DATA/eval-selftest" && "$HARNESS" -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite \
     --split dev --predictions_path gold --max_workers 8 --run_id gold-all-dev-fixed > gold.log 2>&1) || true
fi
"$CLIENT" -c "import json,sys; r=json.load(open(sys.argv[1])); print('gold resolved', len(r['resolved_ids']), '/ 23')" "$GOLD"
echo "eval images still present: $(docker images | grep -c sweb.eval)"

step "9. DeepSeek key"
if grep -q '^DEEPSEEK_API_KEY=.\+' "$REPO/.env" 2>/dev/null; then
  "$CLIENT" -c "
from patchloop_task2.backends import load_settings, make_backend
r = make_backend('deepseek', load_settings('deepseek')).verify(); print('deepseek', r['status'], r['model'])"
else
  echo "MISSING: add DEEPSEEK_API_KEY to $REPO/.env (see README), then rerun this script"
fi
echo; echo "SETUP-DONE"
