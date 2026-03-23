"""
채팅 첨부 파일 전처리 유틸리티.
이미지/문서 첨부를 분석하고 세션 프롬프트에 넣을 컨텍스트를 만든다.
"""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Iterable

import tiktoken
from PIL import Image


지원_문서_확장자 = {".txt", ".md", ".pdf", ".docx"}
지원_DOCX_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _parse_data_url(data_url: str, fallback_mime: str = "application/octet-stream") -> tuple[str, bytes]:
    raw = str(data_url or "").strip()
    if not raw:
        return fallback_mime, b""

    if "," not in raw:
        try:
            return fallback_mime, base64.b64decode(raw)
        except Exception:
            return fallback_mime, b""

    header, payload = raw.split(",", 1)
    mime_type = fallback_mime
    if header.startswith("data:"):
        mime_type = header[5:].split(";", 1)[0] or fallback_mime

    try:
        return mime_type, base64.b64decode(payload)
    except Exception:
        return mime_type, b""


def _decode_text_bytes(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return payload.decode(encoding).replace("\x00", "").strip()
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="ignore").replace("\x00", "").strip()


def _extract_pdf_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF 첨부를 읽으려면 pypdf 패키지가 필요합니다.") from exc

    reader = PdfReader(io.BytesIO(payload))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"[페이지 {index}]\n{text}")
    return "\n\n".join(pages).strip()


