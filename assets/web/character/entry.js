/** 앱 내부 문서 전용 진입점. PC 경로·Qt 브리지·채팅 기능을 적재하지 않는다. */
(() => {
    const origin = 'https://appassets.androidplatform.net';
    if (window.location.origin !== origin) return;
    let snapshot = null;
    let expressions = new Map();
    let generation = 0;
    let disposed = false;
    let request = null;
    const assetId = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
    function assetUrl(kind, id) {
        const resolved = kind === 'expression' ? expressions.get(id) : id;
        if (!assetId(snapshot?.model_version) || !assetId(resolved)) throw new Error('허용되지 않은 캐릭터 자산입니다.');
        return `${origin}/models/${snapshot.model_version}/assets/${resolved}`;
    }
    function emitInput(value) {
        window.eneCharacterNative?.postMessage(JSON.stringify(value));
    }
    const character = window.createCharacter({assetUrl, emitInput}, document.getElementById('live2d-canvas'));
    async function receive(event) {
        if (disposed || event.origin !== origin || typeof event.data !== 'string' || event.data.length > 262144) return;
        let expected = generation;
        try {
            const command = JSON.parse(event.data);
            if (command.type === 'snapshot') {
                const current = ++generation;
                expected = current;
                request?.abort(); request = new AbortController();
                snapshot = command.value; expressions = new Map();
                if (snapshot?.status === 'ready') {
                    const response = await fetch(assetUrl('model', snapshot.entry_asset_id), {signal: request.signal});
                    if (!response.ok) throw new Error('모델 목록을 읽지 못했습니다.');
                    const model = await response.json();
                    if (disposed || generation !== current) return;
                    for (const item of model.FileReferences?.Expressions || []) {
                        if (snapshot.expression_ids?.includes(item.Name) && assetId(item.File)) expressions.set(item.Name, item.File);
                    }
                }
                if (disposed || generation !== current) return;
                const ready = await character.applySnapshot(snapshot);
                if (!disposed && generation === current) emitInput({type: ready ? 'ready' : 'unavailable', model_version: snapshot?.model_version || null});
            } else if (command.type === 'action') {
                await character.applyAction(command.value);
            } else if (command.type === 'playback') {
                character.applyPlayback(command.value);
            }
        } catch (_) {
            if (!disposed && expected === generation) emitInput({type: 'error', code: 'character_render_failed'});
        }
    }
    function dispose() {
        if (disposed) return;
        disposed = true; generation++; request?.abort();
        window.removeEventListener('message', receive);
        window.removeEventListener('pagehide', dispose);
        character.dispose();
    }
    window.addEventListener('message', receive);
    window.addEventListener('pagehide', dispose);
    emitInput({type: 'document_ready'});
})();
