
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
const EXPRESSIVE_SPEECH_MOTION_RESPONSE_HZ = 3.2;
const EXPRESSIVE_SPEECH_ACTIVITY_RESPONSE_HZ = 2.8;
const EXPRESSIVE_CHANNEL_RESPONSE_HZ = { head: 4.6, body: 2.4, eye: 4.6, root: 1.7, breath: 3.8 };
const EXPRESSIVE_TORSO_MOTION_RESPONSE_HZ = { idle: 2.1, speech: 4.4 };

const EXPRESSIVE_MOTION_LAG_CHANNELS = {
    head: ['angleX', 'angleY', 'angleZ'],
    body: ['bodyX', 'bodyY', 'bodyZ'],
    eye: ['eyeX', 'eyeY'],
    root: ['rootXPercent', 'rootYPercent', 'rootScale'],
    breath: ['breath'],
    expression: ['eyeOpen', 'eyeSmile'],
};

const EXPRESSIVE_SPEECH_POSE_NAMES = new Set(['center', 'lean-in', 'look-up-curious', 'return-breath']);
const EXPRESSIVE_IDLE_POSE_NAMES = new Set(['center', 'settle-back', 'look-down-soft', 'return-breath']);
const EXPRESSIVE_ACCENT_SCHEDULE = {
    idle: { minMs: 12000, maxMs: 28000, chance: 0.42 },
    speech: { minMs: 1200, maxMs: 3000, chance: 0.96 },
};
const EXPRESSIVE_ROOT_MOTION_LIMITS = {
    idle: { x: 0.8, y: 0.55, scale: 0.008 },
    speech: { x: 1.0, y: 0.75, scale: 0.010 },
};
const EXPRESSIVE_MICRO_GAZE_SCHEDULE = {
    idle: { minMs: 2200, maxMs: 4200, chance: 0.70 },
    speech: { minMs: 700, maxMs: 1500, chance: 0.88 },
};
const EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T = 0.14;


let idleMotionSpeedHz = IDLE_MOTION_BASE_SPEED_HZ;
let idleMotionAngleX = IDLE_MOTION_BASE_ANGLE_X;
let idleMotionAngleY = IDLE_MOTION_BASE_ANGLE_Y;
let idleMotionBodyX = IDLE_MOTION_BASE_BODY_X;
let idleMotionBreath = IDLE_MOTION_BASE_BREATH;
let expressiveMotionEnabled = false;
let expressiveMotionStrength = 1.0;
let expressiveMotionSpeed = 1.0;
let expressiveMotionSpeechBoost = 1.0;
let expressiveMotionCurrentPose = createEmptySyntheticGestureOffsets();
let expressiveMotionFromPose = createEmptySyntheticGestureOffsets();
let expressiveMotionTargetPose = createEmptySyntheticGestureOffsets();
let expressiveMotionLaggedOffsets = createEmptySyntheticGestureOffsets();
let expressiveTorsoMotionLaggedOffsets = createEmptySyntheticGestureOffsets();
let expressiveMotionTransitionStartedAt = 0;
let expressiveMotionTransitionDurationMs = 1800;
let expressiveMotionHoldUntilMs = 0;
let expressiveMotionLastPoseName = "center";
let expressiveMotionPhase = 0;
let expressiveSpeechEnergyRaw = 0;
let expressiveSpeechEnergySmoothed = 0;
let expressiveSpeechMotionEnergyFiltered = 0;
let expressiveSpeechActivityBlend = 0;
let expressiveSpeechEnergyUpdatedAt = 0;
let expressiveAccentMotionState = createExpressiveAccentMotionState();
let expressiveMicroGazeState = createExpressiveMicroGazeState();

