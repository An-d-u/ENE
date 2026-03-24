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
const DEFAULT_MODEL_PATH = '../live2d_models/jksalt/jksalt.model3.json';
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
window.eneModelConfig = window.eneModelConfig || {};
window.eneThemeConfig = window.eneThemeConfig || {};
let currentModelPath = '';
let currentEmotionsBasePath = '';
let currentAvailableEmotions = new Set(['normal']);
let currentModelLoadToken = 0;
let currentModelErrorText = null;
let currentThemeAccent = DEFAULT_THEME.accentColor;

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

function removeCurrentModelArtifacts() {
    if (window.live2dModel) {
        app.stage.removeChild(window.live2dModel);
        if (typeof window.live2dModel.destroy === 'function') {
            window.live2dModel.destroy();
        }
        window.live2dModel = null;
    }
    if (currentModelErrorText) {
        app.stage.removeChild(currentModelErrorText);
        currentModelErrorText.destroy();
        currentModelErrorText = null;
    }
    trackingParamSupport = null;
    headPatEyeParamSupport = null;
    isHeadPatting = false;
    headPatPointerId = null;
    patRawIntensity = 0;
    patDirection = 0;
    patBlend = 0;
    patBlendMode = 'idle';
}

function applyCurrentModelPlacement() {
    const model = window.live2dModel;
    if (!model) {
        return;
    }

    const config = window.eneModelConfig || {};
    const scale = Number(config.scale ?? 1.0);
    const xPercent = Number(config.xPercent ?? 50);
    const yPercent = Number(config.yPercent ?? 50);

    model.anchor.set(0.5, 0.5);
    model.scale.set(scale);
    model.x = window.innerWidth * (xPercent / 100);
    model.y = window.innerHeight * (yPercent / 100);
}

window.applyENEModelSettings = async function applyENEModelSettings(config) {
    window.eneModelConfig = { ...(window.eneModelConfig || {}), ...(config || {}) };

    const nextModelPath = resolveModelPathFromConfig();
    const nextEmotionsBasePath = resolveEmotionsBasePathFromConfig();
    syncAvailableEmotionsFromConfig();

    if (nextModelPath !== currentModelPath) {
        currentModelPath = nextModelPath;
        currentEmotionsBasePath = nextEmotionsBasePath;
        await loadModel();
        return;
    }

    currentEmotionsBasePath = nextEmotionsBasePath;
    applyCurrentModelPlacement();
};

// Live2D 모델 파일을 로드하고 초기 배치/초기 모션을 적용한다.
async function loadModel() {
    const requestToken = ++currentModelLoadToken;
    const modelPath = resolveModelPathFromConfig();
    const absoluteModelPath = new URL(modelPath, window.location.href).href;

    try {
        console.log(`\n=== Loading model ===`);
        console.log(`Path: ${modelPath}`);
        console.log(`Absolute path: ${absoluteModelPath}`);
        removeCurrentModelArtifacts();
        console.log("Calling PIXI.live2d.Live2DModel.from()...");
        const model = await PIXI.live2d.Live2DModel.from(modelPath);
        if (requestToken !== currentModelLoadToken) {
            if (typeof model.destroy === 'function') {
                model.destroy();
            }
            return;
        }

        console.log("Model loaded successfully!");
        console.log("Model size:", model.width, "x", model.height);
        window.live2dModel = model;
        app.stage.addChild(model);
        applyCurrentModelPlacement();

        console.log(`Model positioned at (${model.x}, ${model.y}) with scale ${model.scale.x}`);
        if (model.internalModel && model.internalModel.motionManager) {
            console.log("Motion manager available");
            try {
                model.motion('Idle');
                console.log("Idle motion started");
            } catch (e) {
                console.warn("Failed to start Idle motion:", e);
            }
        } else {
            console.log("No motion manager found");
        }
        if (model.internalModel && model.internalModel.eyeBlink) {
            console.log("Eye blink enabled");
        }
        window.live2dModel = model;

        console.log("=== Model setup complete ===\n");

    } catch (error) {
        console.error("Failed to load Live2D model");
        console.error("Error:", error);
        console.error("Error type:", error.constructor.name);
        console.error("Error message:", error.message);
        if (error.stack) {
            console.error("Stack trace:", error.stack);
        }
        currentModelErrorText = new PIXI.Text(
            `Live2D 모델 로드 실패\n\n` +
            `에러: ${error.message}\n\n` +
            `경로: ${modelPath}\n` +
            `절대경로: ${absoluteModelPath}\n\n` +
            `콘솔을 확인해 주세요 (F12)`,
            {
                fontFamily: 'Arial',
                fontSize: 14,
                fill: 0xff0000,
                align: 'center',
                wordWrap: true,
                wordWrapWidth: window.innerWidth - 40
            }
        );
        currentModelErrorText.x = window.innerWidth / 2;
        currentModelErrorText.y = window.innerHeight / 2;
        currentModelErrorText.anchor.set(0.5);
        app.stage.addChild(currentModelErrorText);
    }
}
// 창 크기가 바뀌면 모델의 스케일/중심 좌표를 다시 맞춘다.
window.addEventListener('resize', () => {
    if (window.live2dModel) {
        applyCurrentModelPlacement();
        console.log("Window resized, model repositioned");
    }
});
window.addEventListener('load', () => {
    if (window.live2dModel || currentModelLoadToken > 0) {
        return;
    }
    console.log("\n=== Starting model load ===");
    currentModelPath = resolveModelPathFromConfig();
    currentEmotionsBasePath = resolveEmotionsBasePathFromConfig();
    loadModel();
});

// ==========================================
// 마우스 트래킹/쓰다듬기 상태
// ==========================================
let currentMouseX = 0;
let currentMouseY = 0;
let targetMouseX = 0;
let targetMouseY = 0;
let mouseTrackingEnabled = true;
let lastMouseUpdateAt = performance.now();
let lastTargetUpdateAt = performance.now();
let trackingParamSupport = null;
let headPatEyeParamSupport = null;
let idleMotionEnabled = true;
let idleMotionDynamicMode = false;
let idleMotionPhase = 0;
let lastSpeechAt = 0;
let headPatEnabled = true;
let headPatStrength = 1.0;
let headPatEventsBound = false;
let isHeadPatting = false;
let headPatPointerId = null;
let headPatLastX = 0;
let headPatLastY = 0;
let headPatLastMoveAt = 0;
let patRawIntensity = 0;
let patDirection = 0;
let patBlend = 0;
let patBlendMode = 'idle'; // idle | in | hold | out
let patFadeElapsedMs = 0;
let patOffsetsCurrent = { angleX: 0, angleY: 0, bodyX: 0, eyeY: 0 };
let patOffsetsApplied = { angleX: 0, angleY: 0, bodyX: 0, eyeY: 0 };
let lastNonPatTrackingState = { angleX: 0, angleY: 0, bodyX: 0, eyeY: 0 };
let previousEmotionBeforePat = 'normal';
let currentEmotionTag = 'normal';
let baseEmotionTag = 'normal';
let pendingPatEmotionTimer = null;
let pendingPatRestoreEmotion = null;
let headPatFadeInMs = 180;
let headPatFadeOutMs = 220;
let headPatActiveEmotion = 'eyeclose';
let headPatEndEmotion = 'shy';
let headPatEndEmotionDurationMs = 5000;
let headPatSessionCounted = false;
let headPatSavedEyeBlink = undefined;
let headPatEyeBlinkDisabled = false;

const TRACKING_CLAMP = 1.5;
// Vertical bias for gaze tracking.
// Negative: look slightly upward, Positive: look slightly downward.
const TRACKING_Y_OFFSET = 0.08;
const TRACKING_IDLE_TIMEOUT_MS = 1200;
const TRACKING_DAMPING_AT_60FPS = 0.2;
const TRACKING_FACE_Y_RATIO = 0.32;
const IDLE_MOTION_BASE_SPEED_HZ = 0.12;
const IDLE_MOTION_BASE_ANGLE_X = 2.5;
const IDLE_MOTION_BASE_ANGLE_Y = 0.8;
const IDLE_MOTION_BASE_BODY_X = 1.3;
const SPEECH_IDLE_BLOCK_MS = 450;
const HEAD_PAT_SPEED_EMA = 0.28;
const HEAD_PAT_INTENSITY_EMA = 0.22;
const HEAD_PAT_DIRECTION_EMA = 0.35;
const HEAD_PAT_SPEED_GAIN = 0.95;
const HEAD_PAT_DECAY_AT_60FPS = 0.84;

let idleMotionSpeedHz = IDLE_MOTION_BASE_SPEED_HZ;
let idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X;
let idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y;
let idleMotionBodyX = IDLE_MOTION_BASE_BODY_X;

// 마우스 트래킹에 사용할 Live2D coreModel 인스턴스를 가져온다.
function getTrackingCoreModel() {
    const model = window.live2dModel;
    if (!model || !model.internalModel || !model.internalModel.coreModel) {
        return null;
    }
    return model.internalModel.coreModel;
}

// 모델이 지원하는 시선/몸통 파라미터 유무를 1회 감지해 캐시한다.
function detectTrackingParams(coreModel) {
    if (trackingParamSupport) {
        return trackingParamSupport;
    }

    const hasParam = (paramId) => {
        try {
            return coreModel.getParameterIndex(paramId) >= 0;
        } catch (_) {
            return false;
        }
    };

    trackingParamSupport = {
        angleX: hasParam('ParamAngleX'),
        angleY: hasParam('ParamAngleY'),
        bodyAngleX: hasParam('ParamBodyAngleX'),
        eyeBallX: hasParam('ParamEyeBallX'),
        eyeBallY: hasParam('ParamEyeBallY'),
    };

    return trackingParamSupport;
}