def _extract_docx_text(payload: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("DOCX 첨부를 읽으려면 python-docx 패키지가 필요합니다.") from exc

    document = Document(io.BytesIO(payload))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n".join(paragraphs).strip()


def _guess_attachment_category(name: str, mime_type: str) -> str:
    suffix = Path(str(name or "")).suffix.lower()
    normalized = str(mime_type or "").lower()
    if normalized.startswith("image/"):
        return "image"
    if suffix in 지원_문서_확장자:
        return "document"
    if normalized.startswith("text/"):
        return "document"
    if normalized == "application/pdf":
        return "document"
    if normalized in 지원_DOCX_MIME:
        return "document"
    return "unsupported"


def _estimate_text_tokens(text: str, model_name: str = "") -> int:
    content = str(text or "")
    if not content:
        return 0

    try:
        if model_name:
            encoder = tiktoken.encoding_for_model(model_name)
        else:
            encoder = tiktoken.get_encoding("cl100k_base")
        return len(encoder.encode(content))
    except Exception:
        return max(1, math.ceil(len(content) / 4))


def _estimate_image_tokens(payload: bytes) -> tuple[int, int, int]:
    image = Image.open(io.BytesIO(payload))
    width, height = image.size
    tile_x = max(1, math.ceil(width / 512))
    tile_y = max(1, math.ceil(height / 512))
    token_estimate = max(256, tile_x * tile_y * 256)
    return token_estimate, width, height


def _extract_document_text(name: str, mime_type: str, payload: bytes) -> str:
    suffix = Path(str(name or "")).suffix.lower()
    normalized = str(mime_type or "").lower()

    if suffix in {".txt", ".md"} or normalized.startswith("text/"):
        return _decode_text_bytes(payload)
    if suffix == ".pdf" or normalized == "application/pdf":
        return _extract_pdf_text(payload)
    if suffix == ".docx" or normalized in 지원_DOCX_MIME:
        return _extract_docx_text(payload)
    raise ValueError(f"지원하지 않는 문서 형식입니다: {name}")


def prepare_attachments(raw_attachments: Iterable[dict], model_name: str = "") -> list[dict]:
    """
    첨부 데이터를 분석해 UI/브리지에서 재사용 가능한 메타데이터로 변환한다.
    """
    prepared: list[dict] = []

    for item in raw_attachments or []:
        attachment_id = str((item or {}).get("id", "")).strip()
        name = str((item or {}).get("name", "")).strip() or "이름 없는 첨부"
        declared_type = str((item or {}).get("type", "")).strip() or "application/octet-stream"
        data_url = str((item or {}).get("dataUrl", "")).strip()
        mime_type, payload = _parse_data_url(data_url, fallback_mime=declared_type)
        category = _guess_attachment_category(name, mime_type)

        base_info = {
            "id": attachment_id,
            "name": name,
            "type": mime_type,
            "category": category,
            "dataUrl": data_url,
            "tokenEstimate": 0,
            "extractedText": "",
            "width": 0,
            "height": 0,
            "status": "ready",
            "error": "",
        }

        try:
            if category == "image":
                token_estimate, width, height = _estimate_image_tokens(payload)
                base_info["tokenEstimate"] = token_estimate
                base_info["width"] = width
                base_info["height"] = height
            elif category == "document":
                extracted_text = _extract_document_text(name, mime_type, payload)
                base_info["extractedText"] = extracted_text
                base_info["tokenEstimate"] = _estimate_text_tokens(extracted_text, model_name=model_name)
            else:
                raise ValueError(f"지원하지 않는 첨부 형식입니다: {name}")
        except Exception as exc:
            base_info["status"] = "error"
            base_info["error"] = str(exc)

        prepared.append(base_info)

    return prepared


def build_attachment_context_block(documents: Iterable[dict]) -> str:
    """
    현재 세션에서 유지할 문서 첨부 컨텍스트를 구성한다.
    """
    items = []
    for item in documents or []:
        category = str((item or {}).get("category", "")).strip()
        if category == "document":
            items.append(item)
            continue
        guessed = _guess_attachment_category(
            str((item or {}).get("name", "")),
            str((item or {}).get("type", "")),
        )
        if guessed == "document":
            items.append(item)
    if not items:
        return ""

    parts = [
        "[현재 세션 첨부 자료]",
        "- 아래 문서들은 현재 대화 세션에서 계속 참고할 수 있는 자료입니다.",
        "- 파일명을 기준으로 구분해서 질문해 주세요.",
    ]

    for item in items:
        name = str(item.get("name", "")).strip() or "이름 없는 문서"
        mime_type = str(item.get("type", "")).strip() or "application/octet-stream"
        token_estimate = int(item.get("tokenEstimate", 0) or 0)
        extracted_text = str(item.get("extractedText", "") or "").strip()
        parts.append(f"[파일:{name}]")
        parts.append(f"- 형식: {mime_type}")
        parts.append(f"- 추정 토큰: {token_estimate}")
        if extracted_text:
            parts.append(extracted_text)
        else:
            parts.append("문서에서 읽을 수 있는 텍스트를 찾지 못했습니다.")

    return "\n".join(parts).strip()


def build_general_chat_prompt(message: str, obsidian_context: str = "", attachment_context: str = "") -> str:
    """
    Obsidian 컨텍스트와 세션 첨부 자료를 함께 포함한 일반 채팅 프롬프트를 만든다.
    """
    sections: list[str] = []
    obs_context = str(obsidian_context or "").strip()
    attach_context = str(attachment_context or "").strip()
    if obs_context:
        sections.append(obs_context)
    if attach_context:
        sections.append(attach_context)
    sections.append(f"[사용자 메시지]\n{str(message or '').strip()}")
    return "\n\n".join(section for section in sections if section).strip()


def build_attachment_note(attachments: Iterable[dict]) -> str:
    """
    대화 버퍼에 남길 첨부 요약 메모를 만든다.
    """
    docs = [str(item.get("name", "")).strip() for item in (attachments or []) if item.get("category") == "document"]
    image_count = sum(1 for item in (attachments or []) if item.get("category") == "image")

    parts: list[str] = []
    if docs:
        parts.append(f"파일: {', '.join(name for name in docs if name)}")
    if image_count:
        parts.append(f"이미지 {image_count}장")

    if not parts:
        return ""
    return " [" + " | ".join(parts) + "]"
