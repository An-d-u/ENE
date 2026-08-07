# ENE 비활성 생활 기록 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE 프로세스가 설정한 시간 이상 비활성 상태였을 때 다음 실행 세션의 첫 일반 채팅 직전에 해당 공백 전체의 생활 기록을 생성하고, 최신 기록만 일반 대화의 임시 컨텍스트로 사용하며, 날짜별 조회와 최신 기록 수동 재생성을 제공한다.

**Architecture:** `AppSessionTracker`가 종료·하트비트 시각으로 복귀 후보를 한 번 복구하고, `LifeRecordManager`가 스키마 검증·원자 저장·날짜 조회·최신 기록 교체를 책임진다. `LifeRecordPromptBuilder`와 공급자 공통 one-shot API가 히스토리 없는 구조화 생성을 수행한다. `LifeRecordBridgeMixin`은 텍스트와 첨부 채팅의 공통 진입점에서 첫 일반 요청을 잠시 보류한 뒤 기록 생성 성공 여부와 무관하게 기존 답변 흐름을 재개한다. 일반 대화에는 저장된 최신 성공 기록 한 개만 매 요청마다 임시 블록으로 주입하고 SDK/HTTP 히스토리와 `conversation_buffer`에는 저장하지 않는다.

**Tech Stack:** Python 3, PyQt6/QWebEngine, pytest, JavaScript(Node 기반 자산 테스트), JSON/Markdown 런타임 파일, 기존 Gemini·OpenAI·Anthropic·Ollama·사용자 지정 HTTP 공급자 계층

---

## 작업 원칙과 완료 기준

- 모든 테스트 fixture와 문서 예시는 2099년의 가상 장소·가상 활동만 사용한다.
- 새 파일과 수정 파일은 UTF-8 without BOM으로 유지한다.
- `life_records.json`, `life_session_state.json`, `prompts/life_world.md`는 런타임 데이터이므로 커밋하지 않는다.
- 생성 프롬프트, ENE 프로필 원문, 기분 설명, 활동 문장, 첫 채팅 내용은 로그에 남기지 않는다.
- 각 작업은 실패 테스트 작성 → 실패 확인 → 최소 구현 → 통과 확인 → 해당 범위 커밋 순서로 진행한다.
- 전체 기능 완료 전에는 기존 2D 월드 코드를 재사용하거나 확장하지 않는다. 이번 V1은 텍스트 생활 기록만 다룬다.

### 모든 커밋에 적용하는 필수 사전 검사

구현을 시작하기 직전에 로컬 전용 기준 태그를 만든다. 같은 이름의 태그가 이미 있으면 기존 태그를 덮어쓰지 말고 원인을 확인한다.

```powershell
git tag -l codex-ene-life-record-v1-base
git tag codex-ene-life-record-v1-base HEAD
```

Expected: 첫 명령 출력 없음, 두 번째 명령 성공. 이 태그는 최종 검증 범위를 계산한 뒤 삭제하며 원격에 push하지 않는다.

각 Task의 `커밋` 단계에서는 먼저 의도한 파일만 stage한 뒤 아래 검사를 실행한다. 검사를 통과하거나 검색 결과를 사람이 안전하다고 판정하기 전에는 커밋하지 않는다.

```powershell
$stagedFiles = @(git diff --cached --name-only --diff-filter=ACMR)
$bomFiles = foreach ($path in $stagedFiles) { if (Test-Path -LiteralPath $path) { $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path)); if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $path } } }
if ($bomFiles) { $bomFiles; throw 'UTF-8 BOM이 포함된 staged 파일이 있습니다.' }
git diff --cached --no-ext-diff --unified=0 | rg -n "(?i)(sk-[a-z0-9_-]{20,}|AIza[a-z0-9_-]{20,}|api[_-]?key\s*[:=]\s*['\"][^'\"]+|secret\s*[:=]\s*['\"][^'\"]+)"
git diff --cached --no-ext-diff --unified=0 | rg -n "(실제 대화|건강|취업|자소서|일정|생일|직업|전공|user_profile|calendar\.json|diary\.json)"
```

첫 번째 `rg`는 비밀값 후보가 0건이어야 한다. 두 번째는 코드상 일반 키 이름도 잡힐 수 있으므로 모든 결과를 확인해 실제 사용자 정보·실제 대화 재사용이 없음을 확인한다. 계획에 적힌 각 `git add`는 이 검사보다 먼저, `git commit`은 검사보다 나중에 실행한다.

## Task 1: 원자적 JSON 저장 기반 추가

**Files:**
- Modify: `src/core/app_paths.py`
- Modify: `tests/test_app_paths.py`

- [ ] **Step 1: 정상 저장과 교체 실패 보존 테스트 작성**

`tests/test_app_paths.py`에 다음 행위를 검증한다.

```python
def test_save_json_data_atomic_writes_utf8_without_bom(tmp_path):
    target = tmp_path / "state.json"
    save_json_data_atomic(target, {"text": "가상 기록"})

    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["text"] == "가상 기록"


def test_save_json_data_atomic_keeps_previous_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("replace failed")))

    with pytest.raises(OSError):
        save_json_data_atomic(target, {"version": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
```

Microsoft Store Python 경로를 강제로 활성화한 회귀 테스트도 추가한다.

- runtime canonical 파일과 visible mirror 파일이 모두 같은 디렉터리의 임시 파일을 거쳐 `os.replace`됨
- visible mirror 교체 실패를 삼키지 않고 호출자에게 예외로 전달
- mirror 실패 뒤 canonical·visible 어느 쪽에도 잘린 JSON이나 임시 파일이 남지 않음
- mirror 실패를 받은 manager가 메모리 최신값을 갱신하지 않음은 Task 4에서 검증

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_app_paths.py -q`

Expected: `save_json_data_atomic` import 또는 속성 부재로 FAIL.

- [ ] **Step 3: 같은 디렉터리 임시 파일과 `os.replace` 기반 최소 구현**

`src/core/app_paths.py`에 아래 계약을 추가한다.

```python
def save_json_data_atomic(path: Path, data: object) -> None:
    """JSON을 UTF-8(BOM 없음) 임시 파일에 쓴 뒤 원자적으로 교체한다."""
```

기존 경로 준비·가상화 규칙을 재사용하되 기존의 오류를 삼키는 visible 직접 쓰기 함수는 이 저장 경로에 사용하지 않는다. runtime canonical과 visible mirror 각각의 같은 디렉터리에 임시 파일을 만들고 파일 핸들을 닫은 뒤 `os.replace`한다. canonical 교체 뒤 visible mirror가 실패하면 예외를 호출자에게 전달해 manager가 메모리를 갱신하지 않게 한다. 이 경우 다음 Store Python 동기화에서 기존 visible 완성본이 canonical을 복구할 수 있으며, 두 경로 어디에도 부분 JSON은 남기지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_app_paths.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/app_paths.py tests/test_app_paths.py
git commit -m "feat: add atomic JSON persistence"
```

## Task 2: 앱 세션 종료·하트비트 복구 구현

**Files:**
- Create: `src/core/life_session_tracker.py`
- Create: `tests/test_life_session_tracker.py`

- [ ] **Step 1: 세션 후보 복구 테스트 작성**