// 정규화된 시선 입력값을 실제 Live2D 파라미터 값으로 변환해 적용한다.
function applyTrackingParams(coreModel, x, y, idleOffsets = null) {
    const support = detectTrackingParams(coreModel);
    const idleAngleX = idleOffsets ? idleOffsets.angleX : 0;
    const idleAngleY = idleOffsets ? idleOffsets.angleY : 0;
    const idleBodyX = idleOffsets ? idleOffsets.bodyX : 0;
    const idleEyeY = idleOffsets && Number.isFinite(idleOffsets.eyeY) ? idleOffsets.eyeY : 0;
    if (support.angleX) coreModel.setParameterValueById('ParamAngleX', (x * 15) + idleAngleX);
    if (support.angleY) coreModel.setParameterValueById('ParamAngleY', (-y * 15) + idleAngleY);
    if (support.bodyAngleX) coreModel.setParameterValueById('ParamBodyAngleX', (x * 5) + idleBodyX);
    if (support.eyeBallX) coreModel.setParameterValueById('ParamEyeBallX', x * 0.8);
    if (support.eyeBallY) coreModel.setParameterValueById('ParamEyeBallY', (-y * 0.8) + idleEyeY);
}

// 쓰다듬기 시 눈 감기 오버라이드에 필요한 파라미터 지원 여부를 확인한다.
function detectHeadPatEyeParams(coreModel) {
    if (headPatEyeParamSupport) {
        return headPatEyeParamSupport;
    }

    const hasParam = (paramId) => {
        try {
            return coreModel.getParameterIndex(paramId) >= 0;
        } catch (_) {
            return false;
        }
    };

    headPatEyeParamSupport = {
        eyeLOpen: hasParam('ParamEyeLOpen'),
        eyeROpen: hasParam('ParamEyeROpen'),
        eyeLSquint: hasParam('ParamEyeLSquint'),
        eyeRSquint: hasParam('ParamEyeRSquint'),
    };
    return headPatEyeParamSupport;
}

// 쓰다듬기 강도에 맞춰 눈 파라미터를 보정한다.
function applyHeadPatEyeCloseOverride(coreModel, blend) {
    const support = detectHeadPatEyeParams(coreModel);
    const closeAmount = clamp01(blend);
    const openValue = 1 - closeAmount;

    if (support.eyeLOpen) coreModel.setParameterValueById('ParamEyeLOpen', openValue);
    if (support.eyeROpen) coreModel.setParameterValueById('ParamEyeROpen', openValue);
    if (support.eyeLSquint) coreModel.setParameterValueById('ParamEyeLSquint', closeAmount);
    if (support.eyeRSquint) coreModel.setParameterValueById('ParamEyeRSquint', closeAmount);
}

// 립싱크 직후 구간인지 판정해 idle 모션 간섭을 줄인다.
function isSpeakingNow(nowMs) {
    return (nowMs - lastSpeechAt) < SPEECH_IDLE_BLOCK_MS;
}

// idle 모션 전체 활성/비활성 토글.
window.setIdleMotionEnabled = function (enabled) {
    idleMotionEnabled = Boolean(enabled);
    if (!idleMotionEnabled) {
        idleMotionPhase = 0;
    }
    console.log("Idle motion:", idleMotionEnabled ? "enabled" : "disabled");
};

// idle 모션 강도/속도 설정을 JS 쪽 상태값으로 반영한다.
window.setIdleMotionConfig = function (strength, speed) {
    const s = Number.isFinite(strength) ? Math.min(2.0, Math.max(0.2, Number(strength))) : 1.0;
    const v = Number.isFinite(speed) ? Math.min(2.0, Math.max(0.5, Number(speed))) : 1.0;

    idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X * s;
    idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y * s;
    idleMotionBodyX = IDLE_MOTION_BASE_BODY_X * s;
    idleMotionSpeedHz = IDLE_MOTION_BASE_SPEED_HZ * v;
};

// idle 동적 모드(상황별 가감)를 켜거나 끈다.
window.setIdleMotionDynamic = function (enabled) {
    idleMotionDynamicMode = Boolean(enabled);
    console.log("Idle motion dynamic mode:", idleMotionDynamicMode ? "enabled" : "disabled");
};

// 쓰다듬기 감도/페이드/동작 파라미터를 일괄 설정한다.
window.setHeadPatConfig = function (
    enabled,
    strength,
    fadeInMs = 180,
    fadeOutMs = 220,
    activeEmotion = 'eyeclose',
    endEmotion = 'shy',
    endEmotionDurationSec = 5
) {
    headPatEnabled = Boolean(enabled);
    headPatStrength = Number.isFinite(strength) ? Math.min(2.5, Math.max(0.5, Number(strength))) : 1.0;
    headPatFadeInMs = Number.isFinite(fadeInMs) ? Math.min(1000, Math.max(50, Number(fadeInMs))) : 180;
    headPatFadeOutMs = Number.isFinite(fadeOutMs) ? Math.min(1200, Math.max(50, Number(fadeOutMs))) : 220;
    headPatActiveEmotion = typeof activeEmotion === 'string' && activeEmotion.trim() ? activeEmotion.trim() : 'eyeclose';
    headPatEndEmotion = typeof endEmotion === 'string' && endEmotion.trim() ? endEmotion.trim() : 'shy';
    headPatEndEmotionDurationMs = Number.isFinite(endEmotionDurationSec)
        ? Math.min(30000, Math.max(1000, Number(endEmotionDurationSec) * 1000))
        : 5000;

    if (!headPatEnabled) {
        isHeadPatting = false;
        headPatPointerId = null;
        patRawIntensity = 0;
        patDirection = 0;
        patBlend = 0;
        patBlendMode = 'idle';
        setHeadPatEyeBlinkEnabled(true);
    }
    console.log(
        "Head pat:",
        headPatEnabled ? "enabled" : "disabled",
        "strength=", headPatStrength,
        "fadeIn=", headPatFadeInMs,
        "fadeOut=", headPatFadeOutMs,
        "activeEmotion=", headPatActiveEmotion,
        "emotion=", headPatEndEmotion,
        "durationMs=", headPatEndEmotionDurationMs
    );
};

// 쓰다듬기 중/종료 후 표정 전환 규칙을 설정한다.
window.setHeadPatEmotionConfig = function (activeEmotion = 'eyeclose', endEmotion = 'shy', endEmotionDurationSec = 5) {
    headPatActiveEmotion = typeof activeEmotion === 'string' && activeEmotion.trim() ? activeEmotion.trim() : 'eyeclose';
    headPatEndEmotion = typeof endEmotion === 'string' && endEmotion.trim() ? endEmotion.trim() : 'shy';
    headPatEndEmotionDurationMs = Number.isFinite(endEmotionDurationSec)
        ? Math.min(30000, Math.max(1000, Number(endEmotionDurationSec) * 1000))
        : 5000;
};

// 0~1 범위로 clamp.
function clamp01(v) {
    return Math.max(0, Math.min(1, v));
}

