
function isEyeCloseExpressionActive(sample) {
    if (!sample) {
        return false;
    }

    if (sample.fromExpression) {
        const fromEyeCloseActive =
            sample.fromWeight > 0.001 && resolveExpressionEmotion(sample.fromExpression.emotion) === 'eyeclose';
        if (fromEyeCloseActive) {
            return true;
        }
    }

    if (!sample.toExpression) {
        return false;
    }
    return sample.toWeight > 0.001 && resolveExpressionEmotion(sample.toExpression.emotion) === 'eyeclose';
}

function shouldSuspendAutoEyeBlink(sample, hasHeadPatEffect) {
    if (!autoEyeBlinkState.enabled) {
        return true;
    }
    if (hasHeadPatEffect) {
        return true;
    }
    return isEyeCloseExpressionActive(sample);
}

function updateAutoEyeBlinkRuntime(nowMs = performance.now()) {
    if (!autoEyeBlinkState.runtime) {
        resetAutoEyeBlinkRuntime(nowMs);
    }

    const runtime = autoEyeBlinkState.runtime;
    if (runtime.phase === 'idle') {
        if (runtime.nextBlinkAtMs <= 0) {
            scheduleNextAutoEyeBlink(nowMs);
        }
        if (nowMs >= runtime.nextBlinkAtMs) {
            runtime.phase = 'closing';
            runtime.phaseStartedAtMs = nowMs;
        }
        return 1;
    }

    if (runtime.phase === 'closing') {
        const progress = Math.min((nowMs - runtime.phaseStartedAtMs) / Math.max(1, runtime.closeDurationMs), 1.0);
        if (progress >= 1.0) {
            runtime.phase = 'closed';
            runtime.phaseStartedAtMs = nowMs;
            return 0;
        }
        return 1 - progress;
    }

    if (runtime.phase === 'closed') {
        if ((nowMs - runtime.phaseStartedAtMs) >= runtime.closedDurationMs) {
            runtime.phase = 'opening';
            runtime.phaseStartedAtMs = nowMs;
        }
        return 0;
    }

    const progress = Math.min((nowMs - runtime.phaseStartedAtMs) / Math.max(1, runtime.openDurationMs), 1.0);
    if (progress >= 1.0) {
        runtime.phase = 'idle';
        runtime.phaseStartedAtMs = nowMs;
        scheduleNextAutoEyeBlink(nowMs);
        return 1;
    }
    return progress;
}

function applyAutoEyeBlinkToCoreModel(coreModel, sample, hasHeadPatEffect) {
    if (!coreModel || !autoEyeBlinkState.enabled || isUsingBuiltinAutoEyeBlink()) {
        return;
    }

    const support = detectHeadPatEyeParams(coreModel);
    if (!support.eyeLOpen && !support.eyeROpen) {
        return;
    }

    const nowMs = performance.now();
    if (shouldSuspendAutoEyeBlink(sample, hasHeadPatEffect)) {
        resetAutoEyeBlinkRuntime(nowMs);
        return;
    }

    const openValue = updateAutoEyeBlinkRuntime(nowMs);
    if (support.eyeLOpen) coreModel.setParameterValueById('ParamEyeLOpen', openValue);
    if (support.eyeROpen) coreModel.setParameterValueById('ParamEyeROpen', openValue);
}

function createFallbackTrackingOffsets() {
    return typeof createEmptySyntheticGestureOffsets === 'function'
        ? createEmptySyntheticGestureOffsets()
        : { angleX: 0, angleY: 0, bodyX: 0, eyeX: 0, eyeY: 0, breath: 0 };
}

function buildHeadPatOverlayOffsets() {
    if (typeof scaleMotionOffsets === 'function') {
        return scaleMotionOffsets(patOffsetsCurrent, patMotionBlend);
    }
    return {
        angleX: finiteOrZero(patOffsetsCurrent.angleX) * patMotionBlend,
        angleY: finiteOrZero(patOffsetsCurrent.angleY) * patMotionBlend,
        bodyX: finiteOrZero(patOffsetsCurrent.bodyX) * patMotionBlend,
        eyeY: finiteOrZero(patOffsetsCurrent.eyeY) * patMotionBlend,
        breath: finiteOrZero(patOffsetsCurrent.breath) * patMotionBlend,
    };
}

