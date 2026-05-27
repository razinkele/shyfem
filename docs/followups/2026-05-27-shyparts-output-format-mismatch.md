# Follow-up: Partition analysis reads a `.par` format that `shyparts` does not produce

**Severity:** Medium (a UI feature — partition inspection/validation — operates on files that never exist, so it silently returns empty/degenerate results against real runs).

**Origin:** 2026-05-27 multi-angle review of `docs/superpowers/plans/2026-05-27-deferred-issues-master-plan.md` (Phase I, "Deepen Validate Partitions"). The review found Phase I would deepen validation of a phantom file format; tracing it back showed the *existing* partition-analysis code already targets that non-existent format.

**Problem.** The UI's partition tooling expects per-partition `.par` files:

- `services/shyfem_wrapper.py:53` declares `"shyparts": [".par"]` as the tool's output glob.
- `services/partitioning_logic.py:14` (`parse_par_file`) and `:61` read `output_dir / f"partition.{i:04d}.par"` (e.g. `partition.0000.par`, `partition.0001.par`, …).

But the Fortran `shyparts`, invoked as `shyparts -np <N> <bas>` (`shyfem_wrapper.py:288-310`), writes **no `.par` files**. Its actual outputs (`src/utils/shympi/shyparts_util.f90`):

- `partition.<np>.txt` — a single summary table (`make_name_with_number('partition',nparts,'txt',name)`, line 128)
- `<grd>.<np>.node.grd` — partition coloring on nodes (line 277)
- `<grd>.<np>.elem.grd` — partition coloring on elements (line 294)

A repo-wide search finds no `.par` writer anywhere in `src/` (Fortran/C). The filenames don't even share a shape: the UI expects one zero-padded file *per partition index*; shyparts writes one `.txt` summary plus two `.grd` files for the whole decomposition.

**Consequence.** `analyze_partitions` / `validate_partition_files` glob/parse files that are never created, so against real shyparts output they return empty maps / "no files found". The "Validate Partitions" UI feature is effectively non-functional on real runs. (It likely worked against an older shyparts build, or was written speculatively — the `.txt` summary format is dated `18.11.2024` in the Fortran header, suggesting the output format changed under the UI.)

**Compounding domain issue (blocks Phase I's design, not just the format).** Phase I assumed each mesh element belongs to exactly one partition, so it proposed duplicate/missing/phantom element checks. That model is wrong for SHYFEM: partitioning is **node-based**, and boundary/ghost elements are legitimately shared — `count_elements` counts an element toward *every* partition owning ≥1 of its nodes (`netot`), and `info_partition` prints a dedicated "ghost" column (`netot − neint`). So element-level duplicate/phantom checks would false-alarm on every correctly-partitioned mesh, and an empty partition at high `np` is a warn-worthy (not fatal) condition.

**Suggested fix.**
1. Point the reader at the real artifacts: parse `partition.<np>.txt` for the summary/stats, and `<grd>.<np>.node.grd` / `<grd>.<np>.elem.grd` for the node/element partition coloring (reuse the existing `.grd` parser, `parser_grd.py`). Update `shyfem_wrapper.py:53`'s output glob accordingly.
2. Re-scope any validation to the **node** partition and treat ghost-element overlap as expected. Keep `validate_partition_count` (found vs requested `np`); make empty-partition a warning.
3. Add a regression test that runs `shyparts -np N` on a small `.bas` and asserts the reader finds the files shyparts actually wrote (this would have caught the drift).

**Related code:**
- `shyfem-ui/shyfem_ui/services/partitioning_logic.py:14,42,61` (`.par` reader)
- `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:53,288-310` (output glob + invocation)
- `shyfem-ui/shyfem_ui/services/parser_grd.py:99-118` (`.grd` parser to reuse)
- `src/utils/shympi/shyparts_util.f90:128,277,294` (actual shyparts output filenames)
- `src/tools/shyparts/shyparts.f90` (entry point)
