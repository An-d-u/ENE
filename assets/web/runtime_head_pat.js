// 입력 예측과 원격 시각 상태를 분리한다. 원격 상태 적용은 입력 콜백을 호출하지 않는다.
let headPatInput = null;
let headPatInputTimer = null;
let headPatRemote = null;
let headPatObserved = null;

function headPatModelGeneration() {
    return String(characterHost?.currentModel?.() || '');
}

function headPatInteractionId() {
    if (typeof window.crypto?.randomUUID === 'function') return window.crypto.randomUUID();
    if (typeof window.crypto?.getRandomValues !== 'function') return null;
    const bytes = window.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

function postHeadPatInput(input, phase) {
    if (phase !== 'start') input.seq += 1;
    input.sentAt = performance.now(); input.pending = false;
    try {
        return characterHost?.emitInput({type:'head_pat_input', model_generation:input.model,
            interaction_id:input.id, seq:input.seq, phase, intensity:clamp01(patRawIntensity)}) !== false;
    } catch (_) { return false; }
}

function armHeadPatInputTimer() {
    if (!headPatInput || headPatInputTimer !== null) return;
    headPatInputTimer = setTimeout(() => {
        headPatInputTimer = null;
        const input = headPatInput;
        if (!input) return;
        if (!headPatEnabled || input.model !== headPatModelGeneration()) {
            cancelHeadPatInteraction(); return;
        }
        const elapsed = performance.now() - input.sentAt;
        if ((input.pending && elapsed >= 100) || elapsed >= 500) {
            if (!postHeadPatInput(input, 'update')) { cancelHeadPatInteraction(false); return; }
        }
        armHeadPatInputTimer();
    }, 100);
}

function releaseHeadPatInput(sendPhase = null) {
    const input = headPatInput;
    headPatInput = null;
    if (headPatInputTimer !== null) clearTimeout(headPatInputTimer);
    headPatInputTimer = null;
    if (!input) return;
    if (sendPhase) postHeadPatInput(input, sendPhase);
    try { input.target?.releasePointerCapture?.(input.pointerId); } catch (_) { /* 이미 해제된 포인터 */ }
}

function startHeadPatVisual() {
    const restoreBaseEmotion = pendingPatRestoreEmotion || baseEmotionTag || currentEmotionTag || 'normal';
    cancelPendingPatEmotionRestore();
    previousEmotionBeforePat = restoreBaseEmotion;
    if (typeof captureHeadPatGestureCarryover === 'function') captureHeadPatGestureCarryover();
    triggerPatStartEmotion();
    setHeadPatEyeBlinkEnabled(false);
    isHeadPatting = true;
    patRawIntensity = Math.max(patRawIntensity, 0.12);
    patBlendMode = 'in'; patFadeElapsedMs = 0;
}

function finishHeadPatVisual(normal) {
    isHeadPatting = false; headPatPointerId = null;
    patBlendMode = 'out'; patFadeElapsedMs = 0;
    if (normal) triggerPatEndEmotion();
    else {
        cancelPendingPatEmotionRestore();
        changeExpression(previousEmotionBeforePat || baseEmotionTag || 'normal');
        setHeadPatEyeBlinkEnabled(true);
    }
}

function cancelHeadPatInteraction(send = true) {
    releaseHeadPatInput(send ? 'cancel' : null);
    headPatRemote = null;
    if (isHeadPatting || patBlend > 0) finishHeadPatVisual(false);
}

function applyHeadPatState(value) {
    const model = value?.model_generation || value?.model_version;
    if (!headPatEnabled || !model || model !== headPatModelGeneration()) return false;
    const own = value.source === (characterHost?.kind === 'pc' ? 'pc' : 'phone');
    if (own) {
        if (headPatInput?.id === value.interaction_id && ['rejected','cancelled','ended'].includes(value.phase)) {
            releaseHeadPatInput(); finishHeadPatVisual(value.phase === 'ended');
        }
        return true;
    }
    if (!['accepted','update','ended','cancelled','rejected'].includes(value.phase)
        || !Number.isSafeInteger(value.interaction_no) || value.interaction_no < 1
        || !Number.isSafeInteger(value.seq) || value.seq < 0 || !Number.isFinite(value.intensity)) return false;
    const previous = headPatObserved;
    const connection = value.connection_generation || '';
    if (previous && previous.connection === connection && previous.model === model
        && (value.interaction_no < previous.number || (value.interaction_no === previous.number
            && (value.interaction_id !== previous.id || value.seq <= previous.seq)))) return false;
    headPatObserved = {connection, model, number:value.interaction_no, id:value.interaction_id, seq:value.seq};
    if (value.phase === 'accepted') {
        // 상대 입력이 권위를 얻었다. 로컬 예측만 지우고 새 입력을 만들어내지 않는다.
        releaseHeadPatInput();
        if (isHeadPatting) finishHeadPatVisual(false);
        headPatRemote = {connection, model, number:value.interaction_no, id:value.interaction_id};
        startHeadPatVisual();
        patRawIntensity = clamp01(value.intensity);
        return true;
    }
    if (!headPatRemote || headPatRemote.connection !== connection || headPatRemote.model !== model
        || headPatRemote.number !== value.interaction_no || headPatRemote.id !== value.interaction_id) return false;
    if (value.phase === 'update') patRawIntensity = clamp01(value.intensity);
    else if (['ended','cancelled'].includes(value.phase)) {
        headPatRemote = null; finishHeadPatVisual(value.phase === 'ended');
    }
    return true;
}

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

function smoothHeadPatOffsetValue(current, target, maxStep, damping) {
    const desired = lerp(current, target, damping);
    const delta = desired - current;
    const limit = Math.max(0.0001, maxStep);
    return current + Math.max(-limit, Math.min(limit, delta));
}

function updateHeadPatMotionBlend(dtMs) {
    const frameScale = dtMs > 0 ? dtMs / (1000 / 60) : 1;
    const damping = 1 - Math.pow(1 - HEAD_PAT_MOTION_BLEND_DAMPING_AT_60FPS, frameScale);
    const maxStep = HEAD_PAT_MOTION_BLEND_MAX_STEP_AT_60FPS * Math.max(0.25, frameScale);
    const desired = lerp(patMotionBlend, patBlend, damping);
    const delta = desired - patMotionBlend;
    patMotionBlend += Math.max(-maxStep, Math.min(maxStep, delta));
    if (patMotionBlend < 0.001) patMotionBlend = 0;
    if (patMotionBlend > 0.999) patMotionBlend = 1;
    return patMotionBlend;
}

function smoothHeadPatOffsets(targetOffsets, dtMs) {
    const frameScale = dtMs > 0 ? dtMs / (1000 / 60) : 1;
    const damping = 1 - Math.pow(1 - HEAD_PAT_OFFSET_DAMPING_AT_60FPS, frameScale);
    const stepScale = Math.max(0.25, frameScale);
    const target = normalizeSyntheticGestureOffsets(targetOffsets || {});
    const current = normalizeSyntheticGestureOffsets(patOffsetsApplied || {});
    const nextOffsets = createEmptySyntheticGestureOffsets();

    Object.keys(nextOffsets).forEach((key) => {
        const maxStep = finiteOrZero(HEAD_PAT_OFFSET_MAX_STEP_AT_60FPS[key]) || 0.2;
        nextOffsets[key] = smoothHeadPatOffsetValue(
            finiteOrZero(current[key]),
            finiteOrZero(target[key]),
            maxStep * stepScale,
            damping
        );
    });

    patOffsetsApplied = nextOffsets;

    return patOffsetsApplied;
}

function hasMeaningfulHeadPatOffsetDelta(currentOffsets, targetOffsets) {
    const current = normalizeSyntheticGestureOffsets(currentOffsets || {});
    const target = normalizeSyntheticGestureOffsets(targetOffsets || {});
    return Object.keys(current).some((key) => {
        const epsilon = finiteOrZero(HEAD_PAT_OFFSET_SETTLE_EPSILON[key]) || 0.001;
        return Math.abs(finiteOrZero(current[key]) - finiteOrZero(target[key])) > epsilon;
    });
}

function shouldKeepHeadPatMotionActive(hasHeadPatBlend) {
    if (hasHeadPatBlend || isHeadPatting) {
        patMotionReturnActive = true;
        return true;
    }
    if (!patMotionReturnActive) {
        return false;
    }
    if (hasMeaningfulHeadPatOffsetDelta(patOffsetsApplied, lastNonPatTrackingState)) {
        return true;
    }

    patMotionReturnActive = false;
    return false;
}

function updateHeadPatGestureSuppression(hasHeadPatEffect, dtMs) {
    const target = hasHeadPatEffect ? HEAD_PAT_GESTURE_SUPPRESSION_TARGET : 0;
    const frameScale = dtMs > 0 ? dtMs / (1000 / 60) : 1;
    const damping = 1 - Math.pow(1 - HEAD_PAT_GESTURE_SUPPRESSION_DAMPING_AT_60FPS, frameScale);
    headPatGestureSuppression += (target - headPatGestureSuppression) * damping;
    if (headPatGestureSuppression < 0.001) headPatGestureSuppression = 0;
    if (headPatGestureSuppression > 0.999) headPatGestureSuppression = 1;
    if (typeof updateHeadPatGestureCarryover === 'function') {
        updateHeadPatGestureCarryover(hasHeadPatEffect, dtMs);
    }
    return headPatGestureSuppression;
}

// 포인터가 머리 쓰다듬기 유효 영역에 들어왔는지 판정한다.
function isHeadPatPoint(pointerX, pointerY) {
    if (typeof isImageAvatarMode === 'function' && isImageAvatarMode()) {
        const state = window.imageAvatarState || (typeof imageAvatarState !== 'undefined' ? imageAvatarState : null);
        const sprite = state && state.sprite;
        if (!sprite || typeof sprite.getBounds !== 'function') return false;

        try {
            const bounds = sprite.getBounds();
            if (!bounds || !Number.isFinite(bounds.width) || !Number.isFinite(bounds.height)) return false;
            if (bounds.width <= 0 || bounds.height <= 0) return false;
            const minX = bounds.x;
            const maxX = bounds.x + bounds.width;
            const minY = bounds.y;
            const maxY = bounds.y + bounds.height;
            return pointerX >= minX && pointerX <= maxX && pointerY >= minY && pointerY <= maxY;
        } catch (_) {
            return false;
        }
    }

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
    if (!headPatEnabled || isHeadPatting) return;
    if (event.pointerType === 'mouse' && event.button !== 0) return;

    const chatContainer = document.getElementById('chat-container');
    if (chatContainer && chatContainer.contains(event.target)) {
        return;
    }

    if (!isHeadPatPoint(event.clientX, event.clientY)) {
        return;
    }

    const id = headPatInteractionId();
    const model = headPatModelGeneration();
    if (!id || !model) return;
    headPatInput = {id, model, seq:0, sentAt:performance.now(), pending:false, target:event.target, pointerId:event.pointerId};
    startHeadPatVisual();
    headPatPointerId = event.pointerId;
    headPatLastX = event.clientX;
    headPatLastY = event.clientY;
    headPatLastMoveAt = performance.now();
    patRawIntensity = Math.max(patRawIntensity, 0.12);
    patBlendMode = 'in';
    patFadeElapsedMs = 0;
    if (event.target && typeof event.target.setPointerCapture === 'function') {
        try {
            event.target.setPointerCapture(event.pointerId);
        } catch (_) {
        }
    }
    event.preventDefault();
    if (!postHeadPatInput(headPatInput, 'start')) { cancelHeadPatInteraction(false); return; }
    armHeadPatInputTimer();
}

// 쓰다듬기 중 포인터 이동량을 누적해 강도/방향을 계산한다.
function onHeadPatPointerMove(event) {
    if (!isHeadPatting || !headPatEnabled || !headPatInput) return;
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
    headPatInput.pending = true;
    if (nowMs - headPatInput.sentAt >= 100 && !postHeadPatInput(headPatInput, 'update')) cancelHeadPatInteraction(false);
}

// 쓰다듬기 종료 이벤트 처리.
function onHeadPatPointerUp(event) {
    if (!isHeadPatting || !headPatInput) return;
    if (event.pointerId !== headPatPointerId) return;

    releaseHeadPatInput('end');
    finishHeadPatVisual(true);
}

function onHeadPatPointerCancel(event) {
    if (headPatInput && event.pointerId === headPatPointerId) cancelHeadPatInteraction();
}

function onHeadPatBlur() { cancelHeadPatInteraction(); }

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
    let endEmotion = (headPatEndEmotion || 'normal').trim();
    if (!endEmotion) endEmotion = 'normal';
    changeExpression(endEmotion, { durationMs: headPatFadeOutMs });
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
    let activeEmotion = (headPatActiveEmotion || 'normal').trim();
    if (!activeEmotion) activeEmotion = 'normal';
    changeExpression(activeEmotion, { durationMs: headPatFadeInMs });
}

