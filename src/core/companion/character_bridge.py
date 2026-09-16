"""Qt 캐릭터 상태와 최대 하나의 취소 가능한 파일 작업자를 연결한다."""

from dataclasses import dataclass, field
from pathlib import Path
import json
import threading
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer

from .character_assets import build_bundle
from .character_state import CharacterState, CharacterStateError


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

    def select(self, path, emotions, settings, parameters):
        selection = _Selection(
            str(uuid4()),
            Path(path) if path else None,
            tuple(emotions),
            dict(settings),
            dict(parameters),
        )
        self._selection = selection
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
                        selection.settings,
                        selection.parameters,
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