// 부드러운 페이드용 easing 함수.
function easeInOutCubic(t) {
    const x = clamp01(t);
    return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

// 선형 보간 함수.
function lerp(a, b, t) {
    return a + ((b - a) * t);
}

// 포인터가 머리 쓰다듬기 유효 영역에 들어왔는지 판정한다.
function isHeadPatPoint(pointerX, pointerY) {
    const model = window.live2dModel;
    if (!model) return false;

    try {
        if (typeof model.hitTest === 'function') {
            const hitAreas = ['Head', 'head', 'Face', 'face', 'HeadTouch', 'Body'];
            for (const areaName of hitAreas) {
                try {
                    if (model.hitTest(areaName, pointerX, pointerY)) {
                        return true;
                    }
                } catch (_) {
                }
            }
        }
    } catch (_) {
        // hitTest failed, continue with bounds fallback
    }

    try {
        if (typeof model.getBounds !== 'function') return false;
        const bounds = model.getBounds();
        if (!bounds || !Number.isFinite(bounds.width) || !Number.isFinite(bounds.height)) return false;
        if (bounds.width <= 0 || bounds.height <= 0) return false;

        const minX = bounds.x + (bounds.width * 0.12);
        const maxX = bounds.x + (bounds.width * 0.88);
        const minY = bounds.y + (bounds.height * 0.02);
        const maxY = bounds.y + (bounds.height * 0.58);
        return pointerX >= minX && pointerX <= maxX && pointerY >= minY && pointerY <= maxY;
    } catch (_) {
        return false;
    }
}

// 쓰다듬기 시작 이벤트 처리.
function onHeadPatPointerDown(event) {
    if (!headPatEnabled) return;
    if (event.pointerType === 'mouse' && event.button !== 0) return;

    const chatContainer = document.getElementById('chat-container');
    if (chatContainer && chatContainer.contains(event.target)) {
        return;
    }

    if (!isHeadPatPoint(event.clientX, event.clientY)) {
        return;
    }

    const restoreBaseEmotion = pendingPatRestoreEmotion || baseEmotionTag || currentEmotionTag || 'normal';
    cancelPendingPatEmotionRestore();
    previousEmotionBeforePat = restoreBaseEmotion;
    triggerPatStartEmotion();
    setHeadPatEyeBlinkEnabled(false);
    isHeadPatting = true;
    headPatSessionCounted = false;
    headPatPointerId = event.pointerId;
    headPatLastX = event.clientX;
    headPatLastY = event.clientY;
    headPatLastMoveAt = performance.now();
    patRawIntensity = Math.max(patRawIntensity, 0.12);
    patBlendMode = 'in';
    patFadeElapsedMs = 0;
    lastNonPatTrackingState = { ...patOffsetsApplied };
    if (event.target && typeof event.target.setPointerCapture === 'function') {
        try {
            event.target.setPointerCapture(event.pointerId);
        } catch (_) {
        }
    }
    event.preventDefault();
}

// 쓰다듬기 중 포인터 이동량을 누적해 강도/방향을 계산한다.
function onHeadPatPointerMove(event) {
    if (!isHeadPatting || !headPatEnabled) return;
    if (event.pointerId !== headPatPointerId) return;

    const nowMs = performance.now();
    const dtMs = Math.max(1, nowMs - headPatLastMoveAt);
    const dx = event.clientX - headPatLastX;
    const dy = event.clientY - headPatLastY;
    const distance = Math.sqrt((dx * dx) + (dy * dy));
    const speedPxPerMs = distance / dtMs;

    patRawIntensity += (speedPxPerMs - patRawIntensity) * HEAD_PAT_SPEED_EMA;
    patRawIntensity = Math.max(0, Math.min(1, patRawIntensity * HEAD_PAT_SPEED_GAIN * headPatStrength));

    const directionRaw = dx / (Math.abs(dx) + Math.abs(dy) + 0.0001);
    patDirection += (directionRaw - patDirection) * HEAD_PAT_DIRECTION_EMA;

    headPatLastX = event.clientX;
    headPatLastY = event.clientY;
    headPatLastMoveAt = nowMs;
}

// 쓰다듬기 종료 이벤트 처리.
function onHeadPatPointerUp(event) {
    if (!isHeadPatting) return;
    if (event.pointerId !== headPatPointerId) return;

    isHeadPatting = false;
    headPatPointerId = null;
    patBlendMode = 'out';
    patFadeElapsedMs = 0;
    if (!headPatSessionCounted) {
        notifyHeadPatSessionCount();
        headPatSessionCounted = true;
    }
    if (event.target && typeof event.target.releasePointerCapture === 'function') {
        try {
            event.target.releasePointerCapture(event.pointerId);
        } catch (_) {
        }
    }
    triggerPatEndEmotion();
}

// 쓰다듬기 세션 카운트를 Python 브리지로 보고한다.
function notifyHeadPatSessionCount() {
    if (!window.pyBridge || typeof window.pyBridge.increment_head_pat_count_from_js !== 'function') {
        return;
    }
    try {
        window.pyBridge.increment_head_pat_count_from_js();
    } catch (e) {
        console.warn("Failed to sync head pat count:", e);
    }
}

// 예약된 표정 복구 타이머를 취소한다.
function cancelPendingPatEmotionRestore() {
    if (pendingPatEmotionTimer) {
        clearTimeout(pendingPatEmotionTimer);
        pendingPatEmotionTimer = null;
    }
    pendingPatRestoreEmotion = null;
}

// 쓰다듬기 종료 표정을 잠시 적용한 뒤 기본 표정으로 복귀시킨다.
function triggerPatEndEmotion() {
    cancelPendingPatEmotionRestore();
    let endEmotion = (headPatEndEmotion || 'shy').trim();
    if (!endEmotion) endEmotion = 'shy';
    changeExpression(endEmotion);
    pendingPatRestoreEmotion = previousEmotionBeforePat || baseEmotionTag || 'normal';
    const applyRestoreWhenPossible = () => {
        const restoreEmotion = pendingPatRestoreEmotion || 'normal';
        if (isHeadPatting) {
            // 쓰다듬는 중에는 복귀를 미루고 원래 감정을 유지한다.
            pendingPatEmotionTimer = setTimeout(applyRestoreWhenPossible, 250);
            return;
        }

        pendingPatEmotionTimer = null;
        pendingPatRestoreEmotion = null;
        baseEmotionTag = restoreEmotion;
        changeExpression(restoreEmotion);
    };
    pendingPatEmotionTimer = setTimeout(applyRestoreWhenPossible, headPatEndEmotionDurationMs);
}

// 쓰다듬기 시작 시 활성 표정을 즉시 적용한다.
function triggerPatStartEmotion() {
    let activeEmotion = (headPatActiveEmotion || 'eyeclose').trim();
    if (!activeEmotion) activeEmotion = 'eyeclose';
    changeExpression(activeEmotion);
}

// 포인터 이벤트 리스너를 중복 없이 1회만 바인딩한다.
function ensureHeadPatEventBindings() {
    if (headPatEventsBound) return;

    const canvas = document.getElementById('live2d-canvas');
    if (!canvas) return;

    canvas.style.touchAction = 'none';
    canvas.addEventListener('pointerdown', onHeadPatPointerDown);
    window.addEventListener('pointermove', onHeadPatPointerMove, { passive: true });
    window.addEventListener('pointerup', onHeadPatPointerUp, { passive: true });
    window.addEventListener('pointercancel', onHeadPatPointerUp, { passive: true });
    headPatEventsBound = true;
}

// 프레임 단위로 쓰다듬기 상태를 감쇠/보간해 갱신한다.
function updateHeadPatState(dtMs) {
    if (!headPatEnabled) {
        patRawIntensity = 0;
        patDirection = 0;
        patBlend = 0;
        patBlendMode = 'idle';
        return;
    }

    const frameScale = dtMs > 0 ? dtMs / (1000 / 60) : 1;
    if (!isHeadPatting) {
        patRawIntensity *= Math.pow(HEAD_PAT_DECAY_AT_60FPS, frameScale);
        patDirection *= Math.pow(0.92, frameScale);
        if (patRawIntensity < 0.0005) patRawIntensity = 0;
        if (Math.abs(patDirection) < 0.0005) patDirection = 0;
    }

    if (patBlendMode === 'in') {
        patFadeElapsedMs += dtMs;
        patBlend = easeInOutCubic(patFadeElapsedMs / Math.max(1, headPatFadeInMs));
        if (patBlend >= 0.999) {
            patBlend = 1;
            patBlendMode = isHeadPatting ? 'hold' : 'out';
            patFadeElapsedMs = 0;
        }
    } else if (patBlendMode === 'out') {
        patFadeElapsedMs += dtMs;
        const outT = easeInOutCubic(patFadeElapsedMs / Math.max(1, headPatFadeOutMs));
        patBlend = 1 - outT;
        if (patBlend <= 0.001) {
            patBlend = 0;
            patBlendMode = 'idle';
            patFadeElapsedMs = 0;
            setHeadPatEyeBlinkEnabled(true);
        }
    } else if (patBlendMode === 'hold') {
        patBlend = 1;
    } else {
        patBlend = 0;
    }
}

// 현재 쓰다듬기 상태를 Live2D 오프셋(각도/몸통/눈)으로 변환한다.
function buildHeadPatOffsets(nowMs) {
    const intensity = Math.max(clamp01(patRawIntensity), clamp01(patBlend * 0.95));
    const sway = Math.sin(nowMs * 0.010) * 0.6 * intensity;

    return {
        angleX: Math.max(-10, Math.min(10, (patDirection * 7.5 * intensity) + sway)),
        angleY: Math.max(-8, Math.min(8, -1.8 - (6.0 * intensity))),
        bodyX: Math.max(-6, Math.min(6, patDirection * 4.2 * intensity)),
        eyeY: Math.max(-0.3, Math.min(0.3, -0.18 * intensity)),
    };
}

// 쓰다듬기 중 자동 눈깜빡임 간섭을 제어한다.
function setHeadPatEyeBlinkEnabled(enabled) {
    const model = window.live2dModel;
    if (!model || !model.internalModel) return;

    try {
        if (enabled) {
            if (headPatEyeBlinkDisabled) {
                model.internalModel.eyeBlink = headPatSavedEyeBlink ?? null;
                headPatEyeBlinkDisabled = false;
                console.log("Head pat: EyeBlink restored");
            }
            return;
        }

        if (headPatEyeBlinkDisabled) return;
        headPatSavedEyeBlink = model.internalModel.eyeBlink;
        if (headPatSavedEyeBlink) {
            model.internalModel.eyeBlink = null;
            headPatEyeBlinkDisabled = true;
            console.log("Head pat: EyeBlink disabled");
        }
    } catch (e) {
        console.warn("Head pat EyeBlink toggle failed:", e);
    }
}

/**
 * Python 브리지에서 받은 마우스 좌표를 정규화해 타깃 값으로 반영한다.
 */
// Python에서 전달한 실제 마우스 좌표를 트래킹 타깃으로 저장한다.
window.updateMousePosition = function (mouseX, mouseY) {
    if (!mouseTrackingEnabled) return;
    if (!Number.isFinite(mouseX) || !Number.isFinite(mouseY)) return;

    const model = window.live2dModel;
    if (!model) return;
    const canvasWidth = window.innerWidth;
    const canvasHeight = window.innerHeight;
    let trackingOriginX = model.x;
    let trackingOriginY = model.y;
    try {
        if (typeof model.getBounds === 'function') {
            const bounds = model.getBounds();
            if (bounds && Number.isFinite(bounds.width) && Number.isFinite(bounds.height) && bounds.width > 0 && bounds.height > 0) {
                trackingOriginX = bounds.x + (bounds.width * 0.5);
                trackingOriginY = bounds.y + (bounds.height * TRACKING_FACE_Y_RATIO);
            }
        }
    } catch (_) {
    }

    trackingOriginX = Math.max(0, Math.min(canvasWidth, trackingOriginX));
    trackingOriginY = Math.max(0, Math.min(canvasHeight, trackingOriginY));

    const relativeX = mouseX - trackingOriginX;
    const relativeY = mouseY - trackingOriginY;
    const normalizedX = (relativeX / (canvasWidth * 0.5));

    // Adjust baseline vertical gaze with an offset.
    const normalizedY = (relativeY / (canvasHeight * 0.5)) + TRACKING_Y_OFFSET;
    targetMouseX = Math.max(-TRACKING_CLAMP, Math.min(TRACKING_CLAMP, normalizedX));
    targetMouseY = Math.max(-TRACKING_CLAMP, Math.min(TRACKING_CLAMP, normalizedY));
    lastTargetUpdateAt = performance.now();
};

/**
 * 마우스 트래킹 기능 ON/OFF.
 * @param {boolean} enabled
 */
// 마우스 트래킹 활성화 상태를 변경하고 잔여 상태를 초기화한다.
window.setMouseTrackingEnabled = function (enabled) {
    mouseTrackingEnabled = Boolean(enabled);
    console.log("Mouse tracking:", mouseTrackingEnabled ? "enabled" : "disabled");
    if (!mouseTrackingEnabled) {
        targetMouseX = 0;
        targetMouseY = 0;
    }

    currentMouseX = 0;
    currentMouseY = 0;
    lastTargetUpdateAt = performance.now();
    patBlend = 0;
    patBlendMode = 'idle';
    patRawIntensity = 0;
    patDirection = 0;

    const coreModel = getTrackingCoreModel();
    if (!coreModel) return;

    try {
        applyTrackingParams(coreModel, 0, 0);
    } catch (_) {
    }
};
// 매 프레임 마우스/idle/쓰다듬기 상태를 합성해 파라미터를 적용한다.
function updateMouseTracking(nowMs) {
    ensureHeadPatEventBindings();

    const coreModel = getTrackingCoreModel();
    if (!coreModel) {
        lastMouseUpdateAt = nowMs;
        requestAnimationFrame(updateMouseTracking);
        return;
    }

    if (!mouseTrackingEnabled) {
        targetMouseX = 0;
        targetMouseY = 0;
    }
    if (nowMs - lastTargetUpdateAt > TRACKING_IDLE_TIMEOUT_MS) {
        targetMouseX = 0;
        targetMouseY = 0;
    }
    const dtMs = Math.max(0, Math.min(100, nowMs - lastMouseUpdateAt));
    lastMouseUpdateAt = nowMs;
    const frameScale = dtMs > 0 ? dtMs / (1000 / 60) : 1;
    const damping = 1 - Math.pow(1 - TRACKING_DAMPING_AT_60FPS, frameScale);

    currentMouseX += (targetMouseX - currentMouseX) * damping;
    currentMouseY += (targetMouseY - currentMouseY) * damping;
    if (Math.abs(currentMouseX) < 0.0005) currentMouseX = 0;
    if (Math.abs(currentMouseY) < 0.0005) currentMouseY = 0;
    updateHeadPatState(dtMs);
    const hasHeadPatEffect = headPatEnabled && patBlend > 0.001;

    let idleOffsets = null;
    if (!hasHeadPatEffect && idleMotionEnabled && !isSpeakingNow(nowMs)) {
        idleMotionPhase += dtMs / 1000.0 * Math.PI * 2 * idleMotionSpeedHz;
        if (idleMotionDynamicMode) {
            // Dynamic mode: stronger, layered movement with occasional pulse.
            const pulse = 0.65 + (Math.sin(idleMotionPhase * 0.21 + 0.9) * 0.35);
            const angleXDynamic =
                (Math.sin(idleMotionPhase * 1.6) * idleMotionAngleX * 2.8) +
                (Math.sin(idleMotionPhase * 3.2 + 0.4) * idleMotionAngleX * 0.9 * pulse);
            const angleYDynamic =
                (Math.sin(idleMotionPhase * 1.2 + 1.1) * idleMotionAngleY * 2.4) +
                (Math.sin(idleMotionPhase * 2.8 + 0.2) * idleMotionAngleY * 0.8);
            const bodyXDynamic =
                (Math.sin(idleMotionPhase * 1.05 + 0.6) * idleMotionBodyX * 2.6) +
                (Math.sin(idleMotionPhase * 2.1 + 1.4) * idleMotionBodyX * 0.75);

            idleOffsets = {
                angleX: Math.max(-18, Math.min(18, angleXDynamic)),
                angleY: Math.max(-12, Math.min(12, angleYDynamic)),
                bodyX: Math.max(-10, Math.min(10, bodyXDynamic))
            };
        } else {
            idleOffsets = {
                angleX: Math.sin(idleMotionPhase) * idleMotionAngleX,
                angleY: Math.sin(idleMotionPhase * 0.7 + 1.2) * idleMotionAngleY,
                bodyX: Math.sin(idleMotionPhase * 0.5 + 0.6) * idleMotionBodyX
            };
        }
    }

    const baseTrackingOffsets = idleOffsets || { angleX: 0, angleY: 0, bodyX: 0, eyeY: 0 };
    if (!hasHeadPatEffect) {
        lastNonPatTrackingState = { ...baseTrackingOffsets };
    }
    patOffsetsCurrent = buildHeadPatOffsets(nowMs);
    patOffsetsApplied = {
        angleX: lerp(lastNonPatTrackingState.angleX, patOffsetsCurrent.angleX, patBlend),
        angleY: lerp(lastNonPatTrackingState.angleY, patOffsetsCurrent.angleY, patBlend),
        bodyX: lerp(lastNonPatTrackingState.bodyX, patOffsetsCurrent.bodyX, patBlend),
        eyeY: lerp(lastNonPatTrackingState.eyeY, patOffsetsCurrent.eyeY, patBlend),
    };

    try {
        if (hasHeadPatEffect) {
            applyTrackingParams(coreModel, 0, 0, patOffsetsApplied);
            applyHeadPatEyeCloseOverride(coreModel, patBlend);
        } else {
            applyTrackingParams(coreModel, currentMouseX, currentMouseY, idleOffsets);
        }
    } catch (_) {
    }

    requestAnimationFrame(updateMouseTracking);
}
requestAnimationFrame(updateMouseTracking);
console.log("Mouse tracking initialized");

// ==========================================
// 감정 표정 제어
// ==========================================
/**
 * 현재 표정 전환 애니메이션 상태.
 */
let currentExpressionAnimation = null;
let previousExpressionParams = [];

function resolveExpressionEmotion(emotion) {
    const normalized = String(emotion || '').trim().toLowerCase();
    if (normalized && currentAvailableEmotions.has(normalized)) {
        return normalized;
    }
    if (normalized) {
        console.warn(`Unknown emotion for current model: ${normalized}`);
    }
    if (currentAvailableEmotions.has('normal')) {
        return 'normal';
    }
    return '';
}

// 감정 태그에 맞는 exp3 표정 파일을 로드/보간 적용한다.
async function changeExpression(emotion) {
    const model = window.live2dModel;
    if (!model) {
        console.warn("Model not loaded, cannot change expression");
        return;
    }

    const resolvedEmotion = resolveExpressionEmotion(emotion);
    if (!resolvedEmotion) {
        return;
    }

    try {
        currentEmotionTag = resolvedEmotion;
        if (resolvedEmotion === 'normal') {
            console.log('Resetting to normal expression');
            if (currentExpressionAnimation) {
                cancelAnimationFrame(currentExpressionAnimation);
            }
            const model = window.live2dModel;
            if (model.internalModel && model.internalModel.coreModel) {
                const startValues = {};
                const targetValues = {};

                previousExpressionParams.forEach(paramId => {
                    try {
                        const currentValue = model.internalModel.coreModel.getParameterValueById(paramId);
                        startValues[paramId] = currentValue;
                        targetValues[paramId] = 0;
                    } catch (e) {
                    }
                });
                const duration = 300;
                const startTime = Date.now();

                function animate() {
                    const elapsed = Date.now() - startTime;
                    const progress = Math.min(elapsed / duration, 1.0);
                    const eased = 1 - Math.pow(1 - progress, 3);

                    Object.keys(targetValues).forEach(paramId => {
                        try {
                            const start = startValues[paramId] || 0;
                            const target = targetValues[paramId];
                            const value = start + (target - start) * eased;
                            model.internalModel.coreModel.setParameterValueById(paramId, value);
                        } catch (e) {
                            // 파라미터가 없는 모델에서는 무시
                        }
                    });

                    if (progress < 1.0) {
                        currentExpressionAnimation = requestAnimationFrame(animate);
                    } else {
                        currentExpressionAnimation = null;
                        previousExpressionParams = [];
                        console.log('Reset to normal complete');
                    }
                }

                animate();
            }
            return;
        }
        const expressionPath = new URL(`${resolvedEmotion}.exp3.json`, currentEmotionsBasePath).href;
        console.log(`Changing expression to: ${resolvedEmotion} (${expressionPath})`);
        if (model.internalModel && model.internalModel.coreModel) {
            const response = await fetch(expressionPath);
            const expressionData = await response.json();
            if (currentExpressionAnimation) {
                cancelAnimationFrame(currentExpressionAnimation);
            }
            const startValues = {};
            const targetValues = {};
            previousExpressionParams.forEach(paramId => {
                try {
                    const currentValue = model.internalModel.coreModel.getParameterValueById(paramId);
                    startValues[paramId] = currentValue;
                    targetValues[paramId] = 0;
                } catch (e) {
                }
            });
            const newExpressionParams = [];
            expressionData.Parameters.forEach(param => {
                try {
                    const currentValue = model.internalModel.coreModel.getParameterValueById(param.Id);
                    startValues[param.Id] = currentValue;
                    targetValues[param.Id] = param.Value;
                    newExpressionParams.push(param.Id);
                } catch (e) {
                    console.warn(`Failed to get parameter ${param.Id}:`, e);
                }
            });
            previousExpressionParams = newExpressionParams;
            const duration = 500;
            const startTime = Date.now();
            function animate() {
                const elapsed = Date.now() - startTime;
                const progress = Math.min(elapsed / duration, 1.0);
                const eased = 1 - Math.pow(1 - progress, 3);
                Object.keys(targetValues).forEach(paramId => {
                    try {
                        const start = startValues[paramId] || 0;
                        const target = targetValues[paramId];
                        const value = start + (target - start) * eased;

                        model.internalModel.coreModel.setParameterValueById(
                            paramId,
                            value
                        );
                    } catch (e) {
                        // 파라미터가 없는 모델에서는 무시
                    }
                });
                if (progress < 1.0) {
                    currentExpressionAnimation = requestAnimationFrame(animate);
                } else {
                    currentExpressionAnimation = null;
                    console.log(`Expression animation complete: ${resolvedEmotion}`);
                }
            }
            animate();

            console.log(`Expression changing to: ${resolvedEmotion}`);
        }
    } catch (error) {
        console.error(`Failed to load expression ${resolvedEmotion}:`, error);
    }
}

// ==========================================
// 채팅/버튼 UI
// ==========================================

const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const sendButton = document.getElementById('send-button');
const manualSummarizeButton = document.getElementById('manual-summarize-floating-btn');
const attachButton = document.getElementById('attach-button');
const imageInput = document.getElementById('image-input');
const imagePreviewContainer = document.getElementById('image-preview-container');
const loadingIndicator = document.getElementById('loading-indicator');
const summaryConfirmOverlay = document.getElementById('summary-confirm-overlay');
const summaryConfirmYesButton = document.getElementById('summary-confirm-yes');
const summaryConfirmNoButton = document.getElementById('summary-confirm-no');
const toastContainer = document.getElementById('toast-container');
const moodToggleButton = document.getElementById('mood-toggle-floating-btn');
const obsNoteButton = document.getElementById('obs-note-floating-btn');
const moodWidget = document.getElementById('mood-status-widget');
const moodStatusHeader = document.getElementById('mood-status-header');
const moodCollapseButton = document.getElementById('mood-status-collapse-btn');
const moodStatusLabel = document.getElementById('mood-status-label');
const moodMeterValence = document.getElementById('mood-meter-valence');
const moodMeterBond = document.getElementById('mood-meter-bond');
const moodMeterEnergy = document.getElementById('mood-meter-energy');
const moodMeterStress = document.getElementById('mood-meter-stress');
const obsPanel = document.getElementById('obs-panel');
const obsTree = document.getElementById('obs-tree');
const obsRefreshBtn = document.getElementById('obs-refresh-btn');
const tokenUsageBubble = document.getElementById('token-usage-bubble');
const MAX_ATTACHMENT_COUNT = 5;
const SUPPORTED_DOCUMENT_EXTENSIONS = new Set(['txt', 'md', 'pdf', 'docx']);
let attachedAttachments = [];
let rerollButtonVisibleBySetting = true;
let recentEditButtonVisibleBySetting = true;
let manualSummaryButtonVisibleBySetting = true;
let moodToggleButtonVisibleBySetting = true;
let obsidianNoteButtonVisibleBySetting = true;
let tokenUsageBubbleVisibleBySetting = false;
let hasAssistantMessage = false;
let hasUserMessage = false;
let isRequestPending = false;
let shouldReplaceNextAssistant = false;
let lastAssistantMessageEl = null;
let lastUserMessageEl = null;
let moodPanelOpen = false;
let activeInlineEditBubble = null;
let obsCheckedPaths = new Set();
let moodWidgetDragState = null;
let tokenUsageBubbleTimer = null;

function createAttachmentId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
    }
    return `attachment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getFileExtension(name) {
    const normalized = String(name || '').trim();
    const index = normalized.lastIndexOf('.');
    if (index < 0) return '';
    return normalized.slice(index + 1).toLowerCase();
}

function inferMimeTypeFromName(name) {
    const extension = getFileExtension(name);
    if (extension === 'txt') return 'text/plain';
    if (extension === 'md') return 'text/markdown';
    if (extension === 'pdf') return 'application/pdf';
    if (extension === 'docx') return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    return 'application/octet-stream';
}

function classifyAttachment(fileLike) {
    const mimeType = String(fileLike?.type || '').toLowerCase();
    const extension = getFileExtension(fileLike?.name || '');
    if (mimeType.startsWith('image/')) return 'image';
    if (mimeType.startsWith('text/')) return 'document';
    if (extension && SUPPORTED_DOCUMENT_EXTENSIONS.has(extension)) return 'document';
    if (mimeType === 'application/pdf') return 'document';
    if (mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') return 'document';
    return '';
}

function formatAttachmentSubtitle(attachment) {
    if (attachment.category === 'image') {
        if (attachment.width > 0 && attachment.height > 0) {
            return `이미지 ${attachment.width}×${attachment.height}`;
        }
        return '이미지';
    }

    const extension = getFileExtension(attachment.name);
    if (extension === 'pdf') return 'PDF 문서';
    if (extension === 'docx') return 'DOCX 문서';
    if (extension === 'md') return '마크다운 문서';
    if (extension === 'txt') return '텍스트 문서';
    return '문서';
}

function formatAttachmentTokenText(attachment) {
    if (attachment.status === 'error') {
        return attachment.error || '분석에 실패했어요.';
    }
    if (typeof attachment.tokenEstimate === 'number' && attachment.tokenEstimate >= 0) {
        return `추정 ${attachment.tokenEstimate.toLocaleString('ko-KR')} 토큰`;
    }
    return '토큰 계산 중...';
}

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (event) => resolve(String(event?.target?.result || ''));
        reader.onerror = () => reject(reader.error || new Error('파일을 읽지 못했어요.'));
        reader.readAsDataURL(file);
    });
}

function requestAttachmentPreviewMetadata() {
    if (!window.pyBridge || !window.pyBridge.preview_attachments || attachedAttachments.length === 0) {
        return;
    }
    const payload = attachedAttachments.map((attachment) => ({
        id: attachment.id,
        name: attachment.name,
        type: attachment.type,
        dataUrl: attachment.dataUrl
    }));
    window.pyBridge.preview_attachments(JSON.stringify(payload));
}

function applyAttachmentPreviewMetadata(value) {
    let parsed = [];
    try {
        parsed = typeof value === 'string' ? JSON.parse(value) : value;
    } catch (error) {
        console.error('Failed to parse attachment preview payload', error);
        return;
    }

    if (!Array.isArray(parsed)) return;

    parsed.forEach((meta) => {
        const current = attachedAttachments.find((attachment) => attachment.id === meta.id);
        if (!current) return;
        current.category = meta.category || current.category;
        current.tokenEstimate = Number.isFinite(Number(meta.tokenEstimate)) ? Number(meta.tokenEstimate) : current.tokenEstimate;
        current.width = Number.isFinite(Number(meta.width)) ? Number(meta.width) : current.width;
        current.height = Number.isFinite(Number(meta.height)) ? Number(meta.height) : current.height;
        current.status = meta.status || current.status;
        current.error = meta.error || '';
        current.type = meta.type || current.type;
    });

    updateAttachmentPreview();
}

// -1~1 축값을 게이지 표시용 0~1 값으로 정규화한다.
function normalizeMoodAxis(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0.5;
    return Math.max(0, Math.min(1, (n + 1) / 2));
}

// 내부 mood 키를 사용자 표시용 라벨로 변환한다.
function formatMoodLabel(label) {
    const map = {
        calm: '차분함',
        cheerful: '상쾌함',
        affectionate: '애정 충만',
        tired: '피곤함',
        tense: '긴장됨',
        lonely: '쓸쓸함',
    };
    return map[label] || label || '알 수 없음';
}

// mood 바의 width(%)를 갱신한다.
function setMoodMeterWidth(el, normalized) {
    if (!el) return;
    const width = Math.round(Math.max(0, Math.min(1, normalized)) * 100);
    el.style.width = `${width}%`;
}

// mood 위젯 패널 열림/닫힘 상태를 반영한다.
function setMoodPanelOpen(open) {
    moodPanelOpen = Boolean(open);
    if (moodWidget) {
        moodWidget.classList.toggle('hidden', !moodPanelOpen);
    }
}

// 기분 패널을 드래그 가능하게 설정한다.
function initMoodWidgetDrag() {
    if (!moodWidget || !moodStatusHeader) return;

    moodStatusHeader.addEventListener('mousedown', (e) => {
        // 닫기 버튼 클릭은 드래그 시작하지 않는다.
        if (e.target && e.target.id === 'mood-status-collapse-btn') return;
        const rect = moodWidget.getBoundingClientRect();
        moodWidget.style.right = 'auto';
        moodWidget.style.left = `${rect.left}px`;
        moodWidget.style.top = `${rect.top}px`;

        moodWidgetDragState = {
            offsetX: e.clientX - rect.left,
            offsetY: e.clientY - rect.top,
        };
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!moodWidgetDragState || !moodWidget) return;
        const left = Math.max(0, e.clientX - moodWidgetDragState.offsetX);
        const top = Math.max(0, e.clientY - moodWidgetDragState.offsetY);
        moodWidget.style.left = `${left}px`;
        moodWidget.style.top = `${top}px`;
    });

    document.addEventListener('mouseup', () => {
        moodWidgetDragState = null;
    });
}

// mood 텍스트/게이지/툴팁을 한 번에 갱신한다.
function updateMoodWidget(label, valence, energy, bond, stress) {
    if (moodStatusLabel) {
        moodStatusLabel.textContent = `기분: ${formatMoodLabel(label)}`;
    }

    setMoodMeterWidth(moodMeterValence, normalizeMoodAxis(valence));
    setMoodMeterWidth(moodMeterBond, normalizeMoodAxis(bond));
    setMoodMeterWidth(moodMeterEnergy, normalizeMoodAxis(energy));
    setMoodMeterWidth(moodMeterStress, normalizeMoodAxis(stress));

    if (moodMeterValence) moodMeterValence.title = `긍정 ${Number(valence).toFixed(2)}`;
    if (moodMeterBond) moodMeterBond.title = `친밀 ${Number(bond).toFixed(2)}`;
    if (moodMeterEnergy) moodMeterEnergy.title = `활력 ${Number(energy).toFixed(2)}`;
    if (moodMeterStress) moodMeterStress.title = `긴장 ${Number(stress).toFixed(2)}`;
    if (moodStatusLabel) {
        moodStatusLabel.title = `긍정 ${Number(valence).toFixed(2)} / 친밀 ${Number(bond).toFixed(2)} / 활력 ${Number(energy).toFixed(2)} / 긴장 ${Number(stress).toFixed(2)}`;
    }
}

updateMoodWidget('calm', 0, 0, 0, 0);
setMoodPanelOpen(false);
initMoodWidgetDrag();

// Obsidian 트리 데이터를 렌더링한다.
function renderObsTree(payload) {
    if (!obsTree) return;
    obsTree.innerHTML = '';

    if (!payload || !payload.ok) {
        const msg = document.createElement('div');
        msg.className = 'obs-node obs-file';
        msg.textContent = payload && payload.error
            ? `연결 실패: ${payload.error}`
            : 'Vault 연결 정보가 없습니다.';
        obsTree.appendChild(msg);
        return;
    }

    const checked = new Set(payload.checked_files || []);
    obsCheckedPaths = checked;

    const createNode = (node, depth = 0) => {
        const row = document.createElement('div');
        row.className = `obs-node ${node.type === 'dir' ? 'obs-dir' : 'obs-file'}`;
        row.style.paddingLeft = `${depth * 12}px`;

        if (node.type === 'file') {
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = checked.has(node.path);
            cb.addEventListener('change', () => {
                if (!window.pyBridge || !window.pyBridge.set_obs_file_checked) return;
                window.pyBridge.set_obs_file_checked(node.path, cb.checked);
            });
            row.appendChild(cb);
        } else {
            const icon = document.createElement('span');
            icon.textContent = '📁';
            row.appendChild(icon);
        }

        const label = document.createElement('span');
        label.className = 'obs-path';
        label.textContent = node.path || node.name;
        row.appendChild(label);
        obsTree.appendChild(row);

        if (node.type === 'dir' && Array.isArray(node.children)) {
            node.children.forEach((child) => createNode(child, depth + 1));
        }
    };

    (payload.nodes || []).forEach((node) => createNode(node, 0));
}

function requestObsTree() {
    if (!window.pyBridge || !window.pyBridge.get_obs_tree_json) return;
    try {
        const result = window.pyBridge.get_obs_tree_json();
        const apply = (value) => {
            if (!value) return;
            try {
                const parsed = typeof value === 'string' ? JSON.parse(value) : value;
                renderObsTree(parsed);
            } catch (e) {
                renderObsTree({ ok: false, error: `트리 파싱 실패: ${e}` });
            }
        };
        if (result && typeof result.then === 'function') {
            result.then(apply).catch((e) => renderObsTree({ ok: false, error: String(e) }));
        } else {
            apply(result);
        }
    } catch (e) {
        renderObsTree({ ok: false, error: String(e) });
    }
}

/**
 * 로딩 인디케이터 표시 상태를 갱신한다.
 */
// 요청 진행 중 로딩 인디케이터를 표시/숨김 처리한다.
function showLoadingIndicator(show) {
    if (loadingIndicator) {
        loadingIndicator.style.display = show ? 'flex' : 'none';
        if (show) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
}

// 최근 assistant 메시지 DOM 참조를 재동기화한다.
function syncLastAssistantMessageRef() {
    const nodes = chatMessages.querySelectorAll('.message.assistant');
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

// 리롤/수정/수동요약 버튼의 표시 및 활성 상태를 재평가한다.
function updateRerollButtonState() {
    if (manualSummarizeButton) {
        const enabledByBridge = !!window.pyBridge && !!window.pyBridge.summarize_now;
        manualSummarizeButton.style.display = manualSummaryButtonVisibleBySetting ? 'inline-flex' : 'none';
        manualSummarizeButton.disabled = isRequestPending || !enabledByBridge;
    }
    if (summaryConfirmYesButton) {
        summaryConfirmYesButton.disabled = isRequestPending || !window.pyBridge || !window.pyBridge.summarize_now;
    }

    syncLastAssistantMessageRef();
    syncLastUserMessageRef();

    const oldButtons = chatMessages.querySelectorAll('.message-reroll-btn');
    oldButtons.forEach(btn => btn.remove());
    const oldEditButtons = chatMessages.querySelectorAll('.message-edit-btn');
    oldEditButtons.forEach(btn => btn.remove());

    if (!rerollButtonVisibleBySetting || !hasAssistantMessage || !lastAssistantMessageEl) {
        return;
    }

    const btn = document.createElement('button');
    btn.className = 'message-reroll-btn';
    btn.textContent = '⟲';
    btn.title = '최근 ENE 답변 다시 생성';
    btn.disabled = isRequestPending || !window.pyBridge || !window.pyBridge.reroll_last_response;
    btn.addEventListener('click', () => {
        if (!window.pyBridge || !window.pyBridge.reroll_last_response) return;
        if (isRequestPending) return;
        isRequestPending = true;
        showLoadingIndicator(true);
        updateRerollButtonState();
        window.pyBridge.reroll_last_response();
    });
    const bubble = lastAssistantMessageEl.querySelector('.message-bubble');
    if (!bubble) {
        return;
    }
    bubble.appendChild(btn);

    if (!recentEditButtonVisibleBySetting || !hasUserMessage || !lastUserMessageEl) {
        return;
    }
    const userBubble = lastUserMessageEl.querySelector('.message-bubble');
    if (!userBubble) {
        return;
    }
    const editBtn = document.createElement('button');
    editBtn.className = 'message-edit-btn';
    editBtn.textContent = 'Edit';
    editBtn.title = '최근 메시지 수정';
    editBtn.disabled = isRequestPending || !window.pyBridge || !window.pyBridge.edit_last_user_message;
    editBtn.addEventListener('click', () => {
        if (!window.pyBridge || !window.pyBridge.edit_last_user_message) return;
        if (isRequestPending) return;
        openInlineEdit(userBubble);
    });
    userBubble.appendChild(editBtn);
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

// 수동 요약 확인 모달을 연다.
function showSummaryConfirm() {
    if (!summaryConfirmOverlay) return;
    summaryConfirmOverlay.classList.remove('hidden');
}

// 수동 요약 확인 모달을 닫는다.
function hideSummaryConfirm() {
    if (!summaryConfirmOverlay) return;
    summaryConfirmOverlay.classList.add('hidden');
}

// 토스트 메시지를 생성해 일정 시간 후 자동 제거한다.
function showToast(message, level = 'info') {
    if (!toastContainer || !message) return;
    const toast = document.createElement('div');
    toast.className = `toast-item toast-${level}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-4px)';
        toast.style.transition = 'opacity 0.16s ease, transform 0.16s ease';
        setTimeout(() => toast.remove(), 180);
    }, 2200);
}
window.showToast = showToast;

