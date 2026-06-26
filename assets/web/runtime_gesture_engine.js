// ==========================================
// 합성 Live2D 제스처 엔진
// ==========================================
const GESTURE_INTENSITY = 1.0;
const GESTURE_SPEED = 0.75;
const SPEECH_GESTURE_MIN_DELAY_MS = 700;
const SPEECH_GESTURE_MAX_DELAY_MS = 3200;
const SPEECH_GESTURE_FALLBACK_DELAY_MS = 700;
const SPEECH_GESTURE_ECHO_THRESHOLDS_MS = [3800, 7200, 11200];
const SPEECH_GESTURE_ECHO_ACTIVITY_GRACE_MS = 900;
const SPEECH_GESTURE_ECHO_RETRY_MS = 340;
const SPEECH_GESTURE_ECHO_MIN_GAP_MS = 1700;
const SPEECH_GESTURE_ECHO_SCALES = [0.58, 0.48, 0.40];
const SPEECH_GESTURE_ECHO_LIMITS = {
    nod: 3,
    tilt: 2,
    bow: 2,
    sway: 2,
    shake: 1,
    surprise: 1,
};
const IDLE_SYNTHETIC_GESTURE_FREQUENCIES = {
    low: { minMs: 20000, maxMs: 45000 },
    normal: { minMs: 12000, maxMs: 28000 },
    high: { minMs: 7000, maxMs: 16000 },
};
const IDLE_SYNTHETIC_GESTURES = ["idle-look-around", "idle-tiny-nod", "idle-cute-tilt", "idle-settle"];
const IDLE_SYNTHETIC_GESTURE_SPEECH_GRACE_MS = 1800;
const IDLE_SYNTHETIC_GESTURE_FINISH_COOLDOWN_MS = 3000;
let activeGestureFrame = 0;
let activeGestureKey = "";
let pendingSpeechGestureKey = "";
let pendingSpeechGestureTimer = 0;
let pendingSpeechGestureFallbackTimer = 0;
let currentSpeechGestureKey = "";
let speechGestureActivityStartedAt = 0;
let speechGesturePrimaryPlayed = false;
let speechGestureEchoCount = 0;
let speechGestureEchoTimer = 0;
let speechGestureInactivityTimer = 0;
let lastSpeechGestureEchoAt = 0;
let syntheticGestureScale = 1.0;
let idleSyntheticGestureEnabled = false;
let idleSyntheticGestureFrequency = "normal";
let idleSyntheticGestureTimer = 0;
let lastSyntheticSpeechActivityAt = 0;
let lastSyntheticGestureFinishedAt = 0;

function easeGestureInOut(t) {
    const clamped = Math.max(0, Math.min(1, t));
    return clamped * clamped * (3 - (2 * clamped));
}

function gestureEnvelope(t) {
    if (t <= 0.08) {
        return easeGestureInOut(t / 0.08);
    }
    if (t >= 0.88) {
        return 1 - easeGestureInOut((t - 0.88) / 0.12);
    }
    return 1;
}

function scaleGestureOffsets(offsets, scale) {
    const scaled = {};
    Object.keys(offsets || {}).forEach((key) => {
        scaled[key] = Number(offsets[key] || 0) * scale * GESTURE_INTENSITY * syntheticGestureScale;
    });
    return scaled;
}

function setSyntheticGestureScale(scale) {
    const numericScale = Number(scale);
    syntheticGestureScale = Number.isFinite(numericScale) ? Math.max(0.5, Math.min(3.0, numericScale)) : 1.0;
    return syntheticGestureScale;
}

function sampleKeyframes(frames, t) {
    if (!frames.length) {
        return {};
    }
    if (t <= frames[0].t) {
        return frames[0].value;
    }
    for (let index = 1; index < frames.length; index += 1) {
        const previous = frames[index - 1];
        const next = frames[index];
        if (t <= next.t) {
            const span = Math.max(0.0001, next.t - previous.t);
            const localT = easeGestureInOut((t - previous.t) / span);
            const value = {};
            const keys = new Set([...Object.keys(previous.value), ...Object.keys(next.value)]);
            keys.forEach((key) => {
                const fromValue = Number(previous.value[key] || 0);
                const toValue = Number(next.value[key] || 0);
                value[key] = fromValue + ((toValue - fromValue) * localT);
            });
            return value;
        }
    }
    return frames[frames.length - 1].value;
}

