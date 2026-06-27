
/**
 * 로딩 인디케이터 표시 상태를 갱신한다.
 */
// 요청 진행 중 로딩 인디케이터를 표시/숨김 처리한다.
function getRequestPendingLoadingText() {
    if (requestPendingStage === 'searching') {
        return (currentUiStrings && currentUiStrings.loadingSearching)
            || DEFAULT_UI_STRINGS.loadingSearching
            || (currentUiStrings && currentUiStrings.loading)
            || DEFAULT_UI_STRINGS.loading;
    }
    return (currentUiStrings && currentUiStrings.loading) || DEFAULT_UI_STRINGS.loading;
}

function updateLoadingIndicatorText() {
    if (loadingText) {
        loadingText.textContent = getRequestPendingLoadingText();
    }
}

function normalizeRequestPendingStage(stage) {
    const normalized = String(stage || '').trim().toLowerCase();
    return normalized === 'searching' ? 'searching' : 'thinking';
}

function showLoadingIndicator(show) {
    if (loadingIndicator) {
        if (show) {
            updateLoadingIndicatorText();
            if (loadingIndicator.parentElement !== chatMessages) {
                chatMessages.appendChild(loadingIndicator);
            }
            loadingIndicator.style.display = 'inline-flex';
            chatMessages.scrollTop = chatMessages.scrollHeight;
            return;
        }
        loadingIndicator.style.display = 'none';
        if (loadingIndicator.parentElement === chatMessages && loadingIndicatorAnchor && imagePreviewContainer) {
            loadingIndicatorAnchor.insertBefore(loadingIndicator, imagePreviewContainer);
        }
    }
}

function updateRequestInputControls() {
    if (sendButton) {
        sendButton.disabled = isRequestPending;
    }
    if (activeInlineEditMessageEl) {
        const saveBtn = activeInlineEditMessageEl.querySelector('.inline-edit-save');
        if (saveBtn) {
            saveBtn.disabled = isRequestPending;
        }
    }
}

function setRequestPending(active) {
    isRequestPending = Boolean(active);
    if (!isRequestPending) {
        requestPendingStage = 'thinking';
    }
    showLoadingIndicator(isRequestPending);
    updateRequestInputControls();
    updateRerollButtonState();
}

function setRequestPendingStage(stage) {
    requestPendingStage = normalizeRequestPendingStage(stage);
    if (isRequestPending) {
        updateLoadingIndicatorText();
    }
}

// 최근 assistant 메시지 DOM 참조를 재동기화한다.
function syncLastAssistantMessageRef() {
    const nodes = chatMessages.querySelectorAll('.message.assistant:not([data-reroll-excluded="true"])');
    if (!nodes || nodes.length === 0) {
        lastAssistantMessageEl = null;
        hasAssistantMessage = false;
        return;
    }
    lastAssistantMessageEl = nodes[nodes.length - 1];
    hasAssistantMessage = true;
}

// 최근 user 메시지 DOM 참조를 재동기화한다.
function syncLastUserMessageRef() {
    const nodes = chatMessages.querySelectorAll('.message.user');
    if (!nodes || nodes.length === 0) {
        lastUserMessageEl = null;
        hasUserMessage = false;
        return;
    }
    lastUserMessageEl = nodes[nodes.length - 1];
    hasUserMessage = true;
}

function parseMessageTimeValue(value) {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        return value;
    }
    if (typeof value === 'string') {
        const trimmed = value.trim();
        const match = trimmed.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/);
        if (match) {
            const [, year, month, day, hour, minute] = match;
            return new Date(
                Number(year),
                Number(month) - 1,
                Number(day),
                Number(hour),
                Number(minute),
            );
        }
        const parsed = new Date(trimmed);
        if (!Number.isNaN(parsed.getTime())) {
            return parsed;
        }
    }
    return new Date();
}

function formatMessageTime(value = new Date()) {
    const date = parseMessageTimeValue(value);
    const hours24 = date.getHours();
    const meridiem = hours24 >= 12 ? 'PM' : 'AM';
    let hours12 = hours24 % 12;
    if (hours12 === 0) {
        hours12 = 12;
    }
    const hourText = String(hours12).padStart(2, '0');
    const minuteText = String(date.getMinutes()).padStart(2, '0');
    return `${meridiem} ${hourText}:${minuteText}`;
}

function normalizeMessageTimestampValue(value = null) {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        const year = value.getFullYear();
        const month = String(value.getMonth() + 1).padStart(2, '0');
        const day = String(value.getDate()).padStart(2, '0');
        const hour = String(value.getHours()).padStart(2, '0');
        const minute = String(value.getMinutes()).padStart(2, '0');
        return `${year}-${month}-${day} ${hour}:${minute}`;
    }
    if (typeof value === 'string') {
        const trimmed = value.trim();
        if (trimmed) {
            return trimmed;
        }
    }
    return normalizeMessageTimestampValue(new Date());
}