// 인라인 수정 UI를 닫고 표시 상태를 정리한다.
function closeInlineEdit(bubble, keepText = true) {
    if (!bubble) return;
    const editor = bubble.querySelector('.inline-edit-wrap');
    const textNode = bubble.querySelector('span');
    if (editor) editor.remove();
    if (textNode && keepText) {
        textNode.style.display = '';
    }
    if (activeInlineEditBubble === bubble) {
        activeInlineEditBubble = null;
    }
}

// 최근 user 메시지 버블 안에서 인라인 수정 편집기를 연다.
function openInlineEdit(bubble) {
    if (!bubble) return;
    if (activeInlineEditBubble && activeInlineEditBubble !== bubble) {
        closeInlineEdit(activeInlineEditBubble, true);
    }
    if (bubble.querySelector('.inline-edit-wrap')) {
        return;
    }

    const textNode = bubble.querySelector('span');
    const currentText = textNode ? textNode.textContent : '';
    if (textNode) {
        textNode.style.display = 'none';
    }

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

        if (textNode) {
            textNode.textContent = trimmed;
            textNode.style.display = '';
        }
        closeInlineEdit(bubble, false);
        isRequestPending = true;
        shouldReplaceNextAssistant = true;
        showLoadingIndicator(true);
        updateRerollButtonState();
        window.pyBridge.edit_last_user_message(trimmed);
    };

    cancelBtn.addEventListener('click', () => closeInlineEdit(bubble, true));
    saveBtn.addEventListener('click', commit);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closeInlineEdit(bubble, true);
        }
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    wrap.appendChild(input);
    wrap.appendChild(actions);
    bubble.appendChild(wrap);
    activeInlineEditBubble = bubble;

    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
}

