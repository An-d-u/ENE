
// ==========================================
// 감정 표정 제어
// ==========================================
/**
 * 현재 표정 전환 애니메이션 상태.
 */
const expressionRuntimeState = {
    boundModel: null,
    updateHook: null,
    definitionCache: new Map(),
    transition: null
};

function createEmptyExpressionDefinition(emotion = 'normal') {
    return {
        emotion,
        parameters: []
    };
}

function createEmptyExpressionTransition() {
    return {
        from: null,
        to: createEmptyExpressionDefinition('normal'),
        startedAtMs: 0,
        durationMs: 0
    };
}

function resetExpressionTransitionState() {
    expressionRuntimeState.transition = createEmptyExpressionTransition();
}

function detachExpressionUpdateHook() {
    const internalModel = expressionRuntimeState.boundModel && expressionRuntimeState.boundModel.internalModel;
    if (internalModel && expressionRuntimeState.updateHook && typeof internalModel.off === 'function') {
        internalModel.off('beforeModelUpdate', expressionRuntimeState.updateHook);
    }
    expressionRuntimeState.boundModel = null;
    expressionRuntimeState.updateHook = null;
}

function attachExpressionUpdateHook(model) {
    detachExpressionUpdateHook();

    const internalModel = model && model.internalModel;
    if (!internalModel || typeof internalModel.on !== 'function') {
        return false;
    }

    expressionRuntimeState.updateHook = () => {
        applyCurrentExpressionState();
    };
    internalModel.on('beforeModelUpdate', expressionRuntimeState.updateHook);
    expressionRuntimeState.boundModel = model;
    return true;
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

function normalizeExpressionBlend(blend) {
    const normalized = String(blend || 'Add').trim().toLowerCase();
    if (normalized === 'multiply') {
        return 'multiply';
    }
    if (normalized === 'overwrite') {
        return 'overwrite';
    }
    return 'add';
}

function normalizeExpressionDefinition(emotion, expressionData) {
    const rawParams = Array.isArray(expressionData && expressionData.Parameters)
        ? expressionData.Parameters
        : [];

    return {
        emotion,
        parameters: rawParams
            .map((param) => ({
                id: String(param && param.Id ? param.Id : '').trim(),
                value: Number.isFinite(Number(param && param.Value)) ? Number(param.Value) : 0,
                blend: normalizeExpressionBlend(param.Blend)
            }))
            .filter((param) => param.id)
    };
}

async function loadExpressionDefinition(emotion) {
    const resolvedEmotion = resolveExpressionEmotion(emotion);
    if (!resolvedEmotion || resolvedEmotion === 'normal') {
        return createEmptyExpressionDefinition('normal');
    }

    const expressionPath = new URL(`${resolvedEmotion}.exp3.json`, currentEmotionsBasePath).href;
    const cached = expressionRuntimeState.definitionCache.get(expressionPath);
    if (cached) {
        return cached;
    }

    const response = await fetch(expressionPath);
    if (!response.ok) {
        throw new Error(`Expression HTTP ${response.status}: ${expressionPath}`);
    }

    const expressionData = await response.json();
    const normalizedExpression = normalizeExpressionDefinition(resolvedEmotion, expressionData);
    expressionRuntimeState.definitionCache.set(expressionPath, normalizedExpression);
    return normalizedExpression;
}

function getCurrentExpressionTransition() {
    if (!expressionRuntimeState.transition) {
        expressionRuntimeState.transition = createEmptyExpressionTransition();
    }
    return expressionRuntimeState.transition;
}

function sampleExpressionTransition(nowMs = performance.now()) {
    const transition = getCurrentExpressionTransition();
    const fromExpression = transition.from;
    const toExpression = transition.to || createEmptyExpressionDefinition('normal');
    const duration = Math.max(0, Number(transition.durationMs) || 0);
    if (duration <= 0) {
        return {
            fromExpression,
            toExpression,
            fromWeight: 0,
            toWeight: 1,
            complete: true
        };
    }

    const elapsed = Math.max(0, nowMs - (transition.startedAtMs || nowMs));
    const progress = Math.min(elapsed / duration, 1.0);
    const fadeOutWeight = fromExpression ? (1 - Math.pow(progress, 3)) : 0;
    const fadeInWeight = 1 - Math.pow(1 - progress, 3);

    return {
        fromExpression,
        toExpression,
        fromWeight: fadeOutWeight,
        toWeight: fadeInWeight,
        complete: progress >= 1.0
    };
}

function settleExpressionTransition(sample = sampleExpressionTransition()) {
    expressionRuntimeState.transition = {
        from: null,
        to: sample.toExpression || createEmptyExpressionDefinition('normal'),
        startedAtMs: performance.now(),
        durationMs: 0
    };
}

function resolveExpressionTransitionDuration(resolvedEmotion, requestedDurationMs) {
    if (requestedDurationMs !== null) {
        return requestedDurationMs;
    }
    return resolvedEmotion === 'normal' ? 300 : 500;
}

function setExpressionTransition(nextExpression, durationMs) {
    const sampledState = sampleExpressionTransition();
    expressionRuntimeState.transition = {
        from: sampledState.toExpression || createEmptyExpressionDefinition('normal'),
        to: nextExpression,
        startedAtMs: performance.now(),
        durationMs: durationMs
    };
}

function applyExpressionLayer(coreModel, expression, weight) {
    if (!coreModel || !expression || !Array.isArray(expression.parameters) || weight <= 0.0001) {
        return;
    }

    expression.parameters.forEach((param) => {
        try {
            if (isMouthExpressionParam(param.id)) {
                cacheExpressionMouthValue(param.id, param.value, weight, param.blend);
                if (shouldHoldExpressionMouthParams()) {
                    return;
                }
            }
            if (param.blend === 'multiply') {
                coreModel.multiplyParameterValueById(param.id, param.value, weight);
                return;
            }
            if (param.blend === 'overwrite') {
                coreModel.setParameterValueById(param.id, param.value, weight);
                return;
            }
            coreModel.addParameterValueById(param.id, param.value, weight);
        } catch (error) {
            console.warn(`Failed to apply expression parameter ${param.id}:`, error);
        }
    });
}

function applyCurrentExpressionState() {
    const model = window.live2dModel;
    const coreModel = model && model.internalModel && model.internalModel.coreModel;
    if (!coreModel) {
        return;
    }

    const nowMs = performance.now();
    resetExpressionMouthCache();
    const sample = sampleExpressionTransition(nowMs);
    applyExpressionLayer(coreModel, sample.fromExpression, sample.fromWeight);
    applyExpressionLayer(coreModel, sample.toExpression, sample.toWeight);
    updateMouthExpressionReleaseFade(coreModel, nowMs);
    applyAutoEyeBlinkToCoreModel(coreModel, sample, headPatEnabled && patBlend > 0.001);

    if (sample.complete) {
        settleExpressionTransition(sample);
    }
}

// 감정 태그에 맞는 exp3 표정 파일을 로드/보간 적용한다.
async function changeExpression(emotion, options = {}) {
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
        const durationMs = Number.isFinite(options.durationMs)
            ? Math.max(0, Number(options.durationMs))
            : null;
        const nextExpression = await loadExpressionDefinition(resolvedEmotion);
        const transitionDurationMs = resolveExpressionTransitionDuration(resolvedEmotion, durationMs);
        setExpressionTransition(nextExpression, transitionDurationMs);
        if (transitionDurationMs <= 0) {
            settleExpressionTransition({
                toExpression: nextExpression
            });
        }
        console.log(`Expression changing to: ${resolvedEmotion}`);
    } catch (error) {
        console.error(`Failed to load expression ${resolvedEmotion}:`, error);
    }
}
