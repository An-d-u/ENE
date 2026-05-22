# ENE 목표 시스템 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE가 대화 중 자신의 단기/장기 목표를 생성, 저장, 완료 처리하고 사용자가 UI에서 확인/수정할 수 있게 만든다.

**Architecture:** 최종 응답 형식 계약은 `response_contract.py` 한 곳에서 조립하고, 목표 규칙은 `goal_prompt.py`, 생각 규칙은 `thought_prompt.py`로 분리한다. LLM 응답의 `[ene_goal_update]`는 공통 파서가 제거/구조화하고, `EneGoalManager`가 검증 후 `ene_goals.json`에 반영한다. `WebBridge`는 목표 매니저와 UI 사이의 얇은 연결 계층만 맡는다.

**Tech Stack:** Python 3, PyQt6, 기존 ENE WebBridge/QWebChannel, vanilla JS/CSS, pytest.

---

## Scope Check

이 스펙은 프롬프트, 파서, 상태 매니저, 브리지, 채팅 UI, 설정 UI를 모두 건드리지만 하나의 기능을 완성하기 위한 세로 조각이다. V1은 목표 승인 UI, hard delete, 히스토리 컨텍스트 포함, 별도 목표 판단 LLM 호출을 제외하므로 하나의 구현 계획으로 진행한다.

## File Structure

- Create `src/ai/response_contract.py`
  - 런타임 최종 응답 형식 계약을 단일 조립한다.
  - `analysis`, `ene_goal_update`, `subconscious`, `tts` 블록 포함 여부와 순서를 관리한다.
- Modify `src/ai/thought_prompt.py`
  - 생각 기능 활성 여부와 `subconscious` 규칙만 담당한다.
  - 기존 외부 호출 호환을 위해 `build_thought_system_appendix()` 래퍼는 당분간 유지한다.
- Create `src/ai/goal_prompt.py`
  - 목표 기능 활성 여부, 목표 출력 규칙, 장기/단기 구분 지침을 제공한다.
- Modify `src/ai/prompt.py`
  - `build_response_contract_appendix()`를 사용하도록 변경한다.
- Modify `src/ai/response_cleanup.py`
  - `[ene_goal_update]` 추출/제거 유틸리티를 추가한다.
- Modify `src/ai/llm_client.py`
  - Gemini 계열 응답 파싱 반환값에 goal update dict를 추가한다.
  - LLM 컨텍스트에 활성 목표 블록을 포함한다.
- Modify `src/ai/http_llm_clients.py`
  - HTTP 계열 응답 파싱 반환값에 goal update dict를 추가한다.
  - LLM 컨텍스트에 활성 목표 블록을 포함한다.
- Create `src/ai/ene_goal_manager.py`
  - `ene_goals.json` 로드/저장, 목표 검증, 활성/히스토리 전환, 수동 편집 API를 제공한다.
- Modify `src/core/settings.py`
  - 목표 기능 기본 설정을 추가한다.
- Modify `src/core/app.py`
  - `EneGoalManager`를 초기화하고 LLM 클라이언트/브리지에 연결한다.
- Modify `src/core/bridge.py`
  - 목표 매니저 연결, 응답 목표 업데이트 반영, 목표 UI용 시그널/슬롯을 제공한다.
- Modify `src/core/overlay_window.py`
  - 목표 버튼 표시 설정과 목표 UI 문자열을 JS로 동기화한다.
- Modify `assets/web/index.html`
  - 목표 버튼과 현재 목표 패널 DOM을 추가한다.
- Modify `assets/web/script.js`
  - 목표 버튼 표시/패널 렌더링/브리지 호출을 추가한다.
- Modify `assets/web/style.css`
  - 목표 버튼과 목표 패널 스타일을 추가한다.
- Modify `src/ui/settings_dialog.py`
  - 목표 기능/버튼 토글과 수동 목표 편집 패널을 추가한다.
- Modify `src/locales/ko.json`, `src/locales/en.json`, `src/locales/ja.json`
  - 목표 UI와 설정 문구를 추가한다.
