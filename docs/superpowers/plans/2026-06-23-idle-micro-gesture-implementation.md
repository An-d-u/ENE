# Idle Micro Gesture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional idle micro-gesture scheduler so ENE occasionally performs small Live2D gestures while not speaking or being interacted with.

**Architecture:** Reuse the existing synthetic gesture engine in `assets/web/runtime_gesture_engine.js`. Python settings and the settings dialog store two new values, then `OverlayWindow._sync_idle_motion_settings_to_js()` sends them into the WebView. The WebView owns timer scheduling, guard checks, and gesture playback so it can coordinate with existing head-pat and speech gesture state.

**Tech Stack:** PyQt6 settings UI, ENE `Settings`, WebView JavaScript runtime, pytest smoke tests, `node --check`.

---

## Current Context

- Repo root: `C:/Users/umpad/Desktop/coding/ENE`
- Spec: `docs/superpowers/specs/2026-06-23-idle-micro-gesture-design.md`
- There are already unstaged gesture-scale changes in the working tree. Do not revert them.
- The new idle gestures must reuse the existing `synthetic_gesture_scale` setting.
- Do not stage or commit `docs/mockups/` or `.superpowers/` brainstorm files.

## File Structure

- Modify `src/core/settings.py`
  - Owns default values for `enable_idle_synthetic_gestures` and `idle_synthetic_gesture_frequency`.
- Modify `src/ui/settings_tabs/behavior_tab.py`
  - Adds the idle gesture checkbox and frequency combo inside the existing `응답 제스처` group.
- Modify `src/ui/settings_dialog_values.py`
  - Loads and saves the two new settings.
- Modify `src/core/overlay_window.py`
  - Syncs idle gesture enabled/frequency values into the WebView.
- Modify `assets/web/runtime_gesture_engine.js`
  - Adds small idle-only gestures, scheduler state, frequency presets, speech/head-pat guards, and public setter.
- Modify locale files:
  - `src/locales/ko.json`
  - `src/locales/en.json`
  - `src/locales/ja.json`
- Modify tests:
  - `tests/test_settings.py`
  - `tests/test_ui_i18n_smoke.py`
  - `tests/test_chat_ui_assets.py`

## Verification Environment

Use this PowerShell prefix for pytest commands:

```powershell
$repo = (Get-Location).Path
$site = 'C:\Users\umpad\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\site-packages'
$env:PYTHONPATH = "$repo;$site"
```

---

### Task 1: Settings Defaults

**Files:**
- Modify: `C:/Users/umpad/Desktop/coding/ENE/tests/test_settings.py`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/src/core/settings.py`

- [ ] **Step 1: Write the failing test**

In `test_load_missing_file_uses_default_config`, add:

```python
assert settings.get("enable_idle_synthetic_gestures") is False
assert settings.get("idle_synthetic_gesture_frequency") == "normal"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'C:\Users\umpad\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -p no:cacheprovider tests/test_settings.py::test_load_missing_file_uses_default_config -q
```

Expected: FAIL because the settings are not in defaults yet.

- [ ] **Step 3: Write minimal implementation**

In `Settings.DEFAULT_CONFIG`, add near `enable_synthetic_gestures`:

```python
"enable_idle_synthetic_gestures": False,
"idle_synthetic_gesture_frequency": "normal",
```

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.

Expected: PASS.

- [ ] **Step 5: Commit**

Only if the user wants stepwise commits during implementation:

```powershell
git add src/core/settings.py tests/test_settings.py
git commit -m "feat: add idle gesture settings defaults"
```

---

### Task 2: Settings Dialog Controls

**Files:**
- Modify: `C:/Users/umpad/Desktop/coding/ENE/tests/test_ui_i18n_smoke.py`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/src/ui/settings_tabs/behavior_tab.py`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/src/ui/settings_dialog_values.py`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/src/locales/ko.json`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/src/locales/en.json`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/src/locales/ja.json`

- [ ] **Step 1: Write the failing test**

Extend `test_settings_dialog_exposes_synthetic_gesture_controls_and_saves_values`:

```python
dialog = SettingsDialog(
    {
        "ui_language": "ko",
        "llm_provider": "gemini",
        "tts_provider": "gpt_sovits_http",
        "enable_tts": True,
        "enable_synthetic_gestures": False,
        "synthetic_gesture_scale": 1.4,
        "enable_idle_synthetic_gestures": True,
        "idle_synthetic_gesture_frequency": "high",
    }
)

assert dialog.enable_idle_synthetic_gestures_check.isChecked() is True
assert dialog.idle_synthetic_gesture_frequency_combo.currentData() == "high"

dialog.enable_idle_synthetic_gestures_check.setChecked(False)
low_index = dialog.idle_synthetic_gesture_frequency_combo.findData("low")
dialog.idle_synthetic_gesture_frequency_combo.setCurrentIndex(low_index)

current_values = dialog._get_current_values()
assert current_values["enable_idle_synthetic_gestures"] is False
assert current_values["idle_synthetic_gesture_frequency"] == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'C:\Users\umpad\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -p no:cacheprovider tests/test_ui_i18n_smoke.py::test_settings_dialog_exposes_synthetic_gesture_controls_and_saves_values -q
```

Expected: FAIL because the checkbox/combo attributes do not exist.

- [ ] **Step 3: Add UI controls**

In `behavior_tab.py`, inside `gesture_group` after `synthetic_gesture_scale_spin`, add:

```python
self.enable_idle_synthetic_gestures_check = self._create_toggle(
    "유휴 제스처 사용",
    key="settings.behavior.gesture.idle_enable",
)
self.enable_idle_synthetic_gestures_check.toggled.connect(self._on_setting_changed)
gesture_layout.addRow(self.enable_idle_synthetic_gestures_check)

self.idle_synthetic_gesture_frequency_combo = QComboBox()
for key, fallback, value in [
    ("settings.behavior.gesture.idle_frequency.low", "낮음", "low"),
    ("settings.behavior.gesture.idle_frequency.normal", "보통", "normal"),
    ("settings.behavior.gesture.idle_frequency.high", "높음", "high"),
]:
    self.idle_synthetic_gesture_frequency_combo.addItem(self._translated_text(key, fallback), value)
    self._bind_combo_item(
        self.idle_synthetic_gesture_frequency_combo,
        self.idle_synthetic_gesture_frequency_combo.count() - 1,
        key,
        fallback,
    )
self.idle_synthetic_gesture_frequency_combo.currentIndexChanged.connect(self._on_setting_changed)
self._add_form_row(
    gesture_layout,
    "settings.behavior.gesture.idle_frequency.label",
    "유휴 제스처 빈도:",
    self.idle_synthetic_gesture_frequency_combo,
)
```

- [ ] **Step 4: Load and save values**

In `settings_dialog_values.py`, add load logic near `synthetic_gesture_scale_spin`:

```python
self.enable_idle_synthetic_gestures_check.setChecked(
    self._original_settings.get("enable_idle_synthetic_gestures", False)
)
idle_frequency = str(self._original_settings.get("idle_synthetic_gesture_frequency", "normal")).strip().lower()
if idle_frequency not in {"low", "normal", "high"}:
    idle_frequency = "normal"
idle_frequency_index = self.idle_synthetic_gesture_frequency_combo.findData(idle_frequency)
self.idle_synthetic_gesture_frequency_combo.setCurrentIndex(idle_frequency_index if idle_frequency_index >= 0 else 1)
```

In `_get_current_values`, add:

```python
"enable_idle_synthetic_gestures": self.enable_idle_synthetic_gestures_check.isChecked(),
"idle_synthetic_gesture_frequency": str(self.idle_synthetic_gesture_frequency_combo.currentData() or "normal"),
```

- [ ] **Step 5: Add locale keys**

Under `settings.behavior.gesture`, add:

```json
"idle_enable": "유휴 제스처 사용",
"idle_frequency": {
  "label": "유휴 제스처 빈도:",
  "low": "낮음",
  "normal": "보통",
  "high": "높음"
}
```

Use equivalent English and Japanese translations.

- [ ] **Step 6: Run test to verify it passes**

Run the same pytest command.

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/ui/settings_tabs/behavior_tab.py src/ui/settings_dialog_values.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_ui_i18n_smoke.py
git commit -m "feat: add idle gesture settings controls"
```

---

### Task 3: WebView Sync

**Files:**
- Modify: `C:/Users/umpad/Desktop/coding/ENE/tests/test_ui_i18n_smoke.py`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/src/core/overlay_window.py`

- [ ] **Step 1: Write the failing test**

Add a test near `test_overlay_window_syncs_synthetic_gesture_scale_to_webview`:

