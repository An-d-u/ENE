# Summary-Anchored Life Records Implementation Plan

> **대체 결정:** 이 계획의 saved-at 기준 구현 단계는 [2026-09-27 세션 종료 기준점 설계](../specs/2026-09-27-life-record-session-end-anchor-design.md)와 후속 구현 계획으로 대체됐다. 현재 동작은 승인·저장된 요약이 있는 세션의 종료 시각부터 임계값과 기록 구간을 계산한다. 이 문서는 당시 구현 이력으로 남긴다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인되어 실제 저장까지 끝난 대화 요약과 그 세션의 종료를 생활 기록 기준점으로 삼고, 비어 있는 새 실행의 첫 일반 메시지에서만 생활 기록을 안전하게 한 번 생성한다.

**Architecture:** `AppSessionTracker`의 단일 원자적 V2 상태 파일이 현재 세션의 승인 요약, 활성 기준점, 생성 claim을 함께 소유한다. 모든 수동·자동·초기화·종료 요약은 하나의 검토/저장 파이프라인을 통과하고, 브리지는 단조 감소하는 실행 단위 게이트와 영속 claim을 사용해 생활 기록을 시작한다. 저장소나 상태 추적기가 불확실해지면 일반 대화는 유지하되 생활 기록만 fail-closed 읽기 전용으로 전환한다.

**Tech Stack:** Python 3.12, PyQt6, asyncio, pytest, JSON 원자 저장(`src/core/app_paths.py`)

---

## 공통 실행 규칙

- 구현 방식은 `AGENTS.md` 기준 **Sequential direct implementation**이다. 상태 스키마 → 요약 검토 → 앱 종료 → 생활 기록 게이트가 순차적으로 의존하므로 구현 작업을 병렬 수정하지 않는다.
- 각 Task는 30분 안에 집중 테스트까지 끝내는 것을 목표로 한다. 30분을 넘기면 현재 실패 원인과 남은 범위를 기록하고, 파일/상태 전이 기준으로 더 작은 Task로 다시 나눈 뒤 계속한다.
- 일반 Task에서는 아래에 명시한 집중 테스트만 실행한다. 전체 테스트는 **Task 4, Task 8B, Task 14, Task 15**에서만 실행한다.
- 공식 명세 리뷰와 품질 리뷰는 현재 diff와 직접 관련된 범위로 제한한다. Critical·Important는 즉시 수정하고 같은 집중 테스트를 다시 실행한다. Minor는 본 문서 하단의 `최종 Minor 검토 목록`에만 누적하고 Task 15에서 한 번에 판단한다.
- 테스트 fixture와 문서 예시는 모두 합성 데이터만 사용한다. `memory.json`, `user_profile.json`, `ene_profile.json`, `config.json`, `api_keys.json`, `obs_config.json`, `mood_state.json`, `calendar.json`, `diary.json`, `api_key.txt`, `.env*`와 생성 산출물은 커밋하지 않는다.
- 수정 파일은 UTF-8 without BOM으로 저장한다. 커밋 메시지는 영어로 작성한다.
- 모든 테스트 명령은 선택한 저장소 또는 격리 worktree 루트(`.`)에서 실행한다. 해당 작업 폴더에 `.venv`를 준비한다.
- pytest의 `--basetemp`는 Git에서 제외되는 `.pytest_tmp/` 아래 Task별 하위 경로를 쓴다.

## 공통 테스트 명령

집중 테스트 형식:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& '.\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp='.\.pytest_tmp\<task>' <test files or node ids>
```

전체 테스트 형식(Task 4, 8B, 14, 15만):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& '.\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp='.\.pytest_tmp\ene_summary_anchor_full'
```

기준선은 `4155 passed, 2 skipped`다. 새 테스트 수만큼 passed 수가 늘 수 있지만 실패는 0이어야 한다.

### Task 1: 세션 상태 V2 스키마와 V1 마이그레이션

**Files:**
- Modify: `src/core/life_session_tracker.py`
- Test: `tests/test_life_session_tracker.py`

- [ ] **Step 1: 엄격한 V2 파싱 실패 테스트 작성**

`tests/test_life_session_tracker.py`에 합성 UUID와 UTC timestamp를 사용해 다음을 검증한다.

- V2 envelope의 누락/추가 key 거부
- timezone-naive 또는 마이크로초가 있는 timestamp 거부
- 잘못된 `summary_id`, `expected_record_id`, source 거부
- current summary, active anchor, generation claim 각각의 필드 조합 불일치 거부
- 시간 순서(`saved_at <= origin_session_ended_at <= returned_at`) 위반 거부
- current summary가 있는 상태에서 `started_at > current_summary.saved_at`이면 거부
- claim의 `expected_record_id`를 `stable_life_record_id(active_anchor.saved_at, generation_claim.returned_at)`로 재계산했을 때 일치하지 않으면 거부

- [ ] **Step 2: 집중 테스트를 실행해 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_session_tracker.py`

Expected: 새 V2 테스트가 `_SESSION_VERSION == 1` 또는 parser 부재로 FAIL.

- [ ] **Step 3: V2 데이터 모델과 serializer/parser 구현**

`src/core/life_session_tracker.py`에 다음 불변 dataclass를 둔다.

```python
@dataclass(frozen=True)
class ApprovedSummaryState:
    summary_id: str
    saved_at: datetime

@dataclass(frozen=True)
class ActiveLifeAnchor:
    summary_id: str
    saved_at: datetime
    activation_source: Literal[
        "summary_graceful_exit",
        "summary_heartbeat_recovery",
    ]
    origin_session_started_at: datetime
    origin_session_ended_at: datetime

@dataclass(frozen=True)
class LifeGenerationClaim:
    summary_id: str
    returned_at: datetime
    expected_record_id: str
