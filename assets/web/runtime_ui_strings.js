
DEFAULT_UI_STRINGS.actions.live2dParameters = DEFAULT_UI_STRINGS.actions.live2dParameters || {
    label: 'Live2D',
    title: 'Live2D parameters'
};
DEFAULT_UI_STRINGS.live2dParameters = DEFAULT_UI_STRINGS.live2dParameters || {
    title: 'Live2D parameters',
    close: 'Close Live2D parameter panel',
    warning: 'For decoration controls. Avoid expression, eye, mouth, head, and body motion parameters because they may conflict with expressions, lip-sync, and head pats.',
    search: 'Search parameters',
    all: 'All',
    favorites: 'Favorites',
    save: 'Save',
    reset: 'Reset',
    empty: 'No parameters to show.',
    statusIdle: 'Parameter list has not loaded yet.',
    statusLoading: 'Loading parameter list.',
    statusUnavailable: 'This Live2D model does not expose readable parameters.',
    statusError: 'Could not load parameter list.',
    toastLoadFirst: 'Load the parameter list first.',
    toastMissingModel: 'Select a model before saving.',
    toastMissingBridge: 'Save bridge is not available.',
    toastSaveSuccess: 'Live2D parameters saved.',
    toastSaveError: 'Failed to save Live2D parameters.'
};

const MOOD_V3_UI_STRINGS = {
    ko: {
        primaryEmotion: '주 감정', secondaryEmotion: '보조 감정', trust: '신뢰',
        reset: '상태 초기화', resetConfirm: '기분 상태를 초기화하시겠습니까?',
        trustLevels: { low: '낮음', medium: '보통', high: '높음' },
        emotions: { joy: '기쁨', tenderness: '다정함', amusement: '즐거움', interest: '관심', sadness: '슬픔', hurt: '상처', anger: '분노', anxiety: '불안' }
    },
    en: {
        primaryEmotion: 'Primary emotion', secondaryEmotion: 'Secondary emotion', trust: 'Trust',
        reset: 'Reset state', resetConfirm: 'Reset the mood state?',
        trustLevels: { low: 'Low', medium: 'Medium', high: 'High' },
        emotions: { joy: 'Joy', tenderness: 'Tenderness', amusement: 'Amusement', interest: 'Interest', sadness: 'Sadness', hurt: 'Hurt', anger: 'Anger', anxiety: 'Anxiety' }
    },
    ja: {
        primaryEmotion: '主な感情', secondaryEmotion: '補助感情', trust: '信頼',
        reset: '状態をリセット', resetConfirm: '気分の状態をリセットしますか？',
        trustLevels: { low: '低い', medium: '普通', high: '高い' },
        emotions: { joy: '喜び', tenderness: '優しさ', amusement: '楽しさ', interest: '関心', sadness: '悲しみ', hurt: '傷つき', anger: '怒り', anxiety: '不安' }
    }
};
const moodResetButton = document.getElementById('mood-state-reset-btn');
const moodPrimaryLabel = document.getElementById('mood-detail-primary-label');
const moodSecondaryLabel = document.getElementById('mood-detail-secondary-label');
const moodTrustLabel = document.getElementById('mood-detail-trust-label');

