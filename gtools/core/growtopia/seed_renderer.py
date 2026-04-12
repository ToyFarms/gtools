from gtools import setting
from gtools.core.color import color_tint, composite
from gtools.core.growtopia.items_dat import ItemInfoColor, ItemInfoSeedBase, ItemInfoSeedOverlay
from gtools.core.growtopia.rttex import RTTex
import numpy as np


class SeedRenderer:
    _TEXTURE = RTTex.from_file(setting.gt_path / "game/seed.rttex")

    def get(self, base_type: ItemInfoSeedBase, base_color: ItemInfoColor, overlay_type: ItemInfoSeedOverlay, overlay_color: ItemInfoColor) -> np.ndarray:
        base = SeedRenderer._TEXTURE.crop(int(base_type) * 16, 0, 16, 16)
        overlay = SeedRenderer._TEXTURE.crop(int(overlay_type) * 16, 16, 16, 16)

        base_col = np.array([base_color.r, base_color.g, base_color.b, base_color.a], dtype=np.uint8)
        overlay_col = np.array([
            (int(base_color.r) + int(overlay_color.r)) // 2,
            (int(base_color.g) + int(overlay_color.g)) // 2,
            (int(base_color.b) + int(overlay_color.b)) // 2,
            255,
        ], dtype=np.uint8)

        base_tinted = color_tint(base, base_col)
        overlay_tinted = color_tint(overlay, overlay_col)

        return composite(overlay_tinted, base_tinted)
