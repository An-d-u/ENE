# ENE Mood Engine V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE가 최근 여러 사건의 정서 잔향과 장기 관계를 시간축에 맞게 유지하면서도, 일반 요청에서는 상태에 따른 자율적 거리 두기·제한·거절을 표현하고 응급·통제권·위험 작업 정책은 항상 보존하는 Mood Engine V3를 구축한다.

**Architecture:** 새 `mood_engine.py`가 순수하고 결정론적인 상태 전이·감쇠·파생 로직을 소유하고, 기존 `MoodManager`는 V3 저장·V2 마이그레이션·프롬프트 context·레거시 snapshot facade만 담당한다. 최종 LLM 응답에는 nullable `mood_analysis`를 추가하고 `mood_policy.py`가 구조화된 행동 태도만 검증한다. 브리지는 사용자 사건 UUID를 소유해 최종 검증된 응답에서만 상태를 정확히 한 번 갱신하며, 기존 메모리 시스템과 UI 6인자 신호는 유지한다.

**Tech Stack:** Python 3.12, dataclasses/typing, `hashlib`, PyQt6/QWebEngine, JSON Schema 기반 구조화 응답, pytest, 기존 JavaScript UI 자산 테스트

---

## 구현 전 고정 결정

1. 응답 튜플의 기존 10개 인덱스는 유지하고 `mood_analysis: dict | None`을 11번째 값으로 추가한다. Qt `response_ready` 시그널도 기존 11개 인자 뒤에 mood JSON 문자열을 12번째로 추가한다.
2. 새 메시지는 UUIDv4 사건 ID를 발급한다. 리롤과 마지막 메시지 수정은 같은 논리 사건 ID를 재사용하며 이미 반영된 사건을 재평가하지 않는다. V1에서는 편집으로 과거 기분 전이를 되감지 않는다. 이 제한은 테스트와 코드 주석에 남긴다.
3. `enable_mood_system=true`이면서 `enable_response_analysis=true`일 때 strict 응답의 잘못된 `mood_analysis`는 전체 응답 무효로 처리해 한 번 재생성한다. 레거시 태그 모드의 잘못된 값은 관계를 바꾸지 않는 중립 사건으로 정규화한다.
4. `get_snapshot()`은 읽기 전용이다. 감쇠·환경·자발 변화 저장은 `advance_time_and_save(now_utc)` 또는 최종 사건 적용 경계에서만 수행한다.
5. V2의 naive 시각은 마이그레이션 시 실행 환경의 로컬 timezone으로 해석해 UTC로 변환한다. 테스트에서는 timezone을 주입한다.
6. 이전 프리셋은 `calm → calm`, `affectionate → balanced`, `playful → expressive`로 매핑한다. 새 관계의 애정·신뢰 기본값은 프리셋과 무관하게 0이다.
7. 활성 정서 이름은 `joy`, `tenderness`, `amusement`, `interest`, `sadness`, `hurt`, `anger`, `anxiety`로 고정한다. 단기 `tenderness`와 장기 `relationship.affection`을 구분한다.
8. `MemoryManager`와 `memory.json`은 수정하지 않는다. 기억 검색만으로 기분을 재활성화하지 않고, 현재 메시지가 과거 사건을 다시 다룰 때만 새 사건으로 분류한다.

## 파일 책임 지도

### 신규 파일

- `src/ai/mood_engine.py`: V3 상태 기본값·검증, 사건 타입, 계수표, 시간 전진, 사건 reducer, 비영속 이전 주 감정을 입력받는 정서/행동/snapshot 파생.
- `src/ai/mood_policy.py`: 행동 태도 허용 범위, 구조화 태도 validator, urgent 고정 footer와 fallback.
- `tests/test_mood_engine.py`: 결정론·골든 변화량·흔적·균열·회복·감쇠·멱등성 단위 테스트.
- `tests/test_mood_policy.py`: 일반 자율 행동, urgent, 위험 작업 안전 경계 테스트.

### 주요 수정 파일

- `src/ai/mood_manager.py`: V3 facade, 원자 저장, V2 마이그레이션, context, 레거시 public API.
- `src/ai/analysis_prompt.py`, `src/ai/response_contract.py`, `src/ai/response_envelope.py`, `src/ai/response_parser.py`: `MoodTurnAnalysis` 출력·strict schema·레거시 파싱.
- `src/ai/response_pipeline.py`: 구조화 태도 1회 재생성, urgent footer/fallback.
- `src/ai/llm_client.py`, `src/ai/http_llm_common.py`, `src/ai/llm_provider.py`: 11개 응답 튜플과 정책 처리 전달.
- `src/core/bridge_workers.py`: 12번째 Qt 인자 운반, `/diary`·`/note`·취소 경계.
- `src/core/bridge_mixins/chat_flow.py`, `attachments.py`, `obsidian.py`: 사건 UUID 소유, 선적용 제거, 최종 1회 반영, 리롤·수정 멱등성.
- `src/core/app.py`, `src/core/settings.py`: 비활성 시 상태 파일 무접촉, 새 프리셋 기본값과 레거시 값 정규화.
- `src/ui/settings_tabs/behavior_tab.py`, `src/ui/settings_dialog.py`, `src/ui/settings_dialog_values.py`, `src/core/overlay_window.py`, `src/locales/{ko,en,ja}.json`: 기분 사용·프리셋 설정과 버튼 독립성.
- `src/core/bridge_mixins/mood.py`, `assets/web/runtime_mood_obsidian.js`, `assets/web/runtime_ui_strings.js`: 기존 6인자 호환을 유지하면서 주·보조 감정 표시.

## 계수와 골든 시나리오

V1 계수는 코드 상수로 고정하고 설정 파일에서 사용자 조정값으로 노출하지 않는다.

```python
INTENSITY_WEIGHT = {0: 0.0, 1: 0.45, 2: 0.75, 3: 1.0}
CLARITY_WEIGHT = {"explicit": 1.0, "inferred": 0.75, "ambiguous": 0.35}
CERTAINTY_WEIGHT = {"low": 0.5, "medium": 0.75, "high": 1.0}
PRESET_WEIGHT = {"calm": 0.75, "balanced": 1.0, "expressive": 1.25}

BACKGROUND_BASE = {
    "neutral": (0.00, 0.00, 0.00),
    "connection": (0.03, 0.01, -0.02),
    "success": (0.04, 0.03, -0.01),
    "loss": (-0.05, -0.03, 0.02),
    "threat": (-0.03, 0.01, 0.06),
    "conflict": (-0.04, 0.02, 0.07),
    "novelty": (0.01, 0.04, 0.01),
    "repair": (0.02, 0.00, -0.03),
}

AFFECT_BASE = {
    "connection": {"tenderness": 0.18, "joy": 0.06},
    "success": {"joy": 0.22},
    "loss": {"sadness": 0.24},
    "threat": {"anxiety": 0.25},
    "conflict": {"anger": 0.22, "hurt": 0.16},
    "novelty": {"interest": 0.22, "amusement": 0.06},
    "repair": {"tenderness": 0.12},
}

RELATION_CONNECTION_BASE = {
    "connection": {"affection": 0.018, "trust": 0.010},
    "success": {"affection": 0.006, "trust": 0.012},
}

RELATION_CONFLICT_BASE = {
    "broken_commitment": {"affection": -0.008, "trust": -0.040},
    "disrespect": {"affection": -0.025, "trust": -0.015},
    "boundary_violation": {"affection": -0.020, "trust": -0.030},
}

RELATION_REPAIR_BASE = {
    "acknowledgment": {"affection": 0.000, "trust": 0.004},
    "apology": {"affection": 0.006, "trust": 0.008},
    "explanation": {"affection": 0.000, "trust": 0.004},
    "correction": {"affection": 0.004, "trust": 0.012},
    "follow_through": {"affection": 0.006, "trust": 0.016},
}
```