- Tests:
  - Create `tests/test_response_contract.py`
  - Create `tests/test_goal_update_parsing.py`
  - Create `tests/test_ene_goal_manager.py`
  - Create `tests/test_bridge_goals.py`
  - Modify `tests/test_prompt_config.py`
  - Modify `tests/test_settings.py`
  - Modify existing LLM parser tests if return tuple assumptions break.

## Implementation Tasks

### Task 1: Response Contract Split

**Files:**
- Create: `src/ai/response_contract.py`
- Create: `src/ai/goal_prompt.py`
- Modify: `src/ai/thought_prompt.py`
- Modify: `src/ai/prompt.py`
- Create: `tests/test_response_contract.py`
- Modify: `tests/test_prompt_config.py`

- [ ] **Step 1: Write failing tests for contract combinations**

Add tests that assert:

```python
from src.ai.response_contract import build_response_contract_appendix


def test_response_contract_includes_goals_and_thoughts_when_enabled():
    text = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": True, "enable_ene_thoughts": True}
    )
    assert "[ene_goal_update]" in text
    assert "create" in text
    assert "update" in text
    assert "complete" in text
    assert "cancel" in text
    assert "[subconscious]" in text
    assert "[analysis]" in text


def test_response_contract_omits_disabled_blocks():
    text = build_response_contract_appendix(
        {"ui_language": "ko", "enable_ene_goals": False, "enable_ene_thoughts": False}
    )
    assert "[ene_goal_update]" not in text
    assert "[subconscious]" not in text
    assert "[analysis]" in text
```

Also update the existing thought prompt test name in `tests/test_prompt_config.py` so it checks “runtime response contract” rather than “thought rules”.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_response_contract.py tests/test_prompt_config.py -q
```

Expected: FAIL because `src.ai.response_contract` does not exist yet.

- [ ] **Step 3: Implement `goal_prompt.py`**

Implement small functions:

```python
def is_goal_prompt_enabled(settings_source: object | None = None) -> bool:
    return bool(_read_setting(settings_source, "enable_ene_goals", True))


def build_goal_update_rules(language: str = "ko") -> list[str]:
    return [
        "- 목표 기능이 켜져 있으면 매 응답마다 `[ene_goal_update]...[/ene_goal_update]` 블록을 출력하세요.",
        "- 변화가 없으면 `action=none`을 출력하세요.",
        "- `short_term`은 현재 대화에서 몇 턴 안에 달성될 수 있는 행동 목표입니다.",
        "- `long_term`은 ENE의 캐릭터성, 관계성, 반복 행동 방향을 위한 지속 목표입니다.",
        "- 헷갈리면 `short_term`을 선택하고, `long_term`은 반복 신호가 있을 때만 보수적으로 만드세요.",
    ]
```

Use the same `_read_setting` behavior as `prompt_language.py` or share a local helper.

- [ ] **Step 4: Refactor `thought_prompt.py`**

Keep:

```python
is_thought_prompt_enabled(settings_source)
build_thought_rules(language="ko")
```

Move `_RESPONSE_CONTRACT_BY_LANGUAGE` and `_build_format_block()` out. Add a compatibility wrapper:

```python
def build_thought_system_appendix(settings_source: object | None = None) -> str:
    from .response_contract import build_response_contract_appendix

    return build_response_contract_appendix(settings_source=settings_source)
```

This prevents older imports from crashing during transition.

- [ ] **Step 5: Implement `response_contract.py`**

Build the final block order:

```text
[analysis]
...
[/analysis]

[ene_goal_update]
...
[/ene_goal_update]

[subconscious]
...
[/subconscious]

