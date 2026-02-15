/**
 * Live2D 紐⑤뜽 ?뚮뜑留??ㅽ겕由쏀듃
 * Pixi.js? pixi-live2d-display瑜??ъ슜?섏뿬 Live2D 紐⑤뜽 濡쒕뱶
 */

// ?붾쾭洹?濡쒓렇
console.log("=== Live2D script loaded ===");
console.log("Window location:", window.location.href);

// Pixi.js 諛?Live2D ?쇱씠釉뚮윭由??뺤씤
console.log("PIXI available:", typeof PIXI !== 'undefined');
console.log("Live2DCubismCore available:", typeof Live2DCubismCore !== 'undefined');
console.log("PIXI.live2d available:", typeof PIXI !== 'undefined' && typeof PIXI.live2d !== 'undefined');

// PIXI媛 ?놁쑝硫?以묐떒
if (typeof PIXI === 'undefined') {
    console.error("CRITICAL: PIXI.js is not loaded!");
    document.body.innerHTML = '<div style="color: red; font-family: Arial; text-align: center; margin-top: 50px; font-size: 18px;">PIXI.js 濡쒕뱶 ?ㅽ뙣<br><br>?섏씠吏瑜??덈줈怨좎묠??二쇱꽭??</div>';
    throw new Error("PIXI.js not loaded");
}

// PIXI.live2d媛 ?놁쑝硫?以묐떒
if (typeof PIXI.live2d === 'undefined') {
    console.error("CRITICAL: PIXI.live2d is not available!");
    console.log("Available PIXI properties:", Object.keys(PIXI));
    document.body.innerHTML = '<div style="color: red; font-family: Arial; text-align: center; margin-top: 50px; font-size: 16px;">' +
        'pixi-live2d-display ?쇱씠釉뚮윭由?濡쒕뱶 ?ㅽ뙣<br><br>' +
        '?ъ슜 媛?ν븳 PIXI: ' + Object.keys(PIXI).slice(0, 10).join(', ') + '...<br><br>' +
        '?섏씠吏瑜??덈줈怨좎묠??二쇱꽭??</div>';
    throw new Error("PIXI.live2d not available");
}

console.log("??All libraries loaded successfully");

// Pixi ??珥덇린??
const app = new PIXI.Application({
    view: document.getElementById('live2d-canvas'),
    transparent: true,
    backgroundAlpha: 0,
    resizeTo: window,
    antialias: true
});

console.log("Pixi app initialized");
console.log("Canvas size:", window.innerWidth, "x", window.innerHeight);

// 紐⑤뜽 寃쎈줈 (?곷? 寃쎈줈濡??ㅼ젙)
const modelPath = '../live2d_models/jksalt/jksalt.model3.json';

// ?덈? 寃쎈줈 怨꾩궛 (?붾쾭源낆슜)
const baseUrl = window.location.href.substring(0, window.location.href.lastIndexOf('/'));
const absoluteModelPath = new URL(modelPath, baseUrl + '/').href;
console.log("Model path (relative):", modelPath);
console.log("Model path (absolute):", absoluteModelPath);

