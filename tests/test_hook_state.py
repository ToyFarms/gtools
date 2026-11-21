"""The hook's persistent state store and the panel's snapshot model."""

import json

import pytest

from gtools.hooks import state as hook_state


@pytest.fixture()
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "hook_state.json"
    monkeypatch.setattr(hook_state, "STATE_FILE", path)
    monkeypatch.setattr(hook_state, "_state", None)
    return path


def test_defaults_when_missing(state_file):
    s = hook_state.load()
    assert s.log_level == 1
    assert s.allow_any_module is False
    assert s.low_power is False
    assert s.low_power_fps == 0
    assert s.low_power_skip_draws is False


def test_save_and_reload_roundtrip(state_file):
    s = hook_state.load()
    s.low_power = True
    s.low_power_fps = 30
    hook_state.save(s)

    fresh = hook_state.load()  # re-read: other processes stay coherent
    assert fresh.low_power is True
    assert fresh.low_power_fps == 30
    assert json.loads(state_file.read_text())["low_power_fps"] == 30


def test_unknown_keys_and_corruption_are_tolerated(state_file):
    state_file.write_text(json.dumps({"log_level": 2, "nonsense": [1], "hook": {}}))
    s = hook_state.load()
    assert s.log_level == 2
    assert not hasattr(s, "nonsense")

    state_file.write_text("{not json")
    assert hook_state.load().log_level == 1  # defaults


def test_gui_edits_flow_through_the_store(state_file):
    """The panel's edit path: mutate, save, and the next reader sees it."""
    from gtools.gui.panels import hook_panel  # noqa: F401  (imports the store too)

    s = hook_state.load()
    s.low_power_fps = 60
    hook_state.save(s)
    assert hook_state.load().low_power_fps == 60
