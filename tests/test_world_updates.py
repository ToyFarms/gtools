from gtools.core.growtopia.world import World, WorldEvent
from pyglm.glm import ivec2, vec2
import logging

logging.basicConfig(level=logging.ERROR)


def test_world_tile_events() -> None:
    world = World()
    world.name = b"TEST"
    world.width = 100
    world.height = 100
    world.tiles = {}
    world.fix()

    events = []

    def on_tile_update(x: int, y: int) -> None:
        events.append((x, y))

    world.subscribe(WorldEvent.TILE_UPDATE, single=on_tile_update)

    world.place_tile(2, ivec2(10, 20))
    if (10, 20) not in events:
        raise AssertionError(f"place_tile: event (10, 20) not in {events}")
    events.clear()

    world.destroy_tile(ivec2(10, 20))
    if (10, 20) not in events:
        raise AssertionError(f"destroy_tile: event (10, 20) not in {events}")
    events.clear()

    tile = world.get_tile(30, 40)
    assert tile
    world.place_fg(tile, 4)
    if (30, 40) not in events:
        raise AssertionError(f"place_fg: event (30, 40) not in {events}")
    events.clear()


def test_world_dropped_events() -> None:
    world = World()
    world.name = b"TEST"

    events: list[tuple[list, list, list]] = []

    def on_dropped_update(added, removed, modified) -> None:
        events.append((added, removed, modified))

    world.subscribe(WorldEvent.DROPPED_UPDATE, single=on_dropped_update)

    world.create_dropped(2, vec2(100, 200), 10, 0)
    if len(events) != 1 or len(events[0][0]) != 1:
        raise AssertionError(f"create_dropped: expected 1 added item, got {events}")

    uid = next(iter(world.dropped)).uid
    world.remove_dropped(uid)
    if len(events) != 2 or len(events[1][1]) != 1:
        raise AssertionError(f"remove_dropped: expected 1 removed item, got {events}")

    world.create_dropped(3, vec2(300, 400), 5, 0)
    uid = next(iter(world.dropped)).uid
    world.set_dropped(uid, 10)
    if len(events) != 4 or len(events[3][2]) != 1:
        raise AssertionError(f"set_dropped: expected 1 modified item, got {events}")
