from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from .sql import quote_identifier


def connect_mysql(host: str, port: int, user: str, password: str, database: str):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


@contextmanager
def cursor(conn) -> Iterator[Any]:
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


def table_columns(conn, table: str) -> set[str]:
    with cursor(conn) as cur:
        cur.execute(f"SHOW COLUMNS FROM {quote_identifier(table)}")
        return {row["Field"] for row in cur.fetchall()}


def table_exists(conn, table: str) -> bool:
    with cursor(conn) as cur:
        cur.execute("SHOW TABLES LIKE %s", (table,))
        return cur.fetchone() is not None


def fetch_all_where(conn, table: str, column: str, value: Any) -> list[dict[str, Any]]:
    with cursor(conn) as cur:
        cur.execute(f"SELECT * FROM {quote_identifier(table)} WHERE {quote_identifier(column)} = %s", (value,))
        return list(cur.fetchall())


def fetch_in(conn, table: str, column: str, values: list[Any]) -> list[dict[str, Any]]:
    if not values:
        return []
    placeholders = ", ".join(["%s"] * len(values))
    with cursor(conn) as cur:
        cur.execute(
            f"SELECT * FROM {quote_identifier(table)} WHERE {quote_identifier(column)} IN ({placeholders})",
            values,
        )
        return list(cur.fetchall())


def next_integer_id(conn, table: str, column: str, count: int = 1, *, minimum: int | None = None) -> list[int]:
    with cursor(conn) as cur:
        cur.execute(f"SELECT COALESCE(MAX({quote_identifier(column)}), 0) + 1 AS next_id FROM {quote_identifier(table)}")
        start = int(cur.fetchone()["next_id"])
    if minimum is not None:
        start = max(start, minimum)
    return list(range(start, start + count))
