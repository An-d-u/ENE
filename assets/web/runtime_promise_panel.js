
function formatPromiseReminderTemplate(template, minutes) {
    return String(template || '').replace('{minutes}', String(minutes));
}

function getVisiblePromiseReminderItems() {
    return promiseReminderItems.filter((item) => {
        const status = String((item && item.status) || '');
        return status === 'scheduled' || status === 'queued' || status === 'missed';
    });
}

function formatPromiseReminderTime(triggerAt, status = 'scheduled') {
    const promisePanelStrings = (currentUiStrings && currentUiStrings.promisePanel)
        ? currentUiStrings.promisePanel
        : DEFAULT_UI_STRINGS.promisePanel;
    if (status === 'queued') {
        return promisePanelStrings.queued;
    }

    const parsed = new Date(triggerAt);
    if (Number.isNaN(parsed.getTime())) {
        return String(triggerAt || '');
    }

    const diffMs = parsed.getTime() - Date.now();
    const diffMinutes = Math.round(diffMs / 60000);
    if (diffMinutes > 0) {
        return formatPromiseReminderTemplate(promisePanelStrings.inMinutes, diffMinutes);
    }
    if (diffMinutes === 0) {
        return promisePanelStrings.soon;
    }
    return formatPromiseReminderTemplate(promisePanelStrings.overdueMinutes, Math.abs(diffMinutes));
}

function formatPromiseReminderClock(triggerAt) {
    const parsed = new Date(triggerAt);
    if (Number.isNaN(parsed.getTime())) {
        return '';
    }
    return parsed.toLocaleString([], {
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
    });
}

function setPromiseRemindersPanelOpen(open) {
    if (!promiseRemindersPanel) {
        return;
    }
    promiseRemindersPanel.classList.toggle('hidden', !open);
}

function renderPromiseReminderPanel() {
    if (!promiseRemindersList) {
        return;
    }

    const promisePanelStrings = (currentUiStrings && currentUiStrings.promisePanel)
        ? currentUiStrings.promisePanel
        : DEFAULT_UI_STRINGS.promisePanel;
    const visibleItems = getVisiblePromiseReminderItems();
    promiseRemindersList.textContent = '';
    if (!visibleItems.length) {
        const empty = document.createElement('div');
        empty.className = 'promise-reminder-meta';
        empty.textContent = promisePanelStrings.empty;
        promiseRemindersList.appendChild(empty);
        return;
    }

    visibleItems.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'promise-reminder-item';

        const textWrap = document.createElement('div');
        textWrap.className = 'promise-reminder-text';

        const title = document.createElement('div');
        title.className = 'promise-reminder-title';
        title.textContent = String((item && item.title) || '');

        const meta = document.createElement('div');
        meta.className = 'promise-reminder-meta';
        const timeText = formatPromiseReminderTime(item && item.trigger_at, item && item.status);
        const clockText = formatPromiseReminderClock(item && item.trigger_at);
        meta.textContent = clockText ? `${timeText} · ${clockText}` : timeText;

        textWrap.appendChild(title);
        textWrap.appendChild(meta);
        row.appendChild(textWrap);

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'promise-reminder-remove';
        removeButton.textContent = '×';
        removeButton.addEventListener('click', () => {
            if (!window.pyBridge || !window.pyBridge.delete_promise_reminder) {
                return;
            }
            window.pyBridge.delete_promise_reminder(String((item && item.id) || ''));
        });
        row.appendChild(removeButton);
        promiseRemindersList.appendChild(row);
    });
}

window.setPromiseReminderItems = function setPromiseReminderItems(items) {
    let normalized = items;
    if (typeof items === 'string') {
        try {
            normalized = JSON.parse(items);
        } catch (error) {
            normalized = [];
        }
    }
    promiseReminderItems = Array.isArray(normalized) ? normalized : [];
    renderPromiseReminderPanel();
};

function formatProactiveConversationTemplate(template, minutes) {
    return String(template || '').replace('{minutes}', String(minutes));
}

