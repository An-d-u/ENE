/** PC와 모바일이 함께 사용하는 캐릭터 상태. 문서 하나에 실행부 하나만 소유한다. */
let app = null;
let characterHost = null;
let characterCanvas = null;
let characterDisposed = true;
let characterTrackingFrame = 0;
let characterExpressionGeneration = 0;
const characterExpressionReads = new Set();
window.eneModelConfig = window.eneModelConfig || {};
window.live2dModel = null;

let currentModelPath = '';
let currentEmotionsBasePath = '';
let currentAvailableEmotions = new Set(['normal']);
let currentModelLoadToken = 0;
let currentModelReadyToken = 0;
let currentModelFailedToken = 0;
let currentModelErrorText = null;
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
    return window.eneModelConfig.modelPath || characterHost?.defaultModelPath || '';
}

function resolveEmotionsBasePathFromConfig() {
    if (window.eneModelConfig.emotionsBasePath) {
        return window.eneModelConfig.emotionsBasePath;
    }
    const path = resolveModelPathFromConfig();
    if (!path) return '';
    const absoluteModelUrl = new URL(path, window.location.href);
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
