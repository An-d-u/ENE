
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
let idleMotionPhase = 0;
let lastSpeechAt = 0;

const MOUTH_POSE_SOURCE_RMS = 'rms';
const MOUTH_POSE_SOURCE_VISEME = 'viseme';

function createEmptyMouthShapeState() {
    return {
        open: 0,
        jaw: 0,
        form: 0,
        funnel: 0,
        puckerWiden: 0,
        tongue: 0,
    };
}

function createEmptyMouthReleaseFadeState() {
    return {
        active: false,
        startedAt: 0,
        activePoseAt: 0,
        completedPoseAt: 0,
        from: createEmptyMouthShapeState(),
    };
}

const mouthExpressionState = {
    expression: createEmptyMouthShapeState(),
    source: MOUTH_POSE_SOURCE_RMS,
    lastPoseAt: 0,
    lastVisemeShape: createEmptyMouthShapeState(),
    releaseFade: createEmptyMouthReleaseFadeState(),
};
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
let patOffsetsCurrent = { angleX: 0, angleY: 0, bodyX: 0, eyeY: 0, breath: 0 };
let patOffsetsApplied = { angleX: 0, angleY: 0, bodyX: 0, eyeY: 0, breath: 0 };
let lastNonPatTrackingState = { angleX: 0, angleY: 0, bodyX: 0, eyeY: 0, breath: 0 };
let syntheticGestureOffsets = createEmptySyntheticGestureOffsets();
let previousEmotionBeforePat = 'normal';
let currentEmotionTag = 'normal';
let baseEmotionTag = 'normal';
let pendingPatEmotionTimer = null;
let pendingPatRestoreEmotion = null;
let headPatFadeInMs = 180;
let headPatFadeOutMs = 220;
let headPatActiveEmotion = 'normal';
let headPatEndEmotion = 'normal';
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
const IDLE_MOTION_BASE_BREATH = 1.0;
const SPEECH_IDLE_BLOCK_MS = 450;
const MOUTH_EXPRESSION_HOLD_MS = 90;
const MOUTH_SHAPE_RELEASE_FADE_MS = 180;
const HEAD_PAT_SPEED_EMA = 0.28;
const HEAD_PAT_INTENSITY_EMA = 0.22;
const HEAD_PAT_DIRECTION_EMA = 0.35;
const HEAD_PAT_SPEED_GAIN = 0.95;
const HEAD_PAT_DECAY_AT_60FPS = 0.84;

let idleMotionSpeedHz = IDLE_MOTION_BASE_SPEED_HZ;
let idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X;
let idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y;
let idleMotionBodyX = IDLE_MOTION_BASE_BODY_X;
let idleMotionBreath = IDLE_MOTION_BASE_BREATH;

function finiteOrZero(value) {
    return Number.isFinite(value) ? value : 0;
}

function createEmptySyntheticGestureOffsets() {
    return {
        angleX: 0,
        angleY: 0,
        angleZ: 0,
        bodyX: 0,
        bodyY: 0,
        bodyZ: 0,
        eyeX: 0,
        eyeY: 0,
        breath: 0,
    };
}

function normalizeSyntheticGestureOffsets(offsets = {}) {
    const source = offsets || {};
    return {
        angleX: finiteOrZero(Number(source.angleX)),
        angleY: finiteOrZero(Number(source.angleY)),
        angleZ: finiteOrZero(Number(source.angleZ)),
        bodyX: finiteOrZero(Number(source.bodyX ?? source.bodyAngleX)),
        bodyY: finiteOrZero(Number(source.bodyY ?? source.bodyAngleY)),
        bodyZ: finiteOrZero(Number(source.bodyZ ?? source.bodyAngleZ)),
        eyeX: finiteOrZero(Number(source.eyeX ?? source.eyeBallX)),
        eyeY: finiteOrZero(Number(source.eyeY ?? source.eyeBallY)),
        breath: finiteOrZero(Number(source.breath)),
    };
}

