let live2dRootMotionOffsets = { rootXPercent: 0, rootYPercent: 0, rootScale: 0 };

function clampLive2DRootMotionValue(value, minValue, maxValue) {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) {
        return 0;
    }
    return Math.max(minValue, Math.min(maxValue, numericValue));
}

function normalizeLive2DRootMotionOffsets(offsets = {}) {
    const source = offsets || {};
    return {
        rootXPercent: clampLive2DRootMotionValue(source.rootXPercent ?? source.rootX, -12, 12),
        rootYPercent: clampLive2DRootMotionValue(source.rootYPercent ?? source.rootY, -8, 8),
        rootScale: clampLive2DRootMotionValue(source.rootScale, -0.08, 0.18),
    };
}

window.setLive2DRootMotionOffsets = function (offsets = {}) {
    live2dRootMotionOffsets = normalizeLive2DRootMotionOffsets(offsets);
    applyCurrentModelPlacement();
};
function removeCurrentModelArtifacts() {
    detachExpressionUpdateHook();
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
    builtinAutoMotionState.running = false;
    builtinAutoMotionState.breath = null;
    builtinAutoMotionState.physics = null;
    autoEyeBlinkState.builtinInstance = null;
    autoEyeBlinkState.runtime = null;
    resetExpressionTransitionState();
}

function getBuiltinInternalModel(model) {
    if (!model || !model.internalModel) {
        return null;
    }
    return model.internalModel;
}

function getBuiltinIdleMotionManager(model) {
    const internalModel = getBuiltinInternalModel(model);
    if (!internalModel) {
        return null;
    }
    return internalModel.motionManager || null;
}

function captureBuiltinEyeBlinkInstance(model = window.live2dModel) {
    const internalModel = getBuiltinInternalModel(model);
    if (!internalModel) {
        return false;
    }

    if (internalModel.eyeBlink && !autoEyeBlinkState.builtinInstance) {
        autoEyeBlinkState.builtinInstance = internalModel.eyeBlink;
    }
    return Boolean(autoEyeBlinkState.builtinInstance);
}

function syncBuiltinAutoMotionComponent(internalModel, propertyName, enabled) {
    if (!internalModel) {
        return false;
    }

    if (enabled) {
        if (builtinAutoMotionState[propertyName]) {
            internalModel[propertyName] = builtinAutoMotionState[propertyName];
        }
        return true;
    }

    if (internalModel[propertyName]) {
        builtinAutoMotionState[propertyName] = internalModel[propertyName];
    }
    internalModel[propertyName] = null;
    return true;
}

// Cubism 런타임이 기본으로 넣는 breath 움직임을 보관하거나 복원한다.
function syncBuiltinNaturalBreath(enabled, internalModel = getBuiltinInternalModel(window.live2dModel)) {
    return syncBuiltinAutoMotionComponent(internalModel, 'breath', enabled);
}

// 기본 자동 움직임 구성요소(숨쉬기, 눈깜빡임, 물리)를 보관하거나 복원한다.
function syncBuiltinAutoMotionComponents(enabled) {
    const internalModel = getBuiltinInternalModel(window.live2dModel);
    if (!internalModel) {
        return false;
    }

    syncBuiltinNaturalBreath(enabled, internalModel);
    syncBuiltinAutoMotionComponent(internalModel, 'physics', enabled);
    return true;
}

function resetAutoEyeBlinkRuntime(nowMs = performance.now()) {
    autoEyeBlinkState.runtime = createAutoEyeBlinkRuntimeState();
    autoEyeBlinkState.runtime.phaseStartedAtMs = nowMs;
    scheduleNextAutoEyeBlink(nowMs);
}

function scheduleNextAutoEyeBlink(nowMs = performance.now()) {
    if (!autoEyeBlinkState.runtime) {
        autoEyeBlinkState.runtime = createAutoEyeBlinkRuntimeState();
    }

    const runtime = autoEyeBlinkState.runtime;
    const intervalSpan = Math.max(0, runtime.maxIntervalMs - runtime.minIntervalMs);
    runtime.nextBlinkAtMs = nowMs + runtime.minIntervalMs + (Math.random() * intervalSpan);
}

