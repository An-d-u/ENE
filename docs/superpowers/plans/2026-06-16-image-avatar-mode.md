# Image Avatar Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live2D 외에 폴더 기반 이미지 아바타 모드를 추가하고, 등록된 감정 이미지 파일명을 내부 프롬프트와 런타임 표시에 함께 사용한다.

**Architecture:** 아바타 모드를 `live2d`와 `image`로 나누고, 감정 발견은 모드별 소스에서 계산한다. Python 설정/오버레이 계층이 이미지 목록과 이미지별 배치값을 웹 런타임에 내려주고, 웹 런타임은 Live2D 모델 또는 이미지 스프라이트 중 하나만 활성화한다.

**Tech Stack:** Python 3, PyQt6, QWebEngine/QWebChannel, JavaScript, PIXI.js, pytest, Node.js 기반 웹 런타임 단위 테스트

---

## 기준 문서

- 설계 문서: `docs/superpowers/specs/2026-06-15-image-avatar-mode-design.md`
- 기존 Live2D 감정 발견: `src/core/model_emotions.py`
- 기존 런타임 프롬프트 감정 연결: `src/ai/prompt_config.py`
- 기존 오버레이 모델 payload: `src/core/overlay_window.py`
- 기존 모델 설정 UI: `src/ui/settings_tabs/model_tab.py`, `src/ui/settings_dialog_values.py`

## 파일 구조

- Create: `src/core/image_avatar.py`
  - 이미지 폴더 경로 해석, 감정 이미지 스캔, `normal` fallback, 이미지별 배치값 정규화를 담당한다.
- Modify: `src/core/model_emotions.py`
  - `avatar_mode`에 따라 Live2D 감정 또는 이미지 감정을 반환하는 얇은 런타임 감정 API를 추가한다.
- Modify: `src/ai/prompt_config.py`
  - 기존 `get_runtime_emotions()`가 새 모드별 감정 API를 사용하게 한다.
- Modify: `src/core/settings.py`
  - 이미지 모드 기본 설정값을 추가한다.
- Modify: `src/core/overlay_window.py`
  - 웹 런타임으로 `avatarMode`, 이미지 asset 목록, 이미지별 배치값, 현재 미리보기 감정 정보를 전달한다.
- Modify: `src/ui/settings_tabs/model_tab.py`
  - 모델 탭에 아바타 모드 선택, 이미지 폴더 선택, 감정 이미지 목록, 선택 이미지 배치 조절 UI를 추가한다.
- Modify: `src/ui/settings_dialog_values.py`
  - 이미지 폴더 탐색, 감정 이미지 목록 갱신, 선택 이미지별 배치값 로드/저장, 미리보기 payload 생성을 추가한다.
- Modify: `src/locales/ko.json`, `src/locales/en.json`, `src/locales/ja.json`
  - 새 설정 UI 문구를 추가한다.
- Create: `assets/web/runtime_image_avatar.js`
  - 이미지 아바타 렌더링, 감정 전환, 이미지별 배치 적용, TTS 바운스를 담당한다.
- Modify: `assets/web/index.html`
  - `runtime_image_avatar.js`를 Live2D 모델 런타임 이후, 브리지 이전에 로드한다.
- Modify: `assets/web/runtime_live2d_model.js`
  - `avatarMode`가 `live2d`일 때만 Live2D 모델을 로드하고, 이미지 모드 전환 시 Live2D artifacts를 제거한다.
- Modify: `assets/web/runtime_expression.js`
  - `changeExpression()`이 현재 아바타 모드에 따라 Live2D 표정 또는 이미지 감정 전환으로 라우팅되게 한다.
- Modify: `assets/web/runtime_lipsync.js`
  - 이미지 모드에서는 mouth parameter 대신 이미지 바운스에 mouth value를 전달한다.
- Modify: `assets/web/runtime_live2d_parameter_ui.js`
  - 이미지 모드에서 Live2D 파라미터 버튼/패널을 숨긴다.
- Modify: `tests/test_model_emotions.py`
  - 이미지 모드 감정 발견과 prompt 감정 연결 테스트를 추가한다.
- Modify: `tests/test_settings.py`
  - 새 기본 설정값 테스트를 추가한다.
- Modify: `tests/test_chat_ui_assets.py`
  - 웹 런타임 스크립트 순서, 이미지 아바타 함수, 이미지 모드 분기 테스트를 추가한다.
