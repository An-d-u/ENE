/** PC 전용 카탈로그 확인. 경로·표시 이름·설정 원문을 보내지 않는다. */
let pendingCompanionCatalog = null;

window.requestCompanionCharacterCatalog = function (text) {
    if (typeof text !== 'string' || text.length > 512) return;
    try {
        const request = JSON.parse(text);
        if (!/^[a-f0-9-]{36}$/.test(request.generation || '') ||
                !/^[a-f0-9]{64}$/.test(request.model_version || '')) return;
        pendingCompanionCatalog = {generation: request.generation, model_version: request.model_version};
        window.notifyCompanionCharacterReady();
    } catch (_) { /* 잘못된 로컬 확인 요청은 실행하지 않는다. */ }
};

window.notifyCompanionCharacterReady = function () {
    const request = pendingCompanionCatalog;
    if (!request || characterDisposed ||
            request.generation !== window.eneModelConfig?.companionModelGeneration ||
            typeof window.pyBridge?.report_companion_character_catalog !== 'function') return;
    const failed = currentModelFailedToken === currentModelLoadToken && currentModelLoadToken > 0;
    if (!failed && (!window.live2dModel || currentModelReadyToken !== currentModelLoadToken)) return;
    let report = {...request, status: 'unsupported'};
    try {
        if (failed) throw new Error('지원하지 않는 모델');
        const core = getLive2DParameterCoreModel();
        const ids = readLive2DParameterIds(core);
        if (!core || ids.length < 1 || ids.length > 256 || new Set(ids).size !== ids.length) throw new Error('잘못된 카탈로그');
        const read = (index, arrays, getter) => {
            const values = readLive2DParameterArray(core, arrays);
            const value = values ? values[index] : core[getter]?.(index);
            if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('잘못된 범위');
            return value;
        };
        const parameters = ids.map((id, index) => {
            if (!id || id.length > 128) throw new Error('잘못된 매개변수');
            const min = read(index, ['minimumValues', 'parameterMinimumValues'], 'getParameterMinimumValue');
            const max = read(index, ['maximumValues', 'parameterMaximumValues'], 'getParameterMaximumValue');
            const initial = read(index, ['defaultValues', 'parameterDefaultValues'], 'getParameterDefaultValue');
            if (!(min <= initial && initial <= max)) throw new Error('잘못된 범위');
            return {id, min, max, default: initial};
        }).sort((a, b) => a.id.localeCompare(b.id));
        report = {...request, parameters, expressions: [...currentAvailableEmotions].sort(), default_expression: baseEmotionTag,
            gestures: Object.keys(SYNTHETIC_GESTURES).sort()};
    } catch (_) { /* 실제 SDK 범위를 확인할 수 없으면 기능을 해제한다. */ }
    pendingCompanionCatalog = null;
    window.pyBridge.report_companion_character_catalog(JSON.stringify(report));
};