function isUsingBuiltinAutoEyeBlink() {
    return autoEyeBlinkState.enabled && builtinAutoMotionState.enabled && Boolean(autoEyeBlinkState.builtinInstance);
}

function syncAutoEyeBlinkMode(model = window.live2dModel) {
    const internalModel = getBuiltinInternalModel(model);
    if (!internalModel) {
        return false;
    }

    captureBuiltinEyeBlinkInstance(model);
    if (isUsingBuiltinAutoEyeBlink()) {
        internalModel.eyeBlink = autoEyeBlinkState.builtinInstance;
        resetAutoEyeBlinkRuntime();
        return true;
    }

    internalModel.eyeBlink = null;
    resetAutoEyeBlinkRuntime();
    return true;
}

// 런타임이 자동으로 기본 Idle을 다시 예약하지 못하도록 idle 그룹 자체를 제어한다.
function syncBuiltinIdleMotionGroup(enabled) {
    const model = window.live2dModel;
    const motionManager = getBuiltinIdleMotionManager(model);
    if (!motionManager || !motionManager.groups) {
        return false;
    }

    const currentIdleGroup = motionManager.groups.idle;
    if (
        enabled &&
        currentIdleGroup &&
        currentIdleGroup !== BUILTIN_IDLE_GROUP_DISABLED &&
        typeof currentIdleGroup === 'string'
    ) {
        builtinAutoMotionState.idleGroupName = currentIdleGroup;
    }

    if (enabled) {
        motionManager.groups.idle = builtinAutoMotionState.idleGroupName;
        return true;
    }

    if (
        currentIdleGroup &&
        currentIdleGroup !== BUILTIN_IDLE_GROUP_DISABLED &&
        typeof currentIdleGroup === 'string'
    ) {
        builtinAutoMotionState.idleGroupName = currentIdleGroup;
    }
    motionManager.groups.idle = BUILTIN_IDLE_GROUP_DISABLED;
    return true;
}

function applyBuiltinAutoMotionState(enabled) {
    syncBuiltinIdleMotionGroup(enabled);
    syncBuiltinAutoMotionComponents(enabled);
}

function stopBuiltinIdleMotion() {
    const model = window.live2dModel;
    const motionManager = getBuiltinIdleMotionManager(model);
    builtinAutoMotionState.running = false;

    applyBuiltinAutoMotionState(false);
    syncAutoEyeBlinkMode(model);

    if (!motionManager) {
        return true;
    }

    const stopCandidates = [
        () => motionManager.stopAllMotions?.(),
        () => motionManager._stopAllMotions?.(),
        () => motionManager.queueManager?.stopAllMotions?.()
    ];

    for (const stop of stopCandidates) {
        try {
            stop();
            console.log('Built-in Live2D idle motion stopped');
            return true;
        } catch (error) {
            console.warn('Failed to stop built-in idle motion via candidate:', error);
        }
    }

    return false;
}