```

기존 session 필드와 위 세 필드를 `_SessionState`에 넣고 V2 payload로 직렬화한다. 모든 영속 timestamp는 timezone-aware, integer-second ISO 8601로 canonicalize한다. `summary_id`는 현재 memory 저장소가 생성하는 canonical lowercase UUID4, `expected_record_id`는 `stable_life_record_id()`가 만드는 정확히 64자의 lowercase hex여야 한다. V2는 정확한 key 집합과 상태별 불변식을 검사한다.

V2의 정확한 JSON envelope는 아래와 같다. 선택 상태는 key를 생략하지 않고 JSON `null`로 표현한다. 중첩 객체도 아래 key 집합과 정확히 일치해야 한다.

```json
{
  "version": 2,
  "session_id": "4f692dde-1ccf-4d2e-b640-a79dbf3c628a",
  "started_at": "2026-09-25T11:00:00+00:00",
  "last_seen_at": "2026-09-25T11:20:00+00:00",
  "status": "running",
  "stopped_at": null,
  "current_summary": {
    "summary_id": "a4e98a50-ed9f-4141-9f32-f31af718db83",
    "saved_at": "2026-09-25T11:20:00+00:00"
  },
  "active_anchor": {
    "summary_id": "1ed9694d-800e-4286-a954-90c95eb34f68",
    "saved_at": "2026-09-24T09:00:00+00:00",
    "activation_source": "summary_graceful_exit",
    "origin_session_started_at": "2026-09-24T08:00:00+00:00",
    "origin_session_ended_at": "2026-09-24T09:30:00+00:00"
  },
  "generation_claim": {
    "summary_id": "1ed9694d-800e-4286-a954-90c95eb34f68",
    "returned_at": "2026-09-25T11:00:00+00:00",
    "expected_record_id": "5fa9832ad49f374217b0fe506ac06211682435ae150f44f1db77a9bbcd6acd87"
  }
}
```

`status == "running"`이면 `stopped_at`은 `null`, `status == "stopped"`이면 aware integer-second timestamp여야 한다. current summary가 있으면 `started_at <= current_summary.saved_at <= last_seen_at`이어야 한다. active anchor는 `origin_session_started_at <= active_anchor.saved_at <= origin_session_ended_at`이어야 한다. claim이 있으면 active anchor가 반드시 존재하고 두 `summary_id`가 같으며 `max(active_anchor.saved_at, active_anchor.origin_session_ended_at, started_at) <= generation_claim.returned_at <= last_seen_at`이어야 한다. 또한 `expected_record_id == stable_life_record_id(active_anchor.saved_at, generation_claim.returned_at)`를 parser에서 재계산해 확인한다. claim이 없는 active anchor는 허용한다.

- [ ] **Step 4: V1을 anchor 없는 V2로만 마이그레이션**

V1 payload는 기존 엄격 parser로 검증한 뒤 session 기본 필드만 V2로 옮기고 `current_summary`, `active_anchor`, `generation_claim`은 모두 `None`으로 둔다. 예전 종료 시각이나 과거 memory를 기준점으로 추론하지 않는다. 다음 성공 commit 때 V2로 저장한다.

- [ ] **Step 5: 집중 테스트 통과 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_session_tracker.py`

Expected: PASS.

- [ ] **Step 6: 커밋**

```powershell
git add src/core/life_session_tracker.py tests/test_life_session_tracker.py
git commit -m "feat: add life session state v2"
```

### Task 2: 승인 요약 등록과 단조 시간 보정

**Files:**
- Modify: `src/core/life_session_tracker.py`
- Test: `tests/test_life_session_tracker.py`

- [ ] **Step 1: 등록 동작 실패 테스트 작성**

다음을 검증한다.

- 현재 running session 소유자만 `register_approved_summary(summary_id)` 성공
- 등록 시 tracker clock의 canonical integer-second 시간이 `saved_at`이 됨
- 같은 실행에서 새 승인 요약이 이전 current summary를 교체
- 시스템 시간이 뒤로 가도 `saved_at <= last_seen_at`이고 이전 등록 시각보다 감소하지 않음
- heartbeat가 current summary, active anchor, claim을 그대로 보존
- stale owner, commit 실패, clock 실패는 false를 반환하고 tracker를 읽기 전용으로 전환

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_session_tracker.py -k "approved_summary or heartbeat_preserves"`

Expected: `register_approved_summary`가 없어 FAIL.

- [ ] **Step 3: 원자 등록 API 구현**

```python
def register_approved_summary(self, summary_id: str) -> ApprovedSummaryState | None:
    ...
```

authoritative running payload를 다시 읽고 소유권을 확인한 뒤, `saved_at = max(canonical_now, started_at, last_seen_at, previous_current.saved_at)`으로 정규화한다. 같은 payload에서 `last_seen_at = max(last_seen_at, saved_at)`으로 올린다. current summary만 교체하고 active anchor/claim은 보존한다. 검증 및 저장 후 authoritative state를 다시 메모리에 반영한다. 실패 시 `_set_degraded(...)`를 호출한다.

- [ ] **Step 4: 집중 테스트 통과 확인**

Run: 위 Step 2 명령.

Expected: PASS.

- [ ] **Step 5: 커밋**

```powershell
git add src/core/life_session_tracker.py tests/test_life_session_tracker.py
git commit -m "feat: register approved summary anchors"
```

### Task 3: 종료 승격과 heartbeat 복구

**Files:**
- Modify: `src/core/life_session_tracker.py`
- Test: `tests/test_life_session_tracker.py`

- [ ] **Step 1: 기준점 승격 상태 전이 테스트 작성**

다음을 표 기반 parameterized test로 작성한다.

| 이전 상태 | 새 실행 결과 |
|---|---|
| stopped + current summary | `summary_graceful_exit` anchor 활성화 |
| running + current summary | `last_seen_at`를 종료 시각으로 쓰는 `summary_heartbeat_recovery` anchor 활성화 |
| summary 없음 + unused anchor 있음 | 기존 anchor 보존 |
| 새 current summary + 오래된 unused anchor | 새 summary anchor로 교체 |
| V1 stopped/running | anchor 없음 |
| 미래 summary/종료 시각 | fail-closed 또는 candidate 없음 |

정상 `stop_session()`은 current summary가 있으면 그 summary를 활성 anchor로 승격하고, current summary를 비운 뒤 stopped payload 하나로 commit하는지 검증한다. 이때 종료 endpoint는 `max(canonical_now, last_seen_at, current_summary.saved_at)`으로 계산한다. 비정상 종료 복구는 `start_session()`이 이전 running payload를 읽어 같은 승격을 수행하는지 검증한다.

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_session_tracker.py -k "promote or recovery or preserve_anchor"`