가상 clock과 임시 데이터 루트를 사용해 다음을 각각 검증한다.

- 파일 없음 또는 손상된 JSON → 후보 없음, 새 `running` 세션 저장
- 이전 `status=stopped` → `stopped_at`과 `graceful_exit` 후보 복구
- 이전 `status=running` → `last_seen_at`과 `heartbeat_recovery` 후보 복구
- 시작 즉시 새 `session_id`, `started_at`, `last_seen_at`, `status=running`, `stopped_at=null` 저장
- `heartbeat()`는 현재 세션의 `last_seen_at`만 갱신
- `stop_session()`은 `status=stopped`, `last_seen_at`, `stopped_at`을 한 번에 저장
- ISO 8601 시각이 없거나 미래 시각인 후보는 폐기

핵심 공개 계약을 테스트에서 먼저 고정한다.

```python
tracker = AppSessionTracker(state_path, now=lambda: fixed_now)
candidate = tracker.start_session()

assert candidate == InactiveStartCandidate(
    started_at=previous_stop,
    source="graceful_exit",
)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_session_tracker.py -q`

Expected: 모듈 부재로 FAIL.

- [ ] **Step 3: 직렬화 모델과 추적기 구현**

`InactiveStartCandidate`는 불변 dataclass로 만들고 `source`를 `Literal["graceful_exit", "heartbeat_recovery"]`로 제한한다. `AppSessionTracker`는 Task 1의 원자 저장만 사용한다. 손상된 세션 상태는 복귀 후보로 신뢰하지 않고 “후보 없음”으로 처리한 뒤 현재 `running` 상태로 교체한다. 세션 상태는 복구용 단일 슬롯이므로 별도 `.corrupt` 사본은 만들지 않는다. 진단 로그에는 오류 코드와 경로 종류만 남기며 파일 내용은 남기지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_session_tracker.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/life_session_tracker.py tests/test_life_session_tracker.py
git commit -m "feat: track ENE process sessions"
```

## Task 3: 생활 기록 출력 스키마와 호스트 메타데이터 검증

**Files:**
- Create: `src/ai/life_record_types.py`
- Create: `tests/test_life_record_types.py`

- [ ] **Step 1: 스키마·시간 연속성·안정 ID 테스트 작성**

다음 실패 케이스를 각각 매개변수화한다.

- 최상위 추가 필드 또는 누락 필드
- 0개/25개 항목
- 빈 `place`, `activity`, `ending_state`
- 첫 시작/마지막 종료가 전체 구간과 다름
- 항목 사이 공백 또는 겹침
- 역전된 시각, 전체 구간 이탈, 잘못된 오프셋
- 마지막 항목 장소와 `ending_state.place` 불일치
- 같은 순간을 서로 다른 오프셋으로 표기해도 같은 ID 생성
- 저장 파일 최상위 키가 정확히 `version`, `records`인지와 `version == 1`인지 검증
- 저장 레코드의 필수·추가 필드, ID 재계산 일치, 유효한 IANA timezone, source enum, 양의 revision 검증
- `created_at <= updated_at`, `inactive_started_at < returned_at`과 모든 메타데이터 시각의 timezone awareness 검증
- `mood_snapshot`은 정확히 여섯 필수 키 `label`, `valence`, `energy`, `bond`, `stress`, `short_term_mood`만 가지며 추가·누락 필드를 거부. `label`·`short_term_mood`는 비어 있지 않은 문자열, 나머지 네 값은 유한한 수치인지 검증
- 저장 레코드 내부의 entry·ending_state도 모델 출력과 같은 strict nested-field·연속성 규칙 적용

```python
payload = parse_and_validate_life_record_output(
    raw_json,
    inactive_started_at=start,
    returned_at=end,
    timezone_name="Asia/Seoul",
)
assert len(payload.entries) <= 24
```

호스트 레코드 생성 테스트에서는 ID 입력을 `UTC 초 단위 Z 시작|UTC 초 단위 Z 종료`로 정규화한 SHA-256으로 고정하고 `revision=1`을 확인한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_types.py -q`

Expected: 모듈 부재로 FAIL.

- [ ] **Step 3: 엄격 파서와 dataclass 구현**

다음 타입을 추가한다.

```python
@dataclass(frozen=True)
class LifeRecordEntry:
    started_at: datetime
    ended_at: datetime
    place: str
    activity: str


@dataclass(frozen=True)
class LifeRecord:
    id: str
    inactive_started_at: datetime
    returned_at: datetime
    created_at: datetime
    updated_at: datetime
    revision: int
    timezone: str
    inactive_start_source: str
    mood_snapshot: dict[str, object]
    entries: tuple[LifeRecordEntry, ...]
    ending_state: dict[str, str]
```

JSON 파싱은 코드펜스 제거 정도만 허용하고, 모델 출력은 `entries`, `ending_state` 외 필드를 거부한다. 저장 파일은 별도 `parse_life_record_store(raw)`에서 `{version, records}`와 각 호스트 레코드를 완전히 역직렬화·재검증하며, 저장된 `id`를 interval로 재계산해 일치해야만 허용한다. 검증 오류는 프롬프트 원문을 포함하지 않는 안정적인 코드(`invalid_json`, `extra_field`, `invalid_store`, `invalid_id`, `gap`, `overlap`, `out_of_range` 등)로 노출한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_types.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/life_record_types.py tests/test_life_record_types.py
git commit -m "feat: validate life record schema"
```

## Task 4: 생활 기록 저장소·날짜 조회·최신 교체 구현

**Files:**
- Create: `src/ai/life_record_manager.py`
- Create: `tests/test_life_record_manager.py`

- [ ] **Step 1: 저장소 행위 테스트 작성**

다음을 검증한다.

- 최초 상태 `{ "version": 1, "records": [] }`
- 같은 안정 ID의 자동 생성 중복 추가 방지
- `latest()`는 `returned_at desc`, `created_at desc`, `id asc` 기준 첫 레코드 반환
- 선택 로컬 날짜의 `[00:00, 다음 날 00:00)`와 겹치는 레코드 전체 반환
- 자정을 넘긴 레코드는 양쪽 날짜에서 레코드 전체로 조회
- 손상된 `life_records.json`은 덮어쓰지 않고 읽기 오류 상태 유지
- 저장 실패 시 메모리 최신값도 바꾸지 않음
- Microsoft Store visible mirror 저장 실패 시에도 예외를 처리하고 manager 메모리 최신값을 바꾸지 않음
- `replace_latest()`는 같은 ID·원래 interval/source/timezone/mood/created_at을 보존하고 `revision+1`, `updated_at`만 갱신
- 최신이 아닌 ID는 재생성 대상으로 거부
- `previous_before(record_id)`는 대상 자체를 제외한 바로 전 레코드 한 개만 반환

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_manager.py -q`

Expected: 모듈 부재로 FAIL.

- [ ] **Step 3: 관리자 구현**

```python
class LifeRecordManager:
    def latest(self) -> LifeRecord | None: ...
    def add(self, record: LifeRecord) -> bool: ...
    def records_overlapping_date(self, local_date: date, timezone_name: str) -> list[LifeRecord]: ...
    def previous_before(self, record_id: str) -> LifeRecord | None: ...
    def replace_latest(self, record_id: str, generated: LifeRecordOutput, updated_at: datetime) -> LifeRecord: ...
```

