/** 캐릭터 전용 수명. 호스트는 입력 전달과 검증된 자산 URL 생성만 맡는다. */
function readPhoneRenderLimits(renderer) {
    try {
        const gl = renderer.gl;
        const texture = gl.getParameter(gl.MAX_TEXTURE_SIZE);
        const renderbuffer = gl.getParameter(gl.MAX_RENDERBUFFER_SIZE);
        const viewport = gl.getParameter(gl.MAX_VIEWPORT_DIMS);
        if (viewport?.length === 2 && [texture, renderbuffer, viewport[0], viewport[1]].every(value => Number.isInteger(value) && value > 0)) {
            return {valid: true, width: Math.min(4096, texture, renderbuffer, viewport[0]),
                height: Math.min(4096, texture, renderbuffer, viewport[1])};
        }
    } catch (_) { /* 한도 확인이 불가능한 환경에서는 밀도를 승격하지 않는다. */ }
    return {valid: false, width: 4096, height: 4096};
}

function calculatePhoneRenderSize(width, height, dpr, limits) {
    if (![width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
    const target = Number.isFinite(dpr) && dpr > 0 ? Math.min(3, Math.max(1, dpr)) : 1;
    let resolution = Math.min(limits.valid ? target : 1, Math.sqrt(4194304 / (width * height)),
        limits.width / width, limits.height / height);
    const withinCaps = value => {
        const w = Math.round(width * value), h = Math.round(height * value);
        return w <= limits.width && h <= limits.height && w * h <= 4194304;
    };
    // Pixi 7의 반올림 이후에도 예산을 넘지 않게 보정한다. 렌더러 재시도는 하지 않는다.
    if (!withinCaps(resolution)) {
        let low = 0, high = resolution;
        for (let index = 0; index < 48; index++) {
            const middle = (low + high) / 2;
            if (withinCaps(middle)) low = middle; else high = middle;
        }
        resolution = low;
    }
    const bufferWidth = Math.round(width * resolution), bufferHeight = Math.round(height * resolution);
    if (!Number.isFinite(resolution) || resolution <= 0 || bufferWidth < 1 || bufferHeight < 1 || !withinCaps(resolution)) {
        throw new Error('캐릭터 그리기 크기를 적용할 수 없습니다.');
    }
    return {logicalWidth: width, logicalHeight: height, resolution, bufferWidth, bufferHeight};
}

window.createCharacter = function createCharacter(host, canvas) {
    if (!characterDisposed || app) throw new Error('캐릭터 실행부가 이미 존재합니다.');
    if (!host || typeof host.emitInput !== 'function' || typeof host.assetUrl !== 'function' || !canvas) {
        throw new Error('캐릭터 호스트가 올바르지 않습니다.');
    }
    const phone = host.kind === 'phone';
    app = new PIXI.Application(phone
        ? {view: canvas, transparent: true, backgroundAlpha: 0, antialias: true, width: 1, height: 1, resolution: 1, autoDensity: true}
        : {view: canvas, transparent: true, backgroundAlpha: 0, resizeTo: window, antialias: true});
    characterHost = {...host, currentModel: host.currentModel || (() => version)};
    characterCanvas = canvas;
    characterDisposed = false;
    characterPresentationVisible = true;
    characterPlacement = {scale: 1, xPercent: 50, yPercent: 50};
    let disposed = false;
    let version = null;
    let snapshotGeneration = 0;
    let snapshot = null;
    let loadingModel = null;
    let parameterModel = null;
    let parameterHook = null;
    const renderLimits = phone ? readPhoneRenderLimits(app.renderer) : null;
    let renderSize = null;
    let removeDensityListener = null;
    let watchedDensity = null;

    function syncRenderSize() {
        if (!phone || disposed || !characterPresentationVisible) return;
        const next = calculatePhoneRenderSize(window.innerWidth, window.innerHeight, window.devicePixelRatio, renderLimits);
        if (!next || (renderSize?.logicalWidth === next.logicalWidth && renderSize.logicalHeight === next.logicalHeight &&
            renderSize.resolution === next.resolution)) return;
        app.renderer.resolution = next.resolution;
        // Pixi는 너비부터 바꾸므로 회전 중의 임시 정사각형도 픽셀 예산을 넘지 않게 한다.
        if (next.bufferWidth * canvas.height > 4194304) {
            app.renderer.resize(1 / next.resolution, 1 / next.resolution);
        }
        app.renderer.resize(next.logicalWidth, next.logicalHeight);
        renderSize = next;
    }
    function watchDensity() {
        if (!phone || disposed || typeof window.matchMedia !== 'function') return;
        const dpr = Number.isFinite(window.devicePixelRatio) && window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
        if (watchedDensity === dpr) return;
        removeDensityListener?.(); removeDensityListener = null;
        watchedDensity = dpr;
        try {
            const query = window.matchMedia(`(resolution: ${dpr}dppx)`);
            if (typeof query.addEventListener === 'function' && typeof query.removeEventListener === 'function') {
                query.addEventListener('change', resize);
                removeDensityListener = () => query.removeEventListener('change', resize);
            } else if (typeof query.addListener === 'function' && typeof query.removeListener === 'function') {
                query.addListener(resize);
                removeDensityListener = () => query.removeListener(resize);
            }
        } catch (_) { /* 미지원 환경은 창 크기 변경과 전경 복귀 때 다시 확인한다. */ }
    }

    function applyPresentation(value) {
        if (disposed || host.kind !== 'phone' || !value || typeof value.visible !== 'boolean' ||
            Object.keys(value).sort().join(',') !== 'placement,visible') return false;
        const p = value.placement;
        if (!isPhonePlacementInRange(p) || Object.keys(p).sort().join(',') !== 'scale,xPercent,yPercent') return false;
        characterPlacement = {...p};
        applyCurrentModelPlacement();
        if (characterPresentationVisible === value.visible) return true;
        characterPresentationVisible = value.visible;
        if (!value.visible) {
            cancelHeadPatInteraction(); cancelPendingPatEmotionRestore();
            clearIdleSyntheticGestureTimer(); stopSyntheticGesture(); setMouthOpen(0);
            cancelAnimationFrame(characterTrackingFrame); characterTrackingFrame = 0;
            if (window.live2dModel) window.live2dModel.autoUpdate = false;
            app.stop();
        } else {
            try { syncRenderSize(); watchDensity(); }
            catch (error) { dispose(); throw error; }
            lastMouseUpdateAt = performance.now();
            resetAutoEyeBlinkRuntime();
            if (window.live2dModel) window.live2dModel.autoUpdate = true;
            app.start();
            if (!characterTrackingFrame) characterTrackingFrame = requestAnimationFrame(updateMouseTracking);
            scheduleNextIdleSyntheticGesture();
        }
        return true;
    }

    function resize() {
        if (disposed) return;
        if (phone) {
            try { syncRenderSize(); watchDensity(); }
            catch (_) {
                dispose();
                host.emitInput({type: 'document_error', code: 'character_render_failed'});
                return;
            }
        }
        applyCurrentModelPlacement();
        if (typeof isImageAvatarMode === 'function' && isImageAvatarMode()) applyImageAvatarPlacement();
        host.emitInput({type: 'resize'});
    }
    function detachParameters() {
        if (parameterHook) parameterModel?.off('beforeModelUpdate', parameterHook);
        parameterModel = null; parameterHook = null;
    }
    function reset() {
        cancelHeadPatInteraction();
        loadingModel = null;
        currentModelLoadToken++;
        characterExpressionGeneration++;
        characterExpressionReads.forEach(controller => controller.abort());
        characterExpressionReads.clear();
        expressionRuntimeState.definitionCache.clear();
        setIdleSyntheticGestureConfig(false, 'normal');
        stopSyntheticGesture();
        cancelPendingPatEmotionRestore();
        setMouthOpen(0);
        detachParameters();
        removeCurrentModelArtifacts();
        currentModelPath = ''; currentEmotionsBasePath = '';
        currentEmotionTag = 'normal'; baseEmotionTag = 'normal';
    }
    function invalidatePending() {
        if (disposed) return;
        snapshotGeneration++;
        characterExpressionGeneration++;
        characterExpressionReads.forEach(controller => controller.abort());
        characterExpressionReads.clear();
        cancelHeadPatInteraction(); cancelPendingPatEmotionRestore();
        clearIdleSyntheticGestureTimer(); stopSyntheticGesture(); setMouthOpen(0);
        // 준비된 모델은 보존한다. 아직 반환되지 않은 SDK 생성 결과만 무효화한다.
        if (loadingModel && !window.live2dModel) {
            currentModelLoadToken++; loadingModel = null; currentModelPath = '';
        }
    }
    function applySettings(settings, defaults) {
        const s = settings || {};
        window.setBuiltinIdleMotionEnabled(s.enable_builtin_idle_motion ?? true);
        window.setAutoEyeBlinkEnabled(s.enable_auto_eye_blink ?? true);
        window.setIdleMotionEnabled(s.enable_idle_motion ?? true);
        window.setIdleMotionConfig(s.idle_motion_strength ?? 1, s.idle_motion_speed ?? 1);
        window.setExpressiveMotionConfig(s.enable_expressive_motion ?? true, s.expressive_motion_strength ?? 1,
            s.expressive_motion_speed ?? 1, s.expressive_motion_speech_boost ?? 1, s.enable_expressive_pose_transitions ?? true);
        window.setSyntheticGestureScale(s.synthetic_gesture_scale ?? 1);
        window.setIdleSyntheticGestureConfig(s.enable_idle_synthetic_gestures ?? false, s.idle_synthetic_gesture_frequency ?? 'normal');
        window.setHeadPatConfig(s.enable_head_pat ?? true, s.head_pat_strength ?? 1, s.head_pat_fade_in_ms ?? 180,
            s.head_pat_fade_out_ms ?? 220, s.head_pat_active_emotion_custom || defaults?.active || 'normal', s.head_pat_end_emotion_custom || defaults?.end || 'normal',
            s.head_pat_end_emotion_duration_sec ?? 5);
    }
    function applyParameters(next) {
        const values = next.parameters || {};
        const defaults = new Map((next.parameter_catalog || []).map(item => [item.id, item.default]));
        for (const id of Object.keys(getLive2DParameterOverrideValues())) {
            if (!Object.prototype.hasOwnProperty.call(values, id) && Number.isFinite(defaults.get(id))) {
                setLive2DParameterModelValue(id, defaults.get(id));
            }
        }
        live2dParameterState.values = {...values};
        live2dParameterState.dirtyValues = {};
        live2dParameterState.removedValues.clear();
    }
    async function applySnapshot(next) {
        if (disposed) return false;
        const generation = ++snapshotGeneration;
        if (!next || next.status !== 'ready' || !/^[a-f0-9]{64}$/.test(next.model_version || '') ||
                !/^[a-f0-9]{64}$/.test(next.entry_asset_id || '')) {
            reset(); snapshot = null; version = null; return false;
        }
        if (version !== next.model_version) reset();
        version = next.model_version;
        snapshot = next;
        applyParameters(next);
        applySettings(next.settings, next.head_pat_defaults);
        const loading = loadingModel || (loadingModel = window.applyENEModelSettings({modelPath: host.assetUrl('model', next.entry_asset_id),
            emotionsBasePath: '', availableEmotions: next.expression_ids || ['normal']}));
        await loading;
        if (loadingModel === loading) loadingModel = null;
        if (disposed || generation !== snapshotGeneration) return false;
        // 전용 WebView는 PC 매개변수 창을 적재하지 않으므로 적용 hook도 직접 소유한다.
        detachParameters();
        parameterModel = window.live2dModel?.internalModel;
        if (parameterModel?.on) {
            parameterHook = () => applyLive2DParameterOverrides();
            parameterModel.on('beforeModelUpdate', parameterHook);
        }
        await changeExpression(next.default_expression || 'normal', {durationMs: 0});
        return !disposed && generation === snapshotGeneration && Boolean(window.live2dModel);
    }
    function applyPreview(next) {
        if (disposed || !snapshot || next?.status !== 'ready' || next.model_version !== version) return false;
        applyParameters(next);
        applySettings(next.settings, next.head_pat_defaults);
        return true;
    }
    async function applyAction(action, {restoreCurrent = false} = {}) {
        if (disposed || !snapshot || action?.model_version !== version) return false;
        // 준비 중에는 현재 표정 하나만 복원한다. 숨긴 제스처나 애니메이션은 재생하지 않는다.
        if (!characterCanAnimate() && !(restoreCurrent && action.kind === 'expression')) return false;
        if (action.kind === 'expression' && snapshot.expression_ids?.includes(action.action_id)) {
            await changeExpression(action.action_id, {durationMs: restoreCurrent ? 0 : Math.min(30000, Math.max(0, Number(action.duration_ms) || 0))});
            return !disposed;
        }
        if (action.kind === 'gesture' && snapshot.gesture_ids?.includes(action.action_id)) {
            return playSyntheticGesture(action.action_id);
        }
        return false;
    }
    function applyPlayback(value) {
        if (disposed) return false;
        const mouth = characterCanAnimate() && value?.active && Number.isFinite(value.mouth_open) ? Math.min(1, Math.max(0, value.mouth_open)) : 0;
        applyMouthPose({source: 'rms', open: mouth});
        return true;
    }
    function dispose() {
        if (disposed) return;
        disposed = true; characterDisposed = true; snapshotGeneration++;
        try { reset(); } catch (_) { /* 그래픽 컨텍스트가 사라져도 수명 자원은 회수한다. */ }
        cancelAnimationFrame(characterTrackingFrame); characterTrackingFrame = 0;
        removeHeadPatEventBindings();
        window.removeEventListener('resize', resize);
        window.removeEventListener('pagehide', dispose);
        removeDensityListener?.(); removeDensityListener = null;
        try { app.destroy(false, {children: true, texture: true, baseTexture: true}); } catch (_) { /* 이미 손실된 컨텍스트 */ }
        window.live2dModel = null;
        app = null; characterHost = null; characterCanvas = null;
    }
    try {
        syncRenderSize(); watchDensity();
        window.addEventListener('resize', resize);
        window.addEventListener('pagehide', dispose);
        ensureHeadPatEventBindings();
        characterTrackingFrame = requestAnimationFrame(updateMouseTracking);
    } catch (error) { dispose(); throw error; }
    return Object.freeze({applySnapshot, applyAction, applyPreview, applyPlayback, applyPresentation, applyHeadPat:applyHeadPatState, invalidatePending, dispose});
};
