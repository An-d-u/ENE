from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1] / "assets" / "web"
SCRIPT_PATH = WEB_DIR / "script.js"
HTML_PATH = WEB_DIR / "index.html"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


def _html_text() -> str:
    return HTML_PATH.read_text(encoding="utf-8-sig")


def test_live2d_script_defines_capability_profiler():
    script = _script_text()
    assert "function buildModelCapabilityProfile(" in script
    assert "function resolveMotionSlotCandidates(" in script
    assert "modelCapabilityProfile" in script


def test_live2d_script_defines_parameter_mixer_pipeline():
    script = _script_text()
    assert "function buildMixedParameterFrame(" in script
    assert "function applyMixedParameterFrame(" in script
    assert "function blendEyeOpenValue(" in script


def test_live2d_script_defines_performance_state_machine_hooks():
    script = _script_text()
    assert "const PERFORMANCE_STATES =" in script
    assert "function setPerformanceState(" in script
    assert "function updateSpeechFeatureState(" in script


def test_live2d_script_defines_gesture_scheduler():
    script = _script_text()
    assert "function schedulePerformanceGesture(" in script
    assert "const PERFORMANCE_GESTURES =" in script
    assert "microNod" in script
    assert "sideGlance" in script


def test_live2d_debug_overlay_hooks_exist():
    script = _script_text()
    assert "function setMotionDebugOverlayEnabled(" in script
    assert "function renderMotionDebugOverlay(" in script


def test_live2d_debug_overlay_root_exists():
    html = _html_text()
    assert 'id="motion-debug-overlay"' in html


def test_live2d_script_controls_model_idle_motion_when_performance_engine_changes():
    script = _script_text()
    assert "function syncModelIdleAnimationState(" in script
    assert "stopAllMotions" in script
    assert "model.motion('Idle')" in script
    assert "syncModelIdleAnimationState(window.live2dModel);" in script


def test_live2d_script_scales_idle_motion_by_performance_state():
    script = _script_text()
    assert "function getIdleMotionBlendFactor(" in script
    assert "const idleBlendFactor = getIdleMotionBlendFactor(nowMs);" in script
    assert "angleX: Math.max(-18, Math.min(18, angleXDynamic * idleBlendFactor))" in script
    assert "bodyX: Math.max(-10, Math.min(10, bodyXDynamic * idleBlendFactor))" in script
    assert "bodyY: Math.max(-7.5, Math.min(7.5, bodyYDynamic * idleBlendFactor))" in script


def test_live2d_script_keeps_motion_debug_overlay_hidden_by_default():
    script = _script_text()
    assert "const ALLOW_MOTION_DEBUG_OVERLAY = false;" in script
    assert "motionDebugOverlayEnabled = ALLOW_MOTION_DEBUG_OVERLAY && Boolean(enabled);" in script


def test_live2d_script_smooths_performance_motion_and_idle_return():
    script = _script_text()
    assert "const PERFORMANCE_IDLE_RETURN_FADE_MS =" in script
    assert "function getPerformanceSettleProgress(" in script
    assert "function smoothPerformanceOffsets(" in script
    assert "const smoothedPerformanceOffsets = smoothPerformanceOffsets(targetPerformanceOffsets, dtMs, nowMs);" in script


def test_live2d_script_restores_speaking_presence_with_targeted_constants():
    script = _script_text()
    assert "const SPEAKING_GESTURE_TRIGGER_THRESHOLD = 0.32;" in script
    assert "const SPEAKING_GESTURE_COOLDOWN_MS = 980;" in script
    assert "const SPEAKING_MOTION_SMOOTHING_AT_60FPS = 0.18;" in script
    assert "const SPEAKING_MOTION_GAIN = 1.45;" in script


def test_live2d_script_boosts_body_motion_with_heavier_follow_through():
    script = _script_text()
    assert "const BODY_MOTION_GAIN = 1.7;" in script
    assert "const BODY_PITCH_MOTION_GAIN = 2.35;" in script
    assert "const BODY_ROLL_MOTION_GAIN = 2.15;" in script
    assert "const BODY_MOTION_SMOOTHING_AT_60FPS = 0.09;" in script
    assert "bodyX: clampSymmetric(((speechYawWave * (0.2 + speechPulse * 0.36)) * expressiveScale) * BODY_MOTION_GAIN, 6.4)," in script
    assert "const bodySmoothingAt60Fps = currentPerformanceState === 'speaking' ? BODY_MOTION_SMOOTHING_AT_60FPS : 0.06;" in script