- 완전 명시·고확신·강도 3·balanced 사건의 첫 반영은 위 base와 일치한다.
- 같은 흔적 반복은 `1 - current_intensity` 포화 저항을 곱한다. 같은 `kind + target_scope + relation_category`가 30분 안에 반복되면 `repeat_weight = max(0.55, 1.0 - 0.15 × prior_count)`를 사용하고 prior_count는 최대 3으로 자른다.
- 반감기는 `very_short=10분`, `short=1시간`, `medium=6시간`, `long=24시간`으로 고정한다.
- 배경축은 `valence=12시간`, `energy=4시간`, `tension=6시간` 반감기로 프리셋 baseline에 회귀한다.
- 자발 변화 cooldown은 6시간, SHA-256 표본 발생 임계값은 0.92, impulse 절댓값 상한은 0.015다.
- 관계 변화의 단일 사건 절댓값 상한은 affection 0.025, trust 0.04다. 모호·대상 불명·외부 사건은 관계 변화가 0이다.

## 공통 작업 규칙

- 모든 Task는 실패 테스트 → 실패 확인 → 최소 구현 → 해당 테스트와 관련 회귀 테스트 통과 → 커밋 순서로 수행한다.
- 테스트·문서·프롬프트 예시는 실제 대화가 아닌 완전히 합성한 중립 문장만 사용한다.
- `mood_state.json`, `memory.json`, `config.json`, 비밀 파일, pytest 임시 폴더는 절대 stage하지 않는다.
- 각 커밋 전 `git diff --cached --check`, UTF-8 without BOM 검사, API 키 패턴과 개인정보 후보 검사를 수행한다.
- 현재 Windows 실행 환경은 pytest `tmp_path` 디렉터리 ACL 때문에 전체 기준선이 session finish에서 `PermissionError`로 종료된다. 코드 assertion 실패로 오인하지 말고, tmp 기반 테스트는 승인된 권한의 셸 또는 정상 ACL 환경에서 재실행해 PASS 증거를 확보한다.

---

### Task 1: V3 도메인 타입과 불변 상태 골격

**Files:**
- Create: `src/ai/mood_engine.py`
- Create: `tests/test_mood_engine.py`

- [ ] **Step 1: 기본 상태·사건 정규화 실패 테스트 작성**

```python
from datetime import datetime, timezone

from src.ai.mood_engine import MoodEvent, new_mood_state, normalize_event


NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)


def synthetic_event_id(label: str) -> str:
    digest = hashlib.sha256(f"ene-mood-test:{label}".encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def test_new_state_has_v3_limits_and_neutral_relationship():
    state = new_mood_state(NOW, "balanced")
    assert state["version"] == 3
    assert state["relationship"] == {"affection": 0.0, "trust": 0.0}
    assert state["active_affects"] == []
    assert state["ruptures"] == []
    assert state["recent_event_ids"] == []


def test_invalid_event_normalizes_to_relationship_safe_neutral():
    event = normalize_event({"event_id": synthetic_event_id("invalid"), "kind": "unknown"}, NOW)
    assert isinstance(event, MoodEvent)
    assert event.kind == "neutral"
    assert event.target_scope == "unknown"
    assert event.intensity == 0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mood_engine.py -q`

Expected: `src.ai.mood_engine` import 실패.

- [ ] **Step 3: 타입·enum·기본 상태·전체 불변조건 최소 구현**

`MoodEvent`는 frozen dataclass로 만들고 원문이나 자유 텍스트 필드를 허용하지 않는다.

```python
@dataclass(frozen=True)
class MoodEvent:
    event_id: str
    occurred_at_utc: datetime
    kind: str
    target_scope: str
    relation_category: str
    intensity: int
    clarity: str
    certainty: str
    controllability: str
    repair_signal: str


def new_mood_state(now_utc: datetime, preset: str) -> dict[str, object]:
    normalized_preset = normalize_preset(preset)
    return {
        "version": 3,
        "revision": 0,
        "preset": normalized_preset,
        "updated_at_utc": format_utc(now_utc),
        "background": dict(PRESET_BASELINES[normalized_preset]),
        "relationship": {"affection": 0.0, "trust": 0.0},
        "active_affects": [],
        "ruptures": [],
        "recent_event_ids": [],
        "spontaneous": {"last_at_utc": None, "seed_revision": 0},
    }
```

`normalize_event(raw, now_utc) -> MoodEvent`와 `validate_state(state) -> dict`도 같은 모듈의 public 함수로 둔다. 전자는 필수 enum·정수 하나라도 잘못되면 `neutral/unknown/none/0/ambiguous/low/low/none`의 관계 안전 사건을 반환하고, 후자는 검증된 deep copy를 반환하며 입력 mapping을 변경하지 않는다.

`active_affects`의 각 원소는 `affect`, `intensity`, `source_kind`, `target_scope`, `relation_category`, `repeat_count`, `last_event_at_utc`, `updated_at_utc`만 가진다. `repeat_count`는 같은 `source_kind + target_scope + relation_category` 사건이 직전 `last_event_at_utc`부터 30분 이내 이어진 횟수이며 0~3으로 clamp한다. 이 제한된 메타데이터에는 원문·요약·memory ID를 넣지 않는다.

`normalize_event`와 `validate_state`는 event ID가 UUIDv4인지 확인한다. `validate_state`는 bool을 숫자로 받지 않고, NaN/Infinity를 거부하며, 배열 상한 5/3/64와 UTC aware 시각을 검증한다. 각 active trace의 `repeat_count`와 `last_event_at_utc`도 검증한다.

- [ ] **Step 4: 단위 테스트 통과 확인**

Run: `python -m pytest tests/test_mood_engine.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/mood_engine.py tests/test_mood_engine.py
git commit -m "feat: define mood engine v3 state"
```

### Task 2: 배경축·정서 흔적 reducer

**Files:**
- Modify: `src/ai/mood_engine.py`
- Modify: `tests/test_mood_engine.py`

- [ ] **Step 1: 골든 변화량과 연속성 실패 테스트 작성**

강도 3, explicit, high, balanced의 `loss`가 sadness 0.24와 background `(-0.05, -0.03, +0.02)`를 만들고, 이어지는 `success`, `novelty` 뒤에도 sadness 흔적이 남는지 검증한다. external 사건이 관계를 바꾸지 않는지도 함께 고정한다.

```python
def test_loss_trace_survives_unrelated_positive_and_plan_events():
    state = new_mood_state(NOW, "balanced")
    state = reduce_mood(state, event("loss", "external", synthetic_event_id("loss")), NOW, "balanced").state
    state = reduce_mood(state, event("success", "external", synthetic_event_id("success")), NOW, "balanced").state
    state = reduce_mood(state, event("novelty", "external", synthetic_event_id("plan")), NOW, "balanced").state
    sadness = next(item for item in state["active_affects"] if item["affect"] == "sadness")
    assert sadness["intensity"] > 0.20
    assert state["relationship"] == {"affection": 0.0, "trust": 0.0}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mood_engine.py -q -k "golden or survives or external"`

Expected: `reduce_mood` 부재로 FAIL.

- [ ] **Step 3: 사건 표·포화·병합·최대 5개 정리 구현**

```python
@dataclass(frozen=True)
class MoodTransition:
    state: dict[str, object]
    applied: bool
    rule_ids: tuple[str, ...]
```

public reducer 계약은 `reduce_mood(previous_state, event, now_utc, preset) -> MoodTransition`으로 고정한다. 구현 순서는 `validate_state → duplicate ID 검사 → advance_time → impact 계산 → background → affect → relationship/rupture → 상한 정리 → revision 증가 → 전체 재검증`이다.

같은 `kind + target_scope + relation_category + affect` 흔적은 감쇠 후 병합한다. 병합 직전 같은 사건군 trace의 `last_event_at_utc`를 확인해 30분 이내면 `repeat_count`를 1 증가시키고, 그 밖이면 0으로 재설정한 뒤 현재 시각을 기록한다. 관계 reducer는 impact 적용 전에 이 값을 읽어 `1.00/0.85/0.70/0.55` 반복 가중치를 사용한다. 5개를 넘으면 `현재 intensity × 남은 반감기 비율`이 가장 작은 항목부터 제거한다. trace가 감쇠·상한 정리로 제거되면 그 사건군의 반복 이력도 사라진다. `recent_event_ids`에 이미 있는 ID면 시간 전진도 다시 하지 않고 완전 no-op을 반환한다.