// Live2D 紐⑤뜽 濡쒕뱶
async function loadModel() {
    try {
        console.log(`\n=== Loading model ===`);
        console.log(`Path: ${modelPath}`);

        // pixi-live2d-display ?ъ슜
        console.log("Calling PIXI.live2d.Live2DModel.from()...");
        const model = await PIXI.live2d.Live2DModel.from(modelPath);

        console.log("??Model loaded successfully!");
        console.log("Model size:", model.width, "x", model.height);

        // 紐⑤뜽???꾩뿭 蹂?섏뿉 ???(Python?먯꽌 ?묎렐 媛?ν븯寃?
        window.live2dModel = model;

        // 紐⑤뜽???ㅽ뀒?댁???異붽?
        app.stage.addChild(model);

        // ?듭빱 ?ㅼ젙 (以묒떖 湲곗?)
        model.anchor.set(0.5, 0.5);

        // 湲곕낯 ?ш린 諛??꾩튂 (Python ?ㅼ젙?쇰줈 ??뼱?뚯썙吏??덉젙)
        const scaleX = window.innerWidth / model.width;
        const scaleY = window.innerHeight / model.height;
        const scale = Math.min(scaleX, scaleY) * 0.8;  // 80% ?ш린濡?

        model.scale.set(scale);
        model.x = window.innerWidth / 2;
        model.y = window.innerHeight / 2;

        console.log(`Model positioned at (${model.x}, ${model.y}) with scale ${scale}`);


        // ?먮룞 紐⑥뀡 ?ъ깮 (?덈뒗 寃쎌슦)
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

        // ??源쒕묀??(議댁옱?섎뒗 寃쎌슦)
        if (model.internalModel && model.internalModel.eyeBlink) {
            console.log("Eye blink enabled");
        }

        // ?꾩뿭 李몄“ ???
        window.live2dModel = model;

        console.log("=== Model setup complete ===\n");

    } catch (error) {
        console.error("??Failed to load Live2D model");
        console.error("Error:", error);
        console.error("Error type:", error.constructor.name);
        console.error("Error message:", error.message);
        if (error.stack) {
            console.error("Stack trace:", error.stack);
        }

        // ?먮윭 硫붿떆吏 ?쒖떆
        const errorText = new PIXI.Text(
            `Live2D 紐⑤뜽 濡쒕뱶 ?ㅽ뙣\n\n` +
            `?먮윭: ${error.message}\n\n` +
            `寃쎈줈: ${modelPath}\n` +
            `?덈?寃쎈줈: ${absoluteModelPath}\n\n` +
            `肄섏넄???뺤씤?섏꽭??(F12)`,
            {
                fontFamily: 'Arial',
                fontSize: 14,
                fill: 0xff0000,
                align: 'center',
                wordWrap: true,
                wordWrapWidth: window.innerWidth - 40
            }
        );
        errorText.x = window.innerWidth / 2;
        errorText.y = window.innerHeight / 2;
        errorText.anchor.set(0.5);
        app.stage.addChild(errorText);
    }
}

// ?덈룄??由ъ궗?댁쫰 泥섎━
window.addEventListener('resize', () => {
    if (window.live2dModel) {
        const model = window.live2dModel;

        const scaleX = window.innerWidth / model.width;
        const scaleY = window.innerHeight / model.height;
        const scale = Math.min(scaleX, scaleY) * 0.8;

        model.scale.set(scale);
        model.x = window.innerWidth / 2;
        model.y = window.innerHeight / 2;

        console.log("Window resized, model repositioned");
    }
});

// 紐⑤뜽 濡쒕뱶 ?쒖옉
console.log("\n=== Starting model load ===");
loadModel();

// ==========================================
// 留덉슦???몃옒??湲곕뒫
// ==========================================

// ?꾩옱 留덉슦???꾩튂 (?뺢퇋?붾맂 媛? -1 ~ 1)
let currentMouseX = 0;
let currentMouseY = 0;

// 紐⑺몴 留덉슦???꾩튂 (遺?쒕윭???꾪솚???꾪븳 以묎컙媛?
let targetMouseX = 0;
let targetMouseY = 0;

// 留덉슦???몃옒???쒖꽦???щ?
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

function getTrackingCoreModel() {
    const model = window.live2dModel;
    if (!model || !model.internalModel || !model.internalModel.coreModel) {
        return null;
    }
    return model.internalModel.coreModel;
}

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

function applyHeadPatEyeCloseOverride(coreModel, blend) {
    const support = detectHeadPatEyeParams(coreModel);
    const closeAmount = clamp01(blend);
    const openValue = 1 - closeAmount;

    if (support.eyeLOpen) coreModel.setParameterValueById('ParamEyeLOpen', openValue);
    if (support.eyeROpen) coreModel.setParameterValueById('ParamEyeROpen', openValue);
    if (support.eyeLSquint) coreModel.setParameterValueById('ParamEyeLSquint', closeAmount);
    if (support.eyeRSquint) coreModel.setParameterValueById('ParamEyeRSquint', closeAmount);
}

function isSpeakingNow(nowMs) {
    return (nowMs - lastSpeechAt) < SPEECH_IDLE_BLOCK_MS;
}

window.setIdleMotionEnabled = function (enabled) {
    idleMotionEnabled = Boolean(enabled);
    if (!idleMotionEnabled) {
        idleMotionPhase = 0;
    }
    console.log("Idle motion:", idleMotionEnabled ? "enabled" : "disabled");
};

window.setIdleMotionConfig = function (strength, speed) {
    const s = Number.isFinite(strength) ? Math.min(2.0, Math.max(0.2, Number(strength))) : 1.0;
    const v = Number.isFinite(speed) ? Math.min(2.0, Math.max(0.5, Number(speed))) : 1.0;

    idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X * s;
    idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y * s;
    idleMotionBodyX = IDLE_MOTION_BASE_BODY_X * s;
    idleMotionSpeedHz = IDLE_MOTION_BASE_SPEED_HZ * v;
};

