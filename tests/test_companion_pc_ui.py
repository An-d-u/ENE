"""Node VM에서 PC 초안·수락 순서·ID 표시의 실제 상태 전이를 검증한다."""

import json
from pathlib import Path
import subprocess


RUNTIME = Path(__file__).resolve().parents[1] / "assets/web/runtime_companion_chat.js"


def run_case(case):
    assert RUNTIME.is_file(), "공개 ID 기반 PC 입력 runtime이 필요하다"
    script = (
        r"""
const fs = require('fs');
const vm = require('vm');
const rendered = new Map();
const calls = [], notices = [], pending = [];
let draft = {text: '가상 도형 초안', attachments: [{id: 'synthetic-file'}], version: 1};
let nextId = 40;
const id = (value) => `00000000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const context = {console, result: null, window: {}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const chat = context.createCompanionChatRuntime({
    newId: () => id(nextId++),
    readDraft: () => structuredClone(draft),
    clearDraft: () => { draft = {text: '', attachments: [], version: draft.version + 1}; },
    restoreVoice: (text) => { draft.text += (draft.text ? '\n' : '') + text; draft.version += 1; },
    render: (message) => { rendered.set(message.id, message); },
    update: (message) => { rendered.set(message.id, {...rendered.get(message.id), ...message}); },
    remove: (messageId) => { rendered.delete(messageId); },
    send: (payload, callback) => calls.push({payload, callback}),
    setPending: (active) => pending.push(active),
    notice: (code) => notices.push(code),
});
chat.applySnapshot({server_epoch: id(1), conversation_id: id(2), conversation_revision: 0, messages: [], processing: {phase: 'idle'}});
const event = (requestId = id(40)) => ({op: 'append', server_epoch: id(1), conversation_id: id(2), conversation_revision: 1,
    message: {id: id(3), role: 'user', text: '가상 도형 초안', request_id: requestId, displayed_at: '2030-02-03T00:00:00Z'}});
const status = (state, extra = {}) => ({request_id: id(40), state, ...extra});
"""
        + case
        + "\nprocess.stdout.write(JSON.stringify(result));"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(RUNTIME)],
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_reserved_then_rejected_keeps_text_and_attachments():
    result = run_case("""
chat.submit({text: draft.text, attachments: draft.attachments});
calls[0].callback(status('reserved'));
const reserved = structuredClone(draft);
chat.receiveAdmission(status('rejected', {code: 'busy'}));
result = {reserved, draft, count: rendered.size, notices};
""")
    assert result["reserved"] == result["draft"]
    assert result["draft"]["text"] == "가상 도형 초안"
    assert len(result["draft"]["attachments"]) == 1
    assert result["count"] == 0
    assert result["notices"] == ["busy"]


def test_display_before_acceptance_renders_only_once_and_then_clears_draft():
    result = run_case("""
chat.submit({text: draft.text, attachments: draft.attachments});
chat.applyEvent(event());
chat.applyEvent(event());
calls[0].callback(status('accepted', {message_id: id(3)}));
chat.receiveAdmission(status('accepted', {message_id: id(3)}));
result = {draft, count: rendered.size, id: [...rendered.keys()][0]};
""")
    assert result["draft"]["text"] == ""
    assert result["draft"]["attachments"] == []
    assert result["count"] == 1
    assert result["id"].endswith("000000000003")


def test_late_acceptance_does_not_clear_new_draft_version():
    result = run_case("""
chat.submit({text: draft.text, attachments: draft.attachments});
draft = {text: '가상 다음 도형 초안', attachments: [{id: 'synthetic-new-file'}], version: 2};
calls[0].callback(status('accepted', {message_id: id(3)}));
result = draft;
""")
    assert result["text"] == "가상 다음 도형 초안"
    assert result["attachments"] == [{"id": "synthetic-new-file"}]


def test_rejected_voice_is_preserved_without_erasing_typed_draft():
    result = run_case("""
chat.submit({text: '가상 음성 초안', attachments: [], voice: true});
calls[0].callback(status('rejected', {code: 'busy'}));
result = draft;
""")
    assert "가상 도형 초안" in result["text"]
    assert "가상 음성 초안" in result["text"]
    assert len(result["attachments"]) == 1


def test_phone_message_renders_without_local_submission():
    result = run_case("""
chat.applyEvent(event(id(99)));
result = {count: rendered.size, calls: calls.length, draft};
""")
    assert result["count"] == 1 and result["calls"] == 0
    assert result["draft"]["text"] == "가상 도형 초안"


