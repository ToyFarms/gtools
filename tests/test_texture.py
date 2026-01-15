from collections import defaultdict
from dataclasses import dataclass

from pyglm.glm import ivec2

from gtools.core.growtopia.items_dat import Item, ItemInfoTextureType, item_database
from gtools.core.growtopia.world import World


@dataclass(slots=True)
class TestSample:
    world: World
    tile: ivec2
    expected: int


sample_id: list[int] = []
tex_types: dict[ItemInfoTextureType, list[int]] = defaultdict(list)

for _, item in item_database.items().items():
    tex_types[item.texture_type].append(item.id)

print(tex_types[ItemInfoTextureType.SMART_EDGE_HORIZ_CAVE])