```python
def test_overlay_window_syncs_idle_synthetic_gesture_settings_to_webview(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir(parents=True, exist_ok=True)
    (locales_dir / "en.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ja.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    from src.core.overlay_window import OverlayWindow

    captured = []

    class _FakePage:
        def runJavaScript(self, code):
            captured.append(code)

    class _FakeWebView:
        def __init__(self):
            self._page = _FakePage()

        def page(self):
            return self._page

    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay.settings = _DummySettings({})
    overlay.web_view = _FakeWebView()
    overlay._page_loaded = True

    OverlayWindow._sync_idle_motion_settings_to_js(
        overlay,
        {
            "enable_idle_synthetic_gestures": True,
            "idle_synthetic_gesture_frequency": "high",
        },
    )

    assert any('window.setIdleSyntheticGestureConfig(true, "high");' in code for code in captured)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'C:\Users\umpad\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -p no:cacheprovider tests/test_ui_i18n_smoke.py::test_overlay_window_syncs_idle_synthetic_gesture_settings_to_webview -q
```

Expected: FAIL because no JS sync exists.

- [ ] **Step 3: Implement sync**

In `_sync_idle_motion_settings_to_js`, normalize:

```python
idle_synthetic_gestures_enabled = "true" if bool(source.get("enable_idle_synthetic_gestures", False)) else "false"
idle_synthetic_gesture_frequency = str(source.get("idle_synthetic_gesture_frequency", "normal")).strip().lower()
if idle_synthetic_gesture_frequency not in {"low", "normal", "high"}:
    idle_synthetic_gesture_frequency = "normal"
```

After `setSyntheticGestureScale`, add:

```python
self.web_view.page().runJavaScript(
    "(function(){"
    "if (typeof window.setIdleSyntheticGestureConfig === 'function') {"
    f"window.setIdleSyntheticGestureConfig({idle_synthetic_gestures_enabled}, "
    f"{json.dumps(idle_synthetic_gesture_frequency)});"
    "}"
    "})();"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core/overlay_window.py tests/test_ui_i18n_smoke.py
git commit -m "feat: sync idle gesture settings to webview"
```

---

### Task 4: Runtime Scheduler

**Files:**
- Modify: `C:/Users/umpad/Desktop/coding/ENE/tests/test_chat_ui_assets.py`
- Modify: `C:/Users/umpad/Desktop/coding/ENE/assets/web/runtime_gesture_engine.js`

- [ ] **Step 1: Write the failing asset smoke test**

Extend `test_gesture_engine_exposes_chat_gesture_player` with:

```python
assert "const IDLE_SYNTHETIC_GESTURE_FREQUENCIES = {" in script
assert "const IDLE_SYNTHETIC_GESTURES = [" in script
assert "function setIdleSyntheticGestureConfig(enabled, frequency)" in script
assert "function scheduleNextIdleSyntheticGesture()" in script
assert "window.setIdleSyntheticGestureConfig = setIdleSyntheticGestureConfig;" in script
assert "lastSyntheticSpeechActivityAt" in script
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'C:\Users\umpad\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -p no:cacheprovider tests/test_chat_ui_assets.py::test_gesture_engine_exposes_chat_gesture_player -q
```

Expected: FAIL because scheduler API is missing.

- [ ] **Step 3: Add idle scheduler state**

In `runtime_gesture_engine.js`, add near existing state:

```javascript
const IDLE_SYNTHETIC_GESTURE_FREQUENCIES = {
    low: { minMs: 20000, maxMs: 45000 },
    normal: { minMs: 12000, maxMs: 28000 },
    high: { minMs: 7000, maxMs: 16000 },
};
const IDLE_SYNTHETIC_GESTURES = ["idle-look-around", "idle-tiny-nod", "idle-cute-tilt", "idle-settle"];
const IDLE_SYNTHETIC_GESTURE_SPEECH_GRACE_MS = 1800;
const IDLE_SYNTHETIC_GESTURE_FINISH_COOLDOWN_MS = 3000;
let idleSyntheticGestureEnabled = false;
let idleSyntheticGestureFrequency = "normal";
let idleSyntheticGestureTimer = 0;
let lastSyntheticSpeechActivityAt = 0;
let lastSyntheticGestureFinishedAt = 0;
```

- [ ] **Step 4: Add idle-only gestures**

Add small entries to `SYNTHETIC_GESTURES`:

