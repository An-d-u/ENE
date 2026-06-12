# Live2D Parameter Inspector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE 클라이언트 안에서 현재 Live2D 모델의 파라미터를 탐색하고, 장식용 파라미터 값을 모델별로 저장해 재시작 후에도 유지한다.

**Architecture:** 웹 런타임에 `runtime_live2d_parameters.js`를 추가해 파라미터 목록, 패널 UI, 미리보기, 프레임 후반 오버라이드 적용을 맡긴다. Python 쪽은 새 bridge mixin으로 모델별 저장값을 검증하고 `Settings`의 `live2d_parameter_overrides`에 저장한다. `OverlayWindow`는 현재 모델 key와 저장 payload를 JS에 전달한다.

**Tech Stack:** PyQt6 `QWebChannel`, `QWebEngineView.runJavaScript`, Pixi Live2D runtime, vanilla JavaScript classic scripts, pytest asset/string tests.

---

## File Structure

- Create `assets/web/runtime_live2d_parameters.js`
  - Live2D 파라미터 metadata 수집, 추천 필터, 오버라이드 상태, 프레임 후반 적용 훅, 패널 렌더링과 저장 이벤트를 담당한다.
- Create `src/core/bridge_mixins/live2d_parameters.py`
  - `get_live2d_parameter_overrides(...)`, `save_live2d_parameter_overrides(...)` QWebChannel 슬롯과 payload 검증을 담당한다.
- Modify `src/core/bridge.py`
  - `Live2DParameterBridgeMixin`을 `WebBridge`에 추가한다.
- Modify `src/core/overlay_window.py`
  - 현재 모델 key와 저장된 override payload를 `window.eneModelConfig`에 전달한다.
- Modify `src/core/settings.py`
  - `live2d_parameter_overrides` 기본값 `{}`를 추가한다.
- Modify `assets/web/index.html`
  - 빠른 메뉴 `Live2D` 버튼, floating panel DOM, 새 script chunk를 추가한다.
- Modify `assets/web/runtime_chat_state.js`
  - 새 DOM 참조와 패널 상태 변수를 추가한다.
- Modify `assets/web/runtime_ui_strings.js`
  - Live2D 버튼/패널/주의문 문구를 런타임 i18n에 연결한다.
- Modify `assets/web/runtime_live2d_model.js`
  - 모델 로드/변경 완료 후 파라미터 런타임에 알린다.
- Modify `assets/web/style.css`
  - 기존 floating panel 언어에 맞춘 inspector 스타일을 추가한다.
- Modify `src/locales/en.json`, `src/locales/ko.json`, `src/locales/ja.json`
  - 버튼, 패널, 주의문, 빈 상태, 저장/초기화 문구를 추가한다.
- Modify tests
  - `tests/test_chat_ui_assets.py`
  - `tests/test_settings.py`
  - `tests/test_bridge_attachment_slots.py`
  - Add `tests/test_bridge_live2d_parameters.py`

---

### Task 1: 웹 런타임 오버라이드 레이어 계약

**Files:**
- Create: `assets/web/runtime_live2d_parameters.js`
- Modify: `assets/web/index.html`
- Modify: `tests/test_chat_ui_assets.py`

- [ ] **Step 1: script order 실패 테스트 추가**

`tests/test_chat_ui_assets.py`의 `EXPECTED_RUNTIME_SCRIPTS`에서 `runtime_live2d_parameters.js`를 `runtime_lipsync.js` 뒤, `script.js` 앞에 넣는다.

```python
EXPECTED_RUNTIME_SCRIPTS = [
    "runtime_bootstrap.js",
    "runtime_live2d_model.js",
    "runtime_motion_state.js",
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
    "runtime_live2d_parameters.js",
    "script.js",
]
```

추가 테스트:

```python
def test_live2d_parameter_runtime_loads_after_live2d_writers():
    script_order = {script_name: index for index, script_name in enumerate(EXPECTED_RUNTIME_SCRIPTS)}
    parameter_index = script_order["runtime_live2d_parameters.js"]
    for dependency in [
        "runtime_live2d_model.js",
        "runtime_motion_state.js",
        "runtime_head_pat.js",
        "runtime_auto_blink_tracking.js",
        "runtime_expression.js",
        "runtime_lipsync.js",
    ]:
        assert script_order[dependency] < parameter_index
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_web_runtime_is_split_into_ordered_scripts tests/test_chat_ui_assets.py::test_live2d_parameter_runtime_loads_after_live2d_writers -q`

Expected: `runtime_live2d_parameters.js`가 없거나 script order가 달라 실패한다.

- [ ] **Step 3: 최소 script chunk 추가**

`assets/web/index.html`에서 `runtime_lipsync.js` 뒤에 추가한다.

```html
<script src="runtime_lipsync.js"></script>
<script src="runtime_live2d_parameters.js"></script>
<script src="script.js"></script>
```

`assets/web/runtime_live2d_parameters.js`를 UTF-8 BOM으로 만들고 다음 skeleton을 넣는다.

