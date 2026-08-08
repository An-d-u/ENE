from __future__ import annotations

import json
import re
import subprocess

from test_life_record_panel_assets import WEB_DIR, _run_panel_case


def _run_controls_case(case_script: str) -> dict:
    runtime_path = WEB_DIR / "runtime_chat_panel_controls.js"
    node_script = f"""
const fs = require('fs');
const vm = require('vm');
class Element {{
  constructor(name, disabled = false) {{ this.name = name; this.disabled = disabled; this.isConnected = true; this.value = ''; this.files = null; this.map = {{}}; }}
  querySelector(selector) {{ return this.map[selector] || null; }}
  querySelectorAll(selector) {{ return this.map[selector] || []; }}
  remove() {{ this.isConnected = false; }}
}}
const chatInput = new Element('chatInput');
const sendButton = new Element('sendButton', true);
const attachButton = new Element('attachButton');
const imageInput = new Element('imageInput');
const editButton = new Element('editButton');
const rerollButton = new Element('rerollButton', true);
const saveButton = new Element('saveButton');
const inlineInput = new Element('inlineInput');
const inlineCancel = new Element('inlineCancel');
const activeInlineEditMessageEl = new Element('inlineEdit');
activeInlineEditMessageEl.map['.inline-edit-save'] = saveButton;
activeInlineEditMessageEl.map['.inline-edit-input'] = inlineInput;
activeInlineEditMessageEl.map['.inline-edit-cancel'] = inlineCancel;
const chatMessages = new Element('chatMessages');
chatMessages.map['.message-edit-btn'] = [editButton];
chatMessages.map['.message-reroll-btn'] = [rerollButton];
chatMessages.map['.inline-edit-save'] = [saveButton];
chatMessages.map['.inline-edit-input'] = [inlineInput];
chatMessages.map['.inline-edit-cancel'] = [inlineCancel];
const panelLockCalls = [];
const window = {{ eneLifeRecordPanel: {{ setInteractionLocked: (active, reason) => panelLockCalls.push([active, reason]) }} }};
let requestPendingStage = 'thinking';
const currentUiStrings = {{ loading: 'Thinking', loadingSearching: 'Searching' }};
const DEFAULT_UI_STRINGS = currentUiStrings;
const loadingText = null, loadingIndicator = null, loadingIndicatorAnchor = null, imagePreviewContainer = null;
let isRequestPending = false;
const manualSummarizeButton = null, summaryConfirmYesButton = null;
let rerollButtonVisibleBySetting = false, recentEditButtonVisibleBySetting = false;
let hasAssistantMessage = false, hasUserMessage = false, lastAssistantMessageEl = null, lastUserMessageEl = null;
function updateMessageThoughtButtons() {{}}
const runtimeSource = fs.readFileSync({json.dumps(str(runtime_path))}, 'utf8');
const context = {{ window, chatInput, sendButton, attachButton, imageInput, editButton, rerollButton, saveButton, inlineInput, inlineCancel,
  activeInlineEditMessageEl, chatMessages, panelLockCalls, requestPendingStage, currentUiStrings, DEFAULT_UI_STRINGS,
  loadingText, loadingIndicator, loadingIndicatorAnchor, imagePreviewContainer, isRequestPending,
  manualSummarizeButton, summaryConfirmYesButton, rerollButtonVisibleBySetting, recentEditButtonVisibleBySetting,
  hasAssistantMessage, hasUserMessage, lastAssistantMessageEl, lastUserMessageEl, updateMessageThoughtButtons,
  Map, result: null }};
vm.createContext(context);
vm.runInContext(runtimeSource + '\\n' + {json.dumps(case_script)}, context, {{ filename: 'runtime_chat_panel_controls.js' }});
process.stdout.write(JSON.stringify(context.result));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _ready_records_script(*, writable: bool = True, language: str = "ko") -> str:
    writable_literal = "true" if writable else "false"
    return f"""
window.eneLifeRecordPanel.setNowProvider(() => new Date(2099, 7, 7, 10, 0, 0));
window.eneLifeRecordPanel.open();
const request = requests[0];
window.eneLifeRecordPanel.receive({{
  status: 'ready', requested_date: request[0], request_id: request[1],
  view_timezone: 'Asia/Seoul', language: '{language}', latest_id: 'record-latest',
  life_records_writable: {writable_literal},
  read_only_reason: {"null" if writable else "'session_lease_unavailable'"},
  records: [
    {{ id: 'record-latest', inactive_started_at: '2099-08-07T08:00:00+09:00', returned_at: '2099-08-07T09:00:00+09:00', entries: [], ending_state: {{ place: 'Atrium', summary: 'Waiting quietly.' }} }},
    {{ id: 'record-past', inactive_started_at: '2099-08-06T08:00:00+09:00', returned_at: '2099-08-06T09:00:00+09:00', entries: [], ending_state: {{ place: 'Garden', summary: 'Reading.' }} }},
  ]
}});
"""


def test_only_backend_global_latest_card_can_offer_regeneration_and_read_only_disables_it():
    result = _run_panel_case(
        _ready_records_script(writable=True)
        + """
