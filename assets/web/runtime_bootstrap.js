/**
 * Live2D 렌더링, 표정/립싱크, 채팅 UI 이벤트를 함께 제어하는 메인 스크립트.
 */
console.log("=== Live2D script loaded ===");
console.log("Window location:", window.location.href);
console.log("PIXI available:", typeof PIXI !== 'undefined');
console.log("Live2DCubismCore available:", typeof Live2DCubismCore !== 'undefined');
console.log("PIXI.live2d available:", typeof PIXI !== 'undefined' && typeof PIXI.live2d !== 'undefined');
if (typeof PIXI === 'undefined') {
    console.error("CRITICAL: PIXI.js is not loaded!");
    document.body.innerHTML = '<div style="color: red; font-family: Arial; text-align: center; margin-top: 50px; font-size: 18px;">PIXI.js 로드 실패<br><br>페이지를 새로고침해 주세요.</div>';
    throw new Error("PIXI.js not loaded");
}
if (typeof PIXI.live2d === 'undefined') {
    console.error("CRITICAL: PIXI.live2d is not available!");
    console.log("Available PIXI properties:", Object.keys(PIXI));
    document.body.innerHTML = '<div style="color: red; font-family: Arial; text-align: center; margin-top: 50px; font-size: 16px;">' +
        'pixi-live2d-display 라이브러리 로드 실패<br><br>' +
        '사용 가능한 PIXI: ' + Object.keys(PIXI).slice(0, 10).join(', ') + '...<br><br>' +
        '페이지를 새로고침해 주세요.</div>';
    throw new Error("PIXI.live2d not available");
}

console.log("All libraries loaded successfully");
const app = new PIXI.Application({
    view: document.getElementById('live2d-canvas'),
    transparent: true,
    backgroundAlpha: 0,
    resizeTo: window,
    antialias: true
});

console.log("Pixi app initialized");
console.log("Canvas size:", window.innerWidth, "x", window.innerHeight);
const DEFAULT_MODEL_PATH = '../live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json';
const DEFAULT_THEME = {
    accentColor: '#0071E3',
    settingsWindowBgColor: '#EEF1F5',
    settingsCardBgColor: '#FFFFFF',
    settingsInputBgColor: '#F8FAFC',
    chatPanelBgColor: '#111214',
    chatInputBgColor: '#1B1D22',
    chatAssistantBubbleColor: '#FFFFFF',
    chatUserBubbleColor: '#0071E3'
};
const DEFAULT_UI_STRINGS = {
    loading: 'Thinking...',
    input: {
        placeholder: 'Type a message...'
    },
    send: 'Send',
    actions: {
        summary: {
            label: 'Summary',
            title: 'Conversation summary'
        },
        note: {
            label: 'Note',
            title: 'Open or close the Obsidian note panel'
        },
        mood: {
            label: 'Mood',
            title: 'Mood status'
        },
        promises: {
            label: 'Scheduled',
            title: 'Scheduled conversation promises'
        },
        goals: {
            label: 'Goals',
            title: 'ENE goals'
        }
    },
    promiseNotice: {
        saved: 'Conversation promise saved.'
    },
    promisePanel: {
        title: 'Scheduled',
        close: 'Close',
        empty: 'No scheduled conversation promises.',
        soon: 'Soon',
        queued: 'Right after the current reply',
        inMinutes: 'In {minutes} min',
        overdueMinutes: '{minutes} min late'
    },
    goalPanel: {
        label: 'Goals',
        title: 'ENE goals',
        close: 'Close',
        empty: 'No active goals yet.',
        shortTerm: 'Short-term',
        longTerm: 'Long-term'
    },
    mood: {
        label: 'Mood: {label}',
        loading: 'Loading',
        collapse: 'Collapse',
        axis: {
            valence: 'Positive',
            bond: 'Bond',
            energy: 'Energy',
            stress: 'Stress'
        },
        states: {
            calm: 'Calm',
            cheerful: 'Bright',
            affectionate: 'Warm',
            tired: 'Tired',
            tense: 'Guarded',
            sensitive: 'Sensitive',
            unknown: 'Unknown'
        },
        temporaryStates: {
            steady: 'Steady',
            playful: 'Playful',
            focused: 'Focused',
            drained: 'Drained',
            guarded: 'Guarded',
            pout: 'Pouty'
        }
    },
    summaryConfirm: {
        title: 'Manual summary',
        body: 'Would you like to start a manual summary?',
        no: 'No',
        yes: 'Yes'
    },
    thoughts: {
        button: 'Thoughts',
        buttonTitle: 'Show ENE thoughts',
        panelTitle: 'Thoughts',
        close: 'Close',
        empty: 'No thoughts to show yet.',
        show: 'Show thought',
        hide: 'Hide thought',
        speaker: 'ENE'
    }
};
const ATTACHMENT_DELETE_CONFIRM_BODY = '지운 사진은 컨텍스트에 포함되지 않습니다.\n정말 지우시겠습니까?';
window.eneModelConfig = window.eneModelConfig || {};
window.eneThemeConfig = window.eneThemeConfig || {};
window.eneUiStrings = window.eneUiStrings || {};
let currentModelPath = '';
let currentEmotionsBasePath = '';
let currentAvailableEmotions = new Set(['normal']);
let currentModelLoadToken = 0;
let currentModelErrorText = null;
let currentThemeAccent = DEFAULT_THEME.accentColor;
const BUILTIN_IDLE_GROUP_DISABLED = '__ENE_DISABLED_BUILTIN_IDLE__';
const builtinAutoMotionState = {
    enabled: true,
    running: false,
    idleGroupName: 'Idle',
    breath: null,
    physics: null
};
const autoEyeBlinkState = {
    enabled: true,
    builtinInstance: null,
    runtime: null
};