한국어 답변 [emotion]
```

Rules:

- Always mention `[analysis]`.
- Include `[ene_goal_update]` only when `enable_ene_goals` is true.
- Include `[subconscious]` only when `enable_ene_thoughts` is true.
- Include `[tts]` only when `resolve_tts_language(...) != resolve_prompt_language(...)`.
- Append `build_goal_update_rules()` and `build_thought_rules()` only when their feature is enabled.

- [ ] **Step 6: Update `prompt.py`**

Replace:

```python
from .thought_prompt import build_thought_system_appendix
```

with:

```python
from .response_contract import build_response_contract_appendix
```

Then call `build_response_contract_appendix(settings_source=settings_source)`.

- [ ] **Step 7: Run tests**

Run:

```powershell
pytest tests/test_response_contract.py tests/test_prompt_config.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add src/ai/response_contract.py src/ai/goal_prompt.py src/ai/thought_prompt.py src/ai/prompt.py tests/test_response_contract.py tests/test_prompt_config.py
git commit -m "refactor: split response contract prompt"
```

### Task 2: Goal Update Parser

**Files:**
- Modify: `src/ai/response_cleanup.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_clients.py`
- Create: `tests/test_goal_update_parsing.py`

- [ ] **Step 1: Write failing parser tests**

Test the common extractor:

```python
from src.ai.response_cleanup import extract_goal_update_metadata


def test_extract_goal_update_metadata_removes_block_and_parses_keys():
    text = """[analysis]
user_intent=seek_comfort
[/analysis]

[ene_goal_update]
action=create
type=short_term
id=
title=마스터가 안정될 때까지 위로하기
reason=사용자가 우울해 보임
completion_reason=
[/ene_goal_update]

괜찮아요. 제가 여기 있을게요. [smile]"""

    cleaned, update = extract_goal_update_metadata(text)

    assert "[ene_goal_update]" not in cleaned
    assert update["action"] == "create"
    assert update["type"] == "short_term"
    assert update["title"] == "마스터가 안정될 때까지 위로하기"
```

Also test `action=none` with empty fields.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_goal_update_parsing.py -q
```

Expected: FAIL because `extract_goal_update_metadata` does not exist.

- [ ] **Step 3: Implement `extract_goal_update_metadata()`**

Add to `response_cleanup.py`:

```python
GOAL_UPDATE_KEYS = ("action", "type", "id", "title", "reason", "completion_reason")
```

Parser behavior:

- Find first `[ene_goal_update]...[/ene_goal_update]` block case-insensitively.
- Remove all such blocks from visible text.
- Parse only `key=value` lines for allowed keys.
- Return `(cleaned_text, parsed_dict)`.
- Return `(source, {})` if no block exists.

- [ ] **Step 4: Add LLM parser integration tests**

In `tests/test_goal_update_parsing.py`, instantiate parser methods without network:

```python
from src.ai.llm_client import GeminiClient


def test_gemini_parse_response_returns_goal_update():
    client = object.__new__(GeminiClient)
    client.settings = {"ui_language": "ko"}
    text, emotion, tts, events, analysis, promises, thought, goal_update = GeminiClient._parse_response(
        client,
        "[ene_goal_update]\naction=none\n[/ene_goal_update]\n좋아요. [smile]",
    )
    assert text == "좋아요."
    assert emotion == "smile"
    assert goal_update["action"] == "none"
```

- [ ] **Step 5: Update `_parse_response()` return tuples**

In both `llm_client.py` and `http_llm_clients.py`:

- Import `extract_goal_update_metadata`.
- Parse after analysis and before thought:

```python
response_text, goal_update = self._extract_goal_update_block(response_text)
response_text, thought = self._extract_thought_block(response_text)
```

- Return 8 values:

```python
return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update
```

Add `_extract_goal_update_block()` wrappers matching existing `_extract_thought_block()`.

- [ ] **Step 6: Update method type hints and docstrings**

Update public async methods that call `_parse_response()` so their return tuple hints mention the added `dict` at the end. Do not change behavior of note/diary raw document generation.

- [ ] **Step 7: Run focused tests**

Run:

```powershell
pytest tests/test_goal_update_parsing.py tests/test_http_llm_clients_provider_parity.py tests/test_llm_provider.py -q
```

Expected: PASS or only unrelated pre-existing failures. Fix tuple unpacking failures in touched tests immediately.

- [ ] **Step 8: Commit**

```powershell
git add src/ai/response_cleanup.py src/ai/llm_client.py src/ai/http_llm_clients.py tests/test_goal_update_parsing.py
git commit -m "feat: parse ENE goal update metadata"
```

