/** 캐릭터 전용 수명. 호스트는 입력 전달과 검증된 자산 URL 생성만 맡는다. */
window.createCharacter = function createCharacter(host, canvas) {
    if (!characterDisposed || app) throw new Error('캐릭터 실행부가 이미 존재합니다.');
    if (!host || typeof host.emitInput !== 'function' || typeof host.assetUrl !== 'function' || !canvas) {
        throw new Error('캐릭터 호스트가 올바르지 않습니다.');
    }
    app = new PIXI.Application({view: canvas, transparent: true, backgroundAlpha: 0, resizeTo: window, antialias: true});
    characterHost = {...host, currentModel: host.currentModel || (() => version)};
    characterCanvas = canvas;
    characterDisposed = false;
    let disposed = false;
    let version = null;
    let snapshotGeneration = 0;
    let snapshot = null;
    let loadingModel = null;
    let parameterModel = null;
    let parameterHook = null;

    function resize() {
        if (disposed) return;
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
    function applySettings(settings) {
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
            s.head_pat_fade_out_ms ?? 220, s.head_pat_active_emotion_custom || 'normal', s.head_pat_end_emotion_custom || 'normal',
            s.head_pat_end_emotion_duration_sec ?? 5);
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
        live2dParameterState.values = {...(next.parameters || {})};
        live2dParameterState.dirtyValues = {};
        live2dParameterState.removedValues.clear();
        applySettings(next.settings);
        const loading = loadingModel || (loadingModel = window.applyENEModelSettings({modelPath: host.assetUrl('model', next.entry_asset_id),
            emotionsBasePath: '', availableEmotions: next.expression_ids || ['normal'], scale: 1, xPercent: 50, yPercent: 50}));
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
    async function applyAction(action) {
        if (disposed || !snapshot || action?.model_version !== version) return false;
        if (action.kind === 'expression' && snapshot.expression_ids?.includes(action.action_id)) {
            await changeExpression(action.action_id, {durationMs: Math.min(30000, Math.max(0, Number(action.duration_ms) || 0))});
            return !disposed;
        }
        if (action.kind === 'gesture' && snapshot.gesture_ids?.includes(action.action_id)) {
            return playSyntheticGesture(action.action_id);
        }
        return false;
    }
    function applyPlayback(value) {
        if (disposed) return false;
        const mouth = value?.active && Number.isFinite(value.mouth_open) ? Math.min(1, Math.max(0, value.mouth_open)) : 0;
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
        try { app.destroy(false, {children: true, texture: true, baseTexture: true}); } catch (_) { /* 이미 손실된 컨텍스트 */ }
        window.live2dModel = null;
        app = null; characterHost = null; characterCanvas = null;
    }
    window.addEventListener('resize', resize);
    window.addEventListener('pagehide', dispose);
    ensureHeadPatEventBindings();
    characterTrackingFrame = requestAnimationFrame(updateMouseTracking);
    return Object.freeze({applySnapshot, applyAction, applyPlayback, applyHeadPat:applyHeadPatState, dispose});
};