Task 3의 `parse_life_record_store()`로 최상위 envelope와 모든 중첩 호스트 레코드를 검증한 뒤에만 메모리에 올리고, Task 1의 원자 저장 성공 이후에만 메모리 상태를 교체한다. JSON 문법은 맞지만 ID·timezone·revision·중첩 필드가 잘못된 파일도 손상 상태로 취급하고 절대 덮어쓰지 않는다. 조회 결과는 복사 가능한 직렬화 딕셔너리로 브리지에 넘길 수 있게 별도 `to_public_dict()`를 둔다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_manager.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/life_record_manager.py tests/test_life_record_manager.py
git commit -m "feat: persist and query life records"
```

## Task 5: 자유형 생활 환경 프롬프트와 기본 설정 추가

**Files:**
- Create: `prompts/defaults/life_world.md`
- Modify: `src/ai/prompt_config.py`
- Modify: `src/core/settings.py`
- Modify: `.gitignore`
- Modify: `tests/test_prompt_config.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 기본값·복사·설정 테스트 작성**

다음을 검증한다.

- `enable_life_records` 기본값은 `False`
- `life_record_min_inactive_minutes` 기본값은 `60`
- 사용자 데이터 루트에 `prompts/life_world.md`가 없으면 합성 마을 기본본을 복사
- 읽기·저장 시 UTF-8 without BOM
- 빈 문자열 저장을 허용하고 자동 기본값으로 되돌리지 않음
- 설정 저장/로드 round trip
- 기존 `PROMPT_MARKDOWN_FILENAMES`에 `life_world.md`를 포함하고 Microsoft Store Python visible↔runtime 양방향 동기화
- config에 0·음수·비정수 임계값이 있어도 런타임에서는 양의 정수 기본값 60으로 정규화

기본 프롬프트에는 실제 대화나 인적 사항 없이 `작은 광장`, `빵집`, `도서관`, `주택` 같은 중립 장소만 작성한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_prompt_config.py tests/test_settings.py -q`

Expected: 새 상수와 설정 키 부재로 FAIL.

- [ ] **Step 3: 프롬프트 경로와 설정 기본값 구현**

`src/ai/prompt_config.py`에 `LIFE_WORLD_PROMPT_PATH`, 기본 파일명, `load_life_world_prompt()`, `save_life_world_prompt()`를 기존 prompt 경로 규칙에 맞춰 추가하고 `PROMPT_MARKDOWN_FILENAMES`에도 등록한다. 기존 `_sync_visible_roaming_prompt_files_to_runtime()`와 `_sync_runtime_prompt_files_to_visible_roaming()` 테스트에 이 파일의 양방향 동기화를 추가한다. `Settings.load()`는 `life_record_min_inactive_minutes`를 `int >= 1`로 정규화하고 잘못된 값은 60으로 되돌린다. `.gitignore`에는 아래 런타임 파일을 명시한다.

```text
prompts/life_world.md
life_records.json
life_session_state.json
```

- [ ] **Step 4: 통과 및 ignore 확인**

Run: `python -m pytest tests/test_prompt_config.py tests/test_settings.py -q`

Expected: PASS.

Run: `git check-ignore prompts/life_world.md life_records.json life_session_state.json`

Expected: 세 경로 모두 출력됨.

- [ ] **Step 5: 커밋**

```text
git add prompts/defaults/life_world.md src/ai/prompt_config.py src/core/settings.py .gitignore tests/test_prompt_config.py tests/test_settings.py
git commit -m "feat: add life world prompt settings"
```

## Task 6: 생성 컨텍스트 화이트리스트와 프롬프트 빌더 구현

**Files:**
- Create: `src/ai/life_record_prompt.py`
- Create: `tests/test_life_record_prompt.py`
- Modify: `src/ai/ene_profile.py`

- [ ] **Step 1: 허용·제외 정보 테스트 작성**

합성 프로필을 사용해 다음을 검증한다.

- 포함: `core_profile.identity`, `core_profile.relationship_tone`
- facts 포함 카테고리: `basic`, `preference`, `goal`, `habit`, `relationship_tone`
- facts 순서: 잠금 수동 → 수동 → 자동, 각 그룹 최신순
- facts 최대 개수: 기존 `max_profile_facts_in_context`, 기본 10
- 제외: `speaking_style`, 사용자 상세 프로필, 대화/장기 기억, 일정, 첨부, 첫 채팅 본문
- 이름: 설정에 명시된 ENE·사용자 호출명만 포함
- 포함: 현재 `life_world.md` 전체, exact interval·IANA timezone·현지 날짜/요일, 직전 레코드 한 개, 선캡처 mood snapshot, 복귀 사실, 최대 24개/전 구간 규칙
- 기간별 세분화 지시: 1일 이하는 30분~수시간, 1일 초과 7일 이하는 수시간~하루, 7일 초과는 여러 날 단위의 반복 생활 요약
- 수동 재생성: 대상 레코드가 아니라 그 바로 전 레코드만 포함
- 빈 world는 `LifeWorldEmptyError`로 생성 호출 전 중단

검증은 민감한 문자열이 `prompt`에 없음을 직접 확인한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_prompt.py -q`

Expected: 모듈 부재로 FAIL.

- [ ] **Step 3: 명시적 DTO와 프롬프트 빌더 구현**

```python
@dataclass(frozen=True)
class LifeRecordGenerationContext:
    inactive_started_at: datetime
    returned_at: datetime
    timezone: str
    inactive_start_source: str
    world_markdown: str
    ene_identity: dict[str, object]
    relationship_tone: object
    profile_facts: tuple[dict[str, object], ...]
    display_names: dict[str, str]
    previous_record: dict[str, object] | None
    mood_snapshot: dict[str, object]


def build_life_record_prompt(context: LifeRecordGenerationContext) -> str: ...
```

`ene_profile.py`에는 생활 기록 전용 export 함수를 추가하되 일반 프로필 직렬화 결과를 통째로 넘기지 않는다. 빌더가 첫 채팅 내용을 받을 수 없는 시그니처 자체로 개인정보 경계를 고정한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_prompt.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/life_record_prompt.py src/ai/ene_profile.py tests/test_life_record_prompt.py
git commit -m "feat: build private life record prompts"
```

## Task 7: 공급자 중립 구조화 one-shot 계약과 Gemini 구현

**Files:**
- Modify: `src/ai/response_protocol.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `src/ai/llm_client.py`
- Create: `tests/test_life_record_llm_contract.py`
- Modify: `tests/test_llm_provider.py`
- Modify: `tests/test_llm_privacy_logging.py`

- [ ] **Step 1: 히스토리 없는 생성 계약 테스트 작성**

다음을 검증한다.

- `LLMRequestKind.LIFE_RECORD` 존재
- 공통 `LLMClientProtocol`과 Gemini client가 `generate_life_record_once(prompt)` 비동기 계약 제공
- Gemini는 `entries`와 `ending_state`만 허용하는 response schema 사용
- Gemini SDK가 native schema capability를 명시적으로 거부하면 같은 내용 생성 시도 안에서 strict JSON text config로 한 번 fallback하고 양쪽 사용량 합산
- SDK 대화 히스토리를 읽거나 쓰지 않는 one-shot 호출
- provider는 원문과 토큰 사용량만 반환하고 출력 검증·재시도를 수행하지 않음
- 로그에는 프롬프트·응답 본문이 없음

