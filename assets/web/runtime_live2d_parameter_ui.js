// Live2D 장식 파라미터 UI 런타임.
// PC 전용 편집 기준이다. 로컬 경로와 Qt 저장 API는 모바일 실행부에 포함하지 않는다.
const live2dParameterEdit = { baseline: null, status: 'idle', message: '', nonce: 0, timer: null, generation: '' };

function resetLive2DParameterEdit() {
    live2dParameterEdit.nonce += 1;
    if (live2dParameterEdit.timer !== null) window.clearTimeout(live2dParameterEdit.timer);
    Object.assign(live2dParameterEdit, { baseline: null, status: 'idle', message: '', timer: null });
}

function parseLive2DParameterReply(raw) {
    if (typeof raw !== 'string' || raw.length > 65536) throw new Error('invalid_reply');
    const reply = JSON.parse(raw);
    if (!reply || typeof reply !== 'object' || Array.isArray(reply)) throw new Error('invalid_reply');
    return reply;
}

function validLive2DParameterBaseline(value) {
    return value && value.model_key === live2dParameterState.modelKey
        && typeof value.generation === 'string'
        && Number.isSafeInteger(value.settings_revision) && value.settings_revision >= 0
        && value.payload && value.payload.values && typeof value.payload.values === 'object'
        && !Array.isArray(value.payload.values) && Array.isArray(value.payload.favorites);
}

function parameterEditBusy() {
    return ['loading', 'saving'].includes(live2dParameterEdit.status);
}

function requestLive2DParameterEdit(invoke, receive, saving) {
    const nonce = ++live2dParameterEdit.nonce;
    live2dParameterEdit.status = saving ? 'saving' : 'loading';
    const fail = (unknown) => {
        live2dParameterEdit.status = unknown ? 'unknown' : 'baseline_error';
        live2dParameterEdit.message = unknown
            ? '저장 결과를 확인하지 못했습니다. 새로고침으로 현재 저장값을 확인해 주세요.'
            : '저장 기준을 읽지 못했습니다. 새로고침 후 다시 시도해 주세요.';
        if (saving) showLive2DParameterToast(live2dParameterEdit.message, 'error');
        renderLive2DParameterInspector();
    };
    live2dParameterEdit.timer = window.setTimeout(() => {
        if (nonce !== live2dParameterEdit.nonce) return;
        live2dParameterEdit.nonce += 1;
        window.clearTimeout(live2dParameterEdit.timer);
        live2dParameterEdit.timer = null;
        fail(saving);
    }, 10000);
    try {
        invoke((raw) => {
            if (nonce !== live2dParameterEdit.nonce) return;
            live2dParameterEdit.nonce += 1;
            window.clearTimeout(live2dParameterEdit.timer);
            live2dParameterEdit.timer = null;
            try { receive(parseLive2DParameterReply(raw)); } catch (_error) { fail(saving); }
            renderLive2DParameterInspector();
        });
    } catch (_error) {
        if (nonce === live2dParameterEdit.nonce) {
            live2dParameterEdit.nonce += 1;
            window.clearTimeout(live2dParameterEdit.timer);
            live2dParameterEdit.timer = null;
            fail(saving);
        }
    }
}

function ensureLive2DParameterEdit() {
    if (live2dParameterEdit.baseline || live2dParameterEdit.status !== 'idle'
        || !live2dParameterState.modelKey || !window.pyBridge
        || typeof window.pyBridge.get_live2d_parameter_edit_snapshot !== 'function') return;
    requestLive2DParameterEdit((done) => window.pyBridge.get_live2d_parameter_edit_snapshot(live2dParameterState.modelKey, done), (value) => {
        if (!validLive2DParameterBaseline(value)) throw new Error('invalid_baseline');
        live2dParameterEdit.baseline = value;
        live2dParameterEdit.status = 'idle';
        live2dParameterState.values = { ...value.payload.values };
    }, false);
}

if (typeof window.addEventListener === 'function') window.addEventListener('pagehide', resetLive2DParameterEdit);

