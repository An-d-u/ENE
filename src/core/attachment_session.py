"""
채팅 첨부파일의 프리뷰 캐시와 세션 상태를 관리한다.
"""
import json
from collections.abc import Callable

from ..ai.prompt_language import resolve_prompt_language
from .chat_attachments import build_attachment_note


class AttachmentSession:
    """브릿지에서 쓰는 첨부파일 런타임 상태 묶음."""

    def __init__(self):
        self.pending_attachment_cache: dict[str, dict] = {}
        self.session_attachment_documents: list[dict] = []
        self.message_attachment_records: dict[str, dict] = {}

    def clear(self) -> None:
        """현재 채팅 세션에 묶인 첨부 상태를 초기화한다."""
        self.pending_attachment_cache = {}
        self.session_attachment_documents = []
        self.message_attachment_records = {}

    def cache_prepared_attachments(self, prepared_attachments: list[dict]) -> None:
        """프리뷰 단계에서 준비한 첨부 메타데이터를 임시 캐시에 저장한다."""
        for item in prepared_attachments or []:
            attachment_id = str((item or {}).get("id", "")).strip()
            if attachment_id:
                self.pending_attachment_cache[attachment_id] = item

    def resolve_prepared_attachments(
        self,
        attachments_data: list[dict],
        prepare: Callable[[list[dict]], list[dict]],
    ) -> list[dict]:
        """캐시가 있으면 재사용하고, 없으면 전달받은 준비 함수로 분석한다."""
        items = list(attachments_data or [])
        if not items:
            return []

        if any(not str((item or {}).get("id", "")).strip() for item in items):
            prepared = prepare(items)
            self.cache_prepared_attachments(prepared)
            return prepared

        missing: list[dict] = []
        prepared_by_id: dict[str, dict] = {}

        for raw in items:
            attachment_id = str((raw or {}).get("id", "")).strip()
            cached = self.pending_attachment_cache.get(attachment_id)
            if cached and cached.get("dataUrl") == raw.get("dataUrl"):
                prepared_by_id[attachment_id] = cached
            else:
                missing.append(raw)

        if missing:
            fresh = prepare(missing)
            self.cache_prepared_attachments(fresh)
            for item in fresh:
                attachment_id = str((item or {}).get("id", "")).strip()
                if attachment_id:
                    prepared_by_id[attachment_id] = item

        resolved: list[dict] = []
        for raw in items:
            attachment_id = str((raw or {}).get("id", "")).strip()
            item = prepared_by_id.get(attachment_id)
            if item:
                resolved.append(item)
        return resolved

    def upsert_session_documents(self, prepared_attachments: list[dict]) -> None:
        """전송이 완료된 문서 첨부를 현재 세션 참고 자료로 유지한다."""
        for item in prepared_attachments or []:
            if str(item.get("category", "")) != "document":
                continue
            if str(item.get("status", "ready")) != "ready":
                continue

            normalized_name = str(item.get("name", "")).strip().casefold()
            if not normalized_name:
                continue

            document_entry = {
                "name": item.get("name", ""),
                "type": item.get("type", ""),
                "category": "document",
                "tokenEstimate": int(item.get("tokenEstimate", 0) or 0),
                "extractedText": item.get("extractedText", ""),
                "_name_key": normalized_name,
            }

            replaced = False
            for index, existing in enumerate(self.session_attachment_documents):
                if str(existing.get("_name_key", "")) == normalized_name:
                    self.session_attachment_documents[index] = document_entry
                    replaced = True
                    break
            if not replaced:
                self.session_attachment_documents.append(document_entry)


def build_attachment_preview_payload(prepared_attachments: list[dict]) -> str:
    """프런트 프리뷰 갱신용 최소 메타데이터만 JSON으로 직렬화한다."""
    payload = []
    for item in prepared_attachments or []:
        payload.append(
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "type": item.get("type", ""),
                "category": item.get("category", ""),
                "tokenEstimate": int(item.get("tokenEstimate", 0) or 0),
                "width": int(item.get("width", 0) or 0),
                "height": int(item.get("height", 0) or 0),
                "status": item.get("status", "ready"),
                "error": item.get("error", ""),
            }
        )
    return json.dumps(payload, ensure_ascii=False)


def extract_attachment_message_id(attachments_data: list[dict]) -> str:
    """프런트가 보낸 첨부 목록에서 메시지 ID를 추출한다."""
    for item in attachments_data or []:
        message_id = str((item or {}).get("messageId", "")).strip()
        if message_id:
            return message_id
    return ""


def normalize_attachment_runtime_state(prepared_attachments: list[dict]) -> list[dict]:
    """삭제 상태까지 함께 관리할 첨부 런타임 상태를 만든다."""
    normalized: list[dict] = []
    for item in prepared_attachments or []:
        normalized_item = dict(item)
        if str(normalized_item.get("category", "")) == "image":
            normalized_item["deleted"] = bool(normalized_item.get("deleted", False))
        else:
            normalized_item["deleted"] = False
        normalized.append(normalized_item)
    return normalized


def build_active_image_payload(attachments: list[dict]) -> list[dict]:
    """현재 요청에 실제 이미지 입력으로 포함할 활성 이미지 목록을 만든다."""
    payload: list[dict] = []
    for item in attachments or []:
        if str(item.get("status", "ready")) != "ready":
            continue
        if str(item.get("category", "")) != "image":
            continue
        if bool(item.get("deleted")):
            continue
        payload.append(
            {
                "id": item.get("id", ""),
                "dataUrl": item.get("dataUrl", ""),
                "name": item.get("name", ""),
                "type": item.get("type", "image/png"),
            }
        )
    return payload


def _attachment_history_fallback(language: str | None = None) -> str:
    return {
        "ko": "(첨부)",
        "en": "(attachment)",
        "ja": "(添付)",
    }[resolve_prompt_language(language)]


def compose_attachment_history_message(message: str, attachments: list[dict], language: str | None = None) -> str:
    """현재 첨부 상태를 반영한 사용자 대화 버퍼용 텍스트를 만든다."""
    return ((message or "").strip() or _attachment_history_fallback(language)) + build_attachment_note(
        attachments,
        language=language,
    )


def find_attachment_conversation_index(conversation_buffer: list, record: dict) -> int:
    """첨부 상태 레코드와 연결된 사용자 대화 버퍼 인덱스를 찾는다."""
    try:
        stored_index = int(record.get("conversation_index", -1))
    except Exception:
        stored_index = -1

    if 0 <= stored_index < len(conversation_buffer):
        entry = conversation_buffer[stored_index]
        if len(entry) >= 3 and entry[0] == "user":
            return stored_index

    timestamp = str(record.get("timestamp", "")).strip()
    if timestamp:
        for index in range(len(conversation_buffer) - 1, -1, -1):
            role, _, entry_timestamp = conversation_buffer[index]
            if role == "user" and str(entry_timestamp or "").strip() == timestamp:
                return index

    return -1
