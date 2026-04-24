from __future__ import annotations

import base64
import io

from PIL import Image

from src.core.chat_attachments import (
    build_attachment_context_block,
    build_attachment_note,
    build_general_chat_prompt,
    prepare_attachments,
)


def _make_data_url(mime_type: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def test_prepare_text_attachment_extracts_text_and_estimates_tokens():
    payload = "첫 번째 줄\n두 번째 줄".encode("utf-8-sig")
    attachments = [
        {
            "id": "txt-1",
            "name": "회의메모.txt",
            "type": "text/plain",
            "dataUrl": _make_data_url("text/plain", payload),
        }
    ]

    prepared = prepare_attachments(attachments)

    assert len(prepared) == 1
    assert prepared[0]["category"] == "document"
    assert prepared[0]["extractedText"] == "첫 번째 줄\n두 번째 줄"
    assert prepared[0]["tokenEstimate"] > 0


def test_prepare_image_attachment_returns_dimension_based_token_estimate():
    image = Image.new("RGB", (640, 480), color="navy")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    attachments = [
        {
            "id": "img-1",
            "name": "참고이미지.png",
            "type": "image/png",
            "dataUrl": _make_data_url("image/png", buffer.getvalue()),
        }
    ]

    prepared = prepare_attachments(attachments)

    assert prepared[0]["category"] == "image"
    assert prepared[0]["tokenEstimate"] >= 256
    assert prepared[0]["width"] == 640
    assert prepared[0]["height"] == 480


def test_build_attachment_context_block_uses_file_names_for_follow_up_reference():
    context = build_attachment_context_block(
        [
            {
                "name": "회의록.pdf",
                "type": "application/pdf",
                "tokenEstimate": 321,
                "extractedText": "이번 주 일정은 수요일 회의입니다.",
            },
            {
                "name": "아이디어.md",
                "type": "text/markdown",
                "tokenEstimate": 128,
                "extractedText": "버전 1에서는 문서 첨부와 이미지 첨부를 함께 지원합니다.",
            },
        ]
    )

    assert "회의록.pdf" in context
    assert "아이디어.md" in context
    assert "이번 주 일정은 수요일 회의입니다." in context
    assert "버전 1에서는 문서 첨부와 이미지 첨부를 함께 지원합니다." in context


def test_build_general_chat_prompt_combines_obsidian_and_attachment_contexts():
    prompt = build_general_chat_prompt(
        "이 자료들 기준으로 일정만 정리해줘.",
        obsidian_context="[Obsidian 체크된 파일 본문]\n- 오늘 할 일",
        attachment_context="[현재 세션 첨부 자료]\n[파일:회의록.pdf]\n회의 내용",
    )

    assert "[Obsidian 체크된 파일 본문]" in prompt
    assert "[현재 세션 첨부 자료]" in prompt
    assert "[사용자 메시지]\n이 자료들 기준으로 일정만 정리해줘." in prompt


def test_general_chat_prompt_uses_selected_language():
    prompt = build_general_chat_prompt(
        "Use these notes.",
        attachment_context="[Current Session Attachments]\n[File:notes.pdf]\nBody",
        language="en",
    )

    assert "[User Message]\nUse these notes." in prompt


def test_attachment_context_block_uses_selected_language():
    context = build_attachment_context_block(
        [
            {
                "name": "memo.pdf",
                "type": "application/pdf",
                "category": "document",
                "status": "ready",
                "tokenEstimate": 10,
                "extractedText": "",
            },
        ],
        language="en",
    )

    assert "[Current Session Attachments]" in context
    assert "[File:memo.pdf]" in context
    assert "No readable text was found in the document." in context


def test_build_attachment_note_lists_file_names_and_image_count():
    note = build_attachment_note(
        [
            {"name": "회의록.pdf", "category": "document", "status": "ready"},
            {"name": "장면.png", "category": "image", "status": "ready", "deleted": False},
            {"name": "삭제됨.png", "category": "image", "status": "ready", "deleted": True},
        ]
    )

    assert "파일:회의록.pdf" in note
    assert "이미지:장면.png" in note
    assert "[사진이 삭제되었습니다.]" in note


def test_build_attachment_context_block_keeps_deleted_image_notice_for_follow_up_context():
    context = build_attachment_context_block(
        [
            {
                "name": "첫장.png",
                "type": "image/png",
                "category": "image",
                "status": "ready",
                "deleted": False,
            },
            {
                "name": "삭제됨.png",
                "type": "image/png",
                "category": "image",
                "status": "ready",
                "deleted": True,
            },
            {
                "name": "회의록.pdf",
                "type": "application/pdf",
                "category": "document",
                "status": "ready",
                "tokenEstimate": 321,
                "extractedText": "이번 주 일정은 수요일 회의입니다.",
            },
        ]
    )

    assert "[사진이 삭제되었습니다.]" in context
    assert "회의록.pdf" in context
    assert "이번 주 일정은 수요일 회의입니다." in context
