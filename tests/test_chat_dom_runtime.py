"""실제 PC 채팅 런타임을 연결해 생성 표시 순서와 연속 재생성을 검증한다."""

import json
from pathlib import Path
import subprocess


def run_dom_case(source):
    completed = subprocess.run(
        ["node", str(Path(__file__).with_name("chat_dom_harness.js"))],
        input=source,
        capture_output=True,
        encoding="utf-8",
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_pending_indicator_stays_after_messages_appended_during_generation():
    result = run_dom_case("""
setRequestPending(true);
addMessage('가상 도형을 배치합니다.', 'user');
setRequestPending(true);
result = {last: chatMessages.lastElementChild.id, visible: loadingIndicator.style.display};
""")
    assert result == {"last": "loading-indicator", "visible": "inline-flex"}


def test_message_append_keeps_pending_indicator_last_without_another_status_event():
    result = run_dom_case("""
setRequestPending(true);
addMessage('가상 안내를 표시합니다.', 'assistant', [], new Date(), {excludeFromReroll: true});
const last = chatMessages.lastElementChild.id;
setRequestPending(false);
result = {last, hidden: loadingIndicator.style.display, returned: loadingIndicator.parentElement === loadingIndicatorAnchor};
""")
    assert result == {"last": "loading-indicator", "hidden": "none", "returned": True}


def test_reroll_button_survives_replacement_and_allows_another_request():
    result = run_dom_case("""
const head = {server_epoch: 'epoch', conversation_id: 'conversation'};
window.eneCompanionChat.applySnapshot({...head, conversation_revision: 2, event_seq: 2, messages: [
    {id: 'user-1', role: 'user', text: '가상 도형을 배치합니다.', displayed_at: '2099-01-01T10:00:00Z'},
    {id: 'assistant-1', role: 'assistant', text: '가상 도형을 배치했습니다.', displayed_at: '2099-01-01T10:00:01Z'},
], processing: {phase: 'idle'}});
await new Promise(resolve => setTimeout(resolve, 0));
chatMessages.querySelector('.message-reroll-btn').click();
calls[0].callback({state: 'accepted'});
window.eneCompanionChat.setBackendPending(true);
window.eneCompanionChat.applyEvent({...head, conversation_revision: 3, event_seq: 3, op: 'replace',
    message: {id: 'assistant-1', text: '가상 도형을 다시 배치했습니다.'}, processing: {phase: 'generating'}});
window.eneCompanionChat.applyEvent({...head, conversation_revision: 3, event_seq: 4, op: 'processing', processing: {phase: 'idle'}});
bridge.chat_admission_result.emit({request_id: calls[0].payload.request_id, state: 'completed'});
window.eneCompanionChat.setBackendPending(false);
await new Promise(resolve => setTimeout(resolve, 0));
const buttons = chatMessages.querySelectorAll('.message-reroll-btn');
const disabled = buttons[0]?.disabled;
buttons[0]?.click();
result = {buttons: buttons.length, disabled, requests: calls.length,
    target: calls[1]?.payload.target_message_id, revision: calls[1]?.payload.expected_revision};
""")
    assert result == {
        "buttons": 1,
        "disabled": False,
        "requests": 2,
        "target": "assistant-1",
        "revision": 3,
    }
