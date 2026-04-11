# Live2D 기본 Idle 토글 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE 설정에서 Live2D 모델의 기본 제공 `Idle` 모션을 별도로 켜고 끌 수 있게 만든다.

**Architecture:** Python 설정 계층에 `enable_builtin_idle_motion`을 추가하고, 설정 창에서 별도 토글로 노출한다. 오버레이는 새 값을 웹뷰에 동기화하고, 웹 스크립트는 기본 `Idle` 시작과 중지를 전용 helper로 관리해 현재 모델에도 즉시 반영한다.

**Tech Stack:** Python 3.12, PyQt6, QWebEngine, JavaScript, Live2D Web runtime, pytest, UTF-8 with BOM

---

### Task 1: 설정 계약을 테스트로 고정한다

**Files:**
- Modify: `tests/test_settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: 새 기본 설정 키를 검증하는 실패 테스트를 추가한다**

```python
def test_load_missing_file_uses_builtin_idle_default(tmp_path):
    settings = Settings(config_path=str(tmp_path / "config.json"), secret_path=str(tmp_path / "api_keys.json"))
    assert settings.get("enable_builtin_idle_motion") is True
```

- [ ] **Step 2: 저장/재로드 유지 여부를 검증하는 실패 테스트를 추가한다**

```python
def test_save_and_reload_preserves_builtin_idle_toggle(tmp_path):
    settings = Settings(config_path=str(tmp_path / "config.json"), secret_path=str(tmp_path / "api_keys.json"))
    settings.set("enable_builtin_idle_motion", False)
    settings.save()

    reloaded = Settings(config_path=str(tmp_path / "config.json"), secret_path=str(tmp_path / "api_keys.json"))
    assert reloaded.get("enable_builtin_idle_motion") is False
```

- [ ] **Step 3: 테스트를 실행해 실패를 확인한다**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_settings.py -q`
Expected: 새 키가 없어서 실패

- [ ] **Step 4: `src/core/settings.py`에 최소 구현을 추가한다**

- [ ] **Step 5: 테스트를 다시 실행해 통과를 확인한다**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_settings.py -q`
Expected: PASS

### Task 2: 웹 런타임 계약을 테스트로 고정한다

**Files:**
- Modify: `tests/test_chat_ui_assets.py`
- Test: `tests/test_chat_ui_assets.py`

- [ ] **Step 1: 새 JS 런타임 훅과 조건부 Idle 시작을 검증하는 실패 테스트를 추가한다**

```python
def test_chat_script_exposes_builtin_idle_runtime_hook():
    script = _script_text()
    assert "window.setBuiltinIdleMotionEnabled = function" in script
    assert "builtinIdleMotionEnabled" in script


def test_chat_script_starts_builtin_idle_only_when_enabled():
    script = _script_text()
    assert "if (builtinIdleMotionEnabled)" in script
    assert "model.motion('Idle');" in script
```

- [ ] **Step 2: 현재 모델에 즉시 반영하는 helper 존재를 검증하는 실패 테스트를 추가한다**

```python
def test_chat_script_defines_builtin_idle_start_stop_helpers():
    script = _script_text()
    assert "function startBuiltinIdleMotion(" in script
    assert "function stopBuiltinIdleMotion(" in script
```

- [ ] **Step 3: 테스트를 실행해 실패를 확인한다**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_chat_ui_assets.py -q`
Expected: 새 함수/상태값 부재로 실패

- [ ] **Step 4: `assets/web/script.js`에 최소 구현을 추가한다**

- [ ] **Step 5: 테스트를 다시 실행해 통과를 확인한다**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_chat_ui_assets.py -q`
Expected: PASS

### Task 3: 설정 UI와 동기화 경로를 연결한다

**Files:**
- Modify: `src/ui/settings_dialog.py`
- Modify: `src/core/overlay_window.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`

- [ ] **Step 1: 설정 창 로드/저장 경로에서 새 토글을 다루는 코드를 추가한다**

- [ ] **Step 2: 오버레이 idle 설정 동기화 경로에 새 JS 호출을 추가한다**

- [ ] **Step 3: 다국어 문자열 키를 추가한다**

- [ ] **Step 4: 관련 테스트를 다시 실행해 회귀가 없는지 확인한다**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_settings.py tests/test_chat_ui_assets.py -q`
Expected: PASS

### Task 4: 최종 검증

**Files:**
- Modify: `docs/superpowers/specs/2026-04-11-live2d-builtin-idle-toggle-design.md`
- Modify: `docs/superpowers/plans/2026-04-11-live2d-builtin-idle-toggle.md`

- [ ] **Step 1: 변경 파일 인코딩이 UTF-8 with BOM인지 확인한다**

Run: `.\venv\Scripts\python.exe - <<'PY' ... PY`
Expected: 모든 변경 파일이 BOM 포함

- [ ] **Step 2: 대상 테스트를 한 번 더 실행한다**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_settings.py tests/test_chat_ui_assets.py -q`
Expected: PASS

- [ ] **Step 3: 수동 확인 포인트를 기록한다**

수동 확인:
- 설정 창에서 `Live2D 기본 idle 모션 활성화`를 끄면 현재 모델 기본 모션이 즉시 멈추는지
- 다시 켜면 현재 모델 기본 모션이 즉시 재시작되는지
- 기존 `유휴 모션 활성화`는 ENE 커스텀 idle만 계속 제어하는지
