from typing import Iterator
import numpy as np
from pyglm import glm
from gtools.core.growtopia.items_dat import ItemInfoCollisionType, item_database
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.layer import WORLD_TILE_OVERLAY
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.core.growtopia.world import FriendsEntranceTile, LockTile, Tile, TileFlags, VipEntranceTile, World


class TileOverlayRenderer(Renderer):
    def __init__(self) -> None:
        self.shader = ShaderProgram.get("shaders/solid")
        self.u_proj = self.shader.get_uniform("u_proj")
        self.u_model = self.shader.get_uniform("u_model")

        self.shader3d = ShaderProgram.from_file("shaders/solid3d.vert", "shaders/solid.frag")
        self.u_vp3d = self.shader3d.get_uniform("u_view_proj")
        self.u_model3d = self.shader3d.get_uniform("u_model")
        self.u_z3d = self.shader3d.get_uniform("u_z")
        self.u_spread3d = self.shader3d.get_uniform("u_layer_spread")

    def draw(self, camera: Camera2D, mesh: Mesh) -> None:
        self.shader.use()

        model = glm.mat4x4(1.0)
        model = glm.scale(model, glm.vec3(32.0, 32.0, 1.0))
        self.u_model.set_mat4x4(glm.value_ptr(model))
        self.u_proj.set_mat4x4(camera.proj_as_numpy())

        mesh.draw_instanced()

    def draw_3d(self, camera3d: Camera3D, layer_spread: float, mesh: Mesh) -> None:
        self.shader3d.use()

        model = glm.mat4x4(1.0)
        model = glm.scale(model, glm.vec3(32.0, 32.0, 1.0))
        self.u_model3d.set_mat4x4(glm.value_ptr(model))
        self.u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self.u_spread3d.set_float(layer_spread)

        mesh.draw_instanced()

    def build(self, world: World, tiles: Iterator[Tile], uid: int = 0) -> Mesh:
        instances: list[float] = []

        for tile in tiles:
            item = item_database.get(tile.fg_id)

            while True:
                match item.collision_type:
                    case ItemInfoCollisionType.FULL:
                        instances.extend([1.0, 0.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                    case ItemInfoCollisionType.JUMP_THROUGH:
                        instances.extend([0.5, 0.5, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                    case ItemInfoCollisionType.GATEWAY:
                        if tile.lock_index != 0:
                            lock = world.get_tile(tile.lock_index)
                            if lock and lock.extra and isinstance(lock.extra, LockTile):
                                if uid in lock.extra.access_uids:
                                    instances.extend([0.0, 1.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                                    break

                        instances.extend([1.0, 0.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                    case ItemInfoCollisionType.COLLIDE_IF_OFF:
                        if tile.flags & TileFlags.IS_ON != 0:
                            instances.extend([0.0, 1.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                        else:
                            instances.extend([1.0, 0.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                    case ItemInfoCollisionType.COLLIDE_IF_ON:
                        if tile.flags & TileFlags.IS_ON == 0:
                            instances.extend([0.0, 1.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                        else:
                            instances.extend([1.0, 0.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                    case ItemInfoCollisionType.VIP_DOOR:
                        if tile and tile.extra and isinstance(tile.extra, VipEntranceTile):
                            if uid == tile.extra.owner_uid or uid in tile.extra.access_uids:
                                instances.extend([0.0, 1.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                                break

                        instances.extend([1.0, 0.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                    case ItemInfoCollisionType.FRIEND_ENTRANCE:
                        instances.extend([1.0, 0.0, 0.0, 0.5, tile.pos.x, tile.pos.y, WORLD_TILE_OVERLAY])
                break

        return Mesh(Mesh.RECT_VERTS, [2], Mesh.RECT_INDICES, instance_data=np.array(instances, dtype=np.float32), instance_layout=[4, 3], instance_attrib_base=1)

    def delete(self) -> None:
        pass