- Modify: `tests/test_ui_i18n_smoke.py`
  - 새 설정 문구와 모델 탭 smoke test를 확장한다.

## Task 1: 이미지 아바타 데이터 계층

**Files:**
- Create: `src/core/image_avatar.py`
- Modify: `src/core/model_emotions.py`
- Modify: `src/ai/prompt_config.py`
- Test: `tests/test_model_emotions.py`
- Test: `tests/test_prompt_config.py`

- [ ] **Step 1: 이미지 폴더 스캔 실패 테스트 작성**

`tests/test_model_emotions.py`에 추가한다.

```python
def test_discover_image_avatar_emotions_reads_supported_image_files(tmp_path):
    from src.core.image_avatar import discover_image_avatar_emotions

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "sad.webp").write_bytes(b"fake")
    (avatar_dir / "joy.png").write_bytes(b"fake")
    (avatar_dir / "normal.png").write_bytes(b"fake")
    (avatar_dir / "ignore.txt").write_text("x", encoding="utf-8-sig")

    emotions = discover_image_avatar_emotions(avatar_dir)

    assert emotions == ["normal", "joy", "sad"]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_model_emotions.py::test_discover_image_avatar_emotions_reads_supported_image_files -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.image_avatar'`

- [ ] **Step 3: 최소 구현 작성**

`src/core/image_avatar.py`를 만들고 다음 책임을 구현한다.

```python
SUPPORTED_IMAGE_AVATAR_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")

def discover_image_avatar_emotions(folder_path: str | Path) -> list[str]:
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return []
    discovered = {
        path.stem.strip().lower()
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_AVATAR_EXTENSIONS and path.stem.strip()
    }
    if "normal" not in discovered:
        return []
    ordered = ["normal"]
    discovered.remove("normal")
    ordered.extend(sorted(discovered))
    return ordered
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_model_emotions.py::test_discover_image_avatar_emotions_reads_supported_image_files -v`

Expected: PASS

- [ ] **Step 5: 확장자 우선순위와 파일 payload 테스트 작성**

`tests/test_model_emotions.py`에 추가한다.

```python
def test_build_image_avatar_payload_prefers_png_and_includes_file_placements(tmp_path):
    from src.core.image_avatar import build_image_avatar_payload

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.webp").write_bytes(b"fake")
    (avatar_dir / "normal.png").write_bytes(b"fake")
    (avatar_dir / "joy.jpg").write_bytes(b"fake")

    payload = build_image_avatar_payload(
        {"image_avatar_folder": "avatar_images/sample", "image_avatar_placements": {
            "avatar_images/sample/joy.jpg": {"scale": 1.2, "x_percent": 55, "y_percent": 45}
        }},
        base_path=tmp_path,
    )

    assert payload["availableEmotions"] == ["normal", "joy"]
    assert payload["images"]["normal"]["path"].endswith("/normal.png")
    assert payload["images"]["joy"]["placement"] == {"scale": 1.2, "xPercent": 55, "yPercent": 45}
```

- [ ] **Step 6: 실패 확인**

Run: `pytest tests/test_model_emotions.py::test_build_image_avatar_payload_prefers_png_and_includes_file_placements -v`

Expected: FAIL with `ImportError` or missing function.

- [ ] **Step 7: 이미지 payload 구현**

`src/core/image_avatar.py`에 다음 API를 추가한다.

- `resolve_image_avatar_folder(settings_source, base_path) -> Path`
- `discover_image_avatar_files(folder_path) -> dict[str, Path]`
- `normalize_image_avatar_placement(value) -> dict`
- `build_image_avatar_payload(settings_source, base_path) -> dict`

Payload 형태는 다음을 따른다.

```python
{
    "folderPath": folder_path.as_uri() if folder_path.exists() else "",
    "availableEmotions": ["normal", "joy"],
    "images": {
        "normal": {
            "path": normal_path.as_uri(),
            "storageKey": "avatar_images/sample/normal.png",
            "placement": {"scale": 1.0, "xPercent": 50, "yPercent": 50},
        },
    },
    "error": "",
}
```

주의:
- `normal` 이미지가 없으면 `availableEmotions`는 `["normal"]`, `images`는 `{}`, `error`는 `"missing_normal"`로 둔다.
- 저장 키는 `/` 구분자를 사용한다.
- 배치값은 `scale` 0.1-2.0, `xPercent` -100-200, `yPercent` -100-200 범위로 정규화한다.

