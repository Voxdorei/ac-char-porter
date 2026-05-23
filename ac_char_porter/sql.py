from __future__ import annotations

import re
from typing import Any, Iterable


IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER.match(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f"`{identifier}`"


def insert_sql(table: str, row: dict[str, Any]) -> tuple[str, list[Any]]:
    if not row:
        raise ValueError("Cannot insert an empty row")
    columns = list(row)
    column_sql = ", ".join(quote_identifier(column) for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {quote_identifier(table)} ({column_sql}) VALUES ({placeholders})"
    return sql, [row[column] for column in columns]


def select_by_column_sql(table: str, columns: Iterable[str]) -> str:
    where = " AND ".join(f"{quote_identifier(column)} = %s" for column in columns)
    return f"SELECT * FROM {quote_identifier(table)} WHERE {where}"