Expected: 기존 종료 시각 기반 candidate 동작 때문에 FAIL.

- [ ] **Step 3: candidate 계산을 active anchor 기반으로 교체**

`InactiveStartCandidate`는 `summary_id`, `started_at`, 새 source를 노출한다. `stop_session()`과 `start_session()`은 current summary가 있을 때만 새 anchor를 만든다. 세션 종료 시각은 provenance로만 저장하고 경과 시간 시작점은 항상 `saved_at`이다.

복구 시 하나의 새 V2 payload 안에서 이전 running 상태 승격과 새 running session 생성을 함께 계산해 한 번만 commit한다. commit 실패 전의 디스크 payload는 그대로 유지한다.

- [ ] **Step 4: 집중 테스트 통과 확인**

Run: 위 Step 2 명령.

Expected: PASS.

- [ ] **Step 5: 커밋**

```powershell
git add src/core/life_session_tracker.py tests/test_life_session_tracker.py
git commit -m "feat: promote summary anchors on session end"
```

### Task 4: 영속 claim·시작 복구와 앱 bootstrap 체크포인트

**Files:**
- Modify: `src/core/life_session_tracker.py`
- Modify: `src/core/app.py`
- Test: `tests/test_life_session_tracker.py`
- Test: `tests/test_life_record_app_lifecycle.py`

- [ ] **Step 1: claim API와 충돌 복구 실패 테스트 작성**

다음을 검증한다.

- `claim_life_generation(summary_id, requested_returned_at)`는 현재 active anchor와 summary ID가 일치할 때만 성공
- claim은 `returned_at = max(canonical(requested_returned_at), current.started_at, current.last_seen_at, active.saved_at, active.origin_session_ended_at)`으로 정규화하고 같은 commit에서 `last_seen_at = returned_at`으로 올림
- expected record ID는 정규화된 `active.saved_at`과 `returned_at`으로 tracker가 계산해 반환
- 동일 claim 재호출은 idempotent, 다른 claim은 거부
- `release_life_generation_claim(...)`은 anchor를 남김
- `complete_life_generation_claim(...)`은 claim과 해당 anchor를 함께 제거
- startup에서 `expected_record_id`가 `life_records.json`에 있으면 anchor 소비
- 없으면 claim만 해제하고 anchor 유지
- life record store `read_error`, tracker read/validation/commit 실패는 원래 디스크 state를 바꾸지 않고 생활 기록 읽기 전용 전환
- A의 claim을 정리한 후 같은 이전 세션의 B summary를 승격하는 계산이 단일 commit으로 끝남

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_session_tracker.py tests/test_life_record_app_lifecycle.py`

Expected: claim API와 app reconciliation 부재로 FAIL.

- [ ] **Step 3: claim API 구현**

tracker에 아래 claim/create/release/complete 메서드를 추가한다.

```python
def claim_life_generation(
    self,
    summary_id: str,
    requested_returned_at: datetime,
) -> LifeGenerationClaim | None:
    ...

def release_life_generation_claim(
    self,
    summary_id: str,
    expected_record_id: str,
) -> bool:
    ...

def complete_life_generation_claim(
    self,
    summary_id: str,
    expected_record_id: str,
) -> bool:
    ...
```

claim 메서드는 authoritative state와 tracker clock을 기준으로 `returned_at`을 위 Step 1 공식대로 정규화하고, `stable_life_record_id(active.saved_at, returned_at)`를 계산해 반환한다. 이때 `last_seen_at`도 같은 값으로 올린다. 각 메서드는 lease, running owner, authoritative state, summary ID, expected record ID를 다시 확인하고 전체 V2 payload를 원자 저장한다. 저장 실패는 `life_records_writable=False`로 전환한다.

- [ ] **Step 4: startup reconciliation을 manager 검증 뒤 수행**

`AppSessionTracker.start_session()`의 정확한 호출 계약을 다음처럼 확장한다.

```python
def start_session(
    self,
    *,
    persisted_record_ids: frozenset[str] | None = None,
    record_store_healthy: bool | None = None,
) -> InactiveStartCandidate | None:
    ...
