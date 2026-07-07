from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL


def conn():
    return psycopg2.connect(DATABASE_URL)


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    with conn() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row or {})


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
