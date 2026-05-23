from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bundle import new_bundle
from .db import fetch_all_where, fetch_in, next_integer_id, table_columns, table_exists
from .schema import CHARACTER_TABLES, ITEM_INSTANCE_TABLE, SKIPPED_TABLES, TableRule
from .sql import insert_sql, quote_identifier


class PorterError(RuntimeError):
    pass


LIVE_IMPORT_GUID_GAP = 1_000_000


@dataclass(frozen=True)
class ImportPlan:
    source_guid: int
    target_guid: int
    target_account: int
    target_name: str
    item_count: int
    table_counts: dict[str, int]
    live_import: bool = False
    guid_gap: int = 0


@dataclass(frozen=True)
class CheckoutResult:
    guid: int
    original_account: int
    original_name: str
    holding_account: int
    parked_name: str


@dataclass(frozen=True)
class PurgeResult:
    guid: int
    name: str
    item_count: int
    deleted_counts: dict[str, int]


def find_character(conn, *, guid: int | None = None, name: str | None = None, account: int | None = None) -> dict[str, Any]:
    if guid is None and name is None:
        raise PorterError("Provide either a character GUID or name")

    where: list[str] = []
    params: list[Any] = []
    if guid is not None:
        where.append("`guid` = %s")
        params.append(guid)
    if name is not None:
        where.append("`name` = %s")
        params.append(name)
    if account is not None:
        where.append("`account` = %s")
        params.append(account)

    sql = f"SELECT * FROM `characters` WHERE {' AND '.join(where)}"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        raise PorterError("No matching character found")
    if len(rows) > 1:
        raise PorterError("Multiple matching characters found; add --account or --guid")
    return dict(rows[0])


def export_character(conn, *, guid: int | None = None, name: str | None = None, account: int | None = None) -> dict[str, Any]:
    character = find_character(conn, guid=guid, name=name, account=account)
    source_guid = character["guid"]
    tables: dict[str, list[dict[str, Any]]] = {}
    skipped = dict(SKIPPED_TABLES)

    for rule in CHARACTER_TABLES:
        if not table_exists(conn, rule.table):
            skipped[rule.table] = "table not present in this schema"
            continue
        columns = table_columns(conn, rule.table)
        missing = [column for column in rule.character_columns if column not in columns]
        if missing:
            skipped[rule.table] = f"missing expected column(s): {', '.join(missing)}"
            continue
        rows = fetch_all_where(conn, rule.table, rule.character_columns[0], source_guid)
        tables[rule.table] = rows

    inventory_rows = tables.get("character_inventory", [])
    item_guids = sorted(
        {
            int(row[column])
            for row in inventory_rows
            for column in ("item", "bag")
            if column in row and row[column] not in (None, 0, "0")
        }
    )

    if table_exists(conn, ITEM_INSTANCE_TABLE):
        tables[ITEM_INSTANCE_TABLE] = fetch_in(conn, ITEM_INSTANCE_TABLE, "guid", item_guids)
    else:
        skipped[ITEM_INSTANCE_TABLE] = "table not present in this schema"

    return new_bundle(character, tables, skipped)


def checkout_character(conn, *, guid: int, holding_account: int) -> CheckoutResult:
    character = find_character(conn, guid=guid)
    original_name = str(character["name"])
    original_account = int(character["account"])
    parked_name = available_parked_name(conn, guid)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE `characters` SET `account` = %s, `name` = %s, `online` = 0 WHERE `guid` = %s",
            (holding_account, parked_name, guid),
        )
    conn.commit()

    return CheckoutResult(
        guid=guid,
        original_account=original_account,
        original_name=original_name,
        holding_account=holding_account,
        parked_name=parked_name,
    )


def available_parked_name(conn, guid: int) -> str:
    stem = f"Xfer{to_base36(guid)}"[:12]
    candidate = stem
    suffix = 1
    while character_name_exists(conn, candidate):
        suffix_text = to_base36(suffix)
        candidate = f"{stem[:12 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return candidate


