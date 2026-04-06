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
        }
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
    }
};
window.eneModelConfig = window.eneModelConfig || {};
window.eneThemeConfig = window.eneThemeConfig || {};
window.eneUiStrings = window.eneUiStrings || {};
let currentModelPath = '';
let currentEmotionsBasePath = '';
let currentAvailableEmotions = new Set(['normal']);
let currentModelLoadToken = 0;
let currentModelErrorText = null;
let currentThemeAccent = DEFAULT_THEME.accentColor;
let modelCapabilityProfile = null;
let modelIdleAnimationActive = false;
window.enePerformanceConfig = window.enePerformanceConfig || {};
let performanceEngineEnabled = true;
let performanceIntensity = 1.0;
let speechReactivity = 1.0;
let idleMicroMotion = 0.35;
let motionDebugOverlayEnabled = false;
const ALLOW_MOTION_DEBUG_OVERLAY = false;

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

window.setPerformanceEngineConfig = function setPerformanceEngineConfig(config) {
    const source = config || {};
    performanceEngineEnabled = source.enabled !== false;
    performanceIntensity = Math.max(0.2, Math.min(2.5, Number(source.intensity) || 1.0));
    speechReactivity = Math.max(0.2, Math.min(2.5, Number(source.speechReactivity) || 1.0));
    idleMicroMotion = Math.max(0.0, Math.min(1.5, Number(source.idleMicroMotion) || 0.35));
    setMotionDebugOverlayEnabled(Boolean(source.showDebugOverlay));
    syncModelIdleAnimationState(window.live2dModel);
};

window.setPerformanceEngineConfig(window.enePerformanceConfig);

function setMotionDebugOverlayEnabled(enabled) {
    motionDebugOverlayEnabled = ALLOW_MOTION_DEBUG_OVERLAY && Boolean(enabled);
    if (!window.motionDebugOverlay) {
        return;
    }
    window.motionDebugOverlay.classList.toggle('hidden', !motionDebugOverlayEnabled);
}

function renderMotionDebugOverlay(snapshot) {
    if (!window.motionDebugOverlay || !motionDebugOverlayEnabled) {
        return;
    }
    const safeSnapshot = snapshot || {};
    window.motionDebugOverlay.textContent = [
        `state: ${safeSnapshot.state || 'idle'}`,
        `mood: ${safeSnapshot.mood || 'calm'}`,
        `gesture: ${safeSnapshot.gesture || '-'}`,
        `speech: ${Number(safeSnapshot.speech || 0).toFixed(2)}`,
        `headYaw: ${Number(safeSnapshot.headYaw || 0).toFixed(2)}`,
        `headPitch: ${Number(safeSnapshot.headPitch || 0).toFixed(2)}`,
    ].join('\n');
}

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
    modelCapabilityProfile = null;
    modelIdleAnimationActive = false;
    smoothedPerformanceOffsets = { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
    isHeadPatting = false;
    headPatPointerId = null;
    patRawIntensity = 0;
    patDirection = 0;
    patBlend = 0;
    patBlendMode = 'idle';
}