window.setSyntheticGestureOffsets = function (offsets = {}) {
    syntheticGestureOffsets = normalizeSyntheticGestureOffsets(offsets);
};

window.clearSyntheticGestureOffsets = function () {
    syntheticGestureOffsets = createEmptySyntheticGestureOffsets();
};

window.isHeadPatEffectActive = function () {
    return Boolean(isHeadPatting || patBlend > 0.001 || patBlendMode !== 'idle');
};

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

    const configuredMap = (window.eneModelConfig && window.eneModelConfig.trackingParameterMap) || {};
    const resolveParam = (key, fallbackId) => {
        const configuredId = typeof configuredMap[key] === 'string' ? configuredMap[key].trim() : '';
        if (configuredId && hasParam(configuredId)) {
            return configuredId;
        }
        return hasParam(fallbackId) ? fallbackId : '';
    };

    trackingParamSupport = {
        angleX: resolveParam('angleX', 'ParamAngleX'),
        angleY: resolveParam('angleY', 'ParamAngleY'),
        angleZ: resolveParam('angleZ', 'ParamAngleZ'),
        bodyAngleX: resolveParam('bodyAngleX', 'ParamBodyAngleX'),
        bodyAngleY: resolveParam('bodyAngleY', 'ParamBodyAngleY'),
        bodyAngleZ: resolveParam('bodyAngleZ', 'ParamBodyAngleZ'),
        eyeBallX: resolveParam('eyeBallX', 'ParamEyeBallX'),
        eyeBallY: resolveParam('eyeBallY', 'ParamEyeBallY'),
        breath: resolveParam('breath', 'ParamBreath'),
    };

    return trackingParamSupport;
}

// 정규화된 시선 입력값을 실제 Live2D 파라미터 값으로 변환해 적용한다.
function applyTrackingParams(coreModel, x, y, idleOffsets = null) {
    const support = detectTrackingParams(coreModel);
    const gestureOffsets = syntheticGestureOffsets || createEmptySyntheticGestureOffsets();
    const idleAngleX = idleOffsets ? idleOffsets.angleX : 0;
    const idleAngleY = idleOffsets ? idleOffsets.angleY : 0;
    const idleBodyX = idleOffsets ? idleOffsets.bodyX : 0;
    const idleBodyY = idleOffsets && Number.isFinite(idleOffsets.bodyY) ? idleOffsets.bodyY : 0;
    const idleBodyZ = idleOffsets && Number.isFinite(idleOffsets.bodyZ) ? idleOffsets.bodyZ : 0;
    const idleEyeY = idleOffsets && Number.isFinite(idleOffsets.eyeY) ? idleOffsets.eyeY : 0;
    const gestureAngleX = finiteOrZero(gestureOffsets.angleX);
    const gestureAngleY = finiteOrZero(gestureOffsets.angleY);
    const gestureAngleZ = finiteOrZero(gestureOffsets.angleZ);
    const gestureBodyX = finiteOrZero(gestureOffsets.bodyX);
    const gestureBodyY = finiteOrZero(gestureOffsets.bodyY);
    const gestureBodyZ = finiteOrZero(gestureOffsets.bodyZ);
    const gestureEyeX = finiteOrZero(gestureOffsets.eyeX);
    const gestureEyeY = finiteOrZero(gestureOffsets.eyeY);
    if (support.angleX) coreModel.setParameterValueById(support.angleX, (x * 15) + idleAngleX + gestureAngleX);
    if (support.angleY) coreModel.setParameterValueById(support.angleY, (-y * 15) + idleAngleY + gestureAngleY);
    if (support.angleZ) coreModel.setParameterValueById(support.angleZ, gestureAngleZ);
    if (support.bodyAngleX) coreModel.setParameterValueById(support.bodyAngleX, (x * 5) + idleBodyX + gestureBodyX);
    if (support.bodyAngleY) coreModel.setParameterValueById(support.bodyAngleY, idleBodyY + gestureBodyY);
    if (support.bodyAngleZ) coreModel.setParameterValueById(support.bodyAngleZ, idleBodyZ + gestureBodyZ);
    if (support.eyeBallX) coreModel.setParameterValueById(support.eyeBallX, (x * 0.8) + gestureEyeX);
    if (support.eyeBallY) coreModel.setParameterValueById(support.eyeBallY, (-y * 0.8) + idleEyeY + gestureEyeY);
}

