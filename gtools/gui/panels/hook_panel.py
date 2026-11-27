import logging
import queue
import threading
from dataclasses import dataclass, field

from imgui_bundle import imgui
from imgui_bundle import imgui_toggle  # pyright: ignore[reportMissingModuleSource]

from gtools.core.pipe import PipeError, PipeUnavailable
from gtools.gui.widgets.toast import push_error
from gtools.gui.panels.panel import Panel
from gtools.hooks import hook, state as hook_state
from gtools.hooks.control import HookControl

logger = logging.getLogger("gui-hook-panel")


@dataclass(frozen=True)
class HookRow:
    key: str
    status: str
    enabled: bool
    hits: int
    faults: int
    state0: int


@dataclass(frozen=True)
class HookSnapshot:
    connected: bool = False
    target: str = ""
    pid: int = 0
    uptime_ms: int = 0
    log_level: int = 1
    rows: tuple[HookRow, ...] = field(default=tuple())


@dataclass(frozen=True)
class EnableCommand:
    key: str
    on: bool


@dataclass(frozen=True)
class StateCommand:
    key: str
    slot: int
    value: int


@dataclass(frozen=True)
class LogLevelCommand:
    level: int


@dataclass(frozen=True)
class InjectCommand:
    pass


HookCommand = EnableCommand | StateCommand | LogLevelCommand | InjectCommand


class HookPanelModel:
    def __init__(self, poll_interval: float = 0.5) -> None:
        self.poll_interval = poll_interval
        self.snapshot = HookSnapshot()
        self.commands: queue.Queue[HookCommand] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="hook-panel-model", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def submit(self, command: HookCommand) -> None:
        self.commands.put(command)

    def _run(self) -> None:
        try:
            ctl = HookControl(timeout=0.5)
        except Exception:
            logger.exception("the hook panel model could not create its control")
            return
        inject_error = ""
        while not self._stop.is_set():
            if not ctl.connected:
                try:
                    if not ctl.connect(0.5):
                        self.snapshot = HookSnapshot()
                        self._stop.wait(self.poll_interval)
                        continue
                except (PipeUnavailable, PipeError):
                    self.snapshot = HookSnapshot()
                    self._stop.wait(self.poll_interval)
                    continue

            try:
                self._drain_commands(ctl)
                self.snapshot = self._poll(ctl)
            except (PipeError, PipeUnavailable):
                ctl.close()
                self.snapshot = HookSnapshot()
            except Exception:
                logger.exception("the hook panel model failed")
                ctl.close()
                self.snapshot = HookSnapshot()
            self._stop.wait(self.poll_interval)
        ctl.close()
        if inject_error:
            logger.debug(inject_error)

    def _drain_commands(self, ctl: HookControl) -> None:
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return

            try:
                if isinstance(command, EnableCommand):
                    ctl.enable(command.key, command.on)
                elif isinstance(command, StateCommand):
                    ctl.state(command.key, command.slot, command.value)
                elif isinstance(command, LogLevelCommand):
                    ctl.log_level(command.level)
                elif isinstance(command, InjectCommand):
                    inject_error = self._inject()
                    if inject_error:
                        push_error("Hook", "injection failed", inject_error)
            except (PipeError, PipeUnavailable):
                raise
            except Exception:
                logger.exception("the hook panel command failed: %r", command)

    def _inject(self) -> str:
        try:
            hook.build_payload_file()
        except Exception as e:
            logger.exception("failed to write the hook payload")
            return str(e)
        try:
            if not hook.inject_hook():
                return str(hook.read_inject_status().get("error", "injection failed"))
        except hook.UacDeclined:
            push_error("Hook", "elevation declined", "the hook stays off until you inject again")
            return ""
        return ""

    def _poll(self, ctl: HookControl) -> HookSnapshot:
        pairs = ctl.status()
        status = {key: value for key, value in pairs.items() if not key.startswith(("hook_", "target_", "hits_", "faults_", "enabled_", "state_"))}
        hooks: dict[str, dict[str, str]] = {}
        for key, value in pairs.items():
            if key.startswith("hook_"):
                name = key[len("hook_") :]
                hooks.setdefault(name, {})["status"] = value
            elif key.startswith("enabled_"):
                hooks.setdefault(key[len("enabled_") :], {})["enabled"] = value
            elif key.startswith("hits_"):
                hooks.setdefault(key[len("hits_") :], {})["hits"] = value
            elif key.startswith("faults_"):
                hooks.setdefault(key[len("faults_") :], {})["faults"] = value
            elif key.startswith("state_"):
                parts = key[len("state_") :].rsplit("_", 1)
                if len(parts) == 2:
                    hooks.setdefault(parts[0], {})[f"state{parts[1]}"] = value

        rows = []
        for name, fields in sorted(hooks.items()):
            rows.append(
                HookRow(
                    key=name,
                    status=fields.get("status", "missing"),
                    enabled=fields.get("enabled") == "1",
                    hits=int(fields.get("hits", "0") or 0),
                    faults=int(fields.get("faults", "0") or 0),
                    state0=int(fields.get("state0", "0") or 0),
                )
            )
        return HookSnapshot(
            connected=True,
            target=status.get("target", ""),
            pid=int(status.get("pid", "0") or 0),
            uptime_ms=int(status.get("uptime_ms", "0") or 0),
            log_level=int(status.get("level", "1") or 1),
            rows=tuple(rows),
        )


