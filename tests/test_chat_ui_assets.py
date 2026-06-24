from pathlib import Path
import json
import re
import subprocess


WEB_DIR = Path(__file__).resolve().parents[1] / "assets" / "web"
STYLE_PATH = WEB_DIR / "style.css"
SCRIPT_PATH = WEB_DIR / "script.js"
EXPECTED_RUNTIME_SCRIPTS = [
    "runtime_bootstrap.js",
    "runtime_live2d_model.js",
    "runtime_image_avatar.js",
    "runtime_motion_state.js",
    "runtime_gesture_engine.js",
    "runtime_head_pat.js",
    "runtime_auto_blink_tracking.js",
    "runtime_expression.js",
    "runtime_chat_state.js",
    "runtime_ui_strings.js",
    "runtime_attachments.js",
    "runtime_chat_panel_controls.js",
    "runtime_promise_panel.js",
    "runtime_goal_panel.js",
    "runtime_message_helpers.js",
    "runtime_mood_obsidian.js",
    "runtime_message_rendering.js",
    "runtime_chat_flow.js",
    "runtime_bridge.js",
    "runtime_lipsync.js",
    "runtime_live2d_parameter_core.js",
    "runtime_live2d_parameter_ui.js",
    "runtime_live2d_parameters.js",
    "script.js",
]


def _rule_block(selector: str) -> str:
    css = STYLE_PATH.read_text(encoding="utf-8-sig")
    pattern = rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}"
    match = re.search(pattern, css, re.DOTALL)
    assert match, f"{selector} 규칙을 찾지 못했습니다."
    return match.group("body")


def _script_text() -> str:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    script_paths = re.findall(r'<script src="([^"]+\.js)"></script>', html)
    runtime_paths = [
        path for path in script_paths
        if not path.startswith("lib/") and not path.startswith("qrc:")
    ]
    if runtime_paths:
        return "\n".join((WEB_DIR / path).read_text(encoding="utf-8-sig") for path in runtime_paths)
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


def _runtime_motion_state_text() -> str:
    return (WEB_DIR / "runtime_motion_state.js").read_text(encoding="utf-8-sig")


def _gesture_runtime_text() -> str:
    return (WEB_DIR / "runtime_gesture_engine.js").read_text(encoding="utf-8-sig")


def _live2d_parameter_runtime_text() -> str:
    return "\n".join(
        (WEB_DIR / path).read_text(encoding="utf-8-sig")
        for path in [
            "runtime_live2d_parameter_core.js",
            "runtime_live2d_parameter_ui.js",
            "runtime_live2d_parameters.js",
        ]
    )


def _run_live2d_parameter_runtime_case(case_script: str) -> dict:
    runtime_paths = [
        str(WEB_DIR / "runtime_live2d_parameter_core.js"),
        str(WEB_DIR / "runtime_live2d_parameter_ui.js"),
        str(WEB_DIR / "runtime_live2d_parameters.js"),
    ]
    node_script = f"""
const fs = require('fs');
const vm = require('vm');

const runtimeSource = {json.dumps(runtime_paths)}.map((path) => fs.readFileSync(path, 'utf8')).join('\\n');
const caseSource = {json.dumps(case_script)};
const context = {{
    window: {{}},
    console: {{
        warn: () => {{}},
    }},
    result: null,
}};

vm.createContext(context);
vm.runInContext(runtimeSource + '\\n' + caseSource, context, {{
    filename: 'runtime_live2d_parameters.js',
}});
process.stdout.write(JSON.stringify(context.result));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _run_image_avatar_runtime_case(case_script: str) -> dict:
    runtime_path = str(WEB_DIR / "runtime_image_avatar.js")
    node_script = f"""
const fs = require('fs');
const vm = require('vm');

const runtimeSource = fs.readFileSync({json.dumps(runtime_path)}, 'utf8');
const caseSource = {json.dumps(case_script)};
const stageChildren = [];
function makePoint() {{
    return {{
        x: 0,
        y: 0,
        set(x, y) {{
            this.x = x;
            this.y = y === undefined ? x : y;
        }},
    }};
}}
const context = {{
    window: {{
        innerWidth: 1000,
        innerHeight: 800,
        eneModelConfig: {{}},
    }},
    PIXI: {{
        Sprite: class {{
            constructor(texture) {{
                this.texture = texture;
                this.anchor = makePoint();
                this.scale = makePoint();
                this.destroyed = false;
            }}
            destroy() {{
                this.destroyed = true;
            }}
        }},
        Texture: {{
            from: (path) => ({{ path }}),
        }},
        Text: class {{
            constructor(text) {{
                this.text = text;
                this.anchor = makePoint();
            }}
            destroy() {{}}
        }},
    }},
    app: {{
        stage: {{
            children: stageChildren,
            addChild(child) {{
                stageChildren.push(child);
            }},
            removeChild(child) {{
                const index = stageChildren.indexOf(child);
                if (index >= 0) {{
                    stageChildren.splice(index, 1);
                }}
            }},
        }},
    }},
    console: {{
        warn: () => {{}},
        log: () => {{}},
    }},
    result: null,
}};
context.window.PIXI = context.PIXI;
context.window.app = context.app;

vm.createContext(context);
vm.runInContext(runtimeSource + '\\n' + caseSource, context, {{
    filename: 'runtime_image_avatar.js',
}});
process.stdout.write(JSON.stringify(context.result));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _run_head_pat_runtime_case(case_script: str) -> dict:
    runtime_paths = [
        str(WEB_DIR / "runtime_motion_state.js"),
        str(WEB_DIR / "runtime_head_pat.js"),
    ]
    node_script = f"""
const fs = require('fs');
const vm = require('vm');

const runtimeSource = {json.dumps(runtime_paths)}.map((path) => fs.readFileSync(path, 'utf8')).join('\\n');
const preludeSource = 'function isImageAvatarMode() {{ return Boolean(window.imageMode); }}';
const caseSource = {json.dumps(case_script)};
const changeCalls = [];
const timeoutCallbacks = [];
let headPatCount = 0;
const context = {{
    window: {{
        live2dModel: null,
        pyBridge: {{
            increment_head_pat_count_from_js() {{
                headPatCount += 1;
            }},
        }},
    }},
    document: {{
        getElementById(id) {{
            if (id === 'chat-container') {{
                return {{
                    contains() {{
                        return false;
                    }},
                }};
            }}
            return null;
        }},
    }},
    performance: {{
        now() {{
            return 1000;
        }},
    }},
    setTimeout(callback) {{
        timeoutCallbacks.push(callback);
        return timeoutCallbacks.length;
    }},
    clearTimeout() {{}},
    changeExpression(emotion, options) {{
        changeCalls.push({{ emotion, options: options || {{}} }});
    }},
    console: {{
        warn: () => {{}},
        log: () => {{}},
    }},
    imageAvatarState: {{
        sprite: null,
    }},
    changeCalls,
    timeoutCallbacks,
    getHeadPatCount() {{
        return headPatCount;
    }},
    result: null,
}};
context.window.imageAvatarState = context.imageAvatarState;

vm.createContext(context);
vm.runInContext(preludeSource + '\\n' + runtimeSource + '\\n' + caseSource + '\\nresult = {{ ...result, changeCalls, headPatCount: getHeadPatCount(), timeoutCount: timeoutCallbacks.length }};', context, {{
    filename: 'runtime_head_pat.js',
}});
process.stdout.write(JSON.stringify(context.result));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_tracking_runtime_supports_body_y_and_z_parameter_map():
    script = _runtime_motion_state_text()

    assert "bodyAngleY: resolveParam('bodyAngleY', 'ParamBodyAngleY')" in script
    assert "bodyAngleZ: resolveParam('bodyAngleZ', 'ParamBodyAngleZ')" in script
    assert "if (support.bodyAngleY) coreModel.setParameterValueById(support.bodyAngleY, idleBodyY + gestureBodyY);" in script
    assert "if (support.bodyAngleZ) coreModel.setParameterValueById(support.bodyAngleZ, idleBodyZ + gestureBodyZ);" in script


def test_tracking_runtime_supports_synthetic_gesture_offsets():
    script = _runtime_motion_state_text()

    assert "window.setSyntheticGestureOffsets = function (offsets = {})" in script
    assert "angleZ: resolveParam('angleZ', 'ParamAngleZ')" in script
    assert "const gestureOffsets = syntheticGestureOffsets || createEmptySyntheticGestureOffsets();" in script
    assert "if (support.angleZ) coreModel.setParameterValueById(support.angleZ, gestureAngleZ);" in script
    assert "if (support.eyeBallX) coreModel.setParameterValueById(support.eyeBallX, (x * 0.8) + gestureEyeX);" in script


def test_gesture_engine_exposes_chat_gesture_player():
    script = _gesture_runtime_text()

    assert "const GESTURE_INTENSITY = 1.0;" in script
    assert "const GESTURE_SPEED = 0.75;" in script
    assert "const SPEECH_GESTURE_MIN_DELAY_MS = 700;" in script
    assert "const SPEECH_GESTURE_MAX_DELAY_MS = 3200;" in script
    assert "const SYNTHETIC_GESTURES = {" in script
    for gesture in ["nod", "bow", "shake", "surprise", "tilt", "sway"]:
        assert f"{gesture}:" in script
    assert "window.playSyntheticGesture = playSyntheticGesture;" in script
    assert "window.scheduleSyntheticGestureDuringSpeech = scheduleSyntheticGestureDuringSpeech;" in script
    assert "window.notifySyntheticGestureSpeechActivity = notifySyntheticGestureSpeechActivity;" in script
    assert "window.setSyntheticGestureScale = setSyntheticGestureScale;" in script
    assert "const IDLE_SYNTHETIC_GESTURE_FREQUENCIES = {" in script
    assert "const IDLE_SYNTHETIC_GESTURES = [" in script
    assert "function setIdleSyntheticGestureConfig(enabled, frequency)" in script
    assert "function scheduleNextIdleSyntheticGesture()" in script
    assert "window.setIdleSyntheticGestureConfig = setIdleSyntheticGestureConfig;" in script
    assert "lastSyntheticSpeechActivityAt" in script
    assert "window.stopSyntheticGesture = stopSyntheticGesture;" in script
    assert "durationMs / GESTURE_SPEED" in script


def test_idle_synthetic_gestures_are_visible_but_settle_stays_subtle():
    script = _gesture_runtime_text()

    assert '{ t: 0.28, value: { angleX: -8, eyeX: -0.28 } }' in script
    assert '{ t: 0.58, value: { angleX: 8, eyeX: 0.28 } }' in script
    assert '{ t: 0.36, value: { angleY: -7, eyeY: -0.12 } }' in script
    assert '{ t: 0.68, value: { angleY: 5, eyeY: 0.08 } }' in script
    assert '{ t: 0.38, value: { angleX: -6, angleZ: -11, eyeX: 0.12 } }' in script
    assert '{ t: 0.72, value: { angleX: -5, angleZ: -9, eyeX: 0.08 } }' in script
    assert '{ t: 0.35, value: { bodyY: -0.8, breath: 0.2 } }' in script
    assert '{ t: 0.70, value: { bodyY: 0.4, breath: 0.1 } }' in script


def test_web_runtime_is_split_into_ordered_scripts():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    runtime_scripts = [
        path for path in re.findall(r'<script src="([^"]+\.js)"></script>', html)
        if not path.startswith("lib/") and not path.startswith("qrc:")
    ]

    assert runtime_scripts == EXPECTED_RUNTIME_SCRIPTS
    assert len(SCRIPT_PATH.read_text(encoding="utf-8-sig").splitlines()) <= 80
    for script_name in EXPECTED_RUNTIME_SCRIPTS[:-1]:
        assert (WEB_DIR / script_name).exists()


def test_web_runtime_default_model_path_uses_bundled_hiyori():
    bootstrap = (WEB_DIR / "runtime_bootstrap.js").read_text(encoding="utf-8-sig")

    assert "const DEFAULT_MODEL_PATH = '../live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json';" in bootstrap


def test_web_runtime_initializers_load_after_called_dependencies():
    script_order = {script_name: index for index, script_name in enumerate(EXPECTED_RUNTIME_SCRIPTS)}

    mood_initializer_index = script_order["runtime_mood_obsidian.js"]
    for dependency in [
        "runtime_message_helpers.js",
        "runtime_promise_panel.js",
        "runtime_goal_panel.js",
    ]:
        assert script_order[dependency] < mood_initializer_index


def test_gesture_runtime_loads_after_motion_state_and_before_bridge():
    script_order = {script_name: index for index, script_name in enumerate(EXPECTED_RUNTIME_SCRIPTS)}

    assert script_order["runtime_motion_state.js"] < script_order["runtime_gesture_engine.js"]
    assert script_order["runtime_gesture_engine.js"] < script_order["runtime_bridge.js"]


def test_bridge_connects_gesture_signal_to_runtime_player():
    script = (WEB_DIR / "runtime_bridge.js").read_text(encoding="utf-8-sig")

    assert "window.pyBridge.gesture_requested.connect(function (gesture)" in script
    assert "window.scheduleSyntheticGestureDuringSpeech(gesture);" in script
    assert "window.playSyntheticGesture(gesture);" in script
    assert "window.notifySyntheticGestureSpeechActivity();" in script


def test_live2d_parameter_runtime_loads_after_live2d_writers():
    script_order = {script_name: index for index, script_name in enumerate(EXPECTED_RUNTIME_SCRIPTS)}
    parameter_index = script_order["runtime_live2d_parameter_core.js"]
    for dependency in [
        "runtime_live2d_model.js",
        "runtime_motion_state.js",
        "runtime_head_pat.js",
        "runtime_auto_blink_tracking.js",
        "runtime_expression.js",
        "runtime_lipsync.js",
    ]:
        assert script_order[dependency] < parameter_index
    assert script_order["runtime_live2d_parameter_core.js"] < script_order["runtime_live2d_parameter_ui.js"]
    assert script_order["runtime_live2d_parameter_ui.js"] < script_order["runtime_live2d_parameters.js"]


def test_image_avatar_runtime_loads_between_model_and_motion_state():
    script_order = {script_name: index for index, script_name in enumerate(EXPECTED_RUNTIME_SCRIPTS)}

    assert script_order["runtime_live2d_model.js"] < script_order["runtime_image_avatar.js"]
    assert script_order["runtime_image_avatar.js"] < script_order["runtime_motion_state.js"]


def test_image_avatar_runtime_exposes_mode_hooks():
    script = _script_text()

    assert "const imageAvatarState = {" in script
    assert "function isImageAvatarMode()" in script
    assert "function applyImageAvatarSettings(config)" in script
    assert "function changeImageAvatarEmotion(emotion)" in script
    assert "function applyImageAvatarMouthValue(value)" in script
    assert "window.applyImageAvatarSettings = applyImageAvatarSettings;" in script


def test_live2d_loader_skips_model_when_image_avatar_mode_is_active():
    script = _script_text()

    assert "if (isImageAvatarMode())" in script
    assert "removeCurrentModelArtifacts();" in script
    assert "applyImageAvatarSettings(window.eneModelConfig);" in script


def test_live2d_loader_forces_reload_after_switching_back_from_image_avatar_mode():
    script = _script_text()

    assert "currentModelPath = '';\n        currentEmotionsBasePath = '';" in script


def test_image_avatar_mode_invalidates_pending_live2d_model_loads():
    script = _script_text()

    assert "currentModelLoadToken++;\n        removeCurrentModelArtifacts();" in script
    assert (
        "if (isImageAvatarMode()) {\n"
        "            if (typeof model.destroy === 'function') {\n"
        "                model.destroy();\n"
        "            }\n"
        "            return;\n"
        "        }\n\n"
        "        if (requestToken !== currentModelLoadToken)"
    ) in script


def test_stale_live2d_load_failure_does_not_show_error_in_image_avatar_mode():
    script = _script_text()

    assert (
        "} catch (error) {\n"
        "        if (requestToken !== currentModelLoadToken || isImageAvatarMode()) {\n"
        "            return;\n"
        "        }\n"
        "        console.error(\"Failed to load Live2D model\");"
    ) in script


def test_expression_change_routes_to_image_avatar_in_image_mode():
    script = _script_text()

    assert "if (isImageAvatarMode())" in script
    assert "changeImageAvatarEmotion(emotion);" in script


def test_lipsync_routes_mouth_value_to_image_avatar_bounce():
    script = _script_text()

    assert "if (isImageAvatarMode())" in script
    assert "applyImageAvatarMouthValue(value);" in script


def test_apply_mouth_pose_routes_image_avatar_before_live2d_mouth_state():
    script = _script_text()

    assert (
        "const poseSource = normalizeMouthPoseSource(pose.source);\n"
        "    const open = normalizeMouthPoseNumber(Number(pose.open));\n\n"
        "    if (isImageAvatarMode()) {\n"
        "        applyImageAvatarMouthValue(open);\n"
        "        return;\n"
        "    }\n\n"
        "    lastSpeechAt = performance.now();"
    ) in script


def test_live2d_parameter_button_hides_in_image_avatar_mode():
    script = _script_text()

    assert "function syncLive2DParameterVisibilityForAvatarMode()" in script
    assert "live2dParametersButton.style.display = isImageAvatarMode() ? 'none' : 'inline-flex';" in script


def test_image_avatar_runtime_falls_back_to_normal_emotion_image():
    result = _run_image_avatar_runtime_case(
        """