function startBuiltinIdleMotion() {
    const model = window.live2dModel;
    if (!builtinAutoMotionState.enabled || !model) {
        builtinAutoMotionState.running = false;
        return false;
    }

    const motionManager = getBuiltinIdleMotionManager(model);
    if (!motionManager) {
        syncBuiltinAutoMotionComponents(true);
        syncAutoEyeBlinkMode(model);
        builtinAutoMotionState.running = false;
        return false;
    }

    applyBuiltinAutoMotionState(true);
    syncAutoEyeBlinkMode(model);

    if (builtinAutoMotionState.running) {
        stopBuiltinIdleMotion();
        applyBuiltinAutoMotionState(true);
    }

    try {
        model.motion('Idle');
        builtinAutoMotionState.running = true;
        console.log('Built-in Live2D idle motion started');
        return true;
    } catch (error) {
        builtinAutoMotionState.running = false;
        console.warn('Failed to start built-in idle motion:', error);
        return false;
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
    const rootOffsets = normalizeLive2DRootMotionOffsets(live2dRootMotionOffsets);
    const resolvedScale = Math.max(0.05, scale * (1 + rootOffsets.rootScale));
    const resolvedXPercent = xPercent + rootOffsets.rootXPercent;
    const resolvedYPercent = yPercent + rootOffsets.rootYPercent;

    model.anchor.set(0.5, 0.5);
    model.scale.set(resolvedScale);
    model.x = window.innerWidth * (resolvedXPercent / 100);
    model.y = window.innerHeight * (resolvedYPercent / 100);
}

window.applyENEModelSettings = async function applyENEModelSettings(config) {
    window.eneModelConfig = { ...(window.eneModelConfig || {}), ...(config || {}) };

    const nextModelPath = resolveModelPathFromConfig();
    const nextEmotionsBasePath = resolveEmotionsBasePathFromConfig();
    syncAvailableEmotionsFromConfig();

    if (isImageAvatarMode()) {
        currentModelLoadToken++;
        removeCurrentModelArtifacts();
        currentModelPath = '';
        currentEmotionsBasePath = '';
        applyImageAvatarSettings(window.eneModelConfig);
        if (typeof syncLive2DParameterVisibilityForAvatarMode === 'function') {
            syncLive2DParameterVisibilityForAvatarMode();
        }
        return;
    }

    removeImageAvatarArtifacts();
    if (typeof syncLive2DParameterVisibilityForAvatarMode === 'function') {
        syncLive2DParameterVisibilityForAvatarMode();
    }

    if (nextModelPath !== currentModelPath) {
        currentModelPath = nextModelPath;
        currentEmotionsBasePath = nextEmotionsBasePath;
        await loadModel();
        return;
    }

    currentEmotionsBasePath = nextEmotionsBasePath;
    applyCurrentModelPlacement();
    if (typeof window.onLive2DParameterModelChanged === 'function') {
        window.onLive2DParameterModelChanged(window.eneModelConfig);
    }
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
        if (isImageAvatarMode()) {
            removeCurrentModelArtifacts();
            currentModelPath = '';
            currentEmotionsBasePath = '';
            applyImageAvatarSettings(window.eneModelConfig);
            if (typeof syncLive2DParameterVisibilityForAvatarMode === 'function') {
                syncLive2DParameterVisibilityForAvatarMode();
            }
            return;
        }
        removeImageAvatarArtifacts();
        removeCurrentModelArtifacts();
        console.log("Calling PIXI.live2d.Live2DModel.from()...");
        const model = await PIXI.live2d.Live2DModel.from(modelPath);
        if (isImageAvatarMode()) {
            if (typeof model.destroy === 'function') {
                model.destroy();
            }
            return;
        }

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
        captureBuiltinEyeBlinkInstance(model);
        resetAutoEyeBlinkRuntime();
        attachExpressionUpdateHook(model);
        applyCurrentModelPlacement();

        console.log(`Model positioned at (${model.x}, ${model.y}) with scale ${model.scale.x}`);
        if (model.internalModel && model.internalModel.motionManager) {
            console.log("Motion manager available");
            if (builtinAutoMotionState.enabled) {
                startBuiltinIdleMotion();
            } else {
                applyBuiltinAutoMotionState(false);
                syncAutoEyeBlinkMode(model);
            }
        } else {
            console.log("No motion manager found");
            if (!builtinAutoMotionState.enabled) {
                syncBuiltinAutoMotionComponents(false);
            }
            syncAutoEyeBlinkMode(model);
        }
        if (model.internalModel && model.internalModel.eyeBlink) {
            console.log("Eye blink enabled");
        }
        window.live2dModel = model;

        console.log("=== Model setup complete ===\n");
        if (typeof window.onLive2DParameterModelChanged === 'function') {
            window.onLive2DParameterModelChanged(window.eneModelConfig);
        }

    } catch (error) {
        if (requestToken !== currentModelLoadToken || isImageAvatarMode()) {
            return;
        }
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
    if (isImageAvatarMode()) {
        applyImageAvatarPlacement();
    }
    if (chatPanelHeightPx !== null) {
        applyChatPanelHeight(chatPanelHeightPx);
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
