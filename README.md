# AzerothCore Character Porter

Move an offline AzerothCore WotLK character between private servers with a
portable JSON bundle.

This is **not live sync**. It is a manual checkout/import tool for small groups
who each host their own server but sometimes want to bring a character to a
friend's realm.

## What It Does

The tool exports one character from `acore_characters`, including common
character-owned rows, then imports that bundle into another server with new
local character and item GUIDs.

Included:

- `characters`
- inventory and `item_instance`
- action bars, spells, talents, glyphs
- quest status and rewarded quests
- reputation, skills, achievements
- homebind, account data, auras, equipment sets when present

Skipped by design in this first version:

- mail
- auctions
- guild membership
- arena teams
- instance binds
- corpses
- social/friend/ignore lists
- pets

## Important Safety Rules

- The character must be logged out before export.
- Always back up `acore_characters` before a real import or checkout.
- Always run import with `--dry-run` first.
- The safest real import is with the destination `ac-worldserver` stopped.
- If importing while the worldserver is running, use `--allow-live-import`.
- Do not play the same character on two servers at once.
- Keep the parked checkout copy until the imported copy is confirmed in game.
- Participating servers should use compatible AzerothCore schemas, modules, and
  world data.

## Install

From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

If `acchar` is not on your PATH, run commands as:

```powershell
python -m ac_char_porter --help
```

## Recommended Workflow

Example story: Pete wants to move `Potato` from his server to Greg's server.

### 1. Back Up The Source Server

Back up at least `acore_characters`. If you also create accounts during the
test, back up `acore_auth` too.

```bash
mysqldump -u root -p acore_characters > acore_characters-before-transfer.sql
mysqldump -u root -p acore_auth > acore_auth-before-transfer.sql
```

### 2. Create A Holding Account

Checkout parks the source character on a holding account so nobody accidentally
keeps playing the old copy.

Create a normal AzerothCore account, lock it, and note its account id. You can
also create it with your usual server tooling or GM commands.

The examples below use:

```text
holding account id: 99
```

### 3. Export And Checkout The Character

```powershell
acchar export `
  --host pete-server `
  --user root `
  --password "password" `
  --database acore_characters `
  --character "Potato" `
  --out .\bundles\Potato-to-Greg.acchar.json `
  --checkout `
  --holding-account 99
```

After this:

- `Potato-to-Greg.acchar.json` contains the portable character bundle.
- `Potato` is no longer on Pete's normal account.
- The old local copy is parked on the holding account with a generated name such
  as `Xfer1f`.

### 4. Inspect The Bundle

```powershell
acchar inspect .\bundles\Potato-to-Greg.acchar.json
```

Look at the row counts and skipped tables. Skipped mail, auctions, guilds, and
pet rows are expected in this version.

### 5. Dry-Run Import On The Destination

```powershell
acchar import `
  --host greg-server `
  --user root `
  --password "password" `
  --database acore_characters `
  --bundle .\bundles\Potato-to-Greg.acchar.json `
  --account 7 `
  --name "Potato" `
  --dry-run
```

Dry-run performs the inserts inside a rollback-only transaction. It should end
with:

```text
Dry-run insert completed and rolled back.
```

### 6. Real Import: Safest Mode

Stop the destination worldserver, import, then start it again.

```bash
docker compose stop ac-worldserver
```

```powershell
acchar import `
  --host greg-server `
  --user root `
  --password "password" `
  --database acore_characters `
  --bundle .\bundles\Potato-to-Greg.acchar.json `
  --account 7 `
  --name "Potato" `
  --worldserver-stopped
```

```bash
docker compose start ac-worldserver
```

This is safest because AzerothCore keeps GUID allocation state in memory while
the worldserver is running.

### 7. Real Import: Guarded Live Mode

If you cannot stop the destination worldserver, use guarded live import:

```powershell
acchar import `
  --host greg-server `
  --user root `
  --password "password" `
  --database acore_characters `
  --bundle .\bundles\Potato-to-Greg.acchar.json `
  --account 7 `
  --name "Potato" `
  --allow-live-import
```

Live mode allocates imported character and item GUIDs far above the current
database maximum, then validates that imported inventory rows point to items
owned by the imported character.

This is much safer than a plain live DB import, but importing with the
worldserver stopped is still the strongest option. Restart the worldserver at
the next maintenance window so its in-memory GUID counters resync from the
database.

### 8. Verify In Game

Log into the destination account and check:

- character appears on the correct account
- level, race, class, and location look sane
- equipped items, bags, and inventory look correct
- quest progress looks correct
- action bars look reasonable
- no unexpected mail/guild/auction state is expected

### 9. Clean Up The Parked Copy

Only purge the parked source copy after the imported character works in game.

Dry-run first:

```powershell
acchar purge `
  --host pete-server `
  --user root `
  --password "password" `
  --database acore_characters `
  --guid 42 `
  --expected-name "Xfer1f"
```

Commit:

```powershell
acchar purge `
  --host pete-server `
  --user root `
  --password "password" `
  --database acore_characters `
  --guid 42 `
  --expected-name "Xfer1f" `
  --yes
```

`purge` refuses to run if it sees known unmanaged references such as mail,
guild, auction, arena, pet, corpse, social, or instance-bind rows. Clear those
manually or leave the parked copy in place.

## Command Reference

### Export Only

```powershell
acchar export `
  --host localhost `
  --user root `
  --password "password" `
  --database acore_characters `
  --character "Mychar" `
  --out .\bundles\Mychar.acchar.json
```

Select by GUID instead:

```powershell
acchar export `
  --host localhost `
  --user root `
  --password "password" `
  --database acore_characters `
  --guid 42 `
  --out .\bundles\char42.acchar.json
```

### Inspect

```powershell
acchar inspect .\bundles\Mychar.acchar.json
```

### Import

```powershell
acchar import --help
```

Real imports require one of:

```text
--worldserver-stopped
--allow-live-import
```

Dry-runs do not require either flag.

### Purge

```powershell
acchar purge --help
```

## Current Limitations

- No merge logic. One character timeline should be active at a time.
- No live sync service.
- Mail, auctions, guilds, arena teams, pets, social lists, and instance binds
  are not portable yet.
- Custom modules can add character state this tool does not know about.
- The most robust future version would import through an AzerothCore module so
  the worldserver itself allocates GUIDs.