// 수동 요약 버튼 클릭 시 확인 모달을 띄운다.
function requestManualSummary() {
    if (!window.pyBridge || !window.pyBridge.summarize_now) return;
    if (isRequestPending) return;
    showSummaryConfirm();
}

// 리롤/수정 응답 수신 시 마지막 assistant 버블 내용을 교체한다.
function replaceLastAssistantMessage(text) {
    if (!lastAssistantMessageEl || !chatMessages.contains(lastAssistantMessageEl)) {
        syncLastAssistantMessageRef();
    }
    if (!lastAssistantMessageEl) {
        return false;
    }

    const bubble = lastAssistantMessageEl.querySelector('.message-bubble');
    if (!bubble) {
        return false;
    }

    bubble.innerHTML = '';
    const textSpan = document.createElement('span');
    textSpan.textContent = text;
    bubble.appendChild(textSpan);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return true;
}

/**
 * 채팅 영역에 메시지 버블을 추가한다.
 */
// 채팅 메시지(텍스트/첨부)를 DOM에 append하고 상태를 갱신한다.
function addMessage(text, role, attachments = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    if (attachments && attachments.length > 0) {
        const attachmentList = document.createElement('div');
        attachmentList.className = 'message-attachment-list';

        attachments.forEach((attachment) => {
            const normalized = typeof attachment === 'string'
                ? { category: 'image', name: '이미지', dataUrl: attachment }
                : attachment;
            const chip = document.createElement('div');
            chip.className = 'message-attachment-chip';

            if (normalized.category === 'image' && normalized.dataUrl) {
                const img = document.createElement('img');
                img.src = normalized.dataUrl;
                chip.appendChild(img);
            } else {
                const extensionBadge = document.createElement('span');
                extensionBadge.textContent = getFileExtension(normalized.name || 'file').toUpperCase() || 'FILE';
                chip.appendChild(extensionBadge);
            }

            const label = document.createElement('span');
            label.textContent = normalized.name || (normalized.category === 'image' ? '이미지' : '첨부 파일');
            chip.appendChild(label);
            attachmentList.appendChild(chip);
        });

        bubble.appendChild(attachmentList);
    }
    const textSpan = document.createElement('span');
    textSpan.textContent = text;
    bubble.appendChild(textSpan);

    messageDiv.appendChild(bubble);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    if (role === 'assistant') {
        hasAssistantMessage = true;
        lastAssistantMessageEl = messageDiv;
    } else if (role === 'user') {
        hasUserMessage = true;
        lastUserMessageEl = messageDiv;
    }
    updateRerollButtonState();
    return messageDiv;
}

