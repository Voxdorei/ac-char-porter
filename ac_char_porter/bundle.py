from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import __version__


BUNDLE_FORMAT = "ac-character-bundle"
BUNDLE_VERSION = 1


def json_default(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def new_bundle(character: dict[str, Any], tables: dict[str, list[dict[str, Any]]], skipped: dict[str, str]) -> dict[str, Any]:
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "tool": {"name": "azerothcore-character-porter", "version": __version__},
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "character_guid": character.get("guid"),
            "character_name": character.get("name"),
            "account": character.get("account"),
        },
        "character": character,
        "tables": tables,
        "skipped": skipped,
    }


def read_bundle(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_bundle(data)
    return data


def write_bundle(path: str | Path, data: dict[str, Any]) -> None:
    validate_bundle(data)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def validate_bundle(data: dict[str, Any]) -> None:
    if data.get("format") != BUNDLE_FORMAT:
        raise ValueError("Not an AzerothCore character bundle")
    if data.get("version") != BUNDLE_VERSION:
        raise ValueError(f"Unsupported bundle version: {data.get('version')!r}")
    if not isinstance(data.get("character"), dict):
        raise ValueError("Bundle is missing the character row")
    if not isinstance(data.get("tables"), dict):
        raise ValueError("Bundle is missing table data")