def test_live2d_script_maps_body_pitch_roll_and_breath_slots():
    script = _script_text()
    assert "bodyPitch: ['ParamBodyAngleY', 'ParamBodyAngleY2']," in script
    assert "bodyRoll: ['ParamBodyAngleZ', 'ParamBodyAngleZ2']," in script
    assert "breath: ['ParamBreath']," in script
    assert "'bodyPitch'," in script
    assert "'bodyRoll'," in script
    assert "'breath'," in script


def test_live2d_script_drives_body_pitch_roll_and_breath_in_tracking_and_speaking():
    script = _script_text()
    assert "bodyAngleY: hasParam('ParamBodyAngleY')," in script
    assert "bodyAngleZ: hasParam('ParamBodyAngleZ')," in script
    assert "breath: hasParam('ParamBreath')," in script
    assert "if (support.bodyAngleY) addMixedValue(values, getMotionSlotParamId('bodyPitch') || 'ParamBodyAngleY', (-y * 3.2) + idleBodyY);" in script
    assert "if (support.bodyAngleZ) addMixedValue(values, getMotionSlotParamId('bodyRoll') || 'ParamBodyAngleZ', (x * 2.4) + idleBodyZ);" in script
    assert "if (support.breath) addMixedValue(values, getMotionSlotParamId('breath') || 'ParamBreath', idleBreath);" in script
    assert "bodyY: clampSymmetric(((((speechPitchWave * (0.4 + speechPulse * 0.72)) - 0.08) + (moodPitchBias * 0.12)) * expressiveScale) * BODY_PITCH_MOTION_GAIN, 8.8)," in script
    assert "bodyZ: clampSymmetric(((((speechYawWave * (0.34 + speechPulse * 0.5)) + (speechPitchWave * 0.16)) + (moodAngleBias * 0.24)) * expressiveScale) * BODY_ROLL_MOTION_GAIN, 7.8)," in script
    assert "breath: clamp01(0.16 + speechPulse * 0.3)," in script


def test_live2d_script_strengthens_body_drive_during_non_speaking_states():
    script = _script_text()
    assert "bodyY: (0.34 + Math.sin(nowMs * 0.0012 + 0.4) * 0.16) * subtleScale," in script
    assert "bodyZ: ((stateWave * 0.42) + (Math.sin(nowMs * 0.0016 + 0.3) * 0.12)) * subtleScale," in script
    assert "breath: clamp01(0.16 + subtleScale * 0.3)," in script
    assert "bodyY: subtleScale * 0.22," in script
    assert "bodyZ: (moodAngleBias * 0.14 + Math.sin(nowMs * 0.0014 + 0.6) * 0.1) * subtleScale," in script
    assert "breath: clamp01(0.12 + subtleScale * 0.2)," in script
    assert "bodyY: subtleScale * 0.16," in script
    assert "bodyZ: Math.sin(nowMs * 0.0012 + 0.1) * subtleScale * 0.14," in script
    assert "breath: clamp01(0.1 + subtleScale * 0.16)," in script


def test_live2d_script_expands_idle_body_y_and_vertical_range():
    script = _script_text()
    assert "const IDLE_MOTION_BASE_ANGLE_Y = 1.3;" in script
    assert "const IDLE_MOTION_BASE_BODY_Y = 1.15;" in script
    assert "let idleMotionBodyY = IDLE_MOTION_BASE_BODY_Y;" in script
    assert "idleMotionBodyY = IDLE_MOTION_BASE_BODY_Y * s;" in script
    assert "const bodyYDynamic =" in script
    assert "angleY: Math.max(-15, Math.min(15, angleYDynamic * idleBlendFactor))" in script
    assert "bodyY: Math.max(-7.5, Math.min(7.5, bodyYDynamic * idleBlendFactor))" in script
    assert "bodyY: Math.sin(idleMotionPhase * 0.62 + 0.9) * idleMotionBodyY * idleBlendFactor," in script
