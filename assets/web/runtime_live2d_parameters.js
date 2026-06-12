// Live2D 장식 파라미터 오버라이드 런타임.
const LIVE2D_PARAMETER_RECOMMENDED_EXCLUDE_KEYWORDS = [
    'ParamEye',
    'ParamMouth',
    'ParamJaw',
    'ParamTongue',
    'ParamBrow',
    'ParamAngle',
    'ParamBody',
    'ParamBreath',
    'ParamArm',
    'ParamHand',
    'ParamShoulder',
    'ParamLeg',
];

const live2dParameterState = {
    modelKey: '',
    metadata: [],
    values: {},
    pinned: new Set(),
    dirtyValues: {},
    removedValues: new Set(),
    metadataStatus: 'idle',
    metadataError: '',
    applyHookModel: null,
    hookedInternalModels: new WeakSet(),
};

function getLive2DParameterCoreModel(internalModel = null) {
    if (internalModel && internalModel.coreModel) {
        return internalModel.coreModel;
    }
    const model = window.live2dModel;
    return model && model.internalModel && model.internalModel.coreModel
        ? model.internalModel.coreModel
        : null;
}

function isRecommendedLive2DParameter(paramId) {
    return !LIVE2D_PARAMETER_RECOMMENDED_EXCLUDE_KEYWORDS.some((keyword) => String(paramId || '').startsWith(keyword));
}

function getLive2DParameterOverrideValues() {
    const merged = { ...live2dParameterState.values, ...live2dParameterState.dirtyValues };
    live2dParameterState.removedValues.forEach((paramId) => {
        delete merged[paramId];
    });
    return merged;
}

function applyLive2DParameterOverrides(coreModel = getLive2DParameterCoreModel()) {
    if (!coreModel || typeof coreModel.setParameterValueById !== 'function') {
        return false;
    }
    Object.entries(getLive2DParameterOverrideValues()).forEach(([paramId, value]) => {
        const numericValue = Number(value);
        if (!paramId || !Number.isFinite(numericValue)) {
            return;
        }
        try {
            if (typeof coreModel.getParameterIndex === 'function') {
                const parameterIndex = coreModel.getParameterIndex(paramId);
                if (parameterIndex < 0) {
                    return;
                }
                if (typeof coreModel.getParameterCount === 'function' && parameterIndex >= coreModel.getParameterCount()) {
                    return;
                }
            }
            coreModel.setParameterValueById(paramId, numericValue);
        } catch (error) {
            console.warn(`Failed to apply Live2D parameter override ${paramId}:`, error);
        }
    });
    return true;
}

function bindLive2DParameterOverrideHook() {
    const model = window.live2dModel;
    const internalModel = model && model.internalModel ? model.internalModel : null;
    if (!internalModel || typeof internalModel.on !== 'function') {
        return false;
    }
    if (live2dParameterState.hookedInternalModels.has(internalModel)) {
        live2dParameterState.applyHookModel = internalModel;
        return true;
    }
    const coreModel = getLive2DParameterCoreModel(internalModel);
    internalModel.on('beforeModelUpdate', () => {
        const currentModel = window.live2dModel;
        if (currentModel && currentModel.internalModel === internalModel) {
            applyLive2DParameterOverrides(coreModel);
        }
    });
    live2dParameterState.hookedInternalModels.add(internalModel);
    live2dParameterState.applyHookModel = internalModel;
    return true;
}

window.applyLive2DParameterOverrides = applyLive2DParameterOverrides;
window.onLive2DParameterModelChanged = function onLive2DParameterModelChanged(config = {}) {
    live2dParameterState.modelKey = String(config.modelKey || '');
    live2dParameterState.values = { ...((config.parameterOverrides && config.parameterOverrides.values) || {}) };
    live2dParameterState.pinned = new Set((config.parameterOverrides && config.parameterOverrides.pinned) || []);
    live2dParameterState.dirtyValues = {};
    live2dParameterState.removedValues = new Set();
    bindLive2DParameterOverrideHook();
    applyLive2DParameterOverrides();
};