window.setIdleMotionDynamic = function (enabled) {
    idleMotionDynamicMode = Boolean(enabled);
    console.log("Idle motion dynamic mode:", idleMotionDynamicMode ? "enabled" : "disabled");
};

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

window.setHeadPatEmotionConfig = function (activeEmotion = 'eyeclose', endEmotion = 'shy', endEmotionDurationSec = 5) {
    headPatActiveEmotion = typeof activeEmotion === 'string' && activeEmotion.trim() ? activeEmotion.trim() : 'eyeclose';
    headPatEndEmotion = typeof endEmotion === 'string' && endEmotion.trim() ? endEmotion.trim() : 'shy';
    headPatEndEmotionDurationMs = Number.isFinite(endEmotionDurationSec)
        ? Math.min(30000, Math.max(1000, Number(endEmotionDurationSec) * 1000))
        : 5000;
};

function clamp01(v) {
    return Math.max(0, Math.min(1, v));
}

function easeInOutCubic(t) {
    const x = clamp01(t);
    return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

function lerp(a, b, t) {
    return a + ((b - a) * t);
}

function isHeadPatPoint(pointerX, pointerY) {
    const model = window.live2dModel;
    if (!model) return false;

    try {
        if (typeof model.hitTest === 'function' && model.hitTest('Head', pointerX, pointerY)) {
            return true;
        }
    } catch (_) {
        // hitTest failed, continue with bounds fallback
    }

    try {
        if (typeof model.getBounds !== 'function') return false;
        const bounds = model.getBounds();
        if (!bounds || !Number.isFinite(bounds.width) || !Number.isFinite(bounds.height)) return false;
        if (bounds.width <= 0 || bounds.height <= 0) return false;

        const minX = bounds.x + (bounds.width * 0.20);
        const maxX = bounds.x + (bounds.width * 0.80);
        const minY = bounds.y + (bounds.height * 0.08);
        const maxY = bounds.y + (bounds.height * 0.40);
        return pointerX >= minX && pointerX <= maxX && pointerY >= minY && pointerY <= maxY;
    } catch (_) {
        return false;
    }
}

function onHeadPatPointerDown(event) {
    if (!headPatEnabled || event.button !== 0) return;

    const chatContainer = document.getElementById('chat-container');
    if (chatContainer && chatContainer.contains(event.target)) {
        return;
    }

    if (!isHeadPatPoint(event.clientX, event.clientY)) {
        return;
    }

    const restoreBaseEmotion = pendingPatRestoreEmotion || currentEmotionTag || 'normal';
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
    event.preventDefault();
}

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
    triggerPatEndEmotion();
}

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

function cancelPendingPatEmotionRestore() {
    if (pendingPatEmotionTimer) {
        clearTimeout(pendingPatEmotionTimer);
        pendingPatEmotionTimer = null;
    }
    pendingPatRestoreEmotion = null;
}

function triggerPatEndEmotion() {
    cancelPendingPatEmotionRestore();
    let endEmotion = (headPatEndEmotion || 'shy').trim();
    if (!endEmotion) endEmotion = 'shy';
    changeExpression(endEmotion);
    pendingPatRestoreEmotion = previousEmotionBeforePat || 'normal';
    pendingPatEmotionTimer = setTimeout(() => {
        pendingPatEmotionTimer = null;
        const restoreEmotion = pendingPatRestoreEmotion || 'normal';
        pendingPatRestoreEmotion = null;
        if (!isHeadPatting) {
            changeExpression(restoreEmotion);
        }
    }, headPatEndEmotionDurationMs);
}

function triggerPatStartEmotion() {
    let activeEmotion = (headPatActiveEmotion || 'eyeclose').trim();
    if (!activeEmotion) activeEmotion = 'eyeclose';
    changeExpression(activeEmotion);
}

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
 * Python?먯꽌 ?몄텧: ?꾩뿭 留덉슦???꾩튂 ?낅뜲?댄듃
 * @param {number} mouseX - 罹붾쾭????留덉슦??X 醫뚰몴 (?쎌?)
 * @param {number} mouseY - 罹붾쾭????留덉슦??Y 醫뚰몴 (?쎌?)
 */
