# Box-model manifest form — Implementation Plan

**Goal:** create and edit `boxmodel.json` from the UI. It must be hand-written
today, which is the last thing standing between the Box model page and a new
dataset. The final deferred item of the feature.

## The schema, as the loader defines it

`services/boxmodel_manifest.py` is and stays the only validator. The form
writes what it accepts:

| key | required | notes |
|---|---|---|
| `schema` | yes | always `1` |
| `title` | no | string, ≤ 200 chars, defaults to "Box model" |
| `grid.grd` | **yes** | the mesh |
| `grid.bas`, `grid.boxes_txt` | no | |
| `boxes.polygons` | no | outlines; `boxes.layer` names a layer inside it |
| `boxes.id_field` | no | identifier, defaults to `box` |
| `str` | no | the STR the Setup tab reads |
| `forcing.dir` | no | where `boundn` files are resolved |
| `observations.file`, `observations.sites` | no | |
| `runs[]` | **yes, ≥ 1** | `id` (`[a-z0-9_-]+`, ≤ 64, unique), `label`, `dir` |

Relative paths resolve against the project directory and may not escape it.
**An absolute path is allowed and is the normal case for `runs[].dir`** — the
Curonian manifest points at an analysis root outside the project — and is
confined by `Config.confine_path` alone.

## Scope

1. A **Manifest** tab on the Box model page, editor-gated server-side.
2. Every path field is a picker, never free text. Names (`title`, `label`,
   `id`, `id_field`, `layer`) stay text.
3. A **runs editor**: add and remove rows, each with id, label and directory,
   following the boundary editor's pattern (a `reactive.value` list of dicts
   rendered by one `@render.ui`, per-row input ids).
4. **Run directories can be outside the project**, so their picker offers
   project directories *and* directories under the configured analysis roots.
   A project-only dropdown could not express the one real manifest we have.
5. **Save** writes atomically and then re-loads through `load_manifest`; a file
   that does not load is rolled back, so the page can never be left pointing at
   a manifest the loader rejects.
6. **Create when absent**: the tab is the way to write the first manifest, not
   just to edit one.

## Rules

- **One validator.** The form never re-implements the loader's rules. It
  builds a candidate, asks the loader, and shows the loader's own message,
  which already names the offending key.
- **Never leave a broken manifest.** Validate the candidate before replacing
  the file; on any failure the previous file stays exactly as it was.
- **Editor gate on the server**, like build and cancel, not in the UI only.
- Writes go through the project's write confinement.
- After a successful save the page reloads the manifest, so the run selector
  and every tab follow immediately.

## Open question for review before coding

Listing directories under the analysis roots in a dropdown shows every
authenticated user the names of run directories an admin has declared readable.
That is what an analysis root already means — the page reads run output from
them for any user — but a *listing* is new, and it should be an explicit
decision rather than a side effect.

## Tests

- Service-level: building the JSON from a form state, round-tripping through
  `load_manifest`, and the rollback when the candidate does not load.
- The runs editor: add, remove, duplicate id, empty list (the loader requires
  at least one run).
- Path fields: a project-relative pick, an analysis-root pick, and a rejected
  escape.
- E2E: write a manifest for the fixture project from an empty state, then see
  the run appear in the selector.
- Every branch that produces a written value must be executed by a test, not
  asserted as source text.
