
function getActiveGoalItems(type) {
    const active = (eneGoalSnapshot && eneGoalSnapshot.active) || {};
    const items = active[type];
    return Array.isArray(items) ? items : [];
}

function normalizeGoalSnapshot(value) {
    let parsed = value;
    if (typeof value === 'string') {
        try {
            parsed = JSON.parse(value);
        } catch (error) {
            parsed = {};
        }
    }
    if (!parsed || typeof parsed !== 'object') {
        parsed = {};
    }
    const active = parsed.active && typeof parsed.active === 'object' ? parsed.active : {};
    return {
        ...parsed,
        active: {
            short_term: Array.isArray(active.short_term) ? active.short_term : [],
            long_term: Array.isArray(active.long_term) ? active.long_term : []
        },
        history: Array.isArray(parsed.history) ? parsed.history : []
    };
}

function setGoalPanelOpen(open) {
    goalPanelOpen = Boolean(open);
    if (goalPanel) {
        goalPanel.classList.toggle('hidden', !goalPanelOpen);
    }
}

function appendGoalSection(type, label) {
    const items = getActiveGoalItems(type);
    if (!goalStatusList || items.length === 0) {
        return;
    }

    const section = document.createElement('div');
    section.className = 'goal-status-section';

    const heading = document.createElement('div');
    heading.className = 'goal-status-section-title';
    heading.textContent = String(label || type);
    section.appendChild(heading);

    items.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'goal-status-item';

        const title = document.createElement('div');
        title.className = 'goal-status-title';
        title.textContent = String((item && item.title) || (item && item.id) || '');
        row.appendChild(title);

        if (item && item.reason) {
            const reason = document.createElement('div');
            reason.className = 'goal-status-reason';
            reason.textContent = String(item.reason);
            row.appendChild(reason);
        }

        const metaParts = [];
        if (item && item.type) metaParts.push(String(item.type));
        if (item && item.id) metaParts.push(String(item.id));
        if (metaParts.length) {
            const meta = document.createElement('div');
            meta.className = 'goal-status-meta';
            meta.textContent = metaParts.join(' · ');
            row.appendChild(meta);
        }

        section.appendChild(row);
    });

    goalStatusList.appendChild(section);
}

function renderGoalPanel() {
    if (!goalStatusList) {
        return;
    }

    const goalPanelStrings = (currentUiStrings && currentUiStrings.goalPanel)
        ? currentUiStrings.goalPanel
        : DEFAULT_UI_STRINGS.goalPanel;
    goalStatusList.textContent = '';

    appendGoalSection('short_term', goalPanelStrings.shortTerm);
    appendGoalSection('long_term', goalPanelStrings.longTerm);

    if (!goalStatusList.children.length) {
        const empty = document.createElement('div');
        empty.className = 'goal-status-empty';
        empty.textContent = goalPanelStrings.empty;
        goalStatusList.appendChild(empty);
    }
}

window.setGoalItems = function setGoalItems(value) {
    eneGoalSnapshot = normalizeGoalSnapshot(value);
    renderGoalPanel();
};

window.showPromiseReminderNotice = function showPromiseReminderNotice(message) {
    const fallback = (currentUiStrings && currentUiStrings.promiseNotice)
        ? currentUiStrings.promiseNotice.saved
        : DEFAULT_UI_STRINGS.promiseNotice.saved;
    const text = String(message || fallback);
    showPromiseNoticeBubble(text);
};

window.setInterval(() => {
    if (!promiseRemindersPanel || !getVisiblePromiseReminderItems().length) {
        return;
    }
    renderPromiseReminderPanel();
}, 30000);

window.setTokenUsageBubbleEnabled = function (enabled) {
    tokenUsageBubbleVisibleBySetting = Boolean(enabled);
    if (!tokenUsageBubbleVisibleBySetting) {
        if (tokenUsageBubbleTimer) {
            clearTimeout(tokenUsageBubbleTimer);
            tokenUsageBubbleTimer = null;
        }
        hideTokenUsageBubble();
    }
};