window.updateMousePosition = function (mouseX, mouseY) {
    if (!mouseTrackingEnabled) return;
    if (!Number.isFinite(mouseX) || !Number.isFinite(mouseY)) return;
    
    const model = window.live2dModel;
    if (!model) return;

    // 罹붾쾭???ш린
    const canvasWidth = window.innerWidth;
    const canvasHeight = window.innerHeight;

    // 紐⑤뜽???꾩튂 (以묒떖??
    let trackingOriginX = model.x;
    let trackingOriginY = model.y;

    // 紐⑤뜽 湲곗? ?곷? ?꾩튂 怨꾩궛
    try {
        if (typeof model.getBounds === 'function') {
            const bounds = model.getBounds();
            if (bounds && Number.isFinite(bounds.width) && Number.isFinite(bounds.height) && bounds.width > 0 && bounds.height > 0) {
                trackingOriginX = bounds.x + (bounds.width * 0.5);
                trackingOriginY = bounds.y + (bounds.height * TRACKING_FACE_Y_RATIO);
            }
        }
    } catch (_) {
        // getBounds ?ㅽ뙣 ??model.x/y ?ъ슜
    }

    trackingOriginX = Math.max(0, Math.min(canvasWidth, trackingOriginX));
    trackingOriginY = Math.max(0, Math.min(canvasHeight, trackingOriginY));

    const relativeX = mouseX - trackingOriginX;
    const relativeY = mouseY - trackingOriginY;

    // ?뺢퇋??(-1 ~ 1 踰붿쐞濡?
    // ?붾㈃ ?ш린??50%瑜?湲곗??쇰줈 ?뺢퇋??(?덈Т 怨쇱옣?섏? ?딄쾶)
    const normalizedX = (relativeX / (canvasWidth * 0.5));

    // Adjust baseline vertical gaze with an offset.
    const normalizedY = (relativeY / (canvasHeight * 0.5)) + TRACKING_Y_OFFSET;

    // 踰붿쐞 ?쒗븳 (-1.5 ~ 1.5濡??쎄컙 ?ъ쑀瑜???
    targetMouseX = Math.max(-TRACKING_CLAMP, Math.min(TRACKING_CLAMP, normalizedX));
    targetMouseY = Math.max(-TRACKING_CLAMP, Math.min(TRACKING_CLAMP, normalizedY));
    lastTargetUpdateAt = performance.now();
};

/**
 * 留덉슦???몃옒??ON/OFF
 * @param {boolean} enabled 
 */
window.setMouseTrackingEnabled = function (enabled) {
    mouseTrackingEnabled = Boolean(enabled);
    console.log("Mouse tracking:", mouseTrackingEnabled ? "enabled" : "disabled");

    // 鍮꾪솢?깊솕 ???먯쐞移섎줈
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
        // 紐⑤뜽蹂??뚮씪誘명꽣 李⑥씠??臾댁떆
    }
};

// ?좊땲硫붿씠??猷⑦봽: 遺?쒕윭???꾪솚 諛?紐⑤뜽 ?낅뜲?댄듃
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

    // ?쇱젙 ?쒓컙 ?낅젰???놁쑝硫??쒖꽑???뺣㈃?쇰줈 蹂듦?
    if (nowMs - lastTargetUpdateAt > TRACKING_IDLE_TIMEOUT_MS) {
        targetMouseX = 0;
        targetMouseY = 0;
    }

    // ?꾨젅?꾨젅?댄듃? 臾닿??섍쾶 ?좎궗??媛먯뇿 媛먭컖???좎?
    const dtMs = Math.max(0, Math.min(100, nowMs - lastMouseUpdateAt));
    lastMouseUpdateAt = nowMs;
    const frameScale = dtMs > 0 ? dtMs / (1000 / 60) : 1;
    const damping = 1 - Math.pow(1 - TRACKING_DAMPING_AT_60FPS, frameScale);

    currentMouseX += (targetMouseX - currentMouseX) * damping;
    currentMouseY += (targetMouseY - currentMouseY) * damping;

    // 誘몄꽭 ?⑤┝ ?쒓굅
    if (Math.abs(currentMouseX) < 0.0005) currentMouseX = 0;
    if (Math.abs(currentMouseY) < 0.0005) currentMouseY = 0;
    
    // 留먰븯吏 ?딆쓣 ?뚮쭔 ?좏쑕 紐⑥뀡 ?곸슜
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
        // 紐⑤뜽蹂??뚮씪誘명꽣 李⑥씠??臾댁떆
    }

    requestAnimationFrame(updateMouseTracking);
}

