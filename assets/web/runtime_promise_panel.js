
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