```

`ENEApp._init_life_record_runtime()`은 `manager.store_status in {"missing", "ready"}`를 `record_store_healthy`로, `frozenset(record.id for record in manager.records)`를 `persisted_record_ids`로 항상 전달한다. 이전 state에 미완료 claim이 있는데 둘 중 하나라도 `None`이면 “기록 없음”으로 추정하지 않고 원래 state를 보존한 채 tracker를 읽기 전용으로 닫는다. 미완료 claim이 없는 기존 직접 호출은 두 인자가 생략돼도 정상 시작할 수 있어야 한다. manager가 `read_error`이면 tracker state를 쓰지 않고 전체 생활 기록 기능을 읽기 전용으로 둔다. claim 정리, 이전 summary 승격, 새 running session 기록은 tracker 안의 한 computed payload/commit으로 처리한다.

- [ ] **Step 5: 집중 테스트 통과 확인**

Run: Step 2 명령.

Expected: PASS.

- [ ] **Step 6: 전체 테스트 실행**

Run: 공통 전체 테스트 명령.

Expected: 0 failed, 기존 2 skipped 유지.

- [ ] **Step 7: 현재 diff 명세·품질 리뷰**

검토 범위는 `life_session_tracker.py`, `app.py`, 관련 테스트 diff로 제한한다. 원자성, V1 호환, 미래 시각, stale owner, store read error를 확인한다. Critical·Important만 즉시 수정하고 Step 5~6을 재실행한다. Minor는 최종 목록에 적는다.

- [ ] **Step 8: 커밋**

```powershell
git add src/core/life_session_tracker.py src/core/app.py tests/test_life_session_tracker.py tests/test_life_record_app_lifecycle.py
git commit -m "feat: recover durable life record claims"
```

### Task 5: 새 source 타입과 프롬프트 의미 정정

**Files:**
- Modify: `src/ai/life_record_types.py`
- Modify: `src/ai/life_record_prompt.py`
- Test: `tests/test_life_record_types.py`
- Test: `tests/test_life_record_prompt.py`

- [ ] **Step 1: 호환성과 문구 실패 테스트 작성**

- 새 source `summary_graceful_exit`, `summary_heartbeat_recovery` 저장/파싱 허용
- 과거 source `graceful_exit`, `heartbeat_recovery`도 계속 읽고 재생성 가능
- prompt에서 사용자가 전 구간 부재했다는 단정 제거
- prompt가 시작점을 “승인 요약 저장 시각”으로 설명하고 이후 실제 대화와 가상 생활이 겹칠 수 있음을 허용
- 저장 키 `inactive_started_at`은 호환을 위해 유지

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_record_types.py tests/test_life_record_prompt.py`

Expected: 새 source가 거부되고 기존 부재 문구가 남아 FAIL.

- [ ] **Step 3: allowlist와 prompt 수정**

두 새 source를 추가하되 과거 source를 삭제하지 않는다. 시간 구간의 사실성 제약은 유지하면서 사용자 부재를 가정하는 문장만 제거한다.

- [ ] **Step 4: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/ai/life_record_types.py src/ai/life_record_prompt.py tests/test_life_record_types.py tests/test_life_record_prompt.py
git commit -m "fix: align life record prompts with summary anchors"
```

### Task 6: 요약 검토 origin·결과 계약 통일

**Files:**
- Modify: `src/core/bridge.py`
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge_mixins/memory_summary.py`
- Test: `tests/test_bridge_memory_metadata.py`
- Test: `tests/test_chat_ui_assets.py`

- [ ] **Step 1: origin-aware 검토 상태 테스트 작성**

pending review에 아래 내부 메타데이터가 포함되지만 JS payload에는 불필요한 내부 값이 노출되지 않는지 검증한다.

```python
{
    "origin": "manual" | "auto" | "clear" | "quit",
    "completion_action": "continue" | "clear" | "quit",
    "messages": [...],
    ...
}
```

`summary_review_finished(origin, outcome)` 신호의 outcome은 `saved`, `cancelled`, `failed`, `saved_unregistered`로 제한한다. 기존 `summary_review_saved`는 호환을 위해 승인 성공 시 계속 emit하되 앱의 새 분기는 origin-aware 신호를 사용한다.

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_bridge_memory_metadata.py tests/test_chat_ui_assets.py -k "summary_review"`

Expected: origin/outcome 계약 부재로 FAIL.

- [ ] **Step 3: 단일 검토 시작 helper 구현**

`summarize_now()`는 manual origin으로 helper를 호출한다. worker 준비 성공/실패, 재생성, 승인, 취소는 pending origin을 보존한다. 검토 생성 실패는 `failed`, 취소는 `cancelled`를 emit한다. 동시 review와 종료 중 새 review는 기존 busy 규칙대로 거부한다.

- [ ] **Step 4: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/core/bridge.py src/core/bridge_state.py src/core/bridge_mixins/memory_summary.py tests/test_bridge_memory_metadata.py tests/test_chat_ui_assets.py
git commit -m "refactor: unify summary review outcomes"
```

### Task 7: 자동 요약을 검토 경로로 전환하고 watermark 적용

**Files:**
- Modify: `src/core/bridge.py`
- Modify: `src/core/bridge_mixins/memory_summary.py`
- Modify: `src/ui/memory_dialog.py`
- Test: `tests/test_bridge_memory_metadata.py`
- Test: `tests/test_memory_state_integration.py`

- [ ] **Step 1: 자동 검토와 watermark 실패 테스트 작성**

