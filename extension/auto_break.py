import array
from collections import deque
from dataclasses import dataclass
from enum import IntEnum, auto
from functools import lru_cache
import io
import math
import random
import sys
import time
import numpy as np

from pyglm.glm import ivec2
from gtools.baked.items import BEDROCK
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.core.growtopia.particles import ParticleID
from gtools.core.growtopia.player import CharacterFlags
from gtools.core.growtopia.world import ItemSuckerTile
from gtools.core.mixer import AudioMixer, Sound
from gtools.core.task_scheduler import schedule_task
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_CALL_FUNCTION,
    INTEREST_PING_REPLY,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    INTEREST_TILE_APPLY_DAMAGE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    InterestCallFunction,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch, register_thread
from gtools.proxy.extension.client.sdk_utils import helper
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag


@dataclass(slots=True)
class TileChangeRequest:
    item_id: int
    target: ivec2


class State(IntEnum):
    BREAKING = auto()
    BUILDING = auto()


s = helper()

if sys.platform == "win32":
    try:
        import wave, winsound
        _SAMPLE_RATE = 44100

        _NOISE_POOL = array.array("d", [random.uniform(-1, 1) for _ in range(_SAMPLE_RATE)])
        _noise_cursor = 0

        @lru_cache(maxsize=512)
        def _bake_waveform_win(freq: float, duration_ms: int, freq_end: float | None, waveform: str, drive: float) -> array.array:
            n_samples = int(_SAMPLE_RATE * duration_ms / 1000)
            if freq_end is not None and freq_end != freq:
                k = (freq_end - freq) / (duration_ms / 1000)

                def phase_at(i: int) -> float:
                    ti = i / _SAMPLE_RATE
                    return 2 * math.pi * (freq * ti + 0.5 * k * ti**2)

            else:

                def phase_at(i: int) -> float:
                    return 2 * math.pi * freq * (i / _SAMPLE_RATE)

            gain = math.tanh(1 + drive * 5) if drive > 0 else 1.0
            values = []
            for i in range(n_samples):
                p = phase_at(i)
                if waveform == "square":
                    v = 1.0 if math.sin(p) >= 0 else -1.0
                elif waveform == "saw":
                    x = (p / (2 * math.pi)) % 1.0
                    v = 2 * x - 1
                else:
                    v = math.sin(p)
                if drive > 0:
                    v = math.tanh(v * (1 + drive * 5)) / gain
                values.append(v)

            return array.array("d", values)

        def _to_pcm16(shape, volume: float) -> array.array:
            return array.array("h", [int(32767 * volume * v) for v in shape])

        def _play_pcm16(samples: array.array) -> None:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(_SAMPLE_RATE)
                w.writeframes(samples.tobytes())
            winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

        def beep(
            freq: int = 440,
            duration_ms: int = 80,
            volume: float = 0.3,
            freq_end: int | None = None,
            waveform: str = "sine",
            drive: float = 0.0,
        ) -> None:
            shape = _bake_waveform_win(
                float(freq),
                int(duration_ms),
                float(freq_end) if freq_end is not None else None,
                waveform,
                round(drive, 2),
            )

            _play_pcm16(_to_pcm16(shape, volume))

        def click(duration_ms: int = 20, volume: float = 0.4) -> None:
            global _noise_cursor
            n_samples = int(_SAMPLE_RATE * duration_ms / 1000)
            start = _noise_cursor
            end = start + n_samples
            if end <= len(_NOISE_POOL):
                chunk = _NOISE_POOL[start:end]
            else:
                chunk = _NOISE_POOL[start:] + _NOISE_POOL[: end - len(_NOISE_POOL)]
            _noise_cursor = end % len(_NOISE_POOL)

            _play_pcm16(_to_pcm16(chunk, volume))

    except Exception:
        pass
