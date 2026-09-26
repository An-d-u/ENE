# Life Record Session-End Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인·저장된 요약이 있는 세션의 종료 시각을 생활 기록 임계값, 기록 구간과 새 기록 ID의 단일 기준으로 사용한다.

**Architecture:** 기존 세션 상태 V2와 `origin_session_ended_at` 필드를 그대로 사용한다. `AppSessionTracker`가 종료 시각 기반 후보와 새 claim ID를 만들고, `LifeRecordBridgeMixin`은 기존 `candidate.started_at` 데이터 흐름을 그대로 사용한다. 이전 릴리스의 saved-at 기반 미완료 claim은 parser와 시작 복구에서만 제한적으로 호환한다.

**Tech Stack:** Python 3.11+, PySide6, pytest, JSON locale, Markdown 문서

---

## 실행 규칙

- `AGENTS.md` 기준 **Sequential direct implementation**으로 실행한다.
- 동시성·lifecycle 상태 변경이므로 reasoning effort는 high로 취급한다.
- 각 Task에서는 해당 집중 테스트만 실행하고 전체 테스트는 Task 5 최종 체크포인트에서 한 번 실행한다.
- 공식 명세·품질 리뷰는 현재 branch diff로 제한한다.
- Critical·Important는 즉시 수정하고, Minor는 Task 5 목록에서 한 번에 판단한다.
- 모든 새 테스트 데이터는 합성 데이터만 사용한다.
- 테스트 명령은 `.venv`가 준비된 저장소 루트에서 실행한다. 임시 결과는 Git 제외 경로인 `.pytest_tmp/` 아래에 둔다.
- 수정 파일은 UTF-8 without BOM으로 유지한다.

## 공통 커밋 전 공개 저장소 안전 검사

각 Task는 정확한 파일만 먼저 stage한 뒤, `git commit` 전에 아래 검사를 실행한다. 검색 결과가 있으면 모두 합성 fixture·일반 문서인지 직접 확인하고, 실제 개인정보나 비밀 후보가 하나라도 있으면 커밋을 중단한다.

```powershell
$staged = @(git diff --cached --name-only --diff-filter=ACMR)
$forbidden = @($staged | Where-Object { $_ -match '(^|/)(memory\.json|user_profile\.json|ene_profile\.json|config\.json|api_keys\.json|obs_config\.json|mood_state\.json|calendar\.json|diary\.json|api_key\.txt|\.env[^/]*)$|\.(pyc|png|jpg|jpeg|gif|zip|exe|dll)$' })
if ($forbidden.Count -gt 0) { $forbidden; throw 'forbidden staged artifact' }
if ($staged.Count -gt 0) { rg -n -i "(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|실제 대화|건강|일정|취업|프로필)" -- $staged }
git diff --cached --check
```

`rg`가 검색 결과 없음으로 exit 1을 반환하는 것은 정상이다. 파일 내용은 UTF-8 without BOM인지 함께 확인한다.

### Task 1: 세션 종료 시각을 candidate 기준으로 전환

**Files:**
- Modify: `tests/test_life_session_tracker.py`
- Modify: `src/core/life_session_tracker.py:543-566`

- [ ] **Step 1: 정상 종료와 heartbeat 복구 candidate의 실패 테스트 작성**

요약 저장 시각과 세션 종료 시각을 다르게 둔 active anchor를 사용한다.

```python
def test_active_anchor_candidate_starts_at_origin_session_end(tmp_path: Path) -> None:
    anchor = _anchor(saved_at=_at(3), origin_session_ended_at=_at(5))
    # stopped V2 상태를 저장하고 _at(10)에 시작한다.
    candidate = tracker.start_session()
    assert candidate == InactiveStartCandidate(
        started_at=_at(5),
        source="summary_graceful_exit",
        summary_id=SUMMARY_ID,
    )
```

heartbeat recovery도 `current_summary.saved_at`이 아니라 이전 `last_seen_at`으로 승격된 종료 시각을 candidate에 사용하도록 별도 assertion을 둔다. `test_startup_reconciliation_releases_missing_record_claim`의 기대 시작도 `_at(5)`로 바꾼다.

- [ ] **Step 2: RED 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_life_session_tracker.py -k "candidate or promoted or reconciliation_releases" --basetemp='.\.pytest_tmp\ene-session-end-task1-red' -q
```

Expected: 새 candidate 기대값이 현재 `saved_at`을 반환해 FAIL.

- [ ] **Step 3: 최소 구현**

`_candidate_from_previous()`의 endpoint를 `anchor.origin_session_ended_at`으로 바꾼다. canonicalize, 미래 시각 검사와 진단 코드는 그대로 유지한다.

```python
anchor = previous.active_anchor
endpoint = anchor.origin_session_ended_at
```

- [ ] **Step 4: GREEN 확인**

Run: Step 2와 같은 명령.

Expected: PASS.

- [ ] **Step 5: Task 1 집중 회귀**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_life_session_tracker.py --basetemp='.\.pytest_tmp\ene-session-end-task1-green' -q
```