// UI가 먼저 그려진 뒤 Python 브리지 호출이 실행되도록 한 프레임 뒤로 넘긴다.
function dispatchBridgeCall(task, onError) {
    const scheduleFrame = window.requestAnimationFrame
        ? window.requestAnimationFrame.bind(window)
        : (callback) => window.setTimeout(callback, 16);

    scheduleFrame(() => {
        window.setTimeout(() => {
            try {
                task();
            } catch (error) {
                if (typeof onError === 'function') {
                    onError(error);
                    return;
                }
                throw error;
            }
        }, 0);
    });
}

/**
 * 첨부 선택 창 열기.
 */
attachButton.addEventListener('click', () => {
    imageInput.click();
});

/**
 * 선택한 첨부 파일을 읽어 미리보기 목록에 추가한다.
 */
imageInput.addEventListener('change', async (e) => {
    const files = Array.from(e.target.files);

    for (const file of files) {
        const category = classifyAttachment(file);
        if (!category) {
            alert('현재는 이미지, TXT, MD, PDF, DOCX 파일만 첨부할 수 있어요.');
            continue;
        }
        if (attachedAttachments.length >= MAX_ATTACHMENT_COUNT) {
            alert('첨부 파일은 최대 5개까지 첨부할 수 있어요.');
            break;
        }

        try {
            const dataUrl = await readFileAsDataUrl(file);
            const attachment = {
                id: createAttachmentId(),
                dataUrl,
                name: file.name,
                type: file.type || inferMimeTypeFromName(file.name),
                category,
                tokenEstimate: null,
                width: 0,
                height: 0,
                status: 'pending',
                error: ''
            };

            attachedAttachments.push(attachment);
            updateAttachmentPreview();
            requestAttachmentPreviewMetadata();
        } catch (error) {
            console.error('Failed to read attachment', error);
            alert(`첨부 파일을 읽는 중 문제가 생겼어요: ${file.name}`);
        }
    }
    imageInput.value = '';
});