def to_base36(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    digits = []
    current = value
    while current:
        current, remainder = divmod(current, 36)
        digits.append(alphabet[remainder])
    return "".join(reversed(digits))


def create_import_plan(
    conn,
    bundle: dict[str, Any],
    *,
    target_account: int,
    target_name: str | None = None,
    live_import: bool = False,
    guid_gap: int = 0,
) -> ImportPlan:
    source = bundle["character"]
    source_guid = int(source["guid"])
    name = target_name or source["name"]
    validate_character_name(name)
    ensure_character_name_available(conn, name)
    char_minimum = max_existing_id(conn, "characters", "guid") + guid_gap + 1 if live_import else None
    target_guid = next_integer_id(conn, "characters", "guid", 1, minimum=char_minimum)[0]
    item_count = len(bundle["tables"].get(ITEM_INSTANCE_TABLE, []))
    table_counts = {table: len(rows) for table, rows in bundle["tables"].items()}
    return ImportPlan(
        source_guid=source_guid,
        target_guid=target_guid,
        target_account=target_account,
        target_name=name,
        item_count=item_count,
        table_counts=table_counts,
        live_import=live_import,
        guid_gap=guid_gap,
    )


def import_character(
    conn,
    bundle: dict[str, Any],
    *,
    target_account: int,
    target_name: str | None = None,
    dry_run: bool = False,
    live_import: bool = False,
    guid_gap: int = 0,
) -> ImportPlan:
    plan = create_import_plan(
        conn,
        bundle,
        target_account=target_account,
        target_name=target_name,
        live_import=live_import,
        guid_gap=guid_gap,
    )
    item_rows = bundle["tables"].get(ITEM_INSTANCE_TABLE, [])
    item_minimum = max_existing_id(conn, ITEM_INSTANCE_TABLE, "guid") + guid_gap + 1 if live_import else None
    new_item_ids = (
        next_integer_id(conn, ITEM_INSTANCE_TABLE, "guid", len(item_rows), minimum=item_minimum) if item_rows else []
    )
    item_map = {int(row["guid"]): new_id for row, new_id in zip(item_rows, new_item_ids)}

    try:
        insert_character_row(conn, bundle["character"], plan)
        for row in item_rows:
            insert_item_row(conn, row, plan.source_guid, plan.target_guid, item_map)
        for table, rows in bundle["tables"].items():
            if table == ITEM_INSTANCE_TABLE:
                continue
            rule = rule_for_table(table)
            if rule is None:
                continue
            for row in rows:
                insert_remapped_table_row(conn, table, row, rule, plan.source_guid, plan.target_guid, item_map)
        validate_imported_inventory(conn, plan.target_guid)

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise

    return plan


def max_existing_id(conn, table: str, column: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX({quote_identifier(column)}), 0) AS max_id FROM {quote_identifier(table)}")
        return int(cur.fetchone()["max_id"])


def validate_imported_inventory(conn, target_guid: int) -> None:
    if not table_exists(conn, "character_inventory") or not table_exists(conn, ITEM_INSTANCE_TABLE):
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ci.item, ii.owner_guid
            FROM `character_inventory` ci
            LEFT JOIN `item_instance` ii ON ii.guid = ci.item
            WHERE ci.guid = %s
              AND (ii.guid IS NULL OR ii.owner_guid <> %s)
            """,
            (target_guid, target_guid),
        )
        bad_rows = cur.fetchall()
    if bad_rows:
        examples = ", ".join(f"item={row['item']} owner={row.get('owner_guid')}" for row in bad_rows[:5])
        raise PorterError(f"Imported inventory validation failed: {examples}")


def ensure_character_name_available(conn, name: str) -> None:
    if character_name_exists(conn, name):
        raise PorterError(f"Destination already has a character named {name!r}")


def validate_character_name(name: str) -> None:
    if not 2 <= len(name) <= 12:
        raise PorterError("Character names must be 2-12 characters long")
    if not name.isalpha():
        raise PorterError("Character names must contain letters only")


def character_name_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT guid FROM `characters` WHERE `name` = %s", (name,))
        return cur.fetchone() is not None


def purge_character(conn, *, guid: int, expected_name: str | None = None, dry_run: bool = True) -> PurgeResult:
    character = find_character(conn, guid=guid)
    name = str(character["name"])
    if expected_name is not None and name != expected_name:
        raise PorterError(f"GUID {guid} is named {name!r}, not expected name {expected_name!r}")
    unmanaged = unmanaged_reference_counts(conn, guid)
    if unmanaged:
        detail = ", ".join(f"{table}.{column}={count}" for (table, column), count in sorted(unmanaged.items()))
        raise PorterError(
            "Refusing to purge because unmanaged references still exist. "
            f"Handle these manually first: {detail}"
        )

    item_ids = inventory_item_ids(conn, guid)
    deleted_counts: dict[str, int] = {}

    try:
        for rule in CHARACTER_TABLES:
            if not table_exists(conn, rule.table):
                continue
            deleted_counts[rule.table] = delete_where_guid(conn, rule.table, rule.character_columns[0], guid)
        if item_ids and table_exists(conn, ITEM_INSTANCE_TABLE):
            deleted_counts[ITEM_INSTANCE_TABLE] = delete_items(conn, item_ids)
        deleted_counts["characters"] = delete_where_guid(conn, "characters", "guid", guid)

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise

    return PurgeResult(guid=guid, name=name, item_count=len(item_ids), deleted_counts=deleted_counts)


def unmanaged_reference_counts(conn, guid: int) -> dict[tuple[str, str], int]:
    references = (
        ("arena_team_member", "guid"),
        ("auctionhouse", "itemowner"),
        ("character_instance", "guid"),
        ("character_pet", "owner"),
        ("character_social", "guid"),
        ("character_social", "friend"),
        ("corpse", "guid"),
        ("guild_member", "guid"),
        ("mail", "receiver"),
        ("mail", "sender"),
        ("petition", "ownerguid"),
        ("petition_sign", "playerguid"),
    )
    counts: dict[tuple[str, str], int] = {}
    for table, column in references:
        if not table_exists(conn, table):
            continue
        columns = table_columns(conn, table)
        if column not in columns:
            continue
        count = count_where_guid(conn, table, column, guid)
        if count:
            counts[(table, column)] = count
    return counts


def count_where_guid(conn, table: str, column: str, guid: int) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS count FROM {quote_identifier(table)} WHERE {quote_identifier(column)} = %s", (guid,))
        return int(cur.fetchone()["count"])


def inventory_item_ids(conn, guid: int) -> list[int]:
    if not table_exists(conn, "character_inventory"):
        return []
    rows = fetch_all_where(conn, "character_inventory", "guid", guid)
    ids = {
        int(row[column])
        for row in rows
        for column in ("item", "bag")
        if column in row and row[column] not in (None, 0, "0")
    }
    return sorted(ids)


def delete_where_guid(conn, table: str, column: str, guid: int) -> int:
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {quote_identifier(table)} WHERE {quote_identifier(column)} = %s", (guid,))
        return cur.rowcount


def delete_items(conn, item_ids: list[int]) -> int:
    placeholders = ", ".join(["%s"] * len(item_ids))
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {quote_identifier(ITEM_INSTANCE_TABLE)} WHERE `guid` IN ({placeholders})", item_ids)
        return cur.rowcount


def rule_for_table(table: str) -> TableRule | None:
    for rule in CHARACTER_TABLES:
        if rule.table == table:
            return rule
    return None


def insert_character_row(conn, source_row: dict[str, Any], plan: ImportPlan) -> None:
    row = dict(source_row)
    row["guid"] = plan.target_guid
    row["account"] = plan.target_account
    row["name"] = plan.target_name
    if "online" in row:
        row["online"] = 0
    if "logout_time" in row:
        row["logout_time"] = 0
    clear_deleted_character_fields(row)
    insert_row(conn, "characters", row)


def clear_deleted_character_fields(row: dict[str, Any]) -> None:
    if "deleteInfos_Account" in row:
        row["deleteInfos_Account"] = None
    if "deleteInfos_Name" in row:
        row["deleteInfos_Name"] = None
    if "deleteDate" in row:
        row["deleteDate"] = None


def insert_remapped_table_row(
    conn,
    table: str,
    source_row: dict[str, Any],
    rule: TableRule,
    source_guid: int,
    target_guid: int,
    item_map: dict[int, int],
) -> None:
    row = remap_row(source_row, source_guid, target_guid, rule.character_columns, item_map, rule.item_columns)
    insert_row(conn, table, row)


def insert_item_row(
    conn,
    source_row: dict[str, Any],
    source_guid: int,
    target_guid: int,
    item_map: dict[int, int],
) -> None:
    row = dict(source_row)
    row["guid"] = item_map[int(source_row["guid"])]
    for column in ("owner_guid", "creatorGuid", "giftCreatorGuid"):
        if column in row and int_or_none(row[column]) == source_guid:
            row[column] = target_guid
    insert_row(conn, ITEM_INSTANCE_TABLE, row)


def remap_row(
    source_row: dict[str, Any],
    source_guid: int,
    target_guid: int,
    character_columns: tuple[str, ...],
    item_map: dict[int, int],
    item_columns: tuple[str, ...],
) -> dict[str, Any]:
    row = dict(source_row)
    for column in character_columns:
        if column in row and int_or_none(row[column]) == source_guid:
            row[column] = target_guid
    for column in item_columns:
        if column in row:
            item_id = int_or_none(row[column])
            if item_id in item_map:
                row[column] = item_map[item_id]
    return row


def int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def insert_row(conn, table: str, row: dict[str, Any]) -> None:
    existing_columns = table_columns(conn, table)
    filtered = {column: value for column, value in row.items() if column in existing_columns}
    if not filtered:
        return
    sql, params = insert_sql(table, filtered)
    with conn.cursor() as cur:
        cur.execute(sql, params)


def describe_plan(plan: ImportPlan) -> str:
    counts = ", ".join(f"{table}={count}" for table, count in sorted(plan.table_counts.items()))
    return (
        f"source_guid={plan.source_guid}, target_guid={plan.target_guid}, "
        f"target_account={plan.target_account}, target_name={plan.target_name}, "
        f"items={plan.item_count}, tables=[{counts}]"
    )