- [ ] **Step 8: 통과 확인**

Run: `pytest tests/test_model_emotions.py::test_build_image_avatar_payload_prefers_png_and_includes_file_placements -v`

Expected: PASS

- [ ] **Step 9: 런타임 감정 분기 테스트 작성**

`tests/test_model_emotions.py`에 추가한다.

```python
def test_runtime_emotions_use_image_avatar_folder_when_image_mode_is_enabled(tmp_path):
    from src.ai.prompt_config import get_runtime_emotions

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")
    (avatar_dir / "joy.png").write_bytes(b"fake")

    emotions = get_runtime_emotions(
        settings_source={"avatar_mode": "image", "image_avatar_folder": "avatar_images/sample"},
        base_path=tmp_path,
    )

    assert emotions == ["normal", "joy"]
```

- [ ] **Step 10: 실패 확인**

Run: `pytest tests/test_model_emotions.py::test_runtime_emotions_use_image_avatar_folder_when_image_mode_is_enabled -v`

Expected: FAIL because current prompt config only uses Live2D model emotions.

- [ ] **Step 11: `model_emotions.py`에 모드별 감정 API 추가**

`src/core/model_emotions.py`에 `get_available_avatar_emotions()`를 추가한다.

```python
def get_available_avatar_emotions(settings_source=None, base_path=None, fallback_emotions=None) -> list[str]:
    source = _resolve_settings_source(settings_source)
    avatar_mode = str(source.get("avatar_mode", "live2d") or "live2d").strip().lower()
    if avatar_mode == "image":
        from .image_avatar import get_available_image_avatar_emotions

        discovered = get_available_image_avatar_emotions(source, base_path=base_path)
        if discovered:
            return discovered
        return _normalize_fallback_emotions(fallback_emotions)
    return get_available_model_emotions(source, base_path=base_path, fallback_emotions=fallback_emotions)
```

`src/ai/prompt_config.py`의 import와 `get_runtime_emotions()`를 `get_available_avatar_emotions()`로 교체한다.

- [ ] **Step 12: 통과 확인**

Run: `pytest tests/test_model_emotions.py::test_runtime_emotions_use_image_avatar_folder_when_image_mode_is_enabled -v`

Expected: PASS

- [ ] **Step 13: 관련 회귀 테스트 실행**

Run: `pytest tests/test_model_emotions.py tests/test_prompt_config.py -v`

Expected: PASS

- [ ] **Step 14: 커밋**

```bash
git add src/core/image_avatar.py src/core/model_emotions.py src/ai/prompt_config.py tests/test_model_emotions.py tests/test_prompt_config.py
git commit -m "feat: discover image avatar emotions"
```

## Task 2: 설정 기본값과 오버레이 payload

**Files:**
- Modify: `src/core/settings.py`
- Modify: `src/core/overlay_window.py`
- Test: `tests/test_settings.py`
- Test: `tests/test_model_emotions.py`

- [ ] **Step 1: 기본 설정 테스트 작성**

`tests/test_settings.py`에 추가한다.

```python
def test_image_avatar_defaults_are_present():
    from src.core.settings import Settings

    assert Settings.DEFAULT_CONFIG["avatar_mode"] == "live2d"
    assert Settings.DEFAULT_CONFIG["image_avatar_folder"] == ""
    assert Settings.DEFAULT_CONFIG["image_avatar_placements"] == {}
    assert Settings.DEFAULT_CONFIG["image_avatar_preview_emotion"] == "normal"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_settings.py::test_image_avatar_defaults_are_present -v`

Expected: FAIL with `KeyError`.

- [ ] **Step 3: 기본 설정 추가**

`src/core/settings.py`의 `DEFAULT_CONFIG`에 추가한다.

```python
"avatar_mode": "live2d",
"image_avatar_folder": "",
"image_avatar_placements": {},
"image_avatar_preview_emotion": "normal",
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_settings.py::test_image_avatar_defaults_are_present -v`

Expected: PASS

- [ ] **Step 5: 오버레이 payload 테스트 작성**

`tests/test_model_emotions.py`에 추가한다.