const cards = elements['life-records-list'].querySelectorAll('.life-record-card');
const writableButtons = elements['life-records-list'].querySelectorAll('.life-record-regenerate');
const firstButtonRecord = writableButtons[0] && writableButtons[0].dataset.recordId;
window.eneLifeRecordPanel.receive({
  status: 'ready', requested_date: request[0], request_id: request[1],
  view_timezone: 'Asia/Seoul', language: 'ko', latest_id: 'record-latest',
  life_records_writable: false, read_only_reason: 'session_lease_unavailable',
  records: [
    { id: 'record-latest', inactive_started_at: '2099-08-07T08:00:00+09:00', returned_at: '2099-08-07T09:00:00+09:00', entries: [], ending_state: { place: 'Atrium', summary: 'Waiting quietly.' } },
    { id: 'record-past', inactive_started_at: '2099-08-06T08:00:00+09:00', returned_at: '2099-08-06T09:00:00+09:00', entries: [], ending_state: { place: 'Garden', summary: 'Reading.' } },
  ]
});
const readOnlyButtons = elements['life-records-list'].querySelectorAll('.life-record-regenerate');
readOnlyButtons[0].click();
result = {
  cardIds: cards.map((card) => card.dataset.recordId),
  writableCount: writableButtons.length,
  firstButtonRecord,
  readOnlyCount: readOnlyButtons.length,
  readOnlyDisabled: readOnlyButtons[0].disabled,
  status: elements['life-records-status'].textContent,
  regenerationCalls,
};
"""
    )

    assert result["cardIds"] == ["record-latest", "record-past"]
    assert result["writableCount"] == 1
    assert result["firstButtonRecord"] == "record-latest"
    assert result["readOnlyCount"] == 1
    assert result["readOnlyDisabled"] is True
    assert result["status"]
    assert result["regenerationCalls"] == []


def test_missing_or_invalid_writable_capability_fails_closed():
    result = _run_panel_case(
        _ready_records_script(writable=True)
        + """
const base = {
  status: 'ready', requested_date: request[0], request_id: request[1],
  view_timezone: 'Asia/Seoul', language: 'ko', latest_id: 'record-latest',
  records: [{ id: 'record-latest', inactive_started_at: '2099-08-07T08:00:00+09:00', returned_at: '2099-08-07T09:00:00+09:00', entries: [], ending_state: { place: 'Atrium', summary: 'Waiting quietly.' } }]
};
window.eneLifeRecordPanel.receive(base);
const missingDisabled = elements['life-records-list'].querySelector('.life-record-regenerate').disabled;
window.eneLifeRecordPanel.receive({ ...base, life_records_writable: 'true', read_only_reason: 'private-detail' });
const invalidDisabled = elements['life-records-list'].querySelector('.life-record-regenerate').disabled;
result = { missingDisabled, invalidDisabled, reason: window.eneLifeRecordPanel.getState().readOnlyReason };
"""
    )

    assert result == {"missingDisabled": True, "invalidDisabled": True, "reason": ""}


def test_regeneration_alertdialog_cancel_traps_focus_and_confirm_calls_bridge_once():
    result = _run_panel_case(
        _ready_records_script(writable=True)
        + """
