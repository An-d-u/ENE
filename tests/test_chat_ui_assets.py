from pathlib import Path
import re


STYLE_PATH = Path(__file__).resolve().parents[1] / "assets" / "web" / "style.css"


def _rule_block(selector: str) -> str:
    css = STYLE_PATH.read_text(encoding="utf-8-sig")
    pattern = rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}"
    match = re.search(pattern, css, re.DOTALL)
    assert match, f"{selector} 규칙을 찾지 못했습니다."
    return match.group("body")


def test_chat_container_uses_roomier_bounded_height():
    block = _rule_block("#chat-container")
    assert "overflow: hidden;" in block
    assert "max-height: min(360px, 42vh);" in block


def test_chat_messages_can_shrink_inside_flex_panel():
    block = _rule_block("#chat-messages")
    assert "min-height: 0;" in block


def test_image_preview_stays_reserved_and_keeps_controls_inside():
    preview_block = _rule_block("#image-preview-container")
    remove_button_block = _rule_block(".attachment-preview-item .remove-btn")

    assert "flex-shrink: 0;" in preview_block
    assert "overflow-y: hidden;" in preview_block
    assert "top: 4px;" in remove_button_block
    assert "right: 4px;" in remove_button_block


def test_message_time_meta_rail_aligns_with_bubbles():
    message_block = _rule_block(".message")
    meta_block = _rule_block(".message-meta-rail")
    time_block = _rule_block(".message-time")

    assert "align-items: flex-end;" in message_block
    assert "display: inline-flex;" in meta_block
    assert "align-items: flex-end;" in meta_block
    assert "font-size: 11px;" in time_block
    assert "white-space: nowrap;" in time_block


def test_edit_button_uses_svg_icon_styles():
    block = _rule_block(".message-edit-btn")
    assert "width: 16px;" in block
    assert "height: 16px;" in block
    assert "border-radius: 999px;" in block