### Task 3: EneGoalManager

**Files:**
- Create: `src/ai/ene_goal_manager.py`
- Create: `tests/test_ene_goal_manager.py`

- [ ] **Step 1: Write failing manager tests**

Cover:

```python
from src.ai.ene_goal_manager import EneGoalManager


def test_apply_create_and_complete_moves_goal_to_history(tmp_path, monkeypatch):
    monkeypatch.setenv("ENE_USER_DATA_DIR", str(tmp_path))
    manager = EneGoalManager(state_file="ene_goals.json", settings={"enable_ene_goals": True})

    created = manager.apply_llm_update({
        "action": "create",
        "type": "short_term",
        "title": "마스터가 안정될 때까지 위로하기",
        "reason": "사용자가 우울해 보임",
    })
    goal_id = created["active"]["short_term"][0]["id"]

    snapshot = manager.apply_llm_update({
        "action": "complete",
        "id": goal_id,
        "completion_reason": "사용자가 안정됨",
    })

    assert snapshot["active"]["short_term"] == []
    assert snapshot["history"][0]["status"] == "completed"
```

Also test:

- `action=none` changes nothing.
- `action=update` with an existing `id` updates `title` and/or `reason`, refreshes `updated_at`, and keeps the goal active.
- `action=update` with a missing `id` or no editable fields returns an unchanged snapshot.
- duplicate same normalized title does not create another active goal.
- `cancel` moves to history with `status=cancelled`.
- disabled settings ignore updates.
- `build_context_block()` includes `id`, `type`, `title`, `reason`.
- corrupted `ene_goals.json` falls back to the default structure and does not crash manager initialization.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_ene_goal_manager.py -q
```

Expected: FAIL because `EneGoalManager` does not exist.

- [ ] **Step 3: Implement state loading and defaults**

Use existing path utilities:

```python
from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data
```

Default structure:

```python
{
    "version": 1,
    "active": {"long_term": [], "short_term": []},
    "history": [],
}
```

Read `ene_goal_state_file` from settings when no explicit `state_file` is passed.

Wrap load failures. If `load_json_data()` raises because the file is missing, malformed, or not a dict, log a short `[Goals] 상태 로드 실패: ...` message when a file existed and use the default structure. Manager construction must not raise for a corrupted JSON file.

- [ ] **Step 4: Implement validation helpers**

Rules:

- Allowed actions: `none`, `create`, `update`, `complete`, `cancel`.
- Allowed types: `short_term`, `long_term`.
- `title` max 120 chars.
- `reason` and `completion_reason` max 300 chars.
- `action=none` bypasses other field validation.
- Unknown action or missing required fields returns unchanged snapshot.

- [ ] **Step 5: Implement goal lifecycle**

Implement:

```python
apply_llm_update(update: dict) -> dict
add_manual_goal(goal_type: str, title: str, reason: str = "") -> dict
update_goal(goal_id: str, fields: dict) -> dict
complete_goal(goal_id: str, reason: str = "") -> dict
cancel_goal(goal_id: str, reason: str = "") -> dict
```

Use `source="llm"` for LLM updates and `source="manual"` for manual adds.

`apply_llm_update({"action": "update", ...})` must find the active goal by `id`, apply only provided `title` and `reason`, trim them to the configured limits, refresh `updated_at`, set `source` to the existing goal source, save, and return the fresh snapshot. It must not move the goal to history.

- [ ] **Step 6: Implement duplicate detection**

Normalize by:

- strip
- collapse whitespace
- lower
- remove common punctuation `.,!?;:，。！？、`

Only same `type` + same normalized `title` counts as duplicate.

- [ ] **Step 7: Implement context and snapshot**

`get_snapshot()` returns a JSON-serializable dict with active and history. `build_context_block()` returns empty string if disabled or no active goals.

Korean context format:

```text
[ENE 현재 목표]
- id=goal_...
  type=short_term
  title=...
  reason=...
