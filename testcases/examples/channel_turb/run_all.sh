#!/bin/bash
# k-eps vs GOTM neutral open-channel benchmark. Needs the model built
# (bin/shyfem) and Python 3 with numpy. ~12 s per run, 8 runs.
# Everything generated (grid, STRs, GOTM namelists, output) goes into the
# untracked run/ folder; no tracked file is written (#307).
set -e
cd "$(dirname "$0")"
export PATH="$(cd ../../.. && pwd)/bin:$PATH"
HERE=$(pwd)
# snapshot of this folder's git state, to check at the end that the run left
# every tracked file as it was (skipped outside a git checkout)
gitstate() {
  git -C "$HERE" status --short -- . 2>/dev/null
  git -C "$HERE" diff HEAD -- . 2>/dev/null | cksum
}
before=$(gitstate)
mkdir -p run/INPUT
cd run
python3 "$HERE/make_grid.py" >/dev/null
python3 "$HERE/make_cases.py" >/dev/null
shypre -silent channel.grd >shypre.log 2>&1
for nl in 20 40; do
  for run in keps gotm_gen gotm_ke1 gotm_ke2; do
    shyfem -debout ${run}_${nl}.str >${run}_${nl}.out 2>&1
    grep -q "simulation end" ${run}_${nl}.out || { echo "${run}_${nl} failed"; exit 1; }
  done
done
python3 "$HERE/analyse.py"
if git -C "$HERE" rev-parse --git-dir >/dev/null 2>&1; then
  after=$(gitstate)
  if [ "$before" != "$after" ]; then
    echo "run_all.sh changed tracked files in $HERE (#307):"
    git -C "$HERE" status --short -- .
    exit 1
  fi
fi