const SYNTHETIC_GESTURES = {
    nod: {
        durationMs: 1180,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.16, value: { angleY: -13, bodyY: -1.2, eyeY: -0.2 } },
            { t: 0.34, value: { angleY: 9, bodyY: 0.8, eyeY: 0.12 } },
            { t: 0.50, value: { angleY: -10, bodyY: -1.0, eyeY: -0.15 } },
            { t: 0.68, value: { angleY: 7, bodyY: 0.6, eyeY: 0.1 } },
            { t: 1.00, value: {} },
        ],
    },
    bow: {
        durationMs: 1680,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.24, value: { angleY: -17, bodyY: -3.0, eyeY: -0.35 } },
            { t: 0.70, value: { angleY: -18, bodyY: -3.2, eyeY: -0.38 } },
            { t: 1.00, value: {} },
        ],
    },
    shake: {
        durationMs: 1480,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.17, value: { angleX: -15, angleZ: 1.4, bodyX: -0.45, eyeX: -0.18 } },
            { t: 0.34, value: { angleX: 15, angleZ: -1.4, bodyX: 0.45, eyeX: 0.18 } },
            { t: 0.51, value: { angleX: -14, angleZ: 1.2, bodyX: -0.35, eyeX: -0.15 } },
            { t: 0.68, value: { angleX: 14, angleZ: -1.2, bodyX: 0.35, eyeX: 0.15 } },
            { t: 1.00, value: {} },
        ],
    },
    surprise: {
        durationMs: 1260,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.10, value: { angleY: 20, bodyY: 4.2, eyeY: 0.45, breath: 0.7 } },
            { t: 0.24, value: { angleY: 11, bodyY: 2.0, eyeY: 0.22, breath: 0.3 } },
            { t: 0.58, value: { angleY: 10, bodyY: 1.8, eyeY: 0.18 } },
            { t: 1.00, value: {} },
        ],
    },
    tilt: {
        durationMs: 1520,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.24, value: { angleX: -7, angleY: 4, angleZ: -15, bodyX: -0.8, eyeX: 0.12 } },
            { t: 0.60, value: { angleX: -8, angleY: 5, angleZ: -16, bodyX: -0.8, eyeX: 0.14 } },
            { t: 0.78, value: { angleX: -4, angleY: 3, angleZ: -9, bodyX: -0.35, eyeX: 0.08 } },
            { t: 1.00, value: {} },
        ],
    },
    sway: {
        durationMs: 2480,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.16, value: { angleX: -8, angleZ: -4, bodyX: -7.0, bodyZ: -2.5 } },
            { t: 0.32, value: { angleX: 8, angleZ: 4, bodyX: 7.0, bodyZ: 2.5 } },
            { t: 0.48, value: { angleX: -8, angleZ: -4, bodyX: -7.0, bodyZ: -2.5 } },
            { t: 0.64, value: { angleX: 8, angleZ: 4, bodyX: 7.0, bodyZ: 2.5 } },
            { t: 1.00, value: {} },
        ],
    },
    "idle-look-around": {
        durationMs: 1500,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.28, value: { angleX: -8, eyeX: -0.28 } },
            { t: 0.58, value: { angleX: 8, eyeX: 0.28 } },
            { t: 1.00, value: {} },
        ],
    },
    "idle-tiny-nod": {
        durationMs: 1200,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.36, value: { angleY: -7, eyeY: -0.12 } },
            { t: 0.68, value: { angleY: 5, eyeY: 0.08 } },
            { t: 1.00, value: {} },
        ],
    },
    "idle-cute-tilt": {
        durationMs: 1600,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.38, value: { angleX: -6, angleZ: -11, eyeX: 0.12 } },
            { t: 0.72, value: { angleX: -5, angleZ: -9, eyeX: 0.08 } },
            { t: 1.00, value: {} },
        ],
    },
    "idle-settle": {
        durationMs: 1400,
        frames: [
            { t: 0.00, value: {} },
            { t: 0.35, value: { bodyY: -0.8, breath: 0.2 } },
            { t: 0.70, value: { bodyY: 0.4, breath: 0.1 } },
            { t: 1.00, value: {} },
        ],
    },
};

const GESTURE_ALIASES = {
    yes: "nod",
    no: "shake",
    sad: "bow",
    confused: "tilt",
    happy: "nod",
    angry: "shake",
};

function normalizeSyntheticGestureKey(rawKey) {
    const requestedKey = String(rawKey || "").trim().toLowerCase().replace("_", "-");
    return GESTURE_ALIASES[requestedKey] || requestedKey;
}

function clearSyntheticGestureEchoTimer() {
    if (speechGestureEchoTimer) {
        clearTimeout(speechGestureEchoTimer);
        speechGestureEchoTimer = 0;
    }
}