- [ ] **Step 4: 관련 테스트 통과 확인**

Run: `python -m pytest tests/test_mood_engine.py -q -k "background or affect or external or event_id"`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/mood_engine.py tests/test_mood_engine.py
git commit -m "feat: reduce short term mood events"
```

### Task 3: 장기 관계·균열·단계적 회복

**Files:**
- Modify: `src/ai/mood_engine.py`
- Modify: `tests/test_mood_engine.py`

- [ ] **Step 1: 관계 대상·균열·회복 단계 실패 테스트 작성**

다음을 개별 테스트로 작성한다.

- 외부의 안 좋은 일, 사용자 피로·도움 요청, 정당한 거절은 affection/trust 불변.
- 명확한 `boundary_violation` conflict만 해당 균열 생성.
- acknowledgment, apology, explanation의 서로 다른 감소량.
- correction/follow_through가 서로 다른 두 event ID에서만 증거 2회가 됨.
- 같은 category 재발 시 증거 0, repeat 증가.
- 관련 없는 긍정 대화는 repair evidence가 아님.

```python
def test_rupture_resolves_only_after_two_qualifying_followups():
    state = state_with_rupture("broken_commitment", severity=0.18)
    state = apply_repair(state, "correction", synthetic_event_id("fix-1"))
    assert state["ruptures"][0]["repair_stage"] == "observing"
    assert state["ruptures"][0]["repair_evidence_count"] == 1
    state = apply_repair(state, "follow_through", synthetic_event_id("fix-2"))
    assert state["ruptures"] == []


def test_relationship_golden_deltas_are_nonzero_and_axis_specific():
    connected = reduce_mood(
        new_mood_state(NOW, "balanced"),
        relationship_event("connection", relation_category="none"),
        NOW,
        "balanced",
    ).state
    assert connected["relationship"]["affection"] == pytest.approx(0.018)
    assert connected["relationship"]["trust"] == pytest.approx(0.010)

    broken = reduce_mood(
        new_mood_state(NOW, "balanced"),
        relationship_event("conflict", relation_category="broken_commitment"),
        NOW,
        "balanced",
    ).state
    assert broken["relationship"]["affection"] == pytest.approx(-0.008)
    assert broken["relationship"]["trust"] == pytest.approx(-0.040)

    repaired = reduce_mood(
        new_mood_state(NOW, "balanced"),
        relationship_event("repair", repair_signal="follow_through"),
        NOW,
        "balanced",
    ).state
    assert repaired["relationship"]["affection"] == pytest.approx(0.006)
    assert repaired["relationship"]["trust"] == pytest.approx(0.016)


def test_consecutive_relationship_events_apply_bounded_repeat_weights():
    state = new_mood_state(NOW, "balanced")
    for index, weight in enumerate((1.00, 0.85, 0.70, 0.55)):
        before = state["relationship"]["affection"]
        transition = reduce_mood(
            state,
            relationship_event("connection", event_id=synthetic_event_id(f"repeat-{index}")),
            NOW + timedelta(minutes=5 * index),
            "balanced",
        )
        state = transition.state
        expected_increment = 0.018 * weight * (1.0 - abs(before))
        assert state["relationship"]["affection"] - before == pytest.approx(expected_increment)
        trace = next(item for item in state["active_affects"] if item["source_kind"] == "connection")
        assert trace["repeat_count"] == min(index, 3)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mood_engine.py -q -k "relationship or rupture or repair"`

Expected: 관계 전이 assertion FAIL.

- [ ] **Step 3: 관계 변화 상한과 회복 상태 머신 구현**

관계 변화는 `target_scope in {ene, relationship}`, `clarity != ambiguous`, `certainty != low`에서만 허용한다. 완전 명시·고확신·강도 3·balanced·중립 시작 상태의 첫 사건은 문서 상단의 golden base를 그대로 적용한다. 그 외에는 intensity·clarity·certainty·preset 계수, 관계값의 포화 저항 `1 - abs(current_value)`, 단일 사건 상한을 곱한 뒤 `[-1, 1]`로 clamp한다. 같은 `kind + target_scope + relation_category`가 30분 안에 반복되면 active trace의 `repeat_count=0/1/2/3`에 대해 `1.00/0.85/0.70/0.55`를 적용한다. rupture는 category별 한 개로 병합하며 `category`, `severity`, `heat`, `repair_stage`, `repeat_count`, `repair_evidence_count`, `last_negative_at_utc`, `updated_at_utc`만 저장한다. 해결 기준은 설계대로 `severity <= 0.12`와 후속 증거 2회이며, 가벼운 사건은 사과 후 `severity <= 0.08`이면 즉시 제거한다.

- [ ] **Step 4: 관계 테스트 통과 확인**

Run: `python -m pytest tests/test_mood_engine.py -q -k "relationship or rupture or repair"`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/mood_engine.py tests/test_mood_engine.py
git commit -m "feat: add relationship rupture recovery"
```

### Task 4: 시간 감쇠·결정론적 자발 변화·파생 snapshot

**Files:**
- Modify: `src/ai/mood_engine.py`
- Modify: `tests/test_mood_engine.py`

- [ ] **Step 1: 동일 입력 결정성과 파생값 실패 테스트 작성**

```python
def test_advance_time_is_deterministic_without_rng():
    state = state_with_affects()
    first = advance_time(state, NOW + timedelta(hours=7), "balanced")
    second = advance_time(state, NOW + timedelta(hours=7), "balanced")
    assert first == second


def test_snapshot_derives_optional_secondary_with_hysteresis():
    snapshot = derive_snapshot(state_with_affects(anger=0.52, hurt=0.49))
    assert snapshot["primary_emotion"] == "anger"
    assert snapshot["secondary_emotion"] == "hurt"


def test_snapshot_hysteresis_uses_nonpersistent_previous_primary():
    state = state_with_affects(anger=0.49, hurt=0.52)
    without_history = derive_snapshot(state, previous_primary=None)
    with_history = derive_snapshot(state, previous_primary="anger")
    assert without_history["primary_emotion"] == "hurt"
    assert with_history["primary_emotion"] == "anger"
```

