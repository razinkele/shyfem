# Phase 28: Database Query Optimization — Design

**Date:** 2026-02-14

## Scope

Add connection pool configuration for PostgreSQL deployments. SQLite
keeps current `StaticPool`-equivalent behavior (single-threaded,
`check_same_thread=False`).

**Config fields:**
- `db_pool_size` (default 5) — core pool connections
- `db_pool_overflow` (default 10) — extra connections under load
- `db_pool_recycle` (default 3600) — seconds before recycling stale connections

**Engine changes:**
- PostgreSQL: pass `pool_size`, `max_overflow`, `pool_recycle`, `pool_pre_ping=True`
- SQLite: keep current `connect_args={"check_same_thread": False}`, no pool args

## Skipped

- **28.1 Eager loading** — Dashboard converts relationships to dicts
  immediately, so N+1 queries don't occur in practice. Low ROI.
- **28.2 Pagination** — Job listing already has configurable `limit`
  parameter (100 local, 500 DB). No UI pagination needed for current
  user base.
- **Foreign key indexes** — SQLAlchemy auto-creates indexes on
  ForeignKey columns in most backends. Not worth a migration.