[/ENE 현재 목표]
```

- [ ] **Step 8: Run manager tests**

Run:

```powershell
pytest tests/test_ene_goal_manager.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add src/ai/ene_goal_manager.py tests/test_ene_goal_manager.py
git commit -m "feat: add ENE goal manager"
```

### Task 4: LLM Context and App Wiring

**Files:**
- Modify: `src/core/settings.py`
- Modify: `src/core/app.py`
- Modify: `src/core/bridge.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_clients.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `tests/test_settings.py`
- Create or Modify: LLM context tests in `tests/test_bridge_context_compaction.py` or `tests/test_llm_provider.py`

- [ ] **Step 1: Write failing settings test**

Update `tests/test_settings.py`:

```python
assert settings.get("enable_ene_goals") is True
assert settings.get("show_ene_goal_button") is True
assert settings.get("ene_goal_state_file") == "ene_goals.json"
```

- [ ] **Step 2: Write failing context test**

Add a lightweight test that a dummy client with `goal_manager.build_context_block()` includes goal context in the enhanced prompt. Use the same pattern as existing mood context tests if present.

Expected assertion:

```python
assert "[ENE 현재 목표]" in enhanced_prompt
assert "goal_20260522_001" in enhanced_prompt
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
pytest tests/test_settings.py tests/test_llm_provider.py -q
```

Expected: FAIL for missing defaults and/or missing goal manager wiring.

- [ ] **Step 4: Add settings defaults**

In `Settings.DEFAULT_CONFIG` add:

```python
"enable_ene_goals": True,
"show_ene_goal_button": True,
"ene_goal_state_file": "ene_goals.json",
```

- [ ] **Step 5: Update LLM constructors**

Thread `goal_manager=None` through:

- `src/ai/llm_provider.py`
- each concrete client constructor in `src/ai/http_llm_clients.py`
- `GeminiClient.__init__` in `src/ai/llm_client.py`

Store as `self.goal_manager`.

- [ ] **Step 6: Add goal context to prompt assembly**

Where mood context is appended, add:

```python
if self.goal_manager and hasattr(self.goal_manager, "build_context_block"):
    goal_block = self.goal_manager.build_context_block(language=self._prompt_language())
    if goal_block:
        context_parts.append("\n" + goal_block)
```

Keep this next to mood context so ENE state blocks stay grouped.

- [ ] **Step 7: Initialize manager in app**

In `ENEApplication._init_llm_client()`:

- import `EneGoalManager`
- create `_init_goal_manager()` similar to `_init_mood_manager()`
- call it after `_init_mood_manager()`
- pass `goal_manager=self.goal_manager` to `create_llm_client()`

After overlay creation, call `bridge.set_goal_manager(self.goal_manager)` if present.

- [ ] **Step 8: Add bridge setter**

In `WebBridge`:

```python
def set_goal_manager(self, goal_manager):
    self.goal_manager = goal_manager
    if self.llm_client and self.goal_manager:
        self.llm_client.goal_manager = self.goal_manager
    self._emit_goal_items_updated()
```

Update `set_llm_client()` to assign `goal_manager` too.

- [ ] **Step 9: Run focused tests**

Run:

```powershell
pytest tests/test_settings.py tests/test_llm_provider.py tests/test_bridge_context_compaction.py -q
```

Expected: PASS or unrelated pre-existing failures.

- [ ] **Step 10: Commit**

```powershell
git add src/core/settings.py src/core/app.py src/core/bridge.py src/ai/llm_provider.py src/ai/llm_client.py src/ai/http_llm_clients.py tests/test_settings.py tests/test_llm_provider.py tests/test_bridge_context_compaction.py
git commit -m "feat: wire ENE goals into runtime context"
```

### Task 5: Bridge Response Flow

**Files:**
- Modify: `src/core/bridge.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_clients.py`
- Create: `tests/test_bridge_goals.py`
- Modify: existing tests that normalize response tuple length.

- [ ] **Step 1: Write failing bridge tests**

Create a dummy goal manager:

```python
class _DummyGoalManager:
    def __init__(self):
        self.updates = []

    def apply_llm_update(self, update):
        self.updates.append(update)
        return {"active": {"short_term": [], "long_term": []}, "history": []}
```