const regenerate = elements['life-records-list'].querySelector('.life-record-regenerate');
regenerate.focus();
regenerate.click();
const overlay = elements['life-records-panel'].querySelector('.life-record-regeneration-overlay');
const cancel = overlay.querySelector('.life-record-regeneration-cancel');
const confirm = overlay.querySelector('.life-record-regeneration-confirm');
const opened = {
  role: overlay.getAttribute('role'), modal: overlay.getAttribute('aria-modal'),
  labelledby: overlay.getAttribute('aria-labelledby'), describedby: overlay.getAttribute('aria-describedby'),
  focus: document.activeElement && document.activeElement.className,
};
cancel.focus();
overlay.dispatch('keydown', { key: 'Tab', shiftKey: true });
const shiftTabFocus = document.activeElement && document.activeElement.className;
confirm.focus();
overlay.dispatch('keydown', { key: 'Tab', shiftKey: false });
const tabFocus = document.activeElement && document.activeElement.className;
cancel.click();
const afterCancelFocus = document.activeElement && document.activeElement.className;
regenerate.click();
const secondOverlay = elements['life-records-panel'].querySelector('.life-record-regeneration-overlay');
const secondConfirm = secondOverlay.querySelector('.life-record-regeneration-confirm');
secondConfirm.click();
secondConfirm.click();
result = {
  opened, shiftTabFocus, tabFocus, afterCancelFocus,
  regenerationCalls, interactionLockCalls,
  dialogHidden: secondOverlay.classList.contains('hidden'),
  status: elements['life-records-status'].textContent,
};
"""
    )

    assert result["opened"] == {
        "role": "alertdialog",
        "modal": "true",
        "labelledby": "life-record-regeneration-title",
        "describedby": "life-record-regeneration-description",
        "focus": "life-record-regeneration-cancel",
    }
    assert result["shiftTabFocus"] == "life-record-regeneration-confirm"
    assert result["tabFocus"] == "life-record-regeneration-cancel"
    assert result["afterCancelFocus"] == "life-record-regenerate"
    assert result["regenerationCalls"] == ["record-latest"]
    assert result["interactionLockCalls"] == [[True, "life_record_regeneration"]]
    assert result["dialogHidden"] is True
    assert result["status"]


def test_rejected_manual_regeneration_releases_provisional_lock_without_touching_records():
    result = _run_panel_case(
        _ready_records_script(writable=True)
        + """
const before = elements['life-records-list'].querySelectorAll('.life-record-card').map((card) => card.dataset.recordId);
const regenerate = elements['life-records-list'].querySelector('.life-record-regenerate');
regenerate.click();
elements['life-records-panel'].querySelector('.life-record-regeneration-confirm').click();
window.eneLifeRecordPanel.showNotice('busy');
const after = elements['life-records-list'].querySelectorAll('.life-record-card').map((card) => card.dataset.recordId);
result = {
  before, after, interactionLockCalls,
  locked: window.eneLifeRecordPanel.getState().interactionLocked,
  status: elements['life-records-status'].textContent,
};
"""
    )

    assert result["before"] == result["after"] == ["record-latest", "record-past"]
    assert result["interactionLockCalls"] == [
        [True, "life_record_regeneration"],
        [False, "life_record_regeneration"],
    ]
    assert result["locked"] is False
    assert result["status"]


def test_manual_regeneration_failure_restores_focus_to_safe_visible_fallback_after_rerender():
    result = _run_panel_case(
        _ready_records_script(writable=True)
        + """
const regenerate = elements['life-records-list'].querySelector('.life-record-regenerate');
regenerate.click();
elements['life-records-panel'].querySelector('.life-record-regeneration-confirm').click();
window.eneLifeRecordPanel.setBackendPending(true);
window.eneLifeRecordPanel.showNotice('generation_failed');
window.eneLifeRecordPanel.setBackendPending(false);
result = {
  focused: document.activeElement && document.activeElement.id,
  oldTriggerConnected: regenerate.isConnected,
  cards: elements['life-records-list'].querySelectorAll('.life-record-card').length,
};
"""
    )

    assert result == {
        "focused": "life-records-date-input",
        "oldTriggerConnected": False,
        "cards": 2,
    }


def test_manual_regeneration_completion_uses_visible_menu_fallback_if_panel_was_closed():
    result = _run_panel_case(
        _ready_records_script(writable=True)
        + """
const regenerate = elements['life-records-list'].querySelector('.life-record-regenerate');
regenerate.click();
elements['life-records-panel'].querySelector('.life-record-regeneration-confirm').click();
window.eneLifeRecordPanel.setBackendPending(true);
window.eneLifeRecordPanel.close();
window.eneLifeRecordPanel.setBackendPending(false);
result = {
  focused: document.activeElement && document.activeElement.id,
  panelHidden: elements['life-records-panel'].classList.contains('hidden'),
};
"""
    )

    assert result == {"focused": "floating-actions-toggle", "panelHidden": True}


def test_panel_language_updates_visible_and_aria_strings_without_owning_document_lang():
    result = _run_panel_case(
        _ready_records_script(writable=True, language="ja")
        + """
