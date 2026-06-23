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
    favorites: new Set(),
    dirtyValues: {},
    removedValues: new Set(),
    metadataStatus: 'idle',
    metadataError: '',
    activeTab: 'all',
    searchQuery: '',
    panelOpen: false,
    parameterDisplayInfo: { parameters: {}, groups: {} },
    applyHookModel: null,
    hookedInternalModels: new WeakSet(),
    drag: null,
};

const LIVE2D_PARAMETER_TABS = ['all', 'favorites'];
const LIVE2D_PARAMETER_PANEL_MARGIN = 8;

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

function isLive2DParameterOverrideAllowed(paramId) {
    return isRecommendedLive2DParameter(paramId);
}

function getLive2DParameterElement(id) {
    if (typeof document === 'undefined' || !document || typeof document.getElementById !== 'function') {
        return null;
    }
    return document.getElementById(id);
}

function showLive2DParameterToast(message, level = 'info') {
    if (typeof showToast === 'function') {
        showToast(message, level);
        return;
    }
    if (window.showToast) {
        window.showToast(message, level);
    }
}

function getLive2DParameterUiString(key, fallback) {
    const strings = (window.eneUiStrings && window.eneUiStrings.live2dParameters)
        || (typeof currentUiStrings !== 'undefined' && currentUiStrings && currentUiStrings.live2dParameters)
        || (typeof DEFAULT_UI_STRINGS !== 'undefined' && DEFAULT_UI_STRINGS.live2dParameters)
        || {};
    return strings[key] || fallback;
}

function normalizeLive2DParameterNumber(value, fallback = 0) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : fallback;
}

function normalizeLive2DParameterDisplayInfo(displayInfo) {
    const parameters = displayInfo && typeof displayInfo.parameters === 'object' && displayInfo.parameters
        ? displayInfo.parameters
        : {};
    const groups = displayInfo && typeof displayInfo.groups === 'object' && displayInfo.groups
        ? displayInfo.groups
        : {};
    return { parameters, groups };
}

function getLive2DParameterDisplayInfo(paramId) {
    const displayInfo = live2dParameterState.parameterDisplayInfo || {};
    const parameters = displayInfo.parameters || {};
    const groups = displayInfo.groups || {};
    const item = parameters[paramId] || {};
    const groupId = String(item.groupId || '');
    const group = groups[groupId] || {};
    return {
        displayName: String(item.name || ''),
        groupId,
        groupName: String(item.groupName || group.name || ''),
    };
}

function readLive2DParameterArray(coreModel, names) {
    if (!coreModel) {
        return null;
    }
    const containers = [
        coreModel,
        coreModel.parameters,
        coreModel._model && coreModel._model.parameters,
    ];
    for (const container of containers) {
        if (!container) {
            continue;
        }
        for (const name of names) {
            const value = container[name];
            if (Array.isArray(value) || ArrayBuffer.isView(value)) {
                return value;
            }
        }
    }
    return null;
}

function readLive2DParameterIds(coreModel) {
    if (!coreModel) {
        return [];
    }
    if (typeof coreModel.getParameterIds === 'function') {
        const ids = coreModel.getParameterIds();
        if (Array.isArray(ids) || ArrayBuffer.isView(ids)) {
            return Array.from(ids).map((id) => String(id));
        }
    }
    const ids = readLive2DParameterArray(coreModel, ['ids', 'parameterIds', 'parameterIdsArray']);
    if (ids) {
        return Array.from(ids).map((id) => String(id));
    }
    if (
        typeof coreModel.getParameterCount === 'function'
        && typeof coreModel.getParameterId === 'function'
    ) {
        const count = Number(coreModel.getParameterCount());
        if (!Number.isFinite(count) || count < 1) {
            return [];
        }
        return Array.from({ length: count }, (_, index) => String(coreModel.getParameterId(index)));
    }
    return [];
}

function getLive2DParameterIndex(coreModel, paramId, ids = null) {
    if (!coreModel || !paramId) {
        return -1;
    }
    if (typeof coreModel.getParameterIndex === 'function') {
        try {
            const index = Number(coreModel.getParameterIndex(paramId));
            if (Number.isInteger(index) && index >= 0) {
                return index;
            }
        } catch (error) {
            console.warn(`Failed to read Live2D parameter index ${paramId}:`, error);
        }
    }
    const resolvedIds = ids || readLive2DParameterIds(coreModel);
    return resolvedIds.indexOf(String(paramId));
}

function readLive2DParameterValue(coreModel, paramId, fallback = 0) {
    if (!coreModel || !paramId) {
        return fallback;
    }
    if (typeof coreModel.getParameterValueById === 'function') {
        try {
            return normalizeLive2DParameterNumber(coreModel.getParameterValueById(paramId), fallback);
        } catch (error) {
            console.warn(`Failed to read Live2D parameter value ${paramId}:`, error);
        }
    }
    return readLive2DParameterIndexedValue(
        coreModel,
        paramId,
        ['getParameterValue'],
        ['values', 'parameterValues'],
        fallback,
    );
}

