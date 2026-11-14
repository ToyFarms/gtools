# World wire format — client-verified

> Reverse-engineered from the client while fixing `.gtools/worlds` loading. The
> reference functions are `World::LoadFromMem` (0x14055E690), `parseWorldTiles`
> (0x1405660B0), `parseTile` (0x140555A50), `TileExtra::Parse` (0x1405588F0),
> `replaceTileForegroud` (0x140555EB0) and `determineTileExtraType`
> (0x140557B60). The Python model is `gtools/core/growtopia/world.py`;
> `tests/test_world_parse.py` pins the quirks below with synthetic data.
> Verified against the 605-world corpus in `/mnt/c/Users/andra/.gtools/worlds`.

## 1. Framing

A saved world file is one `NetPacket` (u32 `NetType.TANK_PACKET = 4`), one
`TankPacket` header (0x38 bytes) and the world payload in the extended data.
Real Growtopia appends a stray "anomaly byte" after the extended data; the
advertised `extended_len` excludes it. `TankPacket.deserialize` detects it per
packet (one byte beyond `extended_len` *is* the anomaly; exact-length private
server packets are kept intact) and drops it, without depending on the
`anomaly_byte_compensation` setting — 599 of the 605 saved files carry the byte.
`World.from_file` parses the tank payload verbatim; `World.deserialize` ignores
any remaining trailing padding, which the files use freely (e.g. `TRADE` has
24 KB of zero padding after the dropped items).

## 2. Payload layout

| field | type | notes |
|---|---|---|
| `version` | u16 | parse-time format version; the client's `LATEST_TILE_FORMAT_VERSION` is 20, saves go to 27 |
| `f` | u32 | |
| `name` | u16 length + bytes | |
| `width`, `height`, `nb_tiles` | u32 each | |
| `unk2` | 5 bytes | |
| `tiles` | `nb_tiles` × tile | see §3 |
| `unk4` | 12 bytes | |
| dropped | `nb_items` u32, `last_uid` u32, items | item = u16 id, f32 x, f32 y, u8 amount, u8 flags, u32 uid |
| weather | 12 bytes | **only if `version >= 3`** (LoadFromMem); = u16 `default_weather`, u16 `terraform`, u16 `active_weather`, u16 `unk8`, u32 `unk9` |

## 3. Tile

```
fg u16 | bg u16 | parent_index u16 | flags u16
if flags & LOCKED:      u16 lock link
if extra gate is open:  TileExtra (type byte + payload)
if fg in CBOR_IDs:      u32 length + CBOR map
```

- **The LOCKED u16 is `parent_index`.** `parseTile` reads it into
  `tile->parent_index`, overwriting the header value (`toggleLockedAndSetParentIndex`,
  0x140556790, does the same on `SEND_LOCK`). Saved worlds carry the same value in
  both slots (0 mismatches over 119 797 locked tiles), so the Python model keeps
  `lock_index` (renderer) and now mirrors it into `parent_index` (permissions).
- **A NONE extra (`type == 0`) is consumed and dropped** — `parseTile` destroys the
  extra and clears `HAS_EXTRA_DATA`. Type 0 therefore costs exactly one byte.
- **CBOR tiles are keyed by item id, not extra type.** `CBOR_IDs` (world.py) lists the
  items whose tiles carry a length-prefixed CBOR map; e.g. item 16094
  `WEATHER_MACHINE_CONCERT_LIGHTS` (newer than the baked items table) stores
  `{"jsonString": ...}` even though its extra is the normal guild weather machine.

### 3.1 The extra gate (old saves omit `HAS_EXTRA_DATA`)

`parseTile` calls `replaceTileForegroud(tile, fg, ..., world, 1)` **before** testing
`flags & HAS_EXTRA_DATA`. That function allocates a tile extra and sets the flag for
the structural item types — the list mirrored as `_EXTRA_ITEM_TYPES` in `world.py`
(doors, seeds, locks, signs, portals, guild items, ...), plus `flags2 & GUILD_ITEM`
and `DATA_BEDROCK(3760)` / `DATA_STARSHIP_HULL(6546)` via
`isBedrockOrStarshipHull`.

Old saves (v0/v3, also some v23) rely on this: a `Main Door` tile with `flags == 0`
is immediately followed by its door extra (`01 04 00 "EXIT" 00`), and v23 `World
Lock`/`Door Seed` tiles behave the same. A parser that only honours the wire flag
desyncs at the first such tile — that was the PARKOUR/123/TRADE loading bug.

Consequences for the Python model:

- `Tile.deserialize` infers the extra from the foreground item when the flag is
  clear, and sets the flag after a successful parse (the client leaves it set in
  memory). Re-serializing therefore emits `flags | 1` for those tiles, which is
  what the client would save.
- Background-item extras (`fg == 0`) are *not* inferred — `replaceTileForegroud`
  only looks at the foreground; the wire flag governs.

### 3.2 Guild data (the trailing payload has no type byte)

`TileExtra::Parse`'s `handleSpecialTile` tail appends a guild payload after the
parent extra for items whose `flags2` has `GUILD_ITEM` (guild lock/flag/weather
machines, ...). It is read **without its own type byte**; for `GUILD_LOCK` the
leading u8 is skipped, otherwise it is `u8 + 4 × u32`. `TileExtra.serialize_into`
must therefore call `int__serialize_into` on the nested guild object, not
`serialize_into` (which would re-emit the `0x41` type byte and shift the stream).

## 4. Extra type numbers verified while porting

| value | client name / case | Python |
|---|---|---|
| `0x09` | `CHEMICAL_SOURCE_TILE` (item `PROVIDER`) | `ProviderTile` (`PROVIDER`) |
| `0x10` | `GAME_PACK_TILE` (item `TEAM`, `tileType = 4`) | `TeamTile` (`TEAM_TILE`) |
| `0x1C` | `GIVING_TREE_TILE` = u8 + i32 + u8 | `GivingTreeTile` |
| `0x1D` | `FISH_TANK_PORT_TILE\|SEED_TILE` (item stump) — type byte only | `GivingTreeStumpTile` |
| `0x40` | `case 0x40u` — one string (item `LUCKY_TICKET`) | `LuckyTicketTile` |
| `0x21` | `COUNTRY_FLAG_TILE` — string only for the plain `COUNTRY_FLAG` item | `CountryFlagTile` |
| `0x2A` | `DATA_BEDROCK_TILE` | `DataBedrockTile` |
| `0x31` | `GUILD_WEATHER_MACHINE_TILE` (item `WEATHER_SPECIAL2`) | `GuildWeatherMachineTile` |

Item-type → extra-type mapping (used to synthesize extras in `place_fg`):
`determineTileExtraType` also maps `CAMERA` → `BULLETIN_TILE` (word value 2055 =
type 7 + `tileType 8`), `RED/GREEN/BLUE_FACTION` → `BALLOON_O_MATIC_TILE`
(team byte 1..3) and `LUCKY_TICKET` → 0x40; `_ITEMINFO_TO_TILEEXTRA` mirrors that.

## 5. Corpus status (after the fix)

- 605/605 worlds parse end-to-end (`garbage_start == -1`).
- 582 serialize back byte-identically; 16 differ only in CBOR float width (cbor2
  writes float64 `fb`, the client writes float32 `fa`); 7 differ only in the
  forced `HAS_EXTRA_DATA` bit described in §3.1. All re-parse into the same tiles.