def test_edit_target_stays_frozen_after_another_message_arrives():
    result = run_case("""
chat.applyEvent(event());
const target = chat.captureTarget(id(3));
chat.applyEvent({...event(id(41)), conversation_revision: 2, message: {...event().message, id: id(4)}});
result = {target, current: chat.captureTarget(id(4))};
""")
    assert result["target"]["target_message_id"].endswith("000000000003")
    assert result["target"]["expected_revision"] == 1
    assert result["current"]["expected_revision"] == 2


def test_duplicate_snapshot_updates_by_id_without_losing_private_metadata():
    result = run_case("""
chat.applyEvent({...event(), message: {...event().message, thought: '합성 PC 전용 생각', attachments: [{id: 'synthetic-private-file'}]}});
chat.applySnapshot({server_epoch: id(1), conversation_id: id(2), conversation_revision: 1, messages: [event().message], processing: {phase: 'idle'}});
result = {count: rendered.size, message: rendered.get(id(3))};
""")
    assert result["count"] == 1
    assert result["message"]["thought"] == "합성 PC 전용 생각"
    assert result["message"]["attachments"] == [{"id": "synthetic-private-file"}]


def test_mutation_status_is_correlated_without_touching_main_draft():
    result = run_case("""
const states = [];
chat.trackMutation(id(40), value => states.push(value.state));
chat.receiveAdmission(status('accepted', {message_id: id(3)}));
chat.receiveAdmission(status('failed', {message_id: id(3), code: 'request_failed'}));
result = {states, draft, active: pending[pending.length - 1]};
""")
    assert result["states"] == ["accepted", "failed"]
    assert result["draft"]["text"] == "가상 도형 초안"
    assert result["active"] is False


def test_backend_busy_is_not_cleared_by_unrelated_rejection():
    result = run_case("""
chat.setBackendPending(true);
chat.submit({text: draft.text, attachments: draft.attachments});
calls[0].callback(status('rejected', {code: 'busy'}));
result = {active: pending[pending.length - 1], draft};
""")
    assert result["active"] is True
    assert result["draft"]["text"] == "가상 도형 초안"


def run_pc_entry_case(case):
    flow_path = RUNTIME.with_name("runtime_chat_flow.js")
    flow = flow_path.read_text(encoding="utf-8-sig")
    start = flow.index("function sendMessage()")
    end = flow.index("window.submitVoiceText = submitVoiceText;") + len(
        "window.submitVoiceText = submitVoiceText;"
    )
    script = (
        r"""
const fs = require('fs');
const vm = require('vm');
const nodes = [], calls = [], notices = [], inputListeners = {};
let nextId = 40;
const id = value => `00000000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const signal = () => ({callbacks: [], connect(callback) {this.callbacks.push(callback);}, emit(value) {this.callbacks.forEach(callback => callback(value));}});
const bridge = {
  chat_display_event: signal(), chat_admission_result: signal(),
  get_companion_chat_state(callback) {callback(JSON.stringify({server_epoch: id(1), conversation_id: id(2), conversation_revision: 0, messages: [], processing: {phase: 'idle'}}));},
  submit_pc_chat(raw, callback) {calls.push({payload: JSON.parse(raw), callback});},
  send_to_ai() {throw Error('기존 즉시 전송 경로로 우회하면 안 된다');},
};
const context = {
  console: {warn() {}, error() {}, log() {}},
  window: {pyBridge: bridge, crypto: {randomUUID: () => id(nextId++)}},
  chatInput: {value: '가상 PC 초안', addEventListener(name, callback) {inputListeners[name] = callback;}},
  attachedAttachments: [{id: 'synthetic-file', name: 'synthetic.txt', category: 'document', dataUrl: 'synthetic-data'}],
  chatMessages: {querySelectorAll: () => nodes}, isRequestPending: false, shouldReplaceNextAssistant: false,
  createAttachmentId: () => 'synthetic-local-id',
  dispatchBridgeCall(task, error) {try {task();} catch (failure) {if (error) error(failure); else throw failure;}},
  autoResizeTextarea() {}, updateAttachmentPreview() {}, updateRerollButtonState() {},
  showToast(message) {notices.push(message);}, cancelPendingPatEmotionRestore() {}, changeExpression() {},
  setRequestPending(value) {context.isRequestPending = value;},
  addMessage(text, role, attachments, timestamp, options) {
    const node = {dataset: {messageId: options.messageId}, _text: text, _thought: options.thought || '', _messageAttachments: attachments, remove() {nodes.splice(nodes.indexOf(node), 1);}};
    nodes.push(node); return node;
  },
  getMessageLogicalText: node => node._text,
  getMessageThoughtText: node => node._thought,
  getMessageVisualAttachments: node => node._messageAttachments,
  renderMessageBubbleSegments(node, text, options) {node._text = text; node._thought = options.thought; node._messageAttachments = options.attachments;},
  result: null,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + '\n' + JSON.parse(process.argv[2]), context);
vm.runInContext('connectCompanionChatBridge(window.pyBridge);', context);
"""
        + case
        + "\nprocess.stdout.write(JSON.stringify(context.result));"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(RUNTIME), json.dumps(flow[start:end])],
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_actual_send_entry_preserves_draft_until_ack_and_renders_event_once():
    result = run_pc_entry_case("""
vm.runInContext('sendMessage();', context);
const before = {text: context.chatInput.value, attachments: context.attachedAttachments.length, rendered: nodes.length};
bridge.chat_display_event.emit(JSON.stringify({op: 'append', server_epoch: id(1), conversation_id: id(2), conversation_revision: 1,
 message: {id: id(3), request_id: id(40), text: '가상 PC 초안', role: 'user', displayed_at: '2030-02-03T00:00:00Z'}}));
calls[0].callback(JSON.stringify({request_id: id(40), state: 'accepted', message_id: id(3)}));
context.result = {before, after: context.chatInput.value, attachments: context.attachedAttachments.length, rendered: nodes.length};
""")
    assert result["before"] == {"text": "가상 PC 초안", "attachments": 1, "rendered": 0}
    assert result["after"] == "" and result["attachments"] == 0
    assert result["rendered"] == 1


