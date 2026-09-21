import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, auto

from pyglm.glm import ivec2

from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankPacket, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_CALL_FUNCTION,
    INTEREST_MODIFY_ITEM_INVENTORY,
    INTEREST_STATE_UPDATE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    InterestCallFunction,
    InterestTileChangeRequest,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch, register_thread
from gtools.proxy.extension.client.sdk_utils import helper
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag

s = helper()

ACT_DELAY = (0.20, 0.40)
OPEN_DELAY = (0.45, 0.65)
RETRY_DELAY = (0.40, 0.60)
BACKOFF_DELAY = (1.00, 2.00)
START_DELAY = (0.30, 0.80)

DIALOG_TIMEOUT = 4.0
CONFIRM_TIMEOUT = 5.0

MAX_RETRIES = 3


class Phase(IntEnum):
    STOPPED = auto()
    IDLE = auto()

    SUCKER_WRENCH = auto()
    SUCKER_RETRIEVE = auto()
    SUCKER_CONFIRM = auto()

    DROP_OPEN = auto()
    DROP_CONFIRM = auto()


SUCKER_PHASES = frozenset({Phase.SUCKER_WRENCH, Phase.SUCKER_RETRIEVE, Phase.SUCKER_CONFIRM})
DROP_PHASES = frozenset({Phase.DROP_OPEN, Phase.DROP_CONFIRM})
ACTIVE_PHASES = SUCKER_PHASES | DROP_PHASES


@dataclass(slots=True)
class Step:
    run_at: float
    action: Callable[[], None]


@dataclass(slots=True)
class DropJob:
    item_id: int
    stop_after: bool