Expected: 전체 파일 PASS.

- [ ] **Step 6: stage 후 공통 공개 저장소 안전 검사**

```powershell
git add src/core/life_session_tracker.py tests/test_life_session_tracker.py
```

위 “공통 커밋 전 공개 저장소 안전 검사”를 실행한다.

- [ ] **Step 7: 커밋**

```powershell
git commit -m "fix: anchor life records to session end"
```

### Task 2: 새 claim ID와 구버전 claim 호환

**Files:**
- Modify: `tests/test_life_session_tracker.py`
- Modify: `tests/test_life_record_end_to_end.py`
- Modify: `src/core/life_session_tracker.py:308-394`
- Modify: `src/core/life_session_tracker.py:795-864`

- [ ] **Step 1: claim ID 실패 테스트 작성**

다음 동작을 각각 테스트한다.

1. 새 claim의 ID는 `stable_life_record_id(anchor.origin_session_ended_at, returned_at)`이다.
2. V2 parser는 saved-at 기반 구버전 ID와 session-end 기반 새 ID를 모두 허용한다.
3. 같은 길이의 임의 ID는 `claim_record_id_mismatch`로 거부한다.
4. 구버전 claim의 record가 존재하면 시작 복구가 claim과 기존 anchor를 소비한다.
5. 구버전 claim의 record가 없으면 claim만 해제하고 종료 시각 기반 candidate를 반환한다.

테스트 helper `_claim()`은 기준 시각을 명시적으로 받을 수 있게 한다.

```python
def _claim(*, record_start: datetime = _at(3), returned_at: datetime = _at(7), ...):
    resolved_id = stable_life_record_id(record_start, returned_at)
```

- [ ] **Step 2: 19:00 요약, 20:00 종료 E2E 실패 테스트 작성**

`tests/test_life_record_end_to_end.py`에서 요약 저장과 종료 상수를 분리한다.

```python
SUMMARY_SAVED_AT = datetime(2099, 8, 6, 19, 0, tzinfo=SEOUL)
STOPPED_AT = datetime(2099, 8, 6, 20, 0, tzinfo=SEOUL)
```

`_seed_session()`은 `current_summary.saved_at=SUMMARY_SAVED_AT`, `last_seen_at/stopped_at=STOPPED_AT`을 저장한다. 다음을 검증한다.

- 300분 설정에서 다음 날 00:59 첫 메시지는 기록을 만들지 않는다.
- 이후 빈 실행의 01:00 첫 메시지는 기록을 만들며 request, 저장 기록과 expected ID가 모두 `STOPPED_AT`을 사용한다.
- `test_post_summary_activity_does_not_move_anchor_timestamp`는 `test_same_summary_session_uses_later_exit_as_anchor_timestamp`로 바꾸고 candidate가 `later_exit`인지 확인한다.
- 요약 없는 후속 세션이 기존 기준점을 보존하는 계약은 `test_intermediate_message_run_preserves_anchor_for_later_eligible_run`에서 별도로 유지한다.

- [ ] **Step 3: RED 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_life_session_tracker.py tests/test_life_record_end_to_end.py -k "claim_life_generation_is_canonical or claim_record_id or startup_reconciliation or session_end_threshold or later_exit or intermediate_message" --basetemp='.\.pytest_tmp\ene-session-end-task2-red' -q
```

Expected: 새 claim ID와 새 parser 허용 경로가 없어 FAIL.

- [ ] **Step 4: 두 결정적 claim ID helper 구현**

anchor와 returned_at으로 허용 ID를 계산하는 작은 private helper를 추가한다.

```python
def _valid_claim_record_ids(anchor: ActiveLifeAnchor, returned_at: datetime) -> frozenset[str]:
    return frozenset(
        {
            stable_life_record_id(anchor.saved_at, returned_at),
            stable_life_record_id(anchor.origin_session_ended_at, returned_at),
        }
    )