```python
def test_overlay_window_model_payload_includes_image_avatar_payload(tmp_path):
    from src.core.overlay_window import OverlayWindow

    avatar_dir = tmp_path / "avatar_images" / "sample"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "normal.png").write_bytes(b"fake")

    window = OverlayWindow.__new__(OverlayWindow)
    window.settings = type("DummySettings", (), {"config": {}})()
    window._get_base_path = lambda: tmp_path

    payload = OverlayWindow._resolve_model_path_payload(
        window,
        {"avatar_mode": "image", "image_avatar_folder": "avatar_images/sample"},
    )

    assert payload["avatarMode"] == "image"
    assert payload["imageAvatar"]["availableEmotions"] == ["normal"]
    assert payload["availableEmotions"] == ["normal"]
```

- [ ] **Step 6: 실패 확인**

Run: `pytest tests/test_model_emotions.py::test_overlay_window_model_payload_includes_image_avatar_payload -v`

Expected: FAIL because payload lacks image avatar fields.

- [ ] **Step 7: `overlay_window.py` payload 확장**

`src/core/overlay_window.py`에서 `build_image_avatar_payload`와 `get_available_avatar_emotions`를 사용한다.

`_resolve_model_path_payload()` 반환값에 다음 키를 추가한다.

```python
"avatarMode": avatar_mode,
"imageAvatar": image_payload,
"availableEmotions": available_emotions,
```

Live2D 모드에서도 `imageAvatar`는 빈 payload를 내려준다. `availableEmotions`는 현재 모드 기준 감정이어야 한다.

- [ ] **Step 8: `_apply_model_settings()`와 `preview_settings()` JS payload 확장**

두 JS payload 모두 다음 필드를 포함한다.

```javascript
avatarMode: "...",
imageAvatar: {...},
```

중복 문자열 조립이 커지면 `_build_model_config_js_payload(source)` 같은 작은 helper를 추가한다.

- [ ] **Step 9: 통과 확인**

Run: `pytest tests/test_model_emotions.py::test_overlay_window_model_payload_includes_image_avatar_payload -v`

Expected: PASS

- [ ] **Step 10: 관련 회귀 테스트 실행**

Run: `pytest tests/test_settings.py tests/test_model_emotions.py -v`

Expected: PASS

- [ ] **Step 11: 커밋**

```bash
git add src/core/settings.py src/core/overlay_window.py tests/test_settings.py tests/test_model_emotions.py
git commit -m "feat: send image avatar payload to overlay"
```

## Task 3: 웹 런타임 이미지 아바타 렌더러

**Files:**
- Create: `assets/web/runtime_image_avatar.js`
- Modify: `assets/web/index.html`
- Modify: `assets/web/runtime_live2d_model.js`
- Modify: `assets/web/runtime_expression.js`
- Modify: `assets/web/runtime_lipsync.js`
- Modify: `assets/web/runtime_live2d_parameter_ui.js`
- Modify: `tests/test_chat_ui_assets.py`

- [ ] **Step 1: 스크립트 순서 테스트 수정**

`tests/test_chat_ui_assets.py`의 `EXPECTED_RUNTIME_SCRIPTS`에서 `runtime_live2d_model.js` 뒤와 `runtime_motion_state.js` 앞에 `runtime_image_avatar.js`를 추가한다.

Expected order:

```python
"runtime_bootstrap.js",
"runtime_live2d_model.js",
"runtime_image_avatar.js",
"runtime_motion_state.js",
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_web_runtime_is_split_into_ordered_scripts -v`

Expected: FAIL because HTML does not load `runtime_image_avatar.js`.

- [ ] **Step 3: HTML 스크립트 추가**

`assets/web/index.html`에 추가한다.

```html
<script src="runtime_image_avatar.js"></script>
```

- [ ] **Step 4: 빈 런타임 파일 생성 후 통과 확인**

Create `assets/web/runtime_image_avatar.js` with a short header and no behavior.

Run: `pytest tests/test_chat_ui_assets.py::test_web_runtime_is_split_into_ordered_scripts -v`

Expected: PASS

- [ ] **Step 5: 이미지 아바타 API 존재 테스트 작성**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_image_avatar_runtime_exposes_mode_hooks():
    script = _script_text()

    assert "const imageAvatarState = {" in script
    assert "function isImageAvatarMode()" in script
    assert "function applyImageAvatarSettings(config)" in script
    assert "function changeImageAvatarEmotion(emotion)" in script
    assert "function applyImageAvatarMouthValue(value)" in script
    assert "window.applyImageAvatarSettings = applyImageAvatarSettings;" in script