const EXPRESSIVE_MOTION_POSES = [
    {
        name: "center",
        weight: 0.85,
        transitionMs: [900, 1700],
        holdMs: [800, 1800],
        value: { angleX: 0, angleY: 0, angleZ: 0, bodyX: 0, bodyY: 0, bodyZ: 0, eyeX: 0, eyeY: 0, eyeOpen: 0, eyeSmile: 0, rootXPercent: 0, rootYPercent: 0, rootScale: 0 },
    },
    {
        name: "lean-in",
        weight: 0.95,
        transitionMs: [950, 1750],
        holdMs: [1400, 3300],
        value: { angleX: -0.8, angleY: 3.1, angleZ: -1.6, bodyX: 0.3, bodyY: 1.3, bodyZ: 0.6, eyeX: 0.01, eyeY: 0.06, rootXPercent: 0.8, rootYPercent: -3.7, rootScale: 0.075 },
    },
    {
        name: "settle-back",
        weight: 0.75,
        transitionMs: [1200, 2400],
        holdMs: [1200, 2800],
        value: { angleX: 1.1, angleY: -1.8, angleZ: 1.0, bodyX: -0.4, bodyY: -0.9, bodyZ: -0.5, eyeX: -0.02, eyeY: -0.03, rootXPercent: -0.9, rootYPercent: 1.8, rootScale: -0.022 },
    },
    {
        name: "drift-left-counter",
        weight: 1.05,
        transitionMs: [1400, 2700],
        holdMs: [1800, 4300],
        value: { angleX: 2.8, angleY: 1.4, angleZ: 5.8, bodyX: -1.8, bodyY: 0.6, bodyZ: -2.7, eyeX: 0.03, eyeY: 0.01, rootXPercent: -6.4, rootYPercent: -1.1, rootScale: 0.024 },
    },
    {
        name: "drift-right-counter",
        weight: 0.95,
        transitionMs: [1300, 2600],
        holdMs: [1700, 3900],
        value: { angleX: -2.1, angleY: 1.9, angleZ: -4.7, bodyX: 2.2, bodyY: 0.4, bodyZ: 2.1, eyeX: -0.01, eyeY: 0.01, rootXPercent: 5.6, rootYPercent: -1.7, rootScale: 0.018 },
    },
    {
        name: "look-up-curious",
        weight: 0.8,
        transitionMs: [850, 1600],
        holdMs: [1300, 3200],
        value: { angleX: -1.7, angleY: 5.7, angleZ: -5.2, bodyX: 0.8, bodyY: 1.1, bodyZ: -1.5, eyeX: 0.05, eyeY: 0.04, rootXPercent: 2.1, rootYPercent: -3.9, rootScale: 0.040 },
    },
    {
        name: "look-down-soft",
        weight: 0.8,
        transitionMs: [1100, 2300],
        holdMs: [1500, 3600],
        value: { angleX: 1.4, angleY: -5.0, angleZ: 2.4, bodyX: -0.6, bodyY: -1.0, bodyZ: 0.9, eyeX: -0.02, eyeY: -0.04, rootXPercent: -1.7, rootYPercent: 2.3, rootScale: -0.014 },
    },
    {
        name: "shy-side-hold",
        weight: 0.65,
        transitionMs: [1500, 2900],
        holdMs: [2200, 5200],
        value: { angleX: -3.6, angleY: 0.9, angleZ: -11.8, bodyX: 1.0, bodyY: 0.2, bodyZ: 3.5, eyeX: 0.03, eyeY: -0.01, rootXPercent: 3.9, rootYPercent: -0.5, rootScale: 0.028 },
    },
    {
        name: "return-breath",
        weight: 0.55,
        transitionMs: [1600, 3100],
        holdMs: [900, 2100],
        value: { angleX: 0.5, angleY: 1.0, angleZ: 0.7, bodyX: -0.2, bodyY: 0.3, bodyZ: -0.3, eyeX: -0.01, eyeY: 0.01, breath: 0.24, rootXPercent: -0.4, rootYPercent: -0.8, rootScale: 0.010 },
    },
];
const EXPRESSIVE_ACCENT_MOTIONS = [
    {
        name: "big-sway",
        idleWeight: 1.0,
        speechWeight: 0.45,
        durationMs: 3600,
        interpolation: "cubic",
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.10, value: { eyeX: -0.012, eyeY: 0.008, angleZ: -1.8, angleX: -0.2, bodyX: -0.5, bodyY: 0.2, bodyZ: -0.4, breath: 0.18, rootXPercent: -0.05, rootYPercent: -0.04, rootScale: 0.001 } },
            { t: 0.40, value: { eyeX: -0.014, eyeY: 0.012, angleZ: -10.4, angleX: -0.8, bodyX: -7.2, bodyY: 1.5, bodyZ: -5.4, breath: 0.72, eyeOpen: -0.08, eyeSmile: 0.10, rootXPercent: -0.72, rootYPercent: -0.16, rootScale: 0.004 } },
            { t: 0.54, value: { eyeX: 0.0, eyeY: 0.008, angleZ: 0.0, angleX: 0.0, bodyX: -0.4, bodyY: 0.3, bodyZ: -0.2, breath: 0.22, rootXPercent: -0.04, rootYPercent: -0.04, rootScale: 0.001 } },
            { t: 0.84, value: { eyeX: 0.014, eyeY: 0.012, angleZ: 11.2, angleX: 0.9, bodyX: 8.0, bodyY: 1.6, bodyZ: 6.0, breath: 0.74, eyeOpen: -0.08, eyeSmile: 0.10, rootXPercent: 0.84, rootYPercent: -0.16, rootScale: 0.004 } },
            { t: 0.96, value: { eyeX: 0.004, eyeY: 0.008, angleZ: 1.3, angleX: 0.1, bodyX: 0.5, bodyY: 0.2, bodyZ: 0.4, breath: 0.14, rootXPercent: 0.06, rootYPercent: -0.03, rootScale: 0.001 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "lean-peek",
        idleWeight: 0.9,
        speechWeight: 1.25,
        durationMs: 2300,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeY: 0.04 } },
            { t: 0.20, value: { eyeY: 0.04, angleY: 7.8 } },
            { t: 0.36, value: { eyeY: 0.04, angleY: 8.6, bodyY: 3.7, breath: 0.58, eyeOpen: -0.08, rootYPercent: -0.7, rootScale: 0.016 } },
            { t: 0.66, value: { eyeY: 0.03, angleY: 6.4, bodyY: 2.6, breath: 0.42, rootYPercent: -0.5, rootScale: 0.012 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "curious-look",
        idleWeight: 1.05,
        speechWeight: 1.05,
        durationMs: 2550,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeX: -0.02, eyeY: 0.04 } },
            { t: 0.24, value: { eyeX: -0.02, eyeY: 0.04, angleX: 7.2, angleY: 6.2, angleZ: 9.8 } },
            { t: 0.42, value: { eyeX: -0.02, eyeY: 0.04, angleX: 8.4, angleY: 6.8, angleZ: 11.0, bodyX: 1.7, bodyY: 1.0, bodyZ: 3.8, eyeOpen: -0.07, rootXPercent: 0.6, rootYPercent: -0.4, rootScale: 0.007 } },
            { t: 0.76, value: { eyeX: -0.02, eyeY: 0.03, angleX: 6.5, angleY: 5.3, angleZ: 10.4, bodyX: 2.0, bodyY: 0.8, bodyZ: 4.1, rootXPercent: 0.7, rootYPercent: -0.3 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "question-tilt",
        idleWeight: 0.9,
        speechWeight: 1.00,
        durationMs: 2650,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeX: -0.02, eyeY: 0.04 } },
            { t: 0.24, value: { eyeX: -0.02, eyeY: 0.04, angleX: 6.6, angleY: 6.0, angleZ: 11.8 } },
            { t: 0.46, value: { eyeX: -0.02, eyeY: 0.04, angleX: 7.4, angleY: 6.6, angleZ: 14.0, bodyX: 1.8, bodyY: 0.8, bodyZ: 4.5, eyeOpen: -0.08, eyeSmile: 0.08, rootXPercent: 0.7, rootYPercent: -0.3, rootScale: 0.006 } },
            { t: 0.78, value: { eyeX: -0.01, eyeY: 0.02, angleX: 5.4, angleY: 4.8, angleZ: 12.8, bodyX: 2.1, bodyY: 0.6, bodyZ: 4.0, rootXPercent: 0.6 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "soft-bounce",
        idleWeight: 0.35,
        speechWeight: 2.40,
        durationMs: 1750,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeY: 0.02 } },
            { t: 0.18, value: { eyeY: 0.04, angleY: 5.8 } },
            { t: 0.30, value: { eyeY: 0.04, angleY: 6.8, bodyY: 4.4, breath: 0.78, rootYPercent: -0.6, rootScale: 0.010 } },
            { t: 0.48, value: { eyeY: -0.02, angleY: -2.8, bodyY: -1.7, breath: 0.24, rootYPercent: 0.3, rootScale: -0.003 } },
            { t: 0.72, value: { eyeY: 0.02, angleY: 3.6, bodyY: 2.2, breath: 0.42, rootYPercent: -0.3, rootScale: 0.006 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "rhythm-sway",
        idleWeight: 0.95,
        speechWeight: 0.45,
        durationMs: 3800,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.10, value: { eyeX: 0, eyeY: 0.01, eyeOpen: -0.03 } },
            { t: 0.20, value: { bodyX: -1.8, bodyY: 1.1, bodyZ: -2.8, breath: 0.34, rootXPercent: -0.4, rootYPercent: -0.2 } },
            { t: 0.28, value: { angleX: 1.4, angleY: -1.0, angleZ: -5.2, eyeX: 0, eyeY: 0, eyeOpen: -0.08, eyeSmile: 0.08 } },
            { t: 0.42, value: { bodyX: 1.7, bodyY: 0.9, bodyZ: 2.5, breath: 0.30, rootXPercent: 0.4, rootYPercent: -0.1 } },
            { t: 0.50, value: { angleX: -1.0, angleY: -0.6, angleZ: 4.4, eyeX: 0, eyeY: 0, eyeOpen: -0.03 } },
            { t: 0.58, value: { angleX: -1.2, angleY: -0.8, angleZ: 5.0, eyeX: 0, eyeY: 0, eyeOpen: -0.10, eyeSmile: 0.10 } },
            { t: 0.72, value: { bodyX: -1.3, bodyY: 0.7, bodyZ: -2.0, breath: 0.26, rootXPercent: -0.3, rootYPercent: 0.0 } },
            { t: 0.80, value: { angleX: 0.8, angleY: -0.5, angleZ: -3.8, eyeX: 0, eyeY: 0, eyeOpen: -0.04 } },
            { t: 0.92, value: { bodyX: 0.4, bodyY: 0.2, bodyZ: 0.5, angleZ: 0.8, breath: 0.12, rootXPercent: 0.1 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "bounce-groove-small",
        idleWeight: 0.55,
        speechWeight: 4.20,
        durationMs: 2850,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.08, value: { eyeX: 0, eyeY: 0.01, eyeOpen: -0.04 } },
            { t: 0.16, value: { bodyY: 3.9, bodyZ: 1.2, breath: 0.70, rootYPercent: -0.5, rootScale: 0.006 } },
            { t: 0.24, value: { angleY: 4.8, angleZ: -2.6, eyeX: 0, eyeY: 0.01, eyeOpen: -0.12, eyeSmile: 0.12 } },
            { t: 0.34, value: { bodyY: -1.4, bodyZ: -0.8, breath: 0.24, rootYPercent: 0.2, rootScale: -0.002 } },
            { t: 0.44, value: { angleY: -2.4, angleZ: 1.4, eyeX: 0, eyeY: 0, eyeOpen: -0.02 } },
            { t: 0.54, value: { bodyY: 3.2, bodyZ: -1.0, breath: 0.58, rootYPercent: -0.4, rootScale: 0.005 } },
            { t: 0.62, value: { angleY: 4.1, angleZ: 2.2, eyeX: 0, eyeY: 0.01, eyeOpen: -0.08, eyeSmile: 0.08 } },
            { t: 0.74, value: { bodyY: -0.9, bodyZ: 0.5, breath: 0.20, rootYPercent: 0.1, rootScale: -0.001 } },
            { t: 0.86, value: { angleY: 1.2, angleZ: -0.5, bodyY: 0.8, breath: 0.18, eyeX: 0, eyeY: 0 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "bounce-groove-large",
        idleWeight: 0.20,
        speechWeight: 4.60,
        durationMs: 3250,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.08, value: { eyeX: 0, eyeY: 0.01, eyeOpen: -0.05 } },
            { t: 0.18, value: { bodyY: 7.2, bodyZ: 1.2, breath: 1.12, rootYPercent: -0.55, rootScale: 0.007 } },
            { t: 0.28, value: { angleY: 6.8, angleZ: -1.1, eyeX: 0, eyeY: 0.01, eyeOpen: -0.15, eyeSmile: 0.14 } },
            { t: 0.44, value: { bodyY: -1.8, bodyZ: -1.0, breath: 0.26, rootYPercent: 0.2, rootScale: -0.002 } },
            { t: 0.56, value: { angleY: -2.8, angleZ: 1.8, eyeX: 0, eyeY: 0, eyeOpen: -0.03 } },
            { t: 0.66, value: { bodyY: 4.8, bodyZ: -1.4, breath: 0.76, rootYPercent: -0.6, rootScale: 0.007 } },
            { t: 0.76, value: { angleY: 5.4, angleZ: 2.8, eyeX: 0, eyeY: 0.01, eyeOpen: -0.10, eyeSmile: 0.10 } },
            { t: 0.88, value: { bodyY: -0.8, bodyZ: 0.4, breath: 0.18, rootYPercent: 0.1, rootScale: -0.001 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "talk-bounce-lift",
        idleWeight: 0.08,
        speechWeight: 4.80,
        durationMs: 1900,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.10, value: { eyeX: 0, eyeY: 0.02, eyeOpen: -0.04 } },
            { t: 0.20, value: { eyeX: 0, eyeY: 0.02, angleY: 6.2, angleZ: 0.4, bodyY: 6.8, bodyZ: 1.0, breath: 1.05, rootYPercent: -0.55, rootScale: 0.006 } },
            { t: 0.34, value: { eyeX: 0, eyeY: -0.01, angleY: -2.6, angleZ: -0.2, bodyY: -2.2, bodyZ: -0.8, breath: 0.22, rootYPercent: 0.18, rootScale: -0.002 } },
            { t: 0.52, value: { eyeX: 0, eyeY: 0.02, angleY: 5.2, angleZ: 0.3, bodyY: 5.6, bodyZ: 0.7, breath: 0.86, rootYPercent: -0.45, rootScale: 0.005 } },
            { t: 0.70, value: { eyeX: 0, eyeY: 0, angleY: -1.2, angleZ: 0, bodyY: -1.0, bodyZ: -0.3, breath: 0.18, rootYPercent: 0.08, rootScale: -0.001 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "talk-bounce-double",
        idleWeight: 0.06,
        speechWeight: 4.40,
        durationMs: 2200,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.08, value: { eyeX: 0, eyeY: 0.02, eyeOpen: -0.03 } },
            { t: 0.18, value: { eyeX: 0, eyeY: 0.02, angleY: 5.8, angleZ: 0.2, bodyY: 5.6, bodyZ: 0.8, breath: 0.88, rootYPercent: -0.45, rootScale: 0.005 } },
            { t: 0.32, value: { eyeX: 0, eyeY: -0.01, angleY: -2.0, angleZ: -0.1, bodyY: -1.6, bodyZ: -0.6, breath: 0.20, rootYPercent: 0.14, rootScale: -0.002 } },
            { t: 0.42, value: { eyeX: 0, eyeY: 0.01, angleY: 2.0, angleZ: 0.1, bodyY: 1.6, bodyZ: 0.4, breath: 0.34, rootYPercent: -0.14, rootScale: 0.002 } },
            { t: 0.58, value: { eyeX: 0, eyeY: 0.02, angleY: 5.2, angleZ: -0.2, bodyY: 5.0, bodyZ: 0.6, breath: 0.78, rootYPercent: -0.40, rootScale: 0.004 } },
            { t: 0.76, value: { eyeX: 0, eyeY: 0, angleY: -1.4, angleZ: 0, bodyY: -1.0, bodyZ: -0.3, breath: 0.18, rootYPercent: 0.08, rootScale: -0.001 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "talk-bounce-triple",
        idleWeight: 0.05,
        speechWeight: 4.10,
        durationMs: 2550,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.06, value: { eyeX: 0, eyeY: 0.02, eyeOpen: -0.03 } },
            { t: 0.16, value: { eyeX: 0, eyeY: 0.02, angleY: 4.8, angleZ: 0.1, bodyY: 4.8, bodyZ: 0.6, breath: 0.72, rootYPercent: -0.34, rootScale: 0.004 } },
            { t: 0.28, value: { eyeX: 0, eyeY: -0.01, angleY: -1.5, angleZ: 0, bodyY: -1.2, bodyZ: -0.4, breath: 0.18, rootYPercent: 0.10, rootScale: -0.001 } },
            { t: 0.36, value: { eyeX: 0, eyeY: 0.01, angleY: 1.6, angleZ: 0, bodyY: 1.2, bodyZ: 0.2, breath: 0.28, rootYPercent: -0.08, rootScale: 0.001 } },
            { t: 0.46, value: { eyeX: 0, eyeY: 0.02, angleY: 5.2, angleZ: -0.1, bodyY: 5.2, bodyZ: 0.6, breath: 0.78, rootYPercent: -0.38, rootScale: 0.004 } },
            { t: 0.58, value: { eyeX: 0, eyeY: -0.01, angleY: -1.3, angleZ: 0, bodyY: -1.0, bodyZ: -0.3, breath: 0.18, rootYPercent: 0.08, rootScale: -0.001 } },
            { t: 0.66, value: { eyeX: 0, eyeY: 0.01, angleY: 1.4, angleZ: 0, bodyY: 1.0, bodyZ: 0.2, breath: 0.24, rootYPercent: -0.06, rootScale: 0.001 } },
            { t: 0.74, value: { eyeX: 0, eyeY: 0.01, angleY: 4.4, angleZ: 0, bodyY: 4.4, bodyZ: 0.4, breath: 0.64, rootYPercent: -0.30, rootScale: 0.003 } },
            { t: 0.88, value: { eyeX: 0, eyeY: 0, angleY: -0.8, angleZ: 0, bodyY: -0.6, bodyZ: -0.1, breath: 0.12, rootYPercent: 0.04, rootScale: -0.001 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "talk-hop-recoil",
        idleWeight: 0.04,
        speechWeight: 3.60,
        durationMs: 1750,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.08, value: { eyeX: 0, eyeY: 0.03, eyeOpen: -0.06 } },
            { t: 0.16, value: { eyeX: 0, eyeY: 0.03, angleY: 8.4, angleZ: 0.6, bodyY: 8.4, bodyZ: 1.4, breath: 1.18, eyeOpen: -0.10, rootYPercent: -0.62, rootScale: 0.008 } },
            { t: 0.30, value: { eyeX: 0, eyeY: -0.01, angleY: -1.0, angleZ: 0.1, bodyY: 0.8, bodyZ: -0.2, breath: 0.34, rootYPercent: -0.04, rootScale: 0.001 } },
            { t: 0.42, value: { eyeX: 0, eyeY: -0.01, angleY: -3.4, angleZ: -0.2, bodyY: -2.8, bodyZ: -0.9, breath: 0.18, rootYPercent: 0.22, rootScale: -0.003 } },
            { t: 0.68, value: { eyeX: 0, eyeY: 0.01, angleY: 2.2, angleZ: 0, bodyY: 1.8, bodyZ: 0.2, breath: 0.30, rootYPercent: -0.12, rootScale: 0.002 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "idle-breath-lift",
        idleWeight: 1.10,
        speechWeight: 0.20,
        durationMs: 5200,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.16, value: { eyeX: 0, eyeY: 0.01, eyeOpen: -0.02 } },
            { t: 0.32, value: { eyeX: 0, eyeY: 0.01, angleY: 2.4, angleZ: 0.3, bodyY: 3.8, bodyZ: 0.6, breath: 0.74, rootYPercent: -0.32, rootScale: 0.004 } },
            { t: 0.50, value: { eyeX: 0, eyeY: 0.01, angleY: 2.2, angleZ: 0.1, bodyY: 3.2, bodyZ: 0.5, breath: 0.66, rootYPercent: -0.28, rootScale: 0.003 } },
            { t: 0.68, value: { eyeX: 0, eyeY: 0, angleY: 1.8, angleZ: -0.2, bodyY: 2.8, bodyZ: 0.4, breath: 0.58, rootYPercent: -0.24, rootScale: 0.003 } },
            { t: 0.86, value: { eyeX: 0, eyeY: 0, angleY: 0.8, angleZ: 0, bodyY: 1.0, bodyZ: 0.1, breath: 0.22, rootYPercent: -0.08, rootScale: 0.001 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "talk-tilt-left-hold",
        idleWeight: 0.12,
        speechWeight: 0.45,
        durationMs: 2100,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeX: 0.03, eyeY: 0.01, eyeOpen: -0.03 } },
            { t: 0.24, value: { eyeX: 0.02, eyeY: 0.01, angleY: 3.8, angleZ: -3.4, bodyX: 0.3, bodyY: 0.5, bodyZ: 0.9 } },
            { t: 0.38, value: { eyeX: 0.02, eyeY: 0.01, angleY: 4.2, angleZ: -4.2, bodyX: 0.4, bodyY: 0.7, bodyZ: 1.2, eyeOpen: -0.04, rootXPercent: 0.1 } },
            { t: 0.64, value: { eyeX: 0.02, eyeY: 0.01, angleY: 3.8, angleZ: -3.8, bodyX: 0.3, bodyY: 0.5, bodyZ: 1.0, eyeSmile: 0.04 } },
            { t: 0.84, value: { eyeX: 0.01, eyeY: 0, angleY: 1.2, angleZ: -1.4, bodyX: 0.1, bodyY: 0.2, bodyZ: 0.3 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "talk-tilt-right-hold",
        idleWeight: 0.12,
        speechWeight: 0.45,
        durationMs: 2100,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeX: -0.03, eyeY: 0.01, eyeOpen: -0.03 } },
            { t: 0.24, value: { eyeX: -0.02, eyeY: 0.01, angleY: 3.8, angleZ: 3.4, bodyX: -0.3, bodyY: 0.5, bodyZ: -0.9 } },
            { t: 0.38, value: { eyeX: -0.02, eyeY: 0.01, angleY: 4.2, angleZ: 4.2, bodyX: -0.4, bodyY: 0.7, bodyZ: -1.2, eyeOpen: -0.04, rootXPercent: -0.1 } },
            { t: 0.64, value: { eyeX: -0.02, eyeY: 0.01, angleY: 3.8, angleZ: 3.8, bodyX: -0.3, bodyY: 0.5, bodyZ: -1.0, eyeSmile: 0.04 } },
            { t: 0.84, value: { eyeX: -0.01, eyeY: 0, angleY: 1.2, angleZ: 1.4, bodyX: -0.1, bodyY: 0.2, bodyZ: -0.3 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "idle-soft-attention",
        idleWeight: 1.25,
        speechWeight: 0.35,
        durationMs: 4200,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.18, value: { eyeX: -0.03, eyeY: 0.02, eyeOpen: -0.04 } },
            { t: 0.34, value: { eyeX: -0.03, eyeY: 0.02, angleY: 3.8, angleZ: 5.2, bodyX: -0.6, bodyY: 0.4, bodyZ: 1.4, breath: 0.20 } },
            { t: 0.62, value: { eyeX: -0.02, eyeY: 0.01, angleY: 3.2, angleZ: 4.8, bodyX: -0.5, bodyY: 0.3, bodyZ: 1.1, eyeSmile: 0.04 } },
            { t: 0.84, value: { eyeX: 0.01, eyeY: 0, angleY: 0.8, angleZ: 1.4, bodyX: -0.1, bodyY: 0.1, bodyZ: 0.3 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "side-hold",
        idleWeight: 0.8,
        speechWeight: 0.18,
        durationMs: 3200,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeX: 0.02, eyeY: 0.01 } },
            { t: 0.26, value: { eyeX: 0.02, eyeY: 0.01, angleX: -5.4, angleZ: -13.8 } },
            { t: 0.48, value: { eyeX: 0.02, eyeY: 0.01, angleX: -6.2, angleZ: -15.8, bodyX: 3.8, bodyY: 0.7, bodyZ: 5.1, rootXPercent: 0.8 } },
            { t: 0.78, value: { eyeX: 0.01, angleX: -5.6, angleZ: -14.6, bodyX: 3.2, bodyY: 0.5, bodyZ: 4.3, rootXPercent: 0.7 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "glance-left-return",
        idleWeight: 0.70,
        speechWeight: 0.12,
        durationMs: 2450,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.26, value: { eyeX: -0.06, eyeY: 0.02 } },
            { t: 0.52, value: { eyeX: -0.05, eyeY: 0.01, angleZ: 0.2 } },
            { t: 0.84, value: { eyeX: 0, eyeY: 0, angleZ: 0 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "glance-right-return",
        idleWeight: 0.70,
        speechWeight: 0.12,
        durationMs: 2450,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: 0.26, value: { eyeX: 0.06, eyeY: 0.02 } },
            { t: 0.52, value: { eyeX: 0.05, eyeY: 0.01, angleZ: -0.2 } },
            { t: 0.84, value: { eyeX: 0, eyeY: 0, angleZ: 0 } },
            { t: 1.00, value: {} },
        ]),
    },
    {
        name: "settle-shift",
        idleWeight: 0.95,
        speechWeight: 0.18,
        durationMs: 2450,
        frames: createExpressiveStagedAccentFrames([
            { t: 0.00, value: {} },
            { t: EXPRESSIVE_STAGED_ACCENT_EYE_LEAD_T, value: { eyeX: -0.02, eyeY: -0.03 } },
            { t: 0.24, value: { eyeX: -0.02, eyeY: -0.03, angleY: -4.2 } },
            { t: 0.40, value: { eyeX: -0.02, eyeY: -0.03, angleY: -5.6, bodyY: -2.4, bodyX: -2.3, breath: 0.30, rootXPercent: -0.5, rootYPercent: 0.3 } },
            { t: 0.66, value: { eyeX: 0.02, eyeY: 0.02, angleY: 3.5, bodyY: 1.7, bodyX: 1.4, breath: 0.28, rootXPercent: 0.3, rootYPercent: -0.2 } },
            { t: 1.00, value: {} },
        ]),
    },
];
function createExpressiveStagedAccentFrames(frames) {
    return Array.isArray(frames) ? frames : [];
}

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
        eyeOpen: 0,
        eyeSmile: 0,
        rootXPercent: 0,
        rootYPercent: 0,
        rootScale: 0,
    };
}

function cloneMotionOffsets(offsets = {}) {
    return normalizeSyntheticGestureOffsets(offsets);
}

function addMotionOffsets(...offsetList) {
    const combined = createEmptySyntheticGestureOffsets();
    offsetList.forEach((offsets) => {
        const normalized = normalizeSyntheticGestureOffsets(offsets || {});
        Object.keys(combined).forEach((key) => {
            combined[key] += finiteOrZero(normalized[key]);
        });
    });
    return combined;
}

function scaleMotionOffsets(offsets = {}, scale = 1) {
    const normalized = normalizeSyntheticGestureOffsets(offsets);
    const numericScale = Number.isFinite(scale) ? scale : 1;
    Object.keys(normalized).forEach((key) => {
        normalized[key] *= numericScale;
    });
    return normalized;
}

function attenuateExpressiveSpeechLateralPoseOffsets(offsets = {}, speechBlend = 0) {
    const attenuated = cloneMotionOffsets(offsets);
    const speechAmount = Math.max(0, Math.min(1, Number(speechBlend) || 0));
    if (speechAmount <= 0) {
        return attenuated;
    }
    const lateralScale = 1 - (speechAmount * 0.55);
    const rootLateralScale = 1 - (speechAmount * 0.70);
    attenuated.angleZ *= lateralScale;
    attenuated.bodyX *= lateralScale;
    attenuated.bodyZ *= lateralScale;
    attenuated.rootXPercent *= rootLateralScale;
    return attenuated;
}

function clampExpressiveMotionValue(value, minValue, maxValue) {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) {
        return 0;
    }
    return Math.max(minValue, Math.min(maxValue, numericValue));
}

function splitExpressiveMotionOffsets(offsets = {}) {
    const normalized = normalizeSyntheticGestureOffsets(offsets);
    const bodyOffsets = cloneMotionOffsets(normalized);
    const placementOffsets = createEmptySyntheticGestureOffsets();
    placementOffsets.rootXPercent = normalized.rootXPercent;
    placementOffsets.rootYPercent = normalized.rootYPercent;
    placementOffsets.rootScale = normalized.rootScale;
    bodyOffsets.rootXPercent = 0;
    bodyOffsets.rootYPercent = 0;
    bodyOffsets.rootScale = 0;
    return { bodyOffsets, placementOffsets };
}

function reduceExpressiveRootMotionOffsets(offsets = {}, speechActive = false) {
    const normalized = normalizeSyntheticGestureOffsets(offsets);
    const limits = speechActive ? EXPRESSIVE_ROOT_MOTION_LIMITS.speech : EXPRESSIVE_ROOT_MOTION_LIMITS.idle;
    const gain = speechActive ? 0.18 : 0.14;
    const reduced = createEmptySyntheticGestureOffsets();
    reduced.rootXPercent = clampExpressiveMotionValue(normalized.rootXPercent * gain, -limits.x, limits.x);
    reduced.rootYPercent = clampExpressiveMotionValue(normalized.rootYPercent * gain, -limits.y, limits.y);
    reduced.rootScale = clampExpressiveMotionValue(normalized.rootScale * gain, -limits.scale, limits.scale);
    return reduced;
}

function applyExpressiveChannelLag(targetOffsets, dtSeconds) {
    const target = normalizeSyntheticGestureOffsets(targetOffsets);
    const lagged = normalizeSyntheticGestureOffsets(expressiveMotionLaggedOffsets);
    const safeDtSeconds = Math.max(0.001, Math.min(0.1, Number(dtSeconds) || 0.016));

    Object.entries(EXPRESSIVE_MOTION_LAG_CHANNELS).forEach(([channelName, keys]) => {
        const responseHz = EXPRESSIVE_CHANNEL_RESPONSE_HZ[channelName] || 3.5;
        const damping = 1 - Math.exp(-safeDtSeconds * responseHz);
        keys.forEach((key) => {
            lagged[key] += (target[key] - lagged[key]) * damping;
        });
    });

    expressiveMotionLaggedOffsets = lagged;
    return cloneMotionOffsets(expressiveMotionLaggedOffsets);
}
function createExpressiveAccentMotionState() {
    return {
        activeName: "",
        startedAt: 0,
        durationMs: 0,
        nextCheckAt: 0,
        lastName: "",
        motion: null,
    };
}

function createExpressiveMicroGazeState() {
    return {
        active: false,
        startedAt: 0,
        durationMs: 0,
        nextCheckAt: 0,
        frames: null,
    };
}

function sampleExpressiveAccentKeyframes(frames, t, interpolation = "") {
    if (!Array.isArray(frames) || frames.length === 0) {
        return createEmptySyntheticGestureOffsets();
    }
    if (t <= frames[0].t) {
        return cloneMotionOffsets(frames[0].value);
    }
    for (let index = 1; index < frames.length; index += 1) {
        const previous = frames[index - 1];
        const next = frames[index];
        if (t <= next.t) {
            const span = Math.max(0.0001, next.t - previous.t);
            if (interpolation === "cubic") {
                return interpolateExpressiveAccentOffsetsCubic(frames, index - 1, index, (t - previous.t) / span);
            }
            return interpolateMotionOffsets(previous.value, next.value, (t - previous.t) / span);
        }
    }
    return cloneMotionOffsets(frames[frames.length - 1].value);
}

function pickWeightedExpressiveAccentMotion(speechActive) {
    const candidates = EXPRESSIVE_ACCENT_MOTIONS.filter((motion) => motion.name !== expressiveAccentMotionState.lastName);
    const pool = candidates.length ? candidates : EXPRESSIVE_ACCENT_MOTIONS;
    const weightKey = speechActive ? 'speechWeight' : 'idleWeight';
    const totalWeight = pool.reduce((total, motion) => total + Math.max(0.01, Number(motion[weightKey]) || 1), 0);
    let cursor = Math.random() * totalWeight;
    for (const motion of pool) {
        cursor -= Math.max(0.01, Number(motion[weightKey]) || 1);
        if (cursor <= 0) {
            return motion;
        }
    }
    return pool[0] || EXPRESSIVE_ACCENT_MOTIONS[0];
}

function scheduleNextExpressiveAccentMotion(nowMs, speechActive) {
    const preset = speechActive ? EXPRESSIVE_ACCENT_SCHEDULE.speech : EXPRESSIVE_ACCENT_SCHEDULE.idle;
    expressiveAccentMotionState.nextCheckAt = nowMs + randomBetween(preset.minMs, preset.maxMs);
}

function scheduleNextExpressiveMicroGazeEvent(nowMs, speechActive) {
    const preset = speechActive ? EXPRESSIVE_MICRO_GAZE_SCHEDULE.speech : EXPRESSIVE_MICRO_GAZE_SCHEDULE.idle;
    expressiveMicroGazeState.nextCheckAt = nowMs + randomBetween(preset.minMs, preset.maxMs);
}

function startExpressiveMicroGazeEvent(nowMs, speechActive) {
    const direction = Math.random() < 0.5 ? -1 : 1;
    const target = {
        eyeX: direction * randomBetween(0.032, speechActive ? 0.070 : 0.052),
        eyeY: randomBetween(-0.024, 0.036),
        eyeOpen: -randomBetween(0.006, 0.026),
        eyeSmile: randomBetween(0, 0.025),
    };
    expressiveMicroGazeState.active = true;
    expressiveMicroGazeState.startedAt = nowMs;
    expressiveMicroGazeState.durationMs = randomBetween(speechActive ? 850 : 1050, speechActive ? 1500 : 1900) / expressiveMotionSpeed;
    expressiveMicroGazeState.frames = createExpressiveStagedAccentFrames([
        { t: 0.00, value: {} },
        { t: 0.16, value: { eyeX: target.eyeX * 0.65, eyeY: target.eyeY * 0.55, eyeOpen: target.eyeOpen * 0.45 } },
        { t: 0.34, value: target },
        { t: 0.62, value: { eyeX: target.eyeX * 0.92, eyeY: target.eyeY * 0.82, eyeOpen: target.eyeOpen * 0.62, eyeSmile: target.eyeSmile * 0.70 } },
        { t: 0.80, value: { eyeX: target.eyeX * 0.55, eyeY: target.eyeY * 0.45, eyeOpen: target.eyeOpen * 0.38, eyeSmile: target.eyeSmile * 0.45 } },
        { t: 1.00, value: {} },
    ]);
    expressiveMicroGazeState.nextCheckAt = 0;
    return true;
}

function buildExpressiveMicroGazeOffsets(nowMs, speechActive) {
    if (expressiveMicroGazeState.active && expressiveMicroGazeState.frames) {
        if (!canPlayExpressiveAccentMotion()) {
            expressiveMicroGazeState = createExpressiveMicroGazeState();
            scheduleNextExpressiveMicroGazeEvent(nowMs, speechActive);
            return null;
        }
        const t = Math.max(0, Math.min(1, (nowMs - expressiveMicroGazeState.startedAt) / Math.max(1, expressiveMicroGazeState.durationMs)));
        const offsets = sampleExpressiveAccentKeyframes(expressiveMicroGazeState.frames, t);
        if (t >= 1) {
            expressiveMicroGazeState = createExpressiveMicroGazeState();
            scheduleNextExpressiveMicroGazeEvent(nowMs, speechActive);
        }
        return offsets;
    }

    if (!expressiveMicroGazeState.nextCheckAt) {
        scheduleNextExpressiveMicroGazeEvent(nowMs, speechActive);
        return null;
    }
    if (nowMs < expressiveMicroGazeState.nextCheckAt) {
        return null;
    }

    const preset = speechActive ? EXPRESSIVE_MICRO_GAZE_SCHEDULE.speech : EXPRESSIVE_MICRO_GAZE_SCHEDULE.idle;
    if (canPlayExpressiveAccentMotion() && Math.random() < preset.chance) {
        startExpressiveMicroGazeEvent(nowMs, speechActive);
        return buildExpressiveMicroGazeOffsets(nowMs, speechActive);
    }
    scheduleNextExpressiveMicroGazeEvent(nowMs, speechActive);
    return null;
}


function buildExpressiveTorsoMotionOffsets(motionModeBlend, speechBob, dtSeconds) {
    const softBounce = Math.sin(expressiveMotionPhase * 1.58 + 0.35) * (0.42 + (motionModeBlend * 0.32));
    const softSway = Math.sin(expressiveMotionPhase * 1.08 + 1.8) * (0.36 + (motionModeBlend * 0.18));
    const softCounter = Math.sin(expressiveMotionPhase * 1.92 + 2.4) * (0.22 + (motionModeBlend * 0.24));
    const speechPulse = Math.max(0, Math.min(1.35, speechBob));
    const torsoTargetOffsets = {
        angleX: (softBounce * 0.34) - (speechPulse * 0.28),
        angleY: (softBounce * 0.40) + (speechPulse * 0.88),
        angleZ: (softSway * 0.56) + (softCounter * 0.24),
        bodyY: (softBounce * 0.72) + (speechPulse * 1.05),
        bodyZ: (softSway * 0.64) + (speechPulse * 0.42),
        breath: (softBounce * 0.24) + (speechPulse * 0.52),
        eyeOpen: -speechPulse * 0.018,
    };
    const responseHz = EXPRESSIVE_TORSO_MOTION_RESPONSE_HZ.idle + ((EXPRESSIVE_TORSO_MOTION_RESPONSE_HZ.speech - EXPRESSIVE_TORSO_MOTION_RESPONSE_HZ.idle) * motionModeBlend);
    const damping = 1 - Math.exp(-Math.max(0.001, dtSeconds) * responseHz);
    expressiveTorsoMotionLaggedOffsets = interpolateMotionOffsets(expressiveTorsoMotionLaggedOffsets, torsoTargetOffsets, damping);
    return expressiveTorsoMotionLaggedOffsets;
}
function canPlayExpressiveAccentMotion() {
    if (typeof window.isHeadPatEffectActive === 'function' && window.isHeadPatEffectActive()) {
        return false;
    }
    if (typeof window.isSyntheticGestureActive === 'function' && window.isSyntheticGestureActive()) {
        return false;
    }
    return true;
}

function startExpressiveAccentMotion(nowMs, speechActive) {
    const motion = pickWeightedExpressiveAccentMotion(speechActive);
    if (!motion) {
        return false;
    }
    expressiveAccentMotionState.activeName = motion.name;
    expressiveAccentMotionState.startedAt = nowMs;
    expressiveAccentMotionState.durationMs = Math.max(600, Number(motion.durationMs) || 1800) / expressiveMotionSpeed;
    expressiveAccentMotionState.motion = motion;
    expressiveAccentMotionState.nextCheckAt = 0;
    return true;
}

function buildExpressiveAccentMotionOffsets(nowMs, speechActive) {
    if (expressiveAccentMotionState.activeName && expressiveAccentMotionState.motion) {
        if (!canPlayExpressiveAccentMotion()) {
            expressiveAccentMotionState.lastName = expressiveAccentMotionState.activeName;
            expressiveAccentMotionState.activeName = "";
            expressiveAccentMotionState.motion = null;
            expressiveAccentMotionState.durationMs = 0;
            scheduleNextExpressiveAccentMotion(nowMs, speechActive);
            return null;
        }
        const t = Math.max(0, Math.min(1, (nowMs - expressiveAccentMotionState.startedAt) / Math.max(1, expressiveAccentMotionState.durationMs)));
        const offsets = sampleExpressiveAccentKeyframes(
            expressiveAccentMotionState.motion.frames,
            t,
            expressiveAccentMotionState.motion.interpolation
        );
        if (t >= 1) {
            expressiveAccentMotionState.lastName = expressiveAccentMotionState.activeName;
            expressiveAccentMotionState.activeName = "";
            expressiveAccentMotionState.motion = null;
            expressiveAccentMotionState.durationMs = 0;
            scheduleNextExpressiveAccentMotion(nowMs, speechActive);
        }
        return offsets;
    }

    if (!expressiveAccentMotionState.nextCheckAt) {
        scheduleNextExpressiveAccentMotion(nowMs, speechActive);
        return null;
    }
    if (nowMs < expressiveAccentMotionState.nextCheckAt) {
        return null;
    }

    const preset = speechActive ? EXPRESSIVE_ACCENT_SCHEDULE.speech : EXPRESSIVE_ACCENT_SCHEDULE.idle;
    if (canPlayExpressiveAccentMotion() && Math.random() < preset.chance) {
        startExpressiveAccentMotion(nowMs, speechActive);
        return buildExpressiveAccentMotionOffsets(nowMs, speechActive);
    }
    scheduleNextExpressiveAccentMotion(nowMs, speechActive);
    return null;
}
function randomBetween(minValue, maxValue) {
    return minValue + (Math.random() * (maxValue - minValue));
}

function randomRange(range, fallback) {
    if (!Array.isArray(range) || range.length < 2) {
        return fallback;
    }
    return randomBetween(Number(range[0]) || fallback, Number(range[1]) || fallback);
}

function pickWeightedExpressiveMotionPose(speechActive = false) {
    const preferredNames = speechActive ? EXPRESSIVE_SPEECH_POSE_NAMES : EXPRESSIVE_IDLE_POSE_NAMES;
    const nonRepeatingPoses = EXPRESSIVE_MOTION_POSES.filter((pose) => pose.name !== expressiveMotionLastPoseName);
    const preferredCandidates = nonRepeatingPoses.filter((pose) => preferredNames.has(pose.name));
    const pool = preferredCandidates.length ? preferredCandidates : (nonRepeatingPoses.length ? nonRepeatingPoses : EXPRESSIVE_MOTION_POSES);
    const totalWeight = pool.reduce((total, pose) => total + Math.max(0.01, Number(pose.weight) || 1), 0);
    let cursor = Math.random() * totalWeight;
    for (const pose of pool) {
        cursor -= Math.max(0.01, Number(pose.weight) || 1);
        if (cursor <= 0) {
            return pose;
        }
    }
    return pool[0] || EXPRESSIVE_MOTION_POSES[0];
}
function startNextExpressiveMotionPose(nowMs, speechActive = false) {
    const pose = pickWeightedExpressiveMotionPose(speechActive);
    expressiveMotionLastPoseName = pose.name;
    expressiveMotionFromPose = cloneMotionOffsets(expressiveMotionCurrentPose);
    expressiveMotionTargetPose = cloneMotionOffsets(pose.value);
    expressiveMotionTransitionStartedAt = nowMs;
    expressiveMotionTransitionDurationMs = randomRange(pose.transitionMs, 1800) / expressiveMotionSpeed;
    expressiveMotionHoldUntilMs = nowMs + expressiveMotionTransitionDurationMs + (randomRange(pose.holdMs, 1800) / expressiveMotionSpeed);
}

function easeExpressiveMotionInOut(t) {
    const clamped = Math.max(0, Math.min(1, t));
    return clamped * clamped * (3 - (2 * clamped));
}

function interpolateMotionOffsets(fromOffsets, toOffsets, t) {
    const progress = easeExpressiveMotionInOut(t);
    const from = normalizeSyntheticGestureOffsets(fromOffsets);
    const to = normalizeSyntheticGestureOffsets(toOffsets);
    const interpolated = createEmptySyntheticGestureOffsets();
    Object.keys(interpolated).forEach((key) => {
        interpolated[key] = from[key] + ((to[key] - from[key]) * progress);
    });
    return interpolated;
}

function calculateExpressiveAccentTangent(frames, frameIndex, key, localSpan) {
    if (frameIndex <= 0 || frameIndex >= frames.length - 1) {
        return 0;
    }
    const previousFrame = frames[frameIndex - 1];
    const currentFrame = frames[frameIndex];
    const nextFrame = frames[frameIndex + 1];
    const previousValue = normalizeSyntheticGestureOffsets(previousFrame.value)[key];
    const currentValue = normalizeSyntheticGestureOffsets(currentFrame.value)[key];
    const nextValue = normalizeSyntheticGestureOffsets(nextFrame.value)[key];
    const leftDelta = currentValue - previousValue;
    const rightDelta = nextValue - currentValue;
    if (Math.abs(leftDelta) < 0.000001 && Math.abs(rightDelta) < 0.000001) {
        return 0;
    }
    if (leftDelta !== 0 && rightDelta !== 0 && Math.sign(leftDelta) !== Math.sign(rightDelta)) {
        return 0;
    }
    const timeSpan = Math.max(0.0001, nextFrame.t - previousFrame.t);
    const rawTangent = ((nextValue - previousValue) / timeSpan) * localSpan * 0.72;
    const segmentLimit = Math.max(Math.abs(leftDelta), Math.abs(rightDelta), 0.0001) * 1.35;
    return clampExpressiveMotionValue(rawTangent, -segmentLimit, segmentLimit);
}

function interpolateExpressiveAccentOffsetsCubic(frames, previousIndex, nextIndex, t) {
    const previousFrame = frames[previousIndex];
    const nextFrame = frames[nextIndex];
    const localSpan = Math.max(0.0001, nextFrame.t - previousFrame.t);
    const progress = Math.max(0, Math.min(1, Number(t) || 0));
    const u2 = progress * progress;
    const u3 = u2 * progress;
    const h00 = (2 * u3) - (3 * u2) + 1;
    const h10 = u3 - (2 * u2) + progress;
    const h01 = (-2 * u3) + (3 * u2);
    const h11 = u3 - u2;
    const previous = normalizeSyntheticGestureOffsets(previousFrame.value);
    const next = normalizeSyntheticGestureOffsets(nextFrame.value);
    const interpolated = createEmptySyntheticGestureOffsets();

    Object.keys(interpolated).forEach((key) => {
        const m0 = calculateExpressiveAccentTangent(frames, previousIndex, key, localSpan);
        const m1 = calculateExpressiveAccentTangent(frames, nextIndex, key, localSpan);
        const rawValue = (h00 * previous[key]) + (h10 * m0) + (h01 * next[key]) + (h11 * m1);
        const minValue = Math.min(previous[key], next[key]);
        const maxValue = Math.max(previous[key], next[key]);
        interpolated[key] = clampExpressiveMotionValue(rawValue, minValue, maxValue);
    });
    return interpolated;
}

function buildExpressiveStyleMotionOffsets(nowMs = performance.now(), dtMs = 16) {
    if (!expressiveMotionEnabled) {
        expressiveSpeechEnergySmoothed = 0;
        expressiveSpeechMotionEnergyFiltered = 0;
        expressiveSpeechActivityBlend = 0;
        expressiveMotionLaggedOffsets = createEmptySyntheticGestureOffsets();
        expressiveAccentMotionState = createExpressiveAccentMotionState();
        return null;
    }

    const dtSeconds = Math.max(0, Math.min(0.1, dtMs / 1000));
    const speechActive = isSpeakingNow(nowMs) || (nowMs - expressiveSpeechEnergyUpdatedAt < 260);
    const speechActivityTarget = speechActive ? 1 : 0;
    const speechActivityDamping = 1 - Math.exp(-Math.max(0.001, dtSeconds) * EXPRESSIVE_SPEECH_ACTIVITY_RESPONSE_HZ);
    expressiveSpeechActivityBlend += (speechActivityTarget - expressiveSpeechActivityBlend) * speechActivityDamping;
    const speechPoseMode = speechActive || expressiveSpeechActivityBlend > 0.35;

    if (speechActive && !EXPRESSIVE_SPEECH_POSE_NAMES.has(expressiveMotionLastPoseName) && nowMs + 420 < expressiveMotionHoldUntilMs) {
        expressiveMotionHoldUntilMs = nowMs + 420;
    } else if (!speechActive && expressiveSpeechActivityBlend < 0.25 && !EXPRESSIVE_IDLE_POSE_NAMES.has(expressiveMotionLastPoseName) && nowMs + 700 < expressiveMotionHoldUntilMs) {
        expressiveMotionHoldUntilMs = nowMs + 700;
    }

    if (!expressiveMotionHoldUntilMs || nowMs >= expressiveMotionHoldUntilMs) {
        startNextExpressiveMotionPose(nowMs, speechPoseMode);
    }

    const transitionProgress = Math.max(
        0,
        Math.min(1, (nowMs - expressiveMotionTransitionStartedAt) / Math.max(1, expressiveMotionTransitionDurationMs))
    );
    expressiveMotionCurrentPose = interpolateMotionOffsets(expressiveMotionFromPose, expressiveMotionTargetPose, transitionProgress);

    const motionModeBlend = expressiveSpeechActivityBlend;
    const idleWaveScale = 0.78 - (motionModeBlend * 0.28);
    const speechWaveScale = 1 + (motionModeBlend * 1.05);
    expressiveMotionPhase += dtSeconds * Math.PI * 2 * (0.34 + (motionModeBlend * 0.18)) * expressiveMotionSpeed;

    const speechTarget = speechActive ? Math.max(0, Math.min(1.5, expressiveSpeechEnergyRaw)) : 0;
    const speechDamping = 1 - Math.pow(0.10, Math.max(0.001, dtSeconds) * 10);
    expressiveSpeechEnergySmoothed += (speechTarget - expressiveSpeechEnergySmoothed) * speechDamping;
    const speechMotionDamping = 1 - Math.exp(-Math.max(0.001, dtSeconds) * EXPRESSIVE_SPEECH_MOTION_RESPONSE_HZ);
    expressiveSpeechMotionEnergyFiltered += (expressiveSpeechEnergySmoothed - expressiveSpeechMotionEnergyFiltered) * speechMotionDamping;

    const wave = {
        angleX: (Math.sin(expressiveMotionPhase * 0.63 + 0.4) * 1.05 * idleWaveScale) + (Math.sin(expressiveMotionPhase * 1.42 + 0.7) * 0.35 * motionModeBlend),
        angleY: (Math.sin(expressiveMotionPhase * 1.05 + 1.1) * 1.20 * idleWaveScale) + (Math.sin(expressiveMotionPhase * 1.74 + 0.2) * 0.50 * motionModeBlend),
        angleZ: (Math.sin(expressiveMotionPhase * 0.48 + 2.0) * 0.90 * idleWaveScale) + (Math.sin(expressiveMotionPhase * 1.18 + 1.4) * 0.18 * motionModeBlend),
        bodyX: Math.sin(expressiveMotionPhase * 0.41 + 0.8) * 1.45 * idleWaveScale,
        bodyY: Math.sin(expressiveMotionPhase * 1.22 + 0.2) * 0.88 * speechWaveScale,
        bodyZ: Math.sin(expressiveMotionPhase * 0.37 + 1.7) * 0.90 * idleWaveScale,
        eyeX: Math.sin(expressiveMotionPhase * 0.74 + 1.5) * 0.020 * speechWaveScale,
        eyeY: Math.sin(expressiveMotionPhase * 1.16 + 0.7) * 0.018 * speechWaveScale,
        breath: Math.sin(expressiveMotionPhase * 0.9 + 0.5) * 0.24 * speechWaveScale,
        eyeOpen: Math.sin(expressiveMotionPhase * 0.52 + 0.3) * -0.020 * motionModeBlend,
        eyeSmile: 0,
        rootXPercent: Math.sin(expressiveMotionPhase * 0.31 + 1.2) * 0.22 * (0.70 + (motionModeBlend * 0.10)),
        rootYPercent: (Math.sin(expressiveMotionPhase * 0.57 + 2.2) * 0.16 * idleWaveScale) + (Math.sin(expressiveMotionPhase * 1.05 + 0.4) * 0.18 * motionModeBlend),
        rootScale: (Math.sin(expressiveMotionPhase * 0.44 + 0.6) * 0.0015 * idleWaveScale) + (Math.sin(expressiveMotionPhase * 0.92 + 0.8) * 0.002 * motionModeBlend),
    };
    const speechBob = expressiveSpeechMotionEnergyFiltered * expressiveMotionSpeechBoost;
    const speechOffsets = {
        angleY: speechBob * 1.25,
        bodyY: speechBob * 1.55,
        angleZ: Math.sin(expressiveMotionPhase * 1.6 + 0.3) * speechBob * 0.04,
        breath: speechBob * 0.75,
        eyeOpen: -speechBob * 0.035,
        rootYPercent: -speechBob * 0.08,
        rootScale: speechBob * 0.0012,
    };

    const torsoOffsets = buildExpressiveTorsoMotionOffsets(motionModeBlend, speechBob, dtSeconds);
    const accentOffsets = buildExpressiveAccentMotionOffsets(nowMs, speechActive);
    const microGazeOffsets = buildExpressiveMicroGazeOffsets(nowMs, speechActive);
    const poseOffsets = attenuateExpressiveSpeechLateralPoseOffsets(expressiveMotionCurrentPose, motionModeBlend);
    const combinedMotionOffsets = addMotionOffsets(poseOffsets, wave, speechOffsets, torsoOffsets, accentOffsets, microGazeOffsets);
    const splitMotionOffsets = splitExpressiveMotionOffsets(combinedMotionOffsets);
    const placementOffsets = reduceExpressiveRootMotionOffsets(splitMotionOffsets.placementOffsets, speechActive);
    const rawMotionOffsets = addMotionOffsets(splitMotionOffsets.bodyOffsets, placementOffsets);
    const laggedMotionOffsets = applyExpressiveChannelLag(rawMotionOffsets, dtSeconds);
    return scaleMotionOffsets(laggedMotionOffsets, expressiveMotionStrength);
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
        eyeOpen: finiteOrZero(Number(source.eyeOpen)),
        eyeSmile: finiteOrZero(Number(source.eyeSmile)),
        rootXPercent: finiteOrZero(Number(source.rootXPercent ?? source.rootX)),
        rootYPercent: finiteOrZero(Number(source.rootYPercent ?? source.rootY)),
        rootScale: finiteOrZero(Number(source.rootScale)),
    };
}

window.setSyntheticGestureOffsets = function (offsets = {}) {
    syntheticGestureOffsets = normalizeSyntheticGestureOffsets(offsets);
};

window.clearSyntheticGestureOffsets = function () {
    syntheticGestureOffsets = createEmptySyntheticGestureOffsets();
};

window.setExpressiveMotionConfig = function (enabled, strength = 1.0, speed = 1.0, speechBoost = 1.0) {
    expressiveMotionEnabled = Boolean(enabled);
    expressiveMotionStrength = Number.isFinite(Number(strength))
        ? Math.min(2.5, Math.max(0.2, Number(strength)))
        : 1.0;
    expressiveMotionSpeed = Number.isFinite(Number(speed))
        ? Math.min(2.0, Math.max(0.4, Number(speed)))
        : 1.0;
    expressiveMotionSpeechBoost = Number.isFinite(Number(speechBoost))
        ? Math.min(2.5, Math.max(0, Number(speechBoost)))
        : 1.0;
    if (!expressiveMotionEnabled) {
        expressiveMotionCurrentPose = createEmptySyntheticGestureOffsets();
        expressiveMotionFromPose = createEmptySyntheticGestureOffsets();
        expressiveMotionTargetPose = createEmptySyntheticGestureOffsets();
        expressiveMotionLaggedOffsets = createEmptySyntheticGestureOffsets();
        expressiveMotionHoldUntilMs = 0;
        expressiveAccentMotionState = createExpressiveAccentMotionState();
        expressiveSpeechEnergyRaw = 0;
        expressiveSpeechEnergySmoothed = 0;
        expressiveSpeechMotionEnergyFiltered = 0;
        expressiveSpeechActivityBlend = 0;
    }
    console.log(
        "Expressive-style motion:",
        expressiveMotionEnabled ? "enabled" : "disabled",
        "strength=", expressiveMotionStrength,
        "speed=", expressiveMotionSpeed,
        "speechBoost=", expressiveMotionSpeechBoost
    );
};

window.updateExpressiveSpeechMotionEnergy = function (energy = 0) {
    const numericEnergy = Number(energy);
    expressiveSpeechEnergyRaw = Number.isFinite(numericEnergy) ? Math.max(0, Math.min(1.5, numericEnergy)) : 0;
    expressiveSpeechEnergyUpdatedAt = performance.now();
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
function applyExpressiveExpressionOverlay(coreModel, offsets = null) {
    if (!coreModel || !offsets) {
        return;
    }
    const support = detectHeadPatEyeParams(coreModel);
    const eyeOpen = Math.max(-0.45, Math.min(0.15, finiteOrZero(offsets.eyeOpen)));
    const eyeSmile = Math.max(0, Math.min(0.35, finiteOrZero(offsets.eyeSmile)));
    if (Math.abs(eyeOpen) < 0.001 && eyeSmile < 0.001) {
        return;
    }

    const openMultiplier = Math.max(0.35, Math.min(1.05, 1 + eyeOpen - (eyeSmile * 0.12)));
    if (openMultiplier < 0.999) {
        if (support.eyeLOpen && typeof coreModel.multiplyParameterValueById === 'function') {
            coreModel.multiplyParameterValueById('ParamEyeLOpen', openMultiplier, 1);
        }
        if (support.eyeROpen && typeof coreModel.multiplyParameterValueById === 'function') {
            coreModel.multiplyParameterValueById('ParamEyeROpen', openMultiplier, 1);
        }
    }
    if (eyeSmile > 0.001) {
        if (support.eyeLSquint && typeof coreModel.addParameterValueById === 'function') {
            coreModel.addParameterValueById('ParamEyeLSquint', eyeSmile, 1);
        }
        if (support.eyeRSquint && typeof coreModel.addParameterValueById === 'function') {
            coreModel.addParameterValueById('ParamEyeRSquint', eyeSmile, 1);
        }
    }
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
    return hasHeadPatEffect && shouldUseHeadPatEyeCloseOverride();
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