def test_actual_voice_entry_preserves_recognition_when_backend_is_busy():
    result = run_pc_entry_case("""
context.isRequestPending = true;
vm.runInContext("submitVoiceText('가상 음성 인식 초안');", context);
calls[0].callback(JSON.stringify({request_id: id(40), state: 'rejected', code: 'busy'}));
context.result = {text: context.chatInput.value, attachments: context.attachedAttachments.length, rendered: nodes.length};
""")
    assert "가상 PC 초안" in result["text"]
    assert "가상 음성 인식 초안" in result["text"]
    assert result["attachments"] == 1 and result["rendered"] == 0


def test_actual_inline_editor_keeps_original_and_captured_target_until_acceptance():
    rendering = RUNTIME.with_name("runtime_message_rendering.js").read_text(
        encoding="utf-8-sig"
    )
    start = rendering.index("function openInlineEdit(")
    end = rendering.index("\nfunction ", start + 1)
    script = r"""
const vm = require('vm');
class Element {
 constructor() {this.children = []; this.className = ''; this.dataset = {}; this.listeners = {}; this.classList = {add() {}, remove() {}};}
 appendChild(child) {this.children.push(child); child.parent = this;}
 addEventListener(name, callback) {this.listeners[name] = callback;}
 querySelector(selector) {for (const child of this.children) {if (child.className === selector.slice(1)) return child; const nested = child.querySelector(selector); if (nested) return nested;} return null;}
 remove() {if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);}
 focus() {} setSelectionRange() {}
}
const stack = new Element(), node = new Element(), calls = [];
node.dataset.messageId = 'synthetic-target';
let revision = 1, renders = 0;
const context = {
 window: {pyBridge: {edit_last_user_message() {throw Error('기존 수정 경로');}}, eneCompanionChat: {
   captureTarget: messageId => Object.freeze({target_message_id: messageId, expected_revision: revision}),
   submitMutation: (kind, target, text, callback) => calls.push({kind, target, text, callback}),
 }},
 document: {createElement: () => new Element()},
 getMessageBubbleStack: () => stack, getMessageLogicalText: () => '가상 원래 문장',
 activeInlineEditMessageEl: null, isRequestPending: false,
 closeInlineEdit() {const wrap = stack.querySelector('.inline-edit-wrap'); if (wrap) wrap.remove();},
 renderMessageBubbleSegments() {renders += 1;}, getMessageVisualAttachments: () => [],
 dispatchBridgeCall: task => task(), setRequestPending() {},
};
vm.createContext(context);
vm.runInContext(JSON.parse(process.argv[1]), context);
context.openInlineEdit(node);
revision = 2;
const input = stack.querySelector('.inline-edit-input');
input.value = '가상 수정 초안';
stack.querySelector('.inline-edit-save').listeners.click();
const before = {renders, open: Boolean(stack.querySelector('.inline-edit-wrap'))};
calls[0].callback({state: 'rejected', code: 'stale_target'});
const rejected = {open: Boolean(stack.querySelector('.inline-edit-wrap')), text: input.value};
calls[0].callback({state: 'accepted'});
process.stdout.write(JSON.stringify({before, rejected, after: Boolean(stack.querySelector('.inline-edit-wrap')), target: calls[0].target}));
"""
    completed = subprocess.run(
        ["node", "-e", script, json.dumps(rendering[start:end])],
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["before"] == {"renders": 0, "open": True}
    assert result["rejected"] == {"open": True, "text": "가상 수정 초안"}
    assert result["after"] is False
    assert result["target"]["expected_revision"] == 1
