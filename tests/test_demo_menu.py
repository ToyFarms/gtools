"""The demo's modifier menu must mirror the engine's clothing checks.

Every checkbox in the Player menu is grouped by *modifier* (the client branch it
drives), not by body slot; the slot is resolved from items.dat. This suite pins the
menu data to the controller predicates, so an item cannot be listed under the wrong
slot, wired to the wrong modifier, or left out of the menu when the engine grows one.
"""

from gtools.baked.items import ABOMINABLE_SNOWMAN_MASK, ABOMINABLE_SNOWMAN_SUIT, SNOWSHOES
from gtools.core.growtopia.physics.controller import (
    CLIMB_GEAR_ITEMS,
    FLOATIE_ITEMS,
    GLIDE_ITEMS,
    PARASOL_ITEMS,
    SKATING_ITEMS,
    SLIPPERY_ITEMS,
    WATER_VEHICLE_ITEMS,
    PlayerController,
)
from gtools.core.growtopia.physics.demo import _clothing_slot, _item_label, _modifier_groups
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.world import World

_SNOWMAN = {ABOMINABLE_SNOWMAN_MASK, ABOMINABLE_SNOWMAN_SUIT}


def make_controller(**slots: int) -> PlayerController:
    world = World()
    world.resize(4, 4)
    world.players[1] = Player(net_id=1, clothing=Clothing(**slots))

    return PlayerController(world, net_id=1)


def make_wearing(item: int) -> PlayerController:
    return make_controller(**{_clothing_slot(item): item})


def test_the_menu_covers_every_controller_group() -> None:
    listed = [item for _, items in _modifier_groups() for item in items]
    expected = PARASOL_ITEMS | GLIDE_ITEMS | FLOATIE_ITEMS | WATER_VEHICLE_ITEMS | CLIMB_GEAR_ITEMS | SLIPPERY_ITEMS | SKATING_ITEMS | {SNOWSHOES}

    assert set(listed) == expected
    assert len(listed) == len(set(listed)), "an item must not appear in two modifier groups"


def test_every_item_resolves_to_a_clothing_slot_and_a_readable_label() -> None:
    bare = Clothing()
    for _, items in _modifier_groups():
        for item in items:
            slot = _clothing_slot(item)
            assert hasattr(bare, slot), item
            assert getattr(bare, slot) == 0, item

            label = _item_label(item)
            assert slot in label and str(item) in label


def test_slow_fall_items_drive_the_parasol_and_glide_groups() -> None:
    for item in PARASOL_ITEMS:
        assert make_wearing(item)._slow_fall_flags() == (True, False), item
    for item in GLIDE_ITEMS:
        assert make_wearing(item)._slow_fall_flags() == (False, True), item


def test_floatie_and_water_vehicle_items() -> None:
    for item in FLOATIE_ITEMS:
        assert make_wearing(item)._is_floatie(), item
    for item in WATER_VEHICLE_ITEMS:
        assert make_wearing(item)._has_water_vehicle(), item


def test_climb_gear_and_skating_items() -> None:
    for item in CLIMB_GEAR_ITEMS:
        assert make_wearing(item)._climb_gear(), item
    for item in SKATING_ITEMS:
        assert make_wearing(item)._wearing_skates(), item


def test_slippery_items_and_the_snowman_pair() -> None:
    for item in SLIPPERY_ITEMS - _SNOWMAN:
        assert make_wearing(item)._slippery_clothing(), item

    # the Abominable Snowman pieces only grant the mod together
    for item in _SNOWMAN:
        assert not make_wearing(item)._slippery_clothing(), item

    both = make_controller(hat=ABOMINABLE_SNOWMAN_MASK, shirt=ABOMINABLE_SNOWMAN_SUIT)
    assert both._slippery_clothing()
