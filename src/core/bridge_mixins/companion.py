"""내부 AI 문맥과 분리된 현재 대화의 공개 경계를 관리한다."""

from dataclasses import replace
from uuid import uuid4

from ..companion.requests import RequestRef


class CompanionBridgeMixin:
    """Qt 스레드에서 요청 소유권과 공개 메시지 식별자를 유지한다."""

    def _new_companion_request_ref(self, source="pc") -> RequestRef:
        transcript = self.chat_state.public_transcript
        return RequestRef(
            registration_generation=0,
            server_epoch=transcript.server_epoch,
            conversation_id=transcript.conversation_id,
            request_id=str(uuid4()),
            source=source,
        )

    def _companion_request_is_current(self, request_ref) -> bool:
        transcript = self.chat_state.public_transcript
        return isinstance(request_ref, RequestRef) and (
            request_ref.server_epoch == transcript.server_epoch
            and request_ref.conversation_id == transcript.conversation_id
        )

    def _bind_companion_worker(self, worker, operation_id, request_ref=None, *, file_result=False):
        """완료 콜백이 이미 캡처한 worker에 불변 요청 사본을 귀속시킨다."""
        request_ref = request_ref or self._new_companion_request_ref(
            "pc" if file_result else "automatic"
        )
        worker.companion_request_ref = replace(
            request_ref, operation_id=str(operation_id)
        )
        worker.companion_file_result = file_result

    def _publish_companion_user(self, request):
        request_ref = request.request_ref
        if not self._companion_request_is_current(request_ref):
            return None
        state = self.chat_state
        if request_ref.key in state.public_user_ids:
            return state.public_user_ids[request_ref.key]
        event = state.public_transcript.append_user(
            request.message,
            request_id=request_ref.request_id,
            attachment_unsupported=bool(request.attachments),
        )
        state.public_user_ids[request_ref.key] = event.message.id
        self.companion_event.emit(event)
        return event.message.id

    def _display_companion_response(
        self, text, emotion, thought, *, request_ref=None, file_result=False
    ):
        """명시적으로 공개한 답변만 기록하고 기존 PC 표시를 유지한다."""
        if request_ref is not None:
            if not self._companion_request_is_current(request_ref):
                return False
            event = self.chat_state.public_transcript.publish_assistant(
                "PC 전용 파일 작업 결과입니다. PC에서 확인해 주세요." if file_result else text,
                request_id=request_ref.request_id,
            )
            if event is None:
                return False
            self.chat_state.public_assistant_ids[request_ref.key] = event.message.id
            self.companion_event.emit(event)
        self.message_received.emit(text, emotion, thought)
        return True

    def _display_companion_file_result(self, text, emotion):
        self._display_companion_response(
            text, emotion, "", request_ref=self._new_companion_request_ref(),
            file_result=True,
        )

    def _reset_companion_conversation(self):
        """명시적인 초기화만 공개 기록과 요청 식별자를 폐기한다."""
        state = self.chat_state
        state.public_transcript.reset()
        state.request_ledger.reset()
        state.public_user_ids.clear()
        state.public_assistant_ids.clear()
