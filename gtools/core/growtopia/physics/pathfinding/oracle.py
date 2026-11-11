"""Authoritative micro-simulation with a real ``PlayerController``.

The oracle never *defines* behaviour -- it runs the controller itself on a
``ProbeWorld`` backed by the same ``WorldSnapshot`` the fast kernel reads.  It is
used to

* measure the capability envelope (``profile.measure``),
* synthesise / confirm a segment's exact input program and end state, and
* validate a finished plan before handing it to the follower.

Because it instantiates a fresh ``PlayerController`` per run, the steam-launcher
``IS_ON`` clear (a real tile mutation in the client) cannot leak between
simulated branches.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from gtools.core.growtopia.physics.controller import TILE, PlayerController, _EPS
from gtools.core.growtopia.physics.pathfinding.snapshot import ProbeWorld, WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import (
    InputFrame,
    MotionState,
    Outcome,
    _clone_permissions,
)
from gtools.core.growtopia.player import CharacterState, Clothing, Player


def motion_from_controller(controller: Any) -> MotionState:
    """Copy every motion field of a live controller into a ``MotionState``."""
    return MotionState(
        x=float(controller.x),
        y=float(controller.y),
        vx=float(controller.vx),
        vy=float(controller.vy),
        frac_x=float(controller.frac_x),
        frac_y=float(controller.frac_y),
        time_ms=float(controller.time_ms),
        left=bool(controller.left),
        right=bool(controller.right),
        jump=bool(controller.jump),
        jump_latch=bool(controller.jump_latch),
        facing_right=bool(controller.facing_right),
        grounded=bool(controller.grounded),
        sliding=bool(controller.sliding),
        in_water=bool(controller.in_water),
        water_float=bool(controller.water_float),
        water_enter_ms=float(controller.water_enter_ms),
        mud=bool(controller.mud),
        left_ground=bool(controller.left_ground),
        damage_slip=bool(controller.damage_slip),
        climbing=bool(controller.climbing),
        double_jumped=bool(controller.double_jumped),
        killed=bool(controller.killed),
        permissions=_clone_permissions(controller.permissions),
    )


def _apply_motion(controller: Any, state: MotionState) -> None:
    """Seed a freshly built controller with a ``MotionState``."""
    controller.x = state.x
    controller.y = state.y
    controller.vx = state.vx
    controller.vy = state.vy
    controller.frac_x = state.frac_x
    controller.frac_y = state.frac_y
    controller.time_ms = state.time_ms
    controller.left = state.left
    controller.right = state.right
    controller.jump = state.jump
    controller.jump_latch = state.jump_latch
    controller.facing_right = state.facing_right
    controller.grounded = state.grounded
    controller.sliding = state.sliding
    controller.in_water = state.in_water
    controller.water_float = state.water_float
    controller.water_enter_ms = state.water_enter_ms
    controller.mud = state.mud
    controller.left_ground = state.left_ground
    controller.damage_slip = state.damage_slip
    controller.climbing = state.climbing
    controller.double_jumped = state.double_jumped
    controller.killed = state.killed
    controller.permissions = _clone_permissions(state.permissions)


class ControllerOracle:
    """Runs the real controller on a snapshot-backed probe world."""

    def __init__(
        self,
        snapshot: WorldSnapshot,
        *,
        character_state: CharacterState,
        clothing: Clothing | None = None,
        hand_item: int = 18,
        permissions: Any = None,
        net_id: int = 1,
        hitbox: tuple[float, float] = (20.0, 30.0),
        fixed_dt: float = 1.0 / 60.0,
    ) -> None:
        self.snapshot = snapshot
        self.character_state = character_state
        self.clothing = clothing
        self.hand_item = hand_item
        self.permissions = permissions
        self.net_id = net_id
        self.hitbox = hitbox
        self.fixed_dt = fixed_dt

    @classmethod
    def from_controller(cls, controller: Any, snapshot: WorldSnapshot) -> "ControllerOracle":
        state = controller.state
        return cls(
            snapshot,
            character_state=CharacterState(
                build_range=state.build_range,
                punch_range=state.punch_range,
                flags=state.flags,
                max_velocity=state.max_velocity,
                vertical_accel=state.vertical_accel,
                horizontal_accel=state.horizontal_accel,
                velocity_in_water=state.velocity_in_water,
                jump_strength=state.jump_strength,
            ),
            clothing=controller._clothing(),
            hand_item=controller.hand_item,
            permissions=_clone_permissions(controller.permissions),
            net_id=controller.net_id,
            hitbox=(controller.width, controller.height),
            fixed_dt=controller.fixed_dt,
        )

    # -- one run ---------------------------------------------------------------

    def build_controller(self, state: MotionState) -> tuple[PlayerController, ProbeWorld]:
        players = {self.net_id: Player(net_id=self.net_id, clothing=self.clothing)} if self.clothing is not None else {}
        world = ProbeWorld(self.snapshot, players=players, local_net_id=self.net_id)
        controller = PlayerController(
            world,
            net_id=self.net_id,
            x=state.x,
            y=state.y,
            state=CharacterState(
                build_range=self.character_state.build_range,
                punch_range=self.character_state.punch_range,
                flags=self.character_state.flags,
                max_velocity=self.character_state.max_velocity,
                vertical_accel=self.character_state.vertical_accel,
                horizontal_accel=self.character_state.horizontal_accel,
                velocity_in_water=self.character_state.velocity_in_water,
                jump_strength=self.character_state.jump_strength,
            ),
            hitbox=self.hitbox,
            fixed_dt=self.fixed_dt,
            send=None,
            auto_respawn=False,
            optimistic=False,
            hand_item=self.hand_item,
        )
        _apply_motion(controller, state)
        if state.permissions is None and self.permissions is not None:
            controller.permissions = _clone_permissions(self.permissions)

        return controller, world

    def run(
        self,
        state: MotionState,
        frames: tuple[InputFrame, ...] | list[InputFrame],
        *,
        max_ticks: int | None = None,
        stop_when: Callable[[MotionState, int], bool] | None = None,
        record_trace: bool = False,
    ) -> Outcome:
        controller, _ = self.build_controller(state)

        ticks = 0
        trace: list[tuple[float, float, bool]] = []
        min_tx, min_ty, max_tx, max_ty = _bbox(controller)
        damage_hits = 0
        bounced = launched = climbed = entered_water = used_wind = used_well = False
        reason = "timeout"
        killed_at_start = controller.killed
        was_climbing = controller.climbing
        was_water = controller.in_water
        last_bounce = (controller.bounce_tx, controller.bounce_ty)

        for direction, jump, count in frames:
            for _ in range(max(0, int(count))):
                if controller.killed:
                    reason = "killed"
                    break

                controller.on_fire = controller.on_acid = controller.damaged = False
                wind = controller._wind_direction()
                pull = controller._gravity_well_pull()
                controller.set_input(left=direction < 0, right=direction > 0, jump=jump)
                controller.step()
                ticks += 1

                if controller.on_fire or controller.on_acid or controller.damaged:
                    damage_hits += 1
                if not was_climbing and controller.climbing:
                    climbed = True
                if not was_water and controller.in_water:
                    entered_water = True
                if wind is not None:
                    used_wind = True
                if pull != (0.0, 0.0):
                    used_well = True
                bounce = (controller.bounce_tx, controller.bounce_ty)
                if bounce != last_bounce:
                    last_bounce = bounce
                    if controller.bounce_item and _item_bouncy(controller.bounce_item):
                        bounced = True
                    else:
                        launched = True

                was_climbing, was_water = controller.climbing, controller.in_water

                tx0, ty0, tx1, ty1 = _bbox(controller)
                min_tx, min_ty = min(min_tx, tx0), min(min_ty, ty0)
                max_tx, max_ty = max(max_tx, tx1), max(max_ty, ty1)
                if record_trace:
                    trace.append((controller.x, controller.y, controller.grounded))
                if stop_when is not None and stop_when(motion_from_controller(controller), ticks):
                    reason = "stopped"
                    break
                if max_ticks is not None and ticks >= max_ticks:
                    reason = "timeout"
                    break
            else:
                continue
            break

        end = motion_from_controller(controller)
        if not end.killed:
            if end.climbing:
                reason = "climb"
            elif end.in_water:
                reason = "water"
            elif end.grounded:
                reason = "landed"
        if end.killed and not killed_at_start:
            reason = "killed"

        return Outcome(
            state=end,
            ticks=ticks,
            reason=reason,
            damage_hits=damage_hits,
            bounced=bounced,
            launched=launched,
            climbed=climbed,
            entered_water=entered_water,
            used_wind=used_wind,
            used_well=used_well,
            bbox=(min_tx, min_ty, max_tx, max_ty),
            tick_trace=trace,
        )


def _bbox(controller: Any) -> tuple[int, int, int, int]:
    tx0 = math.floor(controller.x / TILE)
    ty0 = math.floor(controller.y / TILE)
    tx1 = math.floor((controller.x + controller.width - _EPS) / TILE)
    ty1 = math.floor((controller.y + controller.height - _EPS) / TILE)
    return (tx0, ty0, tx1, ty1)


def _item_bouncy(item_id: int) -> bool:
    from gtools.core.growtopia.items_dat import ItemInfoType, item_database

    return item_database.get(item_id).item_type in (ItemInfoType.BOUNCY, ItemInfoType.TRAMPOLINE, ItemInfoType.TRAMPOLINE_MOMENTUM)