```python
result = await client.generate_life_record_once("합성 생성 지시")
assert result.text
assert result.token_usage.total_tokens == 12
assert fake_chat_history == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_llm_contract.py tests/test_llm_provider.py tests/test_llm_privacy_logging.py -q`

Expected: 새 request kind/API 부재로 FAIL.

- [ ] **Step 3: 공통 API와 Gemini 구조화 호출 구현**

`llm_provider.py`의 공통 Protocol과 Gemini client·필요한 Gemini 테스트 double에 `generate_life_record_once`를 추가한다. HTTP 실제 구현 완료 조건은 Task 8A/8B가 소유한다. `llm_client.py`는 기존 `_generate_one_shot_text`를 재사용하되 LIFE_RECORD 전용 config를 만들고 일반 final-response 파서를 통과시키지 않는다. 이 API는 한 번의 모델 내용 생성 시도와 토큰 정규화만 책임진다. transport가 native capability 거부를 반환해 JSON text wire 형식으로 대체하는 것은 같은 내용 생성 시도 안의 협상으로 보며, 그 과정의 사용량도 결과에 합산한다. exact interval·timezone을 가진 내용 검증, 오류 코드 재프롬프트, 최대 1회 내용 재시도는 Task 10B의 `LifeRecordWorker`만 담당한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_llm_contract.py tests/test_llm_provider.py tests/test_llm_privacy_logging.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/response_protocol.py src/ai/llm_provider.py src/ai/llm_client.py tests/test_life_record_llm_contract.py tests/test_llm_provider.py tests/test_llm_privacy_logging.py
git commit -m "feat: add structured life record generation"
```

## Task 8A: HTTP 공통 one-shot 계약과 OpenAI·Anthropic 구현

**Files:**
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_openai.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_http_llm_privacy_logging.py`
- Create: `tests/test_life_record_http_native_providers.py`

- [ ] **Step 1: 공급자별 요청 모양 테스트 작성**

가짜 transport로 다음을 고정한다.

- OpenAI Chat/Responses: native JSON schema 사용 가능 시 엄격 schema 적용
- Anthropic: strict tool 입력으로 동일 schema 강제
- 호출당 네트워크 요청은 정확히 한 번이며 validator·재시도는 실행하지 않음
- 대화 히스토리 payload에 생성 요청이 섞이지 않음
- 원문을 로그·예외에 포함하지 않음

공통 요청 객체를 먼저 테스트한다.

```python
request = StructuredOneShotRequest(
    kind=LLMRequestKind.LIFE_RECORD,
    prompt="합성 생성 지시",
    schema=LIFE_RECORD_OUTPUT_SCHEMA,
)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_http_native_providers.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_privacy_logging.py -q`

Expected: LIFE_RECORD 처리 부재로 FAIL.

- [ ] **Step 3: 최소 공통 descriptor와 transport 분기 구현**

`http_llm_common.py`에 one-shot 구조화 요청 descriptor를 두고 OpenAI Chat/Responses와 Anthropic transport의 기존 `_request_one_shot_raw`에 선택적 schema/tool 설정만 추가한다. 일반 채팅용 final-response 파서를 공유하지 말고, 네트워크 호출·토큰 정규화 코드만 재사용한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_http_native_providers.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_privacy_logging.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/http_llm_common.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_privacy_logging.py tests/test_life_record_http_native_providers.py
git commit -m "feat: add native HTTP life record requests"
```

## Task 8B: Ollama·사용자 지정 wire format parity와 capability fallback 구현

**Files:**
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_ollama.py`
- Modify: `src/ai/http_llm_custom_providers.py`
- Modify: `src/ai/http_llm_openai.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Create: `tests/test_life_record_http_format_parity.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_http_llm_structured_outputs.py`

- [ ] **Step 1: wire format별 capability 테스트 작성**

공급자 표시 이름이 아니라 실제 wire format과 capability를 기준으로 다음을 고정한다.

- Ollama: 기존 `format` JSON schema 기능을 우선 사용
- custom OpenAI Chat/Responses: native JSON schema 우선
- custom Anthropic: strict tool 우선
- custom Ollama: native `format` schema 우선
- custom Mistral·Google Cloud·Cohere: 해당 transport가 지원하는 구조화 형식을 우선
- registry상 native schema/tool을 지원하지 않으면 처음부터 strict JSON 텍스트 요청을 한 번 수행
- native 요청이 명시적 capability 거부로 실패한 경우에만 같은 내용 생성 시도 안에서 strict JSON 텍스트로 한 번 fallback하고, 양쪽에 토큰 사용량이 있으면 합산
- fallback도 히스토리 없는 one-shot이며 provider 내부 검증·재시도 없음
- `LIFE_RECORD_SCHEMA_VERSION` 또는 request kind가 포함된 capability key로 일반 FINAL_REPLY structured capability 캐시와 완전히 분리
- 생활 기록 native 거부가 일반 답변을 legacy로 낮추지 않고, 일반 답변의 cached legacy 상태도 생활 기록 native 시도를 막지 않음
- Task 8A/8B 완료 시 Gemini를 제외한 모든 실제 HTTP client class가 공통 `generate_life_record_once` 계약을 충족

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_http_format_parity.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_structured_outputs.py -q`

Expected: LIFE_RECORD capability routing 부재로 FAIL.

- [ ] **Step 3: capability 기반 payload 분기 구현**

기존 response capability registry와 wire format 정보를 재사용해 `StructuredOneShotRequest`를 native schema/tool 또는 strict JSON text로 직렬화한다. `ResponseCapabilityKey`에는 request kind를 추가하거나 생활 기록 전용 `LIFE_RECORD_SCHEMA_VERSION`을 사용해 FINAL_REPLY 캐시와 충돌할 수 없게 한다. capability 거부 fallback은 같은 provider의 기존 오류 분류를 사용하고 응답·프롬프트 원문은 예외나 로그에 넣지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_http_format_parity.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_structured_outputs.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/http_llm_common.py src/ai/http_llm_ollama.py src/ai/http_llm_custom_providers.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py tests/test_life_record_http_format_parity.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_structured_outputs.py
git commit -m "feat: route life record requests by capability"
```

## Task 9: 최신 생활 기록 임시 대화 컨텍스트 구현

**Files:**
- Modify: `src/ai/memory_context_builder.py`
- Create: `tests/test_life_record_chat_context.py`
- Modify: `tests/test_bridge_context_compaction.py`

- [ ] **Step 1: 컨텍스트 포함·비축적 테스트 작성**

다음 상태표를 매개변수화한다.

| 기능 | 저장된 최신 기록 | 현재 생성 결과 | 기대 컨텍스트 |
|---|---:|---|---|
| 꺼짐 | 있음 | 해당 없음 | 없음 |
| 켜짐 | 없음 | 실패/생략 | 없음 |
| 켜짐 | 있음 | 임계 미만/빈 world/실패 | 기존 최신 한 개 |
| 켜짐 | 있음 | 성공 | 새 최신 한 개 |

추가로 다음을 검증한다.

- 과거 기록 여러 개가 있어도 최신 성공 기록 한 개만 포함
- record block은 모든 일반 텍스트·첨부 대화 요청에 포함
- `history_user_content`는 원래 사용자 메시지이고 생활 기록 블록이 아님
- SDK/HTTP history와 `conversation_buffer`에는 생활 기록 텍스트가 축적되지 않음
- 리롤은 실행 시점의 최신 저장 기록을 다시 읽음
- `memory_manager`가 없어도 생활 기록 블록은 조기 return 전에 포함
- Gemini와 HTTP client에 manager를 바인딩했을 때 동일한 블록이 생성됨

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_chat_context.py tests/test_bridge_context_compaction.py -q`