- threshold 도달 시 memory에 직접 저장하지 않고 auto review를 표시
- auto 취소 시 `next_auto_summary_count = 현재 buffer 길이 + threshold`
- manual 취소는 현재 길이가 이미 watermark 이상일 때만 같은 방식으로 연기하고, 미만이면 기존 watermark 유지
- 승인 후 reviewed prefix를 제거한 새 buffer 좌표에서 `next_auto_summary_count = threshold`
- clear 완료 후 `threshold`로 reset
- threshold 0은 자동 요약 비활성
- 실행 중 threshold 변경은 `현재 buffer 길이 + 새 threshold`로 재계산하며, 0이면 disabled 상태
- review 진행 중 또는 worker 진행 중 중복 auto review 없음
- 자동 review 후보 생성 실패 시 기존 watermark 유지

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_bridge_memory_metadata.py tests/test_memory_state_integration.py -k "auto or watermark or threshold"`

Expected: 기존 `_auto_summarize()`가 직접 저장하여 FAIL.

- [ ] **Step 3: watermark helper와 자동 review 구현**

bridge 초기화에서 `next_auto_summary_count`를 현재 threshold로 설정한다. `_check_auto_summarize()`는 buffer 길이가 watermark 이상일 때 `_start_summary_review(..., origin="auto")`만 호출한다. 기존 직접 저장형 `_auto_summarize()`는 제거하거나 검토 준비 helper로 축소해 저장 우회 경로가 남지 않게 한다.

`memory_dialog.py`의 threshold 변경 handler는 bridge의 `set_summarize_threshold(value)`를 호출하게 하여 설정 저장과 watermark 재계산을 한곳에서 처리한다.

자동 review를 재생성해도 최초 origin과 review snapshot 뒤에 추가된 메시지는 보존되는지 함께 검증한다.

- [ ] **Step 4: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/core/bridge.py src/core/bridge_mixins/memory_summary.py src/ui/memory_dialog.py tests/test_bridge_memory_metadata.py tests/test_memory_state_integration.py
git commit -m "feat: review automatic conversation summaries"
```

### Task 8A: 대화 초기화의 검토·승인·취소 동작

**Files:**
- Modify: `src/core/bridge_mixins/memory_summary.py`
- Test: `tests/test_bridge_memory_metadata.py`
- Test: `tests/test_memory_state_integration.py`

- [ ] **Step 1: clear 상태 전이 실패 테스트 작성**

- buffer가 비었거나 요약 불가 조건이면 즉시 clear
- non-empty buffer는 clear origin review 표시
- 승인: 저장 → reviewed prefix 제거 → clear 완료
- 취소: 저장 없이 clear 완료
- review 생성 실패 또는 memory 저장 실패: buffer 보존, clear 중단
- origin-aware handler가 합성 `saved_unregistered` outcome을 받으면 reviewed prefix 제거 후 clear 완료와 error 표시 분기를 선택함. 실제 tracker 등록 실패 연결은 Task 9에서 통합 검증
- clear 완료 시 auto watermark reset

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_bridge_memory_metadata.py tests/test_memory_state_integration.py -k "clear"`

Expected: 현재 synchronous `_auto_summarize()` 후 즉시 clear 동작 때문에 FAIL.

- [ ] **Step 3: clear completion action 구현**

실제 buffer·context·attachment 초기화 코드를 `_complete_conversation_clear()`로 분리한다. `clear_conversation()`은 review를 시작하고, origin-aware outcome handler가 `saved`, `cancelled`, `saved_unregistered`일 때만 completion action을 수행한다. `failed`는 아무것도 지우지 않는다.

- [ ] **Step 4: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/core/bridge_mixins/memory_summary.py tests/test_bridge_memory_metadata.py tests/test_memory_state_integration.py
git commit -m "feat: review summaries before clearing chat"
```

### Task 8B: 앱 종료 요약 검토 통합 체크포인트

**Files:**
- Modify: `src/core/app.py`
- Modify: `src/core/bridge_mixins/memory_summary.py`
- Test: `tests/test_app_quit_summary.py`
- Test: `tests/test_task14b_worker_shutdown.py`

- [ ] **Step 1: quit 상태 전이 실패 테스트 작성**

- 최초 확인창에서 “요약 안 함” 선택은 바로 종료
- “요약” 선택은 quit origin review 표시
- origin-aware handler가 합성 `saved` outcome을 받으면 종료 계속. 실제 memory 저장→tracker 등록→종료 연결은 Task 9에서 통합 검증
- review 생성 실패, memory 저장 실패, 검토 취소는 종료 중단하고 앱/buffer 유지
- origin-aware handler가 합성 `saved_unregistered` outcome을 받으면 종료 중단과 error 표시 분기를 선택함. 실제 tracker 등록 실패 연결은 Task 9에서 통합 검증
- 종료 중단 후 사용자가 다시 종료해 “요약 안 함”을 선택할 수 있음
- signal 중복 연결이나 두 번 종료 없음
- worker drain이 성공한 실제 shutdown에서만 `stop_session()`으로 current summary 승격

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_app_quit_summary.py tests/test_task14b_worker_shutdown.py`

Expected: 기존 saved-only signal 경로가 cancel/failure를 구분하지 못해 FAIL.

- [ ] **Step 3: origin-aware 종료 핸들러 구현**

`_start_quit_summary_review()`은 bridge의 quit 전용 review 시작 메서드를 호출한다. `_on_quit_summary_review_finished(origin, outcome)`은 quit origin만 처리하고 `saved`에서만 종료를 진행한다. `cancelled`, `failed`, `saved_unregistered`는 `_quit_after_summary_review`를 해제하고 앱을 유지한다.

- [ ] **Step 4: 집중 테스트 통과 확인**

Run: Step 2 명령.

Expected: PASS.

- [ ] **Step 5: 전체 테스트 실행**

Run: 공통 전체 테스트 명령.

Expected: 0 failed, 기존 2 skipped 유지.

- [ ] **Step 6: 현재 diff 명세·품질 리뷰**

검토 범위는 Task 5~8B diff로 제한한다. 모든 요약 origin이 review를 우회하지 않는지, clear/quit의 cancel과 실패가 서로 다른지, watermark가 무한 재표시를 막는지 확인한다. Critical·Important만 수정하고 집중/전체 테스트를 재실행한다.

- [ ] **Step 7: 커밋**

```powershell
git add src/core/app.py src/core/bridge_mixins/memory_summary.py tests/test_app_quit_summary.py tests/test_task14b_worker_shutdown.py
git commit -m "feat: integrate reviewed summaries with shutdown"
```

### Task 9: 저장된 승인 요약을 tracker에 등록

**Files:**
- Modify: `src/core/bridge_mixins/memory_summary.py`
- Modify: `src/core/app.py`
- Test: `tests/test_bridge_memory_metadata.py`
- Test: `tests/test_app_quit_summary.py`
- Test: `tests/test_life_record_app_lifecycle.py`

- [ ] **Step 1: 저장 순서와 부분 실패 테스트 작성**

승인 경로의 순서를 `memory 저장 → tracker 등록 → origin completion`으로 고정해 다음을 검증한다.

- `saved_memory.id`를 summary ID로 등록
- tracker 성공 뒤에만 outcome `saved`
- tracker 등록 실패 전에는 memory 저장이 이미 durable함
- tracker 실패 시 저장된 요약을 롤백하지 않음
- tracker 실패 시 생활 기록만 읽기 전용으로 전환
- 모든 origin이 reviewed prefix를 제거해 중복 요약을 막음
- manual/auto는 error를 표시하고 계속, clear는 clear 완료, quit은 종료 중단
- memory 저장 자체 실패 시 tracker를 호출하지 않고 buffer 유지

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_bridge_memory_metadata.py tests/test_app_quit_summary.py tests/test_life_record_app_lifecycle.py -k "summary or tracker or register"`