```

- [ ] **Step 6: 실패 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_image_avatar_runtime_exposes_mode_hooks -v`

Expected: FAIL with missing strings.

- [ ] **Step 7: 이미지 렌더러 최소 구현**

`assets/web/runtime_image_avatar.js`에 다음 책임을 구현한다.

- `imageAvatarState`: sprite, currentEmotion, currentPlacement, mouthValue, errorText
- `isImageAvatarMode()`: `window.eneModelConfig.avatarMode === 'image'`
- `getImageAvatarImageForEmotion(emotion)`: 없으면 `normal`
- `applyImageAvatarPlacement()`: `scale`, `xPercent`, `yPercent`, mouth bounce 적용
- `changeImageAvatarEmotion(emotion)`: 이미지 texture 교체
- `applyImageAvatarMouthValue(value)`: mouth value를 Y 오프셋으로 변환
- `removeImageAvatarArtifacts()`: sprite/error 정리

바운스는 과하지 않게 시작한다.

```javascript
const IMAGE_AVATAR_TTS_BOUNCE_PX = 10;
const bounceOffset = -Math.max(0, Math.min(1, imageAvatarState.mouthValue)) * IMAGE_AVATAR_TTS_BOUNCE_PX;
```

- [ ] **Step 8: 통과 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_image_avatar_runtime_exposes_mode_hooks -v`

Expected: PASS

- [ ] **Step 9: Live2D 로더 모드 분기 테스트 작성**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_live2d_loader_skips_model_when_image_avatar_mode_is_active():
    script = _script_text()

    assert "if (isImageAvatarMode())" in script
    assert "removeCurrentModelArtifacts();" in script
    assert "applyImageAvatarSettings(window.eneModelConfig);" in script
```

- [ ] **Step 10: 실패 확인**

Run: `pytest tests/test_chat_ui_assets.py::test_live2d_loader_skips_model_when_image_avatar_mode_is_active -v`

Expected: FAIL.

- [ ] **Step 11: `runtime_live2d_model.js` 분기 구현**

`window.applyENEModelSettings`와 `loadModel()` 시작부에서 이미지 모드면:

```javascript
removeCurrentModelArtifacts();
applyImageAvatarSettings(window.eneModelConfig);
return;
```

Live2D 모드로 돌아가면:

```javascript
removeImageAvatarArtifacts();
```

- [ ] **Step 12: 감정 전환 라우팅 테스트 작성**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_expression_change_routes_to_image_avatar_in_image_mode():
    script = _script_text()

    assert "if (isImageAvatarMode())" in script
    assert "changeImageAvatarEmotion(emotion);" in script
```

- [ ] **Step 13: `runtime_expression.js` 라우팅 구현**

`changeExpression()` 시작부에 이미지 모드 분기를 추가한다.

```javascript
if (isImageAvatarMode()) {
    changeImageAvatarEmotion(emotion);
    return;
}
```

- [ ] **Step 14: 립싱크 라우팅 테스트 작성**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_lipsync_routes_mouth_value_to_image_avatar_bounce():
    script = _script_text()

    assert "if (isImageAvatarMode())" in script
    assert "applyImageAvatarMouthValue(value);" in script
```

- [ ] **Step 15: `runtime_lipsync.js` 라우팅 구현**

`setMouthOpen(value)` 시작부에 이미지 모드 분기를 추가한다.

```javascript
if (isImageAvatarMode()) {
    applyImageAvatarMouthValue(value);
    return;
}
```

- [ ] **Step 16: 이미지 모드에서 Live2D 파라미터 UI 숨김 테스트 작성**

`tests/test_chat_ui_assets.py`에 추가한다.

```python
def test_live2d_parameter_button_hides_in_image_avatar_mode():
    script = _script_text()

    assert "function syncLive2DParameterVisibilityForAvatarMode()" in script
    assert "live2dParametersButton.style.display = isImageAvatarMode() ? 'none' : 'inline-flex';" in script
```

- [ ] **Step 17: `runtime_live2d_parameter_ui.js` 숨김 구현**

`window.onLive2DParameterModelChanged` 또는 설정 적용 시점에서 호출할 수 있는 helper를 추가한다.

