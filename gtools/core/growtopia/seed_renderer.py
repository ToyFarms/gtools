from gtools import setting
from gtools.core.color import color_tint, color_mix, composite
from gtools.core.growtopia.items_dat import ItemInfoColor, ItemInfoSeedBase, ItemInfoSeedOverlay
from gtools.core.growtopia.rttex import RTTex
import numpy as np


class SeedRenderer:
    _TEXTURE = RTTex.from_file(setting.asset_path / "game/seed.rttex")

    def get(self, base_type: ItemInfoSeedBase, base_color: ItemInfoColor, overlay_type: ItemInfoSeedOverlay, overlay_color: ItemInfoColor) -> np.ndarray:
        base = SeedRenderer._TEXTURE.crop(int(base_type) * 16, 0, 16, 16)
        overlay = SeedRenderer._TEXTURE.crop(int(overlay_type) * 16, 16, 16, 16)

        base_col = np.array([base_color.r, base_color.g, base_color.b, base_color.a], dtype=np.uint8)
        overlay_col = np.array([overlay_color.r, overlay_color.g, overlay_color.b, overlay_color.a], dtype=np.uint8)

        base_tinted = color_tint(base, base_col)
        overlay_tinted = color_tint(overlay, color_mix(base_col, overlay_col, 0.5))

        return composite(overlay_tinted, base_tinted)
