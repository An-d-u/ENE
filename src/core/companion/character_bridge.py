"""Qt 캐릭터 상태와 최대 하나의 취소 가능한 파일 작업자를 연결한다."""

from dataclasses import dataclass, field
from pathlib import Path
import json
import threading
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer

from .character_assets import build_bundle
from .character_controls import CharacterControls
from .character_state import CharacterState, CharacterStateError, SETTING_KEYS, _settings
from .extension_protocol import EXPRESSION_SETTINGS, normalize_settings
from ..settings import Settings


@dataclass(frozen=True)
class _Selection:
    generation: str
    path: Path | None = field(repr=False)
    emotions: tuple[str, ...]
    settings: dict = field(repr=False)
    parameters: dict = field(repr=False)


class CompanionCharacterBridge(QObject):
    capabilities = ("character_v1",)

    def __init__(self, owner, *, builder=build_bundle):
        super().__init__(owner)
        self.owner, self._builder = owner, builder
        self.state = CharacterState()
        self._active = self._preview = False
        self._selection = self._pending = self._thread = self._cancel = None
        self._result = None
        self._confirmed_settings = {}
        self._confirmed_parameters = {}
        self._controls = None
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._poll)
        owner.expression_changed.connect(self.expression)
        owner.gesture_requested.connect(lambda key: self.action("gesture", key, 0))
        owner.message_received.connect(
            lambda _text, emotion, _thought: self.expression(emotion)
        )

    @property
    def is_running(self):
        # 스레드 종료뿐 아니라 Qt의 결과 회수까지 포함한다.
        return self._thread is not None

    def select(self, path, emotions, settings, parameters, *, reuse=False):
        if reuse and self._selection is not None and (
            self._selection.path == (Path(path) if path else None)
            and self._selection.emotions == tuple(emotions)
        ):
            self._preview = False
            self._sync_head_pat()
            return self._selection.generation
        selection = _Selection(
            str(uuid4()),
            Path(path) if path else None,
            tuple(emotions),
            dict(settings),
            dict(parameters),
        )
        self._selection = selection
        self._confirmed_settings, self._confirmed_parameters = dict(settings), dict(parameters)
        self._preview = False
        self._invalidate("loading" if path else "unsupported")
        if self._active:
            self._pending = selection if path else None
            self._start_pending()
        return selection.generation

    def _invalidate(self, status):
        if self._cancel is not None:
            self._cancel.set()
        self._pending = None
        self.state.unavailable(status)
        self.changed(status)

    def activate(self):
        if self._active:
            return
        self._active = True
        if self._selection and self._selection.path:
            self.state.unavailable("loading")
            self._pending = self._selection
            self._start_pending()

    def deactivate(self):
        if not self._active:
            return
        self._active = False
        self._invalidate("unavailable")

    def preview(self, active):
        self._preview = bool(active)
        self._sync_head_pat()

    def _sync_head_pat(self):
        pat = getattr(self.owner, "_companion_head_pat", None)
        if pat is not None:
            pat.sync()

    def settings_baseline(self):
        """PC 창 전용 기준이다. 로컬 모델 키는 네트워크 메시지에 넣지 않는다."""
        store = self.owner.settings
        return {
            "model_key": str(store.get("model_json_path", Settings.DEFAULT_CONFIG["model_json_path"]) or "").replace("\\", "/"),
            "generation": self._selection.generation if self._selection else self.state.generation,
            "settings_revision": self.state.settings_revision,
            "settings": _settings({key: store.get(key, Settings.DEFAULT_CONFIG[key]) for key in SETTING_KEYS}),
        }

    def save_local_settings(self, values, baseline=None):
        current = self.settings_baseline()
        baseline = current if baseline is None else baseline
        if not isinstance(baseline, dict) or not isinstance(baseline.get("settings"), dict):
            return {"status": "rejected", "reason": "invalid_baseline"}
        if (baseline.get("model_key"), baseline.get("generation")) != (current["model_key"], current["generation"]):
            return {"status": "conflict", "reason": "model_changed", "baseline": current, "conflicts": {}}
        try:
            requested = normalize_settings({key: value for key, value in values.items() if key in SETTING_KEYS})
        except (ValueError, TypeError, OverflowError):
            return {"status": "rejected", "reason": "invalid_settings"}
        dirty = {key: value for key, value in requested.items() if value != baseline["settings"].get(key)}
        same_model = str(values.get("model_json_path", current["model_key"])).replace("\\", "/") == current["model_key"]
        if same_model and self.state.status == "ready" and any(
            dirty[key] and dirty[key] not in self.state.expressions for key in EXPRESSION_SETTINGS & dirty.keys()
        ):
            return {"status": "rejected", "reason": "invalid_expression"}
        conflicts = {key: current["settings"][key] for key, value in dirty.items()
                     if current["settings"][key] != baseline["settings"].get(key) and current["settings"][key] != value}
        if conflicts:
            return {"status": "conflict", "reason": "revision_conflict", "baseline": current, "conflicts": conflicts}
        if dirty:
            confirmed = {**current["settings"], **dirty}
            try:
                self.owner.settings.commit_character_settings(dirty)
            except Exception:
                return {"status": "rejected", "reason": "storage_failed"}
            self.state.commit_settings(confirmed, self.state.parameters)
            self._confirmed_settings = dict(confirmed)
            self.changed("settings_changed")
        return {"status": "accepted", "settings": self.settings_baseline()["settings"]}

    def _commit_remote_storage(self, changes, parameters):
        self.owner.settings.commit_character_settings(
            changes, model_key=self.settings_baseline()["model_key"], parameters=parameters,
        )

    def save_remote_settings(self, connection, fields):
        if self._controls is None:
            self._controls = CharacterControls(self.state, self._commit_remote_storage)
        before = self.state.settings_revision
        answer = self._controls.patch(connection, **{
            key: fields[key] for key in ("command_id", "model_version", "expected_revision", "changes", "parameters")
        })
        if self.state.settings_revision != before:
            self._confirmed_settings = dict(self.state.settings)
            self._confirmed_parameters = dict(self.state.parameters)
            self.changed("settings_changed")
            if not self._preview:
                self._apply_confirmed_to_pc()
        return answer

    def _apply_confirmed_to_pc(self):
        apply = getattr(self.owner.parent(), "apply_companion_character_settings", None)
        if callable(apply):
            try:
                apply()
            except Exception:
                # 저장 성공과 렌더링 실패는 구분한다. 공개 최신값은 manifest로 복구한다.
                print("[Companion] character_settings_render_failed")

    def disconnected(self):
        if self._controls is not None:
            self._controls.disconnected()

    def parameters_committed(self, values):
        self._confirmed_parameters = dict(values)
        clean = {item["id"]: values[item["id"]] for item in self.state.catalog
                 if item["id"] in values and item["min"] <= values[item["id"]] <= item["max"]}
        self.state.commit_settings(self.state.settings, clean)
        self.changed("settings_changed")
        if not self._preview:
            self._apply_confirmed_to_pc()

    def _start_pending(self):
        if self.is_running or not self._active or self._pending is None:
            return
        selection, self._pending = self._pending, None
        cancel = self._cancel = threading.Event()
        self._result = None

        def run():
            try:
                bundle = self._builder(
                    selection.path, emotions=selection.emotions, cancel=cancel
                )
            except Exception:
                bundle = None
            # 단일 작업자의 불변 결과만 넘기며 Qt 상태와 signal은 건드리지 않는다.
            self._result = (selection, bundle)

        self._thread = threading.Thread(
            target=run, name="ene-character-assets", daemon=True
        )
        self._thread.start()
        self.timer.start()

    def _poll(self):
        if self._thread is None or self._thread.is_alive():
            return
        self._thread.join(timeout=0)
        self._thread = None
        result, self._result = self._result, None
        self._cancel = None
        self.timer.stop()
        if result is not None:
            selection, bundle = result
            if self._active and self._selection is selection:
                if bundle is None:
                    self.state.unavailable("unsupported")
                    self.changed("unsupported")
                else:
                    self.state.select(
                        selection.generation,
                        bundle,
                        self._confirmed_settings,
                        self._confirmed_parameters,
                    )
                    self.request_catalog()
        self._start_pending()

    def request_catalog(self):
        if self._active and self.state.bundle is not None and not self._preview:
            self.owner.character_catalog_requested.emit(
                json.dumps(
                    {
                        "generation": self.state.generation,
                        "model_version": self.state.bundle.model_version,
                    },
                    separators=(",", ":"),
                )
            )

    def catalog(self, payload):
        if not self._active or self._preview or not isinstance(payload, dict):
            return False
        if payload.get("status") == "unsupported":
            if self.state.bundle is not None and (
                payload.get("generation"),
                payload.get("model_version"),
            ) == (self.state.generation, self.state.bundle.model_version):
                self.state.unavailable("unsupported")
                self.changed("unsupported")
            return False
        try:
            accepted = self.state.accept_catalog(
                payload.get("generation"),
                payload.get("model_version"),
                payload.get("parameters"),
                payload.get("expressions"),
                payload.get("gestures"),
            )
        except (CharacterStateError, TypeError, ValueError, OverflowError):
            return False
        if accepted:
            expression = payload.get("default_expression")
            if expression in self.state.expressions:
                self.state.default_expression = expression
            self.changed("ready")
        return accepted

    def changed(self, reason):
        self._sync_head_pat()
        self._publish(
            "character_changed",
            {
                "state_revision": self.state.state_revision,
                "model_version": self.state.bundle.model_version
                if self.state.status == "ready"
                else None,
                "reason": reason,
            },
        )

    def _publish(self, kind, fields):
        adapter = getattr(self.owner, "_companion_adapter", None)
        if adapter is not None:
            adapter.publish_extension(kind, fields)

    def expression(self, expression):
        self.action("expression", expression, 0)

    def action(self, kind, key, duration):
        if not self._active or self._preview:
            return
        value = self.state.action(kind, key, duration)
        if value is not None:
            self._publish("character_action", value)

    def emergency_join(self, timeout=0.2):
        self.deactivate()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._poll()
