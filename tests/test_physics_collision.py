"""Collision-type handling in ``gtools.core.growtopia.physics.controller``.

Mirrors the two client layers (docs/collision-port-backlog.md):

* movement: ``WorldView::collectStepTiles`` (0x1405617E0) +
  ``NetAvatar::canMoveXInto`` (0x140512A40) / ``canMoveYInto`` (0x140512A80)
* interaction: ``CanPassThroughTile`` (0x140554C10)

One backlog item per test group; tick them off in the backlog as they land.
"""

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.world import (
    BalloonOMaticTile,
    FriendsEntranceTile,
    LockTile,
    StormyCloudTile,
    Tile,
    TileFlags,
    VipEntranceTile,
    World,
)

ONE_WAY_BLOCK = 3796
JUMP_DOWN_RAIN = 4530  # Cosmic Rain
WOODEN_PLATFORM = 102
STORM_CLOUD = 7202
GATEWAY_FORCEFIELD = 1162
VIP_ENTRANCE = 3798
LOCKED_ADVENTURE_DOOR = 4698
ADVENTURE_BARRIER = 4706
ADVENTURE_IDOL_GATE = 4710
ADVENTURE_TOMB_GATE = 4744
ADVENTURE_ITEM_KEY = 1696
FACTION_GREEN = 4836
GUILD_ENTRANCE = 5818
FRIENDS_ENTRANCE = 11138
WORLD_LOCK = 242
SMALL_LOCK = 202

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


def make_world(extras=()):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    for item_id, x, y, flags in extras:
        tiles.append(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags))
    return World.from_tiles(tiles)


def set_tile(world, item_id, x, y, flags=TileFlags.NONE, extra=None):
    """Replace the tile at (x, y) -- the world-lock stand-in for the tests."""
    tile = world.get_tile(x, y)
    tile.fg_id = item_id
    tile.flags = flags
    tile.extra = extra
    return tile


def lock(owner=0, access=(), flags=0, guild=0):
    return LockTile(flags=flags, owner_uid=owner, access_count=len(access), access_uids=list(access), unk1=guild)


def walk_from(controller, world, tx, ticks=90, **input_):
    """Spawn at `tx` and walk for `ticks`; returns the controller."""
    c = spawn(controller, world, tx)
    walk(controller, ticks, **input_)
    return c


def spawn(controller, world, tx, *, y=STAND_Y):
    world.set_local_player(1)
    return controller.spawn(tx * 32 + 6.0, y)


def walk(controller, ticks, **input_):
    for _ in range(ticks):
        controller.set_input(**input_)
        controller.step()

    return controller