function createAutoEyeBlinkRuntimeState() {
    return {
        phase: 'idle',
        phaseStartedAtMs: 0,
        nextBlinkAtMs: 0,
        closeDurationMs: 90,
        closedDurationMs: 45,
        openDurationMs: 140,
        minIntervalMs: 2600,
        maxIntervalMs: 5200
    };
}

function resolveModelPathFromConfig() {
    return window.eneModelConfig.modelPath || DEFAULT_MODEL_PATH;
}

function resolveEmotionsBasePathFromConfig() {
    if (window.eneModelConfig.emotionsBasePath) {
        return window.eneModelConfig.emotionsBasePath;
    }
    const absoluteModelUrl = new URL(resolveModelPathFromConfig(), window.location.href);
    return new URL('./emotions/', absoluteModelUrl).href;
}

function resolveAvailableEmotionsFromConfig() {
    const raw = window.eneModelConfig.availableEmotions;
    if (!Array.isArray(raw)) {
        return ['normal'];
    }

    const unique = [];
    const seen = new Set();
    for (const item of raw) {
        const emotion = String(item || '').trim().toLowerCase();
        if (!emotion || seen.has(emotion)) {
            continue;
        }
        seen.add(emotion);
        unique.push(emotion);
    }

    if (unique.length === 0) {
        unique.push('normal');
    }
    return unique;
}

function syncAvailableEmotionsFromConfig() {
    currentAvailableEmotions = new Set(resolveAvailableEmotionsFromConfig());
}

