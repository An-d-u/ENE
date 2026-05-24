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
    let activeEmotion = (headPatActiveEmotion || 'eyeclose').trim();
    if (!activeEmotion) activeEmotion = 'eyeclose';
    changeExpression(activeEmotion, { durationMs: headPatFadeInMs });
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