Expected: 승인 요약과 tracker가 아직 연결되지 않아 FAIL.

- [ ] **Step 3: tracker 등록 helper 구현**

`_persist_reviewed_summary()`는 `saved_memory`를 반환하도록 바꾸고, 승인 orchestration이 `saved_memory.id`를 tracker에 등록한다. bridge가 app과 같은 tracker 객체를 받는 기존 binding을 사용한다. 실패 시 app/bridge의 공통 read-only setter로 상태를 동기화한다.

- [ ] **Step 4: origin별 부분 실패 처리 구현**

tracker 실패라도 memory 저장이 성공했으면 `_complete_summary_context(reviewed_messages)`를 정확히 한 번 호출하고 pending을 비운다. 그런 뒤 `saved_unregistered` outcome을 emit해 clear/quit/manual/auto가 승인된 계약대로 분기한다.

- [ ] **Step 5: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/core/bridge_mixins/memory_summary.py src/core/app.py tests/test_bridge_memory_metadata.py tests/test_app_quit_summary.py tests/test_life_record_app_lifecycle.py
git commit -m "feat: register saved summaries with session tracker"
```

### Task 10: 실행 단위 `life_gate_open` 상태 전이

**Files:**
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge_mixins/life_records.py`
- Modify: `src/core/bridge_mixins/memory_summary.py`
- Test: `tests/test_life_record_request_gate.py`
- Test: `tests/test_life_record_end_to_end.py`
- Test: `tests/test_life_record_bridge_flow.py`
- Test: `tests/test_life_record_regeneration.py`

- [ ] **Step 1: gate 진리표 실패 테스트 작성**

`auto_decision_completed` 기대를 모두 `life_gate_open` 계약으로 바꾸고 다음을 검증한다.

- process 시작 buffer가 비어 있을 때만 true, 기존 buffer가 있으면 false
- 첫 general request가 정상 commit되면 false
- 생활 기록 생성을 시작하면 false
- non-empty buffer의 clear/summary가 시작되면 false
- 한번 false가 되면 같은 process에서 clear 후에도 true로 돌아오지 않음
- command, busy 거부, input validation 실패, attachment parse 거부는 유지
- normal commit 예외/rollback은 유지
- N분 전 메시지는 정상 대화로 commit되어 gate만 닫고 anchor는 소비하지 않음
- 현재 session buffer가 하나라도 있으면 생활 기록을 생성하지 않음

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_record_request_gate.py tests/test_life_record_end_to_end.py tests/test_life_record_bridge_flow.py tests/test_life_record_regeneration.py`

Expected: 기존 `auto_decision_completed`의 첫 판단 소비 semantics 때문에 FAIL.

- [ ] **Step 3: state와 commit 경계 수정**

`LifeRecordBridgeState.auto_decision_completed`를 `life_gate_open`으로 교체한다. 초기화 값은 bridge가 기존 conversation buffer를 읽은 뒤 설정한다. `_dispatch_general_request()`는 gate 조건을 평가하되, 정상 대화는 `_commit_prepared_chat_request()` 성공 후에만 닫고, 생활 기록은 claim이 저장되어 실제 생성을 시작할 때 닫는다.

summary/clear가 non-empty buffer를 대상으로 시작할 때 사용하는 `_close_life_gate()` helper를 둔다. 이 helper는 false로만 전이한다.

- [ ] **Step 4: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/core/bridge_state.py src/core/bridge_mixins/life_records.py src/core/bridge_mixins/memory_summary.py tests/test_life_record_request_gate.py tests/test_life_record_end_to_end.py tests/test_life_record_bridge_flow.py tests/test_life_record_regeneration.py
git commit -m "refactor: make the life record gate monotonic"
```

### Task 11: 생활 기록 생성 전에 영속 claim 획득

**Files:**
- Modify: `src/core/bridge_mixins/life_records.py`
- Test: `tests/test_life_record_request_gate.py`
- Test: `tests/test_life_record_end_to_end.py`

- [ ] **Step 1: claim-first 실패 테스트 작성**