const regenerate = elements['life-records-list'].querySelector('.life-record-regenerate');
regenerate.click();
const overlay = elements['life-records-panel'].querySelector('.life-record-regeneration-overlay');
result = {
  lang: document.documentElement.lang,
  button: regenerate.textContent,
  buttonAria: regenerate.getAttribute('aria-label'),
  title: overlay.querySelector('.life-record-regeneration-title').textContent,
  description: overlay.querySelector('.life-record-regeneration-description').textContent,
  cancel: overlay.querySelector('.life-record-regeneration-cancel').textContent,
  confirm: overlay.querySelector('.life-record-regeneration-confirm').textContent,
};
"""
    )

    assert result["lang"] == "ko"
    assert all(result[key] for key in ("button", "buttonAria", "title", "description", "cancel", "confirm"))
    assert result["button"] != "재생성"


def test_generation_lock_source_covers_mutable_controls_but_not_life_panel_navigation():
    controls = (WEB_DIR / "runtime_chat_panel_controls.js").read_text(encoding="utf-8-sig")

    assert "function setGenerationInteractionLock(active, reason" in controls
    assert "chatInput" in controls
    assert "sendButton" in controls
    assert "attachButton" in controls
    assert "imageInput" in controls
    assert ".message-edit-btn" in controls
    assert ".message-reroll-btn" in controls
    assert ".inline-edit-save" in controls
    assert ".inline-edit-input" in controls
    assert ".inline-edit-cancel" in controls
    assert "window.eneLifeRecordPanel.setInteractionLocked" in controls
    for read_only_control in (
        "life-records-close-btn",
        "life-records-date-input",
        "life-records-previous-btn",
        "life-records-next-btn",
    ):
        assert read_only_control not in controls


def test_generation_lock_is_idempotent_preserves_draft_files_and_restores_exact_disabled_state():
    result = _run_controls_case(
        """
chatInput.value = 'Synthetic draft';
const selectedFiles = { length: 1, marker: 'synthetic-file-selection' };
imageInput.files = selectedFiles;
setRequestPendingStage('life_record');
setRequestPending(true);
setRequestPending(true);
const during = [chatInput, sendButton, attachButton, imageInput, editButton, rerollButton, saveButton, inlineInput, inlineCancel].map((node) => node.disabled);
setRequestPending(false);
setRequestPending(false);
const after = [chatInput, sendButton, attachButton, imageInput, editButton, rerollButton, saveButton, inlineInput, inlineCancel].map((node) => node.disabled);
result = { during, after, draft: chatInput.value, sameFiles: imageInput.files === selectedFiles, panelLockCalls };
"""
    )

    assert result == {
        "during": [True] * 9,
        "after": [False, True, False, False, False, True, False, False, False],
        "draft": "Synthetic draft",
        "sameFiles": True,
        "panelLockCalls": [[True, "life_record"], [False, "life_record"]],
    }


def test_regeneration_lock_restores_preexisting_disabled_state_exactly():
    result = _run_panel_case(
        _ready_records_script(writable=True)
        + """
const regenerate = elements['life-records-list'].querySelector('.life-record-regenerate');
regenerate.disabled = true;
window.eneLifeRecordPanel.setInteractionLocked(true, 'life_record');
window.eneLifeRecordPanel.setInteractionLocked(true, 'life_record');
const during = regenerate.disabled;
window.eneLifeRecordPanel.setInteractionLocked(false, 'life_record');
window.eneLifeRecordPanel.setInteractionLocked(false, 'life_record');
result = { during, after: regenerate.disabled };
"""
    )

    assert result == {"during": True, "after": True}


def test_stage_mapping_and_bridge_do_not_unlock_before_backend_pending_finalization():
    controls = (WEB_DIR / "runtime_chat_panel_controls.js").read_text(encoding="utf-8-sig")
    bridge = (WEB_DIR / "runtime_bridge.js").read_text(encoding="utf-8-sig")

    assert "life_record_regeneration" in controls
    assert "life_record" in controls
    assert re.search(r"function normalizeRequestPendingStage\(stage\).*?searching.*?life_record", controls, re.DOTALL)
    message_handler = re.search(
        r"window\.pyBridge\.message_received\.connect\(function.*?\n\s*\}\);",
        bridge,
        re.DOTALL,
    )
    assert message_handler
    assert "setRequestPending(false)" not in message_handler.group(0)


def test_resolved_language_drives_document_and_life_panel_from_one_ui_payload():
    ui_strings = (WEB_DIR / "runtime_ui_strings.js").read_text(encoding="utf-8-sig")
    overlay = (WEB_DIR.parents[1] / "src" / "core" / "overlay_window.py").read_text(encoding="utf-8-sig")

    assert "resolvedLanguage" in ui_strings
    assert "document.documentElement.lang" in ui_strings
    assert "window.eneLifeRecordPanel.setLanguage" in ui_strings
    assert '"resolvedLanguage": i18n.language' in overlay


def test_regeneration_dialog_css_is_mobile_safe_focus_visible_and_reduced_motion_aware():
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8-sig")

    assert ".life-record-regeneration-overlay" in css
    assert ".life-record-regeneration-dialog" in css
    assert "width: min(420px, calc(100vw - 24px));" in css
    assert ".life-record-regeneration-dialog :focus-visible" in css
    assert "min-width: 44px;" in css
    assert "min-height: 44px;" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