function clearSyntheticGestureInactivityTimer() {
    if (speechGestureInactivityTimer) {
        clearTimeout(speechGestureInactivityTimer);
        speechGestureInactivityTimer = 0;
    }
}

function resetSyntheticSpeechGestureSession() {
    currentSpeechGestureKey = "";
    speechGestureActivityStartedAt = 0;
    speechGesturePrimaryPlayed = false;
    speechGestureEchoCount = 0;
    lastSpeechGestureEchoAt = 0;
    clearSyntheticGestureEchoTimer();
    clearSyntheticGestureInactivityTimer();
}

function clearPendingSyntheticSpeechGesture() {
    pendingSpeechGestureKey = "";
    if (pendingSpeechGestureTimer) {
        clearTimeout(pendingSpeechGestureTimer);
        pendingSpeechGestureTimer = 0;
    }
    if (pendingSpeechGestureFallbackTimer) {
        clearTimeout(pendingSpeechGestureFallbackTimer);
        pendingSpeechGestureFallbackTimer = 0;
    }
}

function playPendingSyntheticSpeechGesture() {
    const gestureKey = pendingSpeechGestureKey;
    clearPendingSyntheticSpeechGesture();
    if (!gestureKey) {
        return false;
    }
    const played = playSyntheticGesture(gestureKey, { clearPending: false });
    if (played) {
        currentSpeechGestureKey = gestureKey;
        speechGesturePrimaryPlayed = true;
    }
    return played;
}

function queuePendingSyntheticSpeechGesture(delayMs) {
    if (!pendingSpeechGestureKey || pendingSpeechGestureTimer) {
        return false;
    }
    const normalizedDelayMs = Math.max(0, Number(delayMs) || 0);
    pendingSpeechGestureTimer = setTimeout(function () {
        pendingSpeechGestureTimer = 0;
        playPendingSyntheticSpeechGesture();
    }, normalizedDelayMs);
    return true;
}

function scheduleSyntheticGestureDuringSpeech(rawKey) {
    const requestedKey = normalizeSyntheticGestureKey(rawKey);
    if (!requestedKey || !SYNTHETIC_GESTURES[requestedKey] || IDLE_SYNTHETIC_GESTURES.includes(requestedKey)) {
        return false;
    }

    clearPendingSyntheticSpeechGesture();
    resetSyntheticSpeechGestureSession();
    pendingSpeechGestureKey = requestedKey;
    currentSpeechGestureKey = requestedKey;
    pendingSpeechGestureFallbackTimer = setTimeout(function () {
        pendingSpeechGestureFallbackTimer = 0;
        queuePendingSyntheticSpeechGesture(0);
    }, SPEECH_GESTURE_FALLBACK_DELAY_MS);
    return true;
}

function getSyntheticGestureEchoLimit(key) {
    return Math.max(0, Number(SPEECH_GESTURE_ECHO_LIMITS[key] ?? 2) || 0);
}

function getSyntheticGestureEchoScale(index) {
    const scale = SPEECH_GESTURE_ECHO_SCALES[Math.max(0, index)] ?? SPEECH_GESTURE_ECHO_SCALES[SPEECH_GESTURE_ECHO_SCALES.length - 1];
    return Math.max(0.25, Math.min(0.75, Number(scale) || 0.45));
}

function playSyntheticGestureEchoIfReady() {
    speechGestureEchoTimer = 0;
    if (!currentSpeechGestureKey || !speechGesturePrimaryPlayed) {
        return false;
    }
    const nowMs = performance.now();
    if (nowMs - lastSyntheticSpeechActivityAt > SPEECH_GESTURE_ECHO_ACTIVITY_GRACE_MS) {
        return false;
    }
    if (activeGestureKey) {
        speechGestureEchoTimer = setTimeout(playSyntheticGestureEchoIfReady, SPEECH_GESTURE_ECHO_RETRY_MS);
        return true;
    }
    const echoLimit = getSyntheticGestureEchoLimit(currentSpeechGestureKey);
    if (speechGestureEchoCount >= echoLimit) {
        return false;
    }
    const scale = getSyntheticGestureEchoScale(speechGestureEchoCount);
    speechGestureEchoCount += 1;
    lastSpeechGestureEchoAt = nowMs;
    return playSyntheticGesture(currentSpeechGestureKey, { scale, clearPending: false });
}

function queueSyntheticGestureEcho(delayMs) {
    if (speechGestureEchoTimer || !currentSpeechGestureKey || !speechGesturePrimaryPlayed) {
        return false;
    }
    const normalizedDelayMs = Math.max(0, Number(delayMs) || 0);
    speechGestureEchoTimer = setTimeout(playSyntheticGestureEchoIfReady, normalizedDelayMs);
    return true;
}

