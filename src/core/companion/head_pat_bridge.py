"""PC 전용 모델 세대와 현재 인증 연결을 쓰다듬기 조정기에 연결한다."""

from collections import OrderedDict
from hashlib import sha256
import json
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer

from .head_pat import HeadPatCoordinator, MAX_SEQUENCE
from .protocol import uuid_value


class CompanionHeadPatBridge(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.character = owner._ensure_companion_character()
        self._generation = self._public_version = None
        self._pc_connection = str(uuid4())
        self._pc_number = 0
        self._pc_ids = OrderedDict()
        self._closed = False
        self.coordinator = HeadPatCoordinator(lambda: owner._record_confirmed_head_pat(), self._publish)
        self.coordinator.bind("pc", self._pc_connection)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.sync()

    def sync(self):
        if self._closed:
            return
        character = self.character
        generation = character._selection.generation if character._selection else character.state.generation
        public = character.state.bundle.model_version if character._active and character.state.status == "ready" else None
        if self._generation is not None and generation != self._generation:
            self.coordinator.cancel("model_changed")
        # PC 단독/이미지 모드의 세대는 네트워크에 내보내지 않는다.
        version = public or (sha256(generation.encode("ascii")).hexdigest() if generation else None)
        store = getattr(self.owner, "settings", None)
        allowed = bool(store and store.get("enable_head_pat", True)) and not character._preview
        self.coordinator.configure(version, enabled=allowed)
        self._generation, self._public_version = generation, public
        self._update_timer()

    def pc(self, raw):
        try:
            if self._closed or not isinstance(raw, str) or len(raw.encode("utf-8")) > 2048:
                raise ValueError("invalid_input")
            fields = json.loads(raw)
            if not isinstance(fields, dict):
                raise ValueError("invalid_input")
            self.sync()
            if uuid_value(fields.get("model_generation")) != self._generation:
                raise ValueError("model_changed")
            clean = self.coordinator._validate({**fields, "model_version": self.coordinator.model_version, "interaction_no": 1})
            identifier = clean["interaction_id"]
            number = self._pc_ids.get(identifier)
            if number is None:
                if clean["phase"] != "start" or self._pc_number >= MAX_SEQUENCE:
                    raise ValueError("no_active_interaction")
                self._pc_number += 1
                number = self._pc_number
                self._pc_ids[identifier] = number
                if len(self._pc_ids) > 256:
                    self._pc_ids.popitem(last=False)
            answer = self.coordinator.receive("pc", self._pc_connection, {**clean, "interaction_no": number})
            self._update_timer()
            return json.dumps({**answer, "model_generation": self._generation}, ensure_ascii=False)
        except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
            return json.dumps({"phase": "rejected", "reason": "invalid_or_stale_input"})

    def phone(self, connection, fields):
        """호출자는 실제 Qt admission과 확장 봉투를 먼저 검증해야 한다."""
        self.sync()
        if self._closed or self._public_version is None:
            clean = self.coordinator._validate(fields)
            return self.coordinator._answer("phone", clean, "rejected", "character_unavailable")
        self.coordinator.bind("phone", connection)
        answer = self.coordinator.receive("phone", connection, fields)
        self._update_timer()
        return answer

    def disconnected(self):
        self.coordinator.bind("phone", None)
        self._update_timer()

    def _publish(self, fields):
        self.owner.head_pat_state.emit(json.dumps({**fields, "model_generation": self._generation,
            "connection_generation": self.coordinator.connections[fields["source"]]}, ensure_ascii=False))
        if fields["source"] == "phone":
            adapter = getattr(self.owner, "_companion_adapter", None)
            current = getattr(adapter, "is_current_connection", None)
            if not callable(current) or not current(self.coordinator.connections["phone"]):
                return
        if self._public_version is not None and fields["model_version"] == self._public_version:
            self.character._publish("head_pat_state", fields)

    def _update_timer(self):
        if self.coordinator.active is not None and not self._closed:
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def _tick(self):
        self.sync()
        self.coordinator.tick()
        self._update_timer()

    def close(self):
        self._closed = True
        self.coordinator.cancel("shutdown")
        self.timer.stop()
