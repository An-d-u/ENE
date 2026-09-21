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


def test_pending_indicator_never_becomes_a_reroll_target():
    result = run_dom_case("""
setRequestPending(true);
updateRerollButtonState();
const beforeNotice = {hasAssistant: hasAssistantMessage, noTarget: lastAssistantMessageEl === null};
addMessage('가상 안내를 표시합니다.', 'assistant', [], new Date(), {excludeFromReroll: true});
result = {beforeNotice, hasAssistant: hasAssistantMessage, noTarget: lastAssistantMessageEl === null,
    buttons: chatMessages.querySelectorAll('.message-reroll-btn').length};
""")
    assert result == {
        "beforeNotice": {"hasAssistant": False, "noTarget": True},
        "hasAssistant": False,
        "noTarget": True,
        "buttons": 0,
    }


def test_first_response_keeps_reroll_button_when_pending_indicator_is_last():
    result = run_dom_case("""
const head = {server_epoch: 'epoch', conversation_id: 'conversation'};
window.eneCompanionChat.setBackendPending(true);
window.eneCompanionChat.applyEvent({...head, conversation_revision: 1, event_seq: 1, op: 'append',
    message: {id: 'user-1', role: 'user', text: '가상 도형을 배치합니다.', displayed_at: '2099-01-01T10:00:00Z'},
    processing: {phase: 'generating'}});
window.eneCompanionChat.applyEvent({...head, conversation_revision: 2, event_seq: 2, op: 'append',
    message: {id: 'assistant-1', role: 'assistant', text: '가상 도형을 배치했습니다.',
        thought: '도형의 순서를 정리합니다.', displayed_at: '2099-01-01T10:00:01Z'},
    processing: {phase: 'generating'}});
const during = {indicatorLast: chatMessages.lastElementChild === loadingIndicator,
    target: lastAssistantMessageEl?.dataset.messageId ?? null,
    disabled: chatMessages.querySelector('.message-reroll-btn')?.disabled ?? null};
window.eneCompanionChat.applyEvent({...head, conversation_revision: 2, event_seq: 3,
    op: 'processing', processing: {phase: 'idle'}});
window.eneCompanionChat.setBackendPending(false);
await new Promise(resolve => setTimeout(resolve, 0));
const button = chatMessages.querySelector('.message-reroll-btn');
result = {during, buttons: chatMessages.querySelectorAll('.message-reroll-btn').length,
    disabled: button?.disabled ?? null, target: button?.closest('.message')?.dataset.messageId ?? null,
    thoughts: chatMessages.querySelectorAll('.message-thought-btn').length,
    returned: loadingIndicator.parentElement === loadingIndicatorAnchor};
""")
    assert result == {
        "during": {
            "indicatorLast": True,
            "target": "assistant-1",
            "disabled": True,
        },
        "buttons": 1,
        "disabled": False,
        "target": "assistant-1",
        "thoughts": 1,
        "returned": True,
    }


def test_reroll_button_survives_repeated_replacements():
    result = run_dom_case("""
const head = {server_epoch: 'epoch', conversation_id: 'conversation'};
window.eneCompanionChat.applySnapshot({...head, conversation_revision: 2, event_seq: 2, messages: [
    {id: 'user-1', role: 'user', text: '가상 도형을 배치합니다.', displayed_at: '2099-01-01T10:00:00Z'},
    {id: 'assistant-1', role: 'assistant', text: '가상 도형을 배치했습니다.',
        thought: '도형의 순서를 정리합니다.', displayed_at: '2099-01-01T10:00:01Z'},
], processing: {phase: 'idle'}});
await new Promise(resolve => setTimeout(resolve, 0));
const rounds = [];
for (let index = 0; index < 3; index++) {
    const button = chatMessages.querySelector('.message-reroll-btn');
    if (!button || button.disabled) break;
    button.click();
    calls[index].callback({state: 'accepted'});
    window.eneCompanionChat.setBackendPending(true);
    window.eneCompanionChat.applyEvent({...head, conversation_revision: 3 + index, event_seq: 3 + index * 2, op: 'replace',
        message: {id: 'assistant-1', text: '가상 도형의 새 배치 ' + index}, processing: {phase: 'generating'}});
    const during = {indicatorLast: chatMessages.lastElementChild === loadingIndicator,
        target: lastAssistantMessageEl?.dataset.messageId ?? null};
    window.eneCompanionChat.applyEvent({...head, conversation_revision: 3 + index, event_seq: 4 + index * 2,
        op: 'processing', processing: {phase: 'idle'}});
    bridge.chat_admission_result.emit({request_id: calls[index].payload.request_id, state: 'completed'});
    window.eneCompanionChat.setBackendPending(false);
    await new Promise(resolve => setTimeout(resolve, 0));
    const buttons = chatMessages.querySelectorAll('.message-reroll-btn');
    rounds.push({during, buttons: buttons.length, disabled: buttons[0]?.disabled ?? null,
        target: buttons[0]?.closest('.message')?.dataset.messageId ?? null,
        thoughts: chatMessages.querySelectorAll('.message-thought-btn').length});
}
result = {rounds, targets: calls.map(call => call.payload.target_message_id),
    revisions: calls.map(call => call.payload.expected_revision)};
""")
    assert result == {
        "rounds": [
            {
                "during": {"indicatorLast": True, "target": "assistant-1"},
                "buttons": 1,
                "disabled": False,
                "target": "assistant-1",
                "thoughts": 1,
            }
        ] * 3,
        "targets": ["assistant-1"] * 3,
        "revisions": [2, 3, 4],
    }