function normalizeThemeHex(value) {
    const raw = typeof value === 'string' ? value.trim() : '';
    const match = raw.match(/^#?([0-9A-Fa-f]{6})$/);
    if (!match) {
        return DEFAULT_THEME.accentColor;
    }
    return `#${match[1].toUpperCase()}`;
}

function hexToRgbTriplet(hex) {
    const normalized = normalizeThemeHex(hex);
    const color = normalized.slice(1);
    const red = parseInt(color.slice(0, 2), 16);
    const green = parseInt(color.slice(2, 4), 16);
    const blue = parseInt(color.slice(4, 6), 16);
    return `${red}, ${green}, ${blue}`;
}

function darkenThemeHex(hex, factor = 0.9) {
    const normalized = normalizeThemeHex(hex);
    const color = normalized.slice(1);
    const toChannel = (offset) => Math.max(0, Math.min(255, Math.round(parseInt(color.slice(offset, offset + 2), 16) * factor)));
    const red = toChannel(0).toString(16).padStart(2, '0');
    const green = toChannel(2).toString(16).padStart(2, '0');
    const blue = toChannel(4).toString(16).padStart(2, '0');
    return `#${(red + green + blue).toUpperCase()}`;
}

function hexToRgba(hex, alpha) {
    return `rgba(${hexToRgbTriplet(hex)}, ${alpha})`;
}

function getThemeTextColor(hex) {
    const normalized = normalizeThemeHex(hex);
    const color = normalized.slice(1);
    const red = parseInt(color.slice(0, 2), 16);
    const green = parseInt(color.slice(2, 4), 16);
    const blue = parseInt(color.slice(4, 6), 16);
    const luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
    return luminance < 0.62 ? '#FFFFFF' : '#111827';
}

function applyThemeVariables(themeConfig) {
    const normalizedTheme = {
        accentColor: normalizeThemeHex(themeConfig.accentColor || DEFAULT_THEME.accentColor),
        settingsWindowBgColor: normalizeThemeHex(themeConfig.settingsWindowBgColor || DEFAULT_THEME.settingsWindowBgColor),
        settingsCardBgColor: normalizeThemeHex(themeConfig.settingsCardBgColor || DEFAULT_THEME.settingsCardBgColor),
        settingsInputBgColor: normalizeThemeHex(themeConfig.settingsInputBgColor || DEFAULT_THEME.settingsInputBgColor),
        chatPanelBgColor: normalizeThemeHex(themeConfig.chatPanelBgColor || DEFAULT_THEME.chatPanelBgColor),
        chatInputBgColor: normalizeThemeHex(themeConfig.chatInputBgColor || DEFAULT_THEME.chatInputBgColor),
        chatAssistantBubbleColor: normalizeThemeHex(themeConfig.chatAssistantBubbleColor || DEFAULT_THEME.chatAssistantBubbleColor),
        chatUserBubbleColor: normalizeThemeHex(themeConfig.chatUserBubbleColor || DEFAULT_THEME.chatUserBubbleColor)
    };

    const accent = normalizedTheme.accentColor;
    const rgbTriplet = hexToRgbTriplet(accent);
    const root = document.documentElement;
    const panelText = getThemeTextColor(normalizedTheme.chatPanelBgColor);
    const panelTextRgb = hexToRgbTriplet(panelText);
    const inputText = getThemeTextColor(normalizedTheme.chatInputBgColor);
    const inputTextRgb = hexToRgbTriplet(inputText);
    const assistantText = getThemeTextColor(normalizedTheme.chatAssistantBubbleColor);
    const userText = getThemeTextColor(normalizedTheme.chatUserBubbleColor);

    root.style.setProperty('--ene-accent', accent);
    root.style.setProperty('--ene-accent-hover', darkenThemeHex(accent, 0.9));
    root.style.setProperty('--ene-accent-rgb', rgbTriplet);
    root.style.setProperty('--ene-accent-soft', `rgba(${rgbTriplet}, 0.12)`);
    root.style.setProperty('--ene-accent-soft-strong', `rgba(${rgbTriplet}, 0.18)`);
    root.style.setProperty('--ene-accent-border', `rgba(${rgbTriplet}, 0.38)`);
    root.style.setProperty('--ene-chat-panel-bg', hexToRgba(normalizedTheme.chatPanelBgColor, 0.78));
    root.style.setProperty('--ene-chat-panel-border', `rgba(${panelTextRgb}, 0.12)`);
    root.style.setProperty('--ene-chat-panel-divider', `rgba(${panelTextRgb}, 0.06)`);
    root.style.setProperty('--ene-chat-panel-text', `rgba(${panelTextRgb}, 0.95)`);
    root.style.setProperty('--ene-chat-panel-muted-text', `rgba(${panelTextRgb}, 0.78)`);
    root.style.setProperty('--ene-chat-input-wrap-bg', hexToRgba(normalizedTheme.chatPanelBgColor, 0.66));
    root.style.setProperty('--ene-chat-input-bg', hexToRgba(normalizedTheme.chatInputBgColor, 0.94));
    root.style.setProperty('--ene-chat-input-focus-bg', hexToRgba(normalizedTheme.chatInputBgColor, 0.98));
    root.style.setProperty('--ene-chat-input-border', `rgba(${inputTextRgb}, 0.16)`);
    root.style.setProperty('--ene-chat-input-text', inputText);
    root.style.setProperty('--ene-chat-input-placeholder', `rgba(${inputTextRgb}, 0.50)`);
    root.style.setProperty('--ene-chat-assistant-bubble-bg', hexToRgba(normalizedTheme.chatAssistantBubbleColor, 0.96));
    root.style.setProperty('--ene-chat-assistant-bubble-text', assistantText);
    root.style.setProperty('--ene-chat-user-bubble-bg', hexToRgba(normalizedTheme.chatUserBubbleColor, 0.88));
    root.style.setProperty('--ene-chat-user-bubble-text', userText);
    root.style.setProperty('--ene-floating-panel-bg', hexToRgba(normalizedTheme.chatPanelBgColor, 0.74));
    root.style.setProperty('--ene-floating-panel-border', `rgba(${panelTextRgb}, 0.18)`);
    root.style.setProperty('--ene-floating-panel-text', `rgba(${panelTextRgb}, 0.95)`);
    root.style.setProperty('--ene-floating-panel-muted-text', `rgba(${panelTextRgb}, 0.75)`);
    root.style.setProperty('--ene-floating-panel-button-bg', `rgba(${panelTextRgb}, 0.10)`);
    root.style.setProperty('--ene-floating-panel-button-hover', `rgba(${panelTextRgb}, 0.18)`);

    currentThemeAccent = accent;
    return normalizedTheme;
}

window.applyENETheme = function applyENETheme(config) {
    window.eneThemeConfig = { ...DEFAULT_THEME, ...(window.eneThemeConfig || {}), ...(config || {}) };
    return applyThemeVariables(window.eneThemeConfig);
};

window.applyENETheme(window.eneThemeConfig);
syncAvailableEmotionsFromConfig();

function resolveBrowserSpeechVoice(preferredVoice, preferredLang) {
    if (!('speechSynthesis' in window)) {
        return null;
    }
    const voices = window.speechSynthesis.getVoices() || [];
    const requestedVoice = (preferredVoice || '').trim().toLowerCase();
    const requestedLang = (preferredLang || '').trim().toLowerCase();

    if (requestedVoice) {
        const exact = voices.find((voice) => String(voice.name || '').trim().toLowerCase() === requestedVoice);
        if (exact) {
            return exact;
        }
    }

    if (requestedLang) {
        const byLang = voices.find((voice) => String(voice.lang || '').trim().toLowerCase().startsWith(requestedLang));
        if (byLang) {
            return byLang;
        }
    }

    return voices[0] || null;
}

window.getBrowserTTSVoices = function getBrowserTTSVoices() {
    if (!('speechSynthesis' in window)) {
        return [];
    }
    try {
        const voices = window.speechSynthesis.getVoices() || [];
        return voices.map((voice) => ({
            name: String(voice.name || ''),
            lang: String(voice.lang || ''),
            default: Boolean(voice.default),
            localService: Boolean(voice.localService)
        }));
    } catch (error) {
        console.warn('Failed to enumerate browser TTS voices:', error);
        return [];
    }
};

if ('speechSynthesis' in window) {
    try {
        window.speechSynthesis.getVoices();
    } catch (error) {
        console.warn('Initial browser TTS voice warmup failed:', error);
    }
}

window.stopBrowserTTS = function stopBrowserTTS() {
    if (!('speechSynthesis' in window)) {
        return false;
    }
    try {
        window.speechSynthesis.cancel();
        return true;
    } catch (error) {
        console.warn('Failed to stop browser TTS:', error);
        return false;
    }
};

window.playBrowserTTS = function playBrowserTTS(payload) {
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
        showToast('브라우저 기본 TTS를 사용할 수 없는 환경입니다.', 'error');
        return false;
    }

    const options = payload || {};
    const text = String(options.text || '').trim();
    if (!text) {
        return false;
    }

    try {
        window.stopBrowserTTS();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = String(options.lang || 'ja-JP');
        utterance.rate = Math.max(0.1, Math.min(Number(options.rate || 1.0), 3.0));
        utterance.pitch = Math.max(0.0, Math.min(Number(options.pitch || 1.0), 2.0));
        utterance.volume = Math.max(0.0, Math.min(Number(options.volume || 1.0), 1.0));

        const voice = resolveBrowserSpeechVoice(options.voice, utterance.lang);
        if (voice) {
            utterance.voice = voice;
            utterance.lang = voice.lang || utterance.lang;
        }

        utterance.onerror = (event) => {
            console.warn('Browser TTS error:', event.error || event);
            showToast('브라우저 기본 TTS 재생에 실패했습니다.', 'error');
        };
        window.speechSynthesis.speak(utterance);
        return true;
    } catch (error) {
        console.warn('Failed to play browser TTS:', error);
        showToast('브라우저 기본 TTS 재생에 실패했습니다.', 'error');
        return false;
    }
};
