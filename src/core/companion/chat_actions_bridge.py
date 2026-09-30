"""마지막 공개 쌍의 판정과 원문 없는 조작 상태를 Qt에서 소유한다."""

from .protocol import MAX_TEXT_BYTES


class CompanionChatActionsBridge:
    capabilities = ("chat_actions_v1",)

    def __init__(self, owner):
        self.owner = owner
        self._sequence = 0

    def targets(self):
        owner, state = self.owner, self.owner.chat_state
        captured = state.public_transcript.capture()
        ref = state.last_request_ref
        if ref is None or ref.source not in {"pc", "mobile"}:
            return captured, None, None, ref
        user_id = state.public_user_ids.get(ref.key)
        assistant_id = state.public_assistant_ids.get(ref.key) or state.failed_assistant_ids.get(ref.key)
        for retry in state.retry_operations.values():
            if retry.ref.key == ref.key:
                user_id, assistant_id = retry.user_id, retry.assistant_id
                break
        latest = captured.messages[-2:]
        if len(latest) != 2 or [(item.id, item.role) for item in latest] != [(user_id, "user"), (assistant_id, "assistant")]:
            return captured, None, None, ref
        return captured, user_id, assistant_id, ref

    def availability(self, *, mobile=True):
        owner = self.owner
        captured, user_id, assistant_id, _ = self.targets()
        reason = "ready"
        if not user_id or not assistant_id:
            reason = "no_target"
        elif owner.life_record_state.phase != "idle" or (owner.worker and owner.worker.isRunning()):
            reason = "busy"
        elif not owner.llm_client or not isinstance(owner._last_request_payload, dict):
            reason = "ai_unavailable"
        edit_reason = reason
        if reason == "ready" and mobile and len(captured.messages[-2].text.encode("utf-8")) > MAX_TEXT_BYTES:
            edit_reason = "text_too_large"
        return {
            "conversation_id": captured.conversation_id,
            "conversation_revision": captured.conversation_revision,
            "event_seq": captured.event_seq,
            "user_message_id": user_id, "assistant_message_id": assistant_id,
            "edit_allowed": edit_reason == "ready", "edit_reason": edit_reason,
            "reroll_allowed": reason == "ready", "reroll_reason": reason,
        }

    def snapshot(self, query_id=None):
        self._sequence += 1
        return {**self.availability(), "state_seq": self._sequence,
                "query_id": query_id, "snapshot_id": None}