applyImageAvatarSettings({
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'normal.png',
        },
    },
});
result = {
    joy: getImageAvatarImageForEmotion('joy'),
    normal: getImageAvatarImageForEmotion('normal'),
};
"""
    )

    assert result == {
        "joy": "normal.png",
        "normal": "normal.png",
    }


def test_image_avatar_mouth_value_bounces_y_without_changing_saved_placement():
    result = _run_image_avatar_runtime_case(
        """
applyImageAvatarSettings({
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'normal.png',
        },
        placement: {
            scale: 1.5,
            xPercent: 25,
            yPercent: 75,
        },
    },
});
const before = {
    baseX: imageAvatarState.baseX,
    baseY: imageAvatarState.baseY,
    scale: imageAvatarState.scale,
    spriteY: imageAvatarState.sprite.y,
};
applyImageAvatarMouthValue(0.5);
const during = {
    baseX: imageAvatarState.baseX,
    baseY: imageAvatarState.baseY,
    scale: imageAvatarState.scale,
    spriteY: imageAvatarState.sprite.y,
};
applyImageAvatarMouthValue(0);
const after = {
    baseX: imageAvatarState.baseX,
    baseY: imageAvatarState.baseY,
    scale: imageAvatarState.scale,
    spriteY: imageAvatarState.sprite.y,
};
result = { before, during, after };
"""
    )

    assert result == {
        "before": {"baseX": 250, "baseY": 600, "scale": 1.5, "spriteY": 600},
        "during": {"baseX": 250, "baseY": 600, "scale": 1.5, "spriteY": 595},
        "after": {"baseX": 250, "baseY": 600, "scale": 1.5, "spriteY": 600},
    }


def test_image_avatar_settings_preview_emotion_uses_selected_image_and_keeps_runtime_changes():
    result = _run_image_avatar_runtime_case(
        """
applyImageAvatarSettings({
    avatarMode: 'image',
    imageAvatarPreviewEmotion: 'smile',
    imageAvatar: {
        images: {
            normal: {
                path: 'normal.png',
                storageKey: 'avatar_images/sample/normal.png',
                placement: {
                    scale: 1,
                    xPercent: 50,
                    yPercent: 50,
                },
            },
            smile: {
                path: 'smile.png',
                storageKey: 'avatar_images/sample/smile.png',
                placement: {
                    scale: 1.4,
                    xPercent: 25,
                    yPercent: 75,
                },
            },
        },
    },
});
const preview = {
    emotion: imageAvatarState.currentEmotion,
    texturePath: imageAvatarState.sprite.texture.path,
    baseX: imageAvatarState.baseX,
    baseY: imageAvatarState.baseY,
    scale: imageAvatarState.scale,
};
changeImageAvatarEmotion('normal');
const runtime = {
    emotion: imageAvatarState.currentEmotion,
    texturePath: imageAvatarState.sprite.texture.path,
    baseX: imageAvatarState.baseX,
    baseY: imageAvatarState.baseY,
    scale: imageAvatarState.scale,
};
result = { preview, runtime };
"""
    )

    assert result == {
        "preview": {
            "emotion": "smile",
            "texturePath": "smile.png",
            "baseX": 250,
            "baseY": 600,
            "scale": 1.4,
        },
        "runtime": {
            "emotion": "normal",
            "texturePath": "normal.png",
            "baseX": 500,
            "baseY": 400,
            "scale": 1,
        },
    }


def test_image_avatar_texture_error_removes_sprite_and_shows_error_text():
    result = _run_image_avatar_runtime_case(
        """
let errorCallback = null;
PIXI.Texture.from = (path) => ({
    path,
    baseTexture: {
        on(eventName, callback) {
            if (eventName === 'error') {
                errorCallback = callback;
            }
        },
    },
});
applyImageAvatarSettings({
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'missing.png',
        },
    },
});
const registered = Boolean(errorCallback);
if (errorCallback) {
    errorCallback(new Error('missing file'));
}
result = {
    registered,
    spriteRemoved: imageAvatarState.sprite === null,
    errorTextShown: Boolean(imageAvatarState.errorText),
    childCount: app.stage.children.length,
};
"""
    )

    assert result == {
        "registered": True,
        "spriteRemoved": True,
        "errorTextShown": True,
        "childCount": 1,
    }


def test_image_avatar_texture_error_listener_is_bound_once_per_texture():
    result = _run_image_avatar_runtime_case(
        """
let listenerCount = 0;
const texture = {
    path: 'normal.png',
    baseTexture: {
        on(eventName, callback) {
            if (eventName === 'error') {
                listenerCount += 1;
            }
        },
    },
};
PIXI.Texture.from = () => texture;
applyImageAvatarSettings({
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'normal.png',
        },
    },
});
changeImageAvatarEmotion('normal');
changeImageAvatarEmotion('normal');
result = { listenerCount };
"""
    )

    assert result == {"listenerCount": 1}


def test_image_avatar_repeated_texture_failure_keeps_error_visible():
    result = _run_image_avatar_runtime_case(
        """