function maybeScheduleSyntheticGestureEcho(nowMs) {
    if (!currentSpeechGestureKey || !speechGesturePrimaryPlayed || pendingSpeechGestureKey || pendingSpeechGestureTimer) {
        return false;
    }
    const echoLimit = getSyntheticGestureEchoLimit(currentSpeechGestureKey);
    if (speechGestureEchoCount >= echoLimit || speechGestureEchoTimer) {
        return false;
    }
    const startedAt = speechGestureActivityStartedAt || nowMs;
    const elapsedMs = nowMs - startedAt;
    const thresholdMs = SPEECH_GESTURE_ECHO_THRESHOLDS_MS[speechGestureEchoCount] || SPEECH_GESTURE_ECHO_THRESHOLDS_MS[SPEECH_GESTURE_ECHO_THRESHOLDS_MS.length - 1];
    if (elapsedMs < thresholdMs) {
        return false;
    }
    if (lastSpeechGestureEchoAt && nowMs - lastSpeechGestureEchoAt < SPEECH_GESTURE_ECHO_MIN_GAP_MS) {
        return false;
    }
    const delayMs = 260 + (Math.random() * 780);
    return queueSyntheticGestureEcho(delayMs);
}

function scheduleSyntheticGestureSpeechInactivityReset() {
    clearSyntheticGestureInactivityTimer();
    speechGestureInactivityTimer = setTimeout(function () {
        speechGestureInactivityTimer = 0;
        if (performance.now() - lastSyntheticSpeechActivityAt > SPEECH_GESTURE_ECHO_ACTIVITY_GRACE_MS) {
            resetSyntheticSpeechGestureSession();
        }
    }, SPEECH_GESTURE_ECHO_ACTIVITY_GRACE_MS + 80);
}

function notifySyntheticGestureSpeechActivity() {
    const nowMs = performance.now();
    lastSyntheticSpeechActivityAt = nowMs;
    if (!speechGestureActivityStartedAt && (currentSpeechGestureKey || pendingSpeechGestureKey)) {
        speechGestureActivityStartedAt = nowMs;
    }
    scheduleSyntheticGestureSpeechInactivityReset();
    if (IDLE_SYNTHETIC_GESTURES.includes(activeGestureKey)) {
        stopSyntheticGesture({ clearPending: false });
    }
    if (!pendingSpeechGestureKey || pendingSpeechGestureTimer) {
        return maybeScheduleSyntheticGestureEcho(nowMs);
    }
    if (pendingSpeechGestureFallbackTimer) {
        clearTimeout(pendingSpeechGestureFallbackTimer);
        pendingSpeechGestureFallbackTimer = 0;
    }
    const delayMs = SPEECH_GESTURE_MIN_DELAY_MS + (Math.random() * (SPEECH_GESTURE_MAX_DELAY_MS - SPEECH_GESTURE_MIN_DELAY_MS));
    return queuePendingSyntheticSpeechGesture(delayMs);
}

function isSyntheticGestureActive() {
    return Boolean(activeGestureKey || pendingSpeechGestureKey || pendingSpeechGestureTimer || pendingSpeechGestureFallbackTimer || speechGestureEchoTimer);
}
function stopSyntheticGesture(options = {}) {
    const hadActiveGesture = Boolean(activeGestureKey);
    if (options.clearPending !== false) {
        clearPendingSyntheticSpeechGesture();
        resetSyntheticSpeechGestureSession();
    }
    activeGestureKey = "";
    if (activeGestureFrame) {
        cancelAnimationFrame(activeGestureFrame);
        activeGestureFrame = 0;
    }
    if (typeof window.clearSyntheticGestureOffsets === "function") {
        window.clearSyntheticGestureOffsets();
    }
    if (hadActiveGesture) {
        lastSyntheticGestureFinishedAt = performance.now();
    }
}

function clearIdleSyntheticGestureTimer() {
    if (idleSyntheticGestureTimer) {
        clearTimeout(idleSyntheticGestureTimer);
        idleSyntheticGestureTimer = 0;
    }
}

function normalizeIdleSyntheticGestureFrequency(frequency) {
    const key = String(frequency || "normal").trim().toLowerCase();
    return IDLE_SYNTHETIC_GESTURE_FREQUENCIES[key] ? key : "normal";
}

