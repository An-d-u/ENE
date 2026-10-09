/** 앱 내부 문서 전용 진입점. PC 경로·Qt 브리지·채팅 기능을 적재하지 않는다. */
(() => {
    const origin = 'https://appassets.androidplatform.net';
    if (window.location.origin !== origin) return;
    const native = window.eneCharacterNative;
    if (typeof native?.postMessage !== 'function') return;
    let snapshot = null;
    let expressions = new Map();
    let generation = 0;
    let documentGeneration = null;
    let presentationGeneration = 0;
    let disposed = false;
    let request = null;
    let character = null;
    let snapshotPending = false;
    let pendingExpression = null;
    let presentation = {placement:{scale:1,xPercent:50,yPercent:50},visible:false};
    const assetId = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
    function assetUrl(kind, id) {
        const resolved = kind === 'expression' ? expressions.get(id) : id;
        if (!assetId(snapshot?.model_version) || !assetId(resolved)) throw new Error('허용되지 않은 캐릭터 자산입니다.');
        return `${origin}/models/${snapshot.model_version}/assets/${resolved}`;
    }
    function emitInput(value, presentation = presentationGeneration) {
        if (disposed || !documentGeneration) return;
        if (value.type === 'document_ready' || value.type === 'document_error' || value.code === 'character_initialization_failed') {
            native.postMessage(JSON.stringify({...value, generation: documentGeneration}));
        } else if (presentation > 0 && presentation === presentationGeneration) {
            native.postMessage(JSON.stringify({...value, generation: documentGeneration, presentation_generation: presentation}));
        }
    }
    async function receive(event) {
        // 허용된 내부 문서에 주입한 객체의 응답만 받는다. 일반 window 메시지는 사용하지 않는다.
        if (disposed || typeof event.data !== 'string' || event.data.length > 262400) return;
        let expected = generation;
        let expectedPresentation = presentationGeneration;
        let failureCode = 'character_render_failed';
        let documentFailure = false;
        try {
            const command = JSON.parse(event.data);
            if (command.type === 'initialize') {
                if (!documentGeneration && typeof command.generation === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(command.generation)) {
                    documentGeneration = command.generation;
                    failureCode = 'character_initialization_failed';
                    character = window.createCharacter({kind:'phone', assetUrl, emitInput, currentModel:()=>snapshot?.model_version}, document.getElementById('live2d-canvas'));
                    emitInput({type: 'document_ready'});
                }
                return;
            }
            if (!character || !documentGeneration || command.generation !== documentGeneration) return;
            if (command.type === 'binding') {
                const next = command.presentation_generation;
                if (!Number.isSafeInteger(next) || next <= presentationGeneration) return;
                presentationGeneration = next; generation++;
                request?.abort(); request = null; pendingExpression = null; snapshotPending = false;
                character.invalidatePending();
                presentation = {...presentation,visible:false};
                character.applyPresentation(presentation);
                return;
            }
            if (!presentationGeneration || command.presentation_generation !== presentationGeneration) return;
            expectedPresentation = presentationGeneration;
            if (command.type === 'snapshot') {
                const current = ++generation;
                expected = current;
                snapshotPending = true;
                request?.abort(); request = new AbortController();
                snapshot = command.value; expressions = new Map();
                if (pendingExpression?.model_version !== snapshot?.model_version ||
                    pendingExpression?.action_seq <= snapshot?.action_seq) pendingExpression = null;
                if (snapshot?.status === 'ready') {
                    failureCode = 'character_asset_failed';
                    const response = await fetch(assetUrl('model', snapshot.entry_asset_id), {signal: request.signal});
                    if (!response.ok) throw new Error('모델 목록을 읽지 못했습니다.');
                    const model = await response.json();
                    if (disposed || generation !== current) return;
                    for (const item of model.FileReferences?.Expressions || []) {
                        if (snapshot.expression_ids?.includes(item.Name) && assetId(item.File)) expressions.set(item.Name, item.File);
                    }
                }
                if (disposed || generation !== current) return;
                failureCode = 'character_render_failed';
                const ready = await character.applySnapshot(snapshot);
                // 스냅샷의 비동기 자산 읽기 동안 도착한 표정은 최신 현재값 하나만 복원한다.
                // 이전 스냅샷의 완료가 새 스냅샷의 준비 상태나 표정을 지우지 못하게 한다.
                while (!disposed && generation === current && ready && pendingExpression) {
                    const latest = pendingExpression; pendingExpression = null;
                    await character.applyAction(latest, {restoreCurrent:true});
                }
                if (!disposed && generation === current) snapshotPending = false;
                if (!disposed && generation === current) emitInput({type: ready ? 'ready' : 'unavailable', model_version: snapshot?.model_version || null}, expectedPresentation);
            } else if (command.type === 'action') {
                if (snapshotPending) {
                    const action = command.value;
                    if (action?.kind === 'expression' && action.model_version === snapshot?.model_version &&
                        snapshot.expression_ids?.includes(action.action_id) && Number.isSafeInteger(action.action_seq) &&
                        action.action_seq > (snapshot.action_seq ?? 0) && action.action_seq > (pendingExpression?.action_seq ?? 0)) {
                        pendingExpression = action;
                    }
                } else await character.applyAction(command.value);
            } else if (command.type === 'playback') {
                character.applyPlayback(command.value);
            } else if (command.type === 'head_pat') {
                character.applyHeadPat(command.value);
            } else if (command.type === 'preview') {
                character.applyPreview(command.value);
            } else if (command.type === 'presentation') {
                if (command.value?.visible === false && presentation.visible) {
                    generation++; expected = generation;
                    request?.abort(); request = null; pendingExpression = null; snapshotPending = false;
                    character.invalidatePending();
                }
                documentFailure = true;
                character.applyPresentation(command.value);
                presentation = command.value;
            }
        } catch (_) {
            if (!disposed && expected === generation) {
                snapshotPending = false; pendingExpression = null;
                emitInput({type: documentFailure ? 'document_error' : 'error', code: failureCode}, expectedPresentation);
            }
        }
    }
    function dispose() {
        if (disposed) return;
        try { character?.dispose(); }
        finally {
            disposed = true; generation++; request?.abort(); pendingExpression = null; snapshotPending = false;
            native.onmessage = null;
            window.removeEventListener('pagehide', dispose);
        }
    }
    native.onmessage = receive;
    window.addEventListener('pagehide', dispose);
    native.postMessage(JSON.stringify({type: 'bridge_ready'}));
})();
