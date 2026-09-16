// PC 화면은 수락 결과로 초안을 정리하고, 공개 ID 이벤트로만 대화를 그린다.
function createCompanionChatRuntime(host) {
    let head = null;
    let revision = 0;
    let eventSeq = 0;
    let processing = { phase: 'idle' };
    let backendPending = false;
    const messages = new Map();
    const submissions = new Map();

    function sameSession(value) {
        return head && value.server_epoch === head.server_epoch
            && value.conversation_id === head.conversation_id;
    }

    function updatePending() {
        host.setPending(backendPending || processing.phase !== 'idle' || submissions.size > 0);
    }

    function upsert(message) {
        const previous = messages.get(message.id);
        const combined = { ...previous, ...message };
        messages.set(message.id, combined);
        if (previous) host.update(combined);
        else host.render(combined);
    }

    function applySnapshot(snapshot) {
        if (sameSession(snapshot) && snapshot.conversation_revision < revision) return false;
        if (!sameSession(snapshot)) {
            for (const messageId of messages.keys()) host.remove(messageId);
            messages.clear();
            submissions.clear();
        }
        head = { server_epoch: snapshot.server_epoch, conversation_id: snapshot.conversation_id };
        revision = snapshot.conversation_revision;
        eventSeq = snapshot.event_seq || 0;
        const currentIds = new Set(snapshot.messages.map(message => message.id));
        for (const messageId of messages.keys()) {
            if (!currentIds.has(messageId)) {
                messages.delete(messageId);
                host.remove(messageId);
            }
        }
        snapshot.messages.forEach(upsert);
        processing = snapshot.processing || { phase: 'idle' };
        if (typeof snapshot.backend_pending === 'boolean') backendPending = snapshot.backend_pending;
        updatePending();
        return true;
    }

    function applyEvent(event) {
        if (event.op === 'reset') return applySnapshot({ ...event, messages: [] });
        if (!sameSession(event)) return false;
        if (Number.isSafeInteger(event.event_seq) && event.event_seq <= eventSeq) return false;
        if (event.conversation_revision < revision) return false;
        if (Number.isSafeInteger(event.event_seq)) eventSeq = event.event_seq;
        revision = event.conversation_revision;
        if (event.op === 'append' || event.op === 'replace') upsert(event.message);
        if (event.processing) processing = event.processing;
        updatePending();
        return true;
    }

    function receiveAdmission(result) {
        if (typeof result === 'string') result = JSON.parse(result);
        const submission = submissions.get(result.request_id);
        if (!submission) return;
        const accepted = result.state === 'accepted' || result.state === 'completed'
            || (result.state === 'failed' && Boolean(result.message_id));
        if (accepted && !submission.accepted) {
            submission.accepted = true;
            if (!submission.mutation && !submission.voice && host.readDraft().version === submission.draft.version) {
                host.clearDraft();
            }
        }
        if (['completed', 'failed', 'rejected'].includes(result.state)) {
            submissions.delete(result.request_id);
            if (result.state !== 'completed') {
                if (submission.voice && !submission.accepted) host.restoreVoice(submission.text);
                host.notice(result.code || 'request_failed');
            }
        }
        updatePending();
        if (submission.onResult) submission.onResult(result);
    }

    function submit(input) {
        if (!head) {
            if (input.voice) host.restoreVoice(input.text);
            host.notice('sync_required');
            return null;
        }
        const requestId = host.newId();
        const submission = { ...input, draft: host.readDraft(), accepted: false };
        submissions.set(requestId, submission);
        updatePending();
        try {
            host.send({
                ...head, request_id: requestId, text: input.text,
                attachments: input.attachments || [],
            }, receiveAdmission);
        } catch (_error) {
            receiveAdmission({ request_id: requestId, state: 'rejected', code: 'connection_failed' });
        }
        return requestId;
    }

    function captureTarget(messageId) {
        if (!head || !messages.has(messageId)) return null;
        return Object.freeze({ ...head, target_message_id: messageId, expected_revision: revision });
    }

    function trackMutation(requestId, onResult) {
        submissions.set(requestId, { mutation: true, onResult, accepted: false });
        updatePending();
    }

    function setBackendPending(active) {
        backendPending = Boolean(active);
        updatePending();
    }

    return { applySnapshot, applyEvent, submit, receiveAdmission, captureTarget, trackMutation, setBackendPending };
}