Expected: 생활 기록 블록 부재로 FAIL.

- [ ] **Step 3: 임시 블록 빌더와 조합 순서 구현**

```python
def build_life_record_context_block(
    *, enabled: bool, latest_record: LifeRecord | None
) -> str:
    """최신 성공 기록 한 개를 현재 요청에만 쓰는 컨텍스트로 만든다."""
```

실제 비동기 `build_memory_context(client, ...)` 진입 직후 `client.life_record_manager`와 `client.settings`를 읽어 이 블록을 가장 먼저 조합한다. `memory_manager`가 없는 조기 return에서도 블록을 보존하고, 기존 `send_message_with_memory(..., history_user_content=original_message)` 경계를 바꾸지 않는다. 생활 기록 관리자 부재·읽기 오류는 빈 블록으로 처리한다. Task 14에서는 동일 manager를 실제 Gemini 또는 HTTP `llm_client.life_record_manager`에 명시적으로 바인딩한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_chat_context.py tests/test_bridge_context_compaction.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/memory_context_builder.py tests/test_life_record_chat_context.py tests/test_bridge_context_compaction.py
git commit -m "feat: inject latest life record ephemerally"
```

## Task 10A: 첫 일반 채팅 판정과 요청 보류 상태 기계 구현

**Files:**
- Create: `src/core/bridge_mixins/life_records.py`
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Modify: `src/core/bridge_mixins/attachments.py`
- Create: `tests/test_life_record_request_gate.py`
- Modify: `tests/test_chat_attachments.py`
- Modify: `tests/test_bridge_attachment_slots.py`

- [ ] **Step 1: 첫 요청 상태 기계 테스트 작성**

가짜 manager/mood와 prepared request를 사용해 다음을 검증한다.

- `/note`, `/obs`, `/diary`는 생활 기록 후보를 소비하지 않음
- 첫 일반 텍스트와 첫 첨부 채팅은 후보를 소비함
- 기능 꺼짐, 후보 없음, 59분, 0분 이하, 빈 world는 LLM 호출 없이 즉시 기존 답변 시작
- 정확히 60분은 생성 시도
- 복귀 종료 시각은 앱 시작이 아니라 첫 일반 채팅 수신 시각
- mood snapshot은 `mood_manager.on_user_message()` 전에 캡처
- 동일 실행 세션에서 성공/실패/생략 뒤 자동 판정은 한 번뿐
- 첫 답변 리롤과 첫 사용자 메시지 수정·재전송은 자동 생성을 다시 예약하지 않음
- 판정 대상이면 conversation append, `on_user_message`, AIWorker 시작 전에 prepared request를 정확히 한 개 보류
- 빈 world는 안전한 `life_record_notice` 코드 `world_empty`를 emit하고, 기능 꺼짐·후보 없음·임계 미만은 사용자 오류 signal 없이 조용히 통과

핵심 테스트 순서는 아래처럼 고정한다.

```python
bridge.send_to_ai("합성 인사")
assert bridge.life_record_state.pending_request is not None
assert conversation_buffer == []
assert mood_events == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_request_gate.py tests/test_chat_attachments.py tests/test_bridge_attachment_slots.py -q`

Expected: life record mixin/state 부재로 FAIL.

- [ ] **Step 3: 브리지 상태와 판정 로직 구현**

`LifeRecordBridgeState`에는 후보, 자동 판정 완료 여부, 진행 중 여부, 보류된 prepared request, 선캡처 mood, 선행 token usage만 둔다. raw 사용자 본문은 로그에 쓰지 않는다. 기능 설정·정규화된 임계값·candidate·world 존재·구간 양수를 순서대로 판정하고 어떤 결과든 해당 세션의 자동 판정은 완료 처리한다.

- [ ] **Step 4: 텍스트·첨부 공통 진입점으로 최소 리팩터링**

`chat_flow.py`와 `attachments.py`가 사용자 메시지를 conversation/mood에 반영하기 직전에 같은 메서드를 호출하게 한다.

```python
def _dispatch_general_request(self, prepared_request: PreparedChatRequest) -> None:
    """필요하면 생활 기록을 먼저 만든 뒤 준비된 일반 요청을 시작한다."""
```

기존 명령 분기는 이 메서드보다 앞에 둔다. 실제 사용자 활동 기록, conversation append, `on_user_message`, `_last_request_payload`, AIWorker 시작은 생활 기록 판정 후 기존 순서를 유지하는 단일 commit 함수로 모은다.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_life_record_request_gate.py tests/test_chat_attachments.py tests/test_bridge_attachment_slots.py -q`

Expected: PASS.

- [ ] **Step 6: 커밋**

```text
git add src/core/bridge_mixins/life_records.py src/core/bridge_state.py src/core/bridge.py src/core/bridge_mixins/chat_flow.py src/core/bridge_mixins/attachments.py tests/test_life_record_request_gate.py tests/test_chat_attachments.py tests/test_bridge_attachment_slots.py
git commit -m "feat: gate the first chat for life records"
```

## Task 10B: 생활 기록 worker·저장·답변 재개 파이프라인 구현

**Files:**
- Modify: `src/core/bridge_workers.py`
- Modify: `src/core/bridge_mixins/life_records.py`
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge.py`
- Create: `tests/test_life_record_bridge_flow.py`
- Modify: `tests/test_bridge_token_usage.py`

- [ ] **Step 1: 생성·재시도·답변 재개 테스트 작성**

다음을 검증한다.

- UI stage가 `life_record`에서 `thinking`으로 전환
- prompt 생성 → `generate_life_record_once` → exact interval/timezone validator 순서
- 첫 출력 검증 실패 시 오류 코드만 추가해 정확히 한 번 재호출하고 두 번째 성공 저장
- 두 번째 검증 실패 또는 LLM 오류 시 더 재시도하지 않음
- 첫 시도와 두 번째 시도의 모든 생성 토큰을 누적해 일반 답변의 prior token usage에 전달
- 생성 성공은 원자 저장 성공 뒤에만 새 최신 기록을 답변 컨텍스트로 사용
- 검증/LLM/저장 실패는 기존 최신 기록이 있으면 그것을, 없으면 무기록으로 보류 요청 재개
- 생성 중 사용자 입력과 중복 생성 잠금
- 생성 호출이 SDK/HTTP history를 변경하지 않음
- 로그에는 오류 코드·시도 수·항목 수·토큰 수만 있고 prompt/profile/activity 원문은 없음
- 생성·검증 실패는 `life_record_notice`의 안전 코드 `generation_failed`, 저장 실패는 `save_failed`를 emit
- 저장 성공은 `life_record_items_updated`에 public record·영향받는 현지 날짜·전역 latest ID를 emit해 열린 패널이 즉시 갱신됨

```python
bridge.send_to_ai("합성 인사")
assert ui_stages == ["life_record"]

