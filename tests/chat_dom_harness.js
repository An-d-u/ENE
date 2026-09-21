// 브라우저 API 경계만 대체하고 메시지·버튼·요청 상태는 실제 런타임을 실행한다.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

class Element {
    constructor(tagName = 'div') {
        this.tagName = tagName.toUpperCase();
        this.children = [];
        this.parentElement = null;
        this.dataset = {};
        this.style = {};
        this.attributes = {};
        this.className = '';
        this.value = '';
        this.disabled = false;
        this.listeners = {};
        this.classList = {
            contains: name => this.className.split(/\s+/).includes(name),
            add: name => { if (!this.classList.contains(name)) this.className += ` ${name}`; },
            remove: name => { this.className = this.className.split(/\s+/).filter(item => item !== name).join(' '); },
            toggle: (name, enabled) => enabled ? this.classList.add(name) : this.classList.remove(name),
        };
    }
    get lastElementChild() { return this.children.at(-1) || null; }
    get isConnected() { return this === body || Boolean(this.parentElement?.isConnected); }
    appendChild(child) { child.remove(); this.children.push(child); child.parentElement = this; return child; }
    insertBefore(child, anchor) {
        if (!anchor) return this.appendChild(child);
        if (!this.children.includes(anchor)) throw Error('잘못된 DOM 기준 노드');
        child.remove(); this.children.splice(this.children.indexOf(anchor), 0, child); child.parentElement = this;
        return child;
    }
    remove() {
        if (this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
        this.parentElement = null;
    }
    contains(child) { return child === this || this.children.some(node => node.contains(child)); }
    set innerHTML(value) { this.children.slice().forEach(child => child.remove()); this._html = value; }
    get innerHTML() { return this._html || ''; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    click() { if (!this.disabled) this.listeners.click?.(); }
    matches(selector) {
        const not = selector.match(/:not\((.+)\)$/);
        if (not) return this.matches(selector.slice(0, not.index)) && !this.matches(not[1]);
        const attribute = selector.match(/^\[data-([\w-]+)="([^"]+)"\]$/);
        if (attribute) return this.dataset[attribute[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] === attribute[2];
        if (selector.startsWith('#')) return this.id === selector.slice(1);
        if (selector.startsWith('.')) return selector.slice(1).split('.').every(name => this.classList.contains(name));
        return this.tagName.toLowerCase() === selector;
    }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
    querySelectorAll(selector) {
        const parts = selector.split(/\s+(?![^\[]*\])/);
        if (parts.length > 1) return this.querySelectorAll(parts[0]).flatMap(node => node.querySelectorAll(parts.slice(1).join(' ')));
        return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const body = new Element('body');
const elements = {};
for (const id of ['chat-container', 'chat-messages', 'chat-input', 'send-button', 'attach-button', 'image-input', 'loading-indicator', 'image-preview-container']) {
    const node = elements[id] = new Element(); node.id = id; body.appendChild(node);
}
for (const id of ['chat-messages', 'loading-indicator', 'image-preview-container']) elements['chat-container'].appendChild(elements[id]);
const label = new Element('span'); label.className = 'typing-text'; elements['loading-indicator'].appendChild(label);
const signal = () => ({callbacks: [], connect(callback) {this.callbacks.push(callback);}, emit(value) {this.callbacks.forEach(callback => callback(value));}});
const calls = [];
const bridge = {
    chat_display_event: signal(), chat_admission_result: signal(),
    get_companion_chat_state(callback) { callback(JSON.stringify({server_epoch: 'epoch', conversation_id: 'conversation', conversation_revision: 0, event_seq: 0, messages: [], processing: {phase: 'idle'}})); },
    submit_pc_chat(raw, callback) { calls.push({payload: JSON.parse(raw), callback}); },
    reroll_companion_message(raw, callback) { calls.push({payload: JSON.parse(raw), callback}); },
    reroll_last_response() {}, edit_last_user_message() {},
};
let nextId = 1;
const context = {
    console, document: {body, getElementById: id => elements[id] || null, querySelector: selector => body.querySelector(selector), createElement: tag => new Element(tag)},
    window: {pyBridge: bridge, crypto: {randomUUID: () => `request-${nextId++}`}, setTimeout, clearTimeout},
    currentUiStrings: {loading: '합성 대기 표시', thoughts: {show: '보기', hide: '숨기기'}},
    DEFAULT_UI_STRINGS: {loading: '합성 대기 표시'},
    cancelPendingPatEmotionRestore() {}, changeExpression() {}, autoResizeTextarea() {}, updateAttachmentPreview() {},
    dispatchBridgeCall(task, failure) { try { task(); } catch (error) { if (failure) failure(error); else throw error; } },
    createAttachmentId: () => `attachment-${nextId++}`, setTimeout, clearTimeout, result: null, calls, bridge,
};
vm.createContext(context);
const web = path.join(__dirname, '..', 'assets', 'web');
for (const name of ['runtime_chat_state.js', 'runtime_message_helpers.js', 'runtime_chat_panel_controls.js', 'runtime_message_rendering.js', 'runtime_companion_chat.js']) {
    vm.runInContext(fs.readFileSync(path.join(web, name), 'utf8'), context, {filename: name});
}
vm.runInContext("typingEffectEnabled = false; connectCompanionChatBridge(window.pyBridge);", context);
const source = fs.readFileSync(0, 'utf8');
vm.runInContext(`(async () => { ${source} })()`, context).then(() => {
    process.stdout.write(JSON.stringify(context.result));
}).catch(error => { console.error(error); process.exitCode = 1; });
