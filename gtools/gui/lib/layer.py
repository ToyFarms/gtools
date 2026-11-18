# LAYER ORDER: lowest to highest = back to front.
#
# The world scene layers are the GUI-side depth slots for the core command
# system's RenderLayer (gtools.core.growtopia.render_commands); the mapping
# lives in gtools.gui.lib.sprite_batch.LAYER_DEPTHS. Depth values are floats:
# bigger = closer to the camera. The *_START/*_END pairs are bands: the
# sprite batch spreads a layer's instances across the band in draw order.
WORLD_BACKGROUND = -90
WORLD_PRE_FOREGROUND = -89
OBJECT_PRE_FOREGROUND_START = -88
OBJECT_PRE_FOREGROUND_END = -87
WORLD_FOREGROUND = -80
OBJECT_POST_FOREGROUND_START = -79
OBJECT_POST_FOREGROUND_END = -76
WORLD_POST_FOREGROUND = -75
WORLD_HIGHLIGHT_OVERLAY = -74
PLAYER = -73
PLAYER_DIRECTION = -72.5
NPC = -72
CYBOT = -71.5
CYBOT_PROJECTILE = -71.4
BLAST = -71.45
OBJECT_DROPPED_START = -70
OBJECT_DROPPED_END = -1
WORLD_FIRE = 0
WORLD_WATER = 1
WORLD_TILE_OVERLAY = 2
GUI_MENU = 90
GUI_MENU_TEXT = 91