function getStoredMessageTimestamp(messageDiv) {
    if (!messageDiv || !messageDiv.dataset) return '';
    return String(messageDiv.dataset.messageTimestamp || '').trim();
}

function ensureMessageMetaRail(messageDiv, role, timestamp = null) {
    if (!messageDiv) return null;
    const normalizedTimestamp = normalizeMessageTimestampValue(timestamp || getStoredMessageTimestamp(messageDiv));
    if (messageDiv.dataset) {
        messageDiv.dataset.messageTimestamp = normalizedTimestamp;
    }
    let rail = messageDiv.querySelector('.message-meta-rail');
    if (!rail) {
        rail = document.createElement('div');
        rail.className = 'message-meta-rail';
        const timeLabel = document.createElement('span');
        timeLabel.className = 'message-time';
        rail.appendChild(timeLabel);
    }

    rail.classList.toggle('user', role === 'user');
    rail.classList.toggle('assistant', role === 'assistant');
    rail.dataset.role = role;
    rail.dataset.timestamp = normalizedTimestamp;

    const timeLabel = rail.querySelector('.message-time');
    if (timeLabel) {
        timeLabel.textContent = formatMessageTime(normalizedTimestamp);
    }
    return rail;
}

// 리롤/수정/수동요약 버튼의 표시 및 활성 상태를 재평가한다.
function isManualSummaryBridgeAvailable() {
    return !!window.pyBridge && typeof window.pyBridge.summarize_now === 'function';
}

function updateRerollButtonState() {
    updateRequestInputControls();

    if (manualSummarizeButton) {
        const enabledByBridge = isManualSummaryBridgeAvailable();
        manualSummarizeButton.style.display = manualSummaryButtonVisibleBySetting ? 'inline-flex' : 'none';
        manualSummarizeButton.disabled = isRequestPending || !enabledByBridge;
    }
    if (summaryConfirmYesButton) {
        summaryConfirmYesButton.disabled = isRequestPending || !isManualSummaryBridgeAvailable();
    }

    syncLastAssistantMessageRef();
    syncLastUserMessageRef();

    const oldButtons = chatMessages.querySelectorAll('.message-reroll-btn');
    oldButtons.forEach(btn => btn.remove());
    const oldEditButtons = chatMessages.querySelectorAll('.message-edit-btn');
    oldEditButtons.forEach(btn => btn.remove());

    if (rerollButtonVisibleBySetting && hasAssistantMessage && lastAssistantMessageEl) {
        const btn = document.createElement('button');
        btn.className = 'message-reroll-btn';
        btn.type = 'button';
        btn.innerHTML = createLucideIcon('rotate-ccw');
        btn.title = '최근 ENE 답변 다시 생성';
        btn.setAttribute('aria-label', '최근 ENE 답변 다시 생성');
        btn.disabled = isRequestPending || !window.pyBridge || !window.pyBridge.reroll_last_response;
        btn.addEventListener('click', () => {
            if (!window.pyBridge || !window.pyBridge.reroll_last_response) return;
            if (isRequestPending) return;
            setRequestPending(true);
            dispatchBridgeCall(() => {
                window.pyBridge.reroll_last_response();
            }, (error) => {
                console.error("Python bridge reroll failed", error);
                shouldReplaceNextAssistant = false;
                setRequestPending(false);
            });
        });
        const assistantRail = ensureMessageMetaRail(
            lastAssistantMessageEl,
            'assistant',
            lastAssistantMessageEl.dataset.messageTimestamp,
        );
        if (assistantRail) {
            assistantRail.appendChild(btn);
        }
    }

    updateMessageThoughtButtons();

    if (!recentEditButtonVisibleBySetting || !hasUserMessage || !lastUserMessageEl) {
        return;
    }
    const userBubbleStack = lastUserMessageEl.querySelector('.message-bubble-stack');
    if (!userBubbleStack) {
        return;
    }
    const editBtn = document.createElement('button');
    editBtn.className = 'message-edit-btn';
    editBtn.type = 'button';
    editBtn.innerHTML = createLucideIcon('pencil');
    editBtn.title = '최근 메시지 수정';
    editBtn.setAttribute('aria-label', '최근 메시지 수정');
    editBtn.disabled = isRequestPending || !window.pyBridge || !window.pyBridge.edit_last_user_message;
    editBtn.addEventListener('click', () => {
        if (!window.pyBridge || !window.pyBridge.edit_last_user_message) return;
        if (isRequestPending) return;
        openInlineEdit(lastUserMessageEl);
    });
    const userRail = ensureMessageMetaRail(
        lastUserMessageEl,
        'user',
        lastUserMessageEl.dataset.messageTimestamp,
    );
    if (!userRail) {
        return;
    }
    userRail.appendChild(editBtn);
}