function readLive2DParameterIndexedValue(coreModel, paramId, getterNames, arrayNames, fallback) {
    if (!coreModel || !paramId) {
        return fallback;
    }
    const ids = readLive2DParameterIds(coreModel);
    const index = getLive2DParameterIndex(coreModel, paramId, ids);
    for (const getterName of getterNames) {
        const getter = coreModel[getterName];
        if (typeof getter !== 'function') {
            continue;
        }
        try {
            const directValue = getter.call(coreModel, paramId);
            if (Number.isFinite(Number(directValue))) {
                return Number(directValue);
            }
        } catch (error) {
            console.warn(`Failed to read Live2D parameter ${getterName} by id ${paramId}:`, error);
        }
        if (index >= 0) {
            try {
                const indexedValue = getter.call(coreModel, index);
                if (Number.isFinite(Number(indexedValue))) {
                    return Number(indexedValue);
                }
            } catch (error) {
                console.warn(`Failed to read Live2D parameter ${getterName} by index ${index}:`, error);
            }
        }
    }
    const values = readLive2DParameterArray(coreModel, arrayNames);
    if (values && index >= 0 && index < values.length) {
        return normalizeLive2DParameterNumber(values[index], fallback);
    }
    return fallback;
}

function collectLive2DParameterMetadata() {
    const coreModel = getLive2DParameterCoreModel();
    const ids = readLive2DParameterIds(coreModel);
    return ids.map((paramId) => {
        const value = readLive2DParameterValue(coreModel, paramId, 0);
        const defaultValue = readLive2DParameterIndexedValue(
            coreModel,
            paramId,
            ['getParameterDefaultValue'],
            ['defaultValues', 'defaults', 'parameterDefaultValues'],
            value,
        );
        const rawMin = readLive2DParameterIndexedValue(
            coreModel,
            paramId,
            ['getParameterMinimumValue'],
            ['minimumValues', 'minValues', 'mins', 'parameterMinimumValues'],
            Math.min(value, defaultValue, -1),
        );
        const rawMax = readLive2DParameterIndexedValue(
            coreModel,
            paramId,
            ['getParameterMaximumValue'],
            ['maximumValues', 'maxValues', 'maxes', 'parameterMaximumValues'],
            Math.max(value, defaultValue, 1),
        );
        const displayInfo = getLive2DParameterDisplayInfo(paramId);
        return {
            id: paramId,
            current: value,
            default: defaultValue,
            min: Math.min(rawMin, value, defaultValue),
            max: Math.max(rawMax, value, defaultValue),
            recommended: isRecommendedLive2DParameter(paramId),
            displayName: displayInfo.displayName,
            groupId: displayInfo.groupId,
            groupName: displayInfo.groupName,
        };
    });
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
        if (!paramId || !Number.isFinite(numericValue) || !isLive2DParameterOverrideAllowed(paramId)) {
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

function setLive2DParameterMetadataStatus(status, message = '') {
    const normalizedStatus = ['idle', 'loading', 'ready', 'unavailable', 'error'].includes(status)
        ? status
        : 'error';
    live2dParameterState.metadataStatus = normalizedStatus;
    live2dParameterState.metadataError = String(message || '');
    const live2dParametersSaveButton = getLive2DParameterElement('live2d-parameters-save-btn');
    if (live2dParametersSaveButton) {
        live2dParametersSaveButton.disabled = live2dParameterState.metadataStatus !== 'ready';
    }
}

function setLive2DParameterModelValue(paramId, value) {
    if (!isLive2DParameterOverrideAllowed(paramId)) {
        return false;
    }
    const coreModel = getLive2DParameterCoreModel();
    if (!coreModel || typeof coreModel.setParameterValueById !== 'function') {
        return false;
    }
    try {
        coreModel.setParameterValueById(paramId, value);
        return true;
    } catch (error) {
        console.warn(`Failed to set Live2D parameter ${paramId}:`, error);
        return false;
    }
}

function getLive2DParameterMetadata(paramId) {
    return live2dParameterState.metadata.find((item) => item.id === paramId) || null;
}

function isLive2DParameterDirty(paramId) {
    return Object.prototype.hasOwnProperty.call(live2dParameterState.dirtyValues, paramId)
        || live2dParameterState.removedValues.has(paramId);
}

function setLive2DParameterDirtyValue(paramId, value) {
    const metadata = getLive2DParameterMetadata(paramId);
    if (!metadata || !isLive2DParameterOverrideAllowed(paramId)) {
        return;
    }
    const numericValue = normalizeLive2DParameterNumber(value, metadata ? metadata.current : 0);
    const baseline = Object.prototype.hasOwnProperty.call(live2dParameterState.values, paramId)
        ? normalizeLive2DParameterNumber(live2dParameterState.values[paramId], numericValue)
        : normalizeLive2DParameterNumber(metadata ? metadata.default : numericValue, numericValue);
    live2dParameterState.removedValues.delete(paramId);
    if (Math.abs(numericValue - baseline) < 0.0001) {
        delete live2dParameterState.dirtyValues[paramId];
    } else {
        live2dParameterState.dirtyValues[paramId] = numericValue;
    }
    if (metadata) {
        metadata.current = numericValue;
    }
    setLive2DParameterModelValue(paramId, numericValue);
}

function resetLive2DParameterOverrideState(paramId) {
    if (!paramId) {
        return false;
    }
    const metadata = getLive2DParameterMetadata(paramId);
    delete live2dParameterState.dirtyValues[paramId];
    delete live2dParameterState.values[paramId];
    live2dParameterState.removedValues.add(paramId);
    const defaultValue = metadata ? metadata.default : 0;
    if (metadata) {
        metadata.current = defaultValue;
    }
    setLive2DParameterModelValue(paramId, defaultValue);
    return true;
}

function resetLive2DParameterOverride(paramId) {
    if (!resetLive2DParameterOverrideState(paramId)) {
        return;
    }
    renderLive2DParameterInspector();
}
