from __future__ import annotations

import json

from koko_pi_agent.ui_state import UIStateStore


def test_mascot_open_state_round_trips_and_preserves_other_state(tmp_path) -> None:
    path = tmp_path / "ui_state.json"
    path.write_text(json.dumps({"theme": "koko"}), encoding="utf-8")

    store = UIStateStore(path)
    assert store.mascot_open is False
    assert store.set_mascot_open(True) is True
    assert UIStateStore(path).mascot_open is True
    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "koko"

    assert store.set_mascot_open(False) is True
    assert UIStateStore(path).mascot_open is False


def test_missing_or_corrupt_ui_state_safely_defaults_to_closed(tmp_path) -> None:
    path = tmp_path / "ui_state.json"
    store = UIStateStore(path)
    assert store.mascot_open is False

    path.write_text("{not-json", encoding="utf-8")
    assert store.mascot_open is False
    assert store.set_mascot_open(True) is True
    assert store.mascot_open is True


def test_invalid_open_value_is_not_treated_as_enabled(tmp_path) -> None:
    path = tmp_path / "ui_state.json"
    path.write_text('{"mascot": {"open": "yes"}}', encoding="utf-8")
    assert UIStateStore(path).mascot_open is False


def test_default_state_path_is_scoped_to_current_project(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    store = UIStateStore()
    assert store.path == tmp_path / ".koko" / "ui_state.json"
    assert store.set_mascot_open(True) is True
    assert store.path.exists()
