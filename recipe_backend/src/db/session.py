from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""


def _create_engine():
    settings = get_settings()
    # Using psycopg (psycopg3) driver. SQLAlchemy will pick it up automatically.
    return create_engine(settings.postgres_url, pool_pre_ping=True)


_ENGINE = _create_engine()
_SessionLocal = sessionmaker(bind=_ENGINE, autocommit=False, autoflush=False, class_=Session)


# PUBLIC_INTERFACE
def get_engine():
    """Return the global SQLAlchemy engine instance."""
    return _ENGINE


# PUBLIC_INTERFACE
@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Yields:
        Session: SQLAlchemy session

    Raises:
        Exception: re-raises any exception after rollback.
    """
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# PUBLIC_INTERFACE
def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a DB session."""
    with session_scope() as session:
        yield session
