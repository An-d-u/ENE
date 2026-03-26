from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "assets" / "web" / "index.html"
SCRIPT_PATH = ROOT / "assets" / "web" / "script.js"
SETTINGS_DIALOG_PATH = ROOT / "src" / "ui" / "settings_dialog.py"


def test_attachment_input_accepts_documents_and_images():
    html = INDEX_PATH.read_text(encoding="utf-8-sig")
    assert 'accept="image/*,.txt,.md,.pdf,.docx"' in html


def test_script_uses_attachment_preview_bridge_and_generic_send_route():
    script = SCRIPT_PATH.read_text(encoding="utf-8-sig")
    assert "window.pyBridge.preview_attachments" in script
    assert "window.pyBridge.send_to_ai_with_attachments" in script
    assert "window.pyBridge.attachment_preview_ready.connect" in script


def test_script_contains_token_usage_bubble_hooks():
    script = SCRIPT_PATH.read_text(encoding="utf-8-sig")
    assert "window.setTokenUsageBubbleEnabled" in script
    assert "showTokenUsageBubble" in script
    assert "window.pyBridge.token_usage_ready.connect" in script


def test_script_contains_message_time_helpers_and_meta_rail():
    script = SCRIPT_PATH.read_text(encoding="utf-8-sig")
    assert "function formatMessageTime" in script
    assert "function ensureMessageMetaRail" in script
    assert "className = 'message-time'" in script


def test_html_and_settings_include_token_usage_ui():
    html = INDEX_PATH.read_text(encoding="utf-8-sig")
    settings_dialog = SETTINGS_DIALOG_PATH.read_text(encoding="utf-8-sig")

    assert 'id="token-usage-bubble"' in html
    assert "대화 토큰 확인" in settings_dialog
