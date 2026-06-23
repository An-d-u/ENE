
// ==========================================
// 채팅/버튼 UI
// ==========================================

const chatMessages = document.getElementById('chat-messages');
const chatContainer = document.getElementById('chat-container');
const chatResizeHandle = document.getElementById('chat-resize-handle');
const chatInput = document.getElementById('chat-input');
const sendButton = document.getElementById('send-button');
const manualSummarizeButton = document.getElementById('manual-summarize-floating-btn');
const floatingActionsRoot = document.getElementById('floating-action-buttons');
const floatingActionsToggle = document.getElementById('floating-actions-toggle');
const floatingActionsMenu = document.getElementById('floating-actions-menu');
const settingsFloatingButton = document.getElementById('settings-floating-btn');
const attachButton = document.getElementById('attach-button');
const imageInput = document.getElementById('image-input');
const imagePreviewContainer = document.getElementById('image-preview-container');
const loadingIndicator = document.getElementById('loading-indicator');
const loadingIndicatorAnchor = loadingIndicator ? loadingIndicator.parentElement : null;
const loadingText = document.querySelector('#loading-indicator .typing-text');
const summaryConfirmOverlay = document.getElementById('summary-confirm-overlay');
const summaryConfirmTitle = document.getElementById('summary-confirm-title');
const summaryConfirmBody = document.getElementById('summary-confirm-body');
const summaryConfirmYesButton = document.getElementById('summary-confirm-yes');
const summaryConfirmNoButton = document.getElementById('summary-confirm-no');
const summaryReviewOverlay = document.getElementById('summary-review-overlay');
const summaryReviewCloseButton = document.getElementById('summary-review-close');
const summaryReviewTextarea = document.getElementById('summary-review-textarea');
const summaryReviewMemoryType = document.getElementById('summary-review-memory-type');
const summaryReviewImportanceReason = document.getElementById('summary-review-importance-reason');
const summaryReviewConfidence = document.getElementById('summary-review-confidence');
const summaryReviewEntities = document.getElementById('summary-review-entities');
const summaryReviewUserFacts = document.getElementById('summary-review-user-facts');
const summaryReviewEneFacts = document.getElementById('summary-review-ene-facts');
const summaryReviewAddUserFactButton = document.getElementById('summary-review-add-user-fact');
const summaryReviewAddEneFactButton = document.getElementById('summary-review-add-ene-fact');
const summaryReviewCancelButton = document.getElementById('summary-review-cancel');
const summaryReviewRegenerateButton = document.getElementById('summary-review-regenerate');
const summaryReviewSaveButton = document.getElementById('summary-review-save');
const attachmentDeleteConfirmOverlay = document.getElementById('attachment-delete-confirm-overlay');
const attachmentDeleteConfirmBody = document.getElementById('attachment-delete-confirm-body');
const attachmentDeleteConfirmYesButton = document.getElementById('attachment-delete-confirm-yes');
const attachmentDeleteConfirmNoButton = document.getElementById('attachment-delete-confirm-no');
const imageLightboxOverlay = document.getElementById('image-lightbox-overlay');
const imageLightboxImage = document.getElementById('image-lightbox-image');
const imageLightboxClose = document.getElementById('image-lightbox-close');
const toastContainer = document.getElementById('toast-container');
const moodToggleButton = document.getElementById('mood-toggle-floating-btn');
const obsNoteButton = document.getElementById('obs-note-floating-btn');
const promiseRemindersButton = document.getElementById('promise-reminders-floating-btn');
const promiseRemindersPanel = document.getElementById('promise-reminders-panel');
const promiseRemindersPanelTitle = document.getElementById('promise-reminders-panel-title');
const promiseRemindersCloseButton = document.getElementById('promise-reminders-close-btn');
const promiseRemindersList = document.getElementById('promise-reminders-list');
const proactiveConversationsButton = document.getElementById('proactive-conversations-floating-btn');
const proactiveConversationsPanel = document.getElementById('proactive-conversations-panel');
const proactiveConversationsPanelTitle = document.getElementById('proactive-conversations-panel-title');
const proactiveConversationsCloseButton = document.getElementById('proactive-conversations-close-btn');
const proactiveConversationsList = document.getElementById('proactive-conversations-list');
const goalButton = document.getElementById('goal-toggle-floating-btn');
const goalPanel = document.getElementById('goal-status-panel');
const goalPanelTitle = document.getElementById('goal-status-panel-title');
const goalPanelCloseButton = document.getElementById('goal-status-close-btn');
const goalStatusList = document.getElementById('goal-status-list');
const live2dParametersButton = document.getElementById('live2d-parameters-floating-btn');
const live2dParametersPanel = document.getElementById('live2d-parameters-panel');
const live2dParametersCloseButton = document.getElementById('live2d-parameters-close-btn');
const live2dParametersPanelTitle = document.getElementById('live2d-parameters-panel-title');
const live2dParametersWarning = document.getElementById('live2d-parameters-warning');
const live2dParametersSearch = document.getElementById('live2d-parameters-search');
const live2dParametersTabs = document.getElementById('live2d-parameters-tabs');
const live2dParametersList = document.getElementById('live2d-parameters-list');
const live2dParametersSaveButton = document.getElementById('live2d-parameters-save-btn');
const live2dParametersResetButton = document.getElementById('live2d-parameters-reset-btn');
const moodWidget = document.getElementById('mood-status-widget');
const moodStatusHeader = document.getElementById('mood-status-header');
const moodCollapseButton = document.getElementById('mood-status-collapse-btn');
const moodStatusLabel = document.getElementById('mood-status-label');
const moodMeterNameValence = document.getElementById('mood-meter-name-valence');
const moodMeterNameBond = document.getElementById('mood-meter-name-bond');
const moodMeterNameEnergy = document.getElementById('mood-meter-name-energy');
const moodMeterNameStress = document.getElementById('mood-meter-name-stress');
const moodMeterValence = document.getElementById('mood-meter-valence');
const moodMeterBond = document.getElementById('mood-meter-bond');
const moodMeterEnergy = document.getElementById('mood-meter-energy');
const moodMeterStress = document.getElementById('mood-meter-stress');
const obsPanel = document.getElementById('obs-panel');
const obsTree = document.getElementById('obs-tree');
const obsRefreshBtn = document.getElementById('obs-refresh-btn');
const overlayNoticeStack = document.getElementById('overlay-notice-stack');
const tokenUsageBubble = document.getElementById('token-usage-bubble');
const promiseNoticeBubble = document.getElementById('promise-notice-bubble');
const MAX_ATTACHMENT_COUNT = 5;
const SUPPORTED_DOCUMENT_EXTENSIONS = new Set(['txt', 'md', 'pdf', 'docx']);
const MESSAGE_TYPING_BASE_INTERVAL_MS = 28;
const MESSAGE_TYPING_MAX_DURATION_MS = 2400;
const MESSAGE_TYPING_MIN_INTERVAL_MS = 10;
const MESSAGE_VISUAL_SENTENCE_SPLIT_MIN_LENGTH = 72;
const MESSAGE_TYPING_SPEED_MULTIPLIERS = {
    fast: 0.72,
    normal: 1.0,
    slow: 1.38
};
let attachedAttachments = [];
let rerollButtonVisibleBySetting = true;
let recentEditButtonVisibleBySetting = true;
let manualSummaryButtonVisibleBySetting = true;
let moodToggleButtonVisibleBySetting = true;
let goalButtonVisibleBySetting = true;
let proactiveConversationButtonVisibleBySetting = true;
let obsidianNoteButtonVisibleBySetting = true;
let tokenUsageBubbleVisibleBySetting = false;
let hasAssistantMessage = false;
let hasUserMessage = false;
let isRequestPending = false;
let shouldReplaceNextAssistant = false;
let lastAssistantMessageEl = null;
let lastUserMessageEl = null;
let moodPanelOpen = false;
let goalPanelOpen = false;
let proactiveConversationPanelOpen = false;
let live2dParametersPanelOpen = false;
let activeInlineEditMessageEl = null;
let obsCheckedPaths = new Set();
let moodWidgetDragState = null;
let tokenUsageBubbleTimer = null;
let promiseNoticeBubbleTimer = null;
let promiseReminderItems = [];
let proactiveConversationItems = [];
let eneGoalSnapshot = { active: { short_term: [], long_term: [] }, history: [] };
let currentMoodSnapshot = { label: 'calm', temporaryState: 'steady', valence: 0, energy: 0, bond: 0, stress: 0 };
let currentUiStrings = null;
let currentSummaryReviewPayload = null;
let summaryReviewBusy = false;
let typingEffectEnabled = true;
let typingEffectSpeed = 'normal';
let messageSplitEnabled = false;
let chatPanelHeightPx = null;
let chatResizeState = null;
let pendingAttachmentDeletion = null;

