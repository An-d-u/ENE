"""
WebBridge의 첨부파일 프리뷰, 전송, 삭제 로직.
"""
import json
from datetime import datetime

from PyQt6.QtCore import pyqtSlot

from ...ai.prompt_language import resolve_prompt_language
from ..attachment_session import (
    AttachmentSession,
    build_active_image_payload,
    build_attachment_preview_payload,
    compose_attachment_history_message,
    extract_attachment_message_id,
    find_attachment_conversation_index,
    normalize_attachment_runtime_state,
)
from ..chat_attachments import build_attachment_context_block, build_attachment_note, prepare_attachments
from .life_records import LifeRecordBridgeMixin, PreparedChatRequest


class AttachmentBridgeMixin:
    def _attachment_model_name(self) -> str:
        """첨부 토큰 추정에 사용할 현재 모델명을 가져온다."""
        if not self.llm_client:
            return ""
        return str(getattr(self.llm_client, "model_name", "") or "")

    def _get_attachment_session(self) -> AttachmentSession:
        """기존 테스트 더미와 실제 브릿지 모두에서 첨부 세션을 얻는다."""
        session = getattr(self, "_attachment_session", None)
        if not isinstance(session, AttachmentSession):
            session = AttachmentSession()
            if hasattr(self, "_pending_attachment_cache"):
                session.pending_attachment_cache = getattr(self, "_pending_attachment_cache") or {}
            if hasattr(self, "_session_attachment_documents"):
                session.session_attachment_documents = getattr(self, "_session_attachment_documents") or []
            if hasattr(self, "_message_attachment_records"):
                session.message_attachment_records = getattr(self, "_message_attachment_records") or {}
            self._attachment_session = session
        self._sync_attachment_session_aliases()
        return session

    def _sync_attachment_session_aliases(self) -> None:
        """기존 내부 속성명을 세션 상태 객체와 같은 참조로 유지한다."""
        session = getattr(self, "_attachment_session", None)
        if not isinstance(session, AttachmentSession):
            return
        self._pending_attachment_cache = session.pending_attachment_cache
        self._session_attachment_documents = session.session_attachment_documents
        self._message_attachment_records = session.message_attachment_records

    def _prepare_attachment_payload(self, attachments_data: list[dict]) -> list[dict]:
        """첨부 원본 페이로드를 분석 가능한 메타데이터로 변환한다."""
        return prepare_attachments(attachments_data, model_name=self._attachment_model_name())

    def _cache_prepared_attachments(self, prepared_attachments: list[dict]):
        """프리뷰 단계에서 준비한 첨부 메타데이터를 임시 캐시에 저장한다."""
        self._get_attachment_session().cache_prepared_attachments(prepared_attachments)
        self._sync_attachment_session_aliases()

    def _resolve_prepared_attachments(self, attachments_data: list[dict]) -> list[dict]:
        """캐시가 있으면 재사용하고, 없으면 즉시 분석한다."""
        return self._get_attachment_session().resolve_prepared_attachments(
            attachments_data,
            self._prepare_attachment_payload,
        )

    def _build_attachment_preview_payload(self, prepared_attachments: list[dict]) -> str:
        """프런트 프리뷰 갱신용 최소 메타데이터만 JSON으로 직렬화한다."""
        return build_attachment_preview_payload(prepared_attachments)

    def _extract_attachment_message_id(self, attachments_data: list[dict]) -> str:
        """프런트가 보낸 첨부 목록에서 메시지 ID를 추출한다."""
        return extract_attachment_message_id(attachments_data)

    def _normalize_attachment_runtime_state(self, prepared_attachments: list[dict]) -> list[dict]:
        """브리지 내부에서 삭제 상태까지 함께 관리할 첨부 런타임 상태를 만든다."""
        return normalize_attachment_runtime_state(prepared_attachments)

    def _build_active_image_payload(self, attachments: list[dict]) -> list[dict]:
        """현재 요청에 실제 이미지 입력으로 포함할 활성 이미지 목록을 만든다."""
        return build_active_image_payload(attachments)

    def _compose_attachment_history_message(self, message: str, attachments: list[dict]) -> str:
        """현재 첨부 상태를 반영한 사용자 대화 버퍼용 텍스트를 만든다."""
        language = resolve_prompt_language(settings_source=getattr(self, "settings", None))
        return compose_attachment_history_message(message, attachments, language=language)

    def _find_attachment_conversation_index(self, record: dict) -> int:
        """첨부 상태 레코드와 연결된 사용자 대화 버퍼 인덱스를 찾는다."""
        return find_attachment_conversation_index(self.conversation_buffer, record)

    def _upsert_session_documents(self, prepared_attachments: list[dict]):
        """전송이 완료된 문서 첨부를 현재 세션 참고 자료로 유지한다."""
        self._get_attachment_session().upsert_session_documents(prepared_attachments)
        self._sync_attachment_session_aliases()

    @pyqtSlot(str, str)
    def send_to_ai_with_images(self, message: str, images_json: str):
        """기존 이미지 전송 진입점을 일반 첨부 전송 경로로 연결한다."""
        capture_received_at = getattr(self, "_capture_life_received_at", None)
        received_at = (
            capture_received_at()
            if callable(capture_received_at)
            else datetime.now().astimezone().replace(microsecond=0)
        )
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if callable(accepts_input) and not accepts_input():
            print("[Bridge] request_rejected category=busy request_type=images")
            return
        try:
            images_data = json.loads(images_json)
        except Exception:
            images_data = []

        attachments = []
        for index, image in enumerate(images_data):
            attachments.append(
                {
                    "id": str((image or {}).get("id", "")).strip() or f"legacy-image-{index}",
                    "name": str((image or {}).get("name", "")).strip() or f"image-{index + 1}.png",
                    "type": str((image or {}).get("type", "")).strip() or "image/png",
                    "dataUrl": str((image or {}).get("dataUrl", "")).strip(),
                }
            )
        self.send_to_ai_with_attachments(
            message,
            json.dumps(attachments, ensure_ascii=False),
            _received_at=received_at,
            _busy_checked=True,
        )

    @pyqtSlot(str)
    def preview_attachments(self, attachments_json: str):
        """프런트가 첨부 미리보기 옆에 표시할 메타데이터를 계산한다."""
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if callable(accepts_input) and not accepts_input():
            print("[Bridge] request_rejected category=busy request_type=attachment_preview")
            return
        try:
            attachments_data = json.loads(attachments_json) if attachments_json else []
        except Exception as e:
            print(f"[Bridge] Failed to parse preview attachments: {e}")
            self.attachment_preview_ready.emit("[]")
            return

        prepared = self._prepare_attachment_payload(attachments_data)
        self._cache_prepared_attachments(prepared)
        self.attachment_preview_ready.emit(self._build_attachment_preview_payload(prepared))

    @pyqtSlot(str, str)
    def send_to_ai_with_attachments(
        self,
        message: str,
        attachments_json: str,
        *,
        _received_at: datetime | None = None,
        _busy_checked: bool = False,
    ):
        """JavaScript에서 호출: 이미지/문서 첨부를 포함한 메시지를 AI로 전송."""
        capture_received_at = getattr(self, "_capture_life_received_at", None)
        received_at = (
            _received_at
            if _received_at is not None
            else (
                capture_received_at()
                if callable(capture_received_at)
                else datetime.now().astimezone().replace(microsecond=0)
            )
        )
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if not _busy_checked and callable(accepts_input) and not accepts_input():
            print("[Bridge] request_rejected category=busy request_type=attachments")
            return
        print("[Bridge] Received message with attachments from JS")

        if not self.llm_client:
            print("[Bridge] LLM client not initialized")
            self.message_received.emit("AI가 초기화되지 않았어요.", "sad", "")
            return

        try:
            attachments_data = json.loads(attachments_json) if attachments_json else []
            print(f"[Bridge] Parsed {len(attachments_data)} attachments")
        except Exception as e:
            print(f"[Bridge] Failed to parse attachments: {e}")
            attachments_data = []

        effective_message = (message or "").strip() or "첨부한 자료를 확인해 줘."
        head_pat_count_before_message = 0
        if hasattr(self, "calendar_manager") and self.calendar_manager:
            getter = getattr(self.calendar_manager, "get_pending_head_pat_count", None)
            if callable(getter):
                head_pat_count_before_message = int(getter())
        prepare_request = getattr(self, "_prepare_chat_request", None)
        if callable(prepare_request):
            prepared = prepare_request(
                received_at=received_at,
                request_type="attachments",
                message=effective_message,
                attachments=attachments_data,
                head_pat_count_before_message=head_pat_count_before_message,
            )
        else:
            prepared = PreparedChatRequest(
                received_at=received_at,
                language=resolve_prompt_language(
                    settings_source=getattr(self, "settings", None)
                ),
                mood_snapshot=LifeRecordBridgeMixin._snapshot_life_mood(self),
                request_type="attachments",
                message=effective_message,
                attachments=tuple(attachments_data),
                head_pat_count_before_message=head_pat_count_before_message,
            )
        dispatch = getattr(self, "_dispatch_general_request", None)
        if callable(dispatch):
            dispatch(prepared)
            return
        cancel_proactive = getattr(
            self,
            "_cancel_pending_proactive_conversations_for_user_message",
            None,
        )
        if callable(cancel_proactive):
            cancel_proactive()
        mark_activity = getattr(self, "_mark_user_activity", None)
        if callable(mark_activity):
            mark_activity()
        AttachmentBridgeMixin._commit_prepared_attachment_request(self, prepared)

    def _commit_prepared_attachment_request(
        self,
        request,
        *,
        emit_pending_state: bool = True,
    ) -> None:
        """gate를 통과한 첨부 요청의 세션·대화·worker 변경을 한 번 적용한다."""
        legacy_direct_mixin = not hasattr(self, "life_record_state")
        attachments_data = request.attachment_copies()
        prepared_attachments = self._resolve_prepared_attachments(attachments_data)
        runtime_attachments = self._normalize_attachment_runtime_state(prepared_attachments)
        ready_attachments = [
            item for item in runtime_attachments
            if str(item.get("status", "ready")) == "ready"
        ]
        image_attachments = self._build_active_image_payload(runtime_attachments)
        timestamp = (
            self._now_timestamp()
            if legacy_direct_mixin
            else request.received_at.strftime("%Y-%m-%d %H:%M")
        )
        message_id = self._extract_attachment_message_id(attachments_data)
        if not message_id:
            message_id = f"attachment-message-{timestamp}"
        effective_message = request.message
        attachment_context = build_attachment_context_block(
            runtime_attachments,
            language=request.language,
        )
        if legacy_direct_mixin:
            prompt = self._build_general_chat_prompt(
                effective_message,
                attachment_context=attachment_context,
            )
            message_with_time = self._with_prompt_time(timestamp, prompt)
        else:
            prompt = self._build_general_chat_prompt(
                effective_message,
                attachment_context=attachment_context,
                language=request.language,
            )
            from .chat_flow import _prompt_time_header

            message_with_time = f"{_prompt_time_header(timestamp, request.language)}\n{prompt}"
        if legacy_direct_mixin:
            memory_search_inputs = self._build_memory_search_inputs(
                effective_message,
                timestamp,
            )
        else:
            memory_search_inputs = self._build_memory_search_inputs(
                effective_message,
                timestamp,
                language=request.language,
            )
        memory_search_text = memory_search_inputs["memory_search_text"]
        if hasattr(self, "calendar_manager") and self.calendar_manager:
            increment = getattr(self.calendar_manager, "increment_conversation_count", None)
            if callable(increment):
                increment()
            drain = getattr(self.calendar_manager, "drain_pending_head_pat_count", None)
            if callable(drain):
                drain()
        attachment_note = build_attachment_note(runtime_attachments, language=request.language)
        if legacy_direct_mixin:
            history_message = self._compose_attachment_history_message(
                effective_message,
                runtime_attachments,
            )
        else:
            history_message = compose_attachment_history_message(
                effective_message,
                runtime_attachments,
                language=request.language,
            )
        self._append_conversation("user", history_message, timestamp)
        record = {
            "message": effective_message,
            "timestamp": timestamp,
            "conversation_index": len(self.conversation_buffer) - 1,
            "attachments": runtime_attachments,
            "attachment_note": attachment_note,
            "attachment_context": attachment_context,
        }
        get_session = getattr(self, "_get_attachment_session", None)
        if callable(get_session):
            session = get_session()
            session.message_attachment_records[message_id] = record
            session.upsert_session_documents(runtime_attachments)
            self._sync_attachment_session_aliases()
        else:
            self._message_attachment_records[message_id] = record
        from .chat_flow import ChatFlowBridgeMixin

        mood_context = ChatFlowBridgeMixin._new_mood_event_context()
        mood_event_id = str(mood_context.get("event_id", ""))
        mood_occurred_at = str(mood_context.get("occurred_at_utc", ""))

        self._last_request_payload = {
            "type": "attachments" if ready_attachments else "text",
            "message": effective_message,
            "message_id": message_id,
            "message_with_time": message_with_time,
            "images": image_attachments,
            "attachment_note": attachment_note,
            "attachment_context": attachment_context,
            "memory_search_text": memory_search_text,
            "latest_user_message": memory_search_inputs["latest_user_message"],
            "recent_memory_context": memory_search_inputs["recent_context_text"],
            "head_pat_count_before_message": request.head_pat_count_before_message,
            "include_life_record_context": True,
            "mood_event_id": mood_event_id,
            "mood_occurred_at": mood_occurred_at,
            "mood_finalized": False,
        }
        self._is_rerolling = False

        worker_kwargs = {
            "memory_search_text": memory_search_text,
            "latest_user_message": memory_search_inputs["latest_user_message"],
            "recent_memory_context": memory_search_inputs["recent_context_text"],
            "head_pat_count_before_message": request.head_pat_count_before_message,
            "include_life_record_context": True,
            "prior_token_usage": (
                getattr(getattr(self, "life_record_state", None), "prior_token_usage", None)
                or request.prior_token_usage
            ),
            "mood_event_id": mood_event_id,
            "mood_occurred_at": mood_occurred_at,
        }
        if not emit_pending_state:
            worker_kwargs["emit_pending_state"] = False
        self._start_ai_worker(
            message_with_time,
            image_attachments,
            **worker_kwargs,
        )
        print(
            f"[Bridge] Worker thread started with "
            f"{len(image_attachments)} images and "
            f"{len([item for item in ready_attachments if item.get('category') == 'document'])} documents"
        )

    @pyqtSlot(str, str)
    def delete_message_attachment(self, message_id: str, attachment_id: str):
        """전송된 사용자 메시지 안의 이미지 첨부 하나를 삭제 상태로 바꾼다."""
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if callable(accepts_input) and not accepts_input():
            print("[Bridge] request_rejected category=busy request_type=attachment_delete")
            return
        normalized_message_id = str(message_id or "").strip()
        normalized_attachment_id = str(attachment_id or "").strip()
        if not normalized_message_id or not normalized_attachment_id:
            return

        record = self._message_attachment_records.get(normalized_message_id)
        if not isinstance(record, dict):
            return

        attachments = record.get("attachments") or []
        changed = False
        for item in attachments:
            if str(item.get("id", "")).strip() != normalized_attachment_id:
                continue
            if str(item.get("category", "")) != "image":
                return
            if bool(item.get("deleted")):
                return
            item["deleted"] = True
            item["dataUrl"] = ""
            changed = True
            break

        if not changed:
            return

        language = resolve_prompt_language(settings_source=getattr(self, "settings", None))
        attachment_note = build_attachment_note(attachments, language=language)
        attachment_context = build_attachment_context_block(
            attachments,
            language=language,
        )
        history_message = self._compose_attachment_history_message(record.get("message", ""), attachments)
        conversation_index = self._find_attachment_conversation_index(record)
        if 0 <= conversation_index < len(self.conversation_buffer):
            role, _, timestamp = self.conversation_buffer[conversation_index]
            self.conversation_buffer[conversation_index] = (role, history_message, timestamp)
            record["conversation_index"] = conversation_index
        record["attachment_note"] = attachment_note
        record["attachment_context"] = attachment_context

        if (
            self._last_request_payload
            and str(self._last_request_payload.get("message_id", "")).strip() == normalized_message_id
        ):
            self._last_request_payload["images"] = self._build_active_image_payload(attachments)
            self._last_request_payload["attachment_note"] = attachment_note
            self._last_request_payload["attachment_context"] = attachment_context

        self._refresh_llm_history_from_visible_conversation()