```javascript
function syncLive2DParameterVisibilityForAvatarMode() {
    const live2dParametersButton = getLive2DParameterElement('live2d-parameters-floating-btn');
    if (live2dParametersButton) {
        live2dParametersButton.style.display = isImageAvatarMode() ? 'none' : 'inline-flex';
    }
    if (isImageAvatarMode()) {
        setLive2DParameterPanelOpen(false);
    }
}
```

- [ ] **Step 18: 웹 asset 테스트 실행**

Run: `pytest tests/test_chat_ui_assets.py -v`

Expected: PASS

- [ ] **Step 19: 커밋**

```bash
git add assets/web/index.html assets/web/runtime_image_avatar.js assets/web/runtime_live2d_model.js assets/web/runtime_expression.js assets/web/runtime_lipsync.js assets/web/runtime_live2d_parameter_ui.js tests/test_chat_ui_assets.py
git commit -m "feat: render image avatar mode"
```

## Task 4: 설정 UI와 이미지별 배치 저장

**Files:**
- Modify: `src/ui/settings_tabs/model_tab.py`
- Modify: `src/ui/settings_dialog_values.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Test: `tests/test_ui_i18n_smoke.py`
- Test: `tests/test_prompt_config.py`

- [ ] **Step 1: UI smoke 테스트 작성**

`tests/test_ui_i18n_smoke.py`에 모델 탭에서 다음 위젯이 존재하는지 확인하는 테스트를 추가한다.

```python
def test_model_tab_exposes_image_avatar_controls(qtbot):
    dialog = _build_settings_dialog(qtbot)

    assert hasattr(dialog, "avatar_mode_combo")
    assert hasattr(dialog, "image_avatar_folder_edit")
    assert hasattr(dialog, "image_avatar_emotion_list")
    assert hasattr(dialog, "image_avatar_scale_spin")
    assert hasattr(dialog, "image_avatar_x_slider")
    assert hasattr(dialog, "image_avatar_y_slider")
```

프로젝트의 기존 helper 이름이 다르면 기존 `SettingsDialog` 생성 패턴을 따른다.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_ui_i18n_smoke.py::test_model_tab_exposes_image_avatar_controls -v`

Expected: FAIL because widgets do not exist.

- [ ] **Step 3: 모델 탭 UI 추가**

`src/ui/settings_tabs/model_tab.py`에 추가한다.

- `avatar_mode_combo`: `Live2D`, `이미지`
- `image_avatar_folder_edit` + 찾아보기 버튼
- `image_avatar_emotion_list`
- `image_avatar_scale_spin` + slider
- `image_avatar_x_slider`, `image_avatar_y_slider`

주의:
- 기존 Live2D 모델 파일 group은 Live2D 모드에서만 보이게 한다.
- 이미지 조절 group은 이미지 모드에서만 보이게 한다.
- 이미지별 조절 UI의 범위는 Live2D와 동일하게 `scale 0.1-2.0`, `x/y -100~200`을 사용한다.

- [ ] **Step 4: 값 로드/저장 테스트 작성**

`tests/test_prompt_config.py` 또는 더 알맞은 설정 다이얼로그 테스트에 추가한다.

```python
def test_settings_dialog_collects_image_avatar_values(qtbot, tmp_path):
    dialog = _build_settings_dialog(qtbot)
    dialog.avatar_mode_combo.setCurrentIndex(dialog.avatar_mode_combo.findData("image"))
    dialog.image_avatar_folder_edit.setText(str(tmp_path / "avatar_images" / "sample"))
    dialog._selected_image_avatar_storage_key = "avatar_images/sample/joy.png"
    dialog._image_avatar_placements = {
        "avatar_images/sample/joy.png": {"scale": 1.2, "x_percent": 55, "y_percent": 45}
    }

    values = dialog._get_current_values()

    assert values["avatar_mode"] == "image"
    assert values["image_avatar_placements"]["avatar_images/sample/joy.png"]["scale"] == 1.2
```

기존 테스트 helper가 없다면 `tests/test_ui_i18n_smoke.py` 안의 기존 다이얼로그 생성 방식을 재사용한다.

- [ ] **Step 5: 실패 확인**

Run the new test with `pytest ... -v`

Expected: FAIL.

- [ ] **Step 6: `settings_dialog_values.py`에 이미지 UI 로직 추가**

추가할 helper:

- `_browse_image_avatar_folder()`
- `_refresh_image_avatar_emotion_list()`
- `_on_image_avatar_emotion_selected()`
- `_read_selected_image_avatar_placement()`
- `_write_selected_image_avatar_placement()`
- `_sync_avatar_mode_visibility()`