life_worker.finish_after_retry(valid_output, usages=[{"total_tokens": 8}, {"total_tokens": 5}])
assert ui_stages == ["life_record", "thinking"]
assert answer_worker.prior_token_usage["total_tokens"] == 13
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_bridge_flow.py tests/test_bridge_token_usage.py -q`

Expected: 전용 worker·재시도·토큰 전달 부재로 FAIL.

- [ ] **Step 3: 검증과 재시도의 단일 소유자인 worker 구현**

`LifeRecordWorker`만 exact interval·timezone을 가진 채 Task 3 validator를 호출한다. 첫 검증 오류일 때 안정 오류 코드만 prompt 끝에 추가해 `generate_life_record_once`를 한 번 더 호출하고, provider 계층에서는 내용 검증이나 내용 재시도를 하지 않는다. 두 호출의 사용량은 성공 여부와 무관하게 합산한다.

- [ ] **Step 4: 저장 결과에 따른 보류 요청 재개 구현**

브리지는 manager 저장 성공을 확인한 뒤에만 새 레코드를 최신값으로 사용한다. 성공 시 활동 원문을 로그에 남기지 않고 public UI payload를 `life_record_items_updated`로 보낸다. 실패는 내부 예외 문장 대신 정해진 notice 코드만 보낸다. 모든 종료 경로에서 pending request와 잠금을 한 번만 해제하고 기존 conversation append → mood update → AIWorker 순서를 재개한다.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_life_record_bridge_flow.py tests/test_bridge_token_usage.py -q`

Expected: PASS.

Run: `python -m pytest tests/test_bridge*.py -q`

Expected: 기존 채팅·리롤·수정 흐름 회귀 없이 PASS.

- [ ] **Step 6: 커밋**

```text
git add src/core/bridge_workers.py src/core/bridge_mixins/life_records.py src/core/bridge_state.py src/core/bridge.py tests/test_life_record_bridge_flow.py tests/test_bridge_token_usage.py
git commit -m "feat: generate life records before first replies"
```

## Task 11: 최신 기록 수동 재생성 브리지 API 구현

**Files:**
- Modify: `src/core/bridge_mixins/life_records.py`
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge.py`
- Create: `tests/test_life_record_regeneration.py`

- [ ] **Step 1: 재생성 불변조건 테스트 작성**

다음을 검증한다.

- 최신 기록 ID만 허용하고 과거 ID 거부
- 같은 interval·timezone·source·mood·created_at·id 사용
- 현재 world와 현재 ENE 프로필 사용
- 대상 자체는 이전 기록 컨텍스트에서 제외하고 바로 전 한 개만 사용
- 성공 시 같은 ID 원자 교체, `revision+1`, `updated_at` 갱신
- 실패/취소 시 기존 파일·메모리·일반 대화 컨텍스트 유지
- 재생성 중 채팅 및 중복 재생성 잠금
- 일반 답변 worker 또는 자동 생활 기록 생성이 이미 실행 중이면 backend가 재생성 요청을 거부
- 재생성은 별도 채팅 답변을 만들지 않음
- 재생성 성공 뒤 리롤은 교체된 최신 기록을 사용
- 날짜 조회 slot은 정렬된 public records와 전역 latest ID를 `life_record_items_updated`로 emit하고 읽기 오류는 안전한 notice 코드만 emit
- 재생성 성공도 교체된 public record·영향받는 날짜·latest ID를 emit해 열린 패널을 즉시 갱신

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_regeneration.py -q`

Expected: 브리지 slot 부재로 FAIL.

- [ ] **Step 3: 조회·재생성 slot과 signal 구현**

브리지에 최소 API를 추가한다.

```python
@pyqtSlot(str)
def request_life_records_for_date(self, iso_date: str) -> None: ...

@pyqtSlot(str)
def regenerate_latest_life_record(self, record_id: str) -> None: ...
```

signal payload는 UI 렌더링에 필요한 public dict와 상태 코드만 전송한다. 사용자 활동 문장을 로그에 출력하지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_regeneration.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/bridge_mixins/life_records.py src/core/bridge_state.py src/core/bridge.py tests/test_life_record_regeneration.py
git commit -m "feat: regenerate the latest life record"
```

## Task 12: 설정 UI와 다국어 문자열 연결

**Files:**
- Modify: `src/ui/settings_tabs/behavior_tab.py`
- Modify: `src/ui/settings_dialog_values.py`
- Modify: `src/ui/settings_tabs/prompt_tab.py`
- Modify: `src/ui/settings_dialog_prompt.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Modify: `tests/test_ui_i18n_smoke.py`
- Create: `tests/test_life_record_settings_ui.py`

- [ ] **Step 1: 설정 UI 테스트 작성**

다음을 검증한다.

- 동작 탭에 `생활 기록 사용` 토글이 기본 off
- 정수 분 입력은 1 이상이고 기본 60
- 설정 저장 후 다시 열면 동일 값
- 프롬프트 탭에 `생활 환경` Markdown 편집기, 실제 사용자 경로, 문자 수, 예상 토큰 수 표시
- 저장과 기본값 불러오기 동작
- 빈 world 저장 가능하며 경고 문구 표시
- ko/en/ja의 모든 새 키가 존재하고 UI에 빈 문자열이 없음

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_settings_ui.py tests/test_ui_i18n_smoke.py -q`

Expected: widget/locale key 부재로 FAIL.

- [ ] **Step 3: 기존 설정 패턴에 맞춰 UI 구현**

동작 탭의 기존 자리 비움 설정 인근에 생활 기록 그룹을 추가하고, 프롬프트 탭의 기존 편집기 공통 동작을 재사용한다. 설정 변경은 다음 일반 요청부터 manager가 최신값을 읽도록 하며 앱 재시작을 요구하지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_settings_ui.py tests/test_ui_i18n_smoke.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ui/settings_tabs/behavior_tab.py src/ui/settings_dialog_values.py src/ui/settings_tabs/prompt_tab.py src/ui/settings_dialog_prompt.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_ui_i18n_smoke.py tests/test_life_record_settings_ui.py
git commit -m "feat: add life record settings UI"
```

## Task 13A: 날짜별 생활 패널 조회·렌더링 구현

**Files:**
- Modify: `assets/web/index.html`
- Modify: `assets/web/runtime_bootstrap.js`
- Modify: `assets/web/runtime_bridge.js`
- Create: `assets/web/runtime_life_record_panel.js`
- Modify: `assets/web/style.css`
- Modify: `tests/test_chat_ui_assets.py`
- Create: `tests/test_life_record_panel_assets.py`

- [ ] **Step 1: 정적·Node DOM 테스트 작성**

다음을 검증한다.

