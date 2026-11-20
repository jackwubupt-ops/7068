#!/usr/bin/env bash
# Repair dependency drift in prebuilt SWE-bench Lite DEV evaluation images.
#
# A gold-patch self-test (official harness, swebench==4.1.0) resolved only 15/23
# Lite dev tasks on our machine. The 8 failures were environment problems, not
# task problems:
#   pvlib  (5 tasks)       NumPy 2.x installed; pvlib at these commits uses np.Inf
#   pydicom-1139 / -1413   pytest 8 no longer calls nose-style setup() -> no 'tag'
#   pyvista-4315           libGL.so.1 missing in the image
# This script rebuilds ONLY those local images with one extra layer (same tag),
# changing no code, tests or task data. Re-run the gold self-test afterwards and
# only count tasks whose gold patch resolves. Disclose this repair in the report.
#
#   bash scripts/fix_eval_images.sh            # after the images were pulled once
set -euo pipefail

fix() {
  local pattern="$1" step="$2" found=0
  for img in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "sweb\.eval\.x86_64\.${pattern}"); do
    found=1
    if docker image inspect "$img" --format '{{json .Config.Labels}}' | grep -q patchloop.envfix; then
      echo "already fixed: $img"; continue
    fi
    printf 'FROM %s\n%s\nLABEL patchloop.envfix="%s"\n' "$img" "$step" "$step" \
      | docker build -q -t "$img" - >/dev/null
    echo "fixed: $img"
  done
  [ "$found" = 1 ] || echo "no local image matches $pattern (pull it by running the harness once)" >&2
}

fix 'pvlib_1776_pvlib-python' 'RUN /opt/miniconda3/envs/testbed/bin/pip install -q "numpy<2"'
fix 'pydicom_1776_pydicom-1(139|413)' 'RUN /opt/miniconda3/envs/testbed/bin/pip install -q "pytest<8"'
fix 'pyvista_1776_pyvista-4315' 'RUN apt-get update -qq && apt-get install -y -qq libgl1 libxrender1 >/dev/null && rm -rf /var/lib/apt/lists/*'