let errorCallback = null;
let listenerCount = 0;
const failedTexture = {
    path: 'missing.png',
    baseTexture: {
        on(eventName, callback) {
            if (eventName === 'error') {
                listenerCount += 1;
                errorCallback = callback;
            }
        },
    },
};
PIXI.Texture.from = () => failedTexture;
applyImageAvatarSettings({
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'missing.png',
        },
    },
});
if (errorCallback) {
    errorCallback(new Error('missing file'));
}
const afterFirstFailure = {
    listenerCount,
    spriteRemoved: imageAvatarState.sprite === null,
    errorTextShown: Boolean(imageAvatarState.errorText),
};
applyImageAvatarSettings({
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'missing.png',
        },
    },
});
const afterRetry = {
    listenerCount,
    spriteRemoved: imageAvatarState.sprite === null,
    errorTextShown: Boolean(imageAvatarState.errorText),
};
result = { afterFirstFailure, afterRetry };
"""
    )

    assert result == {
        "afterFirstFailure": {
            "listenerCount": 1,
            "spriteRemoved": True,
            "errorTextShown": True,
        },
        "afterRetry": {
            "listenerCount": 1,
            "spriteRemoved": True,
            "errorTextShown": True,
        },
    }


def test_image_avatar_failed_texture_path_can_recover_with_new_texture():
    result = _run_image_avatar_runtime_case(
        """
let errorCallback = null;
let mode = 'fail';
const textureCalls = [];
const failedTexture = {
    path: 'avatar.png',
    baseTexture: {
        on(eventName, callback) {
            if (eventName === 'error') {
                errorCallback = callback;
            }
        },
    },
};
const recoveredTexture = {
    path: 'avatar.png',
    baseTexture: {},
};
PIXI.Texture.from = (path) => {
    textureCalls.push(path);
    return mode === 'fail' ? failedTexture : recoveredTexture;
};
const config = {
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'avatar.png',
        },
    },
};
applyImageAvatarSettings(config);
if (errorCallback) {
    errorCallback(new Error('missing file'));
}
const afterFailure = {
    spriteRemoved: imageAvatarState.sprite === null,
    errorTextShown: Boolean(imageAvatarState.errorText),
};
mode = 'recover';
applyImageAvatarSettings(config);
const afterRecovery = {
    textureCalls,
    spriteTexturePath: imageAvatarState.sprite && imageAvatarState.sprite.texture.path,
    errorTextShown: Boolean(imageAvatarState.errorText),
};
result = { afterFailure, afterRecovery };
"""
    )

    assert result == {
        "afterFailure": {
            "spriteRemoved": True,
            "errorTextShown": True,
        },
        "afterRecovery": {
            "textureCalls": ["avatar.png", "avatar.png"],
            "spriteTexturePath": "avatar.png",
            "errorTextShown": False,
        },
    }


def test_image_avatar_failed_cached_texture_can_recover_when_it_becomes_valid():
    result = _run_image_avatar_runtime_case(
        """
let errorCallback = null;
const textureCalls = [];
const cachedTexture = {
    path: 'avatar.png',
    valid: false,
    baseTexture: {
        valid: false,
        on(eventName, callback) {
            if (eventName === 'error') {
                errorCallback = callback;
            }
        },
    },
};
PIXI.Texture.from = (path) => {
    textureCalls.push(path);
    return cachedTexture;
};
const config = {
    avatarMode: 'image',
    imageAvatar: {
        images: {
            normal: 'avatar.png',
        },
    },
};
applyImageAvatarSettings(config);
if (errorCallback) {
    errorCallback(new Error('missing file'));
}
const afterFailure = {
    spriteRemoved: imageAvatarState.sprite === null,
    errorTextShown: Boolean(imageAvatarState.errorText),
};
cachedTexture.valid = true;
cachedTexture.baseTexture.valid = true;
applyImageAvatarSettings(config);
const afterRecovery = {
    textureCalls,
    spriteTexturePath: imageAvatarState.sprite && imageAvatarState.sprite.texture.path,
    errorTextShown: Boolean(imageAvatarState.errorText),
};
result = { afterFailure, afterRecovery };
"""
    )

    assert result == {
        "afterFailure": {
            "spriteRemoved": True,
            "errorTextShown": True,
        },
        "afterRecovery": {
            "textureCalls": ["avatar.png", "avatar.png"],
            "spriteTexturePath": "avatar.png",
            "errorTextShown": False,
        },
    }


def test_head_pat_uses_whole_image_avatar_sprite_bounds_in_image_mode():
    result = _run_head_pat_runtime_case(
        """
window.imageMode = true;
headPatActiveEmotion = 'pat_start';
headPatEndEmotion = 'pat_end';
currentEmotionTag = 'normal';
imageAvatarState.sprite = {
    getBounds() {
        return { x: 100, y: 80, width: 240, height: 360 };
    },
};
const inside = isHeadPatPoint(220, 250);
const outside = isHeadPatPoint(360, 250);
let prevented = false;
const eventTarget = {
    setPointerCapture() {},
    releasePointerCapture() {},
};
onHeadPatPointerDown({
    pointerType: 'mouse',
    button: 0,
    pointerId: 7,
    clientX: 220,
    clientY: 250,
    target: eventTarget,
    preventDefault() {
        prevented = true;
    },
});
onHeadPatPointerUp({
    pointerId: 7,
    target: eventTarget,
});
result = {
    inside,
    outside,
    prevented,
    isHeadPatting,
};
"""
    )

    assert result == {
        "inside": True,
        "outside": False,
        "prevented": True,
        "isHeadPatting": False,
        "changeCalls": [
            {"emotion": "pat_start", "options": {"durationMs": 180}},
            {"emotion": "pat_end", "options": {"durationMs": 220}},
        ],
        "headPatCount": 1,
        "timeoutCount": 1,
    }


def test_live2d_parameter_runtime_does_not_redeclare_chat_state_globals():
    runtime = _live2d_parameter_runtime_text()

    for name in [
        "live2dParametersButton",
        "live2dParametersSearch",
        "live2dParametersSaveButton",
        "live2dParametersResetButton",
        "live2dParametersCloseButton",
    ]:
        assert not re.search(rf"^(?:const|let)\s+{name}\s*=", runtime, re.MULTILINE)


def test_live2d_parameter_inspector_markup_exists():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    css = STYLE_PATH.read_text(encoding="utf-8-sig")

    assert 'id="live2d-parameters-floating-btn" type="button"' in html
    assert 'aria-label="Live2D 파라미터"' in html
    assert 'id="live2d-parameters-panel"' in html
    assert 'id="live2d-parameters-search" type="search" placeholder="파라미터 검색" aria-label="파라미터 검색"' in html
    assert 'id="live2d-parameters-tabs" role="tablist"' in html
    assert 'id="live2d-parameters-tab-recommended"' not in html
    assert 'role="tab" aria-selected="true" aria-controls="live2d-parameters-list"' in html
    assert 'id="live2d-parameters-tab-all"' in html
    assert 'id="live2d-parameters-tab-favorites"' in html
    assert '>즐겨찾기</button>' in html
    assert 'id="live2d-parameters-list" role="tabpanel" aria-labelledby="live2d-parameters-tab-all"' in html
    assert 'id="live2d-parameters-save-btn"' in html
    assert '장식 조절용입니다.' in html
    assert "#live2d-parameters-search:focus-visible" in css


def test_live2d_parameter_runtime_applies_overrides_in_late_internal_model_hook():
    script = _script_text()

    assert "const LIVE2D_PARAMETER_RECOMMENDED_EXCLUDE_KEYWORDS = [" in script
    assert "'ParamEye'," in script
    assert "'ParamMouth'," in script
    assert "function applyLive2DParameterOverrides(coreModel = getLive2DParameterCoreModel())" in script
    assert "removedValues: new Set()" in script
    assert "live2dParameterState.removedValues.forEach" in script
    assert "applyHookModel: null" in script
    assert "hookedInternalModels: new WeakSet()" in script
    assert "internalModel.on('beforeModelUpdate', () => {" in script
    assert "currentModel && currentModel.internalModel === internalModel" in script
    assert "applyLive2DParameterOverrides(coreModel);" in script
    assert "window.onLive2DParameterModelChanged = function" in script


def test_live2d_parameter_runtime_renders_inspector_controls():
    script = _script_text()

    assert "function collectLive2DParameterMetadata()" in script
    assert "function readLive2DParameterIndexedValue(" in script
    assert "getParameterDefaultValue" in script
    assert "getParameterMinimumValue" in script
    assert "getParameterMaximumValue" in script
    assert "coreModel._model && coreModel._model.parameters" in script
    assert "function renderLive2DParameterInspector()" in script
    assert "function setLive2DParameterMetadataStatus(" in script
    assert "function setLive2DParameterPanelOpen(open)" in script
    assert "function saveLive2DParameterOverrides()" in script
    assert "function buildLive2DParameterSavePayload()" in script
    assert "function resetLive2DParameterOverride(paramId)" in script
    assert "live2dParameterState.removedValues.add(paramId);" in script
    assert "live2dParametersSaveButton.disabled = live2dParameterState.metadataStatus !== 'ready';" in script
    assert "live2dParametersSearch.addEventListener('input'" in script
    assert "live2dParametersSaveButton.addEventListener('click'" in script
    assert "window.pyBridge.save_live2d_parameter_overrides" in script


def test_live2d_model_notifies_parameter_runtime_after_model_load():
    script = _script_text()

    assert "window.onLive2DParameterModelChanged(window.eneModelConfig);" in script
    assert "parameterOverrides" in script
    assert "modelKey" in script


def test_live2d_parameter_runtime_merges_dirty_removes_and_skips_invalid_values():
    result = _run_live2d_parameter_runtime_case(
        """
const calls = [];
const validIds = [
    'ParamDecorSaved',
    'ParamDecorDirty',
    'ParamDecorRemoved',
    'ParamDecorNonFinite',
];
window.live2dModel = {
    internalModel: {
        coreModel: {
            getParameterIndex: (paramId) => (
                paramId === 'ParamDecorVirtualMissing'
                    ? validIds.length
                    : validIds.indexOf(paramId)
            ),
            getParameterCount: () => validIds.length,
            setParameterValueById: (paramId, value) => calls.push([paramId, value]),
        },
    },
};

live2dParameterState.values = {
    ParamDecorSaved: 1,
    ParamDecorDirty: 2,
    ParamDecorRemoved: 3,
    ParamDecorNonFinite: 'not-a-number',
    ParamDecorVirtualMissing: 4,
};
live2dParameterState.dirtyValues = {
    ParamDecorDirty: 20,
};
live2dParameterState.removedValues = new Set(['ParamDecorRemoved']);

window.applyLive2DParameterOverrides();
result = { calls };
"""
    )

    assert result == {
        "calls": [
            ["ParamDecorSaved", 1],
            ["ParamDecorDirty", 20],
        ],
    }


def test_live2d_parameter_runtime_never_applies_expression_sensitive_overrides():
    result = _run_live2d_parameter_runtime_case(
        """
const calls = [];
const validIds = ['ParamRibbon', 'ParamEyeLOpen', 'ParamMouthOpenY', 'ParamAngleX'];
window.live2dModel = {
    internalModel: {
        coreModel: {
            getParameterIndex: (paramId) => validIds.indexOf(paramId),
            getParameterCount: () => validIds.length,
            setParameterValueById: (paramId, value) => calls.push([paramId, value]),
        },
    },
};

live2dParameterState.values = {
    ParamRibbon: 0.8,
    ParamEyeLOpen: 0,
    ParamMouthOpenY: 1,
    ParamAngleX: 30,
};

window.applyLive2DParameterOverrides();
result = { calls };
"""
    )

    assert result == {
        "calls": [["ParamRibbon", 0.8]],
    }


def test_live2d_parameter_runtime_hooks_each_model_once_and_ignores_stale_hooks():
    result = _run_live2d_parameter_runtime_case(
        """