```javascript
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
    applyHookModel: null,
};

function getLive2DParameterCoreModel() {
    const model = window.live2dModel;
    return model && model.internalModel && model.internalModel.coreModel
        ? model.internalModel.coreModel
        : null;
}

function isRecommendedLive2DParameter(paramId) {
    return !LIVE2D_PARAMETER_RECOMMENDED_EXCLUDE_KEYWORDS.some((keyword) => String(paramId || '').startsWith(keyword));
}

function getLive2DParameterOverrideValues() {
    const merged = { ...live2dParameterState.values, ...live2dParameterState.dirtyValues };
    live2dParameterState.removedValues.forEach((paramId) => {
        delete merged[paramId];
    });
    return merged;
}

function applyLive2DParameterOverrides() {
    const coreModel = getLive2DParameterCoreModel();
    if (!coreModel || typeof coreModel.setParameterValueById !== 'function') {
        return false;
    }
    Object.entries(getLive2DParameterOverrideValues()).forEach(([paramId, value]) => {
        const numericValue = Number(value);
        if (!paramId || !Number.isFinite(numericValue)) {
            return;
        }
        try {
            if (typeof coreModel.getParameterIndex === 'function' && coreModel.getParameterIndex(paramId) < 0) {
                return;
            }
            coreModel.setParameterValueById(paramId, numericValue);
        } catch (error) {
            console.warn(`Failed to apply Live2D parameter override ${paramId}:`, error);
        }
    });
    return true;
}

function bindLive2DParameterOverrideHook() {
    const model = window.live2dModel;
    const internalModel = model && model.internalModel ? model.internalModel : null;
    if (!internalModel || typeof internalModel.on !== 'function') {
        return false;
    }
    if (live2dParameterState.applyHookModel === internalModel) {
        return true;
    }
    internalModel.on('beforeModelUpdate', () => {
        applyLive2DParameterOverrides();
    });
    live2dParameterState.applyHookModel = internalModel;
    return true;
}

window.applyLive2DParameterOverrides = applyLive2DParameterOverrides;
window.onLive2DParameterModelChanged = function onLive2DParameterModelChanged(config = {}) {
    live2dParameterState.modelKey = String(config.modelKey || '');
    live2dParameterState.values = { ...((config.parameterOverrides && config.parameterOverrides.values) || {}) };
    live2dParameterState.pinned = new Set((config.parameterOverrides && config.parameterOverrides.pinned) || []);
    live2dParameterState.dirtyValues = {};
    live2dParameterState.removedValues = new Set();
    bindLive2DParameterOverrideHook();
    applyLive2DParameterOverrides();
};
```

이 훅은 `runtime_expression.js` 뒤에 로드되는 `runtime_live2d_parameters.js`에서 등록한다. `pixi-live2d-display`의 `beforeModelUpdate` 이벤트는 렌더 직전 Live2D 내부 업데이트 경로에 붙으며, 같은 이벤트에 등록된 기존 expression hook 뒤에 등록되어 저장된 장식 override가 마지막에 다시 적용되는 계약을 만든다.

- [ ] **Step 4: hook 계약 테스트 추가**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_live2d_parameter_runtime_applies_overrides_in_late_internal_model_hook():
    script = _script_text()

    assert "const LIVE2D_PARAMETER_RECOMMENDED_EXCLUDE_KEYWORDS = [" in script
    assert "'ParamEye'," in script
    assert "'ParamMouth'," in script
    assert "function applyLive2DParameterOverrides()" in script
    assert "removedValues: new Set()" in script
    assert "live2dParameterState.removedValues.forEach" in script
    assert "applyHookModel: null" in script
    assert "internalModel.on('beforeModelUpdate', () => {" in script
    assert "live2dParameterState.applyHookModel === internalModel" in script
    assert "applyLive2DParameterOverrides();" in script
    assert "window.onLive2DParameterModelChanged = function" in script
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_web_runtime_is_split_into_ordered_scripts tests/test_chat_ui_assets.py::test_live2d_parameter_runtime_loads_after_live2d_writers tests/test_chat_ui_assets.py::test_live2d_parameter_runtime_applies_overrides_in_late_internal_model_hook -q`

Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add assets/web/index.html assets/web/runtime_live2d_parameters.js tests/test_chat_ui_assets.py
git commit -m "feat: add Live2D parameter override runtime"
```

---

### Task 2: 모델별 저장 브리지

**Files:**
- Create: `src/core/bridge_mixins/live2d_parameters.py`
- Create: `tests/test_bridge_live2d_parameters.py`
- Modify: `src/core/bridge.py`
- Modify: `tests/test_bridge_attachment_slots.py`
- Modify: `src/core/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 설정 기본값 실패 테스트 추가**

`tests/test_settings.py`의 `test_load_missing_file_uses_default_config`에 추가한다.

```python
assert settings.get("live2d_parameter_overrides") == {}
```

Run: `pytest tests/test_settings.py::test_load_missing_file_uses_default_config -q`

Expected: FAIL.

- [ ] **Step 2: 설정 기본값 구현**

`src/core/settings.py`의 `DEFAULT_CONFIG`에 추가한다.

```python
"live2d_parameter_overrides": {},
```

Run: `pytest tests/test_settings.py::test_load_missing_file_uses_default_config -q`

Expected: PASS.

- [ ] **Step 3: bridge 저장/조회 실패 테스트 추가**

`tests/test_bridge_live2d_parameters.py` 생성.

```python
import json

