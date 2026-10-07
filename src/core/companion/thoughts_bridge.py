"""공개 메시지에 대응하는 PC 표시 생각만 별도 협상으로 제공한다."""

from .extension_protocol import MAX_THOUGHT_BYTES


class CompanionThoughtsBridge:
    capabilities = ("message_thoughts_v1",)

    def __init__(self, owner):
        self.owner = owner
        self._display_enabled = None
        signal = getattr(owner, "chat_display_event", None)
        if signal is not None:
            signal.connect(self.changed)

    def settings_changed(self, enabled):
        enabled = bool(enabled)
        if self._display_enabled == enabled:
            return
        self._display_enabled = enabled
        self.changed()

    def changed(self, *_):
        adapter = getattr(self.owner, "_companion_adapter", None)
        if adapter is not None:
            try:
                adapter.publish_extension("thought_invalidated", {
                    "conversation_id": self.owner.chat_state.public_transcript.conversation_id,
                })
            except Exception:
                # 부가 표시 알림이 채팅과 음성 처리를 중단하지 않는다.
                pass

    def response(self, fields):
        state = self.owner.chat_state
        captured = state.public_transcript.capture()
        result = {key: fields[key] for key in ("query_id", "message_id", "conversation_revision")}
        result.update(conversation_id=captured.conversation_id, status="empty", text="")
        if (fields["conversation_id"], fields["conversation_revision"]) != (
            captured.conversation_id, captured.conversation_revision
        ):
            return {**result, "status": "stale"}
        enabled = self._display_enabled
        if enabled is None:
            enabled = self.owner._are_ene_thoughts_enabled()
        if not enabled:
            return result
        public = next((item for item in captured.messages if item.id == fields["message_id"]), None)
        displayed = state.pc_messages.get(fields["message_id"], {})
        if (public is None or public.role != "assistant" or displayed.get("role") != "assistant"
                or displayed.get("id") != public.id or displayed.get("local_only")):
            return result
        value = displayed.get("thought", "")
        if not isinstance(value, str) or not value.strip():
            return result
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError:
            return result
        if size > MAX_THOUGHT_BYTES:
            return {**result, "status": "too_large"}
        return {**result, "status": "available", "text": value}