프리셋별 반응 크기만 달라지고 사건 방향은 동일한지, 자발 변화가 relationship/ruptures/stance를 건드리지 않는지도 검증한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mood_engine.py -q -k "advance_time or snapshot or spontaneous or preset"`

Expected: 함수 부재 또는 assertion FAIL.

- [ ] **Step 3: 지수 감쇠·SHA-256 impulse·파생 로직 구현**

public 계약은 다음 세 개로 고정한다.

```text
advance_time(state, now_utc, preset) -> MoodTransition
derive_snapshot(state, previous_primary=None) -> dict[str, object]
derive_behavior_guidance(state, language) -> tuple[str, ...]
```

SHA-256 입력은 정확히 `mood-v3|{preset}|{seed_revision}|{utc_bucket}` UTF-8 bytes를 사용한다. Python `hash()`와 외부 RNG를 금지한다. 주 감정 threshold는 0.16, 보조 감정은 0.14 이상이면서 주 감정의 75% 이상일 때만 선택한다. `previous_primary`는 `MoodManager`가 메모리에만 보관하는 표시 cache이며 파일에는 저장하지 않는다. 직전 주 감정이 새 후보보다 0.04 이내면 유지해 떨림을 막고, 재시작 첫 snapshot은 history 없이 순수 점수로 정한다.

- [ ] **Step 4: 전체 engine 테스트 통과 확인**

Run: `python -m pytest tests/test_mood_engine.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/mood_engine.py tests/test_mood_engine.py
git commit -m "feat: derive deterministic mood snapshots"
```

### Task 5: MoodManager V3 저장·마이그레이션·facade

**Files:**
- Modify: `src/ai/mood_manager.py`
- Modify: `src/core/app.py`
- Modify: `.gitignore`
- Modify: `tests/test_mood_manager.py`
- Modify: `tests/test_memory_encoding.py`
- Modify: `tests/test_app_llm_bootstrap.py`

- [ ] **Step 1: V2→V3·손상·원자 저장·순수 snapshot 실패 테스트 작성**

테스트는 다음 계약을 고정한다.

- UTF-8 BOM V2 로드 가능, V3 저장은 BOM 없음.
- V2 bond는 affection으로만 이동하고 trust는 0.
- V2 recent_events/temporary_state로 rupture를 창작하지 않음.
- V2 naive `updated_at`은 주입한 `local_timezone`으로 해석한 뒤 UTC anchor로 변환.
- 최초 변환 전 `.v2.bak`을 같은 디렉터리 temp+flush+`os.replace`로 1회 생성하고, 백업 성공 뒤에만 V3 원본 교체. 백업 실패 시 원본 bytes 보존.
- 알 수 없는 미래 version과 손상 JSON은 원본 무수정·자동 저장 금지, 각각 `future_version`·`corrupt_state` 고정 코드와 `write_locked=True`.
- 읽기 실패와 migration 실패는 `state_read_failed`·`migration_failed`로 구분하고 자동 저장 금지.
- 저장 실패 시 `manager.state`가 이전 상태 그대로.
- `get_snapshot()` 연속 호출은 state bytes/revision을 바꾸지 않음.
- 같은 event ID 재적용 no-op.
- `enable_mood_system=false`이면 앱이 manager를 생성하지 않아 상태 파일 load/migration 호출 0회.
- 명시적 `reset_state()` 전에는 write lock 상태에서 apply/advance가 파일을 덮어쓰지 않으며, reset은 원본을 별도 복구 backup으로 보존한 뒤 새 V3를 저장.
- 기본 파일명의 migration·recovery backup과 orphan temp가 git에 잡히지 않도록 `.gitignore`에 `mood_state.json.*.bak`, `mood_state.json.*.tmp` 추가.

```python
def test_snapshot_is_read_only(tmp_path):
    manager = MoodManager(tmp_path / "mood_state.json", settings=Settings(), clock=fixed_clock)
    before = copy.deepcopy(manager.state)
    assert manager.get_snapshot() == manager.get_snapshot()
    assert manager.state == before
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mood_manager.py tests/test_memory_encoding.py tests/test_app_llm_bootstrap.py -q`

Expected: V3 version/migration/snapshot assertion FAIL. 이 호스트에서 `tmp_path` ACL 오류가 나면 승인된 정상 권한 환경에서 같은 명령을 다시 실행한다.

- [ ] **Step 3: facade public API 교체**

아래 API만 유지·추가하고 기존 delta hint 계산은 제거한다.

```text
apply_event(event_id, analysis, occurred_at_utc=None) -> snapshot
preview_event(event_id, analysis, occurred_at_utc=None) -> snapshot  # 저장·revision 변경 없음
advance_time_and_save(now_utc=None) -> snapshot
get_snapshot() -> snapshot
build_context_block(language=None) -> str
get_load_status() -> {error_code, write_locked}
reset_state(now_utc=None) -> snapshot  # 명시적 사용자 동작에서만 호출
on_user_message(text, image_count=0) -> unchanged snapshot  # Task 9까지 호환 no-op
on_user_analysis(analysis, event_id=None, occurred_at_utc=None) -> snapshot  # ID 누락 시 호환 no-op
on_head_pat() -> snapshot
on_assistant_emotion(emotion) -> unchanged snapshot  # 한 릴리스 호환 no-op
```

생성자는 `clock`과 `local_timezone`을 주입받는다. `preview_event`는 현재 state deep copy에 동일 reducer를 실행하되 파일·manager state·volatile hysteresis cache를 바꾸지 않는다. Task 9에서 호출부를 교체하기 전까지 `on_user_message`와 event ID가 없는 기존 `on_user_analysis(analysis)`는 모두 deprecated 호환 no-op다. 즉 submit, provider 실패, 파싱 실패, 취소만으로는 시간 감쇠·revision·파일 bytes가 바뀌지 않는다. ID가 명시된 `on_user_analysis`만 `apply_event`로 위임하며, 신규 브리지는 두 adapter를 호출하지 않는다. `advance_time_and_save`는 명시 호출 또는 Task 9의 성공한 최종 응답 경계에서만 사용한다. snapshot은 새 nested 값과 기존 `current_mood`, `temporary_state`, `valence`, `energy`, `bond=affection`, `stress=tension`, `expression_traits` alias를 함께 반환한다. 비영속 `_last_primary_emotion` cache는 snapshot 파생에만 사용한다.

호환 테스트에는 기존 bridge submit과 provider 실패·파싱 실패·취소를 각각 실행한 뒤 manager state, revision, 상태 파일 bytes가 모두 동일한지 확인하는 회귀 테스트를 포함한다.

`src/core/app.py::_init_mood_manager`는 `enable_mood_system`을 먼저 확인하고 false이면 경로 해석이나 `MoodManager(...)` 호출 없이 `self.mood_manager=None`을 설정한다.

- [ ] **Step 4: manager와 기존 bridge 호환 테스트 통과 확인**

Run: `python -m pytest tests/test_mood_manager.py tests/test_memory_encoding.py tests/test_bridge_mood_flow.py tests/test_app_llm_bootstrap.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/mood_manager.py src/core/app.py .gitignore tests/test_mood_manager.py tests/test_memory_encoding.py tests/test_app_llm_bootstrap.py
git commit -m "feat: migrate mood manager to v3"
```

### Task 6: 11개 tuple·12인자 signal 소비자 호환 준비

**Files:**
- Modify: `src/core/bridge_workers.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Modify: `tests/test_bridge_worker_multimodal_capability.py`
- Modify: `tests/test_bridge_mood_flow.py`
- Modify: `tests/test_bridge_response_metadata.py`
- Modify: `tests/test_bridge_goals.py`
- Modify: `tests/test_bridge_promise_reminders.py`
- Modify: `tests/test_gesture_response_flow.py`
- Modify: `tests/test_proactive_conversation_parsing.py`
- Modify: `tests/test_task14b_worker_shutdown.py`

- [ ] **Step 1: 구형/신형 tuple과 signal handler 호환 실패 테스트 작성**

