# SHYFEM UI Comprehensive Visual Overhaul — Design Document

**Date:** 2026-02-24
**Approach:** CSS-First Overhaul (Approach A)
**Theme:** Ocean/Environmental

## Summary

Complete visual redesign of the SHYFEM UI: custom ocean-themed design system replacing Shinyswatch, sidebar navigation with workflow grouping, rich dashboard with metrics, adaptive Plotly themes, and polished micro-interactions. All changes are CSS + layout-level; page module internals remain unchanged.

---

## 1. Color System

### Light Mode (`:root`)

| Variable | Value | Usage |
|----------|-------|-------|
| `--sf-ocean-deep` | `#0B3D5B` | Sidebar bg, primary headings |
| `--sf-ocean-mid` | `#1A6B8A` | Active nav, primary buttons |
| `--sf-ocean-light` | `#2D9CBA` | Hover states, links, accents |
| `--sf-teal` | `#3DB8A0` | Success states |
| `--sf-sand` | `#F5F0E8` | Page background |
| `--sf-sand-dark` | `#E8DFD0` | Card bg, subtle separation |
| `--sf-coral` | `#E8725A` | Error/danger states |
| `--sf-amber` | `#E6A641` | Warning states |
| `--sf-foam` | `#FFFFFF` | Card surfaces, inputs |
| `--sf-text` | `#2C3E50` | Body text |
| `--sf-text-muted` | `#6B7C8D` | Secondary text |

### Dark Mode (`[data-bs-theme="dark"]`)

| Variable | Value |
|----------|-------|
| `--sf-ocean-deep` | `#0A2A3C` |
| `--sf-ocean-mid` | `#1A8AAA` |
| `--sf-sand` | `#1A2332` |
| `--sf-sand-dark` | `#243040` |
| `--sf-foam` | `#2A3545` |
| `--sf-text` | `#E0E8F0` |
| `--sf-text-muted` | `#8A9AAB` |

### Typography

- Headings: Inter, 600 weight
- Body: Inter, 400 weight, 14px base, 1.5 line-height
- Code/data: JetBrains Mono, 13px

---

## 2. Sidebar Navigation

### Layout

- Fixed left sidebar: 240px wide, `--sf-ocean-deep` background, white text
- Collapsible to 60px icon-only mode (localStorage persisted)
- Top bar: 48px, logo + title left, dark toggle + user/logout right
- Content area: `--sf-sand` background, 24px padding, vertically scrollable

### Navigation Groups

| Group | Pages | Icons |
|-------|-------|-------|
| Overview | Dashboard, Tutorial | `bi-house`, `bi-mortarboard` |
| Prepare | Grid Prep, Partitioning | `bi-grid-3x3`, `bi-diagram-3` |
| Simulate | Configuration, Run | `bi-sliders`, `bi-play-circle` |
| Analyze | Post-Process, Visualize, Compare, Ensemble | `bi-gear`, `bi-graph-up`, `bi-layout-split`, `bi-collection` |
| Manage | Files, Admin | `bi-folder`, `bi-shield-lock` |

### Active State

- Left border accent: 3px `--sf-ocean-light`
- Slightly lighter background
- Hover: `rgba(255,255,255,0.08)` background

### Implementation

Since Shiny's `navset_tab` doesn't support sidebars, build with:
- `ui.page_fillable()` wrapping a `display:flex` row
- Left div = sidebar (HTML/CSS, clicks → `Shiny.setInputValue()`)
- Right div = conditional content panels based on reactive nav value
- Page modules unchanged internally

---

## 3. Card System & Components

### Cards

- Background: `--sf-foam`
- Border: `1px solid rgba(0,0,0,0.06)` / `rgba(255,255,255,0.06)` dark
- Border-radius: 12px
- Box-shadow: `0 1px 3px rgba(11,61,91,0.08)` → hover: `0 4px 12px rgba(11,61,91,0.12)`
- Header with 12px border-bottom, optional action buttons

### Status Badges

Pill-shaped (`border-radius: 999px`), 11px uppercase, 600 weight:
- Running: `--sf-ocean-mid`
- Completed: `--sf-teal`
- Failed: `--sf-coral`
- Pending: `--sf-sand-dark` with `--sf-text`
- Queued: `--sf-ocean-light`