```

parser는 저장된 ID가 이 집합에 포함되는지만 검사한다. 임의 ID 허용이나 느슨한 문자열 검사는 추가하지 않는다.

- [ ] **Step 5: 새 claim은 종료 시각 ID만 생성**

`claim_life_generation()`에서 새 `expected_record_id` 계산의 첫 인자를 `anchor.origin_session_ended_at`으로 바꾼다. `returned_at` 하한과 원자 commit 규칙은 변경하지 않는다.

- [ ] **Step 6: GREEN 확인**

Run: Step 3과 같은 명령.

Expected: PASS.

- [ ] **Step 7: Task 2 집중 회귀**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_life_session_tracker.py tests/test_life_record_end_to_end.py tests/test_life_record_app_lifecycle.py --basetemp='.\.pytest_tmp\ene-session-end-task2-green' -q
```

Expected: PASS.

- [ ] **Step 8: stage 후 공통 공개 저장소 안전 검사**

```powershell
git add src/core/life_session_tracker.py tests/test_life_session_tracker.py tests/test_life_record_end_to_end.py
```

위 “공통 커밋 전 공개 저장소 안전 검사”를 실행한다.

- [ ] **Step 9: 커밋**

```powershell
git commit -m "fix: derive life record claims from session end"
```

### Task 3: 프롬프트 시간 계약 통일

**Files:**
- Modify: `tests/test_life_record_prompt.py`
- Modify: `src/ai/life_record_prompt.py:460-475`

- [ ] **Step 1: 프롬프트 계약 실패 테스트 작성**

`tests/test_life_record_prompt.py`에서 새 source의 시간 설명이 “승인된 요약이 있는 세션의 종료 시각”인지 확인하고, “요약 저장 시각”과 실제 대화가 가상 생활과 겹칠 수 있다는 이전 설명이 없는지 검증한다. 과거 source record 재생성 호환은 유지한다.

- [ ] **Step 2: RED 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_life_record_prompt.py -k "time_contract" --basetemp='.\.pytest_tmp\ene-session-end-task3-red' -q
```

Expected: 기존 프롬프트가 시작점을 요약 저장 시각으로 설명해 FAIL.

- [ ] **Step 3: 프롬프트 최소 수정**

새 summary source에 대해 `inactive_started_at`이 세션 종료 시각임을 설명한다. 사용자 부재를 과도하게 단정하지 않는 기존 안전 규칙과 첫 메시지 원문 비공개 계약은 유지한다. 생성 경로는 이미 candidate를 전달하므로 bridge에 별도 분기나 새 상태를 추가하지 않는다.

- [ ] **Step 4: GREEN과 관련 회귀 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_life_record_end_to_end.py tests/test_life_record_request_gate.py tests/test_life_record_prompt.py tests/test_life_record_types.py --basetemp='.\.pytest_tmp\ene-session-end-task3-green' -q
```

Expected: PASS.

- [ ] **Step 5: stage 후 공통 공개 저장소 안전 검사**

```powershell
git add src/ai/life_record_prompt.py tests/test_life_record_prompt.py
```

위 “공통 커밋 전 공개 저장소 안전 검사”를 실행한다.

- [ ] **Step 6: 커밋**

```powershell
git commit -m "fix: generate life records after session end"
```

### Task 4: 설정 문구와 사용자 문서 동기화

**Files:**
- Modify: `tests/test_ui_i18n_smoke.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Modify: `README.md`
- Modify: `README.ko.md`
- Modify: `README.ja.md`
- Modify: `docs/life_records.md`
- Modify: `docs/superpowers/specs/2026-09-25-life-record-summary-anchor-design.md`
- Modify: `docs/superpowers/plans/2026-09-25-life-record-summary-anchor.md`

- [ ] **Step 1: locale 실패 테스트 작성**

`test_life_record_settings_describe_summary_anchored_timing`의 기대값을 다음 의미로 바꾼다.

```python
"ko": {
    "label": "세션 종료 후 최소 시간:",
    "hint_parts": ("승인·저장된 요약", "세션이 종료된 시점부터", "첫 일반 메시지"),
}
```

영어와 일본어도 같은 의미를 검증한다.

- [ ] **Step 2: RED 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_ui_i18n_smoke.py -k "life_record_settings_describe" --basetemp='.\.pytest_tmp\ene-session-end-task4-red' -q
```

Expected: 기존 “요약 후 최소 시간” 문구 때문에 FAIL.

- [ ] **Step 3: 3개 locale 수정**

라벨과 hint를 승인 명세 §3.3에 맞춘다. JSON 구조와 키 이름 `min_inactive`는 설정 호환을 위해 유지한다.

- [ ] **Step 4: README와 생활 기록 문서 수정**

다음을 모든 언어에서 일관되게 설명한다.

- 승인·저장된 요약이 있는 세션만 기준점을 만든다.
- 최소 시간과 기록 구간은 그 세션 종료 시각부터 시작한다.
- 요약 없는 중간 세션은 기존 기준점을 이동하거나 소비하지 않는다.
- 너무 이른 첫 일반 메시지는 현재 실행의 기회만 닫는다.
- 기존 기록과 구버전 미완료 claim은 호환된다.

