"""합성 모델과 Qt 이벤트 루프로 단일 자산 작업자의 수명을 확인한다."""

import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from src.core.companion.character_bridge import CompanionCharacterBridge
from src.core.companion.character_assets import build_bundle
from src.core.companion.controller import CompanionController
from tests.test_companion_character_assets import synthetic_model
from tests.test_companion_character_state import CATALOG
from tests.test_companion_adapter import qt_app as synthetic_qt_app  # noqa: F401


class Owner(QObject):
    character_catalog_requested = pyqtSignal(str)
    expression_changed = pyqtSignal(str)
    gesture_requested = pyqtSignal(str)
    message_received = pyqtSignal(str, str, str)

    def __init__(self):
        super().__init__()
        self.sent = []
        self._companion_adapter = self

    def publish_extension(self, kind, fields):
        self.sent.append((kind, fields))


def wait_until(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_disabled_does_not_read_files_and_ready_requires_matching_catalog(tmp_path):
    app = QApplication.instance() or QApplication([])
    owner = Owner()
    bridge = CompanionCharacterBridge(owner)
    requests = []
    owner.character_catalog_requested.connect(
        lambda value: requests.append(json.loads(value))
    )
    generation = bridge.select(synthetic_model(tmp_path), (), {}, {})
    assert not bridge.is_running and bridge.state.bundle is None
    bridge.activate()
    wait_until(app, lambda: not bridge.is_running)
    assert requests[-1]["generation"] == generation
    assert bridge.state.status == "loading"
    assert bridge.catalog(
        {
            **requests[-1],
            "parameters": CATALOG,
            "expressions": ["normal", "bright"],
            "gestures": ["nod"],
        }
    )
    owner.expression_changed.emit("bright")
    owner.gesture_requested.emit("nod")
    assert [kind for kind, _ in owner.sent[-2:]] == [
        "character_action",
        "character_action",
    ]
    bridge.preview(True)
    seq = bridge.state.action_seq
    owner.expression_changed.emit("normal")
    assert bridge.state.action_seq == seq
    bridge.deactivate()
    assert bridge.state.capture().bundle is None


def test_pc_default_expression_change_reuses_model_but_invalidates_settings_revision(tmp_path):
    app = QApplication.instance() or QApplication([])
    owner = Owner()
    owner.settings = {"head_pat_active_emotion_default": "normal"}
    bridge = CompanionCharacterBridge(owner)
    path = synthetic_model(tmp_path)
    generation = bridge.select(path, (), owner.settings, {})
    bridge.activate()
    wait_until(app, lambda: not bridge.is_running)
    assert bridge.catalog({"generation": generation, "model_version": bridge.state.bundle.model_version,
                           "parameters": CATALOG, "expressions": ["normal", "bright"], "gestures": ["nod"]})
    revision = bridge.state.settings_revision
    owner.settings["head_pat_active_emotion_default"] = "bright"
    assert bridge.select(path, (), owner.settings, {}, reuse=True) == generation
    assert bridge.state.settings_revision == revision + 1
    assert bridge.state.snapshot()["head_pat_defaults"]["active"] == "bright"
    assert not bridge.is_running
    bridge.deactivate()


def test_replacement_has_one_worker_and_discards_late_result(tmp_path):
    app = QApplication.instance() or QApplication([])
    owner = Owner()
    bundle = build_bundle(synthetic_model(tmp_path))
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked(path, *, emotions, cancel):
        calls.append((path, cancel))
        entered.set()
        release.wait(3)
        return bundle

    bridge = CompanionCharacterBridge(owner, builder=blocked)
    bridge.select(Path("synthetic-first.model3.json"), (), {}, {})
    bridge.activate()
    assert entered.wait(1)
    bridge.select(Path("synthetic-skipped.model3.json"), (), {}, {})
    generation = bridge.select(Path("synthetic-last.model3.json"), (), {}, {})
    assert len(calls) == 1 and calls[0][1].is_set()
    release.set()
    wait_until(app, lambda: not bridge.is_running)
    assert len(calls) == 2 and calls[-1][0].name == "synthetic-last.model3.json"
    assert bridge.state.generation == generation
    bridge.deactivate()


def test_stop_waits_for_worker_and_never_applies_its_late_bundle(tmp_path):
    app = QApplication.instance() or QApplication([])
    owner = Owner()
    bundle = build_bundle(synthetic_model(tmp_path))
    entered, release = threading.Event(), threading.Event()

    def blocked(path, *, emotions, cancel):
        entered.set()
        release.wait(3)
        return bundle

    bridge = CompanionCharacterBridge(owner, builder=blocked)
    bridge.select(Path("synthetic.model3.json"), (), {}, {})
    bridge.activate()
    assert entered.wait(1)
    bridge.deactivate()
    assert bridge.is_running
    release.set()
    wait_until(app, lambda: not bridge.is_running)
    assert bridge.state.bundle is None and bridge.state.status == "unavailable"


def test_controller_does_not_finish_until_cancelled_character_worker_drains(tmp_path):
    app = QApplication.instance() or QApplication([])
    owner = Owner()
    entered, release = threading.Event(), threading.Event()

    def blocked(path, *, emotions, cancel):
        entered.set()
        release.wait(3)
        return None

    owner._companion_character = CompanionCharacterBridge(owner, builder=blocked)
    owner._companion_character.select(Path("synthetic.model3.json"), (), {}, {})
    controller = CompanionController(owner)
    stopped = []
    controller.stopped.connect(lambda: stopped.append(True))
    owner._companion_character.activate()
    assert entered.wait(1)
    controller.stop()
    controller._finish_thread()
    assert controller.isRunning() and stopped == []
    release.set()
    wait_until(app, lambda: bool(stopped))
    assert not controller.isRunning() and stopped == [True]


def test_qt_capture_rechecks_connection_and_returns_frozen_bytes(request, tmp_path):
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter
    from tests.companion_helpers import sample_id
    from tests.test_companion_adapter import SyntheticOwner, context, run_adapter
    from tests.test_companion_character_state import state_with_bundle

    qt_app = request.getfixturevalue("synthetic_qt_app")
    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(
        state.generation, bundle.model_version, CATALOG, ["normal"], ["nod"]
    )
    owner = SyntheticOwner()
    owner._companion_character = SimpleNamespace(
        state=state, activate=lambda: None, deactivate=lambda: None
    )
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)

    async def scenario():
        await adapter.call("connect", context())
        capture = await adapter.call("character_capture", context())
        assert capture.bundle is bundle and isinstance(capture.body, bytes)
        with pytest.raises(AdapterError, match="stale_connection"):
            await adapter.call("character_capture", context(connection=2))
        await adapter.call("block", context())
        with pytest.raises(AdapterError, match="admission_blocked"):
            await adapter.call("character_capture", context())

    run_adapter(qt_app, adapter, scenario)