### Buttons

| Variant | Background | Hover |
|---------|-----------|-------|
| Primary | `--sf-ocean-mid` | `--sf-ocean-deep` |
| Secondary | transparent + border | filled `--sf-ocean-mid` |
| Success | `--sf-teal` | darken 10% |
| Danger | `--sf-coral` | darken 10% |
| Ghost | transparent | `rgba(0,0,0,0.04)` |

All: `border-radius: 8px`, `font-weight: 500`, `transition: 150ms ease`

### Form Inputs

- Border: `1px solid --sf-sand-dark`, `border-radius: 8px`
- Focus ring: `0 0 0 3px rgba(26,107,138,0.15)`

### Progress Bars

- Track: `--sf-sand-dark`, `border-radius: 999px`, 6px height
- Fill: gradient `--sf-ocean-mid` → `--sf-teal`
- Active shimmer animation

### Loading Skeletons

- Pulsing gradient placeholder for async content
- `@keyframes shimmer` on `background-position`

---

## 4. Dashboard Redesign

### Layout: Two-column (65% / 35%)

**Left column:**
- Top: 3 metric cards (Projects count, Active Jobs with pulsing dot, System Health)
- Below: Horizontal scrollable project cards with mesh thumbnails, node counts, last modified. "+" card for new project. Active project highlighted with `--sf-ocean-light` border.

**Right column:**
- Top: Recent Activity timeline (colored dots per event type, relative timestamps)
- Bottom: Quick Start card (New Project, Import Grid, Tutorial buttons)

---

## 5. Plotly Visualization Theme

### Custom Template (`plotly_theme.py`)

**Shared:**
- Font: Inter
- Custom colorscale `shyfem_ocean`: `#0B3D5B` → `#1A6B8A` → `#2D9CBA` → `#3DB8A0` → `#E6A641` → `#E8725A`
- Categorical cycle: 6 colorblind-friendly colors
- Tight margins: `l=60, r=20, t=40, b=50`
- Minimal modebar (download SVG, zoom, pan, reset)

**Light:** white plot bg, `#F5F0E8` paper bg, `rgba(0,0,0,0.06)` gridlines
**Dark:** `#1A2332` plot bg, `#2A3545` paper bg, `rgba(255,255,255,0.08)` gridlines

### Mode Switching

- JavaScript sends `Shiny.setInputValue("_dark_mode", isDark)` on toggle
- Pages react to `input._dark_mode()` and re-render with appropriate template

---

## 6. Micro-interactions

### Transitions

- Page content: `opacity 0→1`, 200ms ease-out on tab switch
- Sidebar collapse/expand: width 250ms ease
- Cards: box-shadow 200ms on hover, `translateY(-2px)` lift on project cards
- Buttons: 150ms on bg-color/shadow, `scale(0.98)` on active press
- Dark mode: 300ms transition on `background-color` and `color`

### Status Animations

- Running badge: pulsing glow (`box-shadow` keyframes, 2s infinite)
- Progress bar: `width 500ms ease` + shimmer on active
- Shiny busy spinner color → `--sf-ocean-mid`

### Not doing

- No parallax, particles, wave animations
- No page slide transitions
- No elastic/bounce easing

---

## 7. Migration Strategy

### Files Changed

| File | Change |
|------|--------|
| `www/css/shyfem.css` | **NEW** — entire design system (~600 lines) |
| `plotly_theme.py` | **NEW** — Plotly template definitions |
| `app.py` | Replace `navset_tab` with sidebar layout, drop `shinyswatch`, load CSS |
| `pages/home.py` | Restructure `home_ui()` for new dashboard layout |
| `pages/*.py` (viz pages) | Add `template=get_plotly_template(...)` to Plotly figures |
| `tests/test_playwright_*.py` | Update nav selectors (tab → sidebar) |

### Unchanged

- All page `*_server()` logic
- All 10 component modules (internal)
- All services, models, middleware
- Database schema

### Rollback

Revert `_build_ui()` + remove CSS file = full restore. No migrations needed.

### Test Impact

- 1004 unit tests: zero impact
- 108 Playwright E2E tests: ~20-30 selector updates for sidebar navigation
