# ENE 선제 대화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE가 LLM 응답에서 선제 대화 예약을 추출하고, 사용자 응답이 없을 때 저장된 생성 프롬프트로 먼저 말을 걸게 만든다.

**Architecture:** 대화 약속과 분리된 `ProactiveConversationManager`와 `ProactiveBridgeMixin`을 추가한다. LLM 응답 튜플에는 기존 호환성을 유지하면서 선제 대화 예약 리스트를 마지막 값으로 붙이고, 브리지는 사용자 새 메시지 시 pending 예약을 취소하고 due 예약을 큐로 실행한다.

**Tech Stack:** Python 3, PyQt6 `QTimer`/signals, 기존 LLM response parser, JSON 사용자 저장소, pytest.

---

## 파일 구조

- Create: `src/ai/proactive_conversation_manager.py`
  - 선제 대화 예약 저장, 시간 가드레일, 허용 `cooldown_key`, 20분 쿨다운, due/expire/cancel 상태 전이를 담당한다.
- Create: `src/core/proactive_conversation_runtime.py`
  - 실행 프롬프트 생성, 실행 서명, 중복 억제 같은 순수 함수를 담당한다.
- Create: `src/core/bridge_mixins/proactive.py`
  - 브리지에서 예약 저장, 사용자 메시지 시 취소, due poll, 실행 큐, active id 정리를 담당한다.
- Modify: `src/ai/response_parser.py`
  - `[proactive_conversation]...[/proactive_conversation]` 블록을 파싱하고 보이는 응답에서 제거한다.
- Modify: `src/ai/response_contract.py`
  - 최종 응답 형식 계약에 선제 대화 예약 블록 규칙과 예시를 추가한다.
- Modify: `src/core/bridge_workers.py`
  - AIWorker normalize/emit payload를 10개 값으로 확장하고 legacy tuple 호환을 유지한다.
- Modify: `src/core/bridge_state.py`
  - `ProactiveBridgeState`와 legacy alias를 추가한다.
- Modify: `src/core/bridge.py`
  - 믹스인 상속, 타이머 초기화, manager setter를 추가한다.
- Modify: `src/core/bridge_mixins/chat_flow.py`
  - 사용자 메시지 시 pending 예약 취소, 응답 완료 시 예약 저장, 큐 drain을 연결한다.
- Modify: `src/core/app.py`
  - `ProactiveConversationManager` 초기화와 bridge 연결을 추가한다.
- Test: `tests/test_proactive_conversation_parsing.py`
- Test: `tests/test_proactive_conversation_manager.py`
- Test: `tests/test_proactive_conversation_runtime.py`
- Test: `tests/test_bridge_proactive_conversation.py`

## Task 1: 응답 파서 계약 확장

**Files:**
- Modify: `src/ai/response_parser.py`
- Modify: `src/core/bridge_workers.py`
- Test: `tests/test_proactive_conversation_parsing.py`
- Test: `tests/test_bridge_promise_reminders.py`

- [ ] **Step 1: Write failing parser tests**

```python
from src.ai.response_parser import parse_llm_response


def test_parse_response_extracts_proactive_conversation_block():
    parsed = parse_llm_response(
        """좋아요. [smile]
[proactive_conversation]
trigger_at=2026-05-26T21:20:00+09:00
title=가벼운 확인
generation_prompt=사용자가 잠시 확인할 일이 있다고 했고 아직 답장이 없다. 부담스럽지 않게 끝났는지 짧게 물어봐.
source_excerpt=잠시 확인하고 돌아온다는 흐름
reason=대화가 잠시 끊겼고 짧은 확인 발화가 자연스러움
cooldown_key=short-followup
[/proactive_conversation]"""
    )

    text, emotion, _tts, _events, _analysis, _promises, _thought, _goal, proactive = parsed
    assert text == "좋아요."
    assert emotion == "smile"
    assert proactive == [
        {
            "trigger_at": "2026-05-26T21:20:00+09:00",
            "title": "가벼운 확인",
            "generation_prompt": "사용자가 잠시 확인할 일이 있다고 했고 아직 답장이 없다. 부담스럽지 않게 끝났는지 짧게 물어봐.",
            "source_excerpt": "잠시 확인하고 돌아온다는 흐름",
            "reason": "대화가 잠시 끊겼고 짧은 확인 발화가 자연스러움",
            "cooldown_key": "short-followup",
        }
    ]
```

- [ ] **Step 2: Run parser test to verify RED**