```javascript
"idle-look-around": {
    durationMs: 1500,
    frames: [
        { t: 0.00, value: {} },
        { t: 0.28, value: { angleX: -5, eyeX: -0.18 } },
        { t: 0.58, value: { angleX: 5, eyeX: 0.18 } },
        { t: 1.00, value: {} },
    ],
},
"idle-tiny-nod": {
    durationMs: 1200,
    frames: [
        { t: 0.00, value: {} },
        { t: 0.36, value: { angleY: -4, eyeY: -0.08 } },
        { t: 0.68, value: { angleY: 3, eyeY: 0.05 } },
        { t: 1.00, value: {} },
    ],
},
"idle-cute-tilt": {
    durationMs: 1600,
    frames: [
        { t: 0.00, value: {} },
        { t: 0.38, value: { angleX: -4, angleZ: -7, eyeX: 0.08 } },
        { t: 0.72, value: { angleX: -3, angleZ: -6, eyeX: 0.05 } },
        { t: 1.00, value: {} },
    ],
},
"idle-settle": {
    durationMs: 1400,
    frames: [
        { t: 0.00, value: {} },
        { t: 0.35, value: { bodyY: -0.8, breath: 0.2 } },
        { t: 0.70, value: { bodyY: 0.4, breath: 0.1 } },
        { t: 1.00, value: {} },
    ],
},
```

- [ ] **Step 5: Track speech and gesture finish times**

In `notifySyntheticGestureSpeechActivity`, set:

```javascript
lastSyntheticSpeechActivityAt = performance.now();
```

In `stopSyntheticGesture`, after clearing state, set:

```javascript
lastSyntheticGestureFinishedAt = performance.now();
```

If this makes stop calls during startup count as a cooldown, guard it with the previous `activeGestureKey`.

- [ ] **Step 6: Add scheduler functions**

Implement:

```javascript
function clearIdleSyntheticGestureTimer() {
    if (idleSyntheticGestureTimer) {
        clearTimeout(idleSyntheticGestureTimer);
        idleSyntheticGestureTimer = 0;
    }
}

function normalizeIdleSyntheticGestureFrequency(frequency) {
    const key = String(frequency || "normal").trim().toLowerCase();
    return IDLE_SYNTHETIC_GESTURE_FREQUENCIES[key] ? key : "normal";
}

function canPlayIdleSyntheticGesture() {
    if (!idleSyntheticGestureEnabled) return false;
    if (activeGestureKey || pendingSpeechGestureKey || pendingSpeechGestureTimer || pendingSpeechGestureFallbackTimer) return false;
    if (typeof window.setSyntheticGestureOffsets !== "function") return false;
    if (typeof window.isHeadPatEffectActive === "function" && window.isHeadPatEffectActive()) return false;
    const nowMs = performance.now();
    if (nowMs - lastSyntheticSpeechActivityAt < IDLE_SYNTHETIC_GESTURE_SPEECH_GRACE_MS) return false;
    if (nowMs - lastSyntheticGestureFinishedAt < IDLE_SYNTHETIC_GESTURE_FINISH_COOLDOWN_MS) return false;
    return true;
}

function pickIdleSyntheticGesture() {
    const index = Math.floor(Math.random() * IDLE_SYNTHETIC_GESTURES.length);
    return IDLE_SYNTHETIC_GESTURES[index] || "idle-look-around";
}

function scheduleNextIdleSyntheticGesture() {
    clearIdleSyntheticGestureTimer();
    if (!idleSyntheticGestureEnabled) return false;
    const preset = IDLE_SYNTHETIC_GESTURE_FREQUENCIES[idleSyntheticGestureFrequency] || IDLE_SYNTHETIC_GESTURE_FREQUENCIES.normal;
    const delayMs = preset.minMs + (Math.random() * (preset.maxMs - preset.minMs));
    idleSyntheticGestureTimer = setTimeout(function () {
        idleSyntheticGestureTimer = 0;
        if (canPlayIdleSyntheticGesture()) {
            playSyntheticGesture(pickIdleSyntheticGesture());
        }
        scheduleNextIdleSyntheticGesture();
    }, delayMs);
    return true;
}

function setIdleSyntheticGestureConfig(enabled, frequency) {
    idleSyntheticGestureEnabled = Boolean(enabled);
    idleSyntheticGestureFrequency = normalizeIdleSyntheticGestureFrequency(frequency);
    clearIdleSyntheticGestureTimer();
    if (idleSyntheticGestureEnabled) {
        scheduleNextIdleSyntheticGesture();
    }
    return { enabled: idleSyntheticGestureEnabled, frequency: idleSyntheticGestureFrequency };
}
```

- [ ] **Step 7: Export public API**

Add:

```javascript
window.setIdleSyntheticGestureConfig = setIdleSyntheticGestureConfig;
```

- [ ] **Step 8: Run asset test and JS syntax check**