- gate의 나머지 조건(world, feature, elapsed, writable, idle)을 통과한 뒤 worker보다 먼저 claim 저장
- tracker가 반환한 claim의 expected ID는 `stable_life_record_id(anchor.saved_at, claim.returned_at)`와 동일
- claim 저장 실패: worker를 시작하지 않고 일반 reply로 fallback
- fallback normal commit 성공: gate 닫힘, anchor 유지
- fallback normal commit 실패: gate 유지, anchor 유지
- claim 성공 뒤 worker 시작: gate 닫힘
- 같은 summary의 두 번째 자동 생성 시도 차단

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_record_request_gate.py tests/test_life_record_end_to_end.py -k "claim or gate or fallback"`

Expected: claim 없이 worker가 시작되어 FAIL.

- [ ] **Step 3: dispatch에 claim 단계 삽입**

world/elapsed 검증 후 `tracker.claim_life_generation(candidate.summary_id, prepared_request.received_at)`을 호출해 claim을 원자 저장한다. 성공 반환값의 정규화된 `returned_at`과 `expected_record_id`를 bridge state에 snapshot으로 보관하고 worker/context/save가 같은 값을 사용하게 한다. bridge가 요청 시각으로 ID를 미리 계산하지 않는다. claim 실패는 read-only 전환 여부를 tracker에서 읽어 반영한 뒤 정상 대화 commit으로 돌아간다.

- [ ] **Step 4: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/core/bridge_mixins/life_records.py tests/test_life_record_request_gate.py tests/test_life_record_end_to_end.py
git commit -m "feat: claim life record generation before workers"
```

### Task 12: 생성 성공·실패에 따른 claim 완료/해제

**Files:**
- Modify: `src/core/bridge_mixins/life_records.py`
- Modify: `src/core/bridge_state.py`
- Test: `tests/test_life_record_end_to_end.py`
- Test: `tests/test_life_record_request_gate.py`
- Test: `tests/test_life_record_regeneration.py`

- [ ] **Step 1: lifecycle 실패 테스트 작성**

- LLM 생성 실패, output validation 실패, record 저장 실패는 claim 해제 + anchor 유지
- 실패한 같은 실행에서는 gate가 닫혀 재시도하지 않음
- record 저장 성공 뒤 tracker complete 성공은 anchor/claim 소비
- record 저장 성공과 tracker complete 사이 crash를 모사하면 다음 startup reconciliation이 expected ID로 소비
- tracker complete 실패는 저장된 record를 삭제하지 않고 읽기 전용 전환
- manual regeneration은 auto claim/anchor를 건드리지 않음
- stale worker callback은 다른 operation의 claim을 해제/완료하지 않음

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_life_record_end_to_end.py tests/test_life_record_request_gate.py tests/test_life_record_regeneration.py -k "claim or failure or save or regeneration"`

Expected: claim finalization 부재로 FAIL.

- [ ] **Step 3: operation-owned claim cleanup 구현**

auto operation state에 claim summary ID/expected ID를 보관한다. `_fail_life_record_before_worker`, worker error, validation error, save error의 공통 finalizer가 claim을 한 번만 release한다. `_save_generated_life_record()`의 authoritative 확인 뒤에만 tracker complete를 호출한다. 수동 재생성 phase는 이 helper를 호출하지 않는다.

- [ ] **Step 4: 집중 테스트 통과 확인 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add src/core/bridge_mixins/life_records.py src/core/bridge_state.py tests/test_life_record_end_to_end.py tests/test_life_record_request_gate.py tests/test_life_record_regeneration.py
git commit -m "feat: finalize life record generation claims"
```

### Task 13: 사용자 시나리오 end-to-end 회귀 테스트

**Files:**
- Modify: `tests/test_life_record_end_to_end.py`
- Modify: `tests/test_life_record_app_lifecycle.py`
- Modify: `tests/test_memory_state_integration.py`

- [ ] **Step 1: 승인된 시나리오를 합성 E2E 테스트로 작성**

다음 흐름을 각각 별도 테스트로 고정한다.

1. 승인 요약 저장 → 세션 정상 종료 → N분 후 빈 실행 → 첫 일반 메시지 → 생활 기록 1개 생성
2. 승인 요약 저장 → 종료 → N분 전 일반 메시지 → 일반 대화만 수행, anchor 미소비 → 같은 실행에서는 재시도 안 함
3. 승인 요약 저장 → 종료 → 테스트 실행/메시지/종료(새 승인 요약 없음) → anchor 보존 → 이후 자격 실행에서 생성
4. 승인 요약 저장 후 잠깐 추가 대화 → 추가 요약 없이 종료 → 최초 승인 요약 시각 기준 anchor
5. 현재 실행에 메시지가 이미 존재 → N분 경과했어도 생성 없음
6. 자동 요약 검토 취소 → threshold만큼 추가 메시지 후 다시 review
7. clear 승인/취소와 quit 승인/취소의 서로 다른 completion 동작
8. 같은 summary는 crash recovery를 포함해 최대 한 개의 성공 record만 생성

- [ ] **Step 2: 집중 테스트 실행**

Run: 공통 집중 테스트 형식으로 `tests/test_life_record_end_to_end.py tests/test_life_record_app_lifecycle.py tests/test_memory_state_integration.py`

Expected: PASS. 실패 시 구현을 바꾸기 전에 시나리오가 설계 문서와 같은지 먼저 확인한다.

- [ ] **Step 3: 필요한 Critical·Important 회귀만 수정**

수정 범위는 실패한 시나리오의 직접 경로로 제한한다. Minor는 목록에 누적한다.

- [ ] **Step 4: 집중 테스트 재실행 및 커밋**

Run: Step 2 명령.

Expected: PASS.

```powershell
git add tests/test_life_record_end_to_end.py tests/test_life_record_app_lifecycle.py tests/test_memory_state_integration.py
git commit -m "test: cover summary anchored life record flows"
```

### Task 14: 설정 문구·문서 동기화와 통합 체크포인트