function getChatPanelMinHeight() {
    return 136;
}

function getChatPanelMaxHeight() {
    return Math.max(getChatPanelMinHeight(), Math.min(window.innerHeight - 64, 560));
}

function clampChatPanelHeight(height) {
    if (!Number.isFinite(height)) {
        return null;
    }
    return Math.max(getChatPanelMinHeight(), Math.min(Math.round(height), getChatPanelMaxHeight()));
}

function applyChatPanelHeight(height, { persist = false } = {}) {
    if (!chatContainer) {
        return null;
    }

    const numericHeight = Number(height);
    if (!Number.isFinite(numericHeight) || numericHeight <= 0) {
        chatPanelHeightPx = null;
        chatContainer.style.height = '';
        chatContainer.style.maxHeight = 'min(360px, 42vh)';
        return null;
    }

    const nextHeight = clampChatPanelHeight(numericHeight);
    if (nextHeight === null) {
        return null;
    }

    chatPanelHeightPx = nextHeight;
    chatContainer.style.height = `${nextHeight}px`;
    chatContainer.style.maxHeight = `${nextHeight}px`;
    chatMessages.scrollTop = chatMessages.scrollHeight;

    if (persist && window.pyBridge && typeof window.pyBridge.save_chat_panel_height === 'function') {
        window.pyBridge.save_chat_panel_height(String(nextHeight));
    }

    return nextHeight;
}

