"""내부 AI 문맥과 분리된 현재 대화의 공개 경계를 관리한다."""

from dataclasses import replace
from hashlib import sha256
import json
from uuid import uuid4

from PyQt6.QtCore import QThread, pyqtSlot

from ...ai.chat_commands import (
    parse_diary_command,
    parse_note_command,
    parse_obs_command,
)
from ..companion.adapter import AdapterError, ConversationHead
from ..companion.protocol import (
    MAX_PUBLIC_TEXT_BYTES,
    MAX_TEXT_BYTES,
    ProtocolError,
    text_value,
    uuid_value,
)
from ..companion.requests import AdmissionResult, RequestRef
from ..companion.session import SyncCapture


class CompanionBridgeMixin:
    """Qt 스레드에서 요청 소유권과 공개 메시지 식별자를 유지한다."""

    def head(self):
        transcript = self.chat_state.public_transcript
        return ConversationHead(transcript.server_epoch, transcript.conversation_id)

    def bind_companion_adapter(self, adapter):
        self._companion_adapter = adapter
        if not hasattr(self, "_companion_audio"):
            from ..companion.audio_bridge import CompanionAudioBridge

            self._companion_audio = CompanionAudioBridge(self)
        if hasattr(self, "character_catalog_requested"):
            self._ensure_companion_character()

    def _ensure_companion_character(self):
        if not hasattr(self, "_companion_character"):
            from ..companion.character_bridge import CompanionCharacterBridge

            self._companion_character = CompanionCharacterBridge(self)
        return self._companion_character

    def _companion_prepare_character(self, path, emotions, settings, parameters):
        return self._ensure_companion_character().select(path, emotions, settings, parameters)

    @pyqtSlot(str)
    def report_companion_character_catalog(self, value):
        character = getattr(self, "_companion_character", None)
        if character is None or not isinstance(value, str) or len(value) > 65536:
            return
        try:
            if len(value.encode("utf-8")) <= 65536:
                character.catalog(json.loads(value))
        except (ValueError, UnicodeError, RecursionError):
            pass

    @pyqtSlot()
    def request_companion_character_catalog(self):
        character = getattr(self, "_companion_character", None)
        if character is not None:
            character.request_catalog()

    def submit_extension(self, context, message):
        from ..companion.extension_protocol import ExtensionContext, validate_extension

        self._companion_adapter.validate_admission(context)
        head = self.head()
        validate_extension(
            message,
            ExtensionContext(
                context.registration_generation,
                head.server_epoch,
                context.connection_generation,
                head.conversation_id,
            ),
            ("audio_pcm_v1", "character_v1"),
            direction="from_phone",
        )
        if message.type == "character_snapshot_request":
            character = getattr(self, "_companion_character", None)
            if character is not None:
                character.changed("requested")
            return None
        return self._companion_audio.receive(context, message)

    def _companion_connection_closed(self):
        audio = getattr(self, "_companion_audio", None)
        if audio is not None:
            audio.disconnected()

    def _companion_tts_settings_changed(self):
        audio = getattr(self, "_companion_audio", None)
        if audio is not None:
            audio.settings_changed()

    def capture(self, registration_generation, pending=()):
        transcript = self.chat_state.public_transcript
        statuses = []
        for request_id in pending:
            ref = RequestRef(
                registration_generation,
                transcript.server_epoch,
                transcript.conversation_id,
                uuid_value(request_id),
                "mobile",
            )
            statuses.append(self._companion_request_status(ref).to_wire())
        return SyncCapture(transcript.capture(), tuple(statuses))

    def submit(self, context, message):
        return self.submit_mobile_text(context, message).to_wire()

    def submit_mobile_text(self, context, message):
        fields = message.fields
        ref = RequestRef(
            context.registration_generation,
            fields["server_epoch"],
            fields["conversation_id"],
            fields["request_id"],
            "mobile",
        )
        return self.submit_chat_request(
            fields["text"], request_ref=ref, context=context
        )

    def submit_chat_request(
        self,
        message,
        *,
        request_ref=None,
        context=None,
        received_at=None,
        request_type="text",
        attachments=(),
        head_pat_count_before_message=None,
    ):
        """중복 확인과 기존 생활 기록 gate 진입을 같은 Qt 호출에서 수행한다."""
        if QThread.currentThread() != self.thread():
            raise RuntimeError("qt_thread_required")
        ref = request_ref or self._new_companion_request_ref()

        def reject(code):
            return AdmissionResult(ref, "rejected", code=code)

        if ref.source == "mobile":
            adapter = getattr(self, "_companion_adapter", None)
            if adapter is None or context is None:
                return reject("admission_blocked")
            try:
                adapter.validate_admission(context)
            except AdapterError as error:
                return reject(error.code)
            if ref.registration_generation != context.registration_generation:
                return reject("stale_registration")
        if not self._companion_request_is_current(ref):
            return reject("stale_session")
        try:
            uuid_value(ref.request_id)
            message = text_value(
                message,
                max_bytes=MAX_TEXT_BYTES
                if ref.source == "mobile"
                else MAX_PUBLIC_TEXT_BYTES,
                nonblank=True,
                limit_code="text_too_large",
            ).strip()
        except ProtocolError as error:
            return reject(error.code)
        if request_type not in {"text", "attachments"}:
            return reject("unsupported_command")
        if ref.source == "mobile" and (
            request_type != "text"
            or attachments
            or any(
                parser(message)[0]
                for parser in (
                    parse_note_command,
                    parse_diary_command,
                    parse_obs_command,
                )
            )
        ):
            return reject("unsupported_command")
        body_hash = sha256(
            json.dumps(
                [request_type, message, attachments],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        ledger = self.chat_state.request_ledger
        existing = ledger.lookup(ref.key)
        if existing is not None:
            return (
                reject("request_conflict")
                if existing.body_hash != body_hash
                else self._companion_request_status(ref)
            )
        if self.life_record_state.phase != "idle" or (
            self.worker and self.worker.isRunning()
        ):
            return reject("busy")
        if not self.llm_client:
            return reject("ai_unavailable")
        ledger.reserve(ref.key, body_hash)
        try:
            if head_pat_count_before_message is None:
                getter = getattr(
                    getattr(self, "calendar_manager", None),
                    "get_pending_head_pat_count",
                    None,
                )
                head_pat_count_before_message = int(getter()) if callable(getter) else 0
            prepared = self._prepare_chat_request(
                received_at=received_at or self._capture_life_received_at(),
                request_type=request_type,
                message=message,
                attachments=attachments,
                head_pat_count_before_message=head_pat_count_before_message,
                request_ref=ref,
            )
            if not self._dispatch_general_request(prepared):
                ledger.discard_reservation(ref.key)
                return reject("busy")
        except Exception:
            state = self.life_record_state
            owned_operation = next(
                (
                    operation_id
                    for operation_id, owned in self.chat_state.operation_requests.items()
                    if owned.key == ref.key
                ),
                None,
            )
            running = any(
                callable(getattr(worker, "isRunning", None)) and worker.isRunning()
                for worker in (self.worker, state.worker)
            )
            if owned_operation is not None and not running:
                state.finish_operation(owned_operation)
                self._companion_finish_operation(owned_operation, code="request_failed")
                if state.phase == "idle":
                    self._reset_pending_ui_state()
            else:
                self._companion_finish_request(ref, succeeded=False)
        return self._companion_request_status(ref)

    def _companion_request_status(self, ref):
        record = self.chat_state.request_ledger.lookup(ref.key)
        if record is None:
            return AdmissionResult(ref, "unknown")
        return AdmissionResult(ref, record.state, record.message_id, record.code)

    def _emit_companion_request_status(self, ref):
        result = self._companion_request_status(ref)
        self.companion_admission_result.emit(result)
        self.chat_admission_result.emit(json.dumps(result.to_wire().to_dict()))
        self.companion_event.emit(result.to_wire())

    def _companion_begin_request(self, request, operation_id, phase):
        ref = request.request_ref
        if not self._companion_request_is_current(ref):
            return
        self.chat_state.operation_requests[operation_id] = replace(
            ref, operation_id=str(operation_id)
        )
        event = self.chat_state.public_transcript.set_processing(phase, ref.request_id)
        if event is not None:
            self.companion_event.emit(event)

    def _companion_finish_request(self, ref, *, succeeded, code=None):
        ledger = self.chat_state.request_ledger
        record = ledger.lookup(ref.key)
        if record is None or record.state not in {"reserved", "accepted"}:
            return
        ledger.finish(ref.key, succeeded=succeeded, code=code)
        self._emit_companion_request_status(ref)

    def _companion_finish_operation(self, operation_id, *, code=None):
        finish_retry = getattr(self, "_finish_companion_retry", None)
        if callable(finish_retry):
            finish_retry(operation_id)
        ref = self.chat_state.operation_requests.pop(operation_id, None)
        if ref is None or not self._companion_request_is_current(ref):
            return
        succeeded = code is None and ref.key in self.chat_state.public_assistant_ids
        event = self.chat_state.public_transcript.set_processing("idle")
        if event is not None:
            self.companion_event.emit(event)
        self._companion_finish_request(ref, succeeded=succeeded, code=code)

    def _companion_begin_shutdown(self):
        audio = getattr(self, "_companion_audio", None)
        if audio is not None:
            audio.cancel("shutdown", release=False)
        for operation_id in tuple(self.chat_state.operation_requests):
            self._companion_finish_operation(operation_id, code="shutdown")

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
            and self.life_record_state.phase != "shutting_down"
        )

    def _bind_companion_worker(
        self, worker, operation_id, request_ref=None, *, file_result=False
    ):
        """완료 콜백이 이미 캡처한 worker에 불변 요청 사본을 귀속시킨다."""
        if request_ref is None and file_result:
            request_ref = self.chat_state.operation_requests.get(operation_id)
        request_ref = request_ref or self._new_companion_request_ref(
            "pc" if file_result else "automatic"
        )
        worker.companion_request_ref = replace(
            request_ref, operation_id=str(operation_id)
        )
        worker.companion_file_result = file_result
        self.chat_state.last_request_ref = worker.companion_request_ref
        self.chat_state.operation_requests[operation_id] = worker.companion_request_ref
        event = self.chat_state.public_transcript.set_processing(
            "responding", request_ref.request_id
        )
        if event is not None:
            self.companion_event.emit(event)

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
        self._emit_pc_message(event, attachments=request.attachment_copies())
        self.companion_event.emit(event)
        if state.request_ledger.lookup(request_ref.key) is not None:
            state.request_ledger.mark_accepted(request_ref.key, event.message.id)
            self._emit_companion_request_status(request_ref)
        return event.message.id

    def _display_companion_response(
        self, text, emotion, thought, *, request_ref=None, file_result=False
    ):
        """명시적으로 공개한 답변만 기록하고 기존 PC 표시를 유지한다."""
        if request_ref is not None:
            if not self._companion_request_is_current(request_ref):
                return False
            publish_retry = getattr(self, "_publish_companion_retry_reply", None)
            if callable(publish_retry) and publish_retry(request_ref, text, emotion, thought):
                return True
            event = self.chat_state.public_transcript.publish_assistant(
                "PC 전용 파일 작업 결과입니다. PC에서 확인해 주세요."
                if file_result
                else text,
                request_id=request_ref.request_id,
            )
            if event is None:
                return False
            self.chat_state.public_assistant_ids[request_ref.key] = event.message.id
            self._emit_pc_message(event, text=text, emotion=emotion, thought=thought, local_only=file_result)
            self.companion_event.emit(event)
        else:
            self.message_received.emit(text, emotion, thought)
        return True

    def _display_companion_file_result(self, text, emotion):
        request_ref = self.chat_state.operation_requests.get(self.life_record_state.operation_id)
        if self.life_record_state.phase != "normal_reply":
            request_ref = None
        self._display_companion_response(
            text,
            emotion,
            "",
            request_ref=request_ref or self._new_companion_request_ref(),
            file_result=True,
        )

    def _reset_companion_conversation(self):
        """명시적인 초기화만 공개 기록과 요청 식별자를 폐기한다."""
        audio = getattr(self, "_companion_audio", None)
        if audio is not None:
            audio.cancel("conversation_reset", release=False)
        state = self.chat_state
        state.public_transcript.reset()
        state.request_ledger.reset()
        state.public_user_ids.clear()
        state.public_assistant_ids.clear()
        state.operation_requests.clear()
        state.pc_messages.clear()
        state.last_request_ref = None
        state.retry_operations.clear()
        self.chat_display_event.emit(json.dumps({**self._pc_chat_head(), "op": "reset", "messages": []}))
        self.companion_event.emit({
            "type": "resync_required", "protocol_version": 1,
            "server_epoch": state.public_transcript.server_epoch,
            "conversation_id": state.public_transcript.conversation_id, "reason": "reset",
        })