function makeModel() {
    const coreModel = {
        calls: [],
        getParameterIndex: () => 0,
        getParameterCount: () => 1,
        setParameterValueById(paramId, value) {
            this.calls.push([paramId, value]);
        },
    };
    const internalModel = {
        coreModel,
        listeners: [],
        on(eventName, callback) {
            if (eventName === 'beforeModelUpdate') {
                this.listeners.push(callback);
            }
        },
    };
    return { internalModel };
}

const modelA = makeModel();
const modelB = makeModel();

window.live2dModel = modelA;
window.onLive2DParameterModelChanged({
    modelKey: 'A',
    parameterOverrides: { values: { ParamDecor: 1 } },
});

window.live2dModel = modelB;
window.onLive2DParameterModelChanged({
    modelKey: 'B',
    parameterOverrides: { values: { ParamDecor: 2 } },
});

window.live2dModel = modelA;
window.onLive2DParameterModelChanged({
    modelKey: 'A-again',
    parameterOverrides: { values: { ParamDecor: 3 } },
});

window.live2dModel = modelB;
window.onLive2DParameterModelChanged({
    modelKey: 'B-current',
    parameterOverrides: { values: { ParamDecor: 4 } },
});

const bCallCountBeforeStaleAUpdate = modelB.internalModel.coreModel.calls.length;
modelA.internalModel.listeners[0]();

result = {
    aListenerCount: modelA.internalModel.listeners.length,
    bCallsFromStaleAUpdate: modelB.internalModel.coreModel.calls.length - bCallCountBeforeStaleAUpdate,
};
"""
    )

    assert result == {
        "aListenerCount": 1,
        "bCallsFromStaleAUpdate": 0,
    }


def test_live2d_parameter_metadata_reads_getters_and_parameter_fallbacks():
    result = _run_live2d_parameter_runtime_case(
        """
const getterCoreModel = {
    getParameterIds: () => ['ParamDecorA', 'ParamEyeLOpen'],
    getParameterValueById: (paramId) => ({ ParamDecorA: 0.75, ParamEyeLOpen: 1 }[paramId]),
    getParameterDefaultValue: (index) => {
        if (typeof index !== 'number') throw new Error('index required');
        return [0.25, 1][index];
    },
    getParameterMinimumValue: (index) => {
        if (typeof index !== 'number') throw new Error('index required');
        return [-0.5, 0][index];
    },
    getParameterMaximumValue: (index) => {
        if (typeof index !== 'number') throw new Error('index required');
        return [1.5, 1][index];
    },
};
window.live2dModel = { internalModel: { coreModel: getterCoreModel } };
const getterMetadata = collectLive2DParameterMetadata();

const fallbackCoreModel = {
    _model: {
        parameters: {
            ids: ['ParamDecorB'],
            values: [0.4],
            defaultValues: [0.1],
            minimumValues: [0.2],
            maximumValues: [0.3],
        },
    },
};
window.live2dModel = { internalModel: { coreModel: fallbackCoreModel } };
const fallbackMetadata = collectLive2DParameterMetadata();

result = {
    getterMetadata,
    fallbackMetadata,
};
"""
    )

    assert result == {
        "getterMetadata": [
            {
                "id": "ParamDecorA",
                "current": 0.75,
                "default": 0.25,
                "min": -0.5,
                "max": 1.5,
                "recommended": True,
                "displayName": "",
                "groupId": "",
                "groupName": "",
            },
            {
                "id": "ParamEyeLOpen",
                "current": 1,
                "default": 1,
                "min": 0,
                "max": 1,
                "recommended": False,
                "displayName": "",
                "groupId": "",
                "groupName": "",
            },
        ],
        "fallbackMetadata": [
            {
                "id": "ParamDecorB",
                "current": 0.4,
                "default": 0.1,
                "min": 0.1,
                "max": 0.4,
                "recommended": True,
                "displayName": "",
                "groupId": "",
                "groupName": "",
            },
        ],
    }


def test_live2d_parameter_metadata_uses_display_info_from_model_config():
    result = _run_live2d_parameter_runtime_case(
        """
const coreModel = {
    getParameterIds: () => ['ParamRibbon', 'ParamEyeLOpen'],
    getParameterValueById: () => 0,
};
window.live2dModel = { internalModel: { coreModel } };
window.onLive2DParameterModelChanged({
    modelKey: 'model-a',
    parameterDisplayInfo: {
        parameters: {
            ParamRibbon: {
                name: '리본',
                groupId: 'ParamGroupDecor',
                groupName: '장식',
            },
            ParamEyeLOpen: {
                name: '왼쪽 눈 뜨기',
                groupId: 'ParamGroupEyes',
                groupName: '눈',
            },
        },
        groups: {
            ParamGroupDecor: { name: '장식' },
            ParamGroupEyes: { name: '눈' },
        },
    },
});

result = collectLive2DParameterMetadata();
"""
    )

    assert result == [
        {
            "id": "ParamRibbon",
            "current": 0,
            "default": 0,
            "min": -1,
            "max": 1,
            "recommended": True,
            "displayName": "리본",
            "groupId": "ParamGroupDecor",
            "groupName": "장식",
        },
        {
            "id": "ParamEyeLOpen",
            "current": 0,
            "default": 0,
            "min": -1,
            "max": 1,
            "recommended": False,
            "displayName": "왼쪽 눈 뜨기",
            "groupId": "ParamGroupEyes",
            "groupName": "눈",
        },
    ]


def test_live2d_parameter_save_payload_keeps_only_saved_dirty_and_favorites_values():
    result = _run_live2d_parameter_runtime_case(
        """
live2dParameterState.metadata = [
    { id: 'ParamVisibleOnly', current: 0.5, default: 0, min: -1, max: 1, recommended: true },
    { id: 'ParamSaved', current: 0.2, default: 0, min: -1, max: 1, recommended: true },
    { id: 'ParamDirty', current: 0.3, default: 0, min: -1, max: 1, recommended: true },
    { id: 'ParamRemoved', current: 0.4, default: 0, min: -1, max: 1, recommended: true },
];
live2dParameterState.values = { ParamSaved: 1, ParamRemoved: 2 };
live2dParameterState.dirtyValues = { ParamDirty: 3 };
live2dParameterState.removedValues = new Set(['ParamRemoved']);
live2dParameterState.favorites = new Set(['ParamVisibleOnly', 'ParamDirty']);

result = buildLive2DParameterSavePayload();
"""
    )

    assert result == {
        "values": {
            "ParamSaved": 1,
            "ParamDirty": 3,
        },
        "favorites": ["ParamVisibleOnly", "ParamDirty"],
    }


def test_live2d_parameter_save_payload_drops_expression_sensitive_parameters():
    result = _run_live2d_parameter_runtime_case(
        """
live2dParameterState.values = {
    ParamRibbon: 0.75,
    ParamEyeLOpen: 0,
    ParamMouthOpenY: 1,
};
live2dParameterState.dirtyValues = {
    ParamAngleX: 20,
    ParamHat: 0.5,
};
live2dParameterState.favorites = new Set(['ParamRibbon', 'ParamEyeLOpen', 'ParamHat']);

result = buildLive2DParameterSavePayload();
"""
    )

    assert result == {
        "values": {
            "ParamRibbon": 0.75,
            "ParamHat": 0.5,
        },
        "favorites": ["ParamRibbon", "ParamHat"],
    }


def test_live2d_parameter_same_model_update_preserves_unsaved_edits():
    result = _run_live2d_parameter_runtime_case(
        """
const calls = [];
window.live2dModel = {
    internalModel: {
        coreModel: {
            getParameterIndex: () => 0,
            getParameterCount: () => 3,
            setParameterValueById: (paramId, value) => calls.push([paramId, value]),
        },
    },
};

window.onLive2DParameterModelChanged({
    modelKey: 'same-model',
    parameterOverrides: {
        values: { ParamSaved: 1 },
        favorites: ['ParamSaved'],
    },
});
live2dParameterState.dirtyValues = { ParamDirty: 2 };
live2dParameterState.removedValues = new Set(['ParamRemoved']);
live2dParameterState.favorites.add('ParamLocalFavorite');

window.onLive2DParameterModelChanged({
    modelKey: 'same-model',
    parameterOverrides: {
        values: { ParamSaved: 10 },
        favorites: ['ParamNewFavorite'],
    },
});
const sameModel = {
    values: live2dParameterState.values,
    favorites: Array.from(live2dParameterState.favorites),
    dirtyValues: live2dParameterState.dirtyValues,
    removedValues: Array.from(live2dParameterState.removedValues),
    payload: buildLive2DParameterSavePayload(),
};

window.onLive2DParameterModelChanged({
    modelKey: 'other-model',
    parameterOverrides: {
        values: { ParamOtherSaved: 3 },
        favorites: ['ParamOtherSaved'],
    },
});

result = {
    sameModel,
    changedModel: {
        values: live2dParameterState.values,
        favorites: Array.from(live2dParameterState.favorites),
        dirtyValues: live2dParameterState.dirtyValues,
        removedValues: Array.from(live2dParameterState.removedValues),
    },
};
"""
    )

    assert result == {
        "sameModel": {
            "values": {"ParamSaved": 10},
            "favorites": ["ParamSaved", "ParamLocalFavorite"],
            "dirtyValues": {"ParamDirty": 2},
            "removedValues": ["ParamRemoved"],
            "payload": {
                "values": {
                    "ParamSaved": 10,
                    "ParamDirty": 2,
                },
                "favorites": ["ParamSaved", "ParamLocalFavorite"],
            },
        },
        "changedModel": {
            "values": {"ParamOtherSaved": 3},
            "favorites": ["ParamOtherSaved"],
            "dirtyValues": {},
            "removedValues": [],
        },
    }


def test_live2d_parameter_same_model_update_preserves_unsaved_favorite_add():
    result = _run_live2d_parameter_runtime_case(
        """
window.onLive2DParameterModelChanged({
    modelKey: 'model-a',
    parameterOverrides: { values: {}, favorites: ['ParamSavedFavorite'] },
});
live2dParameterState.favorites.add('ParamLocalFavorite');

window.onLive2DParameterModelChanged({
    modelKey: 'model-a',
    parameterOverrides: { values: {}, favorites: ['ParamSavedFavorite'] },
});

result = {
    favorites: Array.from(live2dParameterState.favorites),
    payload: buildLive2DParameterSavePayload(),
};
"""
    )

    assert result == {
        "favorites": ["ParamSavedFavorite", "ParamLocalFavorite"],
        "payload": {
            "values": {},
            "favorites": ["ParamSavedFavorite", "ParamLocalFavorite"],
        },
    }


def test_live2d_parameter_same_model_update_preserves_unsaved_favorite_removal():
    result = _run_live2d_parameter_runtime_case(
        """
window.onLive2DParameterModelChanged({
    modelKey: 'model-a',
    parameterOverrides: { values: {}, favorites: ['ParamSavedFavorite', 'ParamOtherFavorite'] },
});
live2dParameterState.favorites.delete('ParamSavedFavorite');

window.onLive2DParameterModelChanged({
    modelKey: 'model-a',
    parameterOverrides: { values: {}, favorites: ['ParamSavedFavorite', 'ParamOtherFavorite'] },
});