function canPlayIdleSyntheticGesture() {
    if (!idleSyntheticGestureEnabled) {
        return false;
    }
    if (activeGestureKey || pendingSpeechGestureKey || pendingSpeechGestureTimer || pendingSpeechGestureFallbackTimer || speechGestureEchoTimer) {
        return false;
    }
    if (typeof window.setSyntheticGestureOffsets !== "function") {
        return false;
    }
    if (typeof window.isHeadPatEffectActive === "function" && window.isHeadPatEffectActive()) {
        return false;
    }
    const nowMs = performance.now();
    if (nowMs - lastSyntheticSpeechActivityAt < IDLE_SYNTHETIC_GESTURE_SPEECH_GRACE_MS) {
        return false;
    }
    if (nowMs - lastSyntheticGestureFinishedAt < IDLE_SYNTHETIC_GESTURE_FINISH_COOLDOWN_MS) {
        return false;
    }
    return true;
}

function pickIdleSyntheticGesture() {
    const index = Math.floor(Math.random() * IDLE_SYNTHETIC_GESTURES.length);
    return IDLE_SYNTHETIC_GESTURES[index] || "idle-look-around";
}

function scheduleNextIdleSyntheticGesture() {
    clearIdleSyntheticGestureTimer();
    if (!idleSyntheticGestureEnabled) {
        return false;
    }
    const preset = IDLE_SYNTHETIC_GESTURE_FREQUENCIES[idleSyntheticGestureFrequency] || IDLE_SYNTHETIC_GESTURE_FREQUENCIES.normal;
    const delayMs = preset.minMs + (Math.random() * (preset.maxMs - preset.minMs));
    idleSyntheticGestureTimer = setTimeout(function () {
        idleSyntheticGestureTimer = 0;
        if (canPlayIdleSyntheticGesture()) {
            playSyntheticGesture(pickIdleSyntheticGesture());
        }
        scheduleNextIdleSyntheticGesture();
    }, delayMs);
    return true;
}

function setIdleSyntheticGestureConfig(enabled, frequency) {
    idleSyntheticGestureEnabled = Boolean(enabled);
    idleSyntheticGestureFrequency = normalizeIdleSyntheticGestureFrequency(frequency);
    clearIdleSyntheticGestureTimer();
    if (!idleSyntheticGestureEnabled && IDLE_SYNTHETIC_GESTURES.includes(activeGestureKey)) {
        stopSyntheticGesture({ clearPending: false });
    }
    if (idleSyntheticGestureEnabled) {
        scheduleNextIdleSyntheticGesture();
    }
    return { enabled: idleSyntheticGestureEnabled, frequency: idleSyntheticGestureFrequency };
}

function playSyntheticGesture(rawKey, options = {}) {
    const key = normalizeSyntheticGestureKey(rawKey);
    const gesture = SYNTHETIC_GESTURES[key];
    if (!gesture || typeof window.setSyntheticGestureOffsets !== "function") {
        return false;
    }
    if (typeof window.isHeadPatEffectActive === "function" && window.isHeadPatEffectActive()) {
        return false;
    }

    stopSyntheticGesture({ clearPending: options.clearPending !== false });
    activeGestureKey = key;
    const startedAt = performance.now();
    const durationMs = Math.max(300, Number(gesture.durationMs / GESTURE_SPEED) || (1000 / GESTURE_SPEED));
    const instanceScale = Math.max(0.1, Math.min(1.25, Number(options.scale) || 1.0));
    const clearPendingOnFinish = options.clearPending !== false;

    const tick = (nowMs) => {
        if (activeGestureKey !== key) {
            return;
        }
        if (typeof window.isHeadPatEffectActive === "function" && window.isHeadPatEffectActive()) {
            stopSyntheticGesture({ clearPending: clearPendingOnFinish });
            return;
        }
        const t = Math.max(0, Math.min(1, (nowMs - startedAt) / durationMs));
        const offsets = scaleGestureOffsets(sampleKeyframes(gesture.frames, t), gestureEnvelope(t) * instanceScale);
        window.setSyntheticGestureOffsets(offsets);
        if (t >= 1) {
            stopSyntheticGesture({ clearPending: clearPendingOnFinish });
            return;
        }
        activeGestureFrame = requestAnimationFrame(tick);
    };

    activeGestureFrame = requestAnimationFrame(tick);
    return true;
}

window.playSyntheticGesture = playSyntheticGesture;
window.scheduleSyntheticGestureDuringSpeech = scheduleSyntheticGestureDuringSpeech;
window.notifySyntheticGestureSpeechActivity = notifySyntheticGestureSpeechActivity;
window.setSyntheticGestureScale = setSyntheticGestureScale;
window.setIdleSyntheticGestureConfig = setIdleSyntheticGestureConfig;
window.stopSyntheticGesture = stopSyntheticGesture;
window.isSyntheticGestureActive = isSyntheticGestureActive;
