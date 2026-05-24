
function mergeUiStrings(config) {
    const source = config || {};
    const input = source.input || {};
    const actions = source.actions || {};
    const mood = source.mood || {};
    const moodAxis = mood.axis || {};
    const moodStates = mood.states || {};
    const moodTemporaryStates = mood.temporaryStates || {};
    const summaryConfirm = source.summaryConfirm || {};
    const promiseNotice = source.promiseNotice || {};
    const promisePanel = source.promisePanel || {};
    const goalPanel = source.goalPanel || {};
    const thoughts = source.thoughts || {};

    return {
        loading: source.loading || DEFAULT_UI_STRINGS.loading,
        input: {
            placeholder: input.placeholder || DEFAULT_UI_STRINGS.input.placeholder
        },
        send: source.send || DEFAULT_UI_STRINGS.send,
        actions: {
            summary: {
                label: (actions.summary && actions.summary.label) || DEFAULT_UI_STRINGS.actions.summary.label,
                title: (actions.summary && actions.summary.title) || DEFAULT_UI_STRINGS.actions.summary.title
            },
            note: {
                label: (actions.note && actions.note.label) || DEFAULT_UI_STRINGS.actions.note.label,
                title: (actions.note && actions.note.title) || DEFAULT_UI_STRINGS.actions.note.title
            },
            mood: {
                label: (actions.mood && actions.mood.label) || DEFAULT_UI_STRINGS.actions.mood.label,
                title: (actions.mood && actions.mood.title) || DEFAULT_UI_STRINGS.actions.mood.title
            },
            promises: {
                label: (actions.promises && actions.promises.label) || DEFAULT_UI_STRINGS.actions.promises.label,
                title: (actions.promises && actions.promises.title) || DEFAULT_UI_STRINGS.actions.promises.title
            },
            goals: {
                label: (actions.goals && actions.goals.label) || DEFAULT_UI_STRINGS.actions.goals.label,
                title: (actions.goals && actions.goals.title) || DEFAULT_UI_STRINGS.actions.goals.title
            }
        },
        promiseNotice: {
            saved: promiseNotice.saved || DEFAULT_UI_STRINGS.promiseNotice.saved
        },
        promisePanel: {
            title: promisePanel.title || DEFAULT_UI_STRINGS.promisePanel.title,
            close: promisePanel.close || DEFAULT_UI_STRINGS.promisePanel.close,
            empty: promisePanel.empty || DEFAULT_UI_STRINGS.promisePanel.empty,
            soon: promisePanel.soon || DEFAULT_UI_STRINGS.promisePanel.soon,
            queued: promisePanel.queued || DEFAULT_UI_STRINGS.promisePanel.queued,
            inMinutes: promisePanel.inMinutes || DEFAULT_UI_STRINGS.promisePanel.inMinutes,
            overdueMinutes: promisePanel.overdueMinutes || DEFAULT_UI_STRINGS.promisePanel.overdueMinutes
        },
        goalPanel: {
            label: goalPanel.label || DEFAULT_UI_STRINGS.goalPanel.label,
            title: goalPanel.title || goalPanel.label || DEFAULT_UI_STRINGS.goalPanel.title,
            close: goalPanel.close || DEFAULT_UI_STRINGS.goalPanel.close,
            empty: goalPanel.empty || DEFAULT_UI_STRINGS.goalPanel.empty,
            shortTerm: goalPanel.shortTerm || DEFAULT_UI_STRINGS.goalPanel.shortTerm,
            longTerm: goalPanel.longTerm || DEFAULT_UI_STRINGS.goalPanel.longTerm
        },
        mood: {
            label: mood.label || DEFAULT_UI_STRINGS.mood.label,
            loading: mood.loading || DEFAULT_UI_STRINGS.mood.loading,
            collapse: mood.collapse || DEFAULT_UI_STRINGS.mood.collapse,
            axis: {
                valence: moodAxis.valence || DEFAULT_UI_STRINGS.mood.axis.valence,
                bond: moodAxis.bond || DEFAULT_UI_STRINGS.mood.axis.bond,
                energy: moodAxis.energy || DEFAULT_UI_STRINGS.mood.axis.energy,
                stress: moodAxis.stress || DEFAULT_UI_STRINGS.mood.axis.stress
            },
            states: {
                calm: moodStates.calm || DEFAULT_UI_STRINGS.mood.states.calm,
                cheerful: moodStates.cheerful || DEFAULT_UI_STRINGS.mood.states.cheerful,
                affectionate: moodStates.affectionate || DEFAULT_UI_STRINGS.mood.states.affectionate,
                tired: moodStates.tired || DEFAULT_UI_STRINGS.mood.states.tired,
                tense: moodStates.tense || DEFAULT_UI_STRINGS.mood.states.tense,
                sensitive: moodStates.sensitive || DEFAULT_UI_STRINGS.mood.states.sensitive,
                unknown: moodStates.unknown || DEFAULT_UI_STRINGS.mood.states.unknown
            },
            temporaryStates: {
                steady: moodTemporaryStates.steady || DEFAULT_UI_STRINGS.mood.temporaryStates.steady,
                playful: moodTemporaryStates.playful || DEFAULT_UI_STRINGS.mood.temporaryStates.playful,
                focused: moodTemporaryStates.focused || DEFAULT_UI_STRINGS.mood.temporaryStates.focused,
                drained: moodTemporaryStates.drained || DEFAULT_UI_STRINGS.mood.temporaryStates.drained,
                guarded: moodTemporaryStates.guarded || DEFAULT_UI_STRINGS.mood.temporaryStates.guarded,
                pout: moodTemporaryStates.pout || DEFAULT_UI_STRINGS.mood.temporaryStates.pout
            }
        },
        summaryConfirm: {
            title: summaryConfirm.title || DEFAULT_UI_STRINGS.summaryConfirm.title,
            body: summaryConfirm.body || DEFAULT_UI_STRINGS.summaryConfirm.body,
            no: summaryConfirm.no || DEFAULT_UI_STRINGS.summaryConfirm.no,
            yes: summaryConfirm.yes || DEFAULT_UI_STRINGS.summaryConfirm.yes
        },
        thoughts: {
            button: thoughts.button || DEFAULT_UI_STRINGS.thoughts.button,
            buttonTitle: thoughts.buttonTitle || DEFAULT_UI_STRINGS.thoughts.buttonTitle,
            panelTitle: thoughts.panelTitle || DEFAULT_UI_STRINGS.thoughts.panelTitle,
            close: thoughts.close || DEFAULT_UI_STRINGS.thoughts.close,
            empty: thoughts.empty || DEFAULT_UI_STRINGS.thoughts.empty,
            show: thoughts.show || DEFAULT_UI_STRINGS.thoughts.show,
            hide: thoughts.hide || DEFAULT_UI_STRINGS.thoughts.hide,
            speaker: thoughts.speaker || DEFAULT_UI_STRINGS.thoughts.speaker
        }
    };
}