- 우측 상단 `···` 메뉴에 `생활` 버튼 존재
- 패널 최초 날짜는 현지 오늘
- 이전/다음/오늘/date input이 ISO 날짜를 브리지에 요청
- 선택 날짜와 겹치는 레코드를 전체 카드로 표시
- 같은 날 여러 레코드는 backend 정렬 순서 유지
- 자정 넘김 entry에는 날짜도 함께 표시
- 비어 있음과 읽기 오류 상태 분리
- HTML escape 적용으로 record 문자열이 markup으로 실행되지 않음

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_panel_assets.py tests/test_chat_ui_assets.py -q`

Expected: 신규 자산·DOM ID·문자열 부재로 FAIL.

- [ ] **Step 3: 패널 렌더러와 브리지 연결 구현**

`runtime_life_record_panel.js`는 날짜 상태와 카드 렌더링을 소유한다. record payload는 `textContent` 또는 기존 escape helper로만 출력한다. `runtime_bridge.js`는 `life_record_items_updated`, `life_record_notice`를 연결하고 패널을 열 때 현재 선택 날짜를 요청한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_panel_assets.py tests/test_chat_ui_assets.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add assets/web/index.html assets/web/runtime_bootstrap.js assets/web/runtime_bridge.js assets/web/runtime_life_record_panel.js assets/web/style.css tests/test_chat_ui_assets.py tests/test_life_record_panel_assets.py
git commit -m "feat: add life record history panel"
```

## Task 13B: 최신 재생성·진행 상태·오류 UI 구현

**Files:**
- Modify: `assets/web/runtime_life_record_panel.js`
- Modify: `assets/web/runtime_ui_strings.js`
- Modify: `assets/web/runtime_bridge.js`
- Modify: `assets/web/runtime_chat_panel_controls.js`
- Modify: `assets/web/style.css`
- Create: `tests/test_life_record_ui_states.py`
- Modify: `tests/test_chat_ui_assets.py`

- [ ] **Step 1: 재생성·상태 전환 Node DOM 테스트 작성**

다음을 검증한다.

- backend가 제공한 전역 latest record ID 카드에만 재생성 버튼 표시
- 확인 대화상자 취소 시 bridge 미호출, 승인 시 한 번 호출
- 빈 world, 생성 실패, 저장/읽기 오류 안내 상태 분리
- 생성 중 `복귀 기록 정리 중…`, 일반 응답 중 `생각 중…`
- 재생성 중 `생활 기록 다시 만드는 중…`
- 진행 중 chat input과 재생성 버튼 disabled, 완료·실패 시 정확히 한 번 복구
- 중복 클릭은 한 번의 backend 호출만 만듦

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_ui_states.py tests/test_chat_ui_assets.py -q`

Expected: 재생성 및 life_record stage 처리 부재로 FAIL.

- [ ] **Step 3: 재생성 확인·오류 상태 구현**

`runtime_life_record_panel.js`는 latest ID와 busy state를 받아 재생성 버튼을 결정하고, 사용자 승인 뒤 bridge slot을 한 번만 호출한다. 모든 안내 문구는 Task 12의 ko/en/ja locale key를 사용한다.

- [ ] **Step 4: 요청 단계 표시 확장**

`runtime_chat_panel_controls.js`의 stage 정규화에 `life_record`, `life_record_regeneration`, `thinking`을 추가하되 기존 검색·생각 단계 동작을 보존한다. `runtime_bridge.js`는 완료·실패 signal에서 패널과 chat input 잠금을 함께 복구한다.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_life_record_ui_states.py tests/test_chat_ui_assets.py -q`

Expected: PASS.

- [ ] **Step 6: 커밋**

```text
git add assets/web/runtime_life_record_panel.js assets/web/runtime_ui_strings.js assets/web/runtime_bridge.js assets/web/runtime_chat_panel_controls.js assets/web/style.css tests/test_life_record_ui_states.py tests/test_chat_ui_assets.py
git commit -m "feat: add life record regeneration states"
```

## Task 14: 앱 수명주기 통합과 종료 안전성 구현

**Files:**
- Modify: `src/core/app.py`
- Modify: `src/core/overlay_window.py`
- Modify: `tests/test_app_llm_bootstrap.py`
- Modify: `tests/test_app_quit_summary.py`
- Create: `tests/test_life_record_app_lifecycle.py`

- [ ] **Step 1: 앱 통합 테스트 작성**

다음을 검증한다.

- 앱 시작 때 tracker가 이전 후보를 먼저 복구한 뒤 현재 `running` 세션 저장
- `LifeRecordManager`, 후보, provider, profile, mood, settings가 bridge에 바인딩
- 같은 `LifeRecordManager`가 실제 Gemini/HTTP `llm_client.life_record_manager`에도 바인딩되어 `build_memory_context()`가 읽을 수 있음
- 60초 QTimer tick이 현재 세션 heartbeat 호출
- 정상 종료에서 timer 정지 후 `stop_session()`이 overlay 종료보다 먼저 호출
- tracker/records 파일 오류가 앱 시작·일반 채팅을 막지 않음
- UI 문자열 payload에 ko/en/ja 생활 기록 키 포함

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_app_lifecycle.py tests/test_app_llm_bootstrap.py tests/test_app_quit_summary.py -q`

Expected: lifecycle wiring 부재로 FAIL.

- [ ] **Step 3: 앱 초기화·종료 순서 구현**

`app.py`가 데이터 루트의 두 JSON 경로를 생성자에 주입하고 `start_session()` 결과만 메모리 후보로 보관한다. 생성한 manager는 bridge뿐 아니라 공급자 종류와 무관하게 실제 `llm_client.life_record_manager`에도 명시적으로 설정한다. 하트비트 QTimer는 성공적으로 현재 세션을 연 뒤 시작한다. `_finish_quit_application`에서는 timer를 먼저 멈추고 `stop_session()`을 호출한 뒤 기존 overlay·tray 종료를 계속한다. 오류는 예외 본문 대신 안정 코드만 기록한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_app_lifecycle.py tests/test_app_llm_bootstrap.py tests/test_app_quit_summary.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/app.py src/core/overlay_window.py tests/test_app_llm_bootstrap.py tests/test_app_quit_summary.py tests/test_life_record_app_lifecycle.py
git commit -m "feat: wire life records into app lifecycle"
```

## Task 15: 대표 시나리오·회귀·문서·개인정보 검증

**Files:**
- Create: `tests/test_life_record_end_to_end.py`
- Modify: `README.md`
- Modify: `README.ko.md`
- Modify: `README.ja.md`
- Reference: `docs/superpowers/specs/2026-08-07-ene-life-record-design.md`

- [ ] **Step 1: 11시간 대표 시나리오 통합 테스트 작성**

실제 사용자 예문을 복사하지 않고 가상의 활동을 사용한다.

```python
def test_graceful_exit_to_first_chat_covers_full_eleven_hours(...):
    stopped_at = datetime(2099, 8, 6, 23, 0, tzinfo=SEOUL)
    first_chat_at = datetime(2099, 8, 7, 10, 0, tzinfo=SEOUL)

    record = run_first_general_chat(stopped_at, first_chat_at)

    assert record.entries[0].started_at == stopped_at
    assert record.entries[-1].ended_at == first_chat_at
    assert all(
        left.ended_at == right.started_at
        for left, right in pairwise(record.entries)
    )
```

