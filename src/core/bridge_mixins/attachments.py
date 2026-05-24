"""
WebBridge의 첨부파일 프리뷰, 전송, 삭제 로직.
"""
import json

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

    def send_to_ai_with_images(self, message: str, images_json: str):
        """기존 이미지 전송 진입점을 일반 첨부 전송 경로로 연결한다."""
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
        self.send_to_ai_with_attachments(message, json.dumps(attachments, ensure_ascii=False))

    @pyqtSlot(str)
    def preview_attachments(self, attachments_json: str):
        """프런트가 첨부 미리보기 옆에 표시할 메타데이터를 계산한다."""
        try:
            attachments_data = json.loads(attachments_json) if attachments_json else []
        except Exception as e:
            print(f"[Bridge] Failed to parse preview attachments: {e}")
            self.attachment_preview_ready.emit("[]")
            return

        prepared = self._prepare_attachment_payload(attachments_data)
        self._cache_prepared_attachments(prepared)
        self.attachment_preview_ready.emit(self._build_attachment_preview_payload(prepared))

    def send_to_ai_with_attachments(self, message: str, attachments_json: str):
        """JavaScript에서 호출: 이미지/문서 첨부를 포함한 메시지를 AI로 전송."""
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

        prepared_attachments = self._resolve_prepared_attachments(attachments_data)
        runtime_attachments = self._normalize_attachment_runtime_state(prepared_attachments)
        ready_attachments = [
            item for item in runtime_attachments
            if str(item.get("status", "ready")) == "ready"
        ]
        image_attachments = self._build_active_image_payload(runtime_attachments)
        timestamp = self._now_timestamp()
        message_id = self._extract_attachment_message_id(attachments_data)
        if not message_id:
            message_id = f"attachment-message-{timestamp}"
        effective_message = (message or "").strip() or "첨부한 자료를 확인해 줘."
        attachment_context = build_attachment_context_block(runtime_attachments, language=self._prompt_language())
        prompt = self._build_general_chat_prompt(effective_message, attachment_context=attachment_context)
        message_with_time = self._with_prompt_time(timestamp, prompt)
        memory_search_inputs = self._build_memory_search_inputs(effective_message, timestamp)
        memory_search_text = memory_search_inputs["memory_search_text"]
        head_pat_count_before_message = 0
        if hasattr(self, "calendar_manager") and self.calendar_manager:
            head_pat_count_before_message = int(self.calendar_manager.drain_pending_head_pat_count())

        self._mark_user_activity()
        attachment_note = build_attachment_note(runtime_attachments, language=self._prompt_language())
        history_message = self._compose_attachment_history_message(effective_message, runtime_attachments)
        self._append_conversation("user", history_message, timestamp)
        self._message_attachment_records[message_id] = {
            "message": effective_message,
            "timestamp": timestamp,
            "conversation_index": len(self.conversation_buffer) - 1,
            "attachments": runtime_attachments,
            "attachment_note": attachment_note,
            "attachment_context": attachment_context,
        }
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(effective_message, image_count=len(image_attachments))
            self._emit_mood_changed(snapshot)

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
            "head_pat_count_before_message": head_pat_count_before_message,
        }
        self._is_rerolling = False

        self._start_ai_worker(
            message_with_time,
            image_attachments,
            memory_search_text=memory_search_text,
            latest_user_message=memory_search_inputs["latest_user_message"],
            recent_memory_context=memory_search_inputs["recent_context_text"],
            head_pat_count_before_message=head_pat_count_before_message,
        )
        print(
            f"[Bridge] Worker thread started with "
            f"{len(image_attachments)} images and "
            f"{len([item for item in ready_attachments if item.get('category') == 'document'])} documents"
        )

    @pyqtSlot(str, str)
    def delete_message_attachment(self, message_id: str, attachment_id: str):
        """전송된 사용자 메시지 안의 이미지 첨부 하나를 삭제 상태로 바꾼다."""
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
