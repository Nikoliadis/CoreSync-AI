# Database

PostgreSQL 16. The authoritative schema reference is
[docs/03 · Database Schema](../docs/03-database-schema.md).

## What lives here

| Path | Purpose |
|---|---|
| `init/` | Scripts the Postgres container runs once, on first start, **before** Alembic |
| `seeds/` | Optional SQL fixtures for local development |

## What deliberately does not live here

**Alembic migrations stay in [`../backend/migrations/`](../backend/migrations/).** They are
not data files — `env.py` imports `coresync.infrastructure.database.models` to resolve
`target_metadata`, and the migrations themselves import SQLAlchemy. Moving them out of the
Python package would mean either a broken import or a second copy of the model layer.

The split is therefore: `database/` holds SQL that runs *before* the application exists,
`backend/migrations/` holds schema changes that are versioned with the code that depends
on them.

## Ordering

`init/` runs before the first migration because extensions must exist before any
migration references their types — `citext` for email, `vector` for AI retrieval,
`pg_trgm` for the exercise and food search indexes. Alembic also declares these
defensively with `CREATE EXTENSION IF NOT EXISTS`, so a database provisioned without the
init scripts still migrates cleanly. Azure Flexible Server needs the extensions
allow-listed on the server parameter first, which is why the guard is in both places.

## Applying schema changes

```bash
make migrate          # alembic upgrade head
make seed             # exercise catalog (idempotent)
```

Never run migrations on application startup — that races across replicas. They are a
pre-deploy step (docs/03 §13).