/**
 * 첨부 미리보기 영역을 다시 렌더링한다.
 */
// 첨부한 이미지/문서 프리뷰 목록을 다시 그린다.
function updateAttachmentPreview() {
    console.log("[Preview] Updating preview, attachments:", attachedAttachments.length);

    if (!imagePreviewContainer) {
        console.error("[Preview] imagePreviewContainer is null!");
        return;
    }

    imagePreviewContainer.innerHTML = '';

    attachedAttachments.forEach((attachment, index) => {
        console.log("[Preview] Adding attachment:", attachment.name);

        const item = document.createElement('div');
        item.className = 'attachment-preview-item';

        if (attachment.category === 'image') {
            const imgEl = document.createElement('img');
            imgEl.className = 'attachment-preview-thumb';
            imgEl.src = attachment.dataUrl;
            item.appendChild(imgEl);
        } else {
            const docEl = document.createElement('div');
            docEl.className = 'attachment-preview-doc';
            docEl.textContent = getFileExtension(attachment.name).toUpperCase() || 'FILE';
            item.appendChild(docEl);
        }

        const meta = document.createElement('div');
        meta.className = 'attachment-preview-meta';

        const nameEl = document.createElement('div');
        nameEl.className = 'attachment-preview-name';
        nameEl.textContent = attachment.name;

        const subtitleEl = document.createElement('div');
        subtitleEl.className = 'attachment-preview-subtitle';
        subtitleEl.textContent = formatAttachmentSubtitle(attachment);

        const tokenEl = document.createElement('div');
        tokenEl.className = 'attachment-preview-token';
        if (attachment.status === 'error') {
            tokenEl.classList.add('is-error');
        }
        tokenEl.textContent = formatAttachmentTokenText(attachment);

        meta.appendChild(nameEl);
        meta.appendChild(subtitleEl);
        meta.appendChild(tokenEl);

        const removeBtn = document.createElement('button');
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '✕';
        removeBtn.onclick = () => {
            attachedAttachments.splice(index, 1);
            updateAttachmentPreview();
        };

        item.appendChild(meta);
        item.appendChild(removeBtn);
        imagePreviewContainer.appendChild(item);
    });
    if (attachedAttachments.length > 0) {
        imagePreviewContainer.style.display = 'flex';
    } else {
        imagePreviewContainer.style.display = 'none';
    }

    console.log("[Preview] Preview container children:", imagePreviewContainer.children.length);
}


/**
 * 입력창/첨부 파일을 Python 브리지로 전송한다.
 */
// 입력창 텍스트/첨부를 브리지로 보내고 전송 상태를 초기화한다.
function sendMessage() {
    const message = chatInput.value.trim();

    if (!message && attachedAttachments.length === 0) return;
    const pendingAttachments = attachedAttachments.map((attachment) => ({
        id: attachment.id,
        dataUrl: attachment.dataUrl,
        name: attachment.name,
        type: attachment.type,
        category: attachment.category
    }));
    addMessage(message || '(첨부)', 'user', pendingAttachments);
    chatInput.value = '';
    autoResizeTextarea();
    if (window.pyBridge) {
        isRequestPending = true;
        shouldReplaceNextAssistant = false;
        updateRerollButtonState();
        showLoadingIndicator(true);

        dispatchBridgeCall(() => {
            if (pendingAttachments.length > 0) {
                window.pyBridge.send_to_ai_with_attachments(message, JSON.stringify(pendingAttachments));
            } else {
                window.pyBridge.send_to_ai(message);
            }
        }, (error) => {
            console.error("Python bridge dispatch failed", error);
            addMessage("연결 오류가 발생했어요.", 'assistant');
            isRequestPending = false;
            shouldReplaceNextAssistant = false;
            updateRerollButtonState();
            showLoadingIndicator(false);
        });
    } else {
        console.error("Python bridge not connected");
        addMessage("연결 오류가 발생했어요.", 'assistant');
        isRequestPending = false;
        shouldReplaceNextAssistant = false;
        updateRerollButtonState();
    }
    attachedAttachments = [];
    updateAttachmentPreview();
}