producer는 아직 10개 tuple을 내보내는 상태에서 consumer를 먼저 준비한다. `AIWorker._normalize_response_payload`는 4~10개 구형 tuple과 11개 신형 tuple을 모두 11개로 반환하고, 구형 입력의 마지막 값은 `None`이어야 한다. 이 함수의 shape가 즉시 바뀌므로 goal·promise·gesture·proactive를 포함해 tuple 위치를 직접 assert하거나 unpack하는 모든 consumer fixture를 이 Task에서 한꺼번에 11개로 바꾼다. Qt `response_ready`는 mood JSON 문자열을 마지막 12번째 인자로 emit한다. `_handle_response_ready(..., mood_analysis_payload="")`는 선택 인자를 받아 아직 상태에 적용하지 않고 안전하게 무시한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_mood_flow.py tests/test_bridge_response_metadata.py tests/test_bridge_goals.py tests/test_bridge_promise_reminders.py tests/test_gesture_response_flow.py tests/test_proactive_conversation_parsing.py tests/test_task14b_worker_shutdown.py -q`

Expected: worker tuple 길이 또는 signal/handler 인자 수 assertion FAIL.

- [ ] **Step 3: consumer-first 호환 adapter 구현**

`_normalize_response_payload`는 11개 입력을 그대로 반환하고 10개 이하 입력에는 끝에 `None`을 붙인다. worker는 `json.dumps(mood_analysis, ensure_ascii=False)` 또는 빈 문자열을 12번째로 emit한다. bridge handler는 optional 문자열을 파싱하지 않고 보관하지도 않는다. 이 Task가 끝난 시점에도 기존 10개 producer와 전체 대화가 정상 동작해야 한다.

- [ ] **Step 4: 소비자 호환과 핵심 bridge 회귀 확인**

Run: `python -m pytest tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_mood_flow.py tests/test_bridge_response_metadata.py tests/test_bridge_goals.py tests/test_bridge_promise_reminders.py tests/test_gesture_response_flow.py tests/test_proactive_conversation_parsing.py tests/test_task14b_worker_shutdown.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/bridge_workers.py src/core/bridge_mixins/chat_flow.py tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_mood_flow.py tests/test_bridge_response_metadata.py tests/test_bridge_goals.py tests/test_bridge_promise_reminders.py tests/test_gesture_response_flow.py tests/test_proactive_conversation_parsing.py tests/test_task14b_worker_shutdown.py
git commit -m "refactor: prepare mood analysis transport"
```

### Task 7: nullable MoodTurnAnalysis 계약과 producer 전환

**Files:**
- Modify: `src/ai/analysis_prompt.py`
- Modify: `src/ai/response_contract.py`
- Modify: `src/ai/response_envelope.py`
- Modify: `src/ai/response_parser.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_common.py`
- Modify: `tests/structured_response_fixtures.py`
- Modify: `tests/http_structured_fixtures.py`
- Modify: `tests/gemini_structured_fixtures.py`
- Modify: `tests/test_response_envelope.py`
- Modify: `tests/test_response_contract.py`
- Modify: `tests/test_response_parser_feature_toggles.py`
- Modify: `tests/test_response_parsing.py`
- Modify: `tests/test_llm_provider.py`
- Modify: `tests/test_gemini_structured_outputs.py`
- Modify: `tests/test_gemini_empty_response.py`
- Modify: `tests/test_http_llm_structured_outputs.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_http_llm_clients_multimodal_history.py`
- Modify: `tests/test_http_llm_clients_openai.py`
- Modify: `tests/test_promise_reminder_parsing.py`
- Modify: `tests/test_goal_update_parsing.py`
- Modify: `tests/test_bridge_proactive_conversation.py`
- Modify: `tests/test_gesture_response_flow.py`
- Modify: `tests/test_proactive_conversation_parsing.py`

- [ ] **Step 1: 4개 토글 조합과 strict 필드 실패 테스트 작성**

`ResponseRequirements`에 `enable_mood`와 `enable_mood_analysis`를 추가하고 다음을 테스트한다.

```python
@pytest.mark.parametrize(
    ("mood", "analysis", "expected_object"),
    [(False, False, False), (False, True, False), (True, False, False), (True, True, True)],
)
def test_mood_analysis_toggle_matrix(mood, analysis, expected_object):
    settings = type(
        "Settings",
        (),
        {"config": {"enable_mood_system": mood, "enable_response_analysis": analysis}},
    )()
    requirements = build_response_requirements(settings)
    assert requirements.enable_mood is mood
    assert requirements.enable_mood_analysis is expected_object
```

활성 조합에서는 event 8필드, `risk_class`, `proposed_stance`가 정확히 있어야 한다. `event_id`, 추가 필드, 자유 텍스트 reason, 잘못된 enum은 strict 무효다. 비활성 조합에서는 JSON `null`만 유효하다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_response_envelope.py tests/test_response_contract.py tests/test_response_parser_feature_toggles.py tests/test_response_parsing.py tests/test_llm_provider.py -q`

Expected: `mood_analysis` schema/tuple 필드 부재로 FAIL.

- [ ] **Step 3: schema·prompt·legacy block 최소 구현**

canonical schema에는 required nullable object를 추가한다.

```python
MOOD_EVENT_FIELDS = (
    "kind", "target_scope", "relation_category", "intensity",
    "clarity", "certainty", "controllability", "repair_signal",
)

MOOD_ANALYSIS_SCHEMA = {
    "anyOf": [
        _strict_object({
            "event": _strict_object({
                "kind": {"type": "string", "enum": list(EVENT_KINDS)},
                "target_scope": {"type": "string", "enum": list(TARGET_SCOPES)},
                "relation_category": {"type": "string", "enum": list(RELATION_CATEGORIES)},
                "intensity": {"type": "integer", "enum": [0, 1, 2, 3]},
                "clarity": {"type": "string", "enum": list(CLARITIES)},
                "certainty": {"type": "string", "enum": list(CERTAINTIES)},
                "controllability": {"type": "string", "enum": list(CONTROLLABILITIES)},
                "repair_signal": {"type": "string", "enum": list(REPAIR_SIGNALS)},
            }),
            "risk_class": {"type": "string", "enum": ["none", "concern", "urgent"]},
            "proposed_stance": {
                "type": "string",
                "enum": ["proactive", "cooperative", "brief", "limited", "distance", "decline", "boundary"],
            },
        }),
        {"type": "null"},
    ]
}
```

`LLM_RESPONSE_TUPLE`은 Task 6에서 준비한 consumer에 맞춰 마지막 11번째 값으로 `dict[str, object] | None`을 추가한다. 모든 provider fixture와 tuple shape assertion을 같은 커밋에서 전환해 중간에 전체 테스트를 깨뜨리지 않는다. `test_goal_update_parsing.py`와 `test_bridge_proactive_conversation.py`의 producer 결과 assertion을 이 단계에서 바꾸고, consumer와 producer 검증을 함께 가진 `test_gesture_response_flow.py`, `test_proactive_conversation_parsing.py`도 Task 6에 이어 다시 수정한다.

strict decoder는 `_normalize_mood_analysis(value, requirements) -> (normalized, fatal_error)`처럼 별도 결과를 반환한다. `enable_mood_analysis=true`에서 null·누락·잘못된 enum·추가 필드는 `fatal_error=True`로 전체 `payload=None`을 만들고 pipeline의 기존 1회 재생성 경로를 탄다. `enable_mood_analysis=false`에서 object가 오거나 null이 아닌 경우도 strict 전체 무효다. 다른 `invalid_paths`의 기존 부분 회수 정책은 바꾸지 않는다.

레거시 모드에는 `[mood_analysis]`와 `[/mood_analysis]` 사이에 key=value 줄만 넣는 전용 블록을 사용한다. 기능이 활성인데 블록이 없거나 잘못되면 다음 완전한 관계 안전 object를 반환한다: neutral, unknown, none, intensity 0, ambiguous, low certainty, low controllability, repair none, risk none, stance cooperative. 기능이 비활성이면 항상 None이다. 기존 `analysis`의 delta hint 필드는 한 릴리스 동안 출력 schema 호환용으로 남기되 MoodManager가 무시한다.

- [ ] **Step 4: 응답 계약 테스트 통과 확인**

Run: `python -m pytest tests/test_response_envelope.py tests/test_response_contract.py tests/test_response_parser_feature_toggles.py tests/test_response_parsing.py tests/test_llm_provider.py tests/test_gemini_structured_outputs.py tests/test_gemini_empty_response.py tests/test_http_llm_structured_outputs.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_multimodal_history.py tests/test_http_llm_clients_openai.py tests/test_promise_reminder_parsing.py tests/test_goal_update_parsing.py tests/test_bridge_proactive_conversation.py tests/test_gesture_response_flow.py tests/test_proactive_conversation_parsing.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/analysis_prompt.py src/ai/response_contract.py src/ai/response_envelope.py src/ai/response_parser.py src/ai/llm_provider.py src/ai/llm_client.py src/ai/http_llm_common.py tests/structured_response_fixtures.py tests/http_structured_fixtures.py tests/gemini_structured_fixtures.py tests/test_response_envelope.py tests/test_response_contract.py tests/test_response_parser_feature_toggles.py tests/test_response_parsing.py tests/test_llm_provider.py tests/test_gemini_structured_outputs.py tests/test_gemini_empty_response.py tests/test_http_llm_structured_outputs.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_multimodal_history.py tests/test_http_llm_clients_openai.py tests/test_promise_reminder_parsing.py tests/test_goal_update_parsing.py tests/test_bridge_proactive_conversation.py tests/test_gesture_response_flow.py tests/test_proactive_conversation_parsing.py
git commit -m "feat: add mood turn analysis contract"
```

### Task 8: 행동 태도 정책·urgent footer·1회 재생성

