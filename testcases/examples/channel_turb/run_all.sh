#!/bin/bash
# k-eps vs GOTM neutral open-channel benchmark. Needs the model built
# (bin/shyfem) and Python 3 with numpy. ~12 s per run, 8 runs.
set -e
cd "$(dirname "$0")"
export PATH="$(cd ../../.. && pwd)/bin:$PATH"
python3 make_grid.py >/dev/null
python3 make_cases.py >/dev/null
shypre -silent channel.grd >shypre.log 2>&1
for nl in 20 40; do
  for run in keps gotm_gen gotm_ke1 gotm_ke2; do
    shyfem -debout ${run}_${nl}.str >${run}_${nl}.out 2>&1
    grep -q "simulation end" ${run}_${nl}.out || { echo "${run}_${nl} failed"; exit 1; }
  done
done
python3 analyse.py
