// Live2D 장식 파라미터 런타임 진입점.
bindLive2DParameterEvents();

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
window.getLive2DParameterInspectorSnapshot = getLive2DParameterInspectorSnapshot;
window.setLive2DParameterInspectorValue = setLive2DParameterInspectorValue;
window.setLive2DParameterInspectorFavorite = setLive2DParameterInspectorFavorite;
window.setLive2DParameterInspectorPinned = setLive2DParameterInspectorFavorite;
window.resetLive2DParameterInspectorValue = resetLive2DParameterInspectorValue;
window.resetLive2DParameterInspectorValues = resetLive2DParameterInspectorValues;
window.saveLive2DParameterInspectorOverrides = saveLive2DParameterInspectorOverrides;
window.syncLive2DParameterVisibilityForAvatarMode = syncLive2DParameterVisibilityForAvatarMode;

function readLive2DParameterFavorites(parameterOverrides) {
    if (parameterOverrides && Array.isArray(parameterOverrides.favorites)) {
        return parameterOverrides.favorites;
    }
    if (parameterOverrides && Array.isArray(parameterOverrides.pinned)) {
        return parameterOverrides.pinned;
    }
    return [];
}

window.onLive2DParameterModelChanged = function onLive2DParameterModelChanged(config = {}) {
    syncLive2DParameterVisibilityForAvatarMode();
    const nextModelKey = String(config.modelKey || '');
    const modelKeyChanged = live2dParameterState.modelKey !== nextModelKey;
    const parameterOverrides = config.parameterOverrides || {};
    live2dParameterState.modelKey = nextModelKey;
    live2dParameterState.parameterDisplayInfo = normalizeLive2DParameterDisplayInfo(config.parameterDisplayInfo);
    live2dParameterState.values = { ...(parameterOverrides.values || {}) };
    if (modelKeyChanged) {
        live2dParameterState.favorites = new Set(readLive2DParameterFavorites(parameterOverrides));
        live2dParameterState.dirtyValues = {};
        live2dParameterState.removedValues = new Set();
    }
    bindLive2DParameterOverrideHook();
    applyLive2DParameterOverrides();
    if (live2dParameterState.panelOpen) {
        refreshLive2DParameterInspector();
    }
};