중요 계약:
- 리스트 선택을 바꾸기 전 현재 선택 이미지의 배치값을 `_image_avatar_placements`에 저장한다.
- `_get_current_values()`는 `image_avatar_placements`를 포함한다.
- `_preview_settings()`는 선택 이미지 감정을 `image_avatar_preview_emotion`으로 포함해 오버레이가 바로 해당 이미지를 보여주게 한다.

- [ ] **Step 7: 다국어 문자열 추가**

`src/locales/ko.json`, `en.json`, `ja.json`에 다음 키를 추가한다.

```json
"settings.model.avatar_mode.title": "...",
"settings.model.avatar_mode.live2d": "...",
"settings.model.avatar_mode.image": "...",
"settings.model.image.path.title": "...",
"settings.model.image.path.hint": "...",
"settings.model.image.path.dialog.title": "...",
"settings.model.image.emotions.title": "...",
"settings.model.image.placement.title": "..."
```

- [ ] **Step 8: 통과 확인**

Run: `pytest tests/test_ui_i18n_smoke.py tests/test_prompt_config.py -v`

Expected: PASS

- [ ] **Step 9: 커밋**

```bash
git add src/ui/settings_tabs/model_tab.py src/ui/settings_dialog_values.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_ui_i18n_smoke.py tests/test_prompt_config.py
git commit -m "feat: add image avatar settings UI"
```

## Task 5: 통합 검증과 문서 마무리

**Files:**
- Modify: `README.ko.md`
- Modify: `README.md`
- Modify: `README.ja.md`
- Optional Modify: `TESTING.md`

- [ ] **Step 1: 사용자 문서 업데이트**

README 3종에 이미지 모드 사용법을 짧게 추가한다.

```text
이미지 아바타 모드:
1. 캐릭터 폴더를 만든다.
2. normal.png를 넣는다.
3. joy.png, sad.png 같은 감정 이미지를 선택적으로 넣는다.
4. 설정 > 모델에서 이미지 모드를 선택하고 각 이미지를 조절한다.
```

실제 사용자 대화나 개인정보 예시는 넣지 않는다.

- [ ] **Step 2: 개인정보 후보 스캔**

Run:

```bash
rg -n "(api[_-]?key|sk-[A-Za-z0-9]|AIza|생일|건강|일정|취업|프로필|실제 대화|memory\\.json|user_profile\\.json|config\\.json|api_keys\\.json|api_key\\.txt|\\.env)" README.md README.ko.md README.ja.md src tests assets/web
```

Expected: 새로 추가한 문서/테스트에 실제 개인정보나 비밀값 없음.

- [ ] **Step 3: 전체 관련 테스트 실행**

Run:

```bash
pytest tests/test_model_emotions.py tests/test_prompt_config.py tests/test_settings.py tests/test_chat_ui_assets.py tests/test_ui_i18n_smoke.py -v
```

Expected: PASS

- [ ] **Step 4: 가능한 경우 앱 smoke 실행**

Run:

```bash
python main.py
```

수동 확인:
- Live2D 모드는 기존처럼 로드된다.
- 이미지 모드에서 `normal.png`가 표시된다.
- 감정 이미지 목록에서 `joy.png`를 선택해 위치/크기를 조절할 수 있다.
- 채팅 응답 감정이 `joy`일 때 `joy.png`가 표시된다.
- TTS 중 이미지가 위아래로 움직인다.
- 이미지 모드에서 Live2D 파라미터 버튼이 보이지 않는다.

- [ ] **Step 5: 커밋**

```bash
git add README.md README.ko.md README.ja.md TESTING.md
git commit -m "docs: document image avatar mode"
```

## 최종 검증

- [ ] `git status --short`가 깨끗한지 확인한다.
- [ ] `pytest tests/test_model_emotions.py tests/test_prompt_config.py tests/test_settings.py tests/test_chat_ui_assets.py tests/test_ui_i18n_smoke.py -v`가 통과했는지 확인한다.
- [ ] 새 이미지 모드 설정값이 `config.json` 같은 런타임 파일에만 저장되고, 런타임 파일이 커밋되지 않았는지 확인한다.
- [ ] README/테스트/문서에 실제 사용자 대화, 이름, 일정, 프로필, API 키가 들어가지 않았는지 확인한다.

