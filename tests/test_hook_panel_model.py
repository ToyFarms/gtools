"""The hook panel's background model against a fake control."""

import threading
import time

from gtools.gui.panels import hook_panel
from gtools.gui.panels.hook_panel import HookCommand, HookPanelModel, InjectCommand, StateCommand
from gtools.hooks import hook


class FakeControl:
    def __init__(self, timeout: float = 0.5):
        self.connected = True
        self.last_reply = ""
        self.status_pairs = {
            "target": "Growtopia.exe", "pid": "4242", "uptime_ms": "1200", "level": "1",
            "hook_render/frame": "patched", "enabled_render/frame": "1",
            "hits_render/frame": "12", "faults_render/frame": "0", "state_render/frame_0": "30",
            "hook_net/response": "patched", "enabled_net/response": "1",
            "hits_net/response": "1", "faults_net/response": "0", "state_net/response_0": "0",
        }

    def connect(self, timeout=None):
        return True

    def close(self):
        self.connected = False

    def status(self, timeout=None):
        return dict(self.status_pairs)

    def enable(self, key, on, timeout=None):
        self.status_pairs[f"enabled_{key}"] = "1" if on else "0"
        return True

    def state(self, key, slot, value, timeout=None):
        self.status_pairs[f"state_{key}_{slot}"] = str(value)
        return True

    def log_level(self, level, timeout=None):
        self.status_pairs["level"] = str(level)
        return True


def test_snapshot_parses_status_into_rows(monkeypatch):
    monkeypatch.setattr(hook_panel, "HookControl", FakeControl)
    model = HookPanelModel(poll_interval=0.05)
    model.start()
    deadline = time.time() + 2
    while time.time() < deadline and len(model.snapshot.rows) < 2:
        time.sleep(0.02)
    model.stop()

    assert model.snapshot.connected
    assert model.snapshot.target == "Growtopia.exe"
    assert model.snapshot.pid == 4242
    frame = next(r for r in model.snapshot.rows if r.key == "render/frame")
    assert frame.status == "patched" and frame.enabled and frame.hits == 12 and frame.state0 == 30


def test_commands_execute(monkeypatch):
    fake = FakeControl()
    monkeypatch.setattr(hook_panel, "HookControl", lambda timeout=0.5: fake)
    model = HookPanelModel(poll_interval=0.05)
    model.start()
    model.submit(StateCommand("render/frame", 0, 77))
    deadline = time.time() + 2
    while time.time() < deadline and fake.status_pairs["state_render/frame_0"] != "77":
        time.sleep(0.02)
    model.stop()
    assert fake.status_pairs["state_render/frame_0"] == "77"