Run:

```powershell
& 'C:\Users\umpad\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -p no:cacheprovider tests/test_chat_ui_assets.py::test_gesture_engine_exposes_chat_gesture_player -q
node --check .\assets\web\runtime_gesture_engine.js
```

Expected: both PASS.

- [ ] **Step 9: Commit**

```powershell
git add assets/web/runtime_gesture_engine.js tests/test_chat_ui_assets.py
git commit -m "feat: add idle synthetic gesture scheduler"
```

---

### Task 5: Integrated Verification

**Files:**
- Verify only unless a prior task failed.

- [ ] **Step 1: Run focused regression tests**

Run:

```powershell
& 'C:\Users\umpad\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -p no:cacheprovider tests/test_settings.py::test_load_missing_file_uses_default_config tests/test_ui_i18n_smoke.py::test_settings_dialog_exposes_synthetic_gesture_controls_and_saves_values tests/test_ui_i18n_smoke.py::test_overlay_window_syncs_synthetic_gesture_scale_to_webview tests/test_ui_i18n_smoke.py::test_overlay_window_syncs_idle_synthetic_gesture_settings_to_webview tests/test_chat_ui_assets.py::test_gesture_engine_exposes_chat_gesture_player -q
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run syntax and format checks**

Run:

```powershell
node --check .\assets\web\runtime_gesture_engine.js
git diff --check
```

Expected: exit code 0.

- [ ] **Step 3: Validate JSON locales**

Run:

```powershell
@'
import json
from pathlib import Path
for path in ['src/locales/ko.json', 'src/locales/en.json', 'src/locales/ja.json']:
    json.loads(Path(path).read_text(encoding='utf-8-sig'))
    print(f'{path}: ok')
'@ | python -
```

Expected: all three locale files print `ok`.

- [ ] **Step 4: Check BOM for edited files**

Run:

```powershell
@'
from pathlib import Path
paths = [
    'assets/web/runtime_gesture_engine.js',
    'src/core/overlay_window.py',
    'src/core/settings.py',
    'src/locales/en.json',
    'src/locales/ja.json',
    'src/locales/ko.json',
    'src/ui/settings_dialog_values.py',
    'src/ui/settings_tabs/behavior_tab.py',
    'tests/test_chat_ui_assets.py',
    'tests/test_settings.py',
    'tests/test_ui_i18n_smoke.py',
]
for path in paths:
    data = Path(path).read_bytes()[:3]
    print(f'{path}: {data.hex()}')
'@ | python -
```

Expected: each file starts with `efbbbf`.

- [ ] **Step 5: Pre-commit privacy scan**

Run:

```powershell
rg -n "api[_-]?key|secret|token|password|bearer|sk-|생일|건강|일정|자소서|이름|주소|전화|email|메일|프롬프트 원문|실제 대화|사용자 대화" src assets tests docs/superpowers/specs/2026-06-23-idle-micro-gesture-design.md docs/superpowers/plans/2026-06-23-idle-micro-gesture-implementation.md
```

Expected: no unexpected matches. If matches are found, inspect them before committing.

- [ ] **Step 6: Final commit if tasks were not committed stepwise**

If prior task commits were skipped, stage only the intended source/test files:

```powershell
git add assets/web/runtime_gesture_engine.js src/core/overlay_window.py src/core/settings.py src/locales/en.json src/locales/ja.json src/locales/ko.json src/ui/settings_dialog_values.py src/ui/settings_tabs/behavior_tab.py tests/test_chat_ui_assets.py tests/test_settings.py tests/test_ui_i18n_smoke.py
git commit -m "feat: add idle synthetic gestures"
```

Do not add:

- `docs/mockups/`
- `.superpowers/`
- runtime config files such as `config.json`, `memory.json`, `.env*`

---

## Implementation Notes

- Keep default `enable_idle_synthetic_gestures` as `false` because the feature is experimental.
- The frequency setting controls candidate checks, not guaranteed gesture playback.
- Idle gestures should be small. Do not reuse large response gestures like `surprise` or `sway` for idle V1.
- If `stopSyntheticGesture()` updates cooldown for every internal cleanup, it may delay first idle gesture after enabling. Prefer updating cooldown only when a gesture was actually active.
- If browser TTS or lip-sync updates call `notifySyntheticGestureSpeechActivity()`, that should also delay idle gestures even when no `[gesture:...]` tag exists.
- If implementation reveals that speech activity is not always reported during some TTS path, add a minimal browser-side public function later rather than expanding this V1 now.