result = {
    favorites: Array.from(live2dParameterState.favorites),
    payload: buildLive2DParameterSavePayload(),
};
"""
    )

    assert result == {
        "favorites": ["ParamOtherFavorite"],
        "payload": {
            "values": {},
            "favorites": ["ParamOtherFavorite"],
        },
    }


def test_live2d_parameter_changed_model_resets_favorites_from_config():
    result = _run_live2d_parameter_runtime_case(
        """
window.onLive2DParameterModelChanged({
    modelKey: 'model-a',
    parameterOverrides: { values: {}, favorites: ['ParamSavedFavorite'] },
});
live2dParameterState.favorites.add('ParamLocalFavorite');
live2dParameterState.favorites.delete('ParamSavedFavorite');

window.onLive2DParameterModelChanged({
    modelKey: 'model-b',
    parameterOverrides: { values: {}, favorites: ['ParamModelBFavorite'] },
});

result = {
    favorites: Array.from(live2dParameterState.favorites),
    payload: buildLive2DParameterSavePayload(),
};
"""
    )

    assert result == {
        "favorites": ["ParamModelBFavorite"],
        "payload": {
            "values": {},
            "favorites": ["ParamModelBFavorite"],
        },
    }


def test_live2d_parameter_changed_model_migrates_legacy_pinned_config_to_favorites():
    result = _run_live2d_parameter_runtime_case(
        """
window.onLive2DParameterModelChanged({
    modelKey: 'model-a',
    parameterOverrides: { values: {}, pinned: ['ParamAccessoryFavorite'] },
});

result = {
    favorites: Array.from(live2dParameterState.favorites),
    payload: buildLive2DParameterSavePayload(),
    aliasAvailable: window.setLive2DParameterInspectorPinned === window.setLive2DParameterInspectorFavorite,
};
"""
    )

    assert result == {
        "favorites": ["ParamAccessoryFavorite"],
        "payload": {
            "values": {},
            "favorites": ["ParamAccessoryFavorite"],
        },
        "aliasAvailable": True,
    }


def test_live2d_parameter_input_updates_row_without_replacing_list():
    result = _run_live2d_parameter_runtime_case(
        """
function makeElement(tagName) {
    return {
        tagName,
        children: [],
        listeners: {},
        attributes: {},
        className: '',
        textContent: '',
        type: '',
        value: '',
        min: '',
        max: '',
        step: '',
        disabled: false,
        classList: {
            toggle() {},
        },
        setAttribute(name, value) {
            this.attributes[name] = String(value);
        },
        addEventListener(name, callback) {
            this.listeners[name] = callback;
        },
        appendChild(child) {
            this.children.push(child);
            return child;
        },
        replaceChildren(...children) {
            this.children = children;
        },
    };
}

const elements = {
    'live2d-parameters-list': makeElement('div'),
    'live2d-parameters-search': makeElement('input'),
    'live2d-parameters-reset-btn': makeElement('button'),
    'live2d-parameters-save-btn': makeElement('button'),
};
document = {
    getElementById: (id) => elements[id] || null,
    createElement: makeElement,
};
const calls = [];
window.live2dModel = {
    internalModel: {
        coreModel: {
            setParameterValueById: (paramId, value) => calls.push([paramId, value]),
        },
    },
};
live2dParameterState.metadataStatus = 'ready';
live2dParameterState.metadata = [
    { id: 'ParamDecor', current: 0.2, default: 0, min: -1, max: 1, recommended: true },
];

renderLive2DParameterInspector();
const firstRow = elements['live2d-parameters-list'].children[0];
const controls = firstRow.children[1];
const range = controls.children[0];
const number = controls.children[1];
range.value = '0.7';
range.listeners.input();

result = {
    sameRow: elements['live2d-parameters-list'].children[0] === firstRow,
    rowCount: elements['live2d-parameters-list'].children.length,
    rangeValue: range.value,
    numberValue: number.value,
    dirtyValues: live2dParameterState.dirtyValues,
    metadataCurrent: live2dParameterState.metadata[0].current,
    calls,
};
"""
    )

    assert result == {
        "sameRow": True,
        "rowCount": 1,
        "rangeValue": "0.7",
        "numberValue": "0.7",
        "dirtyValues": {"ParamDecor": 0.7},
        "metadataCurrent": 0.7,
        "calls": [["ParamDecor", 0.7]],
    }


def test_live2d_parameter_save_refuses_empty_model_key_without_clearing_dirty_state():
    result = _run_live2d_parameter_runtime_case(
        """
const calls = [];
const toasts = [];
window.showToast = (message, type) => toasts.push([message, type]);
window.pyBridge = {
    save_live2d_parameter_overrides: (modelKey, payload) => calls.push([modelKey, payload]),
};
live2dParameterState.modelKey = '';
live2dParameterState.metadataStatus = 'ready';
live2dParameterState.values = { ParamSaved: 1 };
live2dParameterState.dirtyValues = { ParamDirty: 2 };
live2dParameterState.removedValues = new Set(['ParamRemoved']);

saveLive2DParameterOverrides();

result = {
    calls,
    toasts,
    values: live2dParameterState.values,
    dirtyValues: live2dParameterState.dirtyValues,
    removedValues: Array.from(live2dParameterState.removedValues),
};
"""
    )

    assert result == {
        "calls": [],
        "toasts": [["모델을 먼저 선택해야 저장할 수 있습니다.", "error"]],
        "values": {"ParamSaved": 1},
        "dirtyValues": {"ParamDirty": 2},
        "removedValues": ["ParamRemoved"],
    }


def test_live2d_parameter_save_refuses_non_ready_status_and_missing_bridge():
    result = _run_live2d_parameter_runtime_case(
        """
const toasts = [];
window.showToast = (message, type) => toasts.push([message, type]);

live2dParameterState.metadataStatus = 'idle';
saveLive2DParameterOverrides();
const afterIdle = {
    toasts: toasts.slice(),
};

toasts.length = 0;
live2dParameterState.modelKey = 'model-a';
live2dParameterState.metadataStatus = 'ready';
window.pyBridge = {};
saveLive2DParameterOverrides();

result = {
    afterIdle,
    afterMissingBridge: {
        toasts: toasts.slice(),
    },
};
"""
    )

    assert result["afterIdle"]["toasts"] == [["파라미터 목록을 먼저 불러와야 합니다.", "error"]]
    assert result["afterMissingBridge"]["toasts"] == [["저장 브리지를 사용할 수 없습니다.", "error"]]


def test_live2d_parameter_reset_removes_saved_param_and_restores_default():
    result = _run_live2d_parameter_runtime_case(
        """
const calls = [];
window.live2dModel = {
    internalModel: {
        coreModel: {
            setParameterValueById: (paramId, value) => calls.push([paramId, value]),
        },
    },
};
live2dParameterState.metadata = [
    { id: 'ParamSaved', current: 0.8, default: 0.1, min: -1, max: 1, recommended: true },
];
live2dParameterState.metadataStatus = 'ready';
live2dParameterState.values = { ParamSaved: 0.8 };
live2dParameterState.dirtyValues = { ParamSaved: 0.9 };
live2dParameterState.removedValues = new Set();

resetLive2DParameterOverride('ParamSaved');

result = {
    values: live2dParameterState.values,
    dirtyValues: live2dParameterState.dirtyValues,
    removedValues: Array.from(live2dParameterState.removedValues),
    metadataCurrent: live2dParameterState.metadata[0].current,
    calls,
    payload: buildLive2DParameterSavePayload(),
};
"""
    )

    assert result == {
        "values": {},
        "dirtyValues": {},
        "removedValues": ["ParamSaved"],
        "metadataCurrent": 0.1,
        "calls": [["ParamSaved", 0.1]],
        "payload": {
            "values": {},
            "favorites": [],
        },
    }


def test_live2d_parameter_tab_changes_update_selected_and_tabpanel_label():
    result = _run_live2d_parameter_runtime_case(
        """
function makeElement(id) {
    return {
        id,
        attributes: {},
        classList: {
            values: [],
            toggle(name, active) {
                this.values = this.values.filter((value) => value !== name);
                if (active) {
                    this.values.push(name);
                }
            },
            contains(name) {
                return this.values.indexOf(name) >= 0;
            },
            add(name) {
                if (!this.contains(name)) this.values.push(name);
            },
            remove(name) {
                this.values = this.values.filter((value) => value !== name);
            },
        },
        setAttribute(name, value) {
            this.attributes[name] = String(value);
        },
        getAttribute(name) {
            return this.attributes[name];
        },
        addEventListener() {},
        appendChild() {},
        replaceChildren() {},
        dataset: {},
        disabled: false,
        value: '',
        textContent: '',
    };
}

const elements = {
    'live2d-parameters-tab-all': makeElement('live2d-parameters-tab-all'),
    'live2d-parameters-tab-favorites': makeElement('live2d-parameters-tab-favorites'),
    'live2d-parameters-list': makeElement('live2d-parameters-list'),
};
document = {
    getElementById: (id) => elements[id] || null,
};

setLive2DParameterActiveTab('favorites');

result = {
    allSelected: elements['live2d-parameters-tab-all'].getAttribute('aria-selected'),
    favoritesSelected: elements['live2d-parameters-tab-favorites'].getAttribute('aria-selected'),
    favoritesActive: elements['live2d-parameters-tab-favorites'].classList.contains('is-active'),
    label: elements['live2d-parameters-list'].getAttribute('aria-labelledby'),
};
"""
    )

    assert result == {
        "allSelected": "false",
        "favoritesSelected": "true",
        "favoritesActive": True,
        "label": "live2d-parameters-tab-favorites",
    }


def test_live2d_parameter_panel_header_drags_panel_within_viewport():
    result = _run_live2d_parameter_runtime_case(
        """
function makeElement(id) {
    return {
        id,
        listeners: {},
        style: {},
        classList: {
            values: [],
            add(name) {
                if (this.values.indexOf(name) < 0) this.values.push(name);
            },
            remove(name) {
                this.values = this.values.filter((value) => value !== name);
            },
            contains(name) {
                return this.values.indexOf(name) >= 0;
            },
            toggle() {},
        },
        addEventListener(name, callback) {
            this.listeners[name] = callback;
        },
        setPointerCapture(pointerId) {
            this.capturedPointerId = pointerId;
        },
        releasePointerCapture(pointerId) {
            this.releasedPointerId = pointerId;
        },
        getBoundingClientRect() {
            return this.rect || { left: 280, top: 112, width: 340, height: 420 };
        },
        setAttribute() {},
    };
}

const panel = makeElement('live2d-parameters-panel');
const header = makeElement('live2d-parameters-panel-header');
panel.rect = { left: 280, top: 112, width: 340, height: 420 };
window.innerWidth = 640;
window.innerHeight = 480;
window.listeners = {};
window.addEventListener = (name, callback) => {
    window.listeners[name] = callback;
};
window.removeEventListener = () => {};
document = {
    getElementById: (id) => ({
        'live2d-parameters-panel': panel,
        'live2d-parameters-panel-header': header,
    }[id] || null),
};

bindLive2DParameterEvents();
header.listeners.pointerdown({
    button: 0,
    pointerId: 7,
    clientX: 300,
    clientY: 132,
    preventDefault() {},
});
window.listeners.pointermove({
    pointerId: 7,
    clientX: 20,
    clientY: 16,
    preventDefault() {},
});
window.listeners.pointerup({ pointerId: 7 });

