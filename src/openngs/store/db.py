"""Thin, dialect-aware DB-API wrapper: SQLite (stdlib) or Postgres (pg8000, BSD-3 -
psycopg2/psycopg are LGPL, which invariant 8 rules out).

This is not an ORM. Callers write portable SQL by hand and use `Database.ph(n)` for
placeholders, since sqlite3 uses "?" and pg8000 uses "%s". Both the event log (events.py,
and the graph projection it feeds live in the one database this wraps.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit

DEFAULT_DB_URL = "sqlite:///openngs.db"


class Database:
    """Wraps a DB-API 2.0 connection (sqlite3 or pg8000.dbapi) with a uniform interface."""

    def __init__(self, conn: Any, placeholder: str, dialect: str) -> None:
        self._conn = conn
        self._placeholder = placeholder
        self.dialect = dialect
        # Who is doing this unit of work, recorded on every event emitted through this
        # connection (`Event.recorded_by`). A property of the connection rather than an
        # argument to each write, because one connection is exactly one request or one CLI
        # invocation, and threading it through fifteen record_* signatures would say the
        # same thing fifteen times.
        self.recorded_by: str | None = None

    @classmethod
    def connect(cls, db_url: str, recorded_by: str | None = None) -> Database:
        parts = urlsplit(db_url)
        if parts.scheme == "sqlite":
            if not db_url.startswith("sqlite:///"):
                raise ValueError(
                    f"invalid sqlite URL {db_url!r} - expected sqlite:///path/to/file.db "
                    "or sqlite:///:memory:"
                )
            path = db_url[len("sqlite:///") :]
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA foreign_keys = ON")
            db = cls(conn, "?", "sqlite")
            db.recorded_by = recorded_by
            return db
        if parts.scheme in ("postgresql", "postgres"):
            import pg8000.dbapi as pg8000_dbapi

            conn = pg8000_dbapi.connect(
                host=parts.hostname or "localhost",
                port=parts.port or 5432,
                user=parts.username or "",
                password=parts.password or "",
                database=parts.path.lstrip("/"),
            )
            db = cls(conn, "%s", "postgresql")
            db.recorded_by = recorded_by
            return db
        raise ValueError(
            f"unsupported database URL scheme {parts.scheme!r} - use sqlite:// or postgresql://"
        )

    def ph(self, n: int) -> str:
        """n comma-separated placeholders, dialect-appropriate."""
        return ", ".join([self._placeholder] * n)

    def is_unique_violation(self, exc: BaseException) -> bool:
        """Whether this exception is a unique-index violation, per dialect.

        Not `except SomeDriver.IntegrityError`: pg8000 raises its own
        `pg8000.exceptions.DatabaseError` straight from the protocol layer for this, never
        reaching the DB-API `IntegrityError` its dbapi module defines. Caught only by
        running against a real Postgres - SQLite alone reports it the expected way, so the
        test suite could not have found it.
        """
        if self.dialect == "sqlite":
            return isinstance(exc, sqlite3.IntegrityError) and "UNIQUE constraint" in str(exc)
        # pg8000 hands back the server's error fields as a dict; 'C' is the SQLSTATE, and
        # 23505 is unique_violation.
        args: tuple[Any, ...] = getattr(exc, "args", ())
        if not args or not isinstance(args[0], dict):
            return False
        return bool(args[0].get("C") == "23505")

    def timestamp(self, value: datetime) -> Any:
        """Bind a timestamp for comparison against a stored one, per dialect.

        SQLite has no datetime type: these columns hold the exact ISO 8601 string that was
        written, and since every timestamp is normalized to UTC before writing, lexical
        order is chronological order. Postgres holds a real TIMESTAMP WITH TIME ZONE, and
        pg8000 would send a str as text - comparing timestamptz to text is an error - so it
        needs a datetime object.

        Inserts don't need this: the target column's type is known there, so Postgres casts
        an ISO string on its own. Only comparisons are ambiguous.
        """
        return value.isoformat() if self.dialect == "sqlite" else value

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> tuple[Any, ...] | None:
        row = self.execute(sql, params).fetchone()
        return tuple(row) if row is not None else None

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in self.execute(sql, params).fetchall()]

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