else:
    try:
        _mixer = AudioMixer()
        _SAMPLE_RATE = 44100

        _NOISE_POOL = np.random.uniform(-1, 1, _SAMPLE_RATE).astype(np.float32)
        _noise_cursor = 0

        @lru_cache(maxsize=512)
        def _bake_waveform(freq: float, duration_ms: int, freq_end: float | None, waveform: str, drive: float) -> np.ndarray:
            n_samples = int(_SAMPLE_RATE * duration_ms / 1000)
            t = np.arange(n_samples) / _SAMPLE_RATE
            if freq_end is not None and freq_end != freq:
                k = (freq_end - freq) / (duration_ms / 1000)
                phase = 2 * math.pi * (freq * t + 0.5 * k * t**2)
            else:
                phase = 2 * math.pi * freq * t

            if waveform == "square":
                wave_vals = np.sign(np.sin(phase))
            elif waveform == "saw":
                x = (phase / (2 * math.pi)) % 1.0
                wave_vals = 2 * x - 1
            else:
                wave_vals = np.sin(phase)

            if drive > 0:
                k_drive = 1 + drive * 5
                wave_vals = np.tanh(wave_vals * k_drive) / math.tanh(k_drive)

            return wave_vals.astype(np.float32)

        def beep(
            freq: int = 440,
            duration_ms: int = 80,
            volume: float = 0.3,
            freq_end: int | None = None,
            waveform: str = "sine",
            drive: float = 0.0,
        ) -> None:
            shape = _bake_waveform(
                float(freq),
                int(duration_ms),
                float(freq_end) if freq_end is not None else None,
                waveform,
                round(drive, 2),
            )
            pcm = shape * np.float32(volume)
            _mixer.play(Sound(pcm, sample_rate=_SAMPLE_RATE), gain=1.0)

        def click(duration_ms: int = 20, volume: float = 0.4) -> None:
            global _noise_cursor
            n_samples = int(_SAMPLE_RATE * duration_ms / 1000)
            start = _noise_cursor
            end = start + n_samples
            if end <= len(_NOISE_POOL):
                chunk = _NOISE_POOL[start:end]
            else:
                chunk = np.concatenate((_NOISE_POOL[start:], _NOISE_POOL[: end - len(_NOISE_POOL)]))
            _noise_cursor = end % len(_NOISE_POOL)

            pcm = chunk * np.float32(volume)  # pyright: ignore[reportOperatorIssue]
            _mixer.play(Sound(pcm, sample_rate=_SAMPLE_RATE), gain=1.0)

    except Exception:

        def beep(
            freq: int = 440,
            duration_ms: int = 80,
            volume: float = 0.3,
            freq_end: int | None = None,
            waveform: str = "sine",
            drive: float = 0.0,
        ) -> None:
            pass

        def click(duration_ms: int = 20, volume: float = 0.4) -> None:
            pass