같은 파일에서 정상 종료, 비정상 종료, 명령 선행, 첨부 첫 채팅, 생성 실패 fallback, 수동 재생성 성공·실패, 날짜 양쪽 조회, 리롤 비재생성을 잇는 사용자 여정을 검증한다.

- [ ] **Step 2: 완성된 사용자 여정 통과 확인**

Run: `python -m pytest tests/test_life_record_end_to_end.py -q`

Expected: 앞선 Task의 단위·통합 테스트에서 모든 연결을 구현했으므로 첫 실행부터 PASS. 실패하면 이 Task에서 임의 연결 코드를 추가하지 말고, 실패를 소유하는 선행 Task로 돌아가 그 Task의 파일 목록·실패 테스트·커밋 안에서 보완한 뒤 다시 실행한다.

- [ ] **Step 3: README 세 언어에 운영 정보를 추가**

다음만 문서화한다.

- 기본 비활성화 및 60분 기본 임계값
- 자유형 생활 환경 편집 위치
- 첫 일반 채팅에서 2회 호출될 수 있음과 토큰 합산
- `··· → 생활` 날짜 조회와 최신 기록만 재생성 가능
- 런타임 파일 세 개와 백업 권장
- 손상 파일·빈 world·생성 실패 시 일반 채팅은 계속됨

문서 예시는 중립적인 합성 문장만 사용한다.

- [ ] **Step 4: 집중 테스트 실행**

Run:

```text
python -m pytest tests/test_life_session_tracker.py tests/test_life_record_types.py tests/test_life_record_manager.py tests/test_life_record_prompt.py tests/test_life_record_llm_contract.py tests/test_life_record_http_native_providers.py tests/test_life_record_http_format_parity.py tests/test_life_record_chat_context.py tests/test_life_record_request_gate.py tests/test_life_record_bridge_flow.py tests/test_life_record_regeneration.py tests/test_life_record_settings_ui.py tests/test_life_record_panel_assets.py tests/test_life_record_ui_states.py tests/test_life_record_app_lifecycle.py tests/test_life_record_end_to_end.py -q
```

Expected: PASS.

- [ ] **Step 5: 전체 회귀 테스트 실행**

Run: `python -m pytest -q`

Expected: PASS, 기존 테스트 실패 0개.

- [ ] **Step 6: UTF-8 BOM과 런타임 파일 추적 여부 확인**

Run:

```powershell
$committedChanged = @(git diff --name-only "codex-ene-life-record-v1-base..HEAD")
$stagedChanged = @(git diff --cached --name-only --diff-filter=ACMR)
$workingChanged = @(git diff --name-only --diff-filter=ACMR)
$changed = @($committedChanged + $stagedChanged + $workingChanged | Sort-Object -Unique)
$withBom = foreach ($path in $changed) { if (Test-Path -LiteralPath $path) { $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path)); if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $path } } }
if ($withBom) { $withBom; throw 'UTF-8 BOM이 포함된 변경 파일이 있습니다.' }
$trackedRuntime = @(git ls-files -- life_records.json life_session_state.json prompts/life_world.md)
if ($trackedRuntime) { $trackedRuntime; throw '런타임 파일이 Git에 추적되고 있습니다.' }
```

Expected: 예외와 파일 출력 없음.

- [ ] **Step 7: 공개 저장소 개인정보 후보 검색**

Run:

```powershell
$committedChanged = @(git diff --name-only "codex-ene-life-record-v1-base..HEAD")
$stagedChanged = @(git diff --cached --name-only --diff-filter=ACMR)
$workingChanged = @(git diff --name-only --diff-filter=ACMR)
$changed = @($committedChanged + $stagedChanged + $workingChanged | Sort-Object -Unique)
foreach ($path in $changed) { if (Test-Path -LiteralPath $path) { rg -n "(?i)(sk-[a-z0-9_-]{20,}|AIza[a-z0-9_-]{20,}|api[_-]?key\s*[:=]\s*['\"][^'\"]+|secret\s*[:=]\s*['\"][^'\"]+)" -- $path } }
foreach ($path in $changed) { if (Test-Path -LiteralPath $path) { rg -n "(실제 대화|건강|취업|자소서|일정|생일|직업|전공|user_profile|calendar\.json|diary\.json)" -- $path } }
```

Expected: 첫 검색은 0건. 두 번째 검색은 구현상 필요한 일반 키 이름도 잡힐 수 있으므로 모든 결과를 사람이 검토하고, 실제 사용자 이름·실제 대화 문장·건강/일정/취업/프로필 정보가 없음을 확인한다.

- [ ] **Step 8: diff와 최종 상태 검토**

Run: `git diff --check`

Expected: 출력 없음.

Run: `git status --short`

Expected: 의도한 소스·테스트·README 변경만 표시되고 런타임 파일과 빌드 산출물은 없음.

- [ ] **Step 9: 최종 커밋**

```text
git add tests/test_life_record_end_to_end.py README.md README.ko.md README.ja.md
git commit -m "test: verify ENE life record workflow"
```

- [ ] **Step 10: 기준 태그 정리와 최종 상태 확인**

Run:

```powershell
git tag -d codex-ene-life-record-v1-base
git status --short
```

Expected: 로컬 기준 태그 삭제 성공. 의도하지 않은 변경·런타임 파일·빌드 산출물 없음.

## 최종 수동 검증 체크리스트

- [ ] 새 설치 기본값에서 생활 기록이 생성되지 않고 기존 채팅이 동일하게 동작한다.
- [ ] 기능을 켜고 생활 환경을 저장한 뒤 ENE를 정상 종료한다.
- [ ] 가상 또는 조정된 clock으로 60분 미만 복귀는 생성하지 않고 정확히 60분은 생성한다.
- [ ] 전날 23:00 종료, 다음 날 10:00 첫 일반 채팅에서 11시간 전체가 공백 없이 표시된다.
- [ ] 앱만 먼저 실행해 두었다가 나중에 채팅하면 종료 시각부터 그 첫 채팅 시각까지 기록된다.
- [ ] `/note`, `/obs`, `/diary` 후 첫 일반 채팅에서 한 번 생성된다.
- [ ] 첫 첨부 채팅도 동일하게 한 번 생성된다.
- [ ] 생성 화면이 `복귀 기록 정리 중…`에서 `생각 중…`으로 전환되고 첫 답변이 최신 기록을 안다.
- [ ] 첫 답변 리롤과 첫 메시지 수정은 생활 기록을 자동 재생성하지 않는다.
- [ ] `··· → 생활`에서 오늘·이전·다음·날짜 선택이 동작하고 자정 넘김 기록이 양쪽 날짜에 전체로 보인다.
- [ ] 최신 카드만 재생성 버튼을 가지며 취소·실패 시 원본이 보존되고 성공 시 revision이 증가한다.
- [ ] 기능을 끄면 저장 데이터는 남지만 일반 대화 컨텍스트에는 들어가지 않는다.
- [ ] 빈 생활 환경, 공급자 오류, 저장 오류, 손상 기록 파일에서도 일반 채팅은 계속된다.
- [ ] 앱 강제 종료 뒤 다음 실행에서 마지막 하트비트 기준 후보가 만들어지고 약 1분 오차 안내가 성립한다.