function syncModelIdleAnimationState(model = window.live2dModel) {
    if (!model || !model.internalModel || !model.internalModel.motionManager) {
        modelIdleAnimationActive = false;
        return;
    }

    const motionManager = model.internalModel.motionManager;
    const shouldRunIdleAnimation = idleMotionEnabled && !performanceEngineEnabled;

    if (!shouldRunIdleAnimation) {
        if (!modelIdleAnimationActive) {
            return;
        }
        try {
            if (typeof motionManager.stopAllMotions === 'function') {
                motionManager.stopAllMotions();
            } else if (typeof motionManager.stopAllMotion === 'function') {
                motionManager.stopAllMotion();
            }
            modelIdleAnimationActive = false;
            console.log("Model Idle motion stopped");
        } catch (e) {
            console.warn("Failed to stop Idle motion:", e);
        }
        return;
    }

    if (modelIdleAnimationActive) {
        return;
    }

    try {
        model.motion('Idle');
        modelIdleAnimationActive = true;
        console.log("Idle motion started");
    } catch (e) {
        console.warn("Failed to start Idle motion:", e);
    }
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

function resolveMotionSlotCandidates(slotName) {
    const candidates = {
        headYaw: ['ParamAngleX'],
        headPitch: ['ParamAngleY'],
        bodyYaw: ['ParamBodyAngleX', 'ParamBodyAngleX2'],
        bodyPitch: ['ParamBodyAngleY', 'ParamBodyAngleY2'],
        bodyRoll: ['ParamBodyAngleZ', 'ParamBodyAngleZ2'],
        breath: ['ParamBreath'],
        gazeX: ['ParamEyeBallX', 'ParamAngleX'],
        gazeY: ['ParamEyeBallY', 'ParamAngleY'],
        mouthOpen: ['ParamMouthOpenY'],
        mouthForm: ['ParamMouthForm'],
        eyeOpenL: ['ParamEyeLOpen'],
        eyeOpenR: ['ParamEyeROpen'],
    };
    return candidates[slotName] || [];
}

function readModelParameterIds(coreModel) {
    if (!coreModel) {
        return [];
    }

    const found = [];
    const pushUnique = (value) => {
        const paramId = String(value || '').trim();
        if (paramId && !found.includes(paramId)) {
            found.push(paramId);
        }
    };

    try {
        const ids = coreModel.parameters?.ids;
        if (ids && typeof ids.length === 'number') {
            for (let index = 0; index < ids.length; index += 1) {
                pushUnique(ids[index]);
            }
        }
    } catch (_) {
    }

    try {
        if (found.length === 0 && typeof coreModel.getParameterCount === 'function' && typeof coreModel.getParameterId === 'function') {
            const count = Number(coreModel.getParameterCount()) || 0;
            for (let index = 0; index < count; index += 1) {
                pushUnique(coreModel.getParameterId(index));
            }
        }
    } catch (_) {
    }

    return found;
}

function buildModelCapabilityProfile(coreModel) {
    const rawParameterIds = readModelParameterIds(coreModel);
    const available = new Set(rawParameterIds);
    const slots = {};

    [
        'headYaw',
        'headPitch',
        'bodyYaw',
        'bodyPitch',
        'bodyRoll',
        'breath',
        'gazeX',
        'gazeY',
        'mouthOpen',
        'mouthForm',
        'eyeOpenL',
        'eyeOpenR',
    ].forEach((slotName) => {
        const paramId = resolveMotionSlotCandidates(slotName).find((candidate) => available.has(candidate)) || '';
        slots[slotName] = {
            paramId,
            enabled: Boolean(paramId),
        };
    });

    return {
        rawParameterIds,
        slots,
    };
}

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
        if (model.internalModel && model.internalModel.coreModel) {
            modelCapabilityProfile = buildModelCapabilityProfile(model.internalModel.coreModel);
            console.log('Model capability profile:', modelCapabilityProfile);
        }

        console.log(`Model positioned at (${model.x}, ${model.y}) with scale ${model.scale.x}`);
        if (model.internalModel && model.internalModel.motionManager) {
            console.log("Motion manager available");
            syncModelIdleAnimationState(model);
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
let patOffsetsCurrent = { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
let patOffsetsApplied = { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
let lastNonPatTrackingState = { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
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
const IDLE_MOTION_BASE_ANGLE_Y = 1.3;
const IDLE_MOTION_BASE_BODY_X = 1.3;
const IDLE_MOTION_BASE_BODY_Y = 1.15;
const SPEECH_IDLE_BLOCK_MS = 450;
const PERFORMANCE_IDLE_RETURN_FADE_MS = 900;
const SPEAKING_GESTURE_TRIGGER_THRESHOLD = 0.32;
const SPEAKING_GESTURE_COOLDOWN_MS = 980;
const SPEAKING_MOTION_SMOOTHING_AT_60FPS = 0.18;
const SPEAKING_MOTION_GAIN = 1.45;
const BODY_MOTION_GAIN = 1.7;
const BODY_PITCH_MOTION_GAIN = 2.35;
const BODY_ROLL_MOTION_GAIN = 2.15;
const BODY_MOTION_SMOOTHING_AT_60FPS = 0.09;
const HEAD_PAT_SPEED_EMA = 0.28;
const HEAD_PAT_INTENSITY_EMA = 0.22;
const HEAD_PAT_DIRECTION_EMA = 0.35;
const HEAD_PAT_SPEED_GAIN = 0.95;
const HEAD_PAT_DECAY_AT_60FPS = 0.84;

let idleMotionSpeedHz = IDLE_MOTION_BASE_SPEED_HZ;
let idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X;
let idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y;
let idleMotionBodyX = IDLE_MOTION_BASE_BODY_X;
let idleMotionBodyY = IDLE_MOTION_BASE_BODY_Y;
let currentMouthOpenValue = 0;
const PERFORMANCE_STATES = ['idle', 'listening', 'thinking', 'preSpeech', 'speaking', 'settling'];
const PERFORMANCE_GESTURES = ['microNod', 'sideGlance', 'focusLean', 'headTilt', 'resetPose'];
let currentPerformanceState = 'idle';
let currentPerformanceMood = 'calm';
let performanceStateChangedAt = performance.now();
let lastSpeechSignalAt = 0;
let speechLeadUntilMs = 0;
let performanceSpeechIntensity = 0;
let activePerformanceGesture = null;
let lastPerformanceGestureAt = 0;
let smoothedPerformanceOffsets = { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };

function setPerformanceState(nextState) {
    const normalized = String(nextState || '').trim();
    if (!PERFORMANCE_STATES.includes(normalized) || currentPerformanceState === normalized) {
        return;
    }
    currentPerformanceState = normalized;
    performanceStateChangedAt = performance.now();
}

function setPerformanceMood(nextMood) {
    const normalized = String(nextMood || '').trim().toLowerCase();
    if (!normalized) {
        return;
    }
    currentPerformanceMood = normalized;
}

function mapTemporaryMoodToPerformanceMood(temporaryState, label) {
    const normalizedTemporary = String(temporaryState || '').trim().toLowerCase();
    const normalizedLabel = String(label || '').trim().toLowerCase();
    if (normalizedTemporary === 'playful') return 'playful';
    if (normalizedTemporary === 'focused') return 'focused';
    if (normalizedTemporary === 'guarded') return 'guarded';
    if (normalizedTemporary === 'drained') return 'tired';
    if (normalizedTemporary === 'steady') return 'calm';
    if (normalizedLabel.includes('warm') || normalizedLabel.includes('affection')) return 'warm';
    if (normalizedLabel.includes('tired')) return 'tired';
    return 'calm';
}

function receiveSpeechStateSignal(state, intensity = 0) {
    const normalized = String(state || '').trim().toLowerCase();
    const nextIntensity = clamp01(Number(intensity) || 0);
    if (normalized === 'started') {
        performanceSpeechIntensity = Math.max(performanceSpeechIntensity, nextIntensity);
        lastSpeechSignalAt = performance.now();
        speechLeadUntilMs = lastSpeechSignalAt + 120;
        setPerformanceState('preSpeech');
        return;
    }
    if (normalized === 'speaking') {
        performanceSpeechIntensity = Math.max(nextIntensity, performanceSpeechIntensity * 0.75);
        lastSpeechSignalAt = performance.now();
        if (currentPerformanceState === 'thinking') {
            speechLeadUntilMs = lastSpeechSignalAt + 120;
            setPerformanceState('preSpeech');
        }
        return;
    }
    if (normalized === 'ended') {
        performanceSpeechIntensity = 0;
        lastSpeechSignalAt = performance.now();
        setPerformanceState('settling');
    }
}

function updateSpeechFeatureState(mouthValue, nowMs) {
    if (!performanceEngineEnabled) {
        performanceSpeechIntensity = 0;
        if (!isRequestPending) {
            setPerformanceState('idle');
        }
        return;
    }
    const intensity = clamp01(Number(mouthValue) || 0);
    performanceSpeechIntensity += ((intensity * speechReactivity) - performanceSpeechIntensity) * 0.32;

    if (intensity > 0.08) {
        lastSpeechSignalAt = nowMs;
        if (currentPerformanceState === 'thinking' || currentPerformanceState === 'listening' || currentPerformanceState === 'idle') {
            speechLeadUntilMs = nowMs + 90;
            setPerformanceState('preSpeech');
        }
    }

    if (currentPerformanceState === 'preSpeech' && nowMs >= speechLeadUntilMs) {
        setPerformanceState('speaking');
    } else if (currentPerformanceState === 'speaking' && (nowMs - lastSpeechSignalAt) > 170) {
        setPerformanceState('settling');
    } else if (currentPerformanceState === 'settling' && (nowMs - lastSpeechSignalAt) > 650) {
        setPerformanceState(isRequestPending ? 'thinking' : 'listening');
    } else if (!isRequestPending && currentPerformanceState === 'listening' && performanceSpeechIntensity < 0.01 && (nowMs - performanceStateChangedAt) > 2500) {
        setPerformanceState('idle');
    }
}

function schedulePerformanceGesture(type, payload = {}) {
    if (!PERFORMANCE_GESTURES.includes(type)) {
        return;
    }
    activePerformanceGesture = {
        type,
        payload,
        startedAt: performance.now(),
        durationMs: Math.max(140, Math.min(900, Number(payload.durationMs) || 320)),
    };
    lastPerformanceGestureAt = activePerformanceGesture.startedAt;
}

function maybeScheduleThinkingGesture(nowMs) {
    if (!performanceEngineEnabled) {
        return;
    }
    if (activePerformanceGesture || currentPerformanceState !== 'thinking') {
        return;
    }
    if ((nowMs - lastPerformanceGestureAt) < 1800) {
        return;
    }
    if (Math.random() < 0.009) {
        schedulePerformanceGesture(Math.random() < 0.6 ? 'sideGlance' : 'headTilt', { durationMs: 260 });
    }
}

function maybeScheduleSpeechPeakGesture(nowMs) {
    if (!performanceEngineEnabled) {
        return;
    }
    if (activePerformanceGesture || currentPerformanceState !== 'speaking') {
        return;
    }
    if ((nowMs - lastPerformanceGestureAt) < SPEAKING_GESTURE_COOLDOWN_MS) {
        return;
    }
    if (performanceSpeechIntensity >= SPEAKING_GESTURE_TRIGGER_THRESHOLD) {
        schedulePerformanceGesture(Math.random() < 0.7 ? 'microNod' : 'focusLean', { durationMs: 240 });
    }
}

function getPerformanceSettleProgress(nowMs) {
    if (currentPerformanceState !== 'settling') {
        return 1;
    }
    return clamp01((nowMs - performanceStateChangedAt) / PERFORMANCE_IDLE_RETURN_FADE_MS);
}

function buildPerformanceStateOffsets(nowMs) {
    if (!performanceEngineEnabled) {
        return { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
    }
    const moodAngleBias = currentPerformanceMood === 'playful' ? 0.9 : currentPerformanceMood === 'focused' ? 0.2 : 0;
    const moodPitchBias = currentPerformanceMood === 'tired' ? -1.0 : currentPerformanceMood === 'warm' ? 0.5 : 0;
    const stateWave = Math.sin(nowMs * 0.0024);
    const subtleScale = idleMicroMotion * performanceIntensity;
    const expressiveScale = performanceIntensity;

    if (currentPerformanceState === 'thinking') {
        return {
            angleX: (stateWave * 0.6 + moodAngleBias) * subtleScale,
            angleY: (1.0 + (Math.sin(nowMs * 0.0017) * 0.5)) * subtleScale,
            bodyX: (stateWave * 0.35) * subtleScale,
            bodyY: (0.34 + Math.sin(nowMs * 0.0012 + 0.4) * 0.16) * subtleScale,
            bodyZ: ((stateWave * 0.42) + (Math.sin(nowMs * 0.0016 + 0.3) * 0.12)) * subtleScale,
            breath: clamp01(0.16 + subtleScale * 0.3),
            eyeY: (-0.04 + moodPitchBias * 0.01) * subtleScale,
        };
    }
    if (currentPerformanceState === 'preSpeech') {
        return {
            angleX: (moodAngleBias * 0.4) * expressiveScale,
            angleY: (0.7 + moodPitchBias * 0.1) * expressiveScale,
            bodyX: 0.3 * expressiveScale,
            bodyY: 0.55 * expressiveScale,
            bodyZ: moodAngleBias * 0.22 * expressiveScale,
            breath: clamp01(0.14 + expressiveScale * 0.1),
            eyeY: -0.02 * expressiveScale,
        };
    }
    if (currentPerformanceState === 'speaking') {
        const speechPulse = Math.max(performanceSpeechIntensity, clamp01(currentMouthOpenValue * 1.35));
        const speechYawWave = (Math.sin(nowMs * 0.0042) * 1.25) + (Math.sin(nowMs * 0.0081 + 0.6) * 0.34);
        const speechPitchWave = 0.38 + (Math.sin(nowMs * 0.0071 + 0.25) * 0.78);
        return {
            angleX: (((speechYawWave * (1.15 + speechPulse * 1.2)) + (moodAngleBias * 0.55)) * expressiveScale) * SPEAKING_MOTION_GAIN,
            angleY: ((((speechPitchWave * (0.45 + speechPulse * 0.9)) - 0.18) + (moodPitchBias * 0.35)) * expressiveScale) * 1.18,
            bodyX: clampSymmetric(((speechYawWave * (0.2 + speechPulse * 0.36)) * expressiveScale) * BODY_MOTION_GAIN, 6.4),
            bodyY: clampSymmetric(((((speechPitchWave * (0.4 + speechPulse * 0.72)) - 0.08) + (moodPitchBias * 0.12)) * expressiveScale) * BODY_PITCH_MOTION_GAIN, 8.8),
            bodyZ: clampSymmetric(((((speechYawWave * (0.34 + speechPulse * 0.5)) + (speechPitchWave * 0.16)) + (moodAngleBias * 0.24)) * expressiveScale) * BODY_ROLL_MOTION_GAIN, 7.8),
            breath: clamp01(0.16 + speechPulse * 0.3),
            eyeY: (-0.01 - speechPulse * 0.028) * expressiveScale,
        };
    }
    if (currentPerformanceState === 'settling') {
        const settleFade = 1 - getPerformanceSettleProgress(nowMs);
        return {
            angleX: (Math.sin(nowMs * 0.0028) * 0.16) * subtleScale * settleFade,
            angleY: (moodPitchBias * 0.28) * subtleScale * settleFade,
            bodyX: (Math.sin(nowMs * 0.0019 + 0.4) * 0.14 + 0.06) * subtleScale * settleFade,
            bodyY: (Math.sin(nowMs * 0.0015 + 0.8) * 0.12 + 0.08) * subtleScale * settleFade,
            bodyZ: (Math.sin(nowMs * 0.0021 + 0.3) * 0.1) * subtleScale * settleFade,
            breath: clamp01((0.12 + subtleScale * 0.14) * settleFade),
            eyeY: 0,
        };
    }
    if (currentPerformanceState === 'listening') {
        return {
            angleX: (moodAngleBias * 0.25) * subtleScale,
            angleY: (moodPitchBias * 0.35) * subtleScale,
            bodyX: 0,
            bodyY: subtleScale * 0.22,
            bodyZ: (moodAngleBias * 0.14 + Math.sin(nowMs * 0.0014 + 0.6) * 0.1) * subtleScale,
            breath: clamp01(0.12 + subtleScale * 0.2),
            eyeY: 0,
        };
    }
    return {
        angleX: (moodAngleBias * 0.15) * subtleScale,
        angleY: (moodPitchBias * 0.2) * subtleScale,
        bodyX: 0,
        bodyY: subtleScale * 0.16,
        bodyZ: Math.sin(nowMs * 0.0012 + 0.1) * subtleScale * 0.14,
        breath: clamp01(0.1 + subtleScale * 0.16),
        eyeY: 0,
    };
}

function buildPerformanceGestureOffsets(nowMs) {
    if (!performanceEngineEnabled) {
        return { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
    }
    if (!activePerformanceGesture) {
        return { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
    }

    const elapsedMs = nowMs - activePerformanceGesture.startedAt;
    const progress = clamp01(elapsedMs / Math.max(1, activePerformanceGesture.durationMs));
    const envelope = Math.sin(progress * Math.PI);
    let offsets = { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };

    if (activePerformanceGesture.type === 'microNod') {
        offsets = { angleX: 0, angleY: envelope * 1.35, bodyX: envelope * 0.16, bodyY: envelope * 0.24, bodyZ: 0, breath: envelope * 0.03, eyeY: 0 };
    } else if (activePerformanceGesture.type === 'sideGlance') {
        offsets = { angleX: envelope * 1.25, angleY: 0.18, bodyX: envelope * 0.18, bodyY: 0, bodyZ: envelope * 0.2, breath: 0, eyeY: -0.03 };
    } else if (activePerformanceGesture.type === 'focusLean') {
        offsets = { angleX: envelope * 0.4, angleY: envelope * 0.55, bodyX: envelope * 0.22, bodyY: envelope * 0.34, bodyZ: envelope * 0.08, breath: envelope * 0.05, eyeY: -0.015 };
    } else if (activePerformanceGesture.type === 'headTilt') {
        offsets = { angleX: envelope * 0.9, angleY: 0.32, bodyX: envelope * 0.12, bodyY: 0, bodyZ: envelope * 0.22, breath: 0, eyeY: 0 };
    } else if (activePerformanceGesture.type === 'resetPose') {
        offsets = { angleX: envelope * -0.45, angleY: envelope * -0.22, bodyX: envelope * -0.08, bodyY: envelope * -0.12, bodyZ: envelope * -0.1, breath: envelope * -0.04, eyeY: 0 };
    }

    offsets = {
        angleX: offsets.angleX * performanceIntensity,
        angleY: offsets.angleY * performanceIntensity,
        bodyX: offsets.bodyX * performanceIntensity,
        bodyY: offsets.bodyY * performanceIntensity,
        bodyZ: offsets.bodyZ * performanceIntensity,
        breath: offsets.breath * performanceIntensity,
        eyeY: offsets.eyeY * performanceIntensity,
    };

    if (progress >= 0.999) {
        activePerformanceGesture = null;
    }
    return offsets;
}

function smoothPerformanceOffsets(targetOffsets, dtMs, nowMs) {
    const target = targetOffsets || { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
    const frameScale = dtMs > 0 ? dtMs / (1000 / 60) : 1;
    let smoothingAt60Fps = currentPerformanceState === 'speaking' ? SPEAKING_MOTION_SMOOTHING_AT_60FPS : 0.08;
    const bodySmoothingAt60Fps = currentPerformanceState === 'speaking' ? BODY_MOTION_SMOOTHING_AT_60FPS : 0.06;
    if (currentPerformanceState === 'settling') {
        const settleProgress = getPerformanceSettleProgress(nowMs);
        smoothingAt60Fps = lerp(0.07, 0.14, settleProgress);
    }
    const smoothing = 1 - Math.pow(1 - smoothingAt60Fps, frameScale);
    const bodySmoothing = 1 - Math.pow(1 - bodySmoothingAt60Fps, frameScale);
    smoothedPerformanceOffsets = {
        angleX: lerp(smoothedPerformanceOffsets.angleX || 0, target.angleX || 0, smoothing),
        angleY: lerp(smoothedPerformanceOffsets.angleY || 0, target.angleY || 0, smoothing),
        bodyX: lerp(smoothedPerformanceOffsets.bodyX || 0, target.bodyX || 0, bodySmoothing),
        bodyY: lerp(smoothedPerformanceOffsets.bodyY || 0, target.bodyY || 0, bodySmoothing),
        bodyZ: lerp(smoothedPerformanceOffsets.bodyZ || 0, target.bodyZ || 0, bodySmoothing),
        breath: lerp(smoothedPerformanceOffsets.breath || 0, target.breath || 0, bodySmoothing),
        eyeY: lerp(smoothedPerformanceOffsets.eyeY || 0, target.eyeY || 0, smoothing),
    };
    return { ...smoothedPerformanceOffsets };
}

function mergeMotionOffsets(...offsetsList) {
    return offsetsList.reduce((merged, offsets) => {
        const source = offsets || {};
        return {
            angleX: (merged.angleX || 0) + (source.angleX || 0),
            angleY: (merged.angleY || 0) + (source.angleY || 0),
            bodyX: (merged.bodyX || 0) + (source.bodyX || 0),
            bodyY: (merged.bodyY || 0) + (source.bodyY || 0),
            bodyZ: (merged.bodyZ || 0) + (source.bodyZ || 0),
            breath: (merged.breath || 0) + (source.breath || 0),
            eyeY: (merged.eyeY || 0) + (source.eyeY || 0),
        };
    }, { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 });
}

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
        bodyAngleY: hasParam('ParamBodyAngleY'),
        bodyAngleZ: hasParam('ParamBodyAngleZ'),
        breath: hasParam('ParamBreath'),
        eyeBallX: hasParam('ParamEyeBallX'),
        eyeBallY: hasParam('ParamEyeBallY'),
    };

    return trackingParamSupport;
}

// 정규화된 시선 입력값을 실제 Live2D 파라미터 값으로 변환해 적용한다.
function getMotionSlotParamId(slotName) {
    const profileParamId = modelCapabilityProfile?.slots?.[slotName]?.paramId;
    if (profileParamId) {
        return profileParamId;
    }
    return resolveMotionSlotCandidates(slotName)[0] || '';
}

function getExpressionBaseParamValue(paramId, fallbackValue = 0) {
    if (!paramId || !expressionBaseParams.has(paramId)) {
        return fallbackValue;
    }
    const value = Number(expressionBaseParams.get(paramId));
    return Number.isFinite(value) ? value : fallbackValue;
}

function addMixedValue(target, paramId, delta) {
    if (!paramId || !Number.isFinite(delta)) {
        return;
    }
    target.set(paramId, (target.get(paramId) || 0) + delta);
}

function setMixedValue(target, paramId, value) {
    if (!paramId || !Number.isFinite(value)) {
        return;
    }
    target.set(paramId, value);
}

function buildTrackingParameterValues(coreModel, x, y, idleOffsets = null) {
    const support = detectTrackingParams(coreModel);
    const idleAngleX = idleOffsets ? idleOffsets.angleX : 0;
    const idleAngleY = idleOffsets ? idleOffsets.angleY : 0;
    const idleBodyX = idleOffsets ? idleOffsets.bodyX : 0;
    const idleBodyY = idleOffsets ? idleOffsets.bodyY : 0;
    const idleBodyZ = idleOffsets ? idleOffsets.bodyZ : 0;
    const idleBreath = idleOffsets && Number.isFinite(idleOffsets.breath) ? idleOffsets.breath : 0;
    const idleEyeY = idleOffsets && Number.isFinite(idleOffsets.eyeY) ? idleOffsets.eyeY : 0;
    const values = new Map();

    if (support.angleX) addMixedValue(values, getMotionSlotParamId('headYaw') || 'ParamAngleX', (x * 15) + idleAngleX);
    if (support.angleY) addMixedValue(values, getMotionSlotParamId('headPitch') || 'ParamAngleY', (-y * 15) + idleAngleY);
    if (support.bodyAngleX) addMixedValue(values, getMotionSlotParamId('bodyYaw') || 'ParamBodyAngleX', (x * 5) + idleBodyX);
    if (support.bodyAngleY) addMixedValue(values, getMotionSlotParamId('bodyPitch') || 'ParamBodyAngleY', (-y * 3.2) + idleBodyY);
    if (support.bodyAngleZ) addMixedValue(values, getMotionSlotParamId('bodyRoll') || 'ParamBodyAngleZ', (x * 2.4) + idleBodyZ);
    if (support.breath) addMixedValue(values, getMotionSlotParamId('breath') || 'ParamBreath', idleBreath);
    if (support.eyeBallX) addMixedValue(values, getMotionSlotParamId('gazeX') || 'ParamEyeBallX', x * 0.8);
    if (support.eyeBallY) addMixedValue(values, getMotionSlotParamId('gazeY') || 'ParamEyeBallY', (-y * 0.8) + idleEyeY);

    return values;
}

function blendEyeOpenValue(expressionValue, blinkFactor, stateFactor) {
    return clamp01(expressionValue * blinkFactor * stateFactor);
}

function buildHeadPatEyeOverrides(coreModel, blend) {
    const support = detectHeadPatEyeParams(coreModel);
    const closeAmount = clamp01(blend);
    const openFactor = 1 - closeAmount;
    const values = new Map();

    const leftOpenParamId = support.eyeLOpen ? (getMotionSlotParamId('eyeOpenL') || 'ParamEyeLOpen') : '';
    const rightOpenParamId = support.eyeROpen ? (getMotionSlotParamId('eyeOpenR') || 'ParamEyeROpen') : '';

    if (leftOpenParamId) {
        setMixedValue(values, leftOpenParamId, blendEyeOpenValue(getExpressionBaseParamValue(leftOpenParamId, 1), 1, openFactor));
    }
    if (rightOpenParamId) {
        setMixedValue(values, rightOpenParamId, blendEyeOpenValue(getExpressionBaseParamValue(rightOpenParamId, 1), 1, openFactor));
    }
    if (support.eyeLSquint) {
        setMixedValue(values, 'ParamEyeLSquint', closeAmount);
    }
    if (support.eyeRSquint) {
        setMixedValue(values, 'ParamEyeRSquint', closeAmount);
    }

    return values;
}

function buildMixedParameterFrame(coreModel, trackingX = 0, trackingY = 0, idleOffsets = null, headPatBlend = 0) {
    const values = new Map();
    expressionBaseParams.forEach((value, paramId) => {
        setMixedValue(values, paramId, Number(value) || 0);
    });

    buildTrackingParameterValues(coreModel, trackingX, trackingY, idleOffsets).forEach((value, paramId) => {
        addMixedValue(values, paramId, value);
    });

    if (headPatBlend > 0.001) {
        buildHeadPatEyeOverrides(coreModel, headPatBlend).forEach((value, paramId) => {
            setMixedValue(values, paramId, value);
        });
    }

    const mouthOpenParamId = getMotionSlotParamId('mouthOpen') || 'ParamMouthOpenY';
    if (mouthOpenParamId) {
        setMixedValue(values, mouthOpenParamId, clamp01(currentMouthOpenValue));
    }

    return {
        values,
    };
}

function applyMixedParameterFrame(coreModel, frame) {
    if (!coreModel || !frame || !(frame.values instanceof Map)) {
        return;
    }
    frame.values.forEach((value, paramId) => {
        try {
            coreModel.setParameterValueById(paramId, value);
        } catch (_) {
        }
    });
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
    applyMixedParameterFrame(coreModel, { values: buildHeadPatEyeOverrides(coreModel, blend) });
}

// 립싱크 직후 구간인지 판정해 idle 모션 간섭을 줄인다.
function isSpeakingNow(nowMs) {
    return (nowMs - lastSpeechAt) < SPEECH_IDLE_BLOCK_MS;
}

function getIdleMotionBlendFactor(nowMs) {
    if (!performanceEngineEnabled) {
        return 1;
    }
    if (currentPerformanceState === 'preSpeech') {
        return 0.1;
    }
    if (currentPerformanceState === 'speaking') {
        if (isSpeakingNow(nowMs)) {
            return 0.06;
        }
        return 0.12;
    }
    if (currentPerformanceState === 'settling') {
        const settleProgress = getPerformanceSettleProgress(nowMs);
        return lerp(0.08, 0.34, settleProgress);
    }
    if (currentPerformanceState === 'thinking') {
        return 0.24;
    }
    if (currentPerformanceState === 'listening') {
        return 0.32;
    }
    return 0.42;
}

// idle 모션 전체 활성/비활성 토글.
window.setIdleMotionEnabled = function (enabled) {
    idleMotionEnabled = Boolean(enabled);
    if (!idleMotionEnabled) {
        idleMotionPhase = 0;
    }
    syncModelIdleAnimationState(window.live2dModel);
    console.log("Idle motion:", idleMotionEnabled ? "enabled" : "disabled");
};

// idle 모션 강도/속도 설정을 JS 쪽 상태값으로 반영한다.
window.setIdleMotionConfig = function (strength, speed) {
    const s = Number.isFinite(strength) ? Math.min(2.0, Math.max(0.2, Number(strength))) : 1.0;
    const v = Number.isFinite(speed) ? Math.min(2.0, Math.max(0.5, Number(speed))) : 1.0;

    idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X * s;
    idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y * s;
    idleMotionBodyX = IDLE_MOTION_BASE_BODY_X * s;
    idleMotionBodyY = IDLE_MOTION_BASE_BODY_Y * s;
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

function clampSymmetric(value, limit) {
    const safeLimit = Math.max(0, Number(limit) || 0);
    return Math.max(-safeLimit, Math.min(safeLimit, Number(value) || 0));
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
    smoothedPerformanceOffsets = { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };

    const coreModel = getTrackingCoreModel();
    if (!coreModel) return;

    try {
        const frame = buildMixedParameterFrame(coreModel, 0, 0, { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 }, 0);
        applyMixedParameterFrame(coreModel, frame);
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
    updateSpeechFeatureState(currentMouthOpenValue, nowMs);
    maybeScheduleThinkingGesture(nowMs);
    maybeScheduleSpeechPeakGesture(nowMs);
    updateHeadPatState(dtMs);
    const hasHeadPatEffect = headPatEnabled && patBlend > 0.001;
    const idleBlendFactor = getIdleMotionBlendFactor(nowMs);

    let idleOffsets = null;
    if (!hasHeadPatEffect && idleMotionEnabled && idleBlendFactor > 0.001 && !isSpeakingNow(nowMs)) {
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
            const bodyYDynamic =
                (Math.sin(idleMotionPhase * 0.92 + 0.9) * idleMotionBodyY * 2.2) +
                (Math.sin(idleMotionPhase * 1.85 + 0.1) * idleMotionBodyY * 0.7);

            idleOffsets = {
                angleX: Math.max(-18, Math.min(18, angleXDynamic * idleBlendFactor)),
                angleY: Math.max(-15, Math.min(15, angleYDynamic * idleBlendFactor)),
                bodyX: Math.max(-10, Math.min(10, bodyXDynamic * idleBlendFactor)),
                bodyY: Math.max(-7.5, Math.min(7.5, bodyYDynamic * idleBlendFactor)),
                bodyZ: Math.max(-4.5, Math.min(4.5, Math.sin(idleMotionPhase * 0.85 + 0.5) * idleBlendFactor * 2.4)),
                breath: clamp01(idleBlendFactor * 0.08),
            };
        } else {
            idleOffsets = {
                angleX: Math.sin(idleMotionPhase) * idleMotionAngleX * idleBlendFactor,
                angleY: Math.sin(idleMotionPhase * 0.7 + 1.2) * idleMotionAngleY * idleBlendFactor,
                bodyX: Math.sin(idleMotionPhase * 0.5 + 0.6) * idleMotionBodyX * idleBlendFactor,
                bodyY: Math.sin(idleMotionPhase * 0.62 + 0.9) * idleMotionBodyY * idleBlendFactor,
                bodyZ: Math.sin(idleMotionPhase * 0.4 + 0.2) * idleBlendFactor * 1.6,
                breath: clamp01(idleBlendFactor * 0.06),
            };
        }
    }

    const targetPerformanceOffsets = mergeMotionOffsets(
        idleOffsets || { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 },
        buildPerformanceStateOffsets(nowMs),
        buildPerformanceGestureOffsets(nowMs)
    );
    const smoothedPerformanceOffsets = smoothPerformanceOffsets(targetPerformanceOffsets, dtMs, nowMs);
    const baseTrackingOffsets = smoothedPerformanceOffsets || { angleX: 0, angleY: 0, bodyX: 0, bodyY: 0, bodyZ: 0, breath: 0, eyeY: 0 };
    if (!hasHeadPatEffect) {
        lastNonPatTrackingState = { ...baseTrackingOffsets };
    }
    patOffsetsCurrent = buildHeadPatOffsets(nowMs);
    patOffsetsApplied = {
        angleX: lerp(lastNonPatTrackingState.angleX, patOffsetsCurrent.angleX, patBlend),
        angleY: lerp(lastNonPatTrackingState.angleY, patOffsetsCurrent.angleY, patBlend),
        bodyX: lerp(lastNonPatTrackingState.bodyX, patOffsetsCurrent.bodyX, patBlend),
        bodyY: lerp(lastNonPatTrackingState.bodyY || 0, patOffsetsCurrent.bodyY || 0, patBlend),
        bodyZ: lerp(lastNonPatTrackingState.bodyZ || 0, patOffsetsCurrent.bodyZ || 0, patBlend),
        breath: lerp(lastNonPatTrackingState.breath || 0, patOffsetsCurrent.breath || 0, patBlend),
        eyeY: lerp(lastNonPatTrackingState.eyeY, patOffsetsCurrent.eyeY, patBlend),
    };

    try {
        const frame = hasHeadPatEffect
            ? buildMixedParameterFrame(coreModel, 0, 0, patOffsetsApplied, patBlend)
            : buildMixedParameterFrame(coreModel, currentMouseX, currentMouseY, smoothedPerformanceOffsets, 0);
        applyMixedParameterFrame(coreModel, frame);
        renderMotionDebugOverlay({
            state: currentPerformanceState,
            mood: currentPerformanceMood,
            gesture: activePerformanceGesture ? activePerformanceGesture.type : '',
            speech: performanceSpeechIntensity,
            headYaw: hasHeadPatEffect ? patOffsetsApplied.angleX : smoothedPerformanceOffsets.angleX,
            headPitch: hasHeadPatEffect ? patOffsetsApplied.angleY : smoothedPerformanceOffsets.angleY,
        });
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
let expressionBaseParams = new Map();

function setExpressionBaseParams(entries) {
    expressionBaseParams = new Map(entries);
}

function clearExpressionBaseParams() {
    expressionBaseParams = new Map();
}

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
            clearExpressionBaseParams();
            if (currentExpressionAnimation) {
                cancelAnimationFrame(currentExpressionAnimation);
            }
            if (model.internalModel && model.internalModel.coreModel) {
                const startValues = {};
                const targetValues = {};

                previousExpressionParams.forEach(paramId => {
                    startValues[paramId] = getExpressionBaseParamValue(paramId, 0);
                    targetValues[paramId] = 0;
                });
                const duration = 300;
                const startTime = Date.now();

                function animate() {
                    const elapsed = Date.now() - startTime;
                    const progress = Math.min(elapsed / duration, 1.0);
                    const eased = 1 - Math.pow(1 - progress, 3);
                    const animatedEntries = [];

                    Object.keys(targetValues).forEach(paramId => {
                        const start = startValues[paramId] || 0;
                        const target = targetValues[paramId];
                        const value = start + (target - start) * eased;
                        animatedEntries.push([paramId, value]);
                    });
                    setExpressionBaseParams(animatedEntries);

                    if (progress < 1.0) {
                        currentExpressionAnimation = requestAnimationFrame(animate);
                    } else {
                        currentExpressionAnimation = null;
                        previousExpressionParams = [];
                        clearExpressionBaseParams();
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
                startValues[paramId] = getExpressionBaseParamValue(paramId, 0);
                targetValues[paramId] = 0;
            });
            const newExpressionParams = [];
            expressionData.Parameters.forEach(param => {
                startValues[param.Id] = getExpressionBaseParamValue(param.Id, 0);
                targetValues[param.Id] = param.Value;
                newExpressionParams.push(param.Id);
            });
            previousExpressionParams = newExpressionParams;
            const duration = 500;
            const startTime = Date.now();
            function animate() {
                const elapsed = Date.now() - startTime;
                const progress = Math.min(elapsed / duration, 1.0);
                const eased = 1 - Math.pow(1 - progress, 3);
                const animatedEntries = [];
                Object.keys(targetValues).forEach(paramId => {
                    const start = startValues[paramId] || 0;
                    const target = targetValues[paramId];
                    const value = start + (target - start) * eased;
                    animatedEntries.push([paramId, value]);
                });
                setExpressionBaseParams(animatedEntries);
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
const toastContainer = document.getElementById('toast-container');
const motionDebugOverlay = document.getElementById('motion-debug-overlay');
window.motionDebugOverlay = motionDebugOverlay;
setMotionDebugOverlayEnabled(motionDebugOverlayEnabled);
const moodToggleButton = document.getElementById('mood-toggle-floating-btn');
const obsNoteButton = document.getElementById('obs-note-floating-btn');
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
const tokenUsageBubble = document.getElementById('token-usage-bubble');
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
let obsidianNoteButtonVisibleBySetting = true;
let tokenUsageBubbleVisibleBySetting = false;
let hasAssistantMessage = false;
let hasUserMessage = false;
let isRequestPending = false;
let shouldReplaceNextAssistant = false;
let lastAssistantMessageEl = null;
let lastUserMessageEl = null;
let moodPanelOpen = false;
let activeInlineEditMessageEl = null;
let obsCheckedPaths = new Set();
let moodWidgetDragState = null;
let tokenUsageBubbleTimer = null;
let currentMoodSnapshot = { label: 'calm', temporaryState: 'steady', valence: 0, energy: 0, bond: 0, stress: 0 };
let currentUiStrings = null;
let typingEffectEnabled = true;
let typingEffectSpeed = 'normal';
let messageSplitEnabled = false;

function createLucideIcon(name) {
    const icons = {
        paperclip: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551" /></svg>',
        pencil: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" /><path d="m15 5 4 4" /></svg>',
        'rotate-ccw': '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /></svg>',
        settings: '<svg class="lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" /><circle cx="12" cy="12" r="3" /></svg>'
    };
    return icons[name] || '';
}

let floatingActionsOpen = false;

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

function mergeUiStrings(config) {
    const source = config || {};
    const input = source.input || {};
    const actions = source.actions || {};
    const mood = source.mood || {};
    const moodAxis = mood.axis || {};
    const moodStates = mood.states || {};
    const moodTemporaryStates = mood.temporaryStates || {};
    const summaryConfirm = source.summaryConfirm || {};

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
            }
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
    if (moodMeterNameValence) moodMeterNameValence.textContent = currentUiStrings.mood.axis.valence;
    if (moodMeterNameBond) moodMeterNameBond.textContent = currentUiStrings.mood.axis.bond;
    if (moodMeterNameEnergy) moodMeterNameEnergy.textContent = currentUiStrings.mood.axis.energy;
    if (moodMeterNameStress) moodMeterNameStress.textContent = currentUiStrings.mood.axis.stress;
    if (moodCollapseButton) moodCollapseButton.title = currentUiStrings.mood.collapse;
    if (summaryConfirmTitle) summaryConfirmTitle.textContent = currentUiStrings.summaryConfirm.title;
    if (summaryConfirmBody) summaryConfirmBody.textContent = currentUiStrings.summaryConfirm.body;
    if (summaryConfirmNoButton) summaryConfirmNoButton.textContent = currentUiStrings.summaryConfirm.no;
    if (summaryConfirmYesButton) summaryConfirmYesButton.textContent = currentUiStrings.summaryConfirm.yes;
}

window.applyENEUiStrings = function applyENEUiStrings(config) {
    currentUiStrings = mergeUiStrings(config);
    window.eneUiStrings = currentUiStrings;
    applyUiStringsToStaticNodes();
    updateMoodWidget(
        currentMoodSnapshot.label,
        currentMoodSnapshot.temporaryState,
        currentMoodSnapshot.valence,
        currentMoodSnapshot.energy,
        currentMoodSnapshot.bond,
        currentMoodSnapshot.stress
    );
};

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
    const map = (currentUiStrings && currentUiStrings.mood && currentUiStrings.mood.states)
        ? currentUiStrings.mood.states
        : DEFAULT_UI_STRINGS.mood.states;
    return map[label] || label || map.unknown || DEFAULT_UI_STRINGS.mood.states.unknown;
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
function updateMoodWidget(label, temporaryState, valence, energy, bond, stress) {
    currentMoodSnapshot = {
        label: label,
        temporaryState: temporaryState || 'steady',
        valence: valence,
        energy: energy,
        bond: bond,
        stress: stress
    };

    if (moodStatusLabel) {
        moodStatusLabel.textContent = formatMoodStatusText(label, temporaryState);
    }

    setMoodMeterWidth(moodMeterValence, normalizeMoodAxis(valence));
    setMoodMeterWidth(moodMeterBond, normalizeMoodAxis(bond));
    setMoodMeterWidth(moodMeterEnergy, normalizeMoodAxis(energy));
    setMoodMeterWidth(moodMeterStress, normalizeMoodAxis(stress));

    const axis = (currentUiStrings && currentUiStrings.mood && currentUiStrings.mood.axis)
        ? currentUiStrings.mood.axis
        : DEFAULT_UI_STRINGS.mood.axis;
    if (moodMeterValence) moodMeterValence.title = `${axis.valence} ${Number(valence).toFixed(2)}`;
    if (moodMeterBond) moodMeterBond.title = `${axis.bond} ${Number(bond).toFixed(2)}`;
    if (moodMeterEnergy) moodMeterEnergy.title = `${axis.energy} ${Number(energy).toFixed(2)}`;
    if (moodMeterStress) moodMeterStress.title = `${axis.stress} ${Number(stress).toFixed(2)}`;
    if (moodStatusLabel) {
        moodStatusLabel.title = `${axis.valence} ${Number(valence).toFixed(2)} / ${axis.bond} ${Number(bond).toFixed(2)} / ${axis.energy} ${Number(energy).toFixed(2)} / ${axis.stress} ${Number(stress).toFixed(2)}`;
    }
}

window.applyENEUiStrings(window.eneUiStrings);
updateMoodWidget('calm', 'steady', 0, 0, 0, 0);
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
        if (show) {
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
    btn.type = 'button';
    btn.innerHTML = createLucideIcon('rotate-ccw');
    btn.title = '최근 ENE 답변 다시 생성';
    btn.setAttribute('aria-label', '최근 ENE 답변 다시 생성');
    btn.disabled = isRequestPending || !window.pyBridge || !window.pyBridge.reroll_last_response;
    btn.addEventListener('click', () => {
        if (!window.pyBridge || !window.pyBridge.reroll_last_response) return;
        if (isRequestPending) return;
        isRequestPending = true;
        showLoadingIndicator(true);
        updateRerollButtonState();
        window.pyBridge.reroll_last_response();
    });
    const assistantRail = ensureMessageMetaRail(
        lastAssistantMessageEl,
        'assistant',
        lastAssistantMessageEl.dataset.messageTimestamp,
    );
    if (!assistantRail) {
        return;
    }
    assistantRail.appendChild(btn);

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

function normalizeLogicalMessageText(text) {
    return String(text || '').replace(/\r\n?/g, '\n');
}

function setMessageLogicalText(messageDiv, text) {
    if (!messageDiv) return '';
    const normalizedText = normalizeLogicalMessageText(text);
    messageDiv.dataset.logicalMessageText = normalizedText;
    return normalizedText;
}

function getMessageLogicalText(messageDiv) {
    if (!messageDiv) return '';
    return normalizeLogicalMessageText(messageDiv.dataset.logicalMessageText || '');
}

function getMessageBubbleStack(messageDiv) {
    if (!messageDiv) return null;
    let stack = messageDiv.querySelector('.message-bubble-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.className = 'message-bubble-stack';
    }
    return stack;
}

function normalizeMessageAttachments(attachments) {
    if (!attachments || attachments.length === 0) {
        return [];
    }
    return attachments.map((attachment) => {
        if (typeof attachment === 'string') {
            return { category: 'image', name: '이미지', dataUrl: attachment };
        }
        return attachment;
    });
}

function getMessageVisualAttachments(messageDiv) {
    if (!messageDiv || !Array.isArray(messageDiv._messageAttachments)) {
        return [];
    }
    return messageDiv._messageAttachments;
}

function splitLongMessageLineBySentence(line) {
    const normalizedLine = String(line || '').trim();
    if (!normalizedLine || normalizedLine.length < MESSAGE_VISUAL_SENTENCE_SPLIT_MIN_LENGTH) {
        return [normalizedLine].filter(Boolean);
    }

    const sentenceMatches = normalizedLine.match(/[^.!?。！？]+(?:[.!?。！？]+["')\]]*\s*|$)/g);
    if (!sentenceMatches || sentenceMatches.length <= 1) {
        return [normalizedLine];
    }

    return sentenceMatches
        .map((sentence) => sentence.trim())
        .filter(Boolean);
}

function splitMessageIntoVisualChunks(text) {
    const normalizedText = normalizeLogicalMessageText(text);
    if (!messageSplitEnabled) {
        return normalizedText ? [normalizedText] : [];
    }
    const rawLines = normalizedText.split('\n');
    const chunks = [];

    rawLines.forEach((line) => {
        const trimmedLine = line.trim();
        if (!trimmedLine) {
            return;
        }

        splitLongMessageLineBySentence(trimmedLine).forEach((segment) => {
            if (segment) {
                chunks.push(segment);
            }
        });
    });

    if (chunks.length > 0) {
        return chunks;
    }

    return normalizedText.trim() ? [normalizedText.trim()] : [];
}

function createMessageAttachmentBubble(attachments) {
    const normalizedAttachments = normalizeMessageAttachments(attachments);
    if (normalizedAttachments.length === 0) {
        return null;
    }

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble message-bubble-attachment';

    const attachmentList = document.createElement('div');
    attachmentList.className = 'message-attachment-list';

    normalizedAttachments.forEach((attachment) => {
        const chip = document.createElement('div');
        chip.className = 'message-attachment-chip';

        if (attachment.category === 'image' && attachment.dataUrl) {
            const img = document.createElement('img');
            img.src = attachment.dataUrl;
            chip.appendChild(img);
        } else {
            const extensionBadge = document.createElement('span');
            extensionBadge.textContent = getFileExtension(attachment.name || 'file').toUpperCase() || 'FILE';
            chip.appendChild(extensionBadge);
        }

        const label = document.createElement('span');
        label.textContent = attachment.name || (attachment.category === 'image' ? '이미지' : '첨부 파일');
        chip.appendChild(label);
        attachmentList.appendChild(chip);
    });

    bubble.appendChild(attachmentList);
    return bubble;
}

function createTextMessageBubble() {
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    const textSpan = document.createElement('span');
    bubble.appendChild(textSpan);
    return { bubble, textSpan };
}

function renderMessageBubbleSegments(messageDiv, text, { attachments = null, immediate = false } = {}) {
    if (!messageDiv) {
        return Promise.resolve();
    }

    const stack = getMessageBubbleStack(messageDiv);
    const normalizedText = setMessageLogicalText(messageDiv, text);
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

    const attachmentBubble = createMessageAttachmentBubble(resolvedAttachments);
    if (attachmentBubble) {
        stack.appendChild(attachmentBubble);
    }

    const segments = splitMessageIntoVisualChunks(text);
    if (!attachmentBubble && segments.length === 0) {
        segments.push('');
    }

    let animationQueue = Promise.resolve();
    segments.forEach((segment) => {
        const { bubble, textSpan } = createTextMessageBubble();
        stack.appendChild(bubble);
        animationQueue = animationQueue.then(() => animateMessageText(textSpan, segment, { immediate }));
    });

    chatMessages.scrollTop = chatMessages.scrollHeight;
    return animationQueue;
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
        isRequestPending = true;
        shouldReplaceNextAssistant = true;
        showLoadingIndicator(true);
        updateRerollButtonState();
        window.pyBridge.edit_last_user_message(trimmed);
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
    if (!window.pyBridge || !window.pyBridge.summarize_now) return;
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

// 리롤/수정 응답 수신 시 마지막 assistant 버블 내용을 교체한다.
function replaceLastAssistantMessage(text, timestamp = new Date()) {
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
        immediate: false
    });
    return true;
}

/**
 * 채팅 영역에 메시지 버블을 추가한다.
 */
// 채팅 메시지(텍스트/첨부)를 DOM에 append하고 상태를 갱신한다.
function addMessage(text, role, attachments = [], timestamp = new Date()) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.dataset.messageTimestamp = normalizeMessageTimestampValue(timestamp);
    setMessageLogicalText(messageDiv, text);
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
        immediate: false
    });
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
    addMessage(message || '(첨부)', 'user', pendingAttachments, new Date());
    chatInput.value = '';
    autoResizeTextarea();
    if (window.pyBridge) {
        isRequestPending = true;
        setPerformanceState('thinking');
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
            addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date());
            isRequestPending = false;
            shouldReplaceNextAssistant = false;
            updateRerollButtonState();
            showLoadingIndicator(false);
        });
    } else {
        console.error("Python bridge not connected");
        addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date());
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

    addMessage(message, 'user', [], new Date());
    if (window.pyBridge && window.pyBridge.send_to_ai) {
        isRequestPending = true;
        setPerformanceState('thinking');
        shouldReplaceNextAssistant = false;
        updateRerollButtonState();
        showLoadingIndicator(true);
        dispatchBridgeCall(() => {
            window.pyBridge.send_to_ai(message);
        }, (error) => {
            console.error("Python bridge dispatch failed", error);
            addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date());
            isRequestPending = false;
            shouldReplaceNextAssistant = false;
            updateRerollButtonState();
            showLoadingIndicator(false);
        });
        return;
    }

    console.error("Python bridge not connected");
    addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date());
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
    moodToggleButton.addEventListener('click', () => {
        setMoodPanelOpen(!moodPanelOpen);
        setFloatingActionsOpen(false);
    });
}

if (obsNoteButton) {
    obsNoteButton.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.toggle_obs_panel) {
            window.pyBridge.toggle_obs_panel();
        }
        setFloatingActionsOpen(false);
    });
}

if (moodCollapseButton) {
    moodCollapseButton.addEventListener('click', () => setMoodPanelOpen(false));
}

if (manualSummarizeButton) {
    manualSummarizeButton.addEventListener('click', () => {
        requestManualSummary();
        setFloatingActionsOpen(false);
    });
}

if (settingsFloatingButton) {
    settingsFloatingButton.innerHTML = createLucideIcon('settings');
    settingsFloatingButton.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.open_settings_dialog) {
            window.pyBridge.open_settings_dialog();
        }
        setFloatingActionsOpen(false);
    });
}

