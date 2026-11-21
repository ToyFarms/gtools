"""apply_hook_settings: settings -> runtime writes through a fake control."""

from gtools.hooks import hook, payload, registry


class FakeControl:
    """Records the generic pipe commands apply_hook_settings should emit."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.fail_keys: set[str] = set()

    def enable(self, key: str, on: bool) -> bool:
        self.calls.append(("ENABLE", key, on))
        return key not in self.fail_keys

    def state(self, key: str, slot: int, value: int) -> bool:
        self.calls.append(("STATE", key, slot, value))
        return key not in self.fail_keys

    def data(self, key: str, offset: int, blob: bytes) -> bool:
        self.calls.append(("DATA", key, offset, blob))
        return key not in self.fail_keys

    def log_level(self, level: int) -> bool:
        self.calls.append(("LOGLEVEL", level))
        return True


def fake_setting(monkeypatch):
    from gtools.setting import HookSetting, Setting

    setting = Setting()
    setting.proxy_server = "10.0.0.5"
    setting.proxy_port = 17000
    setting.hook = HookSetting(low_power=True, low_power_fps=42, low_power_skip_draws=True, stream_game_logs=True)
    monkeypatch.setattr(hook, "setting", setting)
    return setting


def test_settings_map_onto_runtime_writes(monkeypatch):
    fake_setting(monkeypatch)
    ctl = FakeControl()
    hook.apply_hook_settings(ctl)

    calls = {(c[0], c[1]): c for c in ctl.calls}
    # proxy host/port land in net/response's data blob (its runtime data blob)
    data_call = calls[("DATA", "net/response")]
    blob = data_call[3]
    import struct

    host_len = struct.unpack_from("<I", blob, 0)[0]
    assert blob[4:4 + host_len] == b"10.0.0.5"
    port_len = struct.unpack_from("<I", blob, programs_port_offset())[0]
    assert blob[programs_port_offset() + 4:programs_port_offset() + 4 + port_len] == b"17000"

    # low power: fps into frame state, both frame and submit enabled
    assert calls[("STATE", "render/frame")][3] == 42
    assert calls[("ENABLE", "render/frame")] == ("ENABLE", "render/frame", True)
    assert calls[("STATE", "render/submit")][3] == 1
    assert calls[("ENABLE", "render/submit")] == ("ENABLE", "render/submit", True)

    # game log streaming enables the two log hooks
    assert calls[("ENABLE", "log/printf")] == ("ENABLE", "log/printf", True)
    assert calls[("ENABLE", "log/raw")] == ("ENABLE", "log/raw", True)


def programs_port_offset() -> int:
    from gtools.hooks import programs

    return programs.RESP_PORT_LEN


def test_binds_the_control_for_later_runtime_calls(monkeypatch):
    fake_setting(monkeypatch)
    ctl = FakeControl()
    hook.apply_hook_settings(ctl)
    assert registry.get_control() is ctl
    # a later Hook runtime call works without re-binding
    registry.get("render/frame").set_enabled(False)
    assert ("ENABLE", "render/frame", False) in ctl.calls


def test_rejected_writes_do_not_raise(monkeypatch):
    fake_setting(monkeypatch)
    ctl = FakeControl()
    ctl.fail_keys.add("log/raw")
    hook.apply_hook_settings(ctl)  # must not raise
    assert ("ENABLE", "log/raw", True) in ctl.calls  # attempted, reported via log
