
// ==========================================
// 립싱크 제어
// ==========================================

/**
 * Live2D 입 벌림 파라미터를 갱신한다.
 */
function setModelParameterValue(paramId, value) {
    const model = window.live2dModel;
    if (!model || !model.internalModel) {
        return false;
    }

    try {
        const core = model.internalModel.coreModel;
        if (core && typeof core.setParameterValueById === 'function') {
            core.setParameterValueById(paramId, value);
        } else if (model.internalModel.setParameterValueById) {
            model.internalModel.setParameterValueById(paramId, value);
        }
        return true;
    } catch (e) {
        window._mouthPoseWarnedParams = window._mouthPoseWarnedParams || {};
        if (!window._mouthPoseWarnedParams[paramId]) {
            console.warn(`${paramId} not available:`, e);
            window._mouthPoseWarnedParams[paramId] = true;
        }
        return false;
    }
}

// 립싱크 시 ParamMouthOpenY 값을 업데이트한다.
function setMouthOpen(value) {
    if (isImageAvatarMode()) {
        applyImageAvatarMouthValue(value);
        return;
    }
    setModelParameterValue('ParamMouthOpenY', value);
}

function clearMouthShapeParameters() {
    setModelParameterValue('ParamJawOpen', 0);
    setModelParameterValue('ParamMouthForm', 0);
    setModelParameterValue('ParamMouthFunnel', 0);
    setModelParameterValue('ParamMouthPuckerWiden', 0);
    setModelParameterValue('ParamTongue', 0);
}

function normalizeMouthPoseNumber(value) {
    return Number.isFinite(value) ? value : 0;
}

function buildVisemeBlendedMouthPose(pose, expressionState) {
    const open = normalizeMouthPoseNumber(Number(pose.open));
    const jaw = normalizeMouthPoseNumber(Number(pose.jaw));
    const form = normalizeMouthPoseNumber(Number(pose.form));
    const funnel = normalizeMouthPoseNumber(Number(pose.funnel));
    const puckerWiden = normalizeMouthPoseNumber(Number(pose.pucker_widen));
    const tongue = normalizeMouthPoseNumber(Number(pose.tongue));

    return {
        open: normalizeMouthPoseNumber(Math.max(open, expressionState.open * 0.35)),
        jaw: normalizeMouthPoseNumber(Math.max(jaw, expressionState.jaw * 0.25)),
        form: normalizeMouthPoseNumber((expressionState.form * 0.7) + (form * 0.6)),
        funnel: normalizeMouthPoseNumber((expressionState.funnel * 0.75) + (funnel * 0.55)),
        puckerWiden: normalizeMouthPoseNumber((expressionState.puckerWiden * 0.75) + (puckerWiden * 0.55)),
        tongue: Math.abs(tongue) > 0.0001 ? tongue : 0,
    };
}

function applyMouthPose(pose) {
    if (!pose || typeof pose !== 'object') {
        return;
    }

    const poseSource = normalizeMouthPoseSource(pose.source);
    const open = normalizeMouthPoseNumber(Number(pose.open));

    if (isImageAvatarMode()) {
        applyImageAvatarMouthValue(open);
        return;
    }

    lastSpeechAt = performance.now();
    mouthExpressionState.source = poseSource;
    mouthExpressionState.lastPoseAt = lastSpeechAt;
    mouthExpressionState.releaseFade.active = false;

    if (poseSource === MOUTH_POSE_SOURCE_RMS) {
        setMouthOpen(open);
        clearMouthShapeParameters();
        return;
    }

    const shapeValues = buildVisemeBlendedMouthPose(pose, mouthExpressionState.expression);

    mouthExpressionState.lastVisemeShape = {
        ...mouthExpressionState.lastVisemeShape,
        form: shapeValues.form,
        funnel: shapeValues.funnel,
        puckerWiden: shapeValues.puckerWiden,
        tongue: shapeValues.tongue,
    };

    applyMouthShapeValues(shapeValues);
}
// Python에서 직접 입 모양을 갱신할 수 있도록 전역에 노출한다.
window.setMouthOpen = setMouthOpen;
window.applyMouthPose = applyMouthPose;

console.log("=== Chat and expression system initialized ===");
console.log("=== Lip sync system ready ===");