// 留덉슦???몃옒???쒖옉
requestAnimationFrame(updateMouseTracking);
console.log("Mouse tracking initialized");

// ==========================================
// ?쒖젙 ?쒖뒪??
// ==========================================

// 媛먯젙 ???쒖젙 ?뚯씪 留ㅽ븨
const EMOTIONS = {
    'normal': 'normal',
    'angry': 'angry',
    'confused': 'confused',
    'dizzy': 'dizzy',
    'excited': 'excited',
    'joy': 'joy',
    'love': 'love',
    'pathetic': 'pathetic',
    'pervert': 'pervert',
    'sad': 'sad',
    'shy': 'shy',
    'smile': 'smile',
    'smug': 'smug',
    'sulk': 'sulk',
    'teary': 'teary'
};

/**
 * ?쒖젙 蹂寃??⑥닔
 * @param {string} emotion - 媛먯젙 ?대쫫
 */
// ?꾩옱 ?쒖젙 ?좊땲硫붿씠???곹깭
let currentExpressionAnimation = null;
// ?댁쟾 ?쒖젙???뚮씪誘명꽣 ID 紐⑸줉
let previousExpressionParams = [];

async function changeExpression(emotion) {
    const model = window.live2dModel;
    if (!model) {
        console.warn("Model not loaded, cannot change expression");
        return;
    }

    if (!EMOTIONS[emotion]) {
        console.warn(`Unknown emotion: ${emotion}`);
        return;
    }

    try {
        // 'normal' 媛먯젙? 湲곕낯 ?쒖젙(?쒖젙 ?놁쓬)?쇰줈 由ъ뀑
        if (emotion === 'normal') {
            console.log('Resetting to normal expression');

            // ?댁쟾 ?좊땲硫붿씠??痍⑥냼
            if (currentExpressionAnimation) {
                cancelAnimationFrame(currentExpressionAnimation);
            }

            // 紐⑤뱺 ?댁쟾 ?쒖젙 ?뚮씪誘명꽣瑜?0?쇰줈 由ъ뀑
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
                        // ?뚮씪誘명꽣媛 ?놁쓣 ???덉쓬
                    }
                });

                // ?좊땲硫붿씠?섏쑝濡?遺?쒕읇寃?由ъ뀑
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
                            // 臾댁떆
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

        // ?쇰컲 媛먯젙 泥섎━
        if (!EMOTIONS[emotion]) {
            console.warn(`Unknown emotion: ${emotion}`);
            return;
        }

        // ?쒖젙 ?뚯씪 寃쎈줈
        const expressionPath = `../live2d_models/jksalt/emotions/${EMOTIONS[emotion]}.exp3.json`;
        console.log(`Changing expression to: ${emotion} (${expressionPath})`);

        // Live2D ?쒖젙 ?곸슜
        if (model.internalModel && model.internalModel.coreModel) {
            // exp3.json ?뚯씪 濡쒕뱶
            const response = await fetch(expressionPath);
            const expressionData = await response.json();

            // ?댁쟾 ?좊땲硫붿씠??痍⑥냼
            if (currentExpressionAnimation) {
                cancelAnimationFrame(currentExpressionAnimation);
            }

            // ?꾩옱 ?뚮씪誘명꽣 媛????諛?紐⑺몴媛??ㅼ젙
            const startValues = {};
            const targetValues = {};

            // ?댁쟾 ?쒖젙???뚮씪誘명꽣瑜?0?쇰줈 由ъ뀑
            previousExpressionParams.forEach(paramId => {
                try {
                    const currentValue = model.internalModel.coreModel.getParameterValueById(paramId);
                    startValues[paramId] = currentValue;
                    targetValues[paramId] = 0; // ?댁쟾 ?쒖젙 ?뚮씪誘명꽣??0?쇰줈
                } catch (e) {
                    // ?뚮씪誘명꽣媛 ?놁쓣 ???덉쓬
                }
            });

            // ???쒖젙???뚮씪誘명꽣 ?ㅼ젙
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

            // ?댁쟾 ?쒖젙 ?뚮씪誘명꽣 紐⑸줉 ?낅뜲?댄듃
            previousExpressionParams = newExpressionParams;

            // ?좊땲硫붿씠???ㅼ젙
            const duration = 500; // 0.5珥?
            const startTime = Date.now();

            // ?좊땲硫붿씠???⑥닔
            function animate() {
                const elapsed = Date.now() - startTime;
                const progress = Math.min(elapsed / duration, 1.0);

                // Ease-out 怨≪꽑 ?곸슜
                const eased = 1 - Math.pow(1 - progress, 3);

                // 紐⑤뱺 ?뚮씪誘명꽣 蹂닿컙 (?댁쟾 ?쒖젙 由ъ뀑 + ???쒖젙 ?곸슜)
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
                        // 臾댁떆
                    }
                });

                // ?좊땲硫붿씠??怨꾩냽 ?먮뒗 醫낅즺
                if (progress < 1.0) {
                    currentExpressionAnimation = requestAnimationFrame(animate);
                } else {
                    currentExpressionAnimation = null;
                    console.log(`Expression animation complete: ${emotion}`);
                }
            }

            // ?좊땲硫붿씠???쒖옉
            animate();

            console.log(`Expression changing to: ${emotion}`);
        }
    } catch (error) {
        console.error(`Failed to load expression ${emotion}:`, error);
    }
}

