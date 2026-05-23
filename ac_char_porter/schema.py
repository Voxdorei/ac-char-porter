from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableRule:
    table: str
    character_columns: tuple[str, ...] = ("guid",)
    item_columns: tuple[str, ...] = ()
    notes: str = ""


CHARACTER_TABLES: tuple[TableRule, ...] = (
    TableRule("character_account_data"),
    TableRule("character_action"),
    TableRule("character_achievement"),
    TableRule("character_achievement_progress"),
    TableRule("character_aura"),
    TableRule("character_currency"),
    TableRule("character_declinedname"),
    TableRule("character_equipmentsets"),
    TableRule("character_glyphs"),
    TableRule("character_homebind"),
    TableRule("character_inventory", item_columns=("item", "bag")),
    TableRule("character_queststatus"),
    TableRule("character_queststatus_daily"),
    TableRule("character_queststatus_monthly"),
    TableRule("character_queststatus_rewarded"),
    TableRule("character_queststatus_seasonal"),
    TableRule("character_queststatus_weekly"),
    TableRule("character_reputation"),
    TableRule("character_skills"),
    TableRule("character_spell"),
    TableRule("character_spell_cooldown"),
    TableRule("character_stats"),
    TableRule("character_talent"),
    TableRule("character_tutorial"),
)


SKIPPED_TABLES: dict[str, str] = {
    "auctionhouse": "auction ownership and bids need separate conflict handling",
    "character_instance": "instance binds should usually reset during a transfer",
    "corpse": "corpse location/state is transient",
    "guild_member": "guild membership is local server social state",
    "mail": "mail can contain other character and item references",
    "mail_items": "mail item references need separate ownership handling",
    "petition": "petition ownership/signature state is local social state",
    "character_pet": "pet GUID remapping is not implemented in this first pass",
    "pet_aura": "pet GUID remapping is not implemented in this first pass",
    "pet_spell": "pet GUID remapping is not implemented in this first pass",
    "pet_spell_cooldown": "pet GUID remapping is not implemented in this first pass",
}


ITEM_INSTANCE_TABLE = "item_instance"