class AutoBreakExtension(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="auto_break",
            interest=[Interest(interest=INTEREST_STATE_UPDATE)],
        )
        self.enabled = False
        self.target: list[ivec2] = []
        self.auto_state = State.BREAKING
        self.punching_state = False

        self._set_id_to_next = False
        self.item_id = 0
        self.place_pending: dict[ivec2, float] = {}
        self.last_confirmation = 0
        self.recording = False
        self.beep = True

        self.cycle_start_time: float | None = None
        self.cycle_durations: deque[float] = deque(maxlen=64)
        self._last_eta_log = 0.0

    @register_thread
    def tone_worker(self) -> None:
        dur = 0.05
        stall_since: float | None = None

        while True:
            while not self.beep:
                time.sleep(0.5)
                stall_since = None

            if self.state.status != Status.IN_WORLD:
                stall_since = None
                beep(900, 110, 0.4, freq_end=1400, waveform="square", drive=0.3)
                beep(1400, 110, 0.4, freq_end=900, waveform="square", drive=0.3)
                continue

            if time.time() - self.last_confirmation < 1:
                stall_since = None
                beep(523, int(dur * 1000), 0.08)
                time.sleep(5 - dur)
                continue

            if stall_since is None:
                stall_since = time.time()
            stalled_for = time.time() - stall_since

            ramp = min(stalled_for / 8.0, 1.0)

            if stalled_for < 2:
                vol = 0.05 + 0.10 * ramp
                drive = 0.15 * ramp
                beep(784, 90, vol, waveform="square", drive=drive)
                time.sleep(0.06)
                beep(523, 130, vol, waveform="square", drive=drive)
                time.sleep(0.9 - 0.2 * ramp)
            elif stalled_for < 5:
                vol = 0.15 + 0.19 * ramp
                drive = 0.15 + 0.10 * ramp
                beep(500, 220, vol, freq_end=1300, waveform="saw", drive=drive)
                time.sleep(0.20 - 0.12 * ramp)
            else:
                vol = 0.34 + 0.16 * ramp
                drive = 0.25 + 0.25 * ramp
                click_vol = 0.15 + 0.25 * ramp
                beep(500, 150, vol, freq_end=1500, waveform="square", drive=drive)
                click(20, click_vol)
                time.sleep(0.02)
                click(20, click_vol)
                time.sleep(0.02)

    @dispatch(Interest(interest=INTEREST_TILE_APPLY_DAMAGE, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_SERVER_TO_CLIENT, id=s.auto))
    def _apply_damange(self, _event: PendingPacket) -> PendingPacket | None:
        self.last_confirmation = time.time()

    @dispatch(Interest(interest=INTEREST_PING_REPLY, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_SERVER_TO_CLIENT, id=s.auto))
    def _ping_reply(self, _event: PendingPacket) -> PendingPacket | None:
        self.last_confirmation = time.time()

    def find_next_target(self) -> bool:
        if self.state.world is None:
            return False

        for i, target in enumerate(self.target):
            tile = self.state.world.get_tile(target)
            if not tile:
                continue

            if tile.fg_id != 0:
                self.target_idx = i
                return True

        return False

    def get_next_target(self) -> TileChangeRequest | bool:
        """true means state change"""
        if self.auto_state == State.BREAKING:
            for target in self.target:
                if not self.in_range(target, punch=True) or self.block_destroyed(target, self.item_id):
                    continue

                return TileChangeRequest(item_id=18, target=target)
            self.auto_state = State.BUILDING
            return True
        elif self.auto_state == State.BUILDING:
            for target in self.target:
                if self.state.inventory.get(self.item_id) is None:
                    self.auto_state = State.BREAKING
                    self._complete_cycle()
                    return True
                if not self.in_range(target, punch=False) or not self.can_place(target, self.item_id):
                    continue
                if target in self.place_pending and time.monotonic() - self.place_pending[target] < 1:
                    continue

                assert self.item_id != 0
                return TileChangeRequest(self.item_id, target)
            self.auto_state = State.BREAKING
            self._complete_cycle()

            return True

        return False

    def _complete_cycle(self) -> None:
        now = time.time()
        if self.cycle_start_time is not None:
            duration = now - self.cycle_start_time
            if duration > 0:
                self.cycle_durations.append(duration)
        self.cycle_start_time = now

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m {secs}s"
        if minutes:
            return f"{minutes}m {secs}s"

        return f"{secs}s"

    def log_eta(self) -> None:
        if not self.cycle_durations:
            self.console_log("ETA: still gathering timing data")
            return

        items_per_cycle = len(self.target)
        if items_per_cycle == 0:
            return

        avg_cycle_time = sum(self.cycle_durations) / len(self.cycle_durations)
        if avg_cycle_time <= 0:
            return

        rate = items_per_cycle / avg_cycle_time
        total_items = self.state.world.dropped.get_total(self.item_id) + self.state.inventory.get(self.item_id).amount if self.state.world else None
        if total_items is None:
            self.console_log(f"cycle avg: {avg_cycle_time:.2f}s for {items_per_cycle} items ({rate:.2f} items/s)")
            return

        eta_seconds = total_items / rate
        self.console_log(f"ETA: {self._format_duration(eta_seconds)} for {total_items} items ({rate:.2f} items/s, based on last {len(self.cycle_durations)} cycles)")

    @register_thread
    def eta_worker(self) -> None:
        while True:
            time.sleep(30)
            if self.enabled:
                self.log_eta()

    @register_thread
    def thread_punch(self) -> None:
        last_tile_change: float = math.inf
        printed = False

        while True:
            while self.state.status == Status.IN_WORLD and self.state.world and self.enabled:
                if time.monotonic() - last_tile_change > 0.3:
                    break

                if self.state.me.state.flags & CharacterFlags.FROZEN:
                    if not printed:
                        print("waiting because character is frozen")
                        printed = True
                    time.sleep(0.01)
                    continue

                if self.last_confirmation != 0 and time.time() - self.last_confirmation > 2:
                    if not printed:
                        print("server not responding in a while, waiting...")
                        printed = True
                    time.sleep(0.01)
                    continue
                printed = False

                next = self.get_next_target()
                if isinstance(next, bool) or not next:
                    # if next:
                    #     time.sleep(0.05)
                    # else:
                    time.sleep(0.01)
                    continue

                now = time.monotonic()
                self.place_pending = {k: v for k, v in self.place_pending.items() if now - v < 1.0}

                if not self.send_tile_change_request(next.item_id, next.target):
                    time.sleep(0.01)
                    continue

                if next.item_id != 18:
                    self.place_pending[next.target] = time.monotonic()

                last_tile_change = time.monotonic()
                time.sleep(random.uniform(0.19, 0.21))

            if self.enabled and self.state.status != Status.IN_WORLD:
                self.punching_state = False
                self.enabled = False
                self.last_confirmation = 0
                self.console_log("auto disabled")

            last_tile_change = math.inf
            self.reset_state()
            time.sleep(0.1)

    def block_destroyed(self, pos: ivec2, id: int) -> bool:
        if not self.state.world:
            return False

        tile = self.state.world.get_tile(pos)
        if not tile:
            return False

        if item_database.get(id).is_background():
            return tile.bg_id == 0

        return tile.fg_id == 0

    def can_place(self, pos: ivec2, item_id: int) -> bool:
        if not self.state.world:
            return False

        tile = self.state.world.get_tile(pos)
        if not tile:
            return False

        if item_database.get(item_id).is_background():
            if tile.fg_id == BEDROCK:
                return False

            if tile.bg_id == item_id:
                return False

            return True
        else:
            return tile.fg_id == 0

    def stop_auto(self) -> None:
        self.enabled = False

    @dispatch(s.command_toggle("/gaut", id=s.auto))
    def _gaut_status(self, _event: PendingPacket) -> PendingPacket | None:
        if self.state.world:
            for sucker in self.state.world.find_tile(where=lambda x: x.extra and isinstance(x.extra, ItemSuckerTile)):
                assert sucker.extra
                extra = sucker.extra.get(ItemSuckerTile)

                self.console_log(f"{item_database.get(extra.item_id).name.decode()}: {extra.item_amount} (of {extra.limit})")

        return self.cancel()

    @dispatch(s.command_toggle("/auto", id=s.auto))
    def _toggle_auto(self, _event: PendingPacket) -> PendingPacket | None:
        if self.item_id != 0:
            self.enabled = not self.enabled
            self.console_log(f"auto is now {self.enabled}")
            if self.enabled:
                self.last_confirmation = time.time()
                if self.cycle_start_time is None:
                    self.cycle_start_time = time.time()
        else:
            self.console_log(f"set item id first")

        return self.cancel()

    @dispatch(s.command_toggle("/beep", id=s.auto))
    def _toggle_beep(self, _event: PendingPacket) -> PendingPacket | None:
        self.beep = not self.beep
        self.console_log(f"beep is now {self.beep}")

        return self.cancel()

    @dispatch(s.command("/t", id=s.auto))
    def _template(self, event: PendingPacket) -> PendingPacket | None:
        self.enabled = False

        template = s.parse_command(event)
        if template == "bfg":
            self.target.clear()
            for x in range(2):
                sign = -1 if self.state.me.flags & TankFlags.FACING_LEFT else 1
                target = ivec2(self.state.me.pos // 32) + ((x + 1) * sign, 0)
                self.target.append(target)
                self.send_particle(ParticleID.LBOT_PLACE, tile=target)
        else:
            self._set_id_to_next = True
            if not self.recording:
                self.target.clear()
                self.recording = True
                self.console_log("now recording action, invoke this command again to complete")
            else:
                self.recording = False
                self.target = list(set(self.target))
                self.target.sort(key=lambda pos: (pos.y, pos.x))
                self.console_log(f"target: {len(self.target)}")
                t = 0
                for _ in range(5):
                    for tile in self.target:
                        schedule_task(lambda tile=tile: self.send_particle(ParticleID.LBOT_PLACE, tile=tile), t)
                        t += 0.1
                    t += 0.5

        return self.cancel()

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(where=[s.tank_flags.bit_test(s.uint(TankFlags.PUNCH))]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        )
    )
    def _on_punch(self, event: PendingPacket) -> PendingPacket | None:
        if self._set_id_to_next and self.state.world:
            pkt = NetPacket.deserialize(event.buf)
            if tile := self.state.world.get_tile(pkt.tank.int_x, pkt.tank.int_y):
                self.item_id = tile.fg_id if tile.fg_id != 0 else tile.bg_id
                self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
                self._set_id_to_next = False

        if self.recording:
            pkt = NetPacket.deserialize(event.buf)
            pos = ivec2(pkt.tank.int_x, pkt.tank.int_y)
            self.target.append(pos)
            self.console_log(f"recorded at {pos.x}, {pos.y}")
            self.send_particle(ParticleID.LBOT_PLACE, tile=pos)

    @dispatch(s.command("/id", id=s.auto))
    def _set_id(self, event: PendingPacket) -> PendingPacket | None:
        id = s.parse_command(event)
        if id:
            self.item_id = int(id)
            self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
        else:
            self._set_id_to_next = True
        return self.cancel()

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(where=[s.tank_flags.bit_test(s.uint(TankFlags.PLACE))]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _on_build(self, event: PendingPacket) -> PendingPacket | None:
        if self._set_id_to_next:
            pkt = NetPacket.deserialize(event.buf)
            self.item_id = pkt.tank.value
            self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
            self._set_id_to_next = False

        if self.recording:
            pkt = NetPacket.deserialize(event.buf)
            pos = ivec2(pkt.tank.int_x, pkt.tank.int_y)
            self.target.append(pos)
            self.console_log(f"recorded at {pos.x}, {pos.y}")
            self.send_particle(ParticleID.LBOT_PLACE, tile=pos)

    @dispatch(
        Interest(
            interest=INTEREST_CALL_FUNCTION,
            call_function=InterestCallFunction(variant=[s.variant[0] == b"OnTalkBubble", s.variant[2] == b"The `2MAGPLANT 5000`` is empty!"]),
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _mag_empty(self, _event: PendingPacket) -> PendingPacket | None:
        self.enabled = False
        self.console_log("auto disabled because of empty magplants")

    @dispatch(
        Interest(
            interest=INTEREST_TILE_CHANGE_REQUEST,
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _tile_change_confirm(self, event: PendingPacket) -> PendingPacket | None:
        self.last_confirmation = time.time()
        if self.place_pending:
            pkt = NetPacket.deserialize(event.buf)
            target = ivec2(pkt.tank.int_x, pkt.tank.int_y)

            if target in self.place_pending and pkt.tank.value != 18:
                del self.place_pending[target]

    def destroy(self) -> None:
        pass

    def send_tile_change_request(self, id: int, target_tile: ivec2) -> bool:
        if not self.in_range(target_tile, id == 18) or self.state.status != Status.IN_WORLD:
            return False
        if (id == 18 and self.block_destroyed(target_tile, self.item_id)) or (id != 18 and not self.can_place(target_tile, id)):
            return False
        if id != 18 and self.state.inventory.get(id) is None:
            return False

        punch_or_place = TankFlags.PUNCH if id == 18 else TankFlags.PLACE
        facing_left = self.facing_left(tile=target_tile)
        print(f"last={time.time()-self.last_confirmation:.2f}, tile change at {target_tile} {id=} facing={'left' if self.state.me.flags & TankFlags.FACING_LEFT != 0 else 'right'}")
        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.TILE_CHANGE_REQUEST,
                        value=id,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=target_tile.x,
                        int_y=target_tile.y,
                        flags=facing_left,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.RELIABLE,
            )
        )
        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.STATE,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=target_tile.x,
                        int_y=target_tile.y,
                        flags=facing_left | TankFlags.STANDING | punch_or_place | TankFlags.TILE_CHANGE,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.NONE,
            )
        )
        self.punching_state = True
        return True

    def reset_state(self) -> None:
        if not self.punching_state or self.state.status != Status.IN_WORLD:
            return

        print("sending reset state")
        facing_left = self.state.me.flags & TankFlags.FACING_LEFT
        pkt = NetPacket(
            type=NetType.TANK_PACKET,
            data=TankPacket(
                type=TankType.STATE,
                vector_x=self.state.me.pos.x,
                vector_y=self.state.me.pos.y,
                int_x=-1,
                int_y=-1,
                flags=facing_left | TankFlags.STANDING,
            ),
        )
        self.push(PreparedPacket(packet=pkt, flags=ENetPacketFlag.NONE, direction=DIRECTION_CLIENT_TO_SERVER))
        time.sleep(random.uniform(0.19, 0.21))
        self.push(PreparedPacket(packet=pkt, flags=ENetPacketFlag.RELIABLE, direction=DIRECTION_CLIENT_TO_SERVER))
        self.punching_state = False


if __name__ == "__main__":
    AutoBreakExtension().standalone()