Test:

```python
def test_on_response_ready_applies_goal_update_after_analysis():
    dummy.goal_manager = _DummyGoalManager()
    WebBridge._on_response_ready(
        dummy,
        "괜찮아요.",
        "smile",
        "",
        [],
        "{}",
        "",
        [],
        "",
        json.dumps({"action": "create", "type": "short_term", "title": "위로하기", "reason": "상태 안정"}),
    )
    assert dummy.goal_manager.updates[0]["action"] == "create"
```

Also test disabled or missing manager does not crash.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_bridge_goals.py tests/test_bridge_mood_flow.py -q
```

Expected: FAIL because `_on_response_ready()` has no goal update parameter.

- [ ] **Step 3: Extend worker signal and normalizer**

In `AIWorker`:

- change `response_ready` signal to include goal update JSON as a final `str`
- update `_normalize_response_payload()`:
  - len 8 returns as-is
  - len 7 treats old 7th value as `thought` and appends `{}`
  - older lengths continue to work
  - every branch must return the new goal-update value, even if it is `{}` for legacy payloads

Emit:

```python
json.dumps(goal_update, ensure_ascii=False)
```

- [ ] **Step 4: Extend `_on_response_ready()`**

Add parameter:

```python
goal_update_payload: str = "",
```

Parse JSON dict and call:

```python
if self.goal_manager and goal_update:
    snapshot = self.goal_manager.apply_llm_update(goal_update)
    self._emit_goal_items_updated(snapshot)
```

Run after mood analysis/emotion updates and before message emission. Do not block visible response on errors.

- [ ] **Step 5: Add goal UI signals and slots**

In `WebBridge` add:

```python
goal_items_updated = pyqtSignal(str)
goal_notice = pyqtSignal(str, str)
```

Slots:

```python
@pyqtSlot()
def request_goal_items(self): ...

@pyqtSlot(str, str, str)
def add_manual_goal(self, goal_type, title, reason): ...

@pyqtSlot(str, str, str)
def update_goal_item(self, goal_id, title, reason): ...

@pyqtSlot(str, str)
def complete_goal_item(self, goal_id, reason): ...

@pyqtSlot(str, str)
def cancel_goal_item(self, goal_id, reason): ...
```

All slots call manager methods then `_emit_goal_items_updated()`.

- [ ] **Step 6: Sanitize leaked goal block**

Update `_sanitize_visible_response_text()` to remove `[ene_goal_update]...[/ene_goal_update]` via `extract_goal_update_metadata()` before emitting.

- [ ] **Step 7: Run bridge tests**

Run:

```powershell
pytest tests/test_bridge_goals.py tests/test_bridge_mood_flow.py tests/test_bridge_context_compaction.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add src/core/bridge.py src/ai/llm_client.py src/ai/http_llm_clients.py tests/test_bridge_goals.py tests/test_bridge_mood_flow.py tests/test_bridge_context_compaction.py
git commit -m "feat: apply ENE goal updates in bridge"
```

### Task 6: Chat Goal Button and Panel

**Files:**
- Modify: `src/core/overlay_window.py`
- Modify: `assets/web/index.html`
- Modify: `assets/web/script.js`
- Modify: `assets/web/style.css`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`

- [ ] **Step 1: Add goal strings to overlay payload**

In `_resolve_ui_strings_payload()`, add:

```python
"goals": {
    "label": i18n.t("chat.goals.label"),
    "empty": i18n.t("chat.goals.empty"),
    "shortTerm": i18n.t("chat.goals.short_term"),
    "longTerm": i18n.t("chat.goals.long_term"),
    "close": i18n.t("chat.goals.close"),
}
```

Also add action label/title under `actions.goal`.

- [ ] **Step 2: Add visibility sync**

In `OverlayWindow` add:

```python
def _sync_goal_button_visibility_to_js(self, settings_override=None):
    enabled = bool(source.get("show_ene_goal_button", True))
    self.web_view.page().runJavaScript(f"window.setGoalButtonEnabled({str(enabled).lower()});")
```

Call it where summary/mood visibility syncs are called.