class HookPanel(Panel):
    def __init__(self, dock_id: int = 0) -> None:
        super().__init__(dock_id)
        self._is_docked = False
        self._model = HookPanelModel()
        self._model.start()

    def delete(self) -> None:
        self._model.stop()

    def render(self) -> None:
        if not self._is_docked and self.dock_id:
            imgui.set_next_window_dock_id(self.dock_id)

        opened, _ = imgui.begin("Hook", None, imgui.WindowFlags_.no_collapse)
        if not opened:
            imgui.end()
            return

        snapshot = self._model.snapshot
        self._render_header(snapshot)

        if imgui.begin_table("##hooks", 5, imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_inner_h):
            imgui.table_setup_column("hook")
            imgui.table_setup_column("status")
            imgui.table_setup_column("enabled")
            imgui.table_setup_column("state0")
            imgui.table_setup_column("hits / faults")
            imgui.table_headers_row()

            for row in snapshot.rows:
                imgui.table_next_row()
                imgui.table_next_column()
                imgui.text(row.key)
                imgui.table_next_column()
                color = (0.4, 0.9, 0.4, 1.0) if row.status == "patched" else (0.95, 0.8, 0.3, 1.0) if row.status == "ready" else (0.6, 0.6, 0.6, 1.0)
                imgui.text_colored(color, row.status)
                imgui.table_next_column()
                changed, _ = imgui_toggle.toggle("##enable_" + row.key, row.enabled)
                if changed:
                    self._model.submit(EnableCommand(row.key, not row.enabled))
                imgui.table_next_column()
                changed, value = imgui.input_int(f"##state_{row.key}", row.state0)
                if changed and value != row.state0:
                    self._model.submit(StateCommand(row.key, 0, value))
                imgui.table_next_column()
                imgui.text(f"{row.hits} / {row.faults}")
            imgui.end_table()

        imgui.separator()
        self._render_state_editor()
        imgui.end()

    def _render_header(self, snapshot: HookSnapshot) -> None:
        if snapshot.connected:
            uptime = snapshot.uptime_ms // 1000
            imgui.text_colored((0.4, 0.9, 0.4, 1.0), "connected")
            imgui.same_line()
            imgui.text(f"target={snapshot.target} uptime={uptime}s")
        else:
            imgui.text_colored((0.95, 0.6, 0.3, 1.0), "not connected")
            imgui.same_line()
            if imgui.small_button("Inject"):
                self._model.submit(InjectCommand())
        imgui.separator()

    def _render_state_editor(self) -> None:
        current = hook_state.load()
        changed_any = False

        changed, value = imgui.slider_int("frame fps", max(0, min(current.low_power_fps, 240)), 0, 240)
        if changed and value != current.low_power_fps:
            current.low_power_fps = value
            changed_any = True
        changed, value = imgui_toggle.toggle("frame pacing (low power)", current.low_power)
        if changed and value != current.low_power:
            current.low_power = value
            changed_any = True
        changed, value = imgui_toggle.toggle("skip draws", current.low_power_skip_draws)
        if changed and value != current.low_power_skip_draws:
            current.low_power_skip_draws = value
            changed_any = True

        changed, value = imgui.input_int("log level", current.log_level)
        if changed and 0 <= value <= 2 and value != current.log_level:
            current.log_level = value
            changed_any = True
        changed, value = imgui_toggle.toggle("allow any module (next inject)", current.allow_any_module)
        if changed and value != current.allow_any_module:
            current.allow_any_module = value
            changed_any = True

        if changed_any:
            hook_state.save(current)
            self._model.submit(EnableCommand("render/frame", current.low_power))
            self._model.submit(StateCommand("render/frame", 0, current.low_power_fps))
            self._model.submit(EnableCommand("render/submit", current.low_power and current.low_power_skip_draws))
            self._model.submit(StateCommand("render/submit", 0, 1 if current.low_power_skip_draws else 0))
            self._model.submit(LogLevelCommand(current.log_level))