2026-09-25 명세와 계획의 saved-at 권위 설명에는 “2026-09-27 결정으로 대체됨”을 명시하고 현재 기준을 세션 종료 시각으로 정정한다. 과거 문서 전체를 다시 쓰지 않는다.

- [ ] **Step 5: GREEN과 문서 형식 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_ui_i18n_smoke.py -k "life_record_settings_describe or locale_keys" --basetemp='.\.pytest_tmp\ene-session-end-task4-green' -q
git diff --check
```

Expected: PASS, `git diff --check` 출력 없음.

- [ ] **Step 6: stage 후 공통 공개 저장소 안전 검사**

```powershell
git add src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_ui_i18n_smoke.py README.md README.ko.md README.ja.md docs/life_records.md
git add docs/superpowers/specs/2026-09-25-life-record-summary-anchor-design.md docs/superpowers/plans/2026-09-25-life-record-summary-anchor.md
```

위 “공통 커밋 전 공개 저장소 안전 검사”를 실행한다.

- [ ] **Step 7: 커밋**

```powershell
git commit -m "docs: explain session-end life record timing"
```

### Task 5: 최종 lifecycle 검증·리뷰·개인정보 검사

**Files:**
- Review: 현재 branch의 `main...HEAD` 전체 diff
- Modify: Critical·Important 수정이 필요한 파일만

- [ ] **Step 1: 관련 집중 테스트**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest tests/test_life_session_tracker.py tests/test_life_record_request_gate.py tests/test_life_record_end_to_end.py tests/test_life_record_app_lifecycle.py tests/test_life_record_prompt.py tests/test_life_record_types.py tests/test_ui_i18n_smoke.py -k "life or session or settings" --basetemp='.\.pytest_tmp\ene-session-end-task5-focused' -q
```

Expected: PASS.

- [ ] **Step 2: 최종 전체 테스트**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & '.\.venv\Scripts\python.exe' -m pytest --basetemp='.\.pytest_tmp\ene-session-end-task5-full' -q
```

Expected: 0 failed.

- [ ] **Step 3: 명세·품질 리뷰**

승인 설계 `docs/superpowers/specs/2026-09-27-life-record-session-end-anchor-design.md`와 현재 diff만 대조한다. Critical·Important는 즉시 수정하고 해당 집중 테스트와 전체 테스트를 다시 실행한다. Minor는 아래 목록에서 한 번에 결정한다.

- [ ] **Step 4: Minor 최종 판단**

| 출처 | 항목 | 최종 판단 |
|---|---|---|
| 명세 리뷰 | 새 종료 시각 기반 claim의 기록 존재/부재 재시작 복구를 직접 검증할지 | Task 2 테스트 결과를 보고 결정 |
| 명세 리뷰 | 미완료 claim A와 새 요약 B의 단일 원자 조정 계약을 새 명세에 재기재할지 | 기존 회귀 테스트와 문서 자립성을 보고 결정 |

- [ ] **Step 5: 공개 저장소 안전 검사**

검사 범위는 `git diff --name-only main...HEAD`로 제한한다.

- runtime 파일과 바이너리가 추적되지 않았는지 확인
- 실제 사용자 이름, 대화, 건강·일정·취업·프로필 내용이 없는지 확인
- API 키 패턴 확인
- 수정 파일의 UTF-8 BOM 확인
- `git diff --check` 실행

- [ ] **Step 6: 최종 상태 확인**

```powershell
git status --short --branch
git log --oneline --decorate main..HEAD
git diff --check main...HEAD
```

수정이 없으면 빈 커밋을 만들지 않는다. 수정이 있으면 관련 파일만 스테이징하고 영어 커밋 메시지를 사용한다.

## 완료 조건

- 요약 저장 19:00, 세션 종료 20:00, 최소 300분이면 01:00부터 생성할 수 있다.
- 새 기록의 `inactive_started_at`과 ID가 20:00 기준이다.
- 요약 없는 중간 세션의 대화와 종료는 기존 기준점을 이동하거나 소비하지 않는다.
- 구버전 saved-at claim을 안전하게 소비 또는 해제하고 새 claim은 종료 시각 ID만 사용한다.
- ko/en/ja 설정 문구와 사용자 문서가 세션 종료 기준을 명확히 설명한다.
- 관련 집중 테스트와 최종 전체 테스트가 통과한다.
- Critical·Important 리뷰 이슈가 남지 않는다.
- 개인정보, runtime 파일, BOM과 의도하지 않은 산출물이 diff에 없다.