// ==========================================
// 梨꾪똿 ?쒖뒪??
// ==========================================

const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const sendButton = document.getElementById('send-button');
const attachButton = document.getElementById('attach-button');
const imageInput = document.getElementById('image-input');
const imagePreviewContainer = document.getElementById('image-preview-container');
const loadingIndicator = document.getElementById('loading-indicator');

// 泥⑤????대?吏 寃쎈줈 紐⑸줉
let attachedImages = [];
let rerollButtonVisibleBySetting = true;
let hasAssistantMessage = false;
let isRequestPending = false;
let shouldReplaceNextAssistant = false;
let lastAssistantMessageEl = null;

/**
 * 濡쒕뵫 ?몃뵒耳?댄꽣 ?쒖떆/?④?
 * @param {boolean} show - true硫??쒖떆, false硫??④?
 */
function showLoadingIndicator(show) {
    if (loadingIndicator) {
        loadingIndicator.style.display = show ? 'flex' : 'none';
        // 濡쒕뵫 ?쒖떆 ??梨꾪똿李??ㅽ겕濡?
        if (show) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
}

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

function updateRerollButtonState() {
    syncLastAssistantMessageRef();

    const oldButtons = chatMessages.querySelectorAll('.message-reroll-btn');
    oldButtons.forEach(btn => btn.remove());

    if (!rerollButtonVisibleBySetting || !hasAssistantMessage || !lastAssistantMessageEl) {
        return;
    }

    const btn = document.createElement('button');
    btn.className = 'message-reroll-btn';
    btn.textContent = 'Reroll';
    btn.title = '理쒓렐 ENE ?듬? ?ㅼ떆 ?앹꽦';
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
}

window.setRerollButtonEnabled = function (enabled) {
    rerollButtonVisibleBySetting = Boolean(enabled);
    updateRerollButtonState();
};

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
 * 硫붿떆吏瑜?梨꾪똿李쎌뿉 異붽?
 * @param {string} text - 硫붿떆吏 ?띿뒪??
 * @param {string} role - 'user' ?먮뒗 'assistant'
 * @param {Array} images - ?대?吏 URL 諛곗뿴 (?듭뀡)
 */
function addMessage(text, role, images = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    // ?대?吏媛 ?덉쑝硫?癒쇱? ?쒖떆
    if (images && images.length > 0) {
        const imagesDiv = document.createElement('div');
        imagesDiv.style.display = 'flex';
        imagesDiv.style.gap = '4px';
        imagesDiv.style.marginBottom = '8px';
        imagesDiv.style.flexWrap = 'wrap';

        images.forEach(imgSrc => {
            const img = document.createElement('img');
            img.src = imgSrc;
            img.style.maxWidth = '100px';
            img.style.maxHeight = '100px';
            img.style.borderRadius = '8px';
            img.style.objectFit = 'cover';
            imagesDiv.appendChild(img);
        });

        bubble.appendChild(imagesDiv);
    }

    // ?띿뒪??異붽?
    const textSpan = document.createElement('span');
    textSpan.textContent = text;
    bubble.appendChild(textSpan);

    messageDiv.appendChild(bubble);
    chatMessages.appendChild(messageDiv);

    // ?ㅽ겕濡ㅼ쓣 留??꾨옒濡?
    chatMessages.scrollTop = chatMessages.scrollHeight;
    if (role === 'assistant') {
        hasAssistantMessage = true;
        lastAssistantMessageEl = messageDiv;
    }
    updateRerollButtonState();
    return messageDiv;
}

/**
 * ?대?吏 泥⑤? 踰꾪듉 ?대┃
 */
attachButton.addEventListener('click', () => {
    imageInput.click();
});

/**
 * ?대?吏 ?좏깮 ??
 */
imageInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files);

    files.forEach(file => {
        if (!file.type.startsWith('image/')) return;

        // 理쒕? 5媛??쒗븳
        if (attachedImages.length >= 5) {
            alert('?대?吏??理쒕? 5媛쒓퉴吏 泥⑤??????덉뼱??');
            return;
        }

        const reader = new FileReader();
        reader.onload = (event) => {
            const imageData = {
                dataUrl: event.target.result,
                name: file.name,
                type: file.type
            };

            attachedImages.push(imageData);
            updateImagePreview();
        };
        reader.readAsDataURL(file);
    });

    // ?낅젰 珥덇린??(媛숈? ?뚯씪 ?ㅼ떆 ?좏깮 媛?ν븯寃?
    imageInput.value = '';
});

