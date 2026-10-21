"""Engine / session management."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import config

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(config.DATABASE_URL, echo=config.SQL_ECHO, pool_pre_ping=True, pool_size=5)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine) -> None:
    """Override the engine (used by tests and the seed/init scripts)."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope():
    """Transactional scope: commit on success, rollback on any exception."""
    get_engine()
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> str | None:
    """Return None if the database is reachable and initialised, else a user-safe message."""
    from sqlalchemy import inspect
    try:
        engine = get_engine()
        if "users" not in inspect(engine).get_table_names():
            return "The database is reachable but not initialised. Run: python -m database.init_db --reset"
    except Exception:
        return "The database is not reachable. Check DATABASE_URL in your .env file and that PostgreSQL is running."
    return None
