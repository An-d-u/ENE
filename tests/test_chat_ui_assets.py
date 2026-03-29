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


def test_reroll_button_uses_svg_icon_styles():
    block = _rule_block(".message-reroll-btn")
    assert "width: 16px;" in block
    assert "height: 16px;" in block
    assert "border-radius: 999px;" in block


def test_loading_indicator_uses_plain_message_row_visuals():
    indicator_block = _rule_block("#loading-indicator")
    typing_text_block = _rule_block(".typing-text")

    assert "display: inline-flex;" in indicator_block
    assert "justify-content: flex-start;" in indicator_block
    assert "gap: 8px;" in indicator_block
    assert "padding-left: 12px;" in indicator_block
    assert "margin-right: auto;" in indicator_block
    assert "align-self: flex-start;" in indicator_block
    assert "width: fit-content;" in indicator_block
    assert "color: var(--ene-chat-panel-text);" in indicator_block
    assert "color: var(--ene-chat-panel-text);" in typing_text_block
    assert "font-size: 14px;" in typing_text_block
    assert "line-height: 1.4;" in typing_text_block
    assert "transform: translateY(4px);" in typing_text_block


def test_token_usage_bubble_is_offset_slightly_lower_from_top_left():
    block = _rule_block("#token-usage-bubble")
    assert "top: 32px;" in block
    assert "left: 4px;" in block


def test_attach_button_centers_within_input_row():
    block = _rule_block("#attach-button")
    assert "align-self: center;" in block
