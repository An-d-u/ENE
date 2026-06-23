
function createTextMessageBubble() {
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    const textSpan = document.createElement('span');
    bubble.appendChild(textSpan);
    return { bubble, textSpan };
}

function createMessageThoughtDisclosure(thought) {
    const normalizedThought = normalizeMessageThoughtText(thought);
    if (!thoughtFeatureEnabled || !normalizedThought) {
        return null;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'message-thought';

    const body = document.createElement('div');
    body.className = 'message-thought-body';
    body.textContent = normalizedThought;
    body.hidden = true;

    wrapper.appendChild(body);
    return wrapper;
}

function renderMessageThoughtDisclosure(messageDiv, stack, thought) {
    if (!messageDiv || !stack || !messageDiv.classList.contains('assistant')) {
        return;
    }

    const previousDisclosure = stack.querySelector('.message-thought');
    if (previousDisclosure) {
        previousDisclosure.remove();
    }
    const thoughtDisclosure = createMessageThoughtDisclosure(thought);
    if (thoughtDisclosure) {
        stack.appendChild(thoughtDisclosure);
    }
}

function renderMessageBubbleSegments(messageDiv, text, { attachments = null, immediate = false, thought = null } = {}) {
    if (!messageDiv) {
        return Promise.resolve();
    }

    const stack = getMessageBubbleStack(messageDiv);
    const normalizedText = setMessageLogicalText(messageDiv, text);
    const resolvedThought = thought === null
        ? getMessageThoughtText(messageDiv)
        : setMessageThoughtText(messageDiv, thought);
    const resolvedAttachments = attachments === null
        ? getMessageVisualAttachments(messageDiv)
        : normalizeMessageAttachments(attachments);

    messageDiv._messageAttachments = resolvedAttachments;

    if (activeInlineEditMessageEl === messageDiv) {
        closeInlineEdit(messageDiv, false);
    }

    stack.classList.remove('is-editing');
    stack.querySelectorAll('.message-bubble span').forEach((textNode) => cancelMessageTyping(textNode));
    stack.innerHTML = '';

    const attachmentBubbles = createMessageAttachmentBubbles(messageDiv, resolvedAttachments);
    attachmentBubbles.forEach((attachmentBubble) => {
        stack.appendChild(attachmentBubble);
    });

    const segments = splitMessageIntoVisualChunks(text);
    if (attachmentBubbles.length === 0 && segments.length === 0) {
        segments.push('');
    }

    let animationQueue = Promise.resolve();
    segments.forEach((segment) => {
        animationQueue = animationQueue.then(() => {
            const { bubble, textSpan } = createTextMessageBubble();
            stack.appendChild(bubble);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            return animateMessageText(textSpan, segment, { immediate });
        });
    });

    chatMessages.scrollTop = chatMessages.scrollHeight;
    return animationQueue.then(() => {
        renderMessageThoughtDisclosure(messageDiv, stack, resolvedThought);
        updateMessageThoughtButtons();
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
}

// 인라인 수정 UI를 닫고 표시 상태를 정리한다.
function closeInlineEdit(messageDiv, keepText = true) {
    if (!messageDiv) return;
    const stack = getMessageBubbleStack(messageDiv);
    const editor = stack ? stack.querySelector('.inline-edit-wrap') : null;
    if (editor) editor.remove();
    if (stack && keepText) {
        stack.classList.remove('is-editing');
    }
    if (activeInlineEditMessageEl === messageDiv) {
        activeInlineEditMessageEl = null;
    }
}

// 최근 user 메시지 버블 안에서 인라인 수정 편집기를 연다.
function openInlineEdit(messageDiv) {
    if (!messageDiv) return;
    const stack = getMessageBubbleStack(messageDiv);
    if (!stack) return;

    if (activeInlineEditMessageEl && activeInlineEditMessageEl !== messageDiv) {
        closeInlineEdit(activeInlineEditMessageEl, true);
    }
    if (stack.querySelector('.inline-edit-wrap')) {
        return;
    }

    const currentText = getMessageLogicalText(messageDiv);
    stack.classList.add('is-editing');

    const wrap = document.createElement('div');
    wrap.className = 'inline-edit-wrap';

    const input = document.createElement('textarea');
    input.className = 'inline-edit-input';
    input.value = currentText || '';
    input.rows = 2;

    const actions = document.createElement('div');
    actions.className = 'inline-edit-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'inline-edit-cancel';
    cancelBtn.textContent = '취소';
    cancelBtn.type = 'button';

    const saveBtn = document.createElement('button');
    saveBtn.className = 'inline-edit-save';
    saveBtn.textContent = '저장';
    saveBtn.type = 'button';

    const commit = () => {
        const trimmed = (input.value || '').trim();
        if (!trimmed) return;
        if (!window.pyBridge || !window.pyBridge.edit_last_user_message) return;
        if (isRequestPending) return;

        closeInlineEdit(messageDiv, false);
        renderMessageBubbleSegments(messageDiv, trimmed, {
            attachments: getMessageVisualAttachments(messageDiv),
            immediate: true
        });
        shouldReplaceNextAssistant = true;
        setRequestPending(true);
        dispatchBridgeCall(() => {
            window.pyBridge.edit_last_user_message(trimmed);
        }, (error) => {
            console.error("Python bridge edit retry failed", error);
            addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date(), { excludeFromReroll: true });
            shouldReplaceNextAssistant = false;
            setRequestPending(false);
        });
    };

    cancelBtn.addEventListener('click', () => closeInlineEdit(messageDiv, true));
    saveBtn.addEventListener('click', commit);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closeInlineEdit(messageDiv, true);
        }
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    wrap.appendChild(input);
    wrap.appendChild(actions);
    stack.appendChild(wrap);
    activeInlineEditMessageEl = messageDiv;

    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
}

// 수동 요약 버튼 클릭 시 확인 모달을 띄운다.
function requestManualSummary() {
    if (!isManualSummaryBridgeAvailable()) return;
    if (isRequestPending) return;
    showSummaryConfirm();
}

function resolveTypingIntervalMs(text) {
    const chars = Array.from(String(text || ''));
    if (chars.length <= 1) {
        return MESSAGE_TYPING_BASE_INTERVAL_MS;
    }

    const speedMultiplier = MESSAGE_TYPING_SPEED_MULTIPLIERS[typingEffectSpeed] || MESSAGE_TYPING_SPEED_MULTIPLIERS.normal;
    const configuredBaseInterval = Math.round(MESSAGE_TYPING_BASE_INTERVAL_MS * speedMultiplier);
    const configuredMaxDuration = Math.round(MESSAGE_TYPING_MAX_DURATION_MS * speedMultiplier);
    const boundedByDuration = Math.floor(configuredMaxDuration / chars.length);
    return Math.max(
        MESSAGE_TYPING_MIN_INTERVAL_MS,
        Math.min(configuredBaseInterval, boundedByDuration)
    );
}

function cancelMessageTyping(textNode) {
    if (!textNode) return;
    if (typeof textNode._typingTimerId === 'number') {
        window.clearTimeout(textNode._typingTimerId);
    }
    textNode._typingTimerId = null;
    textNode._typingRunId = null;
    const bubble = textNode.closest('.message-bubble');
    if (bubble) {
        bubble.classList.remove('is-typing');
    }
}

function animateMessageText(textNode, text, { immediate = false } = {}) {
    if (!textNode) return Promise.resolve();

    const resolvedText = String(text || '');
    cancelMessageTyping(textNode);

    const bubble = textNode.closest('.message-bubble');
    if (!resolvedText || immediate || !typingEffectEnabled) {
        textNode.textContent = resolvedText;
        if (bubble) {
            bubble.classList.remove('is-typing');
        }
        return Promise.resolve();
    }

    const chars = Array.from(resolvedText);
    const intervalMs = resolveTypingIntervalMs(resolvedText);
    let index = 0;
    const runId = Symbol('messageTyping');
    textNode.textContent = '';
    textNode._typingRunId = runId;
    if (bubble) {
        bubble.classList.add('is-typing');
    }

    return new Promise((resolve) => {
        const step = () => {
            if (textNode._typingRunId !== runId) {
                resolve();
                return;
            }

            index += 1;
            textNode.textContent = chars.slice(0, index).join('');
            chatMessages.scrollTop = chatMessages.scrollHeight;

            if (index >= chars.length) {
                textNode._typingTimerId = null;
                textNode._typingRunId = null;
                if (bubble) {
                    bubble.classList.remove('is-typing');
                }
                resolve();
                return;
            }

            textNode._typingTimerId = window.setTimeout(step, intervalMs);
        };

        textNode._typingTimerId = window.setTimeout(step, intervalMs);
    });
}

window.setTypingEffectConfig = function (config) {
    const source = config || {};
    typingEffectEnabled = source.enabled !== false;
    const nextSpeed = String(source.speed || 'normal').trim().toLowerCase();
    typingEffectSpeed = MESSAGE_TYPING_SPEED_MULTIPLIERS[nextSpeed] ? nextSpeed : 'normal';
    window.eneTypingEffectConfig = {
        enabled: typingEffectEnabled,
        speed: typingEffectSpeed
    };
};

window.setMessageSplitConfig = function (config) {
    const source = config || {};
    messageSplitEnabled = source.enabled === true;
    window.eneMessageSplitConfig = {
        enabled: messageSplitEnabled
    };
};

window.setThoughtFeatureEnabled = function (enabled) {
    thoughtFeatureEnabled = enabled !== false;
    window.eneThoughtFeatureConfig = {
        enabled: thoughtFeatureEnabled
    };
    document.body.classList.toggle('thought-feature-disabled', !thoughtFeatureEnabled);
    updateMessageThoughtButtons();
};

// 리롤/수정 응답 수신 시 마지막 assistant 버블 내용을 교체한다.
function replaceLastAssistantMessage(text, timestamp = new Date(), thought = '') {
    if (!lastAssistantMessageEl || !chatMessages.contains(lastAssistantMessageEl)) {
        syncLastAssistantMessageRef();
    }
    if (!lastAssistantMessageEl) {
        return false;
    }

    lastAssistantMessageEl.dataset.messageTimestamp = normalizeMessageTimestampValue(timestamp);
    const rail = ensureMessageMetaRail(lastAssistantMessageEl, 'assistant', timestamp);
    if (rail && rail.parentElement !== lastAssistantMessageEl) {
        lastAssistantMessageEl.appendChild(rail);
    }
    renderMessageBubbleSegments(lastAssistantMessageEl, text, {
        attachments: getMessageVisualAttachments(lastAssistantMessageEl),
        immediate: false,
        thought
    });
    return true;
}

/**
 * 채팅 영역에 메시지 버블을 추가한다.
 */
// 채팅 메시지(텍스트/첨부)를 DOM에 append하고 상태를 갱신한다.
function addMessage(text, role, attachments = [], timestamp = new Date(), options = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.dataset.messageTimestamp = normalizeMessageTimestampValue(timestamp);
    messageDiv.dataset.messageId = (options && typeof options.messageId === 'string' && options.messageId.trim())
        ? options.messageId.trim()
        : `message-${createAttachmentId()}`;
    if (role === 'assistant' && options && options.excludeFromReroll) {
        messageDiv.dataset.rerollExcluded = 'true';
    }
    setMessageLogicalText(messageDiv, text);
    setMessageThoughtText(messageDiv, role === 'assistant' ? (options.thought || '') : '');
    messageDiv._messageAttachments = normalizeMessageAttachments(attachments);
    const bubbleStack = getMessageBubbleStack(messageDiv);

    const metaRail = ensureMessageMetaRail(messageDiv, role, timestamp);
    if (role === 'user') {
        if (metaRail) {
            messageDiv.appendChild(metaRail);
        }
        messageDiv.appendChild(bubbleStack);
    } else {
        messageDiv.appendChild(bubbleStack);
        if (metaRail) {
            messageDiv.appendChild(metaRail);
        }
    }
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    if (role === 'assistant') {
        hasAssistantMessage = true;
        lastAssistantMessageEl = messageDiv;
    } else if (role === 'user') {
        hasUserMessage = true;
        lastUserMessageEl = messageDiv;
    }
    renderMessageBubbleSegments(messageDiv, text, {
        attachments: messageDiv._messageAttachments,
        immediate: false,
        thought: role === 'assistant' ? (options.thought || '') : ''
    });
    updateRerollButtonState();
    return messageDiv;
}