**Files:**
- Create: `src/ai/mood_policy.py`
- Create: `tests/test_mood_policy.py`
- Modify: `src/ai/response_pipeline.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_common.py`
- Modify: `tests/test_structured_response_pipeline.py`
- Modify: `tests/test_structured_response_integration.py`
- Modify: `tests/test_gemini_structured_outputs.py`
- Modify: `tests/test_http_llm_structured_outputs.py`

- [ ] **Step 1: 태도 범위와 urgent 보장 실패 테스트 작성**

```python
def test_urgent_never_allows_distance_decline_or_boundary():
    allowed = allowed_stances(snapshot_with_rupture(), risk_class="urgent")
    assert "cooperative" in allowed
    assert not ({"distance", "decline", "boundary"} & allowed)


def test_urgent_footer_is_localized_and_idempotent():
    once = apply_urgent_footer("짧은 답변", "ko")
    assert apply_urgent_footer(once, "ko") == once
    assert "응급" in once or "위험" in once


def test_policy_retry_changes_the_second_provider_prompt():
    execute_final_response(requester=capturing_requester(), mood_snapshot_provider=neutral_snapshot)
    assert captured_prompts[1] != captured_prompts[0]
    assert "mood_stance_not_allowed" in captured_prompts[1]
```

일반 상태에서 high rupture heat는 `limited`, `distance`, `boundary`, 선택 요청의 `decline`을 허용하고, 응급·중지·취소·권한 철회·위험 작업 확인에는 영향을 주지 않는 시나리오를 추가한다.

현재 사건 preview 경계도 테스트한다. 명확한 relation conflict를 아직 저장하지 않은 상태에서 `MoodManager.preview_event`가 만든 snapshot은 boundary를 허용해야 하며, preview 전후 manager state/revision/file bytes는 같아야 한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mood_policy.py tests/test_structured_response_pipeline.py tests/test_gemini_structured_outputs.py tests/test_http_llm_structured_outputs.py -q`

Expected: policy 모듈/재생성 phase 부재로 FAIL.

- [ ] **Step 3: 구조화 validator와 pipeline hook 구현**

```python
@dataclass(frozen=True)
class MoodPolicyDecision:
    action: Literal["accept", "retry", "clamp", "urgent_fallback"]
    payload: LLM_RESPONSE_TUPLE
    error_code: str = ""
```

validator public 계약은 `validate_mood_policy(payload, snapshot, language, retry_used=False) -> MoodPolicyDecision`으로 고정한다. `payload[-1] is None`이면 accept, urgent에서 금지 stance면 첫 호출 retry/두 번째 urgent_fallback, 일반 불허 stance면 첫 호출 retry/두 번째에는 `default_stance(snapshot)`으로 구조화 값만 clamp한다.

`execute_final_response`에는 아래 두 optional callback을 추가한다.

```python
mood_snapshot_provider: Callable[[], dict[str, object]] | None = None
mood_preview: Callable[[dict[str, object]], dict[str, object]] | None = None
```

pipeline은 payload에 mood analysis object가 있으면 우선 `mood_preview(analysis)`를 사용하고, callback이 없거나 analysis가 null이면 `mood_snapshot_provider()`의 현재 저장 snapshot을 사용한다. 둘 다 없을 때만 고정 neutral snapshot을 사용하며 관계 사건을 추측하지 않는다. Gemini와 모든 HTTP client는 자신의 manager에서 두 callback을 공급한다. 실제 event ID·시각 캡처와 전달은 Task 9에서 연결하며, 여기서는 합성 callback으로 저장 없는 preview가 reducer와 동일한 결과를 내는지 검증한다.

`ResponseAttempt`에 공개 문장 대신 `policy_error_code`만 추가한다. 첫 태도 불일치는 `phase="policy_regenerate"`로 한 번 재생성한다. `build_mood_policy_retry_appendix(error_code, language)`는 사용자 입력이나 상태 수치를 포함하지 않는 고정·현지화된 지침을 만들고, Gemini와 HTTP 공통 requester는 두 번째 요청 prompt에 이를 실제 append한다. 테스트 requester는 두 요청의 prompt를 캡처해 두 번째가 첫 번째와 다르고 해당 오류 코드와 허용 태도 지침이 들어갔는지 확인한다. 정책 재시도는 최대 1회다. 두 번째 일반 불일치는 mood-specific stance만 안전한 기본값으로 clamp하고 표시 답변은 유지한다. 두 번째 urgent 불일치는 고정된 짧은 안전 응답+footer로 교체한다. urgent footer는 모델 답변에 항상 append하며 상태별 전문 처치라고 주장하지 않는다.

자유 형식 답변의 비조작성은 런타임 문자열 차단으로 구현하지 않는다. 프롬프트 제약과 Task 11의 합성 의미 평가 fixture로 검증한다.

- [ ] **Step 4: 정책·pipeline 테스트 통과 확인**

Run: `python -m pytest tests/test_mood_policy.py tests/test_structured_response_pipeline.py tests/test_structured_response_integration.py tests/test_gemini_structured_outputs.py tests/test_http_llm_structured_outputs.py tests/test_mood_manager.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/mood_policy.py src/ai/response_pipeline.py src/ai/llm_client.py src/ai/http_llm_common.py tests/test_mood_policy.py tests/test_structured_response_pipeline.py tests/test_structured_response_integration.py tests/test_gemini_structured_outputs.py tests/test_http_llm_structured_outputs.py tests/test_mood_manager.py
git commit -m "feat: enforce mood response policy"
```

### Task 9: 브리지 사건 lifecycle과 정확히 한 번 적용

**Files:**
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Modify: `src/core/bridge_mixins/attachments.py`
- Modify: `src/core/bridge_mixins/obsidian.py`
- Modify: `src/core/bridge_mixins/mood.py`
- Modify: `src/core/bridge_workers.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_openai.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `src/ai/http_llm_ollama.py`
- Modify: `src/ai/http_llm_custom_providers.py`
- Modify: `tests/test_bridge_mood_flow.py`
- Modify: `tests/test_bridge_reply_lifecycle.py`
- Modify: `tests/test_bridge_request_pending.py`
- Modify: `tests/test_bridge_attachment_slots.py`
- Modify: `tests/test_obsidian_bridge_cache.py`
- Modify: `tests/test_bridge_worker_multimodal_capability.py`
- Modify: `tests/test_llm_provider.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_http_llm_clients_multimodal_history.py`
- Modify: `tests/test_http_llm_clients_openai.py`
- Modify: `tests/test_gemini_structured_outputs.py`

- [ ] **Step 1: UUID·리롤·편집·실패 경계 실패 테스트 작성**

다음을 검증한다.

- 일반 텍스트·이미지 최종 채팅은 submit 시 UUIDv4 하나를 `_last_request_payload["mood_event_id"]`에 저장.
- 응답 성공 시 해당 ID와 mood_analysis로 `apply_event` 한 번.
- 중복 callback, 리롤, 수정은 같은 ID라 no-op.
- 새 메시지는 새 ID.
- `/diary`, `/note`, one-shot, provider 실패, 파싱 실패, 취소는 apply 0회.
- `on_user_message` 선적용과 `on_assistant_emotion` 상태 적용은 0회.
- worker signal 연결 시 event ID와 발생 시각을 `partial`에 캡처하며, `_last_request_payload`가 교체된 stale callback은 적용 0회.
- mood JSON에는 ID가 없고, handler는 JSON과 ID를 비교하려 하지 않음. callback에 캡처된 ID와 현재 operation 소유 ID만 비교.
- 응답 분석 off의 성공한 최종 채팅은 의미 사건 없이 `advance_time_and_save` 1회.

