"""apply_hook_state / apply_proxy_data against a fake control."""

from gtools.hooks import hook, state as hook_state


class FakeControl:
    def __init__(self):
        self.last_reply = ""
        self.calls: list[tuple] = []
        self.fail_keys: set[str] = set()

    def enable(self, key, on, timeout=None):
        self.calls.append(("ENABLE", key, on))
        return key not in self.fail_keys

    def state(self, key, slot, value, timeout=None):
        self.calls.append(("STATE", key, slot, value))
        return key not in self.fail_keys

    def log_level(self, level, timeout=None):
        self.calls.append(("LOGLEVEL", level))
        return True

    def data(self, key, offset, blob, timeout=None):
        self.calls.append(("DATA", key, offset, blob))
        return key not in self.fail_keys


def test_state_maps_onto_runtime_writes(monkeypatch):
    ctl = FakeControl()
    monkeypatch.setattr(hook_state, "load", lambda: hook_state.HookState(
        log_level=2, allow_any_module=True, low_power=True, low_power_fps=42, low_power_skip_draws=True))

    rejected = hook.apply_hook_state(ctl)
    assert rejected == []
    calls = {(c[0], c[1]): c for c in ctl.calls}
    assert calls[("STATE", "render/frame")][3] == 42
    assert calls[("ENABLE", "render/frame")] == ("ENABLE", "render/frame", True)
    assert calls[("STATE", "render/submit")][3] == 1
    assert calls[("ENABLE", "render/submit")] == ("ENABLE", "render/submit", True)
    assert calls[("LOGLEVEL",)] if False else ("LOGLEVEL", 2) in ctl.calls
    # proxy data is NOT part of the hook state push
    assert not any(c[0] == "DATA" for c in ctl.calls)


def test_proxy_data_push(monkeypatch):
    ctl = FakeControl()
    rejected = hook.apply_proxy_data(ctl, "10.0.0.5", 17000)
    assert rejected == []
    data_calls = [c for c in ctl.calls if c[0] == "DATA"]
    assert data_calls and data_calls[0][1] == "net/response"
    blob = data_calls[0][3]
    import struct
    host_len = struct.unpack_from("<I", blob, 0)[0]
    assert blob[4:4 + host_len] == b"10.0.0.5"


def test_rejections_carry_the_agent_reply(monkeypatch):
    ctl = FakeControl()
    ctl.fail_keys.add("render/frame")
    ctl.last_reply = "write failed"
    monkeypatch.setattr(hook_state, "load", lambda: hook_state.HookState())

    rejected = hook.apply_hook_state(ctl)
    assert ("render/frame enable", "write failed") in rejected
    assert ("render/frame fps", "write failed") in rejected