- [ ] **Step 3: Update locales**

Add Korean, English, Japanese strings for:

- `chat.actions.goals`
- `chat.actions.goals.title`
- `chat.goals.label`
- `chat.goals.empty`
- `chat.goals.short_term`
- `chat.goals.long_term`
- `chat.goals.close`

- [ ] **Step 4: Update HTML**

Add a button near mood/promise:

```html
<button id="goal-toggle-floating-btn" title="목표">목표</button>
```

Add panel:

```html
<div id="goal-status-panel" class="hidden" aria-live="polite">
  <div id="goal-status-header">
    <div id="goal-status-title">목표</div>
    <button id="goal-status-close-btn" type="button" title="닫기" aria-label="닫기">×</button>
  </div>
  <div id="goal-status-list"></div>
</div>
```

- [ ] **Step 5: Update JS state and QWebChannel hooks**

Add:

```javascript
let goalButtonVisibleBySetting = true;
let goalPanelOpen = false;
let eneGoalSnapshot = { active: { short_term: [], long_term: [] }, history: [] };
```

Functions:

- `window.setGoalButtonEnabled(enabled)`
- `window.setGoalItems(value)`
- `renderGoalPanel()`
- `setGoalPanelOpen(open)`

Connect:

```javascript
window.pyBridge.goal_items_updated.connect(function (value) {
    window.setGoalItems(value);
});
window.pyBridge.request_goal_items();
```

- [ ] **Step 6: Update CSS**

Mirror `#promise-reminders-panel` and `#mood-status-widget` style, but keep the panel compact. Add stable max-height and overflow for long titles/reasons.

- [ ] **Step 7: Manual browser check**

Start the app or existing dev flow, then in the in-app browser verify:

- Goal button appears when enabled.
- Clicking opens an empty panel.
- `window.setGoalItems(JSON.stringify({active:{short_term:[...],long_term:[]},history:[]}))` renders a goal.
- `window.setGoalButtonEnabled(false)` hides the button and closes panel.

- [ ] **Step 8: Commit**

```powershell
git add src/core/overlay_window.py assets/web/index.html assets/web/script.js assets/web/style.css src/locales/ko.json src/locales/en.json src/locales/ja.json
git commit -m "feat: show ENE goals in chat panel"
```

### Task 7: Settings Toggles and Manual Goal Editing

**Files:**
- Modify: `src/ui/settings_dialog.py`
- Modify: `src/core/bridge.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Add settings toggle attributes**

In `SettingsDialog.__init__`, add:

```python
self.enable_ene_goals_check: ToggleSwitch | None = None
self.show_ene_goal_button_check: ToggleSwitch | None = None
self._goal_items: dict = {}
```

- [ ] **Step 2: Add display/action toggles**

Near thought controls:

```python
self.enable_ene_goals_check = self._create_toggle("에네 목표 기능", key="settings.behavior.display.ene_goals")
self.enable_ene_goals_check.toggled.connect(self._on_ene_goals_toggle)
display_layout.addWidget(self.enable_ene_goals_check)
```

Near mood button:

```python
self.show_ene_goal_button_check = self._create_toggle("목표 버튼 표시", key="settings.behavior.actions.goal_button")
self.show_ene_goal_button_check.toggled.connect(self._on_setting_changed)
action_layout.addWidget(self.show_ene_goal_button_check)
```

- [ ] **Step 3: Load and save values**

In `_load_values()`:

```python
self.enable_ene_goals_check.setChecked(self._original_settings.get("enable_ene_goals", True))
self.show_ene_goal_button_check.setChecked(self._original_settings.get("show_ene_goal_button", True))
```

In `_get_current_values()`:

```python
"enable_ene_goals": self.enable_ene_goals_check.isChecked(),
"show_ene_goal_button": self.show_ene_goal_button_check.isChecked(),
```

- [ ] **Step 4: Add manual goal panel**

Create a new group in the behavior tab:

```text
에네 목표
- active short_term list
- active long_term list
- title input
- reason input
- type combo
- add button
- update selected button
- complete selected button
- cancel selected button
- history preview list
```

Prefer a small helper method in `settings_dialog.py`:

```python
def _build_goal_settings_group(self) -> QGroupBox:
    ...