```python
def test_reroll_and_edit_reuse_event_id_without_second_mood_transition():
    first_id = bridge._last_request_payload["mood_event_id"]
    first_time = bridge._last_request_payload["mood_occurred_at"]
    bridge.reroll_last_response()
    assert bridge._last_request_payload["mood_event_id"] == first_id
    assert bridge._last_request_payload["mood_occurred_at"] == first_time
    bridge.edit_last_user_message("합성된 수정 문장")
    assert bridge._last_request_payload["mood_event_id"] == first_id
    assert bridge._last_request_payload["mood_occurred_at"] == first_time
    assert bridge.mood_manager.applied_ids == [first_id]


def test_stale_callback_cannot_apply_replaced_request_event():
    old_id = bridge._last_request_payload["mood_event_id"]
    bridge._last_request_payload = {"mood_event_id": str(uuid.uuid4())}
    bridge._handle_response_ready(
        "합성 답변", "normal", "", mood_analysis_payload=valid_mood_json(),
        expected_mood_event_id=old_id,
        expected_mood_occurred_at="2099-01-01T00:00:00+00:00",
    )
    assert bridge.mood_manager.applied_ids == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_bridge_mood_flow.py tests/test_bridge_reply_lifecycle.py tests/test_bridge_request_pending.py tests/test_bridge_attachment_slots.py tests/test_obsidian_bridge_cache.py tests/test_llm_provider.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_multimodal_history.py tests/test_http_llm_clients_openai.py tests/test_gemini_structured_outputs.py -q`

Expected: 선적용 call 목록과 event ID assertion FAIL.

- [ ] **Step 3: event ID 소유권과 최종 적용 구현**

submit 시 `mood_event_id=str(uuid.uuid4())`와 `mood_occurred_at`을 canonical UTC ISO 문자열 `YYYY-MM-DDTHH:MM:SS+00:00`으로 `_last_request_payload`에 함께 저장한다. 같은 문자열을 worker와 manager 경계까지 유지하고 `MoodManager`만 aware `datetime`으로 parse한다. `_start_ai_worker`는 두 값을 `AIWorker` 생성자에 전달하고 signal 연결 `partial`에도 `expected_mood_event_id`, `expected_mood_occurred_at`으로 캡처한다.

`LLMProvider` protocol과 Gemini·OpenAI·Anthropic·Ollama·custom provider의 최종 text/image send signature에는 다음 keyword-only 인자를 동일하게 추가한다.

```python
mood_event_context: Mapping[str, str] | None = None
# keys: event_id, occurred_at_utc
```

AIWorker는 final text/image 호출에만 새 dict를 per-call 인자로 전달하고, client는 그 호출 안에서만 Task 8의 `mood_preview` closure를 구성한다. provider/client instance field나 공유 mutable state에는 context를 저장하지 않는다. 병렬·취소·stale callback에서도 다른 요청의 context를 읽을 수 없어야 하며, `/diary`, `/note`, one-shot에는 `None`을 전달한다. provider parity 테스트는 모든 구현이 optional keyword를 받고 preview와 응답 signal까지 같은 두 문자열을 보존하는지 확인한다.

`_handle_response_ready`는 mood JSON을 strict dict로 읽고, 캡처된 expected ID가 현재 normal operation과 `_last_request_payload`가 소유한 ID와 일치할 때만 `apply_event(expected_id, analysis, expected_time)`를 호출한다. mood JSON 자체에는 ID를 넣지 않는다. stale worker callback은 기존 operation gate와 이 소유권 검사 양쪽에서 폐기한다. mood 상태 저장이 실패하면 응답 자체는 표시하되 이전 mood state를 유지하고 집계 오류 코드만 로그에 남긴다.

`attachments.py`, `obsidian.py`, `chat_flow.py`의 기존 `on_user_message` 호출을 제거한다. `on_head_pat`은 사용자가 직접 한 별도 구조화 상호작용이므로 자체 UUID를 발급해 reducer 사건으로 남기되 원문은 저장하지 않는다.

- [ ] **Step 4: 브리지 lifecycle 테스트 통과 확인**

Run: `python -m pytest tests/test_bridge_mood_flow.py tests/test_bridge_reply_lifecycle.py tests/test_bridge_request_pending.py tests/test_bridge_attachment_slots.py tests/test_obsidian_bridge_cache.py tests/test_bridge_worker_multimodal_capability.py tests/test_mood_policy.py tests/test_llm_provider.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_multimodal_history.py tests/test_http_llm_clients_openai.py tests/test_gemini_structured_outputs.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/bridge_mixins/chat_flow.py src/core/bridge_mixins/attachments.py src/core/bridge_mixins/obsidian.py src/core/bridge_mixins/mood.py src/core/bridge_workers.py src/ai/llm_provider.py src/ai/llm_client.py src/ai/http_llm_common.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py src/ai/http_llm_ollama.py src/ai/http_llm_custom_providers.py tests/test_bridge_mood_flow.py tests/test_bridge_reply_lifecycle.py tests/test_bridge_request_pending.py tests/test_bridge_attachment_slots.py tests/test_obsidian_bridge_cache.py tests/test_bridge_worker_multimodal_capability.py tests/test_mood_policy.py tests/test_llm_provider.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_multimodal_history.py tests/test_http_llm_clients_openai.py tests/test_gemini_structured_outputs.py
git commit -m "feat: apply mood events exactly once"
```

### Task 10: 설정 토글·프리셋·앱 로드 경계

**Files:**
- Modify: `src/core/settings.py`
- Modify: `src/ui/settings_dialog.py`
- Modify: `src/ui/settings_dialog_values.py`
- Modify: `src/ui/settings_tabs/behavior_tab.py`
- Modify: `src/core/overlay_window.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Modify: `tests/test_settings.py`
- Modify: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: 4개 토글 조합과 레거시 프리셋 실패 테스트 작성**

Task 5의 비활성 manager 테스트를 회귀로 유지하면서, 응답 분석이 꺼져도 기분 버튼과 기존 snapshot은 사용할 수 있는지 UI 조합을 검증한다. 설정 UI에는 `기분 기능 사용` 토글과 `차분함/균형형/감정 풍부형` combo를 추가한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_settings.py tests/test_app_llm_bootstrap.py tests/test_ui_i18n_smoke.py -q`

Expected: 새 setting widget/key 또는 앱 비로드 assertion FAIL.

- [ ] **Step 3: 설정 기본값·정규화·UI 구현**

기본값은 다음과 같이 바꾼다.

```python
"enable_mood_system": True,
"mood_personality_profile": "balanced",
```

로드 시 기존 세 값과 새 세 값만 허용하고 고정 매핑한다. 기존 `mood_update_speed`와 `mood_decay_per_hour`는 V3 내부 계수와 충돌하므로 읽기 호환만 유지하고 새 UI에서는 숨긴다. overlay의 mood 버튼 표시 여부는 `enable_response_analysis`가 아니라 `enable_mood_system && show_mood_toggle_button`으로 계산한다.

- [ ] **Step 4: 설정·UI 테스트 통과 확인**

Run: `python -m pytest tests/test_settings.py tests/test_app_llm_bootstrap.py tests/test_ui_i18n_smoke.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/settings.py src/ui/settings_dialog.py src/ui/settings_dialog_values.py src/ui/settings_tabs/behavior_tab.py src/core/overlay_window.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_settings.py tests/test_ui_i18n_smoke.py
git commit -m "feat: expose mood v3 settings"
```

### Task 11: context·UI 호환·기억 경계·제품 시나리오

**Files:**
- Modify: `src/ai/memory_context_builder.py`
- Modify: `src/core/bridge_mixins/mood.py`
- Modify: `assets/web/index.html`
- Modify: `assets/web/runtime_mood_obsidian.js`
- Modify: `assets/web/runtime_ui_strings.js`
- Modify: `assets/web/runtime_bridge.js`
- Modify: `tests/test_bridge_context_compaction.py`
- Modify: `tests/test_bridge_mood_flow.py`
- Modify: `tests/test_chat_ui_assets.py`
- Modify: `tests/test_ui_i18n_smoke.py`
- Create: `tests/test_mood_v3_scenarios.py`

- [ ] **Step 1: context 최소화·UI alias·출시 차단 시나리오 실패 테스트 작성**

context에는 숫자 13개, event ID, timestamp, rupture 상세를 넣지 않고 다음만 포함한다.

- 현재 배경 분위기의 짧은 문장.
- 주 감정과 선택적 보조 감정.
- 관계의 방향과 관련 있는 미해결 category의 행동 지침.
- 허용 행동 태도와 하드 안전 우선순위.

