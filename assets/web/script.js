/**
 * ENE 웹 런타임 로더 마커.
 *
 * 실제 런타임은 index.html의 순서 지정 classic script로 분리되어 있다.
 * 패키징과 테스트가 안정적인 진입점을 갖도록 이 파일은 마지막에 둔다.
 */
console.log("=== ENE web runtime chunks loaded ===");

// 개인 모델 경로와 Qt 호출은 PC 호스트에만 둔다. 모바일 묶음에는 이 파일을 넣지 않는다.
window.eneCharacter = window.createCharacter({
    kind: 'pc', defaultModelPath: DEFAULT_MODEL_PATH,
    assetUrl(kind, id) {
        return kind === 'expression' ? new URL(`${id}.exp3.json`, currentEmotionsBasePath).href : id;
    },
    emitInput(value) {
        if (value.type === 'head_pat_completed') window.pyBridge?.increment_head_pat_count_from_js?.();
        if (value.type === 'resize' && chatPanelHeightPx !== null) applyChatPanelHeight(chatPanelHeightPx);
    }
}, document.getElementById('live2d-canvas'));
if (!window.live2dModel && currentModelLoadToken === 0) {
    currentModelPath = resolveModelPathFromConfig();
    currentEmotionsBasePath = resolveEmotionsBasePathFromConfig();
    loadModel();
}