class AutoEmpty(Extension):
    def __init__(self) -> None:
        super().__init__(name="AutoEmpty", interest=[Interest(interest=INTEREST_STATE_UPDATE)])

        self.enabled = False
        self.phase = Phase.STOPPED
        self.target: ivec2 | None = None
        self.item_id = 0

        self._step: Step | None = None
        self._deadline: float | None = None
        self._drop: DropJob | None = None
        self._retries = 0

    @dispatch(s.command_toggle("/e", id=s.auto))
    def _toggle(self, _event: PendingPacket) -> PendingPacket | None:
        if self.enabled:
            self._stop("toggled off", clear_target=False)
            return self.cancel()

        self.enabled = True
        self.console_log("auto empty is now True")

        if self.target is not None:
            self._begin_sucker(delay=START_DELAY)
        else:
            self._enter(Phase.IDLE)
            self.console_log("wrench the item sucker block you want to auto-empty to begin")

        return self.cancel()

    @dispatch(s.command_toggle("/estatus", id=s.auto))
    def _status(self, _event: PendingPacket) -> PendingPacket | None:
        name = item_database.get(self.item_id).name.decode() if self.item_id else "none"
        pending = "-" if self._step is None else f"{max(0.0, self._step.run_at - time.monotonic()):.2f}s"
        waiting = "-" if self._deadline is None else f"{max(0.0, self._deadline - time.monotonic()):.2f}s"
        self.console_log(
            f"enabled={self.enabled} state={self.phase.name} target={self.target} item={name} ({self.item_id}) step_in={pending} timeout_in={waiting} retries={self._retries}"
        )

        return self.cancel()

    def _enter(
        self,
        phase: Phase,
        *,
        do: Callable[[], None] | None = None,
        delay: tuple[float, float] | None = None,
        wait: float | None = None,
    ) -> None:
        now = time.monotonic()
        offset = random.uniform(*delay) if delay is not None else 0.0

        self.phase = phase
        self._step = Step(run_at=now + offset, action=do) if do is not None else None
        self._deadline = (now + offset + wait) if wait is not None else None

    def _stop(self, reason: str, *, clear_target: bool = True) -> None:
        self.enabled = False
        self._step = None
        self._deadline = None
        self._drop = None
        self._retries = 0
        self.phase = Phase.STOPPED
        if clear_target:
            self.target = None
            self.item_id = 0
        self._set_icon_state(busy=False)
        self.console_log(f"auto empty disabled: {reason}")

    def _tick(self) -> None:
        if not self.enabled or self.phase in (Phase.STOPPED, Phase.IDLE):
            return

        if self.state.status != Status.IN_WORLD:
            self._stop("left the world")
            return

        now = time.monotonic()

        step = self._step
        if step is not None:
            if now < step.run_at:
                return
            self._step = None
            step.action()
            return

        if self._deadline is not None and now >= self._deadline:
            self._deadline = None
            self._on_timeout()

    def _on_timeout(self) -> None:
        self._retries += 1
        if self._retries > MAX_RETRIES:
            self._stop(f"no server response after {MAX_RETRIES} retries in {self.phase.name}")
            return

        self.console_log(f"timeout in {self.phase.name}, retry {self._retries}/{MAX_RETRIES}")

        if self.phase is Phase.DROP_CONFIRM:
            self._finish_drop(confirmed=False)
            return

        self._begin_sucker(delay=BACKOFF_DELAY)

    @register_thread
    def _on_state_update(self) -> None:
        while True:
            self._tick()
            time.sleep(0.1)

    def _begin_sucker(self, *, delay: tuple[float, float] = RETRY_DELAY) -> None:
        self._drop = None
        self._enter(Phase.SUCKER_WRENCH, do=self._send_wrench, delay=delay, wait=DIALOG_TIMEOUT)

    @dispatch(
        Interest(
            interest=INTEREST_TILE_CHANGE_REQUEST,
            tile_change_request=InterestTileChangeRequest(where=[s.tank_value == 32]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _on_wrench(self, event: PendingPacket) -> PendingPacket | None:
        if not self.enabled:
            return None

        pkt = NetPacket.deserialize(event.buf)
        target = ivec2(pkt.tank.int_x, pkt.tank.int_y)

        if self._step is not None and self.phase is Phase.SUCKER_WRENCH:
            return None

        self.target = target
        self.console_log(f"tracking item sucker at {target.x}, {target.y}")

        self._drop = None
        self._enter(Phase.SUCKER_WRENCH, wait=DIALOG_TIMEOUT)

    def _handle_main_dialog(self, dialog: StrKV, dialog_name: bytes) -> None:
        self._retries = 0

        text = bytes(dialog.get(b"add_textbox", 1, default=b""))
        item_id = int(dialog.get(b"add_label_with_icon", 4, default=0))
        self.item_id = item_id

        held = self.state.inventory.get(item_id)
        if held is not None:
            carrying = held.amount
        else:
            carrying = 200 if b"already carrying" in text else 0

        if b"currently empty" in text:
            if carrying > 0:
                self.console_log(f"dropping {carrying} {self._item_name(item_id)} before stopping")
                self._begin_drop(DropJob(item_id=item_id, stop_after=True))
            else:
                self.console_log("machine is empty, nothing to retrieve")
                self._stop("machine is empty")

            return

        if carrying >= 200:
            self.console_log(f"inventory full of {self._item_name(item_id)}, dropping to make room")
            self._begin_drop(DropJob(item_id=item_id, stop_after=False))

            return

        self._enter(
            Phase.SUCKER_RETRIEVE,
            do=lambda: self._send_retrieve(dialog_name),
            delay=ACT_DELAY,
            wait=DIALOG_TIMEOUT,
        )

    def _handle_sub_dialog(self, dialog: StrKV) -> None:
        self._retries = 0

        amount = int(dialog.get(b"add_text_input", 3, default=200))

        held = self.state.inventory.get(self.item_id)
        carrying = held.amount if held else 0
        room = max(0, 200 - carrying)

        if amount > room:
            self.console_log(f"capping retrieve amount {amount} -> {room} (room left for item {self.item_id})")
            amount = room

        if amount <= 0:
            self.console_log(f"no room for {self._item_name(self.item_id)}, dropping instead")
            self._begin_drop(DropJob(item_id=self.item_id, stop_after=False))

            return

        self._enter(
            Phase.SUCKER_CONFIRM,
            do=lambda: self._send_removal(str(amount).encode()),
            delay=ACT_DELAY,
            wait=CONFIRM_TIMEOUT,
        )

    def _begin_drop(self, job: DropJob, *, delay: tuple[float, float] = OPEN_DELAY) -> None:
        self._drop = job
        self._enter(
            Phase.DROP_OPEN,
            do=lambda: self._send_drop_request(job.item_id),
            delay=delay,
            wait=DIALOG_TIMEOUT,
        )

    def _handle_drop_dialog(self, dialog: StrKV) -> None:
        self._retries = 0

        job = self._drop
        if job is None:
            return

        item_id_bytes = dialog.relative.get(b"itemID", 1, default=None)
        item_id = int(item_id_bytes) if item_id_bytes is not None else job.item_id

        count_cell = dialog.get(b"add_text_input", 3, default=None)
        if count_cell is not None:
            count = bytes(count_cell)
        else:
            item = self.state.inventory.get(item_id)
            count = str(item.amount).encode() if item else b"200"

        job.item_id = item_id
        self._enter(
            Phase.DROP_CONFIRM,
            do=lambda: self._send_drop(item_id, count),
            delay=ACT_DELAY,
            wait=CONFIRM_TIMEOUT,
        )

    def _finish_drop(self, *, confirmed: bool) -> None:
        job = self._drop
        self._drop = None

        if confirmed:
            self.console_log(f"dropped {self._item_name(self.item_id)}, retrying sucker")
        else:
            self.console_log("drop unconfirmed, re-reading sucker")

        if job is not None and job.stop_after:
            suffix = "" if confirmed else " (confirmation timed out)"
            self._stop(f"machine is empty, inventory cleared{suffix}")
            return

        self._begin_sucker(delay=RETRY_DELAY)

    @dispatch(
        Interest(
            interest=INTEREST_CALL_FUNCTION,
            call_function=InterestCallFunction(variant=[s.variant[0] == b"OnDialogRequest"]),
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_BLOCK,
            id=s.auto,
        ),
    )
    def _on_dialog(self, event: PendingPacket) -> PendingPacket | None:
        if not self.enabled or self.target is None:
            return self.pass_to_next()

        pkt = NetPacket.deserialize(event.buf)
        variant = Variant.deserialize(pkt.tank.extended_data)
        dialog = StrKV.deserialize(bytes(variant.as_string[1]))

        end_dialog_name = dialog.get(b"end_dialog", 1, default=None)
        if end_dialog_name is None:
            return self.pass_to_next()

        dialog_name = bytes(end_dialog_name)

        if dialog_name in (b"itemsucker_block", b"itemsucker_seed"):
            if self.phase in DROP_PHASES:
                self.console_log("sucker dialog during a drop, resyncing to it")
            elif self.phase not in SUCKER_PHASES:
                return self.pass_to_next()

            self._set_icon_state(busy=True)
            self._handle_main_dialog(dialog, dialog_name)

            return self.cancel()

        if dialog_name == b"itemremovedfromsucker":
            if self.phase is not Phase.SUCKER_RETRIEVE:
                return self.pass_to_next()
            self._set_icon_state(busy=True)
            self._handle_sub_dialog(dialog)

            return self.cancel()

        if dialog_name == b"drop_item":
            if self.phase is not Phase.DROP_OPEN:
                return self.pass_to_next()
            self._set_icon_state(busy=True)
            self._handle_drop_dialog(dialog)

            return self.cancel()

        return self.pass_to_next()

    @dispatch(
        Interest(
            interest=INTEREST_MODIFY_ITEM_INVENTORY,
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _on_inventory_modified(self, event: PendingPacket) -> PendingPacket | None:
        if not self.enabled or self.phase not in (Phase.SUCKER_CONFIRM, Phase.DROP_CONFIRM):
            return None

        if self._step is not None:
            return None

        if self.phase is Phase.SUCKER_CONFIRM:
            expected = self.item_id
        else:
            expected = self._drop.item_id if self._drop is not None else self.item_id

        pkt = NetPacket.deserialize(event.buf)
        if pkt.tank.value != expected:
            return None

        self._retries = 0

        if self.phase is Phase.SUCKER_CONFIRM:
            self.console_log(f"retrieved {self._item_name(self.item_id)}")
            self._begin_sucker(delay=RETRY_DELAY)
        else:
            self._finish_drop(confirmed=True)

        return None

    def _send_wrench(self) -> None:
        if self.target is None:
            self._stop("lost the target tile")
            return

        self._set_icon_state(busy=False)
        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.TILE_CHANGE_REQUEST,
                        value=32,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=self.target.x,
                        int_y=self.target.y,
                        flags=self.facing_left(tile=self.target),
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.RELIABLE,
            )
        )

    def _send_retrieve(self, dialog_name: bytes) -> None:
        if self.target is None:
            self._stop("lost the target tile")
            return

        self._set_icon_state(busy=False)
        self._push_generic_text(
            [
                ["action", "dialog_return"],
                ["dialog_name", dialog_name],
                ["tilex", self.target.x, ""],
                ["tiley", self.target.y, ""],
                ["buttonClicked", "retrieveitem"],
                None,
                ["chk_enablesucking", 1],
            ]
        )

    def _send_removal(self, amount: bytes) -> None:
        if self.target is None:
            self._stop("lost the target tile")
            return

        self._set_icon_state(busy=False)
        self._push_generic_text(
            [
                ["action", "dialog_return"],
                ["dialog_name", "itemremovedfromsucker"],
                ["tilex", self.target.x, ""],
                ["tiley", self.target.y, ""],
                ["itemtoremove", amount],
            ]
        )

    def _send_drop_request(self, item_id: int) -> None:
        self._set_icon_state(busy=False)
        self._push_generic_text(
            [
                ["action", "drop"],
                ["", "itemID", item_id],
            ]
        )

    def _send_drop(self, item_id: int, count: bytes) -> None:
        self._set_icon_state(busy=False)
        self._push_generic_text(
            [
                ["action", "dialog_return"],
                ["dialog_name", "drop_item"],
                ["itemID", item_id, ""],
                ["count", min(count, self.state.inventory.get(item_id).amount)],
            ]
        )

    def _set_icon_state(self, busy: bool) -> None:
        if self.state.status != Status.IN_WORLD:
            return

        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.SET_ICON_STATE,
                        net_id=self.state.me.net_id,
                        int_x=2 if busy else 0,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.RELIABLE,
            )
        )

    def _push_generic_text(self, rows: list[list[object] | None]) -> None:
        kv = StrKV()
        for row in rows:
            kv.append([] if row is None else row)  # pyright: ignore[reportArgumentType]
        kv.append_nl()

        self.push(
            PreparedPacket(
                packet=NetPacket(type=NetType.GENERIC_TEXT, data=kv),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.RELIABLE,
            )
        )

    @staticmethod
    def _item_name(item_id: int) -> str:
        return item_database.get(item_id).name.decode()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    AutoEmpty().standalone()