function getVisibleLive2DParameterMetadata() {
    const searchQuery = live2dParameterState.searchQuery.trim().toLowerCase();
    return live2dParameterState.metadata.filter((item) => {
        if (live2dParameterState.activeTab === 'favorites' && !live2dParameterState.favorites.has(item.id)) {
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
    row.classList.toggle('is-blocked', !isLive2DParameterOverrideAllowed(item.id));
    updateLive2DParameterRowDirtyState(row, item.id);

    const header = document.createElement('div');
    header.className = 'live2d-parameter-row-header';

    const label = document.createElement('span');
    label.className = 'live2d-parameter-id';
    label.textContent = item.id;

    const favoriteButton = document.createElement('button');
    favoriteButton.type = 'button';
    favoriteButton.className = 'live2d-parameter-favorite';
    favoriteButton.textContent = live2dParameterState.favorites.has(item.id) ? '★' : '☆';
    favoriteButton.setAttribute('aria-label', `${item.id} 즐겨찾기`);
    favoriteButton.addEventListener('click', () => {
        if (live2dParameterState.favorites.has(item.id)) {
            live2dParameterState.favorites.delete(item.id);
        } else {
            live2dParameterState.favorites.add(item.id);
        }
        renderLive2DParameterInspector();
    });

    header.appendChild(label);
    header.appendChild(favoriteButton);

    const controls = document.createElement('div');
    controls.className = 'live2d-parameter-controls';

    const range = document.createElement('input');
    range.type = 'range';
    range.min = String(item.min);
    range.max = String(item.max);
    range.step = '0.001';
    range.value = String(item.current);
    range.setAttribute('aria-label', `${item.id} 슬라이더`);
    range.disabled = !isLive2DParameterOverrideAllowed(item.id) || parameterEditBusy();

    const number = document.createElement('input');
    number.type = 'number';
    number.min = String(item.min);
    number.max = String(item.max);
    number.step = '0.001';
    number.value = formatLive2DParameterValue(item.current);
    number.setAttribute('aria-label', `${item.id} 값`);
    number.disabled = !isLive2DParameterOverrideAllowed(item.id) || parameterEditBusy();

    const resetButton = document.createElement('button');
    resetButton.type = 'button';
    resetButton.className = 'live2d-parameter-reset';
    resetButton.textContent = '초기화';
    resetButton.disabled = !isLive2DParameterOverrideAllowed(item.id) || parameterEditBusy();
    favoriteButton.disabled = parameterEditBusy();
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
        live2dParametersSaveButton.disabled = !ready || !live2dParameterEdit.baseline
            || parameterEditBusy() || ['unknown', 'model_changed'].includes(live2dParameterEdit.status);
    }
    if (!live2dParametersList) {
        return;
    }
    if (!ready) {
        const messages = {
            idle: getLive2DParameterUiString('statusIdle', '파라미터 목록을 불러오기 전입니다.'),
            loading: getLive2DParameterUiString('statusLoading', '파라미터 목록을 불러오는 중입니다.'),
            unavailable: getLive2DParameterUiString('statusUnavailable', '현재 Live2D 모델에서 파라미터 목록을 읽을 수 없습니다.'),
            error: live2dParameterState.metadataError || getLive2DParameterUiString('statusError', '파라미터 목록을 불러오지 못했습니다.'),
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
        live2dParametersList.textContent = getLive2DParameterUiString('empty', '표시할 파라미터가 없습니다.');
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
    if (['unknown', 'baseline_error', 'model_changed'].includes(live2dParameterEdit.status)) resetLive2DParameterEdit();
    ensureLive2DParameterEdit();
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
        setLive2DParameterMetadataStatus('error', getLive2DParameterUiString('statusError', '파라미터 목록을 읽는 중 오류가 발생했습니다.'));
    }
    renderLive2DParameterInspector();
}

function setLive2DParameterPanelOpen(open) {
    if (typeof isImageAvatarMode === 'function' && isImageAvatarMode()) {
        open = false;
    }
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

function openNativeLive2DParameterInspectorIfAvailable() {
    if (
        window.pyBridge
        && typeof window.pyBridge.open_live2d_parameter_inspector === 'function'
    ) {
        window.pyBridge.open_live2d_parameter_inspector();
        return true;
    }
    return false;
}

function clampLive2DParameterPanelPosition(left, top, width, height) {
    const viewportWidth = Number(window.innerWidth || 0);
    const viewportHeight = Number(window.innerHeight || 0);
    const maxLeft = Math.max(LIVE2D_PARAMETER_PANEL_MARGIN, viewportWidth - width - LIVE2D_PARAMETER_PANEL_MARGIN);
    const maxTop = Math.max(LIVE2D_PARAMETER_PANEL_MARGIN, viewportHeight - height - LIVE2D_PARAMETER_PANEL_MARGIN);
    return {
        left: Math.min(Math.max(left, LIVE2D_PARAMETER_PANEL_MARGIN), maxLeft),
        top: Math.min(Math.max(top, LIVE2D_PARAMETER_PANEL_MARGIN), maxTop),
    };
}

function setLive2DParameterPanelPosition(left, top) {
    const panel = getLive2DParameterElement('live2d-parameters-panel');
    if (!panel || typeof panel.getBoundingClientRect !== 'function') {
        return;
    }
    const rect = panel.getBoundingClientRect();
    const position = clampLive2DParameterPanelPosition(left, top, rect.width || 0, rect.height || 0);
    panel.style.left = `${Math.round(position.left)}px`;
    panel.style.top = `${Math.round(position.top)}px`;
    panel.style.right = 'auto';
}

function finishLive2DParameterPanelDrag(pointerId = null) {
    const drag = live2dParameterState.drag;
    if (!drag || (pointerId !== null && drag.pointerId !== pointerId)) {
        return;
    }
    live2dParameterState.drag = null;
    const header = getLive2DParameterElement('live2d-parameters-panel-header');
    if (header && header.classList) {
        header.classList.remove('is-dragging');
    }
    if (header && pointerId !== null && typeof header.releasePointerCapture === 'function') {
        try {
            header.releasePointerCapture(pointerId);
        } catch (error) {
            console.warn('Failed to release Live2D parameter panel drag capture:', error);
        }
    }
}

function onLive2DParameterPanelDragMove(event) {
    const drag = live2dParameterState.drag;
    if (!drag || event.pointerId !== drag.pointerId) {
        return;
    }
    if (typeof event.preventDefault === 'function') {
        event.preventDefault();
    }
    const nextLeft = drag.startLeft + (Number(event.clientX) - drag.startPointerX);
    const nextTop = drag.startTop + (Number(event.clientY) - drag.startPointerY);
    setLive2DParameterPanelPosition(nextLeft, nextTop);
}

function onLive2DParameterPanelDragEnd(event) {
    finishLive2DParameterPanelDrag(event && event.pointerId !== undefined ? event.pointerId : null);
}

function onLive2DParameterPanelDragStart(event) {
    if (event.pointerType === 'mouse' && event.button !== 0) {
        return;
    }
    const panel = getLive2DParameterElement('live2d-parameters-panel');
    const header = getLive2DParameterElement('live2d-parameters-panel-header');
    if (!panel || !header || typeof panel.getBoundingClientRect !== 'function') {
        return;
    }
    if (typeof event.preventDefault === 'function') {
        event.preventDefault();
    }
    const rect = panel.getBoundingClientRect();
    live2dParameterState.drag = {
        pointerId: event.pointerId,
        startPointerX: Number(event.clientX),
        startPointerY: Number(event.clientY),
        startLeft: rect.left,
        startTop: rect.top,
    };
    if (header.classList) {
        header.classList.add('is-dragging');
    }
    if (typeof header.setPointerCapture === 'function') {
        try {
            header.setPointerCapture(event.pointerId);
        } catch (error) {
            console.warn('Failed to capture Live2D parameter panel drag pointer:', error);
        }
    }
}

function buildLive2DParameterSavePayload() {
    // 미편집 키가 나중에 들어온 원격 값으로 바뀌어도 로컬 수정으로 간주하지 않는다.
    const original = live2dParameterEdit.baseline ? live2dParameterEdit.baseline.payload.values : live2dParameterState.values;
    const values = { ...original, ...live2dParameterState.dirtyValues };
    live2dParameterState.removedValues.forEach((paramId) => {
        delete values[paramId];
    });
    Object.keys(values).forEach((paramId) => {
        const numericValue = Number(values[paramId]);
        if (!Number.isFinite(numericValue) || !isLive2DParameterOverrideAllowed(paramId)) {
            delete values[paramId];
        } else {
            values[paramId] = numericValue;
        }
    });
    return {
        values,
        favorites: Array.from(live2dParameterState.favorites).filter(isLive2DParameterOverrideAllowed),
    };
}

function saveLive2DParameterOverrides() {
    if (live2dParameterState.metadataStatus !== 'ready') {
        showLive2DParameterToast(getLive2DParameterUiString('toastLoadFirst', '파라미터 목록을 먼저 불러와야 합니다.'), 'error');
        return;
    }
    const modelKey = String(live2dParameterState.modelKey || '').trim();
    if (!modelKey) {
        showLive2DParameterToast(getLive2DParameterUiString('toastMissingModel', '모델을 먼저 선택해야 저장할 수 있습니다.'), 'error');
        return;
    }
    if (
        !window.pyBridge
        || typeof window.pyBridge.commit_live2d_parameter_overrides !== 'function'
    ) {
        showLive2DParameterToast(getLive2DParameterUiString('toastMissingBridge', '저장 브리지를 사용할 수 없습니다.'), 'error');
        return;
    }
    if (!live2dParameterEdit.baseline || parameterEditBusy()
        || ['unknown', 'model_changed'].includes(live2dParameterEdit.status)) return false;
    const payload = buildLive2DParameterSavePayload();
    const baseline = live2dParameterEdit.baseline;
    requestLive2DParameterEdit((done) => window.pyBridge.commit_live2d_parameter_overrides(
        modelKey, JSON.stringify(payload), JSON.stringify(baseline), done,
    ), (answer) => {
        const fresh = answer.baseline;
        if (answer.status === 'accepted') {
            if (!validLive2DParameterBaseline(fresh) || fresh.generation !== baseline.generation
                || fresh.settings_revision < baseline.settings_revision) throw new Error('invalid_baseline');
            live2dParameterEdit.baseline = fresh;
            live2dParameterState.values = { ...fresh.payload.values };
            live2dParameterState.dirtyValues = {};
            live2dParameterState.removedValues = new Set();
            live2dParameterState.favorites = new Set(fresh.payload.favorites);
            live2dParameterEdit.status = 'saved';
            live2dParameterEdit.message = getLive2DParameterUiString('toastSaveSuccess', 'Live2D 파라미터를 저장했습니다.');
            applyLive2DParameterOverrides();
            showLive2DParameterToast(live2dParameterEdit.message, 'success');
            return;
        }
        if (answer.status === 'conflict' && answer.reason === 'revision_conflict') {
            if (!validLive2DParameterBaseline(fresh) || fresh.generation !== baseline.generation
                || !answer.conflicts || typeof answer.conflicts !== 'object') throw new Error('invalid_conflict');
            // 충돌한 키만 확인 처리한다. 미편집 원격 키는 기존 편집 기준을 유지한다.
            const values = { ...baseline.payload.values };
            let favorites = baseline.payload.favorites;
            Object.keys(answer.conflicts).forEach((key) => {
                if (key === '__favorites__') favorites = fresh.payload.favorites;
                else if (Object.prototype.hasOwnProperty.call(fresh.payload.values, key)) values[key] = fresh.payload.values[key];
                else delete values[key];
            });
            live2dParameterEdit.baseline = { ...fresh, payload: { values, favorites } };
            live2dParameterEdit.status = 'conflict';
            const conflicts = Object.entries(answer.conflicts);
            const detail = conflicts.slice(0, 3).map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join(', ');
            live2dParameterEdit.message = `다른 곳에서 같은 항목을 변경했습니다. 현재 값: ${detail}${conflicts.length > 3 ? ' 외' : ''}. 편집값은 남아 있습니다. 다시 저장하면 이 편집값을 적용합니다.`;
        } else if (answer.reason === 'model_changed') {
            live2dParameterEdit.status = 'model_changed';
            live2dParameterEdit.message = '모델이 변경되었습니다. 새로고침 후 다시 편집해 주세요.';
        } else if (answer.status === 'rejected') {
            live2dParameterEdit.status = 'error';
            live2dParameterEdit.message = getLive2DParameterUiString('toastSaveError', 'Live2D 파라미터 저장에 실패했습니다.');
        } else throw new Error('invalid_reply');
        showLive2DParameterToast(live2dParameterEdit.message, 'error');
    }, true);
    renderLive2DParameterInspector();
    return true;
}

function resetVisibleLive2DParameterOverrides() {
    if (parameterEditBusy()) return;
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

function buildLive2DParameterInspectorSnapshot() {
    return {
        modelKey: live2dParameterState.modelKey,
        metadataStatus: live2dParameterState.metadataStatus,
        metadataError: live2dParameterState.metadataError,
        saveStatus: live2dParameterEdit.status,
        saveMessage: live2dParameterEdit.message,
        editReady: Boolean(live2dParameterEdit.baseline),
        activeTab: live2dParameterState.activeTab,
        searchQuery: live2dParameterState.searchQuery,
        favorites: Array.from(live2dParameterState.favorites),
        savePayload: buildLive2DParameterSavePayload(),
        metadata: live2dParameterState.metadata.map((item) => ({
            id: item.id,
            current: normalizeLive2DParameterNumber(item.current, item.default),
            default: normalizeLive2DParameterNumber(item.default, 0),
            min: normalizeLive2DParameterNumber(item.min, 0),
            max: normalizeLive2DParameterNumber(item.max, 1),
            recommended: Boolean(item.recommended),
            displayName: String(item.displayName || ''),
            groupId: String(item.groupId || ''),
            groupName: String(item.groupName || ''),
        })),
    };
}

function getLive2DParameterInspectorSnapshot(refreshBaseline = false) {
    if (refreshBaseline && ['unknown', 'baseline_error', 'model_changed'].includes(live2dParameterEdit.status)) resetLive2DParameterEdit();
    ensureLive2DParameterEdit();
    if (live2dParameterState.metadataStatus !== 'ready') {
        refreshLive2DParameterInspector();
    }
    return JSON.stringify(buildLive2DParameterInspectorSnapshot());
}

function setLive2DParameterInspectorValue(paramId, value) {
    if (parameterEditBusy()) return false;
    const item = getLive2DParameterMetadata(paramId);
    if (!item || !isLive2DParameterOverrideAllowed(paramId)) {
        return false;
    }
    const minValue = normalizeLive2DParameterNumber(item.min, value);
    const maxValue = normalizeLive2DParameterNumber(item.max, value);
    const numericValue = Math.min(
        Math.max(normalizeLive2DParameterNumber(value, item.current), minValue),
        maxValue,
    );
    setLive2DParameterDirtyValue(paramId, numericValue);
    return true;
}

function setLive2DParameterInspectorFavorite(paramId, favorites) {
    if (parameterEditBusy()) return false;
    if (!paramId) {
        return false;
    }
    if (favorites) {
        live2dParameterState.favorites.add(paramId);
    } else {
        live2dParameterState.favorites.delete(paramId);
    }
    renderLive2DParameterInspector();
    return true;
}

function resetLive2DParameterInspectorValue(paramId) {
    if (parameterEditBusy()) return false;
    if (!getLive2DParameterMetadata(paramId)) {
        return false;
    }
    resetLive2DParameterOverride(paramId);
    return true;
}

function resetLive2DParameterInspectorValues(paramIds) {
    if (parameterEditBusy()) return false;
    if (!Array.isArray(paramIds)) {
        return false;
    }
    let changed = false;
    paramIds.forEach((paramId) => {
        if (getLive2DParameterMetadata(paramId) && resetLive2DParameterOverrideState(paramId)) {
            changed = true;
        }
    });
    if (changed) {
        renderLive2DParameterInspector();
    }
    return changed;
}

function saveLive2DParameterInspectorOverrides() {
    return Boolean(saveLive2DParameterOverrides());
}

function syncLive2DParameterVisibilityForAvatarMode() {
    if (typeof isImageAvatarMode !== 'function') {
        return;
    }
    const live2dParametersButton = getLive2DParameterElement('live2d-parameters-floating-btn');
    if (live2dParametersButton) {
        live2dParametersButton.style.display = isImageAvatarMode() ? 'none' : 'inline-flex';
    }
    if (isImageAvatarMode()) {
        setLive2DParameterPanelOpen(false);
    }
}

function bindLive2DParameterEvents() {
    const live2dParametersButton = getLive2DParameterElement('live2d-parameters-floating-btn');
    const live2dParametersHeader = getLive2DParameterElement('live2d-parameters-panel-header');
    const live2dParametersCloseButton = getLive2DParameterElement('live2d-parameters-close-btn');
    const live2dParametersSearch = getLive2DParameterElement('live2d-parameters-search');
    const live2dParametersSaveButton = getLive2DParameterElement('live2d-parameters-save-btn');
    const live2dParametersResetButton = getLive2DParameterElement('live2d-parameters-reset-btn');

    syncLive2DParameterVisibilityForAvatarMode();

    if (live2dParametersButton) {
        live2dParametersButton.addEventListener('click', () => {
            if (openNativeLive2DParameterInspectorIfAvailable()) {
                return;
            }
            setLive2DParameterPanelOpen(!live2dParameterState.panelOpen);
        });
    }

    if (live2dParametersHeader) {
        live2dParametersHeader.addEventListener('pointerdown', onLive2DParameterPanelDragStart);
    }

    if (window && typeof window.addEventListener === 'function') {
        window.addEventListener('pointermove', onLive2DParameterPanelDragMove, { passive: false });
        window.addEventListener('pointerup', onLive2DParameterPanelDragEnd, { passive: true });
        window.addEventListener('pointercancel', onLive2DParameterPanelDragEnd, { passive: true });
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
