"""요청 잠금과 독립적으로 현재 작업의 실제 생성 단계만 알린다."""

from .protocol import MAX_SAFE_INTEGER, ProtocolError
from .requests import RequestRef


class CompanionChatProgressBridge:
    capabilities = ("chat_progress_v1",)

    def __init__(self, owner):
        self.owner = owner
        self.reset(owner.chat_state.public_transcript.conversation_id)

    def reset(self, conversation_id):
        self._conversation = conversation_id
        self._revision = 0
        self._phase = "idle"
        self._ref = None
        self._failed = False

    def snapshot(self):
        if self._failed:
            raise ProtocolError("progress_unavailable")
        fields = {"conversation_id": self._conversation, "progress_revision": self._revision, "phase": self._phase}
        if self._phase != "idle":
            fields["request_id"] = self._ref.request_id
        return fields

    def _current(self, ref):
        transcript = self.owner.chat_state.public_transcript
        lifecycle = self.owner.life_record_state
        return isinstance(ref, RequestRef) and (
            ref.server_epoch == transcript.server_epoch
            and ref.conversation_id == transcript.conversation_id == self._conversation
            and ref.operation_id is not None
            and ref.operation_id == str(lifecycle.operation_id)
        )

    def begin(self, ref, phase):
        if phase not in {"preparing", "generating"} or not self._current(ref):
            return
        if self.owner.life_record_state.phase == "shutting_down":
            return
        if self._ref == ref:
            # 완료된 같은 작업이나 늦은 준비 콜백으로 단계를 되돌리지 않는다.
            if self._phase in {"idle", "text_ready", phase} or (self._phase == "generating" and phase == "preparing"):
                return
        self._ref = ref
        self._change(phase)

    def text_ready(self, ref):
        if ref == self._ref and self._current(ref) and self._phase in {"preparing", "generating"}:
            self._change("text_ready")

    def finish(self, ref):
        if ref is not None and ref == self._ref and self._phase != "idle":
            self._change("idle")

    def _change(self, phase):
        if self._failed:
            return
        if self._revision == MAX_SAFE_INTEGER:
            self._failed = True
            self._publish("extension_error", {"feature": "chat_progress_v1", "code": "progress_unavailable"})
            return
        self._revision += 1
        self._phase = phase
        self._publish("chat_progress_state", self.snapshot())

    def _publish(self, kind, fields):
        adapter = getattr(self.owner, "_companion_adapter", None)
        if adapter is not None:
            try:
                adapter.publish_extension(kind, fields)
            except Exception:
                # 부가 알림 실패는 요청 완료를 막지 않는다. 현재 상태는 재조회할 수 있다.
                pass