function applyRootMotionOffsets(trackingOffsets, hasHeadPatEffect) {
    if (typeof window.setLive2DRootMotionOffsets !== 'function') {
        return;
    }
    const motionFadeScale = hasHeadPatEffect ? Math.max(0.65, 1 - (patMotionBlend * 0.35)) : 1;
    const fadedTrackingOffsets = motionFadeScale < 0.999 && typeof scaleMotionOffsets === 'function'
        ? scaleMotionOffsets(trackingOffsets, motionFadeScale)
        : trackingOffsets;
    window.setLive2DRootMotionOffsets(fadedTrackingOffsets);
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
    if (typeof resetHeadPatMotionState === 'function') {
        resetHeadPatMotionState();
    }

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
    const hasHeadPatBlend = headPatEnabled && patBlend > 0.001;
    const hasHeadPatEffect = headPatEnabled && shouldKeepHeadPatMotionActive(hasHeadPatBlend);
    updateHeadPatGestureSuppression(hasHeadPatEffect, dtMs);
    const shouldApplyHeadPatEyeOverride = shouldApplyHeadPatEyeOverrideNow(hasHeadPatBlend);

    let idleOffsets = null;
    if (idleMotionEnabled && !isSpeakingNow(nowMs)) {
        idleMotionPhase += dtMs / 1000.0 * Math.PI * 2 * idleMotionSpeedHz;
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
        const breathWave = Math.sin(idleMotionPhase * 1.1 + 0.35);

        idleOffsets = {
            angleX: Math.max(-18, Math.min(18, angleXDynamic)),
            angleY: Math.max(-12, Math.min(12, angleYDynamic)),
            bodyX: Math.max(-10, Math.min(10, bodyXDynamic)),
            breath: Math.max(-1, Math.min(1, breathWave * idleMotionBreath))
        };
    }

    const expressiveOffsets = typeof buildExpressiveStyleMotionOffsets === 'function'
        ? buildExpressiveStyleMotionOffsets(nowMs, dtMs)
        : null;
    const trackingOffsets = typeof addMotionOffsets === 'function'
        ? addMotionOffsets(idleOffsets, expressiveOffsets)
        : (idleOffsets || expressiveOffsets);
    const baseTrackingOffsets = trackingOffsets || createFallbackTrackingOffsets();
    applyRootMotionOffsets(trackingOffsets, hasHeadPatEffect);
    lastNonPatTrackingState = { ...baseTrackingOffsets };
    patOffsetsCurrent = buildHeadPatOffsets(nowMs);
    const patOverlayOffsets = buildHeadPatOverlayOffsets();
    const patOffsetsTarget = typeof addMotionOffsets === 'function'
        ? addMotionOffsets(baseTrackingOffsets, patOverlayOffsets)
        : patOverlayOffsets;
    patOffsetsApplied = typeof smoothHeadPatOffsets === 'function'
        ? smoothHeadPatOffsets(patOffsetsTarget, dtMs)
        : patOffsetsTarget;
    const centerGazeWeight = typeof resolveScreenCenterGazeWeight === 'function'
        ? resolveScreenCenterGazeWeight(currentMouseX, currentMouseY, mouseTrackingEnabled)
        : 1;
    const centerGazeInput = !hasHeadPatEffect && typeof calculateScreenCenterGazeInput === 'function'
        ? calculateScreenCenterGazeInput(window.live2dModel, centerGazeWeight)
        : null;

    try {
        if (hasHeadPatEffect) {
            applyTrackingParams(coreModel, 0, 0, patOffsetsApplied);
            applyIdleBreathParam(coreModel, patOffsetsApplied);
            if (shouldApplyHeadPatEyeOverride) {
                applyHeadPatEyeCloseOverride(coreModel, patBlend);
            }
        } else {
            applyTrackingParams(coreModel, currentMouseX, currentMouseY, trackingOffsets, centerGazeInput);
            applyIdleBreathParam(coreModel, trackingOffsets);
            applyExpressiveExpressionOverlay(coreModel, trackingOffsets);
        }
    } catch (_) {
    }

    requestAnimationFrame(updateMouseTracking);
}
requestAnimationFrame(updateMouseTracking);
console.log("Mouse tracking initialized");
