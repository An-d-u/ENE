"""현재 공개 발화의 실제 출력 위치만 전달하는 Qt 소유 표시 상태."""

import json
import math
import time


class CharacterPlayback:
    def __init__(self, owner):
        self.owner = owner
        self.now_ms = lambda: int(time.monotonic() * 1000)
        self.ref = None
        self.output = "none"
        self.played_ms = 0
        self.mouth = 0.0
        self.updated = 0
        self.started = 0
        self._published_at = None
        self.player = None
        self._connections = []

    @property
    def active(self):
        return self.ref is not None

    @property
    def phone_active(self):
        return self.active and self.output == "phone"

    def _current(self):
        head = self.owner.head()
        return self.ref is not None and (
            self.ref["server_epoch"], self.ref["conversation_id"]
        ) == (head.server_epoch, head.conversation_id) and (
            self.ref["message_id"] in self.owner.chat_state.public_assistant_ids.values()
        )

    def begin(self, ref, output, player=None):
        self.finish()
        self.ref, self.output, self.player = dict(ref), output, player
        self.played_ms, self.mouth, self.updated = 0, 0.0, self.now_ms()
        self.started, self._published_at = self.updated, None
        if not self._current():
            self.ref, self.player = None, None
            return
        # 이전 장치에서 늦게 전달된 종료 콜백은 새 발화를 종료하지 못한다.
        identity = self.ref
        for name in ("playback_finished", "playback_error"):
            signal = getattr(player, name, None)
            if signal is not None:
                def callback(*_, expected=identity):
                    self.finish_if(expected)
                signal.connect(callback)
                self._connections.append((signal, callback))
        self._publish(True)

    def finish_if(self, expected):
        if self.ref is expected:
            self.finish()

    def phone(self, ref, played_ms, mouth):
        if self.ref != ref or self.output != "phone":
            self.begin(ref, "phone")
        if not self.active or played_ms < self.played_ms:
            return
        self.played_ms, self.mouth, self.updated = played_ms, mouth, self.now_ms()
        self._mouth(mouth)
        self._publish(True)

    def pc_mouth(self, value):
        if self.active and self.output == "pc":
            self.mouth = max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0

    def tick(self):
        if not self.active:
            return
        if not self._current():
            self.finish()
            return
        now = self.now_ms()
        if now < self.started or now - self.started > 180750:
            self.finish()
            return
        if self.output == "pc":
            position = getattr(self.player, "position_ms", None)
            if not callable(position):
                self.finish()
                return
            try:
                value = position()
                if type(value) is not int or value < 0 or value > 180000:
                    self.finish()
                    return
            except Exception:
                self.finish()
                return
            if value > self.played_ms:
                self.played_ms, self.updated = value, now
            if now < self.updated or now - self.updated >= 750:
                self.mouth = 0.0
            self._publish(True)
        else:
            if (now < self.updated or now - self.updated >= 750) and self.mouth != 0:
                self.mouth = 0.0
                self._mouth(0.0)
            self._publish(True)

    def _mouth(self, value):
        self.owner.lip_sync_update.emit(value)
        self.owner.mouth_pose_update.emit(json.dumps({
            "open": value, "jaw": 0, "form": 0, "funnel": 0,
            "pucker_widen": 0, "tongue": 0, "confidence": 0, "source": "rms",
        }))

    def _publish(self, active):
        if not self._current():
            return
        now = self.now_ms()
        if active and self._published_at is not None and now - self._published_at < 100:
            return
        self._published_at = now
        adapter = getattr(self.owner, "_companion_adapter", None)
        if adapter is not None:
            try:
                adapter.publish_extension("character_playback", {
                    **{key: self.ref[key] for key in ("conversation_id", "message_id", "utterance_id")},
                    "output": self.output if active else "none",
                    "played_ms": self.played_ms, "mouth_open": self.mouth if active else 0.0,
                    "active": active,
                })
            except Exception:
                # 표시 채널의 실패로 채팅/PCM 재생 수명을 끊지 않는다.
                pass

    def finish(self):
        for signal, callback in self._connections:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()
        if self.active:
            self._mouth(0.0)
            self._publish(False)
        self.ref, self.player, self.output, self.mouth = None, None, "none", 0.0