from src.core.bridge import WebBridge
from src.core.settings import Settings


def _bridge_with_settings(tmp_path):
    settings = Settings(
        config_path=str(tmp_path / "config.json"),
        secret_path=str(tmp_path / "api_keys.json"),
    )
    return WebBridge(settings=settings), settings


def test_live2d_parameter_overrides_are_saved_per_model(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps(
            {
                "values": {"ParamRibbon": 1.0},
                "pinned": ["ParamRibbon"],
            },
            ensure_ascii=False,
        ),
    )
    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-b/runtime/model.model3.json",
        json.dumps(
            {
                "values": {"ParamHat": 0.5},
                "pinned": ["ParamHat"],
            },
            ensure_ascii=False,
        ),
    )

    model_a = json.loads(bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json"))
    model_b = json.loads(bridge.get_live2d_parameter_overrides("assets/live2d_models/model-b/runtime/model.model3.json"))

    assert model_a == {"values": {"ParamRibbon": 1.0}, "pinned": ["ParamRibbon"]}
    assert model_b == {"values": {"ParamHat": 0.5}, "pinned": ["ParamHat"]}
    assert settings.get("live2d_parameter_overrides")["assets/live2d_models/model-a/runtime/model.model3.json"]["values"]["ParamRibbon"] == 1.0


def test_live2d_parameter_overrides_reject_invalid_payload(tmp_path):
    bridge, settings = _bridge_with_settings(tmp_path)

    bridge.save_live2d_parameter_overrides(
        "assets/live2d_models/model-a/runtime/model.model3.json",
        json.dumps({"values": {"ParamRibbon": "not-a-number"}, "pinned": [123]}, ensure_ascii=False),
    )

    assert settings.get("live2d_parameter_overrides") == {}
    assert json.loads(bridge.get_live2d_parameter_overrides("assets/live2d_models/model-a/runtime/model.model3.json")) == {
        "values": {},
        "pinned": [],
    }
```

Run: `pytest tests/test_bridge_live2d_parameters.py -q`

Expected: FAIL because slots do not exist.

- [ ] **Step 4: bridge mixin 구현**

`src/core/bridge_mixins/live2d_parameters.py` 생성.

```python
"""Live2D 파라미터 저장 브리지."""
from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import pyqtSlot


def _empty_payload() -> dict[str, Any]:
    return {"values": {}, "pinned": []}


def _normalize_model_key(model_key: str) -> str:
    return str(model_key or "").strip().replace("\\", "/")


def _normalize_override_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    raw_values = payload.get("values", {})
    raw_pinned = payload.get("pinned", [])
    if not isinstance(raw_values, dict) or not isinstance(raw_pinned, list):
        return None

    values: dict[str, float] = {}
    for key, value in raw_values.items():
        param_id = str(key or "").strip()
        if not param_id:
            return None
        try:
            numeric_value = float(value)
        except Exception:
            return None
        if not (-1.0e9 < numeric_value < 1.0e9):
            return None
        values[param_id] = numeric_value

    pinned: list[str] = []
    seen: set[str] = set()
    for item in raw_pinned:
        if not isinstance(item, str):
            return None
        param_id = item.strip()
        if not param_id or param_id in seen:
            continue
        seen.add(param_id)
        pinned.append(param_id)

    return {"values": values, "pinned": pinned}


class Live2DParameterBridgeMixin:
    """JS에서 Live2D 파라미터 저장값을 읽고 저장하는 슬롯."""

    @pyqtSlot(str, result=str)
    def get_live2d_parameter_overrides(self, model_key: str) -> str:
        key = _normalize_model_key(model_key)
        if not key or not self.settings:
            return json.dumps(_empty_payload(), ensure_ascii=False)
        overrides = self.settings.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            return json.dumps(_empty_payload(), ensure_ascii=False)
        payload = _normalize_override_payload(overrides.get(key, {})) or _empty_payload()
        return json.dumps(payload, ensure_ascii=False)

    @pyqtSlot(str, str)
    def save_live2d_parameter_overrides(self, model_key: str, payload_json: str) -> None:
        key = _normalize_model_key(model_key)
        if not key or not self.settings:
            return
        try:
            raw_payload = json.loads(str(payload_json or "{}"))
        except Exception:
            return
        payload = _normalize_override_payload(raw_payload)
        if payload is None:
            return

        overrides = self.settings.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        if payload == _empty_payload():
            overrides.pop(key, None)
        else:
            overrides[key] = payload
        self.settings.set("live2d_parameter_overrides", overrides)
        self.settings.save()
```

- [ ] **Step 5: WebBridge에 mixin 연결**

`src/core/bridge.py` import 추가.

```python
from .bridge_mixins.live2d_parameters import Live2DParameterBridgeMixin
```

`WebBridge` 상속 목록에서 `Live2DParameterBridgeMixin`을 기능 mixin들과 함께 추가한다.

```python
class WebBridge(
    AwayNudgeBridgeMixin,
    AttachmentBridgeMixin,
    Live2DParameterBridgeMixin,
    ChatFlowBridgeMixin,
    GoalBridgeMixin,
    MoodBridgeMixin,
    ObsidianBridgeMixin,
    MemorySummaryBridgeMixin,
    PromiseBridgeMixin,
    ProactiveBridgeMixin,
    ThoughtBridgeMixin,
    TTSBridgeMixin,
    BridgeStateAliasMixin,
    QObject,
):
```

- [ ] **Step 6: QWebChannel 노출 테스트 갱신**

`tests/test_bridge_attachment_slots.py`의 `JS_CALLABLE_BRIDGE_METHODS`에 추가한다.

```python
"get_live2d_parameter_overrides",
"save_live2d_parameter_overrides",
```

Run: `pytest tests/test_bridge_live2d_parameters.py tests/test_bridge_attachment_slots.py tests/test_settings.py::test_load_missing_file_uses_default_config -q`

Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add src/core/settings.py src/core/bridge.py src/core/bridge_mixins/live2d_parameters.py tests/test_settings.py tests/test_bridge_live2d_parameters.py tests/test_bridge_attachment_slots.py
git commit -m "feat: persist Live2D parameter overrides"
```

---

### Task 3: 모델 key와 저장값 JS 동기화

**Files:**
- Modify: `src/core/overlay_window.py`
- Modify: `assets/web/runtime_live2d_model.js`
- Modify: `tests/test_chat_ui_assets.py`
- Add or extend: existing overlay/settings tests if practical

- [ ] **Step 1: modelKey 전달 계약 테스트 추가**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_live2d_model_notifies_parameter_runtime_after_model_load():
    script = _script_text()

    assert "window.onLive2DParameterModelChanged(window.eneModelConfig);" in script
    assert "parameterOverrides" in script
    assert "modelKey" in script
```

Run: `pytest tests/test_chat_ui_assets.py::test_live2d_model_notifies_parameter_runtime_after_model_load -q`

Expected: FAIL.

- [ ] **Step 2: OverlayWindow payload 구현**

`src/core/overlay_window.py`에 helper를 추가한다.

```python
    def _resolve_model_key(self, settings_source=None) -> str:
        source = settings_source if isinstance(settings_source, dict) else self.settings.config
        raw_path = str(source.get("model_json_path", "") or "").strip()
        if raw_path:
            return raw_path.replace("\\", "/")
        return "assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json"

    def _resolve_live2d_parameter_overrides_payload(self, settings_source=None) -> dict:
        source = settings_source if isinstance(settings_source, dict) else self.settings.config
        model_key = self._resolve_model_key(source)
        overrides = source.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            return {"values": {}, "pinned": []}
        payload = overrides.get(model_key, {})
        if not isinstance(payload, dict):
            return {"values": {}, "pinned": []}
        values = payload.get("values", {})
        pinned = payload.get("pinned", [])
        return {
            "values": values if isinstance(values, dict) else {},
            "pinned": pinned if isinstance(pinned, list) else [],
        }
```

`_apply_model_settings()`와 `preview_settings()`의 `window.eneModelConfig` payload에 추가한다.

```python
model_key = self._resolve_model_key()
parameter_overrides = self._resolve_live2d_parameter_overrides_payload()
```

JS payload:

```javascript
modelKey: "assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json",
parameterOverrides: {
    values: {},
    pinned: []
}
```

- [ ] **Step 3: 모델 로드 후 JS 알림 구현**

`assets/web/runtime_live2d_model.js`에서 모델 setup 완료 후 호출한다.

```javascript
if (typeof window.onLive2DParameterModelChanged === 'function') {
    window.onLive2DParameterModelChanged(window.eneModelConfig);
}
```

`applyENEModelSettings`에서 모델 경로가 같아 배치만 바뀌는 경우에도 저장 payload가 갱신되도록 호출한다.

```javascript
if (typeof window.onLive2DParameterModelChanged === 'function') {
    window.onLive2DParameterModelChanged(window.eneModelConfig);
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_live2d_model_notifies_parameter_runtime_after_model_load -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/core/overlay_window.py assets/web/runtime_live2d_model.js tests/test_chat_ui_assets.py
git commit -m "feat: sync Live2D parameter overrides to web runtime"
```

---

### Task 4: 인스펙터 패널 DOM, i18n, 스타일

**Files:**
- Modify: `assets/web/index.html`
- Modify: `assets/web/runtime_chat_state.js`
- Modify: `assets/web/runtime_ui_strings.js`
- Modify: `assets/web/style.css`
- Modify: `src/core/overlay_window.py`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/ja.json`
- Modify: `tests/test_chat_ui_assets.py`
- Modify: `tests/test_ui_i18n_smoke.py` if locale smoke requires key fixtures

- [ ] **Step 1: 패널 markup 실패 테스트 추가**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_live2d_parameter_inspector_markup_exists():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")

    assert 'id="live2d-parameters-floating-btn"' in html
    assert 'id="live2d-parameters-panel"' in html
    assert 'id="live2d-parameters-search"' in html
    assert 'id="live2d-parameters-list"' in html
    assert 'id="live2d-parameters-save-btn"' in html
    assert '장식 조절용입니다.' in html
```

Run: `pytest tests/test_chat_ui_assets.py::test_live2d_parameter_inspector_markup_exists -q`

Expected: FAIL.

- [ ] **Step 2: index.html markup 추가**

빠른 메뉴에 추가한다.

```html
<button id="live2d-parameters-floating-btn" title="Live2D 파라미터">Live2D</button>
```

패널을 `goal-status-panel` 근처에 추가한다.

```html
<div id="live2d-parameters-panel" class="hidden" aria-live="polite">
    <div id="live2d-parameters-panel-header">
        <div id="live2d-parameters-panel-title">Live2D 파라미터</div>
        <button id="live2d-parameters-close-btn" type="button" title="닫기" aria-label="닫기">×</button>
    </div>
    <div id="live2d-parameters-warning">장식 조절용입니다. 표정, 눈, 입, 머리, 몸 움직임 관련 파라미터는 표정/립싱크/쓰다듬기와 충돌할 수 있으므로 건드리지 않는 것을 추천합니다.</div>
    <input id="live2d-parameters-search" type="search" placeholder="파라미터 검색">
    <div id="live2d-parameters-tabs" role="tablist">
        <button class="live2d-parameters-tab is-active" type="button" data-live2d-parameter-tab="recommended">추천</button>
        <button class="live2d-parameters-tab" type="button" data-live2d-parameter-tab="all">전체</button>
        <button class="live2d-parameters-tab" type="button" data-live2d-parameter-tab="pinned">고정</button>
    </div>
    <div id="live2d-parameters-list"></div>
    <div id="live2d-parameters-actions">
        <button id="live2d-parameters-reset-btn" type="button">초기화</button>
        <button id="live2d-parameters-save-btn" type="button">저장</button>
    </div>
</div>
```

- [ ] **Step 3: DOM 참조 추가**

`assets/web/runtime_chat_state.js`에 추가한다.

```javascript
const live2dParametersButton = document.getElementById('live2d-parameters-floating-btn');
const live2dParametersPanel = document.getElementById('live2d-parameters-panel');
const live2dParametersCloseButton = document.getElementById('live2d-parameters-close-btn');
const live2dParametersPanelTitle = document.getElementById('live2d-parameters-panel-title');
const live2dParametersWarning = document.getElementById('live2d-parameters-warning');
const live2dParametersSearch = document.getElementById('live2d-parameters-search');
const live2dParametersTabs = document.getElementById('live2d-parameters-tabs');
const live2dParametersList = document.getElementById('live2d-parameters-list');
const live2dParametersSaveButton = document.getElementById('live2d-parameters-save-btn');
const live2dParametersResetButton = document.getElementById('live2d-parameters-reset-btn');
let live2dParametersPanelOpen = false;
```

- [ ] **Step 4: i18n payload 추가**

`DEFAULT_UI_STRINGS`와 `mergeUiStrings`, `applyUiStringsToStaticNodes`에 `live2dParameters`와 actions label을 추가한다.

Python `src/core/overlay_window.py`의 `_resolve_ui_strings_payload()`에 locale key를 추가한다.

Locale keys:

```json
"chat.actions.live2dParameters.label": "Live2D",
"chat.actions.live2dParameters.title": "Live2D parameters",
"chat.live2dParameters.title": "Live2D parameters",
"chat.live2dParameters.warning": "For decoration controls. Avoid expression, eye, mouth, head, and body motion parameters because they may conflict with expressions, lip-sync, and head pats.",
"chat.live2dParameters.search": "Search parameters",
"chat.live2dParameters.recommended": "Recommended",
"chat.live2dParameters.all": "All",
"chat.live2dParameters.pinned": "Pinned",
"chat.live2dParameters.save": "Save",
"chat.live2dParameters.reset": "Reset",
"chat.live2dParameters.empty": "No parameters to show."
```

Korean/Japanese는 자연스럽게 번역하되 실제 사용자 대화나 개인 데이터는 넣지 않는다.

- [ ] **Step 5: CSS 추가**

`assets/web/style.css`에서 기존 `#promise-reminders-panel, #proactive-conversations-panel, #goal-status-panel` 그룹에 `#live2d-parameters-panel`을 포함하고, 별도 row 스타일을 추가한다.

```css
#live2d-parameters-panel {
    position: fixed;
    right: 12px;
    top: 112px;
    width: min(340px, calc(100vw - 24px));
    max-height: min(520px, calc(100vh - 132px));
    overflow: hidden;
    z-index: 1200;
    border: 1px solid var(--ene-floating-panel-border);
    border-radius: 12px;
    background: var(--ene-floating-panel-bg);
    color: var(--ene-floating-panel-text);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22);
    padding: 12px;
}

#live2d-parameters-panel.hidden {
    display: none;
}

#live2d-parameters-warning {
    padding: 8px;
    border-radius: 8px;
    background: rgba(255, 191, 118, 0.13);
    color: var(--ene-floating-panel-muted-text);
    font-size: 11px;
    line-height: 1.45;
}
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_live2d_parameter_inspector_markup_exists tests/test_ui_i18n_smoke.py -q`

Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add assets/web/index.html assets/web/runtime_chat_state.js assets/web/runtime_ui_strings.js assets/web/style.css src/core/overlay_window.py src/locales/en.json src/locales/ko.json src/locales/ja.json tests/test_chat_ui_assets.py tests/test_ui_i18n_smoke.py
git commit -m "feat: add Live2D parameter inspector panel"
```

---

### Task 5: 인스펙터 목록, 검색, 탭, 저장 동작

**Files:**
- Modify: `assets/web/runtime_live2d_parameters.js`
- Modify: `tests/test_chat_ui_assets.py`

- [ ] **Step 1: 렌더링 계약 실패 테스트 추가**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
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
```

Run: `pytest tests/test_chat_ui_assets.py::test_live2d_parameter_runtime_renders_inspector_controls -q`

Expected: FAIL.

- [ ] **Step 2: metadata 수집 구현**

`runtime_live2d_parameters.js`에 metadata 수집 helper를 추가한다. Cubism 내부 구조가 모델마다 다를 수 있으므로 getter 후보를 단계적으로 시도한다.

```javascript
function readLive2DParameterArray(coreModel, names) {
    const sources = [
        coreModel,
        coreModel && coreModel.parameters,
        coreModel && coreModel._model && coreModel._model.parameters,
    ];
    for (const source of sources) {
        if (!source) continue;
        for (const name of names) {
            const value = source[name];
            if (Array.isArray(value)) {
                return value;
            }
        }
    }
    return [];
}

function readLive2DParameterIds(coreModel) {
    if (!coreModel) return [];
    const candidateArrays = [
        coreModel._parameterIds,
        coreModel.parameterIds,
        coreModel._parameterIds && coreModel._parameterIds.values,
        coreModel.parameters && coreModel.parameters.ids,
        readLive2DParameterArray(coreModel, ['ids', '_ids', 'parameterIds', '_parameterIds']),
    ];
    for (const candidate of candidateArrays) {
        if (Array.isArray(candidate) && candidate.length > 0) {
            return candidate.map((item) => String(item || '')).filter(Boolean);
        }
    }
    return [];
}

function readLive2DParameterValue(coreModel, paramId, fallback = 0) {
    try {
        if (typeof coreModel.getParameterValueById === 'function') {
            return Number(coreModel.getParameterValueById(paramId));
        }
        if (typeof coreModel.getParameterIndex === 'function' && typeof coreModel.getParameterValueByIndex === 'function') {
            const index = coreModel.getParameterIndex(paramId);
            return index >= 0 ? Number(coreModel.getParameterValueByIndex(index)) : fallback;
        }
    } catch (_) {
    }
    return fallback;
}

function readLive2DParameterIndexedValue(coreModel, paramId, getterNames, arrayNames, fallback) {
    try {
        if (typeof coreModel.getParameterIndex === 'function') {
            const index = coreModel.getParameterIndex(paramId);
            if (index >= 0) {
                for (const getterName of getterNames) {
                    if (typeof coreModel[getterName] === 'function') {
                        const value = Number(coreModel[getterName](index));
                        if (Number.isFinite(value)) return value;
                    }
                }
                const values = readLive2DParameterArray(coreModel, arrayNames);
                if (Array.isArray(values) && index < values.length) {
                    const value = Number(values[index]);
                    if (Number.isFinite(value)) return value;
                }
            }
        }
    } catch (_) {
    }
    return fallback;
}

function collectLive2DParameterMetadata() {
    const coreModel = getLive2DParameterCoreModel();
    const ids = readLive2DParameterIds(coreModel);
    return ids.map((id) => {
        const value = readLive2DParameterValue(coreModel, id, 0);
        const defaultValue = readLive2DParameterIndexedValue(
            coreModel,
            id,
            ['getParameterDefaultValue'],
            ['_parameterDefaultValues', 'parameterDefaultValues', 'defaultValues'],
            value
        );
        const min = readLive2DParameterIndexedValue(
            coreModel,
            id,
            ['getParameterMinimumValue', 'getParameterMinValue'],
            ['_parameterMinimumValues', 'parameterMinimumValues', 'minimumValues', 'minValues'],
            Math.min(defaultValue, value, -1)
        );
        const max = readLive2DParameterIndexedValue(
            coreModel,
            id,
            ['getParameterMaximumValue', 'getParameterMaxValue'],
            ['_parameterMaximumValues', 'parameterMaximumValues', 'maximumValues', 'maxValues'],
            Math.max(defaultValue, value, 1)
        );
        return {
            id,
            value,
            defaultValue,
            min,
            max,
            recommended: isRecommendedLive2DParameter(id),
        };
    });
}
```

Getter/배열 후보가 모두 실패할 때만 fallback을 쓴다. fallback은 슬라이더가 현재값과 기본값을 포함하도록 `min <= value/default <= max`를 보장해야 하며, 실제 Cubism metadata를 읽을 수 있는 모델에서는 실제 min/default/max를 우선한다.

metadata 상태는 `idle | loading | ready | unavailable | error`로 둔다. 모델이 없으면 `loading`, coreModel은 있지만 ID 목록을 읽지 못하면 `unavailable`, 예외가 나면 `error`로 표시한다. `ready`가 아닌 상태에서는 목록 대신 상태 메시지를 렌더링하고 저장 버튼을 비활성화한다.

```javascript
function setLive2DParameterMetadataStatus(status, message = '') {
    live2dParameterState.metadataStatus = status;
    live2dParameterState.metadataError = String(message || '');
    if (live2dParametersSaveButton) {
        live2dParametersSaveButton.disabled = live2dParameterState.metadataStatus !== 'ready';
    }
}
```

- [ ] **Step 3: 패널 열기/닫기와 탭 상태 구현**

```javascript
function setLive2DParameterPanelOpen(open) {
    live2dParametersPanelOpen = Boolean(open);
    if (live2dParametersPanel) {
        live2dParametersPanel.classList.toggle('hidden', !live2dParametersPanelOpen);
    }
    if (live2dParametersPanelOpen) {
        setFloatingActionsOpen(false);
        refreshLive2DParameterInspector();
    }
}

function refreshLive2DParameterInspector() {
    setLive2DParameterMetadataStatus('loading');
    try {
        live2dParameterState.metadata = collectLive2DParameterMetadata();
        setLive2DParameterMetadataStatus(live2dParameterState.metadata.length > 0 ? 'ready' : 'unavailable');
    } catch (error) {
        live2dParameterState.metadata = [];
        setLive2DParameterMetadataStatus('error', error && error.message ? error.message : String(error));
    }
    renderLive2DParameterInspector();
}
```

- [ ] **Step 4: 행 렌더링 구현**

각 행은 변경된 값만 `dirtyValues`에 넣는다. 저장 대상은 `dirtyValues`와 기존 저장 `values`, 그리고 `pinned`이다. 현재 표시된 모든 파라미터를 저장하지 않는다.

```javascript
function setLive2DParameterDirtyValue(paramId, value) {
    const numericValue = Number(value);
    if (!paramId || !Number.isFinite(numericValue)) return;
    live2dParameterState.removedValues.delete(paramId);
    live2dParameterState.dirtyValues[paramId] = numericValue;
    applyLive2DParameterOverrides();
}

function resetLive2DParameterOverride(paramId) {
    if (!paramId) return;
    delete live2dParameterState.dirtyValues[paramId];
    delete live2dParameterState.values[paramId];
    live2dParameterState.removedValues.add(paramId);
    const metadata = live2dParameterState.metadata.find((item) => item.id === paramId);
    if (metadata) {
        try {
            const coreModel = getLive2DParameterCoreModel();
            if (coreModel && typeof coreModel.setParameterValueById === 'function') {
                coreModel.setParameterValueById(paramId, metadata.defaultValue);
            }
        } catch (_) {
        }
    }
    renderLive2DParameterInspector();
}
```

`renderLive2DParameterInspector()`는 metadata 상태가 `ready`가 아니면 상태 메시지를 보여주고 입력/저장을 비활성화한다. `ready`일 때는 검색어와 탭을 기준으로 목록을 필터링한다. 각 행의 초기화 버튼은 `resetLive2DParameterOverride(paramId)`를 호출해 이미 저장된 단일 파라미터 override도 제거할 수 있어야 한다.

- [ ] **Step 5: 저장 구현**

```javascript
function buildLive2DParameterSavePayload() {
    const values = getLive2DParameterOverrideValues();
    return {
        values,
        pinned: Array.from(live2dParameterState.pinned),
    };
}

function saveLive2DParameterOverrides() {
    if (live2dParameterState.metadataStatus !== 'ready') {
        showToast('Live2D 파라미터 목록을 읽은 뒤 저장할 수 있습니다.', 'error');
        return;
    }
    if (!window.pyBridge || typeof window.pyBridge.save_live2d_parameter_overrides !== 'function') {
        showToast('Live2D 파라미터 저장 브리지를 사용할 수 없습니다.', 'error');
        return;
    }
    const payload = buildLive2DParameterSavePayload();
    window.pyBridge.save_live2d_parameter_overrides(
        live2dParameterState.modelKey,
        JSON.stringify(payload)
    );
    live2dParameterState.values = { ...payload.values };
    live2dParameterState.dirtyValues = {};
    live2dParameterState.removedValues = new Set();
    showToast('Live2D 파라미터를 저장했습니다.', 'success');
}
```

이 payload는 기존 저장값과 이번 세션에서 사용자가 변경한 `dirtyValues`, 단일 초기화로 제거한 `removedValues`, 그리고 `pinned` ID만 반영한다. 현재 화면에 보이는 모든 파라미터 metadata를 저장하지 않는다.

- [ ] **Step 6: 이벤트 바인딩**

`live2dParametersButton`, `live2dParametersCloseButton`, search input, tabs, save/reset 버튼 이벤트를 연결한다.

- [ ] **Step 7: 테스트 통과 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_live2d_parameter_runtime_renders_inspector_controls -q`

Expected: PASS.

- [ ] **Step 8: 커밋**

```bash
git add assets/web/runtime_live2d_parameters.js tests/test_chat_ui_assets.py
git commit -m "feat: render Live2D parameter inspector controls"
```

---

### Task 6: 통합 검증과 브라우저 수동 확인

**Files:**
- Modify as needed based on failed tests only.

- [ ] **Step 1: focused tests 실행**

Run:

```bash
pytest tests/test_chat_ui_assets.py tests/test_bridge_live2d_parameters.py tests/test_bridge_attachment_slots.py tests/test_settings.py::test_load_missing_file_uses_default_config tests/test_ui_i18n_smoke.py -q
```

Expected: PASS.

- [ ] **Step 2: 전체 테스트 실행**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 3: 앱 또는 로컬 HTML로 UI 확인**

가능하면 ENE 앱을 실행해 실제 QWebEngine에서 확인한다. 앱 실행이 무겁거나 환경상 어렵다면, 최소한 `assets/web/index.html`을 브라우저에서 열어 패널 DOM이 깨지지 않는지 확인한다. 실제 저장은 QWebChannel이 있어야 하므로 최종 수동 검증은 앱에서 해야 한다.

확인 항목:

- 빠른 메뉴에 `Live2D` 버튼이 보인다.
- 버튼 클릭 시 오른쪽 패널이 열린다.
- 주의문이 표시된다.
- 파라미터 목록 또는 모델 로딩/오류 상태가 표시된다.
- 검색과 탭이 동작한다.
- 저장 버튼은 QWebChannel이 없을 때 오류 toast를 띄우고, 앱 안에서는 설정에 저장한다.

- [ ] **Step 4: 충돌 수동 검증**

앱에서 다음 순서로 확인한다.

1. 장식 후보 파라미터 하나를 변경하고 저장한다.
2. 표정을 변경한다.
3. 립싱크가 있는 응답을 재생한다.
4. 쓰다듬기를 수행한다.
5. 저장한 장식 파라미터 값이 유지되는지 눈으로 확인한다.
6. 앱을 재시작하거나 모델을 다시 로드한 뒤 값이 유지되는지 확인한다.

writer 충돌 검증도 한 번 수행한다. 테스트 목적으로 `ParamMouthOpenY`, `ParamEyeLOpen`, `ParamAngleX`처럼 기존 expression/lip-sync/tracking/head-pat 경로가 건드리는 것으로 알려진 파라미터 하나를 임시로 저장한다. 표정 변경, 립싱크 응답, 쓰다듬기 중 하나를 실행한 뒤 저장값이 다시 덮어써지는지 확인한다. 확인이 끝나면 해당 파라미터는 패널의 초기화 버튼으로 즉시 제거하고 다시 저장한다.

Expected: `beforeModelUpdate` hook에 등록된 `applyLive2DParameterOverrides()`가 기존 writer 이후에 실행되어, 임시 writer-controlled 파라미터도 마지막 저장값으로 복원된다. 이 검증이 실패하면 `runtime_live2d_parameters.js`를 완성 처리하지 말고, 기존 `runtime_expression.js`의 `beforeModelUpdate` 흐름과 공유되는 명시적 after-writers hook으로 옮긴 뒤 테스트 계약을 갱신한다.

- [ ] **Step 5: 커밋 전 검사**

Run:

```bash
git diff --check
git status --short
```

민감정보 후보 검색:

```bash
git diff --cached -- . | rg -i "api[_-]?key|secret|token|password|BEGIN [A-Z ]*PRIVATE KEY|sk-[A-Za-z0-9]|AIza[0-9A-Za-z_-]|생일|건강|일정|실명|자소서"
```

Expected: 실제 비밀값/개인정보 없음.

- [ ] **Step 6: 최종 커밋**

마지막 검증 수정이 있다면 관련 파일만 스테이징한다.

```bash
git add assets/web/runtime_live2d_parameters.js tests/test_chat_ui_assets.py
git commit -m "test: verify Live2D parameter inspector"
```

이미 각 task에서 커밋했고 추가 변경이 없다면 커밋하지 않는다.