Run: `python -m pytest tests/test_proactive_conversation_parsing.py -q`
Expected: FAIL because `parse_llm_response` still returns 8 values.

- [ ] **Step 3: Implement minimal parser support**

Add a block parser before TTS/emotion parsing:

```python
PROACTIVE_CONVERSATION_KEYS = {
    "trigger_at",
    "title",
    "generation_prompt",
    "source_excerpt",
    "reason",
    "cooldown_key",
}
```

Return tuple shape:

```python
Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict], str, Dict[str, str], List[Dict]]
```

- [ ] **Step 4: Extend AIWorker legacy normalization tests**

Add/modify tests so 8-value legacy payload becomes 9 values with `[]`, and new 9-value payload is preserved.

- [ ] **Step 5: Run targeted parser/worker tests**

Run: `python -m pytest tests/test_proactive_conversation_parsing.py tests/test_bridge_promise_reminders.py::test_ai_worker_normalize_response_payload_keeps_goal_update_for_runtime_flow -q`
Expected: PASS.

## Task 2: 선제 대화 매니저

**Files:**
- Create: `src/ai/proactive_conversation_manager.py`
- Test: `tests/test_proactive_conversation_manager.py`

- [ ] **Step 1: Write failing manager tests**

Cover:
- add/list roundtrip
- invalid `cooldown_key` normalizes to `global-proactive`
- past, under 1 minute, over 60 minute triggers are rejected
- same `cooldown_key` within 20 minutes is rejected
- global 20 minute cooldown rejects a different key
- `cancel_scheduled()` marks scheduled items as `cancelled`
- `refresh_due_statuses()` returns due items within 10 minutes and expires older scheduled items

- [ ] **Step 2: Run manager tests to verify RED**

Run: `python -m pytest tests/test_proactive_conversation_manager.py -q`
Expected: FAIL because the manager module does not exist.

- [ ] **Step 3: Implement dataclass and manager**

Use the existing app path helpers:

```python
from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data
```

Allowed keys:

```python
ALLOWED_COOLDOWN_KEYS = {
    "short-followup",
    "quiet-checkin",
    "topic-reopen",
    "task-momentum",
    "global-proactive",
}
```

Public methods:
- `add_proactive_conversation(...) -> ProactiveConversation | None`
- `list_items(include_statuses=None) -> list[ProactiveConversation]`
- `list_dicts(include_statuses=None) -> list[dict]`
- `cancel_scheduled(now=None) -> list[ProactiveConversation]`
- `set_status(item_id, status, now=None) -> bool`
- `delete_item(item_id) -> bool`
- `refresh_due_statuses(now=None) -> tuple[list[ProactiveConversation], list[ProactiveConversation]]`

- [ ] **Step 4: Run manager tests**

Run: `python -m pytest tests/test_proactive_conversation_manager.py -q`
Expected: PASS.

## Task 3: 런타임 순수 함수

