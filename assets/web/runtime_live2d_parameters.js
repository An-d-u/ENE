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
    activeTab: 'recommended',
    searchQuery: '',
    panelOpen: false,
    applyHookModel: null,
    hookedInternalModels: new WeakSet(),
};

const LIVE2D_PARAMETER_TABS = ['recommended', 'all', 'pinned'];

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

function normalizeLive2DParameterNumber(value, fallback = 0) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : fallback;
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
        return {
            id: paramId,
            current: value,
            default: defaultValue,
            min: Math.min(rawMin, value, defaultValue),
            max: Math.max(rawMax, value, defaultValue),
            recommended: isRecommendedLive2DParameter(paramId),
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

function resetLive2DParameterOverride(paramId) {
    if (!paramId) {
        return;
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
    renderLive2DParameterInspector();
}

function getVisibleLive2DParameterMetadata() {
    const searchQuery = live2dParameterState.searchQuery.trim().toLowerCase();
    return live2dParameterState.metadata.filter((item) => {
        if (live2dParameterState.activeTab === 'recommended' && !item.recommended) {
            return false;
        }
        if (live2dParameterState.activeTab === 'pinned' && !live2dParameterState.pinned.has(item.id)) {
            return false;
        }
        return !searchQuery || item.id.toLowerCase().includes(searchQuery);
    });
}

function formatLive2DParameterValue(value) {
    return String(Math.round(Number(value) * 1000) / 1000);
}

function updateLive2DParameterRowDirtyState(row, paramId) {
    if (row && row.classList) {
        row.classList.toggle('is-dirty', isLive2DParameterDirty(paramId));
    }
}

function createLive2DParameterRow(item) {
    const row = document.createElement('div');
    row.className = 'live2d-parameter-row';
    updateLive2DParameterRowDirtyState(row, item.id);

    const header = document.createElement('div');
    header.className = 'live2d-parameter-row-header';

    const label = document.createElement('span');
    label.className = 'live2d-parameter-id';
    label.textContent = item.id;

    const pinButton = document.createElement('button');
    pinButton.type = 'button';
    pinButton.className = 'live2d-parameter-pin';
    pinButton.textContent = live2dParameterState.pinned.has(item.id) ? '★' : '☆';
    pinButton.setAttribute('aria-label', `${item.id} 고정`);
    pinButton.addEventListener('click', () => {
        if (live2dParameterState.pinned.has(item.id)) {
            live2dParameterState.pinned.delete(item.id);
        } else {
            live2dParameterState.pinned.add(item.id);
        }
        renderLive2DParameterInspector();
    });

    header.appendChild(label);
    header.appendChild(pinButton);

    const controls = document.createElement('div');
    controls.className = 'live2d-parameter-controls';

    const range = document.createElement('input');
    range.type = 'range';
    range.min = String(item.min);
    range.max = String(item.max);
    range.step = '0.001';
    range.value = String(item.current);
    range.setAttribute('aria-label', `${item.id} 슬라이더`);

    const number = document.createElement('input');
    number.type = 'number';
    number.min = String(item.min);
    number.max = String(item.max);
    number.step = '0.001';
    number.value = formatLive2DParameterValue(item.current);
    number.setAttribute('aria-label', `${item.id} 값`);

    const resetButton = document.createElement('button');
    resetButton.type = 'button';
    resetButton.className = 'live2d-parameter-reset';
    resetButton.textContent = '초기화';
    resetButton.addEventListener('click', () => resetLive2DParameterOverride(item.id));

    const syncValue = (nextValue) => {
        const numericValue = normalizeLive2DParameterNumber(nextValue, item.current);
        range.value = String(numericValue);
        number.value = formatLive2DParameterValue(numericValue);
        setLive2DParameterDirtyValue(item.id, numericValue);
        updateLive2DParameterRowDirtyState(row, item.id);
    };
    range.addEventListener('input', () => syncValue(range.value));
    number.addEventListener('change', () => syncValue(number.value));

    controls.appendChild(range);
    controls.appendChild(number);
    controls.appendChild(resetButton);
    row.appendChild(header);
    row.appendChild(controls);
    return row;
}

function renderLive2DParameterInspector() {
    const live2dParametersList = getLive2DParameterElement('live2d-parameters-list');
    const live2dParametersSearch = getLive2DParameterElement('live2d-parameters-search');
    const live2dParametersResetButton = getLive2DParameterElement('live2d-parameters-reset-btn');
    const live2dParametersSaveButton = getLive2DParameterElement('live2d-parameters-save-btn');
    const ready = live2dParameterState.metadataStatus === 'ready';
    if (live2dParametersSearch) {
        live2dParametersSearch.disabled = !ready;
    }
    if (live2dParametersResetButton) {
        live2dParametersResetButton.disabled = !ready;
    }
    if (live2dParametersSaveButton) {
        live2dParametersSaveButton.disabled = live2dParameterState.metadataStatus !== 'ready';
    }
    if (!live2dParametersList) {
        return;
    }
    if (!ready) {
        const messages = {
            idle: '파라미터 목록을 불러오기 전입니다.',
            loading: '파라미터 목록을 불러오는 중입니다.',
            unavailable: '현재 Live2D 모델에서 파라미터 목록을 읽을 수 없습니다.',
            error: live2dParameterState.metadataError || '파라미터 목록을 불러오지 못했습니다.',
        };
        live2dParametersList.textContent = messages[live2dParameterState.metadataStatus] || messages.idle;
        return;
    }
    if (typeof document === 'undefined' || !document || typeof document.createElement !== 'function') {
        return;
    }
    const visibleItems = getVisibleLive2DParameterMetadata();
    if (typeof live2dParametersList.replaceChildren === 'function') {
        live2dParametersList.replaceChildren();
    } else {
        live2dParametersList.textContent = '';
    }
    if (!visibleItems.length) {
        live2dParametersList.textContent = '표시할 파라미터가 없습니다.';
        return;
    }
    visibleItems.forEach((item) => {
        live2dParametersList.appendChild(createLive2DParameterRow(item));
    });
}

function setLive2DParameterActiveTab(tabName) {
    if (!LIVE2D_PARAMETER_TABS.includes(tabName)) {
        return;
    }
    live2dParameterState.activeTab = tabName;
    LIVE2D_PARAMETER_TABS.forEach((tab) => {
        const tabButton = getLive2DParameterElement(`live2d-parameters-tab-${tab}`);
        const active = tab === tabName;
        if (!tabButton) {
            return;
        }
        tabButton.setAttribute('aria-selected', String(active));
        tabButton.classList.toggle('is-active', active);
    });
    const live2dParametersList = getLive2DParameterElement('live2d-parameters-list');
    if (live2dParametersList) {
        live2dParametersList.setAttribute('aria-labelledby', `live2d-parameters-tab-${tabName}`);
    }
    renderLive2DParameterInspector();
}

function refreshLive2DParameterInspector() {
    setLive2DParameterMetadataStatus('loading');
    renderLive2DParameterInspector();
    try {
        const metadata = collectLive2DParameterMetadata();
        live2dParameterState.metadata = metadata;
        if (!metadata.length) {
            setLive2DParameterMetadataStatus('unavailable');
        } else {
            setLive2DParameterMetadataStatus('ready');
        }
    } catch (error) {
        console.warn('Failed to refresh Live2D parameter inspector:', error);
        live2dParameterState.metadata = [];
        setLive2DParameterMetadataStatus('error', '파라미터 목록을 읽는 중 오류가 발생했습니다.');
    }
    renderLive2DParameterInspector();
}

function setLive2DParameterPanelOpen(open) {
    live2dParameterState.panelOpen = Boolean(open);
    const live2dParametersPanel = getLive2DParameterElement('live2d-parameters-panel');
    if (live2dParametersPanel) {
        live2dParametersPanel.classList.toggle('hidden', !live2dParameterState.panelOpen);
    }
    if (typeof setFloatingActionsOpen === 'function') {
        setFloatingActionsOpen(false);
    }
    if (live2dParameterState.panelOpen) {
        refreshLive2DParameterInspector();
    }
}

function buildLive2DParameterSavePayload() {
    const values = { ...live2dParameterState.values, ...live2dParameterState.dirtyValues };
    live2dParameterState.removedValues.forEach((paramId) => {
        delete values[paramId];
    });
    Object.keys(values).forEach((paramId) => {
        const numericValue = Number(values[paramId]);
        if (!Number.isFinite(numericValue)) {
            delete values[paramId];
        } else {
            values[paramId] = numericValue;
        }
    });
    return {
        values,
        pinned: Array.from(live2dParameterState.pinned),
    };
}

function saveLive2DParameterOverrides() {
    if (live2dParameterState.metadataStatus !== 'ready') {
        showLive2DParameterToast('파라미터 목록을 먼저 불러와야 합니다.', 'error');
        return;
    }
    const modelKey = String(live2dParameterState.modelKey || '').trim();
    if (!modelKey) {
        showLive2DParameterToast('모델을 먼저 선택해야 저장할 수 있습니다.', 'error');
        return;
    }
    if (
        !window.pyBridge
        || typeof window.pyBridge.save_live2d_parameter_overrides !== 'function'
    ) {
        showLive2DParameterToast('저장 브리지를 사용할 수 없습니다.', 'error');
        return;
    }
    const payload = buildLive2DParameterSavePayload();
    try {
        window.pyBridge.save_live2d_parameter_overrides(modelKey, JSON.stringify(payload));
        live2dParameterState.values = { ...payload.values };
        live2dParameterState.dirtyValues = {};
        live2dParameterState.removedValues = new Set();
        live2dParameterState.pinned = new Set(payload.pinned);
        showLive2DParameterToast('Live2D 파라미터를 저장했습니다.', 'success');
        renderLive2DParameterInspector();
    } catch (error) {
        console.warn('Failed to save Live2D parameter overrides:', error);
        showLive2DParameterToast('Live2D 파라미터 저장에 실패했습니다.', 'error');
    }
}

function resetVisibleLive2DParameterOverrides() {
    live2dParameterState.metadata.forEach((item) => {
        if (
            Object.prototype.hasOwnProperty.call(live2dParameterState.values, item.id)
            || Object.prototype.hasOwnProperty.call(live2dParameterState.dirtyValues, item.id)
        ) {
            delete live2dParameterState.values[item.id];
            delete live2dParameterState.dirtyValues[item.id];
            live2dParameterState.removedValues.add(item.id);
            item.current = item.default;
            setLive2DParameterModelValue(item.id, item.default);
        }
    });
    renderLive2DParameterInspector();
}

function bindLive2DParameterEvents() {
    const live2dParametersButton = getLive2DParameterElement('live2d-parameters-floating-btn');
    const live2dParametersCloseButton = getLive2DParameterElement('live2d-parameters-close-btn');
    const live2dParametersSearch = getLive2DParameterElement('live2d-parameters-search');
    const live2dParametersSaveButton = getLive2DParameterElement('live2d-parameters-save-btn');
    const live2dParametersResetButton = getLive2DParameterElement('live2d-parameters-reset-btn');

    if (live2dParametersButton) {
        live2dParametersButton.addEventListener('click', () => {
            setLive2DParameterPanelOpen(!live2dParameterState.panelOpen);
        });
    }

    if (live2dParametersCloseButton) {
        live2dParametersCloseButton.addEventListener('click', () => {
            setLive2DParameterPanelOpen(false);
        });
    }

    if (live2dParametersSearch) {
        live2dParametersSearch.addEventListener('input', () => {
            live2dParameterState.searchQuery = live2dParametersSearch.value || '';
            renderLive2DParameterInspector();
        });
    }

    LIVE2D_PARAMETER_TABS.forEach((tab) => {
        const tabButton = getLive2DParameterElement(`live2d-parameters-tab-${tab}`);
        if (tabButton) {
            tabButton.addEventListener('click', () => setLive2DParameterActiveTab(tab));
        }
    });

    if (live2dParametersSaveButton) {
        live2dParametersSaveButton.addEventListener('click', () => {
            saveLive2DParameterOverrides();
        });
    }

    if (live2dParametersResetButton) {
        live2dParametersResetButton.addEventListener('click', () => {
            resetVisibleLive2DParameterOverrides();
        });
    }
}

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
window.onLive2DParameterModelChanged = function onLive2DParameterModelChanged(config = {}) {
    const nextModelKey = String(config.modelKey || '');
    const modelKeyChanged = live2dParameterState.modelKey !== nextModelKey;
    live2dParameterState.modelKey = nextModelKey;
    live2dParameterState.values = { ...((config.parameterOverrides && config.parameterOverrides.values) || {}) };
    if (modelKeyChanged) {
        live2dParameterState.pinned = new Set((config.parameterOverrides && config.parameterOverrides.pinned) || []);
        live2dParameterState.dirtyValues = {};
        live2dParameterState.removedValues = new Set();
    }
    bindLive2DParameterOverrideHook();
    applyLive2DParameterOverrides();
    if (live2dParameterState.panelOpen) {
        refreshLive2DParameterInspector();
    }
};