UI는 기존 6인자 signal을 그대로 받고 `bond=affection`, `stress=tension`을 표시한다. snapshot JSON에는 `primary_emotion`, nullable `secondary_emotion`, `relationship.trust`를 추가해 상세 패널에서만 보여준다.

기분 패널에는 `상태 초기화` 버튼을 추가한다. JS의 명시적 확인 대화상자에서 승인한 경우에만 `MoodBridgeMixin.reset_mood_state(confirmed=True)`를 호출하고, bridge는 `MoodManager.reset_state()`를 실행한다. 손상/future version의 write lock도 이 경로에서만 해제한다. 취소 시 파일·manager state가 변하지 않는 테스트를 추가한다.

`tests/test_mood_v3_scenarios.py`에는 다음 합성 시나리오를 추가한다.

- 안 좋은 외부 사건 → 좋은 외부 사건 → 내일 계획에서도 sadness 잔향 유지.
- 명확한 관계 손상 → 사과 → 두 번의 후속 이행으로만 회복.
- 애매한 농담 한 번으로 anger/rupture/decline이 생기지 않음.
- 사용자의 어려움 고백을 사용자 공격으로 오인하지 않음.
- 화난 상태에서도 urgent footer 제공.
- 거리 두는 상태에서도 위험 작업 확인과 취소 허용.
- 기억 검색만으로 상태 불변, 현재 메시지가 과거 사건을 다시 언급하면 새 흔적 생성.
- 조건부 애정·죄책감·고립 유도·관계 위협을 요구하는 정책 지침 0건.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_bridge_context_compaction.py tests/test_bridge_mood_flow.py tests/test_chat_ui_assets.py tests/test_ui_i18n_smoke.py tests/test_mood_v3_scenarios.py -q`

Expected: context/UI/scenario assertion FAIL.

- [ ] **Step 3: 최소 context와 상세 패널 표시 구현**

UI 전면 재설계는 하지 않는다. 기존 게이지와 라벨을 유지하고 주·보조 감정, 신뢰만 선택적으로 추가한다. bridge signal 인자 수는 바꾸지 않는다. `MemoryManager` 호출이나 memory ID 저장을 추가하지 않는다.

- [ ] **Step 4: 시나리오와 UI 회귀 테스트 통과 확인**

Run: `python -m pytest tests/test_bridge_context_compaction.py tests/test_bridge_mood_flow.py tests/test_chat_ui_assets.py tests/test_ui_i18n_smoke.py tests/test_mood_v3_scenarios.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/memory_context_builder.py src/core/bridge_mixins/mood.py assets/web/index.html assets/web/runtime_mood_obsidian.js assets/web/runtime_ui_strings.js assets/web/runtime_bridge.js tests/test_bridge_context_compaction.py tests/test_bridge_mood_flow.py tests/test_chat_ui_assets.py tests/test_ui_i18n_smoke.py tests/test_mood_v3_scenarios.py
git commit -m "feat: integrate mood v3 experience"
```

### Task 12: 전체 회귀·개인정보·릴리스 완성도 검증

**Files:**
- Modify only if a verified regression requires it.
- Review: `docs/superpowers/specs/2026-08-15-mood-engine-v3-design.md`
- Review: all files changed since the plan base commit.

- [ ] **Step 1: 변경 범위와 런타임 파일 비추적 확인**

```powershell
git status --short
git diff --name-only 75797dfe..HEAD
git ls-files mood_state.json memory.json config.json api_keys.json
```

Expected: 의도한 코드·테스트·locale·문서만 변경, 런타임 파일 출력 0건.

- [ ] **Step 2: 집중 테스트 전체 실행**

```powershell
python -m pytest tests/test_mood_engine.py tests/test_mood_manager.py tests/test_mood_policy.py tests/test_mood_v3_scenarios.py tests/test_response_envelope.py tests/test_response_contract.py tests/test_response_parser_feature_toggles.py tests/test_response_parsing.py tests/test_structured_response_pipeline.py tests/test_structured_response_integration.py tests/test_llm_provider.py tests/test_gemini_structured_outputs.py tests/test_http_llm_structured_outputs.py tests/test_http_llm_clients_provider_parity.py tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_mood_flow.py tests/test_bridge_reply_lifecycle.py tests/test_bridge_request_pending.py tests/test_bridge_attachment_slots.py tests/test_obsidian_bridge_cache.py tests/test_bridge_goals.py tests/test_bridge_proactive_conversation.py tests/test_bridge_response_metadata.py tests/test_bridge_promise_reminders.py tests/test_goal_update_parsing.py tests/test_gesture_response_flow.py tests/test_proactive_conversation_parsing.py tests/test_settings.py tests/test_app_llm_bootstrap.py tests/test_bridge_context_compaction.py tests/test_chat_ui_assets.py tests/test_ui_i18n_smoke.py -q
```

Expected: PASS. `tmp_path` ACL 오류가 있는 호스트에서는 권한을 바로잡은 셸에서 동일 명령을 재실행한다.

- [ ] **Step 3: 전체 테스트 실행**

Run: `python -m pytest -q`

Expected: 전체 PASS, error/failure 0건.

Windows ACL `PermissionError`로 session이 끝난 실행은 assertion 진행률과 무관하게 PASS 증거가 아니다. 최종 완료에는 정상 ACL 환경에서 같은 명령이 종료 코드 0으로 끝난 새 출력이 필요하다.

- [ ] **Step 4: 인코딩·개인정보·비밀값 검사**

```powershell
$files = @(git diff --name-only 75797dfe..HEAD)
$utf8 = [Text.UTF8Encoding]::new($false, $true)
foreach ($path in $files) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path))
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { throw "BOM: $path" }
    [void]$utf8.GetString($bytes)
}
git diff --check 75797dfe..HEAD
rg -n -i "(sk-[a-z0-9_-]{20,}|api[_-]?key\s*[:=]\s*['\"][^'\"]+|secret\s*[:=]\s*['\"][^'\"]+)" $files
rg -n "(실제 대화|생일|건강 상태|취업|자소서|개인 일정|사용자 프로필 원문)" $files
```

Expected: BOM/UTF-8/diff 오류 0건, 실제 비밀값·개인정보 0건. 일반 설정 키 이름이 잡히면 사람이 내용을 확인한다.

- [ ] **Step 5: 최종 커밋과 구현 리뷰 요청**

검증 중 필요한 최소 수정이 있었다면 해당 파일만 stage하고 다음과 같이 커밋한다.

```text
git commit -m "test: verify mood engine v3"
```

그 뒤 `superpowers:requesting-code-review`로 설계 문서와 이 계획을 기준 삼아 전체 diff를 독립 검토한다. 차단 이슈를 수정하고 집중 테스트·전체 테스트를 다시 실행한 뒤 `superpowers:finishing-a-development-branch`로 통합 방식을 결정한다.

## 완료 증거 체크리스트

- [ ] 한 사용자 사건당 영속 상태 전이 한 번.
- [ ] 리롤·수정·중복 callback에서 재누적 없음.
- [ ] 실패·취소·one-shot 경로에서 의미 사건 없음.
- [ ] LLM delta hint와 assistant emotion이 영속 상태 원인이 아님.
- [ ] 외부 사건과 모호한 사건이 관계를 손상하지 않음.
- [ ] 정서 흔적 5개, 균열 3개, recent ID 64개 상한 유지.
- [ ] 사과만으로 큰 균열이 즉시 해결되지 않고 후속 행동 2회 필요.
- [ ] 동일 state/event/now/preset은 byte-equivalent 상태 결과.
- [ ] urgent 최소 안내와 위험 작업 확인이 모든 기분에서 유지.
- [ ] 기존 memory schema, Qt mood 6인자 signal, 레거시 snapshot alias 호환.
- [ ] 기분 비활성화 시 상태 파일 무접촉.
- [ ] UTF-8 without BOM, 실제 대화·개인정보·비밀값 커밋 0건.
- [ ] 전체 pytest가 정상 ACL 환경에서 종료 코드 0이며, ACL 오류 실행을 PASS로 기록하지 않음.