// 기존 렌더러와 입력 요소를 상태 모듈에 연결한다. 모델/기분 정보는 이 경계를 거치지 않는다.
function connectCompanionChatBridge(bridge) {
    if (!bridge || typeof bridge.submit_pc_chat !== 'function' || !bridge.chat_display_event) return null;
    let draftVersion = 0;
    const markDraftChanged = () => { draftVersion += 1; };
    const findMessage = messageId => Array.from(chatMessages.querySelectorAll('.message'))
        .find(node => node.dataset.messageId === messageId);
    const newId = () => {
        if (typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
        const bytes = window.crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    };
    const notice = code => {
        const messages = {
            busy: '다른 요청을 처리 중입니다. 입력 내용은 유지됩니다.',
            stale_target: '대화가 변경되었습니다. 수정 대상을 다시 확인해 주세요.',
            stale_session: '대화가 초기화되었습니다. 입력 내용을 확인한 뒤 다시 보내 주세요.',
            unsupported_command: '이 작업은 해당 경로에서 사용할 수 없습니다.',
            sync_required: '대화 상태를 확인 중입니다. 잠시 후 다시 보내 주세요.',
        };
        showToast(messages[code] || '요청을 처리하지 못했습니다. 내용을 확인한 뒤 다시 시도해 주세요.', 'error');
    };
    function applyEmotion(message) {
        if (message.role !== 'assistant') return;
        cancelPendingPatEmotionRestore();
        baseEmotionTag = message.emotion || 'normal';
        changeExpression(baseEmotionTag);
    }
    const runtime = createCompanionChatRuntime({
        newId,
        readDraft: () => ({ text: chatInput.value, attachments: attachedAttachments.map(item => ({ ...item })), version: draftVersion }),
        clearDraft: () => {
            chatInput.value = '';
            attachedAttachments = [];
            markDraftChanged();
            autoResizeTextarea();
            updateAttachmentPreview();
        },
        restoreVoice: text => {
            chatInput.value += (chatInput.value ? '\n' : '') + text;
            markDraftChanged();
            autoResizeTextarea();
        },
        render: message => {
            const node = addMessage(message.text, message.role, message.attachments || [], new Date(message.displayed_at), {
                messageId: message.id, thought: message.thought || '', excludeFromReroll: Boolean(message.local_only),
            });
            node.dataset.companionManaged = 'true';
            if (message.local_only) node.dataset.editExcluded = 'true';
            applyEmotion(message);
        },
        update: message => {
            const node = findMessage(message.id);
            if (!node) return;
            const attachments = message.attachments || getMessageVisualAttachments(node);
            const thought = message.thought === undefined ? getMessageThoughtText(node) : message.thought;
            if (getMessageLogicalText(node) !== message.text || getMessageThoughtText(node) !== thought
                || JSON.stringify(getMessageVisualAttachments(node)) !== JSON.stringify(attachments)) {
                renderMessageBubbleSegments(node, message.text, { attachments, thought, immediate: true });
            }
            updateRerollButtonState();
            applyEmotion(message);
        },
        remove: messageId => { const node = findMessage(messageId); if (node) node.remove(); },
        send: (payload, callback) => dispatchBridgeCall(() => {
            bridge.submit_pc_chat(JSON.stringify(payload), raw => {
                const result = typeof raw === 'string' ? JSON.parse(raw) : raw;
                callback({ ...result, request_id: payload.request_id });
            });
        }, () => callback({ request_id: payload.request_id, state: 'rejected', code: 'connection_failed' })),
        setPending: setRequestPending,
        notice,
    });
    runtime.markDraftChanged = markDraftChanged;
    runtime.submitMutation = (kind, target, text, onResult) => {
        if (!target) { notice('stale_target'); return; }
        const requestId = newId();
        runtime.trackMutation(requestId, onResult);
        const method = kind === 'edit' ? bridge.edit_companion_message : bridge.reroll_companion_message;
        dispatchBridgeCall(() => method.call(bridge, JSON.stringify({ ...target, request_id: requestId, ...(kind === 'edit' ? { text } : {}) }), raw => {
            const result = typeof raw === 'string' ? JSON.parse(raw) : raw;
            runtime.receiveAdmission({ ...result, request_id: requestId });
        }), () => runtime.receiveAdmission({ request_id: requestId, state: 'rejected', code: 'connection_failed' }));
    };
    window.eneCompanionChat = runtime;
    chatInput.addEventListener('input', markDraftChanged);
    bridge.chat_display_event.connect(raw => runtime.applyEvent(typeof raw === 'string' ? JSON.parse(raw) : raw));
    if (bridge.chat_admission_result) bridge.chat_admission_result.connect(runtime.receiveAdmission);
    bridge.get_companion_chat_state(raw => runtime.applySnapshot(typeof raw === 'string' ? JSON.parse(raw) : raw));
    return runtime;
}