result = {
    left: panel.style.left,
    top: panel.style.top,
    right: panel.style.right,
    dragging: header.classList.contains('is-dragging'),
    capturedPointerId: header.capturedPointerId,
    releasedPointerId: header.releasedPointerId,
};
"""
    )

    assert result == {
        "left": "8px",
        "top": "8px",
        "right": "auto",
        "dragging": False,
        "capturedPointerId": 7,
        "releasedPointerId": 7,
    }


def test_live2d_parameter_panel_drag_css_uses_move_cursor():
    css = STYLE_PATH.read_text(encoding="utf-8-sig")

    assert "#live2d-parameters-panel-header" in css
    assert "cursor: move;" in css
    assert "#live2d-parameters-panel-header.is-dragging" in css


def test_live2d_parameter_button_prefers_native_inspector_when_bridge_available():
    result = _run_live2d_parameter_runtime_case(
        """
const calls = [];
const button = {
    listeners: {},
    addEventListener(name, callback) {
        this.listeners[name] = callback;
    },
};
const panel = {
    classList: {
        toggle() {},
    },
};
window.pyBridge = {
    open_live2d_parameter_inspector: () => calls.push('native'),
};
document = {
    getElementById: (id) => ({
        'live2d-parameters-floating-btn': button,
        'live2d-parameters-panel': panel,
    }[id] || null),
};

bindLive2DParameterEvents();
button.listeners.click();

result = {
    calls,
    panelOpen: live2dParameterState.panelOpen,
};
"""
    )

    assert result == {
        "calls": ["native"],
        "panelOpen": False,
    }


def test_live2d_parameter_native_inspector_commands_update_runtime_state():
    result = _run_live2d_parameter_runtime_case(
        """
const calls = [];
window.live2dModel = {
    internalModel: {
        coreModel: {
            setParameterValueById: (paramId, value) => calls.push([paramId, value]),
        },
    },
};
live2dParameterState.metadataStatus = 'ready';
live2dParameterState.modelKey = 'model-a';
live2dParameterState.metadata = [
    { id: 'ParamRibbon', current: 0.2, default: 0, min: 0, max: 1, recommended: true },
    { id: 'ParamMouthOpenY', current: 0.3, default: 0, min: 0, max: 1, recommended: false },
];
live2dParameterState.values = { ParamRibbon: 0.2 };
live2dParameterState.favorites = new Set();
live2dParameterState.dirtyValues = {};
live2dParameterState.removedValues = new Set();

const before = JSON.parse(window.getLive2DParameterInspectorSnapshot());
const changed = window.setLive2DParameterInspectorValue('ParamRibbon', 0.75);
const blocked = window.setLive2DParameterInspectorValue('ParamMouthOpenY', 0.9);
window.setLive2DParameterInspectorFavorite('ParamRibbon', true);
window.resetLive2DParameterInspectorValue('ParamRibbon');
const after = JSON.parse(window.getLive2DParameterInspectorSnapshot());

result = {
    beforeStatus: before.metadataStatus,
    beforeModelKey: before.modelKey,
    beforeCount: before.metadata.length,
    changed,
    blocked,
    calls,
    afterFavorite: after.favorites,
    afterValues: after.savePayload.values,
    afterRemoved: Array.from(live2dParameterState.removedValues),
    afterCurrent: after.metadata.find((item) => item.id === 'ParamRibbon').current,
};
"""
    )

    assert result == {
        "beforeStatus": "ready",
        "beforeModelKey": "model-a",
        "beforeCount": 2,
        "changed": True,
        "blocked": False,
        "calls": [["ParamRibbon", 0.75], ["ParamRibbon", 0]],
        "afterFavorite": ["ParamRibbon"],
        "afterValues": {},
        "afterRemoved": ["ParamRibbon"],
        "afterCurrent": 0,
    }


def test_live2d_parameter_native_value_update_does_not_rerender_dom_panel():
    result = _run_live2d_parameter_runtime_case(
        """
let renderCalls = 0;
renderLive2DParameterInspector = () => {
    renderCalls += 1;
};
window.live2dModel = {
    internalModel: {
        coreModel: {
            setParameterValueById() {},
        },
    },
};
live2dParameterState.metadataStatus = 'ready';
live2dParameterState.metadata = [
    { id: 'ParamRibbon', current: 0.2, default: 0, min: 0, max: 1, recommended: true },
];
live2dParameterState.values = {};
live2dParameterState.dirtyValues = {};
live2dParameterState.removedValues = new Set();

const changed = window.setLive2DParameterInspectorValue('ParamRibbon', 0.75);