/**
 * ?대?吏 誘몃━蹂닿린 ?낅뜲?댄듃
 */
function updateImagePreview() {
    console.log("[Preview] Updating preview, images:", attachedImages.length);

    if (!imagePreviewContainer) {
        console.error("[Preview] imagePreviewContainer is null!");
        return;
    }

    imagePreviewContainer.innerHTML = '';

    attachedImages.forEach((img, index) => {
        console.log("[Preview] Adding image:", img.name);

        const item = document.createElement('div');
        item.className = 'image-preview-item';

        const imgEl = document.createElement('img');
        imgEl.src = img.dataUrl;

        const removeBtn = document.createElement('button');
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '횞';
        removeBtn.onclick = () => {
            attachedImages.splice(index, 1);
            updateImagePreview();
        };

        item.appendChild(imgEl);
        item.appendChild(removeBtn);
        imagePreviewContainer.appendChild(item);
    });

    // 媛뺤젣濡?display ?ㅼ젙
    if (attachedImages.length > 0) {
        imagePreviewContainer.style.display = 'flex';
    } else {
        imagePreviewContainer.style.display = 'none';
    }

    console.log("[Preview] Preview container children:", imagePreviewContainer.children.length);
}


/**
 * ?ъ슜??硫붿떆吏 ?꾩넚
 */
function sendMessage() {
    const message = chatInput.value.trim();

    if (!message && attachedImages.length === 0) return;

    // ?ъ슜??硫붿떆吏 ?쒖떆 (?대?吏 ?ы븿)
    const imageUrls = attachedImages.map(img => img.dataUrl);
    addMessage(message || '(?대?吏)', 'user', imageUrls);

    // ?낅젰李?珥덇린??
    chatInput.value = '';
    // ?믪씠 由ъ뀑
    autoResizeTextarea();

    // Python?쇰줈 硫붿떆吏 ?꾩넚
    if (window.pyBridge) {
        // 濡쒕뵫 ?몃뵒耳?댄꽣 ?쒖떆
        isRequestPending = true;
        shouldReplaceNextAssistant = false;
        updateRerollButtonState();
        showLoadingIndicator(true);

        if (attachedImages.length > 0) {
            // ?대?吏? ?④퍡 ?꾩넚
            const imageDataList = JSON.stringify(attachedImages.map(img => ({
                dataUrl: img.dataUrl,
                name: img.name,
                type: img.type
            })));
            window.pyBridge.send_to_ai_with_images(message, imageDataList);
        } else {
            // ?띿뒪?몃쭔 ?꾩넚
            window.pyBridge.send_to_ai(message);
        }
    } else {
        console.error("Python bridge not connected");
        addMessage("?곌껐 ?ㅻ쪟媛 諛쒖깮?덉뼱??", 'assistant');
        isRequestPending = false;
        shouldReplaceNextAssistant = false;
        updateRerollButtonState();
    }

    // 泥⑤? ?대?吏 珥덇린??
    attachedImages = [];
    updateImagePreview();
}

/**
 * textarea ?먮룞 ?믪씠 議곗젅
 */
function autoResizeTextarea() {
    chatInput.style.height = 'auto';  // ?믪씠 珥덇린??
    chatInput.style.height = chatInput.scrollHeight + 'px';  // ?ㅽ겕濡??믪씠??留욎땄
}