```

Keep the UI simple: `QListWidget` for active/history, `QLineEdit` for title, `QPlainTextEdit` or `QTextEdit` for reason, `QComboBox` for type.

- [ ] **Step 5: Connect to bridge slots**

`SettingsDialog` stores the injected bridge as `self._bridge`, not `self.bridge`. When the settings dialog has `self._bridge`, connect:

```python
self._bridge.goal_items_updated.connect(self._on_goal_items_updated)
```

On panel open/load, call `self._bridge.request_goal_items()`.

Buttons call:

- add: `self._bridge.add_manual_goal(type, title, reason)`
- update: `self._bridge.update_goal_item(id, title, reason)`
- complete: `self._bridge.complete_goal_item(id, reason)`
- cancel: `self._bridge.cancel_goal_item(id, reason)`

After each call, bridge emits fresh items.

- [ ] **Step 6: Disable controls when feature is off**

Implement:

```python
def _refresh_ene_goal_controls(self):
    enabled = self.enable_ene_goals_check.isChecked()
    self.show_ene_goal_button_check.setEnabled(enabled)
    goal edit widgets.setEnabled(enabled and self._bridge is not None)
```

Call from `_on_ene_goals_toggle()` and `_load_values()`.

- [ ] **Step 7: Add i18n keys**

Add settings strings for Korean, English, Japanese. Keep Korean fallback text readable even if some locale key is missing.

- [ ] **Step 8: Manual settings check**

Open settings and verify:

- Goal feature toggle persists.
- Goal button toggle persists.
- Manual add appears in chat goal panel.
- Complete/cancel removes active item and moves it to history.

- [ ] **Step 9: Commit**

```powershell
git add src/ui/settings_dialog.py src/core/bridge.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_settings.py
git commit -m "feat: add ENE goal settings editor"
```

### Task 8: End-to-End Verification and Polish

**Files:**
- Modify only files needed to fix verification failures.

- [ ] **Step 1: Run full focused test set**

Run:

```powershell
pytest tests/test_response_contract.py tests/test_goal_update_parsing.py tests/test_ene_goal_manager.py tests/test_bridge_goals.py tests/test_prompt_config.py tests/test_settings.py tests/test_bridge_mood_flow.py tests/test_bridge_context_compaction.py tests/test_llm_provider.py tests/test_http_llm_clients_provider_parity.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader test suite if time allows**

Run:

```powershell
pytest -q
```

Expected: PASS. If unrelated pre-existing failures appear, capture the exact failing tests and reason.

- [ ] **Step 3: Browser UI verification**

Use the in-app browser against the local app URL. Verify:

- Goal button visible by default.
- Goal panel opens and closes.
- Empty state is clear.
- Active goal renders title and reason without text overlap.
- Button hide setting hides only the chat button.
- Feature OFF removes goal prompt contract and ignores updates but keeps file.

- [ ] **Step 4: File encoding verification**

Verify every new or modified file is UTF-8 with BOM, including Python, JSON, HTML, CSS, JS, and docs files. This follows the repository AGENTS.md policy even when an existing asset file previously used plain UTF-8.

- [ ] **Step 5: Inspect git diff**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files changed.

- [ ] **Step 6: Final commit for verification fixes**

If fixes were needed:

```powershell
git add <fixed-files>
git commit -m "fix: polish ENE goal system"
```

If no fixes were needed, do not create an empty commit.

## Implementation Notes

- Do not put `[ene_goal_update]` inside `[analysis]`; current analysis parsers filter to fixed keys.
- Preserve backward tuple compatibility in `AIWorker._normalize_response_payload()` because note/diary and tests may return older payload shapes.
- Goal history must not be included in normal LLM context.
- V1 cancel means `status=cancelled` and move to history, not hard delete.
- Keep long-term goals conservative in prompt wording.
- The settings dialog is large. Add focused helper methods instead of unrelated refactors.
- Keep UI text compact; the chat panel is an operational overlay, not a landing page.