// 설정창 값에 따라 리롤 버튼 표시 여부를 반영한다.
window.setRerollButtonEnabled = function (enabled) {
    rerollButtonVisibleBySetting = Boolean(enabled);
    updateRerollButtonState();
};

// 설정창 값에 따라 최근 메시지 수정 버튼 표시 여부를 반영한다.
window.setRecentEditButtonEnabled = function (enabled) {
    recentEditButtonVisibleBySetting = Boolean(enabled);
    updateRerollButtonState();
};

// 설정창 값에 따라 수동 요약 버튼 표시 여부를 반영한다.
window.setManualSummaryButtonEnabled = function (enabled) {
    manualSummaryButtonVisibleBySetting = Boolean(enabled);
    updateRerollButtonState();
};

// 설정창 값에 따라 기분 버튼 표시 여부를 반영한다.
window.setMoodToggleButtonEnabled = function (enabled) {
    moodToggleButtonVisibleBySetting = Boolean(enabled);
    if (moodToggleButton) {
        moodToggleButton.style.display = moodToggleButtonVisibleBySetting ? 'inline-flex' : 'none';
    }
    if (!moodToggleButtonVisibleBySetting) {
        setMoodPanelOpen(false);
    }
};

// 설정창 값에 따라 선제 대화 확인 버튼 표시 여부를 반영한다.
window.setProactiveConversationButtonEnabled = function setProactiveConversationButtonEnabled(enabled) {
    proactiveConversationButtonVisibleBySetting = Boolean(enabled);
    if (proactiveConversationsButton) {
        proactiveConversationsButton.style.display = proactiveConversationButtonVisibleBySetting ? 'inline-flex' : 'none';
    }
    if (!proactiveConversationButtonVisibleBySetting) {
        setProactiveConversationPanelOpen(false);
    }
};

// 설정창 값에 따라 목표 버튼 표시 여부를 반영한다.
window.setGoalButtonEnabled = function setGoalButtonEnabled(enabled) {
    goalButtonVisibleBySetting = Boolean(enabled);
    if (goalButton) {
        goalButton.style.display = goalButtonVisibleBySetting ? 'inline-flex' : 'none';
    }
    if (!goalButtonVisibleBySetting) {
        setGoalPanelOpen(false);
    }
};

// 설정창 값에 따라 노트 버튼 표시 여부를 반영한다.
window.setObsidianNoteButtonEnabled = function (enabled) {
    obsidianNoteButtonVisibleBySetting = Boolean(enabled);
    if (obsNoteButton) {
        obsNoteButton.style.display = obsidianNoteButtonVisibleBySetting ? 'inline-flex' : 'none';
    }
};

function hideTokenUsageBubble() {
    if (!tokenUsageBubble) return;
    tokenUsageBubble.classList.add('hidden');
}

function formatTokenUsageValue(value) {
    return Number.isInteger(value) ? String(value) : 'N/A';
}

function showTokenUsageBubble(payload) {
    if (!tokenUsageBubble || !tokenUsageBubbleVisibleBySetting) {
        return;
    }

    let usage = payload;
    if (typeof payload === 'string') {
        try {
            usage = JSON.parse(payload);
        } catch (error) {
            usage = null;
        }
    }

    const inputTokens = formatTokenUsageValue(usage && usage.input_tokens);
    const outputTokens = formatTokenUsageValue(usage && usage.output_tokens);
    tokenUsageBubble.textContent = `입력 토큰: ${inputTokens} / 출력 토큰: ${outputTokens}`;
    tokenUsageBubble.classList.remove('hidden');

    if (tokenUsageBubbleTimer) {
        clearTimeout(tokenUsageBubbleTimer);
    }
    tokenUsageBubbleTimer = setTimeout(() => {
        hideTokenUsageBubble();
        tokenUsageBubbleTimer = null;
    }, 3000);
}

function hidePromiseNoticeBubble() {
    if (!promiseNoticeBubble) return;
    promiseNoticeBubble.classList.add('hidden');
}

function showPromiseNoticeBubble(message) {
    if (!promiseNoticeBubble || !message) {
        return;
    }

    promiseNoticeBubble.textContent = String(message);
    promiseNoticeBubble.classList.remove('hidden');

    if (promiseNoticeBubbleTimer) {
        clearTimeout(promiseNoticeBubbleTimer);
    }
    promiseNoticeBubbleTimer = setTimeout(() => {
        hidePromiseNoticeBubble();
        promiseNoticeBubbleTimer = null;
    }, 3000);
}