function formatMoodTemporaryLabel(temporaryState) {
    if (!temporaryState || temporaryState === 'steady') {
        return '';
    }
    const map = (currentUiStrings && currentUiStrings.mood && currentUiStrings.mood.temporaryStates)
        ? currentUiStrings.mood.temporaryStates
        : DEFAULT_UI_STRINGS.mood.temporaryStates;
    return map[temporaryState] || temporaryState;
}

function formatMoodStatusText(label, temporaryState) {
    const localizedLabel = formatMoodLabel(label);
    const localizedTemporary = formatMoodTemporaryLabel(temporaryState);
    const combinedLabel = localizedTemporary ? `${localizedLabel} · ${localizedTemporary}` : localizedLabel;
    const template = currentUiStrings.mood.label || DEFAULT_UI_STRINGS.mood.label;
    if (template.indexOf('{label}') >= 0) {
        return template.replace('{label}', combinedLabel);
    }
    return `${template} ${combinedLabel}`.trim();
}

function applyUiStringsToStaticNodes() {
    if (loadingText) loadingText.textContent = currentUiStrings.loading;
    if (chatInput) chatInput.placeholder = currentUiStrings.input.placeholder;
    if (sendButton) sendButton.textContent = currentUiStrings.send;
    if (manualSummarizeButton) {
        manualSummarizeButton.textContent = currentUiStrings.actions.summary.label;
        manualSummarizeButton.title = currentUiStrings.actions.summary.title;
    }
    if (obsNoteButton) {
        obsNoteButton.textContent = currentUiStrings.actions.note.label;
        obsNoteButton.title = currentUiStrings.actions.note.title;
    }
    if (moodToggleButton) {
        moodToggleButton.textContent = currentUiStrings.actions.mood.label;
        moodToggleButton.title = currentUiStrings.actions.mood.title;
    }
    if (promiseRemindersButton) {
        promiseRemindersButton.textContent = currentUiStrings.actions.promises.label;
        promiseRemindersButton.title = currentUiStrings.actions.promises.title;
    }
    if (goalButton) {
        goalButton.textContent = currentUiStrings.actions.goals.label;
        goalButton.title = currentUiStrings.actions.goals.title;
        goalButton.setAttribute('aria-label', currentUiStrings.actions.goals.title);
    }
    if (promiseRemindersPanelTitle) {
        promiseRemindersPanelTitle.textContent = currentUiStrings.promisePanel.title;
    }
    if (promiseRemindersCloseButton) {
        promiseRemindersCloseButton.title = currentUiStrings.promisePanel.close;
        promiseRemindersCloseButton.setAttribute('aria-label', currentUiStrings.promisePanel.close);
    }
    if (goalPanelTitle) {
        goalPanelTitle.textContent = currentUiStrings.goalPanel.title;
    }
    if (goalPanelCloseButton) {
        goalPanelCloseButton.title = currentUiStrings.goalPanel.close;
        goalPanelCloseButton.setAttribute('aria-label', currentUiStrings.goalPanel.close);
    }
    if (moodMeterNameValence) moodMeterNameValence.textContent = currentUiStrings.mood.axis.valence;
    if (moodMeterNameBond) moodMeterNameBond.textContent = currentUiStrings.mood.axis.bond;
    if (moodMeterNameEnergy) moodMeterNameEnergy.textContent = currentUiStrings.mood.axis.energy;
    if (moodMeterNameStress) moodMeterNameStress.textContent = currentUiStrings.mood.axis.stress;
    if (moodCollapseButton) moodCollapseButton.title = currentUiStrings.mood.collapse;
    if (summaryConfirmTitle) summaryConfirmTitle.textContent = currentUiStrings.summaryConfirm.title;
    if (summaryConfirmBody) summaryConfirmBody.textContent = currentUiStrings.summaryConfirm.body;
    if (summaryConfirmNoButton) summaryConfirmNoButton.textContent = currentUiStrings.summaryConfirm.no;
    if (summaryConfirmYesButton) summaryConfirmYesButton.textContent = currentUiStrings.summaryConfirm.yes;
    updateMessageThoughtButtons();
}

window.applyENEUiStrings = function applyENEUiStrings(config) {
    currentUiStrings = mergeUiStrings(config);
    window.eneUiStrings = currentUiStrings;
    applyUiStringsToStaticNodes();
    renderPromiseReminderPanel();
    renderGoalPanel();
    updateMoodWidget(
        currentMoodSnapshot.label,
        currentMoodSnapshot.temporaryState,
        currentMoodSnapshot.valence,
        currentMoodSnapshot.energy,
        currentMoodSnapshot.bond,
        currentMoodSnapshot.stress
    );
};
