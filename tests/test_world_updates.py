from gtools.core.growtopia.world import World
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

    def on_tile_update(x, y):
        events.append((x, y))

    world.on_tile_update(on_tile_update)

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

    events_called = 0

    def on_dropped_update() -> None:
        nonlocal events_called
        events_called += 1

    world.on_dropped_update(on_dropped_update)

    world.create_dropped(2, vec2(100, 200), 10, 0)
    if events_called != 1:
        raise AssertionError(f"create_dropped: events_called is {events_called}, expected 1")

    uid = world.dropped.items[0].uid
    world.remove_dropped(uid)
    if events_called != 2:
        raise AssertionError(f"remove_dropped: events_called is {events_called}, expected 2")

    world.create_dropped(3, vec2(300, 400), 5, 0)
    uid = world.dropped.items[0].uid
    world.set_dropped(uid, 10)
    if events_called != 4:
        raise AssertionError(f"set_dropped: events_called is {events_called}, expected 4")

