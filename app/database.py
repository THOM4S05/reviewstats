from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str) -> Engine:
    kwargs = {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {}
    result = create_engine(database_url, **kwargs)
    if result.dialect.name == "sqlite":
        @event.listens_for(result, "connect")
        def configure_sqlite(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return result


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