// Python 전역 PTT가 호출하는 텍스트 전송 진입점.
function submitVoiceText(text) {
    const message = (text || '').trim();
    if (!message) return;

    addMessage(message, 'user');
    if (window.pyBridge && window.pyBridge.send_to_ai) {
        isRequestPending = true;
        shouldReplaceNextAssistant = false;
        updateRerollButtonState();
        showLoadingIndicator(true);
        dispatchBridgeCall(() => {
            window.pyBridge.send_to_ai(message);
        }, (error) => {
            console.error("Python bridge dispatch failed", error);
            addMessage("연결 오류가 발생했어요.", 'assistant');
            isRequestPending = false;
            shouldReplaceNextAssistant = false;
            updateRerollButtonState();
            showLoadingIndicator(false);
        });
        return;
    }

    console.error("Python bridge not connected");
    addMessage("연결 오류가 발생했어요.", 'assistant');
    isRequestPending = false;
    shouldReplaceNextAssistant = false;
    updateRerollButtonState();
}
window.submitVoiceText = submitVoiceText;

/**
 * 입력창 높이를 내용에 맞게 자동 조절한다.
 */
// 입력창 textarea 높이를 내용에 맞게 자동 조절한다.
function autoResizeTextarea() {
    chatInput.style.height = 'auto';
    chatInput.style.height = chatInput.scrollHeight + 'px';
}
sendButton.addEventListener('click', sendMessage);
if (obsRefreshBtn) {
    obsRefreshBtn.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.refresh_obs_tree) {
            window.pyBridge.refresh_obs_tree();
        } else {
            requestObsTree();
        }
    });
}

if (moodToggleButton) {
    moodToggleButton.addEventListener('click', () => setMoodPanelOpen(!moodPanelOpen));
}

if (obsNoteButton) {
    obsNoteButton.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.toggle_obs_panel) {
            window.pyBridge.toggle_obs_panel();
        }
    });
}

if (moodCollapseButton) {
    moodCollapseButton.addEventListener('click', () => setMoodPanelOpen(false));
}

if (manualSummarizeButton) {
    manualSummarizeButton.addEventListener('click', requestManualSummary);
}

if (summaryConfirmNoButton) {
    summaryConfirmNoButton.addEventListener('click', hideSummaryConfirm);
}

if (summaryConfirmYesButton) {
    summaryConfirmYesButton.addEventListener('click', () => {
        hideSummaryConfirm();
        if (!window.pyBridge || !window.pyBridge.summarize_now) return;
        if (isRequestPending) return;
        window.pyBridge.summarize_now();
    });
}

if (summaryConfirmOverlay) {
    summaryConfirmOverlay.addEventListener('click', (e) => {
        if (e.target === summaryConfirmOverlay) {
            hideSummaryConfirm();
        }
    });
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && summaryConfirmOverlay && !summaryConfirmOverlay.classList.contains('hidden')) {
        hideSummaryConfirm();
    }
});
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
chatInput.addEventListener('input', autoResizeTextarea);

/**
 * 입력창 붙여넣기 이벤트에서 이미지 데이터를 추출해 첨부한다.
 */
chatInput.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;

    let hasImage = false;

    for (const item of items) {
        if (item.type.indexOf('image') === 0) {
            hasImage = true;
            const blob = item.getAsFile();
            if (attachedAttachments.length >= MAX_ATTACHMENT_COUNT) {
                alert('첨부 파일은 최대 5개까지 첨부할 수 있어요.');
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                const imageData = {
                    id: createAttachmentId(),
                    dataUrl: event.target.result,
                    name: "pasted_image.png",
                    type: item.type,
                    category: 'image',
                    tokenEstimate: null,
                    width: 0,
                    height: 0,
                    status: 'pending',
                    error: ''
                };

                attachedAttachments.push(imageData);
                updateAttachmentPreview();
                requestAttachmentPreviewMetadata();
            };
            reader.readAsDataURL(blob);
        }
    }
    if (hasImage) {
    }
});

updateRerollButtonState();

// ==========================================
// QWebChannel 브리지 연결
// ==========================================
if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function (channel) {
        window.pyBridge = channel.objects.bridge;
        console.log("QWebChannel bridge connected");
        updateRerollButtonState();
        if (window.pyBridge.attachment_preview_ready) {
            window.pyBridge.attachment_preview_ready.connect(function (value) {
                applyAttachmentPreviewMetadata(value);
            });
        }
        if (window.pyBridge.token_usage_ready) {
            window.pyBridge.token_usage_ready.connect(function (value) {
                showTokenUsageBubble(value);
            });
        }
        window.pyBridge.message_received.connect(function (text, emotion) {
            console.log(`Received from Python: "${text}" [${emotion}]`);
            showLoadingIndicator(false);
            isRequestPending = false;
            if (shouldReplaceNextAssistant) {
                const replaced = replaceLastAssistantMessage(text);
                if (!replaced) {
                    addMessage(text, 'assistant');
                }
            } else {
                addMessage(text, 'assistant');
            }
            shouldReplaceNextAssistant = false;
            updateRerollButtonState();
            cancelPendingPatEmotionRestore();
            baseEmotionTag = (typeof emotion === 'string' && emotion.trim()) ? emotion.trim() : 'normal';
            changeExpression(emotion);
        });
        window.pyBridge.expression_changed.connect(function (emotion) {
            console.log(`Expression changed: ${emotion}`);
            cancelPendingPatEmotionRestore();
            baseEmotionTag = (typeof emotion === 'string' && emotion.trim()) ? emotion.trim() : 'normal';
            changeExpression(emotion);
        });
        if (window.pyBridge.lip_sync_update) {
            window.pyBridge.lip_sync_update.connect(function (mouthValue) {
                setMouthOpen(mouthValue);
            });
            console.log("Lip sync signal connected");
        }

        if (window.pyBridge.reroll_state_changed) {
            window.pyBridge.reroll_state_changed.connect(function (active) {
                shouldReplaceNextAssistant = Boolean(active);
                isRequestPending = Boolean(active);
                showLoadingIndicator(Boolean(active));
                updateRerollButtonState();
            });
        }

        if (window.pyBridge.summary_notice) {
            window.pyBridge.summary_notice.connect(function (message, level) {
                const normalizedLevel = (typeof level === 'string' && level.trim()) ? level.trim().toLowerCase() : 'info';
                showToast(message, normalizedLevel);
                updateRerollButtonState();
            });
        }

        if (window.pyBridge.obs_tree_updated) {
            window.pyBridge.obs_tree_updated.connect(function (value) {
                try {
                    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
                    renderObsTree(parsed);
                } catch (e) {
                    renderObsTree({ ok: false, error: `트리 파싱 실패: ${e}` });
                }
            });
        }

        if (window.pyBridge.mood_changed) {
            window.pyBridge.mood_changed.connect(function (label, valence, energy, bond, stress) {
                updateMoodWidget(label, valence, energy, bond, stress);
            });
        }

        if (window.pyBridge.get_mood_snapshot_json) {
            const applyMoodSnapshot = (value) => {
                if (!value) return;
                let snapshot = null;
                try {
                    if (typeof value === 'string') {
                        snapshot = JSON.parse(value);
                    } else if (typeof value === 'object') {
                        snapshot = value;
                    } else {
                        snapshot = JSON.parse(String(value));
                    }
                } catch (e) {
                    console.warn("Failed to initialize mood widget:", e);
                    return;
                }

                if (!snapshot) return;
                updateMoodWidget(
                    snapshot.current_mood,
                    snapshot.valence,
                    snapshot.energy,
                    snapshot.bond,
                    snapshot.stress
                );
            };

            try {
                const snapshotResult = window.pyBridge.get_mood_snapshot_json();
                if (snapshotResult && typeof snapshotResult.then === 'function') {
                    snapshotResult
                        .then(applyMoodSnapshot)
                        .catch((e) => console.warn("Failed to initialize mood widget:", e));
                } else {
                    applyMoodSnapshot(snapshotResult);
                }
            } catch (e) {
                console.warn("Failed to initialize mood widget:", e);
            }
        }

    });
} else {
    console.warn("QWebChannel not available - running in standalone mode");
    renderObsTree({ ok: false, error: "QWebChannel 연결 없음" });
}

// ==========================================
// 립싱크 제어
// ==========================================

/**
 * Live2D 입 벌림 파라미터를 갱신한다.
 */
// 립싱크 시 ParamMouthOpenY 값을 업데이트한다.
function setMouthOpen(value) {
    const model = window.live2dModel;
    if (!model || !model.internalModel) {
        return;
    }

    try {
        const core = model.internalModel.coreModel;
        if (core && typeof core.setParameterValueById === 'function') {
            core.setParameterValueById('ParamMouthOpenY', value);
        } else if (model.internalModel.setParameterValueById) {
            model.internalModel.setParameterValueById('ParamMouthOpenY', value);
        }
    } catch (e) {
        if (!window._mouthOpenWarned) {
            console.warn("ParamMouthOpenY not available:", e);
            window._mouthOpenWarned = true;
        }
    }
}
// Python에서 직접 입 모양을 갱신할 수 있도록 전역에 노출한다.
window.setMouthOpen = setMouthOpen;

console.log("=== Chat and expression system initialized ===");
console.log("=== Lip sync system ready ===");