function finishChatPanelResize(pointerId = null, { persist = true } = {}) {
    if (!chatResizeState) {
        return;
    }
    if (pointerId !== null && chatResizeState.pointerId !== pointerId) {
        return;
    }

    const finalHeight = chatPanelHeightPx;
    chatResizeState = null;
    if (chatResizeHandle) {
        chatResizeHandle.classList.remove('is-dragging');
        if (pointerId !== null && typeof chatResizeHandle.releasePointerCapture === 'function') {
            try {
                chatResizeHandle.releasePointerCapture(pointerId);
            } catch (_) {
            }
        }
    }
    document.body.classList.remove('is-chat-resizing');

    if (persist && finalHeight !== null && window.pyBridge && typeof window.pyBridge.save_chat_panel_height === 'function') {
        window.pyBridge.save_chat_panel_height(String(finalHeight));
    }
}

function onChatResizePointerDown(event) {
    if (!chatResizeHandle || !chatContainer) {
        return;
    }
    if (event.pointerType === 'mouse' && event.button !== 0) {
        return;
    }

    const currentHeight = chatPanelHeightPx || chatContainer.getBoundingClientRect().height;
    chatResizeState = {
        pointerId: event.pointerId,
        startY: event.clientY,
        startHeight: currentHeight
    };
    setFloatingActionsOpen(false);
    chatResizeHandle.classList.add('is-dragging');
    document.body.classList.add('is-chat-resizing');
    if (typeof chatResizeHandle.setPointerCapture === 'function') {
        try {
            chatResizeHandle.setPointerCapture(event.pointerId);
        } catch (_) {
        }
    }
    event.preventDefault();
}

function onChatResizePointerMove(event) {
    if (!chatResizeState || chatResizeState.pointerId !== event.pointerId) {
        return;
    }

    const deltaY = chatResizeState.startY - event.clientY;
    const nextHeight = chatResizeState.startHeight + deltaY;
    applyChatPanelHeight(nextHeight);
    event.preventDefault();
}

function onChatResizePointerUp(event) {
    finishChatPanelResize(event.pointerId, { persist: true });
}

window.setChatPanelHeight = function setChatPanelHeight(height) {
    return applyChatPanelHeight(height);
};

function createLucideIcon(name) {
    const icons = {
        paperclip: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551" /></svg>',
        pencil: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" /><path d="m15 5 4 4" /></svg>',
        'rotate-ccw': '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /></svg>',
        settings: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" /><circle cx="12" cy="12" r="3" /></svg>',
        brain: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5a3 3 0 1 0-5.993.2A4 4 0 0 0 4 8.5a4 4 0 0 0 1.5 3.122A4 4 0 0 0 8 18.5a4 4 0 0 0 4-4.5Z" /><path d="M12 5a3 3 0 1 1 5.993.2A4 4 0 0 1 20 8.5a4 4 0 0 1-1.5 3.122A4 4 0 0 1 16 18.5a4 4 0 0 1-4-4.5Z" /><path d="M15 13a4.5 4.5 0 0 1-3-1 4.5 4.5 0 0 1-3 1" /><path d="M17.599 6.5A3 3 0 0 0 15 5" /><path d="M6.401 6.5A3 3 0 0 1 9 5" /></svg>',
        sparkles: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z" /><path d="M20 3v4" /><path d="M22 5h-4" /><path d="M4 17v2" /><path d="M5 18H3" /></svg>'
    };
    return icons[name] || '';
}

let floatingActionsOpen = false;
let thoughtFeatureEnabled = true;

function setFloatingActionsOpen(open) {
    floatingActionsOpen = Boolean(open);
    if (floatingActionsRoot) {
        floatingActionsRoot.classList.toggle('is-open', floatingActionsOpen);
    }
    if (floatingActionsToggle) {
        floatingActionsToggle.setAttribute('aria-expanded', String(floatingActionsOpen));
    }
    if (floatingActionsMenu) {
        floatingActionsMenu.setAttribute('aria-hidden', String(!floatingActionsOpen));
    }
}
