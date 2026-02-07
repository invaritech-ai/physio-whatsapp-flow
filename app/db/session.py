from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings


connect_args: dict = {}
pool_kwargs: dict = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    pool_kwargs = {"pool_pre_ping": True, "pool_recycle": 300}

engine = create_engine(
    settings.database_url, connect_args=connect_args, **pool_kwargs
)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
