# Alembic Migrations Guide
Date: 2026-02-05

This project uses Alembic to manage schema migrations for the SQLModel models.
Alembic reads the database URL from `app/core/config.py` via `settings.database_url` and
uses `SQLModel.metadata` for autogenerate.

**How Alembic Is Wired Here**
1. `alembic/env.py` pulls the database URL from `settings.database_url`.
1. `alembic/env.py` sets `target_metadata = SQLModel.metadata` so autogenerate can
   compare models to the live database.
1. `alembic.ini` contains a placeholder `sqlalchemy.url`, but it is not used at runtime.

**Files You Update**
1. `app/models/`
   - Update SQLModel classes when adding tables, columns, indexes, or defaults.
   - Keep model defaults in sync with DB defaults for accurate autogeneration.
1. `alembic/versions/<new_revision>.py`
   - A new migration file is generated for each change.
   - Always review and edit the migration to ensure constraints, indexes, and defaults
     are correct.
1. `alembic/env.py` (only when model import paths change)
   - Autogenerate only sees models that are imported before `SQLModel.metadata` is used.
   - If you move models into new modules, make sure they are imported so metadata is
     populated. A common fix is adding `import app.models` near the top of `env.py`.
1. `.env` (or environment variables)
   - Set `DATABASE_URL` to point at the database you want Alembic to compare and upgrade.
1. `alembic.ini` (rare)
   - Only update if you change Alembic script location or logging.

**How To Update Schema**
1. Modify models
   - Edit `app/models/` modules to reflect the new schema.
1. Ensure metadata is loaded
   - If models are split across modules, ensure those modules are imported by `alembic/env.py`.
1. Generate a new migration
   - Alembic compares the current database schema to `SQLModel.metadata` and generates
     a revision file under `alembic/versions/`.
1. Review and adjust the migration
   - Confirm column types, `nullable`, `server_default`, indexes, and foreign keys.
   - For SQLite, some operations may need `op.batch_alter_table` (table rebuild).
1. Apply the migration
   - Upgrade the database to the new revision.

**Commands To Generate And Apply**
Set the DB URL (example for local SQLite) so Alembic connects to the correct database:
```bash
export DATABASE_URL="sqlite:///./physio.db"
```

Generate a new migration from model changes:
```bash
alembic revision --autogenerate -m "describe change"
```

Review the new file in `alembic/versions/`, then apply it:
```bash
alembic upgrade head
```

**Useful Inspection Commands**
```bash
alembic current
alembic history
```

**Rollback Commands (If Needed)**
```bash
alembic downgrade -1
alembic downgrade <revision_id>
```

**Notes For This Repo**
- `app/db/session.py` contains `create_db_and_tables()` which uses `SQLModel.metadata.create_all`.
  For production or shared environments, prefer Alembic migrations instead of `create_all`.
- If `alembic revision --autogenerate` creates an empty migration, it usually means the
  model modules were not imported, so metadata was empty.