if (floatingActionsToggle) {
    floatingActionsToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        setFloatingActionsOpen(!floatingActionsOpen);
    });
}

if (floatingActionsMenu) {
    floatingActionsMenu.addEventListener('click', (e) => {
        e.stopPropagation();
    });
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
        return;
    }
    if (e.key === 'Escape' && floatingActionsOpen) {
        setFloatingActionsOpen(false);
    }
});

document.addEventListener('click', (e) => {
    if (!floatingActionsOpen || !floatingActionsRoot) return;
    if (floatingActionsRoot.contains(e.target)) return;
    setFloatingActionsOpen(false);
});

setFloatingActionsOpen(false);
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
            const receivedAt = new Date();
            if (shouldReplaceNextAssistant) {
                const replaced = replaceLastAssistantMessage(text, receivedAt);
                if (!replaced) {
                    addMessage(text, 'assistant', [], receivedAt);
                }
            } else {
                addMessage(text, 'assistant', [], receivedAt);
            }
            shouldReplaceNextAssistant = false;
            updateRerollButtonState();
            cancelPendingPatEmotionRestore();
            baseEmotionTag = (typeof emotion === 'string' && emotion.trim()) ? emotion.trim() : 'normal';
            changeExpression(emotion);
        });
        if (window.pyBridge.performance_state_changed) {
            window.pyBridge.performance_state_changed.connect(function (state) {
                setPerformanceState(state);
            });
        }
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
        if (window.pyBridge.speech_state_changed) {
            window.pyBridge.speech_state_changed.connect(function (state, intensity) {
                receiveSpeechStateSignal(state, intensity);
            });
        }

        if (window.pyBridge.reroll_state_changed) {
            window.pyBridge.reroll_state_changed.connect(function (active) {
                shouldReplaceNextAssistant = Boolean(active);
                isRequestPending = Boolean(active);
                showLoadingIndicator(Boolean(active));
                updateRerollButtonState();
                setPerformanceState(active ? 'thinking' : 'listening');
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
            window.pyBridge.mood_changed.connect(function (label, valence, energy, bond, stress, temporaryState) {
                updateMoodWidget(label, temporaryState, valence, energy, bond, stress);
                setPerformanceMood(mapTemporaryMoodToPerformanceMood(temporaryState, label));
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
                    snapshot.temporary_state,
                    snapshot.valence,
                    snapshot.energy,
                    snapshot.bond,
                    snapshot.stress
                );
                setPerformanceMood(mapTemporaryMoodToPerformanceMood(snapshot.temporary_state, snapshot.current_mood));
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
    currentMouthOpenValue = clamp01(Number(value) || 0);
    if (currentMouthOpenValue > 0.001) {
        lastSpeechAt = performance.now();
    }
}
// Python에서 직접 입 모양을 갱신할 수 있도록 전역에 노출한다.
window.setMouthOpen = setMouthOpen;

console.log("=== Chat and expression system initialized ===");
console.log("=== Lip sync system ready ===");








