"""PC 전용 표시 정보와 ID 기반 명령을 공개 네트워크 DTO에서 분리한다."""

from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
from datetime import datetime, timezone
import json
from uuid import uuid4

from PyQt6.QtCore import QThread, pyqtSlot

from ...ai.chat_commands import (
    parse_diary_command,
    parse_note_command,
    parse_obs_command,
)
from ..companion.protocol import (
    MAX_PUBLIC_TEXT_BYTES,
    MAX_TEXT_BYTES,
    ProtocolError,
    integer_value,
    text_value,
    uuid_value,
)
from ..companion.transcript import TranscriptEvent
from ..companion.requests import AdmissionResult
from ..companion.adapter import AdapterError


@dataclass(repr=False)
class CompanionRetry:
    """재생성 작업이 소유하는 원본 표시와 PC 내부 상태의 복구 사본."""

    ref: object
    previous_ref: object
    user_id: str
    assistant_id: str
    messages: tuple
    conversation: list
    thoughts: list
    topics: list
    payload: dict
    assistant: object
    attachment_records: dict
    displayed: bool = False


class CompanionPCBridgeMixin:
    def _pc_chat_head(self):
        captured = self.chat_state.public_transcript.capture()
        return {
            "server_epoch": captured.server_epoch,
            "conversation_id": captured.conversation_id,
            "conversation_revision": captured.conversation_revision,
            "event_seq": captured.event_seq,
            "processing": captured.processing.to_dict(),
            "backend_pending": self.life_record_state.phase != "idle",
        }

    def _emit_pc_message(
        self,
        event,
        *,
        text=None,
        emotion=None,
        thought=None,
        attachments=None,
        local_only=False,
    ):
        message = event.message.to_dict()
        if emotion is not None:
            message["emotion"] = emotion
        if thought is not None:
            message["thought"] = thought
        if text is not None:
            message["text"] = text
        if attachments is not None:
            message["attachments"] = attachments
        if local_only:
            message["local_only"] = True
        previous = self.chat_state.pc_messages.get(message["id"], {})
        message = {**previous, **message}
        self.chat_state.pc_messages[message["id"]] = message
        self.chat_display_event.emit(
            json.dumps(
                {
                    **self._pc_chat_head(),
                    "op": event.op,
                    "message": message,
                },
                ensure_ascii=False,
            )
        )
        character = getattr(self, "_companion_character", None)
        if character is not None and emotion is not None and message.get("role") == "assistant":
            character.expression(emotion)

    def _emit_pc_processing(self, event):
        if isinstance(event, TranscriptEvent) and event.op == "processing":
            self.chat_display_event.emit(
                json.dumps(
                    {
                        "server_epoch": event.server_epoch,
                        "conversation_id": event.conversation_id,
                        "conversation_revision": event.conversation_revision,
                        "event_seq": event.event_seq,
                        "op": "processing",
                        "processing": event.processing.to_dict(),
                    }
                )
            )

    @pyqtSlot(result=str)
    def get_companion_chat_state(self):
        messages = []
        for message in self.chat_state.pc_messages.values():
            record = self._message_attachment_records.get(message["id"])
            if isinstance(record, dict):
                message = {
                    **message,
                    "attachments": deepcopy(record.get("attachments", [])),
                }
            messages.append(message)
        return json.dumps(
            {
                **self._pc_chat_head(),
                "messages": messages,
            },
            ensure_ascii=False,
        )

    @pyqtSlot(str, result=str)
    def submit_pc_chat(self, raw):
        """PC가 발급한 요청 UUID와 원래 초안만 공통 수락 함수에 전달한다."""
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ProtocolError()
            ref = replace(
                self._new_companion_request_ref(),
                server_epoch=uuid_value(payload.get("server_epoch")),
                conversation_id=uuid_value(payload.get("conversation_id")),
                request_id=uuid_value(payload.get("request_id")),
            )
            attachments = payload.get("attachments", [])
            if not isinstance(attachments, list) or not all(
                isinstance(item, dict) for item in attachments
            ):
                raise ProtocolError()
            text = text_value(payload.get("text"), max_bytes=MAX_PUBLIC_TEXT_BYTES)
            file_command = not attachments and any(
                parser(text)[0]
                for parser in (
                    parse_note_command,
                    parse_diary_command,
                    parse_obs_command,
                )
            )
            if file_command:
                result = self._submit_pc_file_command(ref, text)
            else:
                result = self.submit_chat_request(
                    text.strip() or ("첨부한 자료를 확인해 줘." if attachments else ""),
                    request_ref=ref,
                    request_type="attachments" if attachments else "text",
                    attachments=attachments,
                )
            return json.dumps(
                {**result.to_wire().to_dict(), "current": self._pc_chat_head()}
            )
        except (ValueError, TypeError):
            return json.dumps(
                {
                    "state": "rejected",
                    "code": "invalid_message",
                    "current": self._pc_chat_head(),
                }
            )

    def _submit_pc_file_command(self, ref, text):
        """파일 명령은 PC에서만 실행하고 사용자 원문은 공개 기록에 넣지 않는다."""

        def reject(code):
            return AdmissionResult(ref, "rejected", code=code)

        if not self._companion_request_is_current(ref):
            return reject("stale_session")
        body_hash = sha256(
            json.dumps(["file", text.strip()]).encode("utf-8")
        ).hexdigest()
        ledger = self.chat_state.request_ledger
        previous = ledger.lookup(ref.key)
        if previous is not None:
            return (
                self._companion_request_status(ref)
                if previous.body_hash == body_hash
                else reject("request_conflict")
            )
        if self.life_record_state.phase != "idle" or (
            self.worker and self.worker.isRunning()
        ):
            return reject("busy")
        if not self.llm_client:
            return reject("ai_unavailable")
        handlers = (
            (parse_note_command, self._handle_note_command),
            (parse_diary_command, self._handle_diary_command),
            (parse_obs_command, self._handle_obs_command),
        )
        handler = next(
            (
                callback
                for parser, callback in handlers
                if parser(text)[0] and parser(text)[1]
            ),
            None,
        )
        if handler is None:
            return reject("invalid_message")
        operation_id = self.life_record_state.try_begin_operation("normal_reply")
        if operation_id is None:
            return reject("busy")
        self.chat_state.operation_requests[operation_id] = ref
        self.chat_state.last_request_ref = ref
        ledger.reserve(ref.key, body_hash)
        message = {
            "id": str(uuid4()),
            "role": "user",
            "text": text,
            "request_id": ref.request_id,
            "displayed_at": datetime.now(timezone.utc).isoformat(),
            "local_only": True,
            "attachments": [],
        }
        self.chat_state.pc_messages[message["id"]] = message
        head = self._pc_chat_head()
        head.pop("event_seq", None)
        ledger.mark_accepted(ref.key, message["id"])
        self.chat_display_event.emit(
            json.dumps({**head, "op": "append", "message": message}, ensure_ascii=False)
        )
        self._emit_companion_request_status(ref)
        try:
            handler(text)
            if self.worker is None and self.life_record_state.matches_operation(
                operation_id
            ):
                self._finish_normal_operation(operation_id)
        except Exception:
            if self.life_record_state.matches_operation(operation_id):
                self.life_record_state.finish_operation(operation_id)
                self._companion_finish_operation(operation_id, code="request_failed")
        return self._companion_request_status(ref)

    @pyqtSlot(str, result=str)
    def edit_companion_message(self, raw):
        return self._retry_companion_message(raw, "edit")

    @pyqtSlot(str, result=str)
    def reroll_companion_message(self, raw):
        return self._retry_companion_message(raw, "reroll")

    def _display_companion_error(self, text, *, request_ref):
        """오류 안내를 재시도 대상에 연결하되 성공 답변이나 내부 기억으로 기록하지 않는다."""
        if not self._companion_request_is_current(request_ref):
            return False
        state = self.chat_state
        if request_ref.key not in state.public_user_ids:
            return False
        retry = state.retry_operations.get(int(request_ref.operation_id))
        if retry is not None:
            # 재생성 실패는 요청 상태 알림으로 안내하고 완료 처리에서 원본을 복원한다.
            # 별도 오류 말풍선을 만들면 다음 성공 시에도 화면에 남게 된다.
            return True
        if request_ref.key in state.failed_assistant_ids:
            return True
        event = state.public_transcript.publish_assistant(
            text, request_id=request_ref.request_id
        )
        if event is None:
            return True
        state.failed_assistant_ids[request_ref.key] = event.message.id
        self._emit_pc_message(event, emotion="confused", thought="")
        self.companion_event.emit(event)
        return True

    def _retry_companion_message(self, raw, kind):
        ref = self._new_companion_request_ref()
        try:
            command = json.loads(raw)
            if not isinstance(command, dict):
                raise ProtocolError()
            ref = replace(ref, server_epoch=uuid_value(command.get("server_epoch")),
                          conversation_id=uuid_value(command.get("conversation_id")),
                          request_id=uuid_value(command["request_id"]) if "request_id" in command else ref.request_id)
            result = self._submit_companion_retry(command, kind, request_ref=ref)
        except (ValueError, TypeError):
            result = AdmissionResult(ref, "rejected", code="invalid_message")
        return json.dumps({**result.to_wire().to_dict(), "current": self._pc_chat_head()})

    def _submit_companion_retry(self, command, kind, *, request_ref, admission_context=None):
        """인증·중복 판정 이후에만 기존 재생성/복구 경계로 진입한다."""
        if QThread.currentThread() != self.thread():
            raise RuntimeError("qt_thread_required")
        ref = request_ref

        def reject(code):
            return AdmissionResult(ref, "rejected", code=code)

        if ref.source == "mobile":
            adapter = getattr(self, "_companion_adapter", None)
            if adapter is None or admission_context is None:
                return reject("admission_blocked")
            try:
                adapter.validate_admission(admission_context)
            except AdapterError as error:
                return reject(error.code)
            if ref.registration_generation != admission_context.registration_generation:
                return reject("stale_registration")
        if not self._companion_request_is_current(ref):
            return reject("stale_session")
        state = self.chat_state
        try:
            uuid_value(ref.request_id)
            if kind not in {"edit", "reroll"}:
                return reject("unsupported_command")
            target_id = uuid_value(command.get("target_message_id"))
            expected_revision = integer_value(command.get("expected_revision"))
            edited = None
            if kind == "edit":
                edited = text_value(
                    command.get("text"),
                    max_bytes=MAX_TEXT_BYTES if ref.source == "mobile" else MAX_PUBLIC_TEXT_BYTES,
                    nonblank=True, limit_code="text_too_large",
                ).strip()
                if any(
                    parser(edited)[0]
                    for parser in (
                        parse_note_command,
                        parse_diary_command,
                        parse_obs_command,
                    )
                ):
                    return reject("unsupported_command")
        except ProtocolError as error:
            return reject(error.code)
        except (ValueError, TypeError):
            return reject("invalid_message")

        body_hash = sha256(json.dumps([kind, target_id, expected_revision, edited], ensure_ascii=False).encode("utf-8")).hexdigest()
        existing = state.request_ledger.lookup(ref.key)
        if existing is not None:
            return self._companion_request_status(ref) if existing.body_hash == body_hash else reject("request_conflict")
        actions = self._ensure_companion_chat_actions()
        captured, user_id, assistant_id, previous_ref = actions.targets()
        target = user_id if kind == "edit" else assistant_id
        if expected_revision != captured.conversation_revision or target_id != target or not user_id or not assistant_id:
            return reject("stale_target")
        available = actions.availability(mobile=ref.source == "mobile")
        if not available[kind + "_allowed"]:
            return reject(available[kind + "_reason"])
        operation_id = self.life_record_state.try_begin_operation("normal_reply")
        if operation_id is None:
            return reject("busy")
        retry = CompanionRetry(
            ref,
            previous_ref,
            user_id,
            assistant_id,
            captured.messages,
            list(self.conversation_buffer),
            deepcopy(self._ene_thought_context_buffer),
            deepcopy(self._loaded_topic_memory_context_buffer),
            deepcopy(self._last_request_payload),
            deepcopy(self._last_assistant_response),
            deepcopy(self._message_attachment_records),
        )
        state.retry_operations[operation_id] = retry
        state.operation_requests[operation_id] = ref
        state.public_user_ids[ref.key] = user_id
        state.request_ledger.reserve(ref.key, body_hash)
        state.request_ledger.mark_accepted(ref.key, user_id)
        try:
            if kind == "edit":
                # 동기 완료도 같은 순서를 지킨다. 준비/생성 실패 시 아래 복구 경계가 되돌린다.
                event = state.public_transcript.replace(
                    user_id, edited, expected_revision=expected_revision
                )
                self._emit_pc_message(event)
                self.companion_event.emit(event)
                self.edit_last_user_message(edited, _companion_ref=ref)
            else:
                self.reroll_last_response(_companion_ref=ref)
            worker_ref = getattr(self.worker, "companion_request_ref", None)
            if worker_ref is None or worker_ref.key != ref.key:
                if self.life_record_state.matches_operation(operation_id):
                    self.life_record_state.finish_operation(operation_id)
                    self._companion_finish_operation(operation_id, code="retry_failed")
        except Exception:
            if self.life_record_state.matches_operation(operation_id):
                self.life_record_state.finish_operation(operation_id)
                self._companion_finish_operation(operation_id, code="retry_failed")
        return self._companion_request_status(ref)

    def _publish_companion_retry_reply(self, request_ref, text, emotion, thought):
        if request_ref.operation_id is None:
            return False
        retry = self.chat_state.retry_operations.get(int(request_ref.operation_id))
        if retry is None or retry.ref.key != request_ref.key:
            return False
        if retry.displayed:
            return True
        transcript = self.chat_state.public_transcript
        event = transcript.replace(
            retry.assistant_id,
            text,
            expected_revision=transcript.capture().conversation_revision,
        )
        retry.displayed = True
        self.chat_state.public_assistant_ids[request_ref.key] = retry.assistant_id
        self.chat_state.failed_assistant_ids.pop(retry.previous_ref.key, None)
        self._emit_pc_message(event, emotion=emotion, thought=thought)
        self.companion_event.emit(event)
        return True

    def _finish_companion_retry(self, operation_id):
        state = self.chat_state
        retry = state.retry_operations.pop(operation_id, None)
        if (
            retry is None
            or retry.displayed
            or not self._companion_request_is_current(retry.ref)
        ):
            return
        self.conversation_buffer = retry.conversation
        self._ene_thought_context_buffer = retry.thoughts
        self._loaded_topic_memory_context_buffer = retry.topics
        self._last_request_payload = retry.payload
        self._last_assistant_response = retry.assistant
        self._message_attachment_records.clear()
        self._message_attachment_records.update(retry.attachment_records)
        state.last_request_ref = retry.previous_ref
        state.public_user_ids.pop(retry.ref.key, None)
        self._refresh_llm_history_from_visible_conversation()
        current = {
            message.id: message
            for message in state.public_transcript.capture().messages
        }
        for original in retry.messages:
            if original.id in current and current[original.id].text != original.text:
                event = state.public_transcript.replace(
                    original.id,
                    original.text,
                    expected_revision=state.public_transcript.capture().conversation_revision,
                )
                self._emit_pc_message(event)
                self.companion_event.emit(event)

    def _prepare_companion_retry_response(self, request_ref):
        if request_ref is None or request_ref.operation_id is None:
            return
        retry = self.chat_state.retry_operations.get(int(request_ref.operation_id))
        if retry is not None and retry.ref.key == request_ref.key:
            self._delete_tracked_promises_for_retry(payload=deepcopy(retry.payload))
            self._delete_tracked_proactive_for_retry(payload=deepcopy(retry.payload))