// 포인터 이벤트 리스너를 중복 없이 1회만 바인딩한다.
function ensureHeadPatEventBindings() {
    if (headPatEventsBound) return;

    const canvas = characterCanvas;
    if (!canvas) return;

    canvas.style.touchAction = 'none';
    canvas.addEventListener('pointerdown', onHeadPatPointerDown);
    window.addEventListener('pointermove', onHeadPatPointerMove, { passive: true });
    window.addEventListener('pointerup', onHeadPatPointerUp, { passive: true });
    window.addEventListener('pointercancel', onHeadPatPointerCancel, { passive: true });
    window.addEventListener('blur', onHeadPatBlur);
    headPatEventsBound = true;
}

function removeHeadPatEventBindings() {
    cancelHeadPatInteraction();
    if (!headPatEventsBound) return;
    characterCanvas?.removeEventListener('pointerdown', onHeadPatPointerDown);
    window.removeEventListener('pointermove', onHeadPatPointerMove);
    window.removeEventListener('pointerup', onHeadPatPointerUp);
    window.removeEventListener('pointercancel', onHeadPatPointerCancel);
    window.removeEventListener('blur', onHeadPatBlur);
    headPatEventsBound = false;
}

// 프레임 단위로 쓰다듬기 상태를 감쇠/보간해 갱신한다.
function updateHeadPatState(dtMs) {
    if (!headPatEnabled) {
        resetHeadPatMotionState({ resetPointer: true });
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
    updateHeadPatMotionBlend(dtMs);
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
        breath: 0,
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