// 유휴 모션이 제공하는 호흡 파라미터를 모델이 지원할 때 함께 반영한다.
function applyIdleBreathParam(coreModel, idleOffsets = null) {
    const support = detectTrackingParams(coreModel);
    if (!support.breath) {
        return;
    }

    const idleBreath = idleOffsets && Number.isFinite(idleOffsets.breath) ? idleOffsets.breath : 0;
    const gestureBreath = finiteOrZero(syntheticGestureOffsets.breath);
    coreModel.setParameterValueById(support.breath, idleBreath + gestureBreath);
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

// 활성 표정이 이미 눈 감기 역할을 하는 경우에는 별도 눈 오버라이드를 중복 적용하지 않는다.
function shouldUseHeadPatEyeCloseOverride() {
    return resolveExpressionEmotion(headPatActiveEmotion) !== 'eyeclose';
}

// 현재 프레임에서 쓰다듬기 눈 오버라이드를 실제로 적용할지 판정한다.
function shouldApplyHeadPatEyeOverrideNow(hasHeadPatEffect) {
    return hasHeadPatEffect && patBlendMode !== 'out' && shouldUseHeadPatEyeCloseOverride();
}

// 립싱크 직후 구간인지 판정해 idle 모션 간섭을 줄인다.
function isSpeakingNow(nowMs) {
    return (nowMs - lastSpeechAt) < SPEECH_IDLE_BLOCK_MS;
}

const MOUTH_EXPRESSION_PARAM_IDS = new Set([
    'ParamMouthOpenY',
    'ParamJawOpen',
    'ParamMouthForm',
    'ParamMouthFunnel',
    'ParamMouthPuckerWiden',
    'ParamTongue',
]);

function normalizeMouthPoseSource(source) {
    return (typeof source === 'string' && source.trim().toLowerCase() === MOUTH_POSE_SOURCE_RMS) ? MOUTH_POSE_SOURCE_RMS : MOUTH_POSE_SOURCE_VISEME;
}

function isMouthExpressionParam(paramId) {
    return MOUTH_EXPRESSION_PARAM_IDS.has(paramId);
}

// 말하는 동안 입 관련 표현식 값은 캐시만 하고, 실제 반영은 합성 단계에서 한다.
function cacheExpressionMouthValue(paramId, value, weight, blend = 'add') {
    const numericValue = normalizeMouthPoseNumber(Number(value));
    const weightedValue = numericValue * (Number.isFinite(weight) ? weight : 0);
    const expression = mouthExpressionState.expression;

    if (paramId === 'ParamMouthOpenY') {
        expression.open = weightedValue;
        return;
    }
    if (paramId === 'ParamJawOpen') {
        expression.jaw = weightedValue;
        return;
    }
    if (paramId === 'ParamMouthForm') {
        expression.form = blend === 'overwrite' ? weightedValue : expression.form + weightedValue;
        return;
    }
    if (paramId === 'ParamMouthFunnel') {
        expression.funnel = blend === 'overwrite' ? weightedValue : expression.funnel + weightedValue;
        return;
    }
    if (paramId === 'ParamMouthPuckerWiden') {
        expression.puckerWiden = blend === 'overwrite' ? weightedValue : expression.puckerWiden + weightedValue;
        return;
    }
    if (paramId === 'ParamTongue') {
        expression.tongue = weightedValue;
    }
}

function resetMouthShapeState(shapeState) {
    shapeState.open = 0;
    shapeState.jaw = 0;
    shapeState.form = 0;
    shapeState.funnel = 0;
    shapeState.puckerWiden = 0;
    shapeState.tongue = 0;
}

function resetExpressionMouthCache() {
    resetMouthShapeState(mouthExpressionState.expression);
}

function shouldHoldExpressionMouthParams(nowMs = performance.now()) {
    return (nowMs - lastSpeechAt) < MOUTH_EXPRESSION_HOLD_MS;
}

function beginMouthExpressionReleaseFade(nowMs = performance.now()) {
    const releaseFade = mouthExpressionState.releaseFade;
    releaseFade.active = true;
    releaseFade.startedAt = nowMs;
    releaseFade.activePoseAt = mouthExpressionState.lastPoseAt;
    releaseFade.from.form = mouthExpressionState.lastVisemeShape.form;
    releaseFade.from.funnel = mouthExpressionState.lastVisemeShape.funnel;
    releaseFade.from.puckerWiden = mouthExpressionState.lastVisemeShape.puckerWiden;
    releaseFade.from.tongue = mouthExpressionState.lastVisemeShape.tongue;
}

function buildReleaseFadeShapeValues(fadeFrom, expressionState, fadeProgress) {
    const fadeWeight = 1 - fadeProgress;
    return {
        form: normalizeMouthPoseNumber((fadeFrom.form * fadeWeight) + (expressionState.form * fadeProgress)),
        funnel: normalizeMouthPoseNumber((fadeFrom.funnel * fadeWeight) + (expressionState.funnel * fadeProgress)),
        puckerWiden: normalizeMouthPoseNumber((fadeFrom.puckerWiden * fadeWeight) + (expressionState.puckerWiden * fadeProgress)),
        tongue: normalizeMouthPoseNumber((fadeFrom.tongue * fadeWeight) + (expressionState.tongue * fadeProgress)),
    };
}

function applyMouthShapeValues(shapeValues) {
    setModelParameterValue('ParamMouthOpenY', shapeValues.open);
    setModelParameterValue('ParamJawOpen', shapeValues.jaw);
    setModelParameterValue('ParamMouthForm', shapeValues.form);
    setModelParameterValue('ParamMouthFunnel', shapeValues.funnel);
    setModelParameterValue('ParamMouthPuckerWiden', shapeValues.puckerWiden);
    setModelParameterValue('ParamTongue', shapeValues.tongue);
}

// 발화가 끝난 직후에는 viseme 모양에서 표정 기본값으로 짧게 복귀시킨다.
function updateMouthExpressionReleaseFade(coreModel, nowMs = performance.now()) {
    if (!coreModel || shouldHoldExpressionMouthParams(nowMs) || mouthExpressionState.source === MOUTH_POSE_SOURCE_RMS) {
        mouthExpressionState.releaseFade.active = false;
        return;
    }

    const releaseFade = mouthExpressionState.releaseFade;
    if (releaseFade.active && releaseFade.activePoseAt !== mouthExpressionState.lastPoseAt) {
        releaseFade.active = false;
    }
    if (!releaseFade.active) {
        if (releaseFade.completedPoseAt === mouthExpressionState.lastPoseAt) {
            return;
        }
        beginMouthExpressionReleaseFade(nowMs);
    }

    const fadeFrom = mouthExpressionState.releaseFade.from;
    const fadeProgress = Math.min((nowMs - mouthExpressionState.releaseFade.startedAt) / MOUTH_SHAPE_RELEASE_FADE_MS, 1);
    const fadeWeight = 1 - fadeProgress;
    const shapeValues = buildReleaseFadeShapeValues(fadeFrom, mouthExpressionState.expression, fadeProgress);

    coreModel.setParameterValueById('ParamMouthForm', shapeValues.form);
    coreModel.setParameterValueById('ParamMouthFunnel', shapeValues.funnel);
    coreModel.setParameterValueById('ParamMouthPuckerWiden', shapeValues.puckerWiden);
    coreModel.setParameterValueById('ParamTongue', shapeValues.tongue);

    if (fadeProgress >= 1) {
        releaseFade.active = false;
        releaseFade.completedPoseAt = mouthExpressionState.lastPoseAt;
        mouthExpressionState.source = MOUTH_POSE_SOURCE_RMS;
    }
}

// idle 모션 전체 활성/비활성 토글.
window.setIdleMotionEnabled = function (enabled) {
    idleMotionEnabled = Boolean(enabled);
    if (!idleMotionEnabled) {
        idleMotionPhase = 0;
    }
    console.log("Idle motion:", idleMotionEnabled ? "enabled" : "disabled");
};

// Live2D 모델이 기본 제공하는 Idle 모션의 활성 상태를 제어한다.
window.setBuiltinIdleMotionEnabled = function (enabled) {
    builtinAutoMotionState.enabled = Boolean(enabled);
    if (builtinAutoMotionState.enabled) {
        startBuiltinIdleMotion();
    } else {
        stopBuiltinIdleMotion();
    }
    console.log("Built-in Live2D idle motion:", builtinAutoMotionState.enabled ? "enabled" : "disabled");
};

// ENE 자동 눈 깜빡임 기능의 활성 상태를 제어한다.
window.setAutoEyeBlinkEnabled = function (enabled) {
    autoEyeBlinkState.enabled = Boolean(enabled);
    syncAutoEyeBlinkMode(window.live2dModel);
    console.log("ENE auto eye blink:", autoEyeBlinkState.enabled ? "enabled" : "disabled");
};

// idle 모션 강도/속도 설정을 JS 쪽 상태값으로 반영한다.
window.setIdleMotionConfig = function (strength, speed) {
    const s = Number.isFinite(strength) ? Math.min(2.0, Math.max(0.2, Number(strength))) : 1.0;
    const v = Number.isFinite(speed) ? Math.min(2.0, Math.max(0.5, Number(speed))) : 1.0;

    idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X * s;
    idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y * s;
    idleMotionBodyX = IDLE_MOTION_BASE_BODY_X * s;
    idleMotionBreath = IDLE_MOTION_BASE_BREATH * s;
    idleMotionSpeedHz = IDLE_MOTION_BASE_SPEED_HZ * v;
};

// 쓰다듬기 감도/페이드/동작 파라미터를 일괄 설정한다.
window.setHeadPatConfig = function (
    enabled,
    strength,
    fadeInMs = 180,
    fadeOutMs = 220,
    activeEmotion = 'normal',
    endEmotion = 'normal',
    endEmotionDurationSec = 5
) {
    headPatEnabled = Boolean(enabled);
    headPatStrength = Number.isFinite(strength) ? Math.min(2.5, Math.max(0.5, Number(strength))) : 1.0;
    headPatFadeInMs = Number.isFinite(fadeInMs) ? Math.min(1000, Math.max(50, Number(fadeInMs))) : 180;
    headPatFadeOutMs = Number.isFinite(fadeOutMs) ? Math.min(1200, Math.max(50, Number(fadeOutMs))) : 220;
    headPatActiveEmotion = typeof activeEmotion === 'string' && activeEmotion.trim() ? activeEmotion.trim() : 'normal';
    headPatEndEmotion = typeof endEmotion === 'string' && endEmotion.trim() ? endEmotion.trim() : 'normal';
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
window.setHeadPatEmotionConfig = function (activeEmotion = 'normal', endEmotion = 'normal', endEmotionDurationSec = 5) {
    headPatActiveEmotion = typeof activeEmotion === 'string' && activeEmotion.trim() ? activeEmotion.trim() : 'normal';
    headPatEndEmotion = typeof endEmotion === 'string' && endEmotion.trim() ? endEmotion.trim() : 'normal';
    headPatEndEmotionDurationMs = Number.isFinite(endEmotionDurationSec)
        ? Math.min(30000, Math.max(1000, Number(endEmotionDurationSec) * 1000))
        : 5000;
};