function getVisibleProactiveConversationItems() {
    return proactiveConversationItems.filter((item) => {
        const status = String((item && item.status) || '');
        return status === 'scheduled' || status === 'queued';
    });
}

function formatProactiveConversationTime(triggerAt, status = 'scheduled') {
    const proactivePanelStrings = (currentUiStrings && currentUiStrings.proactivePanel)
        ? currentUiStrings.proactivePanel
        : DEFAULT_UI_STRINGS.proactivePanel;
    if (status === 'queued') {
        return proactivePanelStrings.queued;
    }

    const parsed = new Date(triggerAt);
    if (Number.isNaN(parsed.getTime())) {
        return String(triggerAt || '');
    }

    const diffMs = parsed.getTime() - Date.now();
    const diffMinutes = Math.round(diffMs / 60000);
    if (diffMinutes > 0) {
        return formatProactiveConversationTemplate(proactivePanelStrings.inMinutes, diffMinutes);
    }
    if (diffMinutes === 0) {
        return proactivePanelStrings.soon;
    }
    return formatProactiveConversationTemplate(proactivePanelStrings.overdueMinutes, Math.abs(diffMinutes));
}

function formatProactiveConversationClock(triggerAt) {
    const parsed = new Date(triggerAt);
    if (Number.isNaN(parsed.getTime())) {
        return '';
    }
    return parsed.toLocaleString([], {
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
    });
}

function setProactiveConversationPanelOpen(open) {
    proactiveConversationPanelOpen = Boolean(open);
    if (!proactiveConversationsPanel) {
        return;
    }
    proactiveConversationsPanel.classList.toggle('hidden', !proactiveConversationPanelOpen);
}

function renderProactiveConversationPanel() {
    if (!proactiveConversationsList) {
        return;
    }

    const proactivePanelStrings = (currentUiStrings && currentUiStrings.proactivePanel)
        ? currentUiStrings.proactivePanel
        : DEFAULT_UI_STRINGS.proactivePanel;
    const visibleItems = getVisibleProactiveConversationItems();
    proactiveConversationsList.textContent = '';
    if (!visibleItems.length) {
        const empty = document.createElement('div');
        empty.className = 'proactive-conversation-meta';
        empty.textContent = proactivePanelStrings.empty;
        proactiveConversationsList.appendChild(empty);
        return;
    }

    visibleItems.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'proactive-conversation-item';

        const textWrap = document.createElement('div');
        textWrap.className = 'proactive-conversation-text';

        const title = document.createElement('div');
        title.className = 'proactive-conversation-title';
        title.textContent = String((item && item.title) || '');

        const meta = document.createElement('div');
        meta.className = 'proactive-conversation-meta';
        const timeText = formatProactiveConversationTime(item && item.trigger_at, item && item.status);
        const clockText = formatProactiveConversationClock(item && item.trigger_at);
        meta.textContent = clockText ? `${timeText} · ${clockText}` : timeText;

        textWrap.appendChild(title);
        textWrap.appendChild(meta);
        row.appendChild(textWrap);

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'proactive-conversation-remove';
        removeButton.textContent = '×';
        removeButton.setAttribute('aria-label', proactivePanelStrings.remove);
        removeButton.title = proactivePanelStrings.remove;
        removeButton.addEventListener('click', () => {
            if (!window.pyBridge || !window.pyBridge.delete_proactive_conversation) {
                return;
            }
            window.pyBridge.delete_proactive_conversation(String((item && item.id) || ''));
        });
        row.appendChild(removeButton);
        proactiveConversationsList.appendChild(row);
    });
}

window.setProactiveConversationItems = function setProactiveConversationItems(items) {
    let normalized = items;
    if (typeof items === 'string') {
        try {
            normalized = JSON.parse(items);
        } catch (error) {
            normalized = [];
        }
    }
    proactiveConversationItems = Array.isArray(normalized) ? normalized : [];
    renderProactiveConversationPanel();
};

setInterval(() => {
    renderProactiveConversationPanel();
}, 30000);