def test_one_way_blocks_only_against_its_facing():
    # not flipped = right-facing: walking right passes, walking left is blocked
    world = make_world([(ONE_WAY_BLOCK, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    walk(controller, 60, right=True)
    assert c.x > 11 * 32, f"rightward walk should pass: x={c.x}"

    world = make_world([(ONE_WAY_BLOCK, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 12, y=STAND_Y)
    walk(controller, 60, left=True)
    assert c.x == 11 * 32, f"leftward walk should stop on the tile edge: x={c.x}"

    # flipped = left-facing: mirrored
    world = make_world([(ONE_WAY_BLOCK, 10, FLOOR_Y - 1, TileFlags.FLIPPED_X)])
    controller = PlayerController(world)
    c = spawn(controller, world, 12, y=STAND_Y)
    walk(controller, 60, left=True)
    assert c.x < 9 * 32, f"leftward walk should pass on a flipped tile: x={c.x}"

    world = make_world([(ONE_WAY_BLOCK, 10, FLOOR_Y - 1, TileFlags.FLIPPED_X)])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    walk(controller, 60, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"rightward walk should stop: x={c.x}"


def test_one_way_never_blocks_vertically():
    # a one-way tile is not a platform: falling passes straight through it
    world = make_world([(ONE_WAY_BLOCK, 10, FLOOR_Y - 2, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=STAND_Y - 4 * 32)
    for _ in range(90):
        controller.step()
    assert c.y == STAND_Y  # fell through the one-way tile onto the floor
    assert c.grounded is True


def test_jump_through_lands_on_top_and_passes_from_below():
    world = make_world([(WOODEN_PLATFORM, 10, FLOOR_Y - 2, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10)
    controller.step()  # settle on the floor
    controller.set_input(jump=True)

    for _ in range(150):
        controller.step()

    # rose through the platform, then landed on its top edge
    assert c.y == 6 * 32 - HITBOX[1], f"should rest on the platform top: y={c.y}"
    assert c.grounded is True


def test_jump_down_blocks_rising_and_passes_falling():
    world = make_world([(JUMP_DOWN_RAIN, 10, FLOOR_Y - 3, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10)
    controller.step()
    controller.set_input(jump=True)
    lowest = c.y
    for _ in range(120):
        controller.step()
        lowest = min(lowest, c.y)
    assert lowest == 5 * 32 + 32, f"rising should stop at the JUMP_DOWN bottom edge (192): {lowest}"

    # falling through it from above reaches the floor
    world = make_world([(JUMP_DOWN_RAIN, 10, FLOOR_Y - 3, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=3 * 32)
    for _ in range(150):
        controller.step()
    assert c.y == STAND_Y and c.grounded is True


def test_gateway_public_bit_allows_everyone():
    world = make_world([(GATEWAY_FORCEFIELD, 10, FLOOR_Y - 1, TileFlags.IS_OPEN_TO_PUBLIC)])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    assert c.x > 11 * 32, f"public gateway should pass: x={c.x}"


def test_gateway_resolves_world_lock_access_list():
    # the gateway has no extra of its own: `canDoorPassedThrough_1` falls back to the world lock
    world = make_world([(GATEWAY_FORCEFIELD, 10, FLOOR_Y - 1, TileFlags.NONE)])
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=7, access=[42]))
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 42
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"world-lock access list should open the gateway: x={c.x}"

    world = make_world([(GATEWAY_FORCEFIELD, 10, FLOOR_Y - 1, TileFlags.NONE)])
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=7, access=[42]))
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 43
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"stranger should be blocked by the lock: x={c.x}"

    # the world-lock owner break-taps through even without the access list
    world = make_world([(GATEWAY_FORCEFIELD, 10, FLOOR_Y - 1, TileFlags.NONE)])
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=7))
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 7
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"owner should pass: x={c.x}"


def test_gateway_resolves_parent_lock():
    world = make_world([(GATEWAY_FORCEFIELD, 10, FLOOR_Y - 1, TileFlags.NONE)])
    parent = set_tile(world, SMALL_LOCK, 3, 2, extra=lock(owner=7, access=[42]))
    world.get_tile(10, FLOOR_Y - 1).parent_index = world.index_tile(parent.pos)
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 42
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"parent lock access list should open the gateway: x={c.x}"

    world = make_world([(GATEWAY_FORCEFIELD, 10, FLOOR_Y - 1, TileFlags.NONE)])
    parent = set_tile(world, SMALL_LOCK, 3, 2, extra=lock(owner=7, access=[42]))
    world.get_tile(10, FLOOR_Y - 1).parent_index = world.index_tile(parent.pos)
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 43
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"stranger should be blocked by the parent lock: x={c.x}"


def test_vip_door_needs_its_own_lock_extra():
    # extra-less VIP entrance blocks (unlike GATEWAY's world-lock fallback)
    world = make_world([(VIP_ENTRANCE, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 42
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"extra-less VIP door should block: x={c.x}"

    # access list passes
    world = make_world([(VIP_ENTRANCE, 10, FLOOR_Y - 1, TileFlags.NONE)])
    world.get_tile(10, FLOOR_Y - 1).extra = VipEntranceTile(unk1=0, owner_uid=7, access_uids=[42])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 42
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"access-list user should pass the VIP door: x={c.x}"

    # owner break-tap passes
    world = make_world([(VIP_ENTRANCE, 10, FLOOR_Y - 1, TileFlags.NONE)])
    world.get_tile(10, FLOOR_Y - 1).extra = VipEntranceTile(unk1=0, owner_uid=42, access_uids=[])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 42
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"owner should break-tap through: x={c.x}"

    # public flag passes
    world = make_world([(VIP_ENTRANCE, 10, FLOOR_Y - 1, TileFlags.IS_OPEN_TO_PUBLIC)])
    world.get_tile(10, FLOOR_Y - 1).extra = VipEntranceTile(unk1=0, owner_uid=7, access_uids=[])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 42
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"public VIP door should pass: x={c.x}"

    # stranger blocks
    world = make_world([(VIP_ENTRANCE, 10, FLOOR_Y - 1, TileFlags.NONE)])
    world.get_tile(10, FLOOR_Y - 1).extra = VipEntranceTile(unk1=0, owner_uid=7, access_uids=[42])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    c.permissions.user_id = 43
    controller.teleport(8 * 32 + 6.0, STAND_Y)
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"stranger should be blocked: x={c.x}"


def test_locked_adventure_door_needs_key_in_cache():
    world = make_world([(LOCKED_ADVENTURE_DOOR, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"door without the key should block: x={c.x}"

    world = make_world([(LOCKED_ADVENTURE_DOOR, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.tile_cache = [ADVENTURE_ITEM_KEY]
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"key in the tile cache should open the door: x={c.x}"


def test_adventure_key_is_cached_by_touching_it():
    world = make_world([(ADVENTURE_ITEM_KEY, 9, FLOOR_Y - 1, TileFlags.NONE), (LOCKED_ADVENTURE_DOOR, 11, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    assert ADVENTURE_ITEM_KEY in c.permissions.tile_cache, "touching the key should cache it (avatar+0x2E0)"
    assert c.x > 12 * 32, f"the cached key should open the door ahead: x={c.x}"


def test_adventure_gates_toggle_with_event_flags():
    # without the event flag the gate is open while IS_ON is set
    world = make_world([(ADVENTURE_BARRIER, 10, FLOOR_Y - 1, TileFlags.IS_ON)])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    assert c.x > 11 * 32, f"barrier with IS_ON and no flag should pass: x={c.x}"

    world = make_world([(ADVENTURE_BARRIER, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"barrier without IS_ON and no flag should block: x={c.x}"

    # with the event flag set the gate inverts (open while IS_ON is clear)
    world = make_world([(ADVENTURE_BARRIER, 10, FLOOR_Y - 1, TileFlags.IS_ON)])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.adventure_flags = {40}
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"flag 40 with IS_ON should block: x={c.x}"

    world = make_world([(ADVENTURE_BARRIER, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.adventure_flags = {40}
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"flag 40 without IS_ON should pass: x={c.x}"

    # idol gate (41) and tomb gate (42) follow the same rule
    for item, flag in ((ADVENTURE_IDOL_GATE, 41), (ADVENTURE_TOMB_GATE, 42)):
        world = make_world([(item, 10, FLOOR_Y - 1, TileFlags.NONE)])
        controller = PlayerController(world)
        c = spawn(controller, world, 8)
        c.permissions.adventure_flags = {flag}
        walk(controller, 90, right=True)
        assert c.x > 11 * 32, f"flag {flag} should pass {item}: x={c.x}"


def test_faction_team_gates():
    faction = lambda world: set_tile(world, FACTION_GREEN, 10, FLOOR_Y - 1, extra=BalloonOMaticTile(total_rarity=0, team_type=2))

    # no team, non-public, no lock anywhere -> pass (canDoorPassedThrough_1 is true)
    world = make_world([(FACTION_GREEN, 10, FLOOR_Y - 1, TileFlags.NONE)])
    faction(world)
    controller = PlayerController(world)
    c = walk_from(controller, world, 8, right=True)
    assert c.x > 11 * 32, f"unlocked faction gate should pass: x={c.x}"

    # no team, non-public, world lock without access -> blocked
    world = make_world([(FACTION_GREEN, 10, FLOOR_Y - 1, TileFlags.NONE)])
    faction(world)
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=7, access=[5]))
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"stranger should be blocked by the lock: x={c.x}"

    # team member + access list + matching team -> pass
    world = make_world([(FACTION_GREEN, 10, FLOOR_Y - 1, TileFlags.NONE)])
    faction(world)
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=7, access=[42]))
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    c.permissions.has_team = True
    c.permissions.team = 2
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"matching team with access should pass: x={c.x}"

    # team member with the wrong team -> blocked even when public
    world = make_world([(FACTION_GREEN, 10, FLOOR_Y - 1, TileFlags.IS_OPEN_TO_PUBLIC)])
    faction(world)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.has_team = True
    c.permissions.team = 1
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"wrong team should be blocked: x={c.x}"

    # matching team passes a public gate
    world = make_world([(FACTION_GREEN, 10, FLOOR_Y - 1, TileFlags.IS_OPEN_TO_PUBLIC)])
    faction(world)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.has_team = True
    c.permissions.team = 2
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"matching team should pass: x={c.x}"


def test_guild_entrance_gates():
    def guild_world(flags, guild=99, access=(), public=False):
        world = make_world([(GUILD_ENTRANCE, 10, FLOOR_Y - 1, TileFlags.IS_OPEN_TO_PUBLIC if public else TileFlags.NONE)])
        world.get_tile(10, FLOOR_Y - 1).extra = lock(owner=7, access=access, flags=flags, guild=guild)
        return world

    # door flags 0 -> rank 3 required; matching guild + rank 3 passes
    world = guild_world(0x00)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 50
    c.permissions.guild_id = 99
    c.permissions.guild_rank = 3
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"rank 3 should pass a rank-3 guild door: x={c.x}"

    # matching guild but insufficient rank -> blocked
    world = guild_world(0x00)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 50
    c.permissions.guild_id = 99
    c.permissions.guild_rank = 2
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"rank 2 should be blocked on a rank-3 door: x={c.x}"

    # door flags 0x80 -> rank 1 required
    world = guild_world(0x80)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 50
    c.permissions.guild_id = 99
    c.permissions.guild_rank = 1
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"rank 1 should pass a rank-1 guild door: x={c.x}"

    # door flags 0xC0 -> rank 0 required
    world = guild_world(0xC0)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 50
    c.permissions.guild_id = 99
    c.permissions.guild_rank = 0
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"rank 0 should pass a rank-0 guild door: x={c.x}"

    # access list passes with a foreign guild
    world = guild_world(0x00, guild=99, access=[50])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 50
    c.permissions.guild_id = 1
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"access list should pass a foreign guild door: x={c.x}"

    # public flag passes
    world = guild_world(0x00, public=True)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 50
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"public guild door should pass: x={c.x}"

    # no extra at all -> block (the client requires `extra`)
    world = make_world([(GUILD_ENTRANCE, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 50
    c.permissions.guild_id = 99
    c.permissions.guild_rank = 3
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"extra-less guild door should block: x={c.x}"


def test_friend_entrance_gates():
    def friend_world(owner_uid=7, access=(), timestamp=1, flags=TileFlags.NONE):
        world = make_world([(FRIENDS_ENTRANCE, 10, FLOOR_Y - 1, flags)])
        world.get_tile(10, FLOOR_Y - 1).extra = FriendsEntranceTile(owner_uid=owner_uid, access_uids=list(access), placed_timestamp=timestamp)
        return world

    # stranger without friend state or ownership -> blocked
    world = friend_world()
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"stranger should be blocked: x={c.x}"

    # the world owner passes
    world = friend_world()
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=42))
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"world owner should pass: x={c.x}"

    # friend state (avatar+0x2DB0) passes once a world owner exists
    world = friend_world()
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=7))
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    c.permissions.friend = True
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"friend state should pass: x={c.x}"

    # friend state without a world owner does not pass
    world = friend_world()
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    c.permissions.friend = True
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"friend state without world owner should block: x={c.x}"

    # the friends entrance access list passes
    world = friend_world(access=[42])
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    walk(controller, 90, right=True)
    assert c.x > 11 * 32, f"access list should pass: x={c.x}"

    # a non-default placedTimestamp (TileExtra+0x7C) blocks even friends
    world = friend_world(timestamp=0)
    set_tile(world, WORLD_LOCK, 3, 2, extra=lock(owner=7))
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    c.permissions.user_id = 42
    c.permissions.friend = True
    walk(controller, 90, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"placedTimestamp != 1 should block: x={c.x}"


def test_storm_cloud_blocks_only_while_solid():
    solid = Tile(fg_id=STORM_CLOUD, pos=ivec2(10, FLOOR_Y - 1), flags=TileFlags.NONE)
    solid.extra = StormyCloudTile(sting_duration=0, is_solid=1, non_solid_duration=0)
    world = make_world([(STORM_CLOUD, 10, FLOOR_Y - 1, TileFlags.NONE)])
    world.get_tile(10, FLOOR_Y - 1).extra = solid.extra
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    walk(controller, 60, right=True)
    assert c.x == 10 * 32 - HITBOX[0], f"solid cloud should block: x={c.x}"

    world = make_world([(STORM_CLOUD, 10, FLOOR_Y - 1, TileFlags.NONE)])
    world.get_tile(10, FLOOR_Y - 1).extra = StormyCloudTile(sting_duration=0, is_solid=0, non_solid_duration=0)
    controller = PlayerController(world)
    c = spawn(controller, world, 8)
    walk(controller, 60, right=True)
    assert c.x > 11 * 32, f"non-solid cloud should pass: x={c.x}"
