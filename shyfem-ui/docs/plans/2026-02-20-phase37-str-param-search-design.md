# Phase 37: STR Parameter Search — Design

**Created:** 2026-02-20
**Status:** Approved
**Approach:** Pure Python filter (Approach A)

---

## Goal

Add a search/filter box to the STR editor's structured form view so users can
quickly find parameters by name or description across all 483 documented params.

## Decisions

- **Location:** Form view toolbar (above collapsible section cards)
- **Search scope:** Parameter name + description (from COMMON_PARAMS)
- **Unknown params:** Always shown; searched by name only
- **Approach:** Pure Python re-render (no custom JS)

## UI

- Text input with placeholder: `"Search parameters (e.g. 'wind', 'time step')..."`
- Clear button ("X") when text is entered
- Match count badge below input: `"5 params in 3 sections"`
- When empty: full form, no filtering
- Matching param labels get subtle yellow highlight
- Sections with zero matches are hidden

## Filtering Logic

Pure function `filter_sections()`:

```
Input:  search_term (str), parsed StrFile
Output: dict[section_name → list[param_name]]
```

Rules:
- Case-insensitive substring on param name OR description
- Unknown params (not in COMMON_PARAMS) match on name only
- Empty term → all params (no filtering)
- Sections with zero matches omitted from output

## Rendering Changes

- `_build_form_panel()` gains optional `search_filter: dict | None` parameter
- When provided, only renders params in the filter dict
- Matching labels highlighted with light yellow background
- "Apply Form Changes" button always visible

## Wiring

- Search input namespaced under str_editor module ID
- `input.str_param_search()` → reactive → triggers form panel rebuild
- Only affects form mode (raw view and split layout unchanged)

## Testing (~10-12 tests)

Pure function tests for `filter_sections()`:
- Empty search → all sections
- Match by param name (substring)
- Match by description (substring)
- Case insensitive
- No matches → empty dict
- Unknown params matched by name
- Mixed matches per section
- Single character search
- Special regex chars treated as literal