**Files:**
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `README_JA.md`
- Modify: `docs/life_records.md`
- Test: `tests/test_ui_i18n_smoke.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: locale 기대값 실패 테스트 작성**

기존 “최소 비활성 시간 / Minimum inactive time / 最小非アクティブ時間” 계열 문구가 각각 “요약 후 최소 시간 / Minimum time after summary / 要約後の最小時間” 의미로 바뀌는지 확인한다. 설명에는 승인·저장된 요약과 세션 종료 후의 첫 빈 실행이라는 핵심을 짧게 담는다.

- [ ] **Step 2: 실패 확인**

Run: 공통 집중 테스트 형식으로 `tests/test_ui_i18n_smoke.py tests/test_settings.py`

Expected: 이전 locale 문구 때문에 FAIL.

- [ ] **Step 3: 3개 locale과 문서 수정**

README 3종과 `docs/life_records.md`에 다음을 일관되게 설명한다.

- 승인·저장된 요약이 기준 시각을 만듦
- 그 요약을 포함한 세션이 끝나야 활성화됨
- 현재 실행이 빈 상태로 시작해야 함
- N분 전 메시지는 기준점을 소비하지 않지만 같은 실행의 생성 기회는 닫음
- 자동 요약도 검토창을 거침
- 가상 생활과 이후 실제 대화 시간은 겹칠 수 있음
- V1 상태에서는 과거 종료를 자동 기준점으로 승격하지 않음

- [ ] **Step 4: 집중 테스트 통과 확인**

Run: Step 2 명령.

Expected: PASS.

- [ ] **Step 5: 전체 테스트 실행**

Run: 공통 전체 테스트 명령.

Expected: 0 failed, 기존 2 skipped 유지.

- [ ] **Step 6: 현재 전체 diff 공식 명세·품질 리뷰**

승인 설계 문서 `docs/superpowers/specs/2026-09-25-life-record-summary-anchor-design.md`와 현재 branch diff만 대조한다. Critical·Important는 즉시 수정하고 관련 집중 테스트와 전체 테스트를 재실행한다. Minor는 목록에 남긴다.

- [ ] **Step 7: 커밋**

```powershell
git add src/locales/ko.json src/locales/en.json src/locales/ja.json README.md README_EN.md README_JA.md docs/life_records.md tests/test_ui_i18n_smoke.py tests/test_settings.py
git commit -m "docs: explain summary anchored life records"
```

### Task 15: 최종 개인정보·인코딩·회귀 검증

**Files:**
- Review: 현재 branch의 전체 diff와 새 커밋
- Modify: Critical·Important 또는 승인된 Minor가 있을 때만 직접 관련 파일

- [ ] **Step 1: 최종 Minor 목록 판단**

누적된 Minor를 각각 `수정`, `후속 작업`, `기각`으로 분류한다. 현재 기능의 정확성·사용자 혼란·유지보수에 실질 영향이 있는 항목만 수정한다. 범위 밖 개선은 코드에 넣지 않는다.

- [ ] **Step 2: 개인정보 후보와 runtime 파일 검사**

```powershell
git status --short
git diff --check
git diff --name-only main...HEAD
rg -n --hidden -g '!\.git/**' -g '!\.worktrees/**' -g '!*.pyc' -g '!__pycache__/**' '(sk-|AIza|api[_-]?key|secret|token|password|건강|일정|취업|프로필)' $(git diff --name-only main...HEAD)
```

검색 결과는 모두 문맥을 확인한다. 합성 테스트의 일반 키워드는 허용하지만 실제 사용자 대화·이름·프로필·일정·건강 정보나 비밀 키 패턴이 있으면 커밋을 중단하고 제거한다. runtime 파일이나 binary/generated artifact가 diff에 있으면 제거한다.

- [ ] **Step 3: UTF-8 BOM 검사**

변경된 텍스트 파일의 첫 3바이트가 `EF BB BF`가 아닌지 확인한다. BOM이 있으면 해당 파일만 UTF-8 without BOM으로 다시 저장하고 관련 집중 테스트를 실행한다.

- [ ] **Step 4: 전체 테스트 최종 실행**

Run: 공통 전체 테스트 명령.

Expected: 0 failed, 기존 2 skipped 유지.

- [ ] **Step 5: 최종 diff 품질 확인**

```powershell
git diff --check main...HEAD
git status --short --branch
git log --oneline --decorate main..HEAD
```

Expected: whitespace 오류 없음, 의도하지 않은 파일 없음, 작업 커밋이 영어 메시지로 정리됨.

- [ ] **Step 6: 마지막 수정이 있을 때만 커밋**

```powershell
git add <Task 15에서 실제 수정한 파일만>
git commit -m "fix: close summary anchor review findings"
```

수정이 없다면 빈 커밋을 만들지 않는다.

## 최종 Minor 검토 목록

구현 중 Minor 이슈가 발견될 때 아래 형식으로만 누적한다. 구현 시작 시 목록은 비어 있다.

| Task | 파일/위치 | 내용 | Task 15 결정 |
|---|---|---|---|

## 완료 조건

- 승인·저장된 요약과 세션 종료만 새 생활 기록 기준점을 만든다.
- 자동·수동·초기화·종료 요약이 모두 동일한 사용자 검토를 거친다.
- 빈 실행의 첫 일반 메시지에서만 gate를 평가하며, N분 전 메시지는 anchor를 소비하지 않는다.
- 영속 claim과 startup reconciliation으로 동일 summary의 성공 record가 최대 하나다.
- 저장/추적 오류에서 일반 대화는 유지되고 생활 기록만 안전하게 읽기 전용이 된다.
- Task 4, 8B, 14, 15 전체 테스트와 모든 집중 테스트가 통과한다.
- 개인정보, runtime 파일, BOM, 의도하지 않은 생성 산출물이 diff에 없다.