**Files:**
- Create: `src/core/proactive_conversation_runtime.py`
- Test: `tests/test_proactive_conversation_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

Cover:
- signature uses `cooldown_key` and minute precision
- duplicate suppression checks active signature, queued payloads, and recent signatures
- prompt builder localizes Korean and includes `generation_prompt`

- [ ] **Step 2: Run runtime tests to verify RED**

Run: `python -m pytest tests/test_proactive_conversation_runtime.py -q`
Expected: FAIL because the runtime module does not exist.

- [ ] **Step 3: Implement runtime helpers**

Mirror the promise runtime style:
- `proactive_fire_signature(payload)`
- `prune_recent_proactive_fire_signatures(recent_signatures, now_dt, ttl_seconds=600)`
- `should_suppress_duplicate_proactive_fire(...)`
- `build_proactive_conversation_prompt(language, generation_prompt, title="", reason="", user_name=None)`

- [ ] **Step 4: Run runtime tests**

Run: `python -m pytest tests/test_proactive_conversation_runtime.py -q`
Expected: PASS.

## Task 4: 브리지 믹스인과 상태 연결

**Files:**
- Create: `src/core/bridge_mixins/proactive.py`
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Test: `tests/test_bridge_proactive_conversation.py`

- [ ] **Step 1: Write failing bridge tests**

Cover:
- `_store_proactive_conversations()` stores one candidate and tracks id on `_last_request_payload`
- `send_to_ai()` path cancels scheduled proactive items before appending the new user message
- `_enqueue_due_proactive_conversation()` queues when worker is running
- `_drain_proactive_queue_if_idle()` starts queued payload
- `_start_proactive_ai_worker()` sends `generation_prompt` through `_start_ai_worker()`
- `_handle_response_ready()` skips proactive storage when LLM promises exist

- [ ] **Step 2: Run bridge tests to verify RED**

Run: `python -m pytest tests/test_bridge_proactive_conversation.py -q`
Expected: FAIL because the mixin does not exist.

- [ ] **Step 3: Add `ProactiveBridgeState` aliases**

Add state fields:
- `manager`
- `run_queue`
- `active_id`
- `active_signature`
- `recent_fire_signatures`
- `timer`

Add aliases:
- `proactive_manager`
- `proactive_run_queue`
- `_active_proactive_id`
- `_active_proactive_signature`
- `_recent_proactive_fire_signatures`
- `proactive_timer`

- [ ] **Step 4: Implement `ProactiveBridgeMixin`**

Core methods:
- `_store_proactive_conversations(candidates, suppress=False)`
- `_remember_tracked_proactive_ids(ids)`
- `_delete_tracked_proactive_for_retry()`
- `_cancel_pending_proactive_conversations_for_user_message()`
- `_enqueue_due_proactive_conversation(payload)`
- `_drain_proactive_queue_if_idle()`
- `_start_proactive_ai_worker(payload)`
- `_poll_proactive_conversations()`

- [ ] **Step 5: Wire bridge init and chat flow**

In `WebBridge.__init__`:
- create 10 second `proactive_timer`
- connect to `_poll_proactive_conversations`
- start timer

In `send_to_ai`, `edit_last_user_message`, and slash command user paths:
- call `_cancel_pending_proactive_conversations_for_user_message()`

In `_handle_response_ready`:
- accept `proactive_conversations=None`
- store proactive candidates only when `llm_promises` is empty
- remember tracked proactive ids for reroll/edit cleanup
- delete active proactive item after completion
- drain promise queue first, then proactive queue

- [ ] **Step 6: Run bridge tests**

Run: `python -m pytest tests/test_bridge_proactive_conversation.py -q`
Expected: PASS.

## Task 5: 앱 초기화와 프롬프트 계약

**Files:**
- Modify: `src/core/app.py`
- Modify: `src/ai/response_contract.py`
- Test: `tests/test_response_contract.py`
- Test: `tests/test_app_goal_manager.py` or new focused app bootstrap test if needed

- [ ] **Step 1: Write failing contract tests**

Assert the response contract includes:
- `[proactive_conversation]`
- allowed cooldown keys
- no requirement to output the block every response

- [ ] **Step 2: Run contract tests to verify RED**

Run: `python -m pytest tests/test_response_contract.py -q`
Expected: FAIL because proactive rules are absent.

- [ ] **Step 3: Add contract rules**

Append concise rules in `build_response_contract_appendix()`:
- output block only when natural
- `trigger_at` must be ISO `+09:00`
- allowed `cooldown_key` list
- use synthetic/source summary, not private original text
- one block at most

- [ ] **Step 4: Wire app manager**

Add `_init_proactive_manager()` to `ENEApplication`, initialize after promise manager, set `bridge.proactive_manager`, and pass to llm client only if a future client attribute exists.

- [ ] **Step 5: Run app/contract tests**

Run: `python -m pytest tests/test_response_contract.py tests/test_app_paths.py -q`
Expected: PASS.

## Task 6: 통합 검증과 privacy scan

**Files:**
- All changed files

- [ ] **Step 1: Run focused suite**

Run:

```powershell
python -m pytest `
  tests/test_proactive_conversation_parsing.py `
  tests/test_proactive_conversation_manager.py `
  tests/test_proactive_conversation_runtime.py `
  tests/test_bridge_proactive_conversation.py `
  tests/test_response_contract.py `
  tests/test_promise_runtime.py `
  tests/test_bridge_promise_reminders.py `
  tests/test_away_nudge.py `
  tests/test_away_input_nudge.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Run privacy candidate scan before commit**

Run:

```powershell
rg -n "api[_-]?key|sk-[A-Za-z0-9]|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|생일|건강|자소서|취업|실제 대화" src tests docs
```

Expected: only generic rule/test wording, no real personal data or secrets.

- [ ] **Step 4: Commit**

Run:

```powershell
git add src tests docs/superpowers/plans/2026-05-26-proactive-conversation.md
git commit -m "feat: add proactive conversation scheduling"
```
