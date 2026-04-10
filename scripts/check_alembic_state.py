"""Print alembic_version and whether patient_note exists (masked DB URL)."""

from sqlalchemy import create_engine, text

from app.core.config import settings


def mask(u: str) -> str:
    if "@" not in u:
        return u
    pre, rest = u.split("@", 1)
    if "://" in pre:
        scheme, cred = pre.split("://", 1)
        if ":" in cred:
            user = cred.split(":")[0]
            return f"{scheme}://{user}:***@{rest}"
    return u.split("@")[0] + "@***"


def main() -> None:
    url = str(settings.database_url)
    print("db:", mask(url))
    eng = create_engine(url)
    with eng.connect() as c:
        rows = c.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        print("alembic_version:", [r[0] for r in rows])
        if url.startswith("sqlite"):
            r = c.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='patient_note'"
                )
            ).fetchone()
            print("patient_note table:", bool(r))
        else:
            r = c.execute(text("SELECT to_regclass('public.patient_note')")).fetchone()
            print("patient_note table:", r[0] is not None)


if __name__ == "__main__":
    main()
