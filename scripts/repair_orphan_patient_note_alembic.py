"""
Repair DB after a missing Alembic revision (e.g. ea2a3e8a4bfc) and orphan patient_note.

- DROP TABLE patient_note if present (CASCADE).
- Reset alembic_version to the current repo head (3c3933060850).

Requires DATABASE_URL in .env. Run from repo root:

  PYTHONPATH=. uv run python scripts/repair_orphan_patient_note_alembic.py

Use only when you intend to align this database with the migrations in this repo.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import settings

REPO_HEAD = "3c3933060850"


def repair(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS patient_note CASCADE"))
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": REPO_HEAD},
        )


def main() -> None:
    url = str(settings.database_url)
    if not url.startswith("postgresql"):
        raise SystemExit("This repair is intended for PostgreSQL.")
    engine = create_engine(url)
    repair(engine)
    print(f"OK: dropped patient_note if existed; alembic_version set to {REPO_HEAD}")
    with engine.connect() as c:
        rows = c.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        print("alembic_version now:", [r[0] for r in rows])
        r = c.execute(text("SELECT to_regclass('public.patient_note')")).fetchone()
        print("patient_note exists:", r[0] is not None)


if __name__ == "__main__":
    main()