function mergeUiStrings(config) {
    const source = config || {};
    const input = source.input || {};
    const actions = source.actions || {};
    const mood = source.mood || {};
    const moodAxis = mood.axis || {};
    const moodStates = mood.states || {};
    const moodTemporaryStates = mood.temporaryStates || {};
    const moodEmotionNames = mood.emotions || {};
    const moodTrustLevels = mood.trustLevels || {};
    const moodV3Fallback = MOOD_V3_UI_STRINGS[
        ['ko', 'en', 'ja'].includes(source.resolvedLanguage) ? source.resolvedLanguage : 'en'
    ];
    const summaryConfirm = source.summaryConfirm || {};
    const promiseNotice = source.promiseNotice || {};
    const promisePanel = source.promisePanel || {};
    const proactivePanel = source.proactivePanel || {};
    const goalPanel = source.goalPanel || {};
    const live2dParameters = source.live2dParameters || {};
    const thoughts = source.thoughts || {};
    const lifeRecords = source.lifeRecords || {};

    return {
        locale: typeof source.locale === 'string' ? source.locale : 'auto',
        resolvedLanguage: ['ko', 'en', 'ja'].includes(source.resolvedLanguage) ? source.resolvedLanguage : 'en',
        viewTimezone: typeof source.viewTimezone === 'string' && source.viewTimezone ? source.viewTimezone : 'UTC',
        todayIso: /^\d{4}-\d{2}-\d{2}$/.test(String(source.todayIso || '')) ? source.todayIso : '',
        lifeRecords: { ...lifeRecords },
        loading: source.loading || DEFAULT_UI_STRINGS.loading,
        loadingSearching: source.loadingSearching || DEFAULT_UI_STRINGS.loadingSearching,
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
            proactive: {
                label: (actions.proactive && actions.proactive.label) || DEFAULT_UI_STRINGS.actions.proactive.label,
                title: (actions.proactive && actions.proactive.title) || DEFAULT_UI_STRINGS.actions.proactive.title
            },
            live2dParameters: {
                label: (actions.live2dParameters && actions.live2dParameters.label) || DEFAULT_UI_STRINGS.actions.live2dParameters.label,
                title: (actions.live2dParameters && actions.live2dParameters.title) || DEFAULT_UI_STRINGS.actions.live2dParameters.title
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
        proactivePanel: {
            title: proactivePanel.title || DEFAULT_UI_STRINGS.proactivePanel.title,
            close: proactivePanel.close || DEFAULT_UI_STRINGS.proactivePanel.close,
            empty: proactivePanel.empty || DEFAULT_UI_STRINGS.proactivePanel.empty,
            soon: proactivePanel.soon || DEFAULT_UI_STRINGS.proactivePanel.soon,
            queued: proactivePanel.queued || DEFAULT_UI_STRINGS.proactivePanel.queued,
            inMinutes: proactivePanel.inMinutes || DEFAULT_UI_STRINGS.proactivePanel.inMinutes,
            overdueMinutes: proactivePanel.overdueMinutes || DEFAULT_UI_STRINGS.proactivePanel.overdueMinutes,
            remove: proactivePanel.remove || DEFAULT_UI_STRINGS.proactivePanel.remove
        },
        goalPanel: {
            label: goalPanel.label || DEFAULT_UI_STRINGS.goalPanel.label,
            title: goalPanel.title || goalPanel.label || DEFAULT_UI_STRINGS.goalPanel.title,
            close: goalPanel.close || DEFAULT_UI_STRINGS.goalPanel.close,
            empty: goalPanel.empty || DEFAULT_UI_STRINGS.goalPanel.empty,
            shortTerm: goalPanel.shortTerm || DEFAULT_UI_STRINGS.goalPanel.shortTerm,
            longTerm: goalPanel.longTerm || DEFAULT_UI_STRINGS.goalPanel.longTerm
        },
        live2dParameters: {
            title: live2dParameters.title || DEFAULT_UI_STRINGS.live2dParameters.title,
            close: live2dParameters.close || DEFAULT_UI_STRINGS.live2dParameters.close,
            warning: live2dParameters.warning || DEFAULT_UI_STRINGS.live2dParameters.warning,
            search: live2dParameters.search || DEFAULT_UI_STRINGS.live2dParameters.search,
            all: live2dParameters.all || DEFAULT_UI_STRINGS.live2dParameters.all,
            favorites: live2dParameters.favorites || DEFAULT_UI_STRINGS.live2dParameters.favorites,
            save: live2dParameters.save || DEFAULT_UI_STRINGS.live2dParameters.save,
            reset: live2dParameters.reset || DEFAULT_UI_STRINGS.live2dParameters.reset,
            empty: live2dParameters.empty || DEFAULT_UI_STRINGS.live2dParameters.empty,
            statusIdle: live2dParameters.statusIdle || DEFAULT_UI_STRINGS.live2dParameters.statusIdle,
            statusLoading: live2dParameters.statusLoading || DEFAULT_UI_STRINGS.live2dParameters.statusLoading,
            statusUnavailable: live2dParameters.statusUnavailable || DEFAULT_UI_STRINGS.live2dParameters.statusUnavailable,
            statusError: live2dParameters.statusError || DEFAULT_UI_STRINGS.live2dParameters.statusError,
            toastLoadFirst: live2dParameters.toastLoadFirst || DEFAULT_UI_STRINGS.live2dParameters.toastLoadFirst,
            toastMissingModel: live2dParameters.toastMissingModel || DEFAULT_UI_STRINGS.live2dParameters.toastMissingModel,
            toastMissingBridge: live2dParameters.toastMissingBridge || DEFAULT_UI_STRINGS.live2dParameters.toastMissingBridge,
            toastSaveSuccess: live2dParameters.toastSaveSuccess || DEFAULT_UI_STRINGS.live2dParameters.toastSaveSuccess,
            toastSaveError: live2dParameters.toastSaveError || DEFAULT_UI_STRINGS.live2dParameters.toastSaveError
        },
        mood: {
            label: mood.label || DEFAULT_UI_STRINGS.mood.label,
            loading: mood.loading || DEFAULT_UI_STRINGS.mood.loading,
            collapse: mood.collapse || DEFAULT_UI_STRINGS.mood.collapse,
            primaryEmotion: mood.primaryEmotion || moodV3Fallback.primaryEmotion,
            secondaryEmotion: mood.secondaryEmotion || moodV3Fallback.secondaryEmotion,
            trust: mood.trust || moodV3Fallback.trust,
            trustLevels: { ...moodV3Fallback.trustLevels, ...moodTrustLevels },
            reset: mood.reset || moodV3Fallback.reset,
            resetConfirm: mood.resetConfirm || moodV3Fallback.resetConfirm,
            emotions: { ...moodV3Fallback.emotions, ...moodEmotionNames },
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
    if (typeof updateLoadingIndicatorText === 'function') {
        updateLoadingIndicatorText();
    } else if (loadingText) {
        loadingText.textContent = currentUiStrings.loading;
    }
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
    if (proactiveConversationsButton) {
        proactiveConversationsButton.textContent = currentUiStrings.actions.proactive.label;
        proactiveConversationsButton.title = currentUiStrings.actions.proactive.title;
        proactiveConversationsButton.setAttribute('aria-label', currentUiStrings.actions.proactive.title);
    }
    if (live2dParametersButton) {
        live2dParametersButton.textContent = currentUiStrings.actions.live2dParameters.label;
        live2dParametersButton.title = currentUiStrings.actions.live2dParameters.title;
        live2dParametersButton.setAttribute('aria-label', currentUiStrings.actions.live2dParameters.title);
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
    if (proactiveConversationsPanelTitle) {
        proactiveConversationsPanelTitle.textContent = currentUiStrings.proactivePanel.title;
    }
    if (proactiveConversationsCloseButton) {
        proactiveConversationsCloseButton.title = currentUiStrings.proactivePanel.close;
        proactiveConversationsCloseButton.setAttribute('aria-label', currentUiStrings.proactivePanel.close);
    }
    if (goalPanelTitle) {
        goalPanelTitle.textContent = currentUiStrings.goalPanel.title;
    }
    if (goalPanelCloseButton) {
        goalPanelCloseButton.title = currentUiStrings.goalPanel.close;
        goalPanelCloseButton.setAttribute('aria-label', currentUiStrings.goalPanel.close);
    }
    if (live2dParametersPanelTitle) {
        live2dParametersPanelTitle.textContent = currentUiStrings.live2dParameters.title;
    }
    if (live2dParametersCloseButton) {
        live2dParametersCloseButton.title = currentUiStrings.live2dParameters.close;
        live2dParametersCloseButton.setAttribute('aria-label', currentUiStrings.live2dParameters.close);
    }
    if (live2dParametersWarning) {
        live2dParametersWarning.textContent = currentUiStrings.live2dParameters.warning;
    }
    if (live2dParametersSearch) {
        live2dParametersSearch.placeholder = currentUiStrings.live2dParameters.search;
        live2dParametersSearch.setAttribute('aria-label', currentUiStrings.live2dParameters.search);
    }
    if (live2dParametersTabs) {
        const tabLabels = currentUiStrings.live2dParameters;
        live2dParametersTabs.querySelectorAll('[data-live2d-parameter-tab]').forEach((tab) => {
            const key = tab.dataset.live2dParameterTab;
            if (tabLabels[key]) {
                tab.textContent = tabLabels[key];
            }
        });
    }
    if (live2dParametersSaveButton) {
        live2dParametersSaveButton.textContent = currentUiStrings.live2dParameters.save;
    }
    if (live2dParametersResetButton) {
        live2dParametersResetButton.textContent = currentUiStrings.live2dParameters.reset;
    }
    if (moodMeterNameValence) moodMeterNameValence.textContent = currentUiStrings.mood.axis.valence;
    if (moodMeterNameBond) moodMeterNameBond.textContent = currentUiStrings.mood.axis.bond;
    if (moodMeterNameEnergy) moodMeterNameEnergy.textContent = currentUiStrings.mood.axis.energy;
    if (moodMeterNameStress) moodMeterNameStress.textContent = currentUiStrings.mood.axis.stress;
    if (moodResetButton) {
        moodResetButton.textContent = currentUiStrings.mood.reset;
        moodResetButton.setAttribute('aria-label', currentUiStrings.mood.reset);
    }
    if (moodPrimaryLabel) moodPrimaryLabel.textContent = currentUiStrings.mood.primaryEmotion;
    if (moodSecondaryLabel) moodSecondaryLabel.textContent = currentUiStrings.mood.secondaryEmotion;
    if (moodTrustLabel) moodTrustLabel.textContent = currentUiStrings.mood.trust;
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
    if (document.documentElement) {
        document.documentElement.lang = currentUiStrings.resolvedLanguage;
    }
    if (window.eneLifeRecordPanel && typeof window.eneLifeRecordPanel.setLanguage === 'function') {
        window.eneLifeRecordPanel.setLanguage(currentUiStrings.resolvedLanguage);
    }
    if (window.eneLifeRecordPanel && typeof window.eneLifeRecordPanel.setUiContext === 'function') {
        window.eneLifeRecordPanel.setUiContext({
            todayIso: currentUiStrings.todayIso,
            viewTimezone: currentUiStrings.viewTimezone,
            lifeRecords: currentUiStrings.lifeRecords
        });
    }
    applyUiStringsToStaticNodes();
    renderPromiseReminderPanel();
    renderProactiveConversationPanel();
    renderGoalPanel();
    if (typeof rerenderMoodDetailsForLocale === 'function') {
        rerenderMoodDetailsForLocale();
    }
    updateMoodWidget(
        currentMoodSnapshot.label,
        currentMoodSnapshot.temporaryState,
        currentMoodSnapshot.valence,
        currentMoodSnapshot.energy,
        currentMoodSnapshot.bond,
        currentMoodSnapshot.stress
    );
};
