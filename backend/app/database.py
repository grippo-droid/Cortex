"""Database engine, session factory, and the declarative base."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """SQLite ignores foreign keys (and ON DELETE CASCADE) unless enabled per connection."""
    if not _is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables. Adequate for a prototype; Alembic if this grows."""
    from app import models  # noqa: F401  imported so models register on Base.metadata

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


# Columns added after the first release, as (table, column, DDL type). create_all
# only creates missing *tables*, so a database made before one of these was added
# would otherwise fail every query that selects it. This is a stand-in for real
# migrations, not a substitute: it only ever adds nullable columns, and anything
# more involved than that needs Alembic.
_ADDED_COLUMNS = [("documents", "error", "TEXT")]


def _add_missing_columns() -> None:
    if not _is_sqlite:
        return

    from sqlalchemy import text

    with engine.begin() as connection:
        for table, column, ddl_type in _ADDED_COLUMNS:
            existing = {
                row[1]
                for row in connection.execute(text(f"PRAGMA table_info({table})"))
            }
            if existing and column not in existing:
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
                )