// ?꾩넚 踰꾪듉 ?대┃
sendButton.addEventListener('click', sendMessage);

// Enter ?ㅻ줈 ?꾩넚
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// ?낅젰 ???먮룞 ?믪씠 議곗젅
chatInput.addEventListener('input', autoResizeTextarea);

/**
 * 遺숈뿬?ｊ린(Ctrl+V) ?대깽??泥섎━
 */
chatInput.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;

    let hasImage = false;

    for (const item of items) {
        if (item.type.indexOf('image') === 0) {
            hasImage = true;
            const blob = item.getAsFile();

            // 理쒕? 媛쒖닔 泥댄겕
            if (attachedImages.length >= 5) {
                alert('?대?吏??理쒕? 5媛쒓퉴吏 泥⑤??????덉뼱??');
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                const imageData = {
                    dataUrl: event.target.result,
                    name: "pasted_image.png", // ?꾩쓽???대쫫
                    type: item.type
                };

                attachedImages.push(imageData);
                updateImagePreview();
            };
            reader.readAsDataURL(blob);
        }
    }

    // ?대?吏媛 ?덉쑝硫?遺숈뿬?ｊ린 ?꾩뿉???ъ빱???좎?
    if (hasImage) {
        // ?띿뒪??遺숈뿬?ｊ린???숈떆???????덉쑝誘濡?湲곕낯 ?숈옉? 留됱? ?딆쓬
        // (?? ?대?吏 ?뚯씪留??덈뒗 寃쎌슦 ?띿뒪???낅젰李쎌뿉 ?댁긽??臾몄옄?댁씠 ?ㅼ뼱媛??嫄?留됯퀬 ?띕떎硫?preventDefault 怨좊젮)
    }
});

updateRerollButtonState();

// ==========================================
// QWebChannel 釉뚮┸吏 ?곌껐
// ==========================================

// QWebChannel 珥덇린??
if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function (channel) {
        window.pyBridge = channel.objects.bridge;
        console.log("QWebChannel bridge connected");

        // Python?먯꽌 硫붿떆吏 ?섏떊
        window.pyBridge.message_received.connect(function (text, emotion) {
            console.log(`Received from Python: "${text}" [${emotion}]`);

            // 濡쒕뵫 ?몃뵒耳?댄꽣 ?④?
            showLoadingIndicator(false);
            isRequestPending = false;

            // 由щ·?대㈃ 理쒓렐 assistant 踰꾨툝留?援먯껜, ?ㅽ뙣 ??append
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

            // ?쒖젙 蹂寃?
            changeExpression(emotion);
        });

        // ?쒖젙 蹂寃??쒓렇???곌껐
        window.pyBridge.expression_changed.connect(function (emotion) {
            console.log(`Expression changed: ${emotion}`);
            changeExpression(emotion);
        });

        // 由쎌떛???쒓렇???곌껐
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
    });
} else {
    console.warn("QWebChannel not available - running in standalone mode");
}

// ==========================================
// 由쎌떛???쒖뼱
// ==========================================

/**
 * Live2D 紐⑤뜽????踰뚮┝ ?뺣룄 ?ㅼ젙
 * @param {number} value - ??踰뚮┝ 媛?(0.0 ~ 1.0)
 */
function setMouthOpen(value) {
    const model = window.live2dModel;
    if (!model || !model.internalModel) {
        return;
    }

    try {
        // ParamMouthOpenY ?뚮씪誘명꽣 ?ㅼ젙
        const core = model.internalModel.coreModel;
        if (core && typeof core.setParameterValueById === 'function') {
            core.setParameterValueById('ParamMouthOpenY', value);
        } else if (model.internalModel.setParameterValueById) {
            model.internalModel.setParameterValueById('ParamMouthOpenY', value);
        }
    } catch (e) {
        // ?뚮씪誘명꽣媛 ?놁쓣 ???덉쓬 (紐⑤뜽留덈떎 ?ㅻ쫫)
        // 泥??몄텧?먮쭔 寃쎄퀬
        if (!window._mouthOpenWarned) {
            console.warn("ParamMouthOpenY not available:", e);
            window._mouthOpenWarned = true;
        }
    }
}

// ?꾩뿭?쇰줈 ?몄텧 (Python?먯꽌???몄텧 媛?ν븯寃?
window.setMouthOpen = setMouthOpen;

console.log("=== Chat and expression system initialized ===");
console.log("=== Lip sync system ready ===");