result = {
    changed,
    renderCalls,
    current: live2dParameterState.metadata[0].current,
    dirtyValues: live2dParameterState.dirtyValues,
};
"""
    )

    assert result == {
        "changed": True,
        "renderCalls": 0,
        "current": 0.75,
        "dirtyValues": {"ParamRibbon": 0.75},
    }


def test_chat_container_uses_roomier_bounded_height():
    block = _rule_block("#chat-container")
    assert "overflow: hidden;" in block
    assert "max-height: min(360px, 42vh);" in block


def test_web_css_avoids_backdrop_filter_in_transparent_overlay():
    css = STYLE_PATH.read_text(encoding="utf-8-sig")

    assert "backdrop-filter" not in css


def test_chat_messages_can_shrink_inside_flex_panel():
    block = _rule_block("#chat-messages")
    assert "min-height: 0;" in block


def test_image_preview_stays_reserved_and_keeps_controls_inside():
    preview_block = _rule_block("#image-preview-container")
    remove_button_block = _rule_block(".attachment-preview-item .remove-btn")

    assert "flex-shrink: 0;" in preview_block
    assert "overflow-y: hidden;" in preview_block
    assert "top: 4px;" in remove_button_block
    assert "right: 4px;" in remove_button_block


def test_message_time_meta_rail_aligns_with_bubbles():
    message_block = _rule_block(".message")
    meta_block = _rule_block(".message-meta-rail")
    time_block = _rule_block(".message-time")

    assert "align-items: flex-end;" in message_block
    assert "display: inline-flex;" in meta_block
    assert "align-items: flex-end;" in meta_block
    assert "font-size: 11px;" in time_block
    assert "white-space: nowrap;" in time_block


def test_edit_button_uses_svg_icon_styles():
    block = _rule_block(".message-edit-btn")
    assert "width: 16px;" in block
    assert "height: 16px;" in block
    assert "border-radius: 999px;" in block


def test_reroll_button_uses_svg_icon_styles():
    block = _rule_block(".message-reroll-btn")
    assert "width: 16px;" in block
    assert "height: 16px;" in block
    assert "border-radius: 999px;" in block


def test_loading_indicator_uses_plain_message_row_visuals():
    indicator_block = _rule_block("#loading-indicator")
    typing_text_block = _rule_block(".typing-text")

    assert "display: inline-flex;" in indicator_block
    assert "justify-content: flex-start;" in indicator_block
    assert "gap: 8px;" in indicator_block
    assert "padding-left: 12px;" in indicator_block
    assert "margin-right: auto;" in indicator_block
    assert "align-self: flex-start;" in indicator_block
    assert "width: fit-content;" in indicator_block
    assert "color: var(--ene-chat-panel-text);" in indicator_block
    assert "color: var(--ene-chat-panel-text);" in typing_text_block
    assert "font-size: 14px;" in typing_text_block
    assert "line-height: 1.4;" in typing_text_block
    assert "transform: translateY(4px);" in typing_text_block


def test_chat_script_uses_bridge_pending_signal_for_loading_state():
    script = _script_text()

    assert "function setRequestPending(active)" in script
    assert "window.pyBridge.request_pending_changed.connect" in script
    assert "setRequestPending(Boolean(active));" in script


def test_chat_script_blocks_send_while_request_is_pending():
    script = _script_text()

    assert "sendButton.disabled = isRequestPending;" in script
    assert "if (isRequestPending) return;" in script


def test_reroll_and_inline_edit_restore_pending_when_bridge_call_fails():
    script = _script_text()

    reroll_block = re.search(
        r"setRequestPending\(true\);\s*dispatchBridgeCall\(\(\) => \{\s*window\.pyBridge\.reroll_last_response\(\);",
        script,
    )
    edit_block = re.search(
        r"setRequestPending\(true\);\s*dispatchBridgeCall\(\(\) => \{\s*window\.pyBridge\.edit_last_user_message\(trimmed\);",
        script,
    )

    assert reroll_block
    assert edit_block
    assert "setRequestPending(false);" in script
    assert "shouldReplaceNextAssistant = false;" in script


def test_manual_summary_bridge_call_does_not_toggle_chat_pending():
    script = _script_text()

    assert "window.pyBridge.summarize_now();" in script
    assert "Python bridge manual summary failed" not in script


def test_summary_review_modal_markup_exists():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")

    assert 'id="summary-review-overlay"' in html
    assert 'id="summary-review-textarea"' in html
    assert 'id="summary-review-user-facts"' in html
    assert 'id="summary-review-ene-facts"' in html
    assert 'id="summary-review-add-user-fact"' in html
    assert 'id="summary-review-add-ene-fact"' in html
    assert 'id="summary-review-regenerate"' in html
    assert 'id="summary-review-save"' in html


def test_chat_script_routes_summary_review_through_bridge_slots():
    script = _script_text()

    assert "function showSummaryReview(" in script
    assert "function collectSummaryReviewPayload()" in script
    assert "function setSummaryReviewBusy(active)" in script
    assert "function appendSummaryReviewFact(" in script
    assert "window.pyBridge.summary_review_ready.connect" in script
    assert "window.pyBridge.summary_review_saved.connect" in script
    assert "window.pyBridge.approve_summary_review(JSON.stringify(payload));" in script
    assert "window.pyBridge.regenerate_summary_review();" in script
    assert "window.pyBridge.cancel_summary_review();" in script
    save_handler = re.search(
        r"summaryReviewSaveButton\.addEventListener\('click', \(\) => \{.*?\n    \}\);",
        script,
        re.DOTALL,
    )
    assert save_handler
    assert "setSummaryReviewBusy(true);" in save_handler.group(0)
    assert "hideSummaryReview();" not in save_handler.group(0)


def test_summary_review_facts_are_editable_and_meta_is_preserved():
    script = _script_text()

    assert "text.className = 'summary-review-fact-input';" in script
    assert "Object.assign({}, previousMeta" in script
    assert "ensureSummaryReviewSelectOption(summaryReviewMemoryType" in script
    assert "ensureSummaryReviewSelectOption(summaryReviewImportanceReason" in script


def test_summary_review_modal_uses_bounded_scroll_layout():
    overlay_block = _rule_block("#summary-review-overlay")
    dialog_block = _rule_block("#summary-review-dialog")
    textarea_block = _rule_block("#summary-review-textarea")
    css = STYLE_PATH.read_text(encoding="utf-8-sig")

    assert "position: fixed;" in overlay_block
    assert "max-height: calc(100vh - 32px);" in dialog_block
    assert "overflow: auto;" in dialog_block
    assert "resize: vertical;" in textarea_block
    assert "#summary-review-dialog::-webkit-scrollbar" in css
    assert ".summary-review-facts::-webkit-scrollbar" in css
    assert "#summary-review-textarea::-webkit-scrollbar" in css
    assert ".summary-review-fact-input::-webkit-scrollbar" in css
    assert "#summary-review-dialog::-webkit-scrollbar-thumb" in css
    assert "background: rgba(255, 255, 255, 0.2);" in css


def test_inline_edit_save_button_reflects_request_pending_state():
    script = _script_text()

    assert "const saveBtn = activeInlineEditMessageEl.querySelector('.inline-edit-save');" in script
    assert "saveBtn.disabled = isRequestPending;" in script


def test_token_usage_bubble_is_offset_slightly_lower_from_top_left():
    stack_block = _rule_block("#overlay-notice-stack")
    bubble_block = _rule_block("#token-usage-bubble")
    assert "top: 32px;" in stack_block
    assert "left: 4px;" in stack_block
    assert "position: relative;" in bubble_block


def test_overlay_notice_stack_markup_exists_for_token_and_promise_bubbles():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="overlay-notice-stack"' in html
    assert 'id="token-usage-bubble"' in html
    assert 'id="promise-notice-bubble"' in html


def test_promise_notice_bubble_uses_same_overlay_stack_style():
    stack_block = _rule_block("#overlay-notice-stack")
    notice_block = _rule_block("#promise-notice-bubble")
    hidden_block = _rule_block("#promise-notice-bubble.hidden")

    assert "display: flex;" in stack_block
    assert "flex-direction: column;" in stack_block
    assert "align-items: flex-start;" in stack_block
    assert "gap: 8px;" in stack_block
    assert "position: relative;" in notice_block
    assert "transition: opacity 0.18s ease, transform 0.18s ease;" in notice_block
    assert "pointer-events: none;" in hidden_block


def test_attach_button_centers_within_input_row():
    block = _rule_block("#attach-button")
    assert "align-self: center;" in block


def test_chat_resize_handle_markup_exists_above_messages():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="chat-resize-handle"' in html
    assert '<div id="chat-resize-handle"' in html
    assert html.index('id="chat-resize-handle"') < html.index('id="chat-messages"')


def test_scheduled_promises_menu_markup_exists():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="promise-reminders-floating-btn"' in html
    assert 'id="promise-reminders-panel"' in html
    assert 'id="promise-reminders-close-btn"' in html


def test_chat_thought_history_input_button_is_removed():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="thought-history-button"' not in html
    assert 'id="thought-history-panel"' not in html
    assert 'id="thought-history-close-btn"' not in html
    assert '생각</button>' not in html


def test_chat_script_renders_thought_action_in_message_meta_rail():
    script = _script_text()
    assert "function createMessageThoughtButton(messageDiv)" in script
    assert "btn.className = 'message-thought-btn';" in script
    assert "btn.innerHTML = createLucideIcon('sparkles');" in script
    assert "createLucideIcon('brain')" not in script
    assert "assistantRail.insertBefore(thoughtButton, rerollAnchor);" in script
    assert "const rerollAnchor = assistantRail.querySelector('.message-reroll-btn');" in script


def test_chat_script_exposes_runtime_thought_feature_config_hook():
    script = _script_text()
    assert "window.setThoughtFeatureEnabled = function" in script
    assert "thoughtFeatureEnabled" in script
    assert "updateMessageThoughtButtons()" in script


def test_chat_thought_action_uses_compact_icon_button_styles():
    button_block = _rule_block(".message-thought-btn")
    thought_body_block = _rule_block(".message-thought-body")

    assert "width: 16px;" in button_block
    assert "height: 16px;" in button_block
    assert "border-radius: 999px;" in button_block
    assert "cursor: pointer;" in button_block
    assert "word-break: break-word;" in thought_body_block


def test_chat_resize_handle_uses_vertical_drag_styles():
    block = _rule_block("#chat-resize-handle")
    assert "cursor: ns-resize;" in block
    assert "touch-action: none;" in block
    assert "flex-shrink: 0;" in block


def test_chat_script_defines_typing_effect_speed_guards():
    script = _script_text()
    assert "const MESSAGE_TYPING_BASE_INTERVAL_MS =" in script
    assert "const MESSAGE_TYPING_MAX_DURATION_MS =" in script


def test_chat_script_reuses_typing_renderer_for_new_and_replaced_messages():
    script = _script_text()
    assert "function animateMessageText(" in script
    assert "function renderMessageBubbleSegments(" in script
    assert "animateMessageText(textSpan, segment, { immediate })" in script
    assert "renderMessageBubbleSegments(lastAssistantMessageEl, text" in script


def test_chat_script_creates_split_bubbles_only_when_each_segment_starts_typing():
    script = _script_text()
    assert "animationQueue = animationQueue.then(() => {" in script
    assert "const { bubble, textSpan } = createTextMessageBubble();" in script
    assert "stack.appendChild(bubble);" in script


def test_chat_script_exposes_runtime_typing_config_hook():
    script = _script_text()
    assert "window.setTypingEffectConfig = function" in script
    assert "typingEffectEnabled" in script
    assert "typingEffectSpeed" in script


def test_chat_script_exposes_runtime_message_split_config_hook():
    script = _script_text()
    assert "window.setMessageSplitConfig = function" in script
    assert "messageSplitEnabled" in script
    assert "splitMessageIntoVisualChunks(" in script


def test_chat_script_exposes_builtin_idle_runtime_hook():
    script = _script_text()
    assert "window.setBuiltinIdleMotionEnabled = function" in script
    assert "builtinAutoMotionState.enabled" in script


def test_chat_script_exposes_auto_eye_blink_runtime_hook():
    script = _script_text()
    assert "window.setAutoEyeBlinkEnabled = function" in script
    assert "autoEyeBlinkState.enabled" in script


def test_chat_script_starts_builtin_idle_only_when_enabled():
    script = _script_text()
    assert "if (builtinAutoMotionState.enabled)" in script
    assert "model.motion('Idle');" in script


def test_chat_script_defines_builtin_idle_start_stop_helpers():
    script = _script_text()
    assert "function startBuiltinIdleMotion(" in script
    assert "function stopBuiltinIdleMotion(" in script


def test_chat_script_blocks_motion_manager_idle_group_when_builtin_idle_is_disabled():
    script = _script_text()
    assert "const BUILTIN_IDLE_GROUP_DISABLED =" in script
    assert "motionManager.groups.idle = BUILTIN_IDLE_GROUP_DISABLED;" in script
    assert "motionManager.groups.idle = builtinAutoMotionState.idleGroupName;" in script


def test_chat_script_disables_and_restores_builtin_breath_when_builtin_idle_toggles():
    script = _script_text()
    assert "builtinAutoMotionState.breath = null;" in script
    assert "function syncBuiltinNaturalBreath(" in script
    assert "syncBuiltinAutoMotionComponent(internalModel, 'breath', enabled)" in script


def test_chat_script_runs_idle_motion_without_dynamic_mode_toggle():
    script = _script_text()
    assert "window.setIdleMotionDynamic = function" not in script
    assert "idleMotionDynamicMode" not in script
    assert "const breathWave = Math.sin(idleMotionPhase * 1.1 + 0.35);" in script
    assert "breath: Math.max(-1, Math.min(1, breathWave * idleMotionBreath))" in script
    assert "const IDLE_MOTION_BASE_BREATH = 1.0;" in script


def test_chat_script_disables_and_restores_builtin_physics_when_builtin_idle_toggles():
    script = _script_text()
    assert "builtinAutoMotionState.physics = null;" in script
    assert "function syncBuiltinAutoMotionComponent(" in script
    assert "function syncBuiltinAutoMotionComponents(" in script
    assert "internalModel[propertyName] = null;" in script
    assert "internalModel[propertyName] = builtinAutoMotionState[propertyName];" in script
    assert "syncBuiltinAutoMotionComponent(internalModel, 'physics', enabled)" in script


def test_chat_script_captures_and_toggles_builtin_eye_blink_separately():
    script = _script_text()
    assert "builtinInstance: null," in script
    assert "function captureBuiltinEyeBlinkInstance(" in script
    assert "function syncAutoEyeBlinkMode(" in script
    assert "internalModel.eyeBlink = autoEyeBlinkState.builtinInstance;" in script
    assert "internalModel.eyeBlink = null;" in script


def test_chat_script_defines_fallback_auto_eye_blink_runtime():
    script = _script_text()
    assert "function createAutoEyeBlinkRuntimeState()" in script
    assert "function scheduleNextAutoEyeBlink(" in script
    assert "function updateAutoEyeBlinkRuntime(" in script
    assert "function applyAutoEyeBlinkToCoreModel(" in script
    assert "setParameterValueById('ParamEyeLOpen', openValue)" in script
    assert "setParameterValueById('ParamEyeROpen', openValue)" in script


def test_chat_script_applies_idle_breath_param_when_model_supports_it():
    script = _script_text()
    assert "breath: resolveParam('breath', 'ParamBreath')" in script
    assert "function applyIdleBreathParam(coreModel, idleOffsets = null)" in script
    assert "coreModel.setParameterValueById(support.breath, idleBreath + gestureBreath);" in script
    assert "applyIdleBreathParam(coreModel, patOffsetsApplied);" in script
    assert "applyIdleBreathParam(coreModel, idleOffsets);" in script


def test_chat_script_blocks_fallback_eye_blink_when_eye_closing_state_is_active():
    script = _script_text()
    assert "function isEyeCloseExpressionActive(sample)" in script
    assert "function shouldSuspendAutoEyeBlink(sample, hasHeadPatEffect)" in script
    assert "sample.fromWeight > 0.001 && resolveExpressionEmotion(sample.fromExpression.emotion) === 'eyeclose';" in script
    assert "return sample.toWeight > 0.001 && resolveExpressionEmotion(sample.toExpression.emotion) === 'eyeclose';" in script


def test_chat_script_allows_expression_transition_duration_override():
    script = _script_text()
    assert "async function changeExpression(emotion, options = {})" in script
    assert "const durationMs = Number.isFinite(options.durationMs)" in script


def test_chat_script_uses_head_pat_fade_durations_for_expression_transitions():
    script = _script_text()
    assert "changeExpression(activeEmotion, { durationMs: headPatFadeInMs })" in script
    assert "changeExpression(endEmotion, { durationMs: headPatFadeOutMs })" in script


def test_chat_script_applies_expression_layers_inside_model_update_cycle():
    script = _script_text()
    assert "function applyExpressionLayer(coreModel, expression, weight)" in script
    assert "coreModel.addParameterValueById(param.id, param.value, weight);" in script
    assert "coreModel.multiplyParameterValueById(param.id, param.value, weight);" in script
    assert "coreModel.setParameterValueById(param.id, param.value, weight);" in script
    assert "function attachExpressionUpdateHook(model)" in script
    assert "internalModel.on('beforeModelUpdate', expressionRuntimeState.updateHook);" in script


def test_chat_script_loads_expression_definitions_with_blend_modes():
    script = _script_text()
    assert "const expressionRuntimeState = {" in script
    assert "definitionCache: new Map()," in script
    assert "function normalizeExpressionBlend(blend)" in script
    assert "blend: normalizeExpressionBlend(param.Blend)" in script
    assert "async function loadExpressionDefinition(emotion)" in script
    assert "const cached = expressionRuntimeState.definitionCache.get(expressionPath);" in script


def test_chat_script_overlaps_expression_fade_in_and_fade_out_weights():
    script = _script_text()
    assert "const fadeOutWeight = fromExpression ? (1 - Math.pow(progress, 3)) : 0;" in script
    assert "const fadeInWeight = 1 - Math.pow(1 - progress, 3);" in script
    assert "fromWeight: fadeOutWeight," in script
    assert "toWeight: fadeInWeight," in script


def test_chat_script_keeps_head_pat_eye_override_during_release_fade():
    script = _script_text()
    assert "function shouldUseHeadPatEyeCloseOverride()" in script
    assert "return resolveExpressionEmotion(headPatActiveEmotion) !== 'eyeclose';" in script
    assert "function shouldApplyHeadPatEyeOverrideNow(hasHeadPatEffect)" in script
    assert "return hasHeadPatEffect && shouldUseHeadPatEyeCloseOverride();" in script
    assert "const shouldApplyHeadPatEyeOverride = shouldApplyHeadPatEyeOverrideNow(hasHeadPatEffect);" in script


def test_chat_script_extracts_expression_transition_duration_and_state_helpers():
    script = _script_text()
    assert "function createEmptyExpressionTransition()" in script
    assert "function resolveExpressionTransitionDuration(resolvedEmotion, requestedDurationMs)" in script
    assert "function setExpressionTransition(nextExpression, durationMs)" in script
    assert "expressionRuntimeState.transition = {" in script


def test_chat_script_applies_head_pat_eye_override_with_fading_blend():
    script = _script_text()
    assert "if (shouldApplyHeadPatEyeOverride) {" in script
    assert "applyHeadPatEyeCloseOverride(coreModel, patBlend);" in script


def test_message_bubble_stack_supports_visual_multi_bubble_layout():
    stack_block = _rule_block(".message-bubble-stack")
    user_stack_block = _rule_block(".message.user .message-bubble-stack")
    assistant_stack_block = _rule_block(".message.assistant .message-bubble-stack")

    assert "display: flex;" in stack_block
    assert "flex-direction: column;" in stack_block
    assert "max-width: 70%;" in stack_block
    assert "align-items: flex-end;" in user_stack_block
    assert "align-items: flex-start;" in assistant_stack_block


def test_chat_script_keeps_visual_split_messages_as_single_logical_message():
    script = _script_text()
    assert "function splitMessageIntoVisualChunks(" in script
    assert "messageDiv.dataset.logicalMessageText" in script
    assert "function renderMessageBubbleSegments(" in script
    assert "splitMessageIntoVisualChunks(text)" in script


def test_chat_script_routes_recent_user_edit_through_logical_message_container():
    script = _script_text()
    assert "openInlineEdit(lastUserMessageEl);" in script
    assert "function getMessageLogicalText(" in script


def test_chat_script_exposes_chat_panel_height_restore_and_drag_persistence():
    script = _script_text()
    assert "const chatResizeHandle = document.getElementById('chat-resize-handle');" in script
    assert "function applyChatPanelHeight(height, { persist = false } = {})" in script
    assert "window.setChatPanelHeight = function setChatPanelHeight(height)" in script
    assert "window.pyBridge.save_chat_panel_height(String(nextHeight));" in script
    assert "chatResizeHandle.addEventListener('pointerdown'" in script


def test_chat_script_exposes_promise_panel_runtime_hooks():
    script = _script_text()
    assert "function getVisiblePromiseReminderItems()" in script
    assert "function formatPromiseReminderClock(" in script
    assert "function setPromiseRemindersPanelOpen(open)" in script
    assert "window.setPromiseReminderItems = function" in script
    assert "window.showPromiseReminderNotice = function" in script
    assert "window.setInterval(() => {" in script


def test_chat_script_binds_close_button_for_promise_panel():
    script = _script_text()
    assert "const promiseRemindersCloseButton = document.getElementById('promise-reminders-close-btn');" in script
    assert "promiseRemindersCloseButton.addEventListener('click'" in script
    assert "setPromiseRemindersPanelOpen(false);" in script


def test_chat_script_routes_promise_notice_through_overlay_stack():
    script = _script_text()
    assert "const overlayNoticeStack = document.getElementById('overlay-notice-stack');" in script
    assert "const promiseNoticeBubble = document.getElementById('promise-notice-bubble');" in script
    assert "let promiseNoticeBubbleTimer = null;" in script
    assert "function showPromiseNoticeBubble(message)" in script
    assert "function hidePromiseNoticeBubble()" in script
    assert "window.showPromiseReminderNotice = function showPromiseReminderNotice(message)" in script
    assert "showPromiseNoticeBubble(text);" in script


def test_script_exposes_apply_mouth_pose_hook():
    script = _script_text()
    assert "function applyMouthPose(" in script
    assert "window.pyBridge.mouth_pose_update" in script


def test_script_guards_missing_model_parameters_for_mouth_pose():
    script = _script_text()
    assert "function setModelParameterValue(" in script
    assert "ParamMouthOpenY" in script
    assert "ParamJawOpen" in script
    assert "ParamMouthForm" in script
    assert "ParamMouthFunnel" in script
    assert "ParamMouthPuckerWiden" in script


def test_chat_script_caches_expression_mouth_bias_while_speaking():
    script = _script_text()
    assert "const MOUTH_POSE_SOURCE_RMS = 'rms';" in script
    assert "function createEmptyMouthShapeState()" in script
    assert "function createEmptyMouthReleaseFadeState()" in script
    assert "const MOUTH_EXPRESSION_HOLD_MS =" in script
    assert "const mouthExpressionState = {" in script
    assert "function isMouthExpressionParam(paramId)" in script
    assert "function cacheExpressionMouthValue(paramId, value, weight, blend = 'add')" in script
    assert "function resetExpressionMouthCache()" in script
    assert "function resetMouthShapeState(shapeState)" in script
    assert "function shouldHoldExpressionMouthParams(nowMs = performance.now())" in script
    assert "return (nowMs - lastSpeechAt) < MOUTH_EXPRESSION_HOLD_MS;" in script
    assert "if (isMouthExpressionParam(param.id)) {" in script
    assert "cacheExpressionMouthValue(param.id, param.value, weight, param.blend);" in script
    assert "if (shouldHoldExpressionMouthParams()) {" in script
    assert "resetExpressionMouthCache();" in script


def test_chat_script_uses_rms_only_legacy_path_when_pose_source_is_rms():
    script = _script_text()
    assert "const poseSource = normalizeMouthPoseSource(pose.source);" in script
    assert "if (poseSource === MOUTH_POSE_SOURCE_RMS)" in script
    assert "setMouthOpen(open);" in script
    assert "clearMouthShapeParameters();" in script
    assert "setModelParameterValue('ParamJawOpen', 0);" in script
    assert "setModelParameterValue('ParamMouthForm', 0);" in script
    assert "setModelParameterValue('ParamMouthFunnel', 0);" in script
    assert "setModelParameterValue('ParamMouthPuckerWiden', 0);" in script
    assert "setModelParameterValue('ParamTongue', 0);" in script
    assert "return;" in script


def test_chat_script_blends_expression_bias_only_for_viseme_style_pose():
    script = _script_text()
    assert "const mouthExpressionState = {" in script
    assert "const MOUTH_SHAPE_RELEASE_FADE_MS = 180;" in script
    assert "lastVisemeShape: createEmptyMouthShapeState()," in script
    assert "releaseFade: createEmptyMouthReleaseFadeState()," in script
    assert "function buildReleaseFadeShapeValues(fadeFrom, expressionState, fadeProgress)" in script
    assert "function buildVisemeBlendedMouthPose(pose, expressionState)" in script
    assert "function applyMouthShapeValues(shapeValues)" in script
    assert "function isMouthExpressionParam(paramId)" in script
    assert "function cacheExpressionMouthValue(paramId, value, weight, blend = 'add')" in script
    assert "function resetExpressionMouthCache()" in script
    assert "function shouldHoldExpressionMouthParams(nowMs = performance.now())" in script
    assert "function beginMouthExpressionReleaseFade(nowMs = performance.now())" in script
    assert "function updateMouthExpressionReleaseFade(coreModel, nowMs = performance.now())" in script
    assert "resetExpressionMouthCache();" in script
    assert "if (isMouthExpressionParam(param.id)) {" in script
    assert "cacheExpressionMouthValue(param.id, param.value, weight, param.blend);" in script
    assert "if (shouldHoldExpressionMouthParams()) {" in script
    assert "updateMouthExpressionReleaseFade(coreModel, nowMs);" in script
    assert "open: normalizeMouthPoseNumber(Math.max(open, expressionState.open * 0.35))," in script
    assert "jaw: normalizeMouthPoseNumber(Math.max(jaw, expressionState.jaw * 0.25))," in script
    assert "form: normalizeMouthPoseNumber((expressionState.form * 0.7) + (form * 0.6))," in script
    assert "funnel: normalizeMouthPoseNumber((expressionState.funnel * 0.75) + (funnel * 0.55))," in script
    assert "puckerWiden: normalizeMouthPoseNumber((expressionState.puckerWiden * 0.75) + (puckerWiden * 0.55))," in script
    assert "tongue: Math.abs(tongue) > 0.0001 ? tongue : 0," in script
    assert "mouthExpressionState.lastVisemeShape = {" in script
    assert "const fadeProgress = Math.min((nowMs - mouthExpressionState.releaseFade.startedAt) / MOUTH_SHAPE_RELEASE_FADE_MS, 1);" in script
    assert "const fadeWeight = 1 - fadeProgress;" in script
    assert "mouthExpressionState.source = MOUTH_POSE_SOURCE_RMS;" in script
    assert "applyMouthShapeValues(shapeValues);" in script


def test_message_attachment_image_bubble_styles_support_hover_delete_and_deleted_placeholder():
    image_block = _rule_block(".message-attachment-image")
    media_block = _rule_block(".message-attachment-media")
    delete_button_block = _rule_block(".message-attachment-delete-btn")
    delete_hover_block = _rule_block(".message.user .message-attachment-media:hover .message-attachment-delete-btn")
    caption_block = _rule_block(".message-attachment-caption")
    deleted_block = _rule_block(".message-attachment-deleted")

    assert "overflow: hidden;" in image_block
    assert "cursor: zoom-in;" in media_block
    assert "opacity: 0;" in delete_button_block
    assert "opacity: 1;" in delete_hover_block
    assert "font-size: 14px;" in caption_block
    assert "padding: 10px 14px;" in caption_block
    assert "background:" in deleted_block
    assert "border:" in deleted_block


def test_attachment_delete_confirm_body_keeps_multiline_copy():
    confirm_body_block = _rule_block("#attachment-delete-confirm-body")
    assert "white-space: pre-line;" in confirm_body_block


def test_chat_script_routes_attachment_delete_through_confirm_modal():
    script = _script_text()
    assert "function requestAttachmentDeletion(" in script
    assert "function confirmAttachmentDeletion()" in script
    assert "window.pyBridge.delete_message_attachment(" in script
    assert "지운 사진은 컨텍스트에 포함되지 않습니다.\\n정말 지우시겠습니까?" in script


def test_chat_script_opens_image_lightbox_from_image_area_only():
    script = _script_text()
    assert "function openImageLightbox(" in script
    assert "function closeImageLightbox()" in script
    assert "mediaButton.addEventListener('click'" in script
    assert "imgWrapper.appendChild(removeBtn);" not in script


def test_qwebchannel_result_slots_use_callbacks_instead_of_sync_return_values():
    script = _script_text()

    assert "window.pyBridge.get_obs_tree_json(function (value)" in script
    assert "window.pyBridge.get_mood_snapshot_json(function (value)" in script
    assert "const result = window.pyBridge.get_obs_tree_json();" not in script
    assert "const snapshotResult = window.pyBridge.get_mood_snapshot_json();" not in script
