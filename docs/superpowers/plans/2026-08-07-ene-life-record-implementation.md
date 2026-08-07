# ENE 비활성 생활 기록 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE 프로세스가 설정한 시간 이상 비활성 상태였을 때 다음 실행 세션의 첫 일반 채팅 직전에 해당 공백 전체의 생활 기록을 생성하고, 최신 기록만 일반 대화의 임시 컨텍스트로 사용하며, 날짜별 조회와 최신 기록 수동 재생성을 제공한다.

**Architecture:** `LocalTimeContext`가 aware clock과 IANA timezone을 단일 소유하고, `AppSessionTracker`가 durable 세션 전이 뒤 복귀 후보를 한 번 복구하며, `LifeRecordManager`가 단일 권위 파일의 스키마 검증·원자 저장·날짜 조회·최신 기록 교체를 책임진다. `LifeRecordPromptBuilder`와 공급자 공통 one-shot API가 히스토리 없는 구조화 생성을 수행한다. `LifeRecordBridgeMixin`의 공통 operation arbiter는 텍스트·첨부·명령·리롤·수정·재생성·자동 작업을 상호 배제하고 첫 일반 요청을 잠시 보류한 뒤 기록 생성 성공 여부와 무관하게 기존 답변 흐름을 정확히 한 번 재개한다. 최신 성공 기록 한 개는 사용자 주도의 일반 텍스트·첨부·리롤·수정 요청에만 명시적으로 opt-in한 임시 블록으로 주입하고 SDK/HTTP 히스토리와 `conversation_buffer`에는 저장하지 않는다.

**Tech Stack:** Python 3, PyQt6/QWebEngine, pytest, JavaScript(Node 기반 자산 테스트), JSON/Markdown 런타임 파일, 기존 Gemini·OpenAI·Anthropic·Ollama·사용자 지정 HTTP 공급자 계층

---

## 작업 원칙과 완료 기준

- 모든 테스트 fixture와 문서 예시는 2099년의 가상 장소·가상 활동만 사용한다.
- 새 파일과 수정 파일은 UTF-8 without BOM으로 유지한다.
- `life_records.json`, `life_session_state.json`, `prompts/life_world.md`와 AGENTS.md에 열거된 모든 런타임·비밀 파일은 커밋하지 않는다.
- 생성 프롬프트, ENE 프로필 원문, 기분 설명, 활동 문장, 첫 채팅 내용은 로그에 남기지 않는다.
- 각 작업은 실패 테스트 작성 → 실패 확인 → 최소 구현 → 통과 확인 → 해당 범위 커밋 순서로 진행한다.
- 전체 기능 완료 전에는 기존 2D 월드 코드를 재사용하거나 확장하지 않는다. 이번 V1은 텍스트 생활 기록만 다룬다.

### 모든 커밋에 적용하는 필수 사전 검사

구현을 시작하기 직전에 tracked tree와 staged 경로·내용의 비밀값 후보를 먼저 검사한 뒤 로컬 전용 기준 태그를 만든다. 같은 이름의 태그가 이미 있으면 기존 태그를 덮어쓰지 말고 원인을 확인한다.

```powershell
$secretPattern = @'
(?i)(sk-[a-z0-9_-]{20,}|AIza[a-z0-9_-]{20,}|api[_-]?key\s*[:=]\s*["'][^"']+|secret\s*[:=]\s*["'][^"']+)
'@
$privacyPattern = @'
(실제 대화|건강|취업|자소서|일정|생일|직업|전공|user_profile|calendar\.json|diary\.json)
'@
$trackedFiles = @(git ls-files)
foreach ($path in $trackedFiles) {
    if (Test-Path -LiteralPath $path) {
        rg -n $secretPattern -- $path
        if ($LASTEXITCODE -eq 0) { throw "tracked tree 비밀값 후보: $path" }
        if ($LASTEXITCODE -ge 2) { throw "tracked tree 검색 실패: $path" }
    }
}
($trackedFiles -join "`n") | rg -n $privacyPattern
if ($LASTEXITCODE -ge 2) { throw 'tracked 경로 개인정보 후보 검색이 실패했습니다.' }
foreach ($path in $trackedFiles) {
    if (Test-Path -LiteralPath $path) {
        rg -n $privacyPattern -- $path
        if ($LASTEXITCODE -ge 2) { throw "tracked 개인정보 후보 검색 실패: $path" }
    }
}
git tag -l codex-ene-life-record-v1-base
git tag codex-ene-life-record-v1-base HEAD
```

Expected: secret 검색은 0건, privacy 검색 결과는 모두 일반 코드·합성 자료임을 사람이 확인, 기존 태그 조회는 출력 없음, 태그 생성 성공. 이 태그는 최종 검증 범위를 계산한 뒤 삭제하며 원격에 push하지 않는다.

각 Task의 `커밋` 단계에서는 먼저 의도한 파일만 stage한 뒤 아래 검사를 실행한다. 검사를 통과하거나 검색 결과를 사람이 안전하다고 판정하기 전에는 커밋하지 않는다.

```powershell
$stagedFiles = @(git diff --cached --name-only --diff-filter=ACMR)
$textExtensions = @('.py', '.js', '.css', '.html', '.md', '.json', '.txt', '.yml', '.yaml')
$utf8Strict = [Text.UTF8Encoding]::new($false, $true)
$invalidUtf8 = foreach ($path in $stagedFiles) {
    if ((Test-Path -LiteralPath $path) -and $textExtensions -contains [IO.Path]::GetExtension($path).ToLowerInvariant()) {
        $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path))
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $path; continue }
        try { [void]$utf8Strict.GetString($bytes) } catch { $path }
    }
}
if ($invalidUtf8) { $invalidUtf8; throw 'UTF-8 without BOM이 아닌 staged 텍스트 파일이 있습니다.' }
git diff --cached --check
$secretPattern = @'
(?i)(sk-[a-z0-9_-]{20,}|AIza[a-z0-9_-]{20,}|api[_-]?key\s*[:=]\s*["'][^"']+|secret\s*[:=]\s*["'][^"']+)
'@
$privacyPattern = @'
(실제 대화|건강|취업|자소서|일정|생일|직업|전공|user_profile|calendar\.json|diary\.json)
'@
git diff --cached --no-ext-diff --unified=0 | rg -n $secretPattern
$secretExit = $LASTEXITCODE
if ($secretExit -eq 0) { throw 'staged 내용에 비밀값 후보가 있습니다.' }
if ($secretExit -ge 2) { throw '비밀값 후보 검색 명령이 실패했습니다.' }
($stagedFiles -join "`n") | rg -n $secretPattern
$pathExit = $LASTEXITCODE
if ($pathExit -eq 0) { throw 'staged 경로명에 비밀값 후보가 있습니다.' }
if ($pathExit -ge 2) { throw '경로명 검색 명령이 실패했습니다.' }
($stagedFiles -join "`n") | rg -n $privacyPattern
if ($LASTEXITCODE -ge 2) { throw 'staged 경로 개인정보 후보 검색이 실패했습니다.' }
git diff --cached --no-ext-diff --unified=0 | rg -n $privacyPattern
if ($LASTEXITCODE -ge 2) { throw '개인정보 후보 검색 명령이 실패했습니다.' }
```

첫 번째 `rg`는 비밀값 후보가 0건이어야 한다. 두 번째는 코드상 일반 키 이름도 잡힐 수 있으므로 모든 결과를 확인해 실제 사용자 정보·실제 대화 재사용이 없음을 확인한다. 계획에 적힌 각 `git add`는 이 검사보다 먼저, `git commit`은 검사보다 나중에 실행한다.

## Task 1: 원자적 JSON 저장 기반 추가

**Files:**
- Modify: `src/core/app_paths.py`
- Modify: `tests/test_app_paths.py`
- Modify: `.gitignore`

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

- Store Python은 visible Roaming 파일이 유일한 authoritative 파일이고 runtime 파일은 cache임
- visible 저장은 PowerShell 내부에서 같은 디렉터리의 고유 임시 파일 생성 → flush/`FlushFileBuffers` → 원자 rename → 임시 파일 정리 순서로 수행
- visible 교체 실패 시 기존 visible bytes 보존, runtime·메모리 미갱신, 예외 전달
- visible 교체 성공 뒤 runtime cache 갱신 실패는 저장 성공이며 현재 프로세스와 재시작 모두 새 visible 값을 읽음
- stale runtime cache가 visible 파일을 덮어쓰지 않음
- visible authoritative가 손상됐을 때 정상처럼 보이는 runtime cache로 fallback하지 않고 손상 상태를 노출
- valid stale runtime cache가 있어도 visible authoritative가 없으면 `missing`, PowerShell read가 실패하면 `read_error`로 구분하고 cache를 반환·갱신하지 않음
- 일반 환경은 전달받은 target을 authoritative 파일로 삼아 Python same-directory temp + flush/fsync + `os.replace` 사용
- 각 교체 단계 crash와 orphan temp가 있어도 권위 파일은 이전/새 완성본 중 하나이고 다음 시작 때 orphan temp를 안전하게 정리

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_app_paths.py -q`

Expected: `save_json_data_atomic` import 또는 속성 부재로 FAIL.

- [ ] **Step 3: 같은 디렉터리 임시 파일과 `os.replace` 기반 최소 구현**

`src/core/app_paths.py`에 아래 계약을 추가한다.

```python
def save_json_data_atomic(path: Path, data: object) -> None:
    """JSON을 UTF-8(BOM 없음) 임시 파일에 쓴 뒤 원자적으로 교체한다."""
```

기존 경로 준비·가상화 규칙을 재사용하되 권위 저장소를 하나로 고정한다. 일반 환경에서는 target에 Python atomic replace를 수행한다. Store Python read는 visible authoritative 파일만 판정한다. visible이 없으면 데이터 없음, 읽기·검증에 실패하면 손상/읽기 오류이며 두 경우 모두 기존 runtime cache로 fallback하지 않는다. authoritative read 성공 뒤에만 runtime cache를 refresh한다. Store Python save는 기존 PowerShell 우회 계층 안에서 visible 파일을 먼저 원자 교체하고 성공 뒤 runtime cache를 best-effort로 갱신한다. cache 실패를 authoritative commit 실패로 되돌리지 않으며 다음 성공 read가 visible에서 cache를 복구한다. 모든 임시 파일명은 충돌하지 않아야 하고 성공·실패 뒤 정리한다.

같은 Task에서 `.gitignore`에 `prompts/life_world.md`, `life_records.json`, `life_session_state.json`, `life_session_state.lock`, `.env*`, `diary.json`을 추가한다. 기존 정책의 다른 런타임 파일이 이미 ignore되는지도 테스트하고 누락된 항목만 최소 수정한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_app_paths.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/app_paths.py tests/test_app_paths.py .gitignore
git commit -m "feat: add atomic JSON persistence"
```

## Task 1B: aware clock·IANA timezone 기반 추가

**Files:**
- Create: `src/core/local_time.py`
- Create: `tests/test_local_time.py`
- Modify: `requirements.txt`
- Modify: `scripts/build_windows_release.py`
- Modify: `tests/test_build_windows_release.py`

- [ ] **Step 1: Windows·DST·정밀도 실패 테스트 작성**

`tzlocal`이 반환한 현지 이름을 `zoneinfo.ZoneInfo`로 검증하고, `tzdata`가 시스템 zone database가 없는 Windows에서도 `Asia/Seoul`과 `America/New_York`를 해석하는지 확인한다. 잘못된 이름은 생성·재생성을 안전 코드 `timezone_unavailable`로 fail-closed 처리하고 읽기 전용 `view_timezone=UTC`를 반환한다. `now()`는 aware datetime이며 `canonicalize_endpoint()`는 마이크로초를 버린 정수 초를 반환한다. 봄 DST 건너뜀, 가을 `fold=0/1`, UTC 동등성 테스트를 추가한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_local_time.py tests/test_build_windows_release.py -q`

Expected: resolver·의존성·bundle 수집 부재로 FAIL.

- [ ] **Step 3: 최소 시간 서비스와 배포 의존성 구현**

```python
@dataclass(frozen=True)
class LocalTimeContext:
    timezone_name: str
    zone: ZoneInfo
    now_provider: Callable[[], datetime]

    def now(self) -> datetime: ...
    def canonicalize_endpoint(self, value: datetime) -> datetime: ...
    def local_day_bounds(self, day: date) -> tuple[datetime, datetime]: ...
```

`requirements.txt`에 `tzlocal`과 `tzdata`를 추가하고 Windows release builder가 `tzdata`를 collect하도록 고정한다. 시간 계산은 UTC, 날짜 경계·표시는 유효한 현지 IANA zone을 사용하며 해석 실패 시 열람만 UTC로 폴백하고 UI 안전 코드를 제공한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_local_time.py tests/test_build_windows_release.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/core/local_time.py tests/test_local_time.py requirements.txt scripts/build_windows_release.py tests/test_build_windows_release.py
git commit -m "feat: add local IANA time context"
```

## Task 2: 앱 세션 종료·하트비트 복구 구현

**Files:**
- Create: `src/core/life_session_tracker.py`
- Create: `tests/test_life_session_tracker.py`

- [ ] **Step 1: 세션 후보 복구 테스트 작성**

가상 clock과 임시 데이터 루트를 사용해 다음을 각각 검증한다.

- 파일 없음 또는 손상된 JSON → 후보 없음, 새 `running` 세션 저장
- Store strict read의 `missing`·`read_error`에서 stale runtime state를 후보로 사용하지 않음
- exact-key envelope, `version == 1`, UUIDv4 `session_id`, aware timestamp만 허용
- 이전 `status=stopped` → `stopped_at`과 `graceful_exit` 후보 복구
- 이전 `status=running` → `last_seen_at`과 `heartbeat_recovery` 후보 복구
- 시작 즉시 새 `session_id`, `started_at`, `last_seen_at`, `status=running`, `stopped_at=null` 저장
- `running`은 `stopped_at=null`, `stopped`는 UTC 기준 `started_at <= last_seen_at <= stopped_at`
- 새 `running` authoritative commit 실패 → 이전 후보 폐기, tracker degraded, 해당 세션 자동 생성 비활성화
- `heartbeat()`는 현재 세션의 `last_seen_at`만 갱신
- `stop_session()`은 `status=stopped`, `last_seen_at`, `stopped_at`을 한 번에 저장
- heartbeat/stop 직전 디스크 session ID가 자기 ID와 다르면 stale write 거부
- `life_session_state.lock`의 프로세스 수명 lease를 먼저 획득하고 두 tracker 인스턴스 경쟁에서 한쪽만 활성화; lease 실패 tracker는 degraded/candidate 없음이며 생활 기록 저장을 읽기 전용으로 표시
- 비정상 종료 뒤 QLockFile stale lock은 PID/host 판정에 따라 회수되고 다음 실행이 lease를 획득
- clock rollback은 UTC 기준 이전 `last_seen_at`보다 후퇴시키지 않고 미래 후보·잘못된 ISO 시각은 폐기
- `stop_session()` 이중 호출은 authoritative write 한 번만 수행
- session lease는 `stop_session()` 뒤에도 유지하고 최종 app teardown에서 한 번 해제
- clock rollback 종료는 `shutdown_at=max(canonical_now, persisted_last_seen_at)`으로 `last_seen_at=stopped_at` 저장
- interval 후보 endpoint는 Task 1B의 정수 초 canonicalization 사용

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

`InactiveStartCandidate`는 불변 dataclass로 만들고 `source`를 `Literal["graceful_exit", "heartbeat_recovery"]`로 제한한다. `AppSessionTracker`는 Task 1의 권위 원자 저장, Task 1B의 `LocalTimeContext`, `QLockFile` 기반 프로세스 수명 lease를 사용한다. lease를 얻지 못한 보조 프로세스는 `degraded=True`, candidate 없음, `life_records_writable=False`, reason=`session_lease_unavailable`로 채팅·기록 열람만 계속한다. 손상된 세션 상태는 복귀 후보로 신뢰하지 않고 “후보 없음”으로 처리한 뒤 새 유효 `running` 상태로 교체한다. 새 `running` 상태 commit이 실패하면 후보를 반환하지 않는다. heartbeat·stop 실패는 안전 코드만 남기고 채팅을 막지 않으며, stop은 멱등이다. 종료 clock이 후퇴하면 persisted last_seen을 최대값으로 사용한다. 세션 상태는 복구용 단일 슬롯이므로 별도 `.corrupt` 사본은 만들지 않는다. 진단 로그에는 오류 코드와 경로 종류만 남기며 파일 내용은 남기지 않는다.

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
- 모든 endpoint를 마이크로초 없는 정수 초로 canonicalize하고 fractional 입력을 저장하지 않음
- 같은 정수 초로 정규화되는 sub-second 입력은 캡처 단계부터 같은 endpoint로 취급하며 ID 계산과 exact validator가 같은 값을 사용
- 순서·기간·동등성은 UTC 변환 뒤 수행
- `America/New_York` 봄 DST 건너뜀과 가을 `fold=0/1`, 존재하지 않는 현지 시각, instant에 맞지 않는 offset 거부
- 저장 파일 최상위 키가 정확히 `version`, `records`인지와 `version == 1`인지 검증
- 저장 레코드의 필수·추가 필드, ID 재계산 일치, 유효한 IANA timezone, source enum, 양의 revision 검증
- `created_at <= updated_at`, `inactive_started_at < returned_at`과 모든 메타데이터 시각의 timezone awareness 검증
- `mood_snapshot`은 정확히 여섯 필수 키 `label`, `valence`, `energy`, `bond`, `stress`, `short_term_mood`만 가지며 추가·누락 필드를 거부. `label`·`short_term_mood`는 비어 있지 않은 문자열, 나머지 네 값은 유한한 수치인지 검증
- 저장 레코드 내부의 entry·ending_state도 모델 출력과 같은 strict nested-field·연속성 규칙 적용
- store 전체 ID 유일성 검증과 중복 ID가 있는 기존 store 거부

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

JSON 파싱은 코드펜스 제거 정도만 허용하고, 모델 출력은 `entries`, `ending_state` 외 필드를 거부한다. 저장 파일은 별도 `parse_life_record_store(raw)`에서 `{version, records}`와 각 호스트 레코드를 완전히 역직렬화·재검증하며, Task 1B의 UTC·정수 초 helper로 저장된 `id`를 재계산해 일치해야만 허용한다. 각 timestamp offset은 record IANA timezone의 해당 instant 규칙과 일치해야 한다. 검증 오류는 프롬프트 원문을 포함하지 않는 안정적인 코드(`invalid_json`, `extra_field`, `invalid_store`, `invalid_id`, `duplicate_id`, `invalid_timezone_offset`, `gap`, `overlap`, `out_of_range` 등)로 노출한다.

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
- 날짜 경계·겹침·표시는 호출 시 전달한 현재 `view_timezone` 하나를 사용하고 record timezone은 원래 메타데이터로 보존
- DST 봄의 23시간 날짜와 가을의 25시간 날짜, 정확히 다음 자정인 반열린 경계 검증
- 자정을 넘긴 레코드는 양쪽 날짜에서 레코드 전체로 조회
- 손상된 `life_records.json`은 덮어쓰지 않고 읽기 오류 상태 유지
- Store strict read의 visible `missing`·`read_error`에서 stale runtime records를 로드하지 않음
- 저장 실패 시 메모리 최신값도 바꾸지 않음
- Store Python visible authoritative 교체 실패 시 manager 메모리 미갱신
- visible authoritative 성공·runtime cache 실패 뒤 현재 프로세스와 새 manager 재시작 모두 새 값을 읽고 stale cache가 visible을 덮어쓰지 않음
- 이미 중복 ID가 있는 store는 손상 상태이며 모든 write API가 원본 bytes를 보존하고 거부
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
    def records_overlapping_date(self, local_date: date, view_timezone: str) -> list[LifeRecord]: ...
    def previous_before(self, record_id: str) -> LifeRecord | None: ...
    def replace_latest(self, record_id: str, generated: LifeRecordOutput, updated_at: datetime) -> LifeRecord: ...
```

Task 3의 `parse_life_record_store()`로 최상위 envelope와 모든 중첩 호스트 레코드를 검증한 뒤에만 메모리에 올리고, Task 1의 authoritative commit 성공 이후에만 메모리 상태를 교체한다. runtime cache 갱신 실패는 authoritative 성공을 롤백하지 않는다. JSON 문법은 맞지만 ID·timezone·revision·중복 ID·중첩 필드가 잘못된 파일도 손상 상태로 취급하고 절대 덮어쓰지 않는다. 조회 결과는 복사 가능한 직렬화 딕셔너리로 브리지에 넘길 수 있게 별도 `to_public_dict(view_timezone, locale)`를 둔다.

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

`src/ai/prompt_config.py`에 `LIFE_WORLD_PROMPT_PATH`, 기본 파일명, `load_life_world_prompt()`, `save_life_world_prompt()`를 기존 prompt 경로 규칙에 맞춰 추가하고 `PROMPT_MARKDOWN_FILENAMES`에도 등록한다. 기존 `_sync_visible_roaming_prompt_files_to_runtime()`와 `_sync_runtime_prompt_files_to_visible_roaming()` 테스트에 이 파일의 양방향 동기화를 추가한다. `Settings.load()`는 `life_record_min_inactive_minutes`를 `int >= 1`로 정규화하고 잘못된 값은 60으로 되돌린다. 런타임 ignore는 Task 1에서 선행 완료되어야 한다.

- [ ] **Step 4: 통과 및 ignore 확인**

Run: `python -m pytest tests/test_prompt_config.py tests/test_settings.py -q`

Expected: PASS.

Run: `git check-ignore prompts/life_world.md life_records.json life_session_state.json life_session_state.lock`

Expected: 네 경로 모두 출력됨.

- [ ] **Step 5: 커밋**

```text
git add prompts/defaults/life_world.md src/ai/prompt_config.py src/core/settings.py tests/test_prompt_config.py tests/test_settings.py
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
- system instruction 포함: 현재 `base_system_prompt.md` 전체
- system instruction 제외: 일반 채팅용 `sub_prompt`, 응답 계약, 분석 부록, 메모리 컨텍스트
- 이름: 설정에 명시된 ENE·사용자 호출명만 포함
- 언어: `resolve_prompt_language()`로 해석한 `ko|en|ja` 하나를 포함하고 활동·ending state를 그 언어로 생성하도록 지시
- 포함: 현재 `life_world.md` 전체, exact interval·IANA timezone·현지 날짜/요일, 직전 레코드 한 개, 선캡처 mood snapshot, 복귀 사실, 최대 24개/전 구간 규칙
- 기간별 세분화 지시: 1일 이하는 30분~수시간, 1일 초과 7일 이하는 수시간~하루, 7일 초과는 여러 날 단위의 반복 생활 요약
- 수동 재생성: 대상 레코드가 아니라 그 바로 전 레코드만 포함
- mood adapter: `current_mood`, `temporary_state`, 네 축을 canonical `label`, `short_term_mood`, 네 유한 수치로 정확히 한 번 복사하고 `calm`, `steady` 같은 허용 code인지 검증하며 `profile`, `expression_traits`, `updated_at`과 추가 키 차단
- 빈 world는 `LifeWorldEmptyError`로 생성 호출 전 중단

검증은 첫 채팅·프로필 상세·일정·기억 sentinel이 생활 기록용 user prompt에 없음을 직접 확인한다. `base_system_prompt.md`는 별도 system instruction으로 전달하므로 이 화이트리스트 user prompt에 중복 결합하지 않는다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_prompt.py -q`

Expected: 모듈 부재로 FAIL.

- [ ] **Step 3: 명시적 DTO와 프롬프트 빌더 구현**

```python
@dataclass(frozen=True)
class LifeMoodSnapshot:
    label: str
    valence: float
    energy: float
    bond: float
    stress: float
    short_term_mood: str


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
    mood_snapshot: LifeMoodSnapshot
    language: Literal["ko", "en", "ja"]


def snapshot_life_mood(raw_snapshot: Mapping[str, object]) -> LifeMoodSnapshot: ...
def build_life_record_prompt(context: LifeRecordGenerationContext) -> str: ...
```

`ene_profile.py`에는 생활 기록 전용 export 함수를 추가하되 일반 프로필 직렬화 결과를 통째로 넘기지 않는다. 빌더가 첫 채팅 내용을 받을 수 없는 시그니처 자체로 개인정보 경계를 고정한다. mood adapter는 정확히 여섯 키만 가진 불변 DTO를 만들고 문자열·유한 수치를 검증한다. 언어는 gate가 요청 수락 시 한 번 해석한 값을 받으며 빌더 내부에서 전역 설정을 다시 읽지 않는다.

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
- Modify: `src/ai/prompt.py`
- Create: `tests/test_life_record_llm_contract.py`
- Modify: `tests/test_llm_provider.py`
- Modify: `tests/test_llm_privacy_logging.py`

- [ ] **Step 1: 히스토리 없는 생성 계약 테스트 작성**

다음을 검증한다.

- `LLMRequestKind.LIFE_RECORD` 존재
- 공통 `LLMClientProtocol`과 Gemini client가 `generate_life_record_once(prompt)` 비동기 계약 제공
- 현재 `base_system_prompt.md`가 system instruction에 포함됨
- `sub_prompt`, 일반 응답 계약, 분석 부록, 일반 채팅 메모리 컨텍스트는 system instruction과 user payload에 포함되지 않음
- 기본 프롬프트 뒤에 고정 생활 기록 작업 계약을 배치해 충돌하는 말투·출력 형식보다 JSON 계약을 우선
- Gemini는 `entries`와 `ending_state`만 허용하는 response schema 사용
- Gemini SDK가 native schema capability를 명시적으로 거부하면 같은 내용 생성 시도 안에서 strict JSON text config로 한 번 fallback하고 양쪽 사용량 합산
- Gemini native와 fallback의 실제 `generate_content` config가 동일한 base-first·life-contract-last system instruction을 사용
- `ResponseCapabilityKey`가 `request_kind + schema_id + schema_version`을 모두 포함하고 Gemini FINAL_REPLY native/legacy cache와 LIFE_RECORD native/strict cache가 양방향으로 오염되지 않음
- SDK 대화 히스토리를 읽거나 쓰지 않는 one-shot 호출
- provider는 원문과 토큰 사용량만 반환하고 출력 검증·재시도를 수행하지 않음
- one-shot 결과는 text뿐 아니라 `status`, `finish_reason`, 정규화된 usage를 보존하고 refusal·incomplete·max_tokens를 COMPLETE 출력과 구분
- `prompt`, system instruction, raw response는 `repr`, 로그, 예외에 없음

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

`prompt.py`에 `build_life_record_system_instruction(settings_source)`를 추가한다. 이 함수는 `base_system_prompt.md`만 읽고 그 뒤에 고정 생활 기록 작업 계약을 붙이며, `sub_prompt`, 일반 응답 계약, 분석 부록을 호출하지 않는다. 고정 계약은 충돌 시 생활 기록의 행동·JSON 규칙을 우선한다고 명시한다. `response_protocol.py`의 capability key를 이 Task에서 `request_kind`, `schema_id`, `schema_version`까지 확장하고 Gemini 일반 응답과 생활 기록 호출부가 각각 정확한 key를 만든다.

`llm_provider.py`의 공통 Protocol과 Gemini client·필요한 Gemini 테스트 double에 `generate_life_record_once`를 추가한다. HTTP 실제 구현 완료 조건은 Task 8A/8B가 소유한다. `llm_client.py`는 기존 `_generate_one_shot_text`의 historyless transport를 재사용하되 `build_life_record_system_instruction()`을 받는 LIFE_RECORD 전용 config를 만들고 일반 final-response 파서를 통과시키지 않는다. 이 API는 한 번의 모델 내용 생성 시도와 status·finish reason·토큰 정규화만 책임진다. transport가 명시적 native capability 거부를 반환해 JSON text wire 형식으로 대체하는 것은 같은 내용 생성 시도 안의 최대 1회 협상으로 보며, 그 과정의 사용량도 결과에 합산한다. refusal·incomplete·max_tokens는 validator로 넘기지 않는다. exact interval·timezone을 가진 내용 검증, 오류 코드 재프롬프트, COMPLETE 출력의 host validation 실패에 한정한 최대 1회 내용 재시도는 Task 10B의 `LifeRecordWorker`만 담당한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_llm_contract.py tests/test_llm_provider.py tests/test_llm_privacy_logging.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/response_protocol.py src/ai/llm_provider.py src/ai/llm_client.py src/ai/prompt.py tests/test_life_record_llm_contract.py tests/test_llm_provider.py tests/test_llm_privacy_logging.py
git commit -m "feat: add structured life record generation"
```

## Task 8A: HTTP 공통 one-shot 계약과 OpenAI·Anthropic 구현

**Files:**
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_openai.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_http_llm_privacy_logging.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_life_record_http_native_providers.py`

- [ ] **Step 1: 공급자별 요청 모양 테스트 작성**

가짜 transport로 다음을 고정한다.

- OpenAI Chat/Responses: native JSON schema 사용 가능 시 엄격 schema 적용
- Anthropic: 기존 provider 계약과 같은 `output_config.format` JSON schema로 동일 schema 강제
- 호출당 네트워크 요청은 정확히 한 번이며 validator·재시도는 실행하지 않음
- 대화 히스토리 payload에 생성 요청이 섞이지 않음
- 모든 native HTTP payload가 현재 기본 시스템 프롬프트와 고정 생활 기록 계약을 포함하고 `sub_prompt`·일반 응답 계약·분석 부록·일반 채팅 메모리 컨텍스트는 제외
- 각 HTTP 응답의 input/output/total usage를 공통 형식으로 정규화하고 공급자가 제공하지 않은 값은 `None`으로 유지하며 0으로 위조하지 않음
- HTTP 4xx/5xx, JSON decode, capability 거부에서 prompt·system·raw response sentinel을 repr·stdout·stderr·예외에 포함하지 않음
- `tests/conftest.py`가 새 life-record HTTP 모듈 전후의 process-global capability cache를 명시적으로 초기화

공통 요청 객체를 먼저 테스트한다.

```python
request = StructuredOneShotRequest(
    kind=LLMRequestKind.LIFE_RECORD,
    prompt="합성 생성 지시",
    system_instruction="합성 기본 성격\n\n생활 기록 전용 계약",
    schema=LIFE_RECORD_OUTPUT_SCHEMA,
)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_http_native_providers.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_privacy_logging.py -q`

Expected: LIFE_RECORD 처리 부재로 FAIL.

- [ ] **Step 3: 최소 공통 descriptor와 transport 분기 구현**

`http_llm_common.py`에 `prompt`, `system_instruction`, raw response가 모두 `repr=False`이고 예외 안전한 one-shot 구조화 요청·응답 descriptor를 둔다. OpenAI Chat/Responses에는 native JSON schema를, Anthropic에는 기존 `output_config.format` JSON schema를 추가한다. system instruction은 Task 7의 `build_life_record_system_instruction()` 결과만 사용한다. 일반 채팅용 final-response 파서를 공유하지 말고, 네트워크 호출·status·finish reason·토큰 정규화 코드만 재사용한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_http_native_providers.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_privacy_logging.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/http_llm_common.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py tests/conftest.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_privacy_logging.py tests/test_life_record_http_native_providers.py
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
- Modify: `tests/conftest.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_http_llm_structured_outputs.py`

- [ ] **Step 1: wire format별 capability 테스트 작성**

공급자 표시 이름이 아니라 실제 wire format과 capability를 기준으로 다음을 고정한다.

- Ollama: 기존 `format` JSON schema 기능을 우선 사용
- custom OpenAI Chat/Responses: native JSON schema 우선
- custom Anthropic: 공식 Anthropic endpoint/profile로 확인된 경우에만 `output_config.format` schema 우선
- custom Ollama: native `format` schema 우선
- custom Mistral·Google Cloud·Cohere: 해당 transport가 지원하는 구조화 형식을 우선
- 임의 custom endpoint는 표시 wire 이름만으로 native로 승격하지 않고, 정확한 공식 endpoint/profile 또는 검증된 registry capability가 없으면 처음부터 strict JSON 텍스트 요청을 한 번 수행
- native 요청이 명시적 capability 거부로 실패한 경우에만 같은 내용 생성 시도 안에서 strict JSON 텍스트로 한 번 fallback하고, 양쪽에 토큰 사용량이 있으면 합산
- fallback도 히스토리 없는 one-shot이며 provider 내부 검증·재시도 없음
- capability key에 `request_kind + schema_id + schema_version`을 모두 포함해 일반 FINAL_REPLY structured capability 캐시와 완전히 분리
- 생활 기록 native 거부가 일반 답변을 legacy로 낮추지 않고, 일반 답변의 cached legacy 상태도 생활 기록 native 시도를 막지 않음
- Task 8A/8B 완료 시 Gemini를 제외한 모든 실제 HTTP client class가 공통 `generate_life_record_once` 계약을 충족
- Ollama·Mistral·Google Cloud·Cohere와 모든 custom wire format의 native, 처음부터 strict JSON, capability 거부 후 fallback 실제 payload가 동일한 base-first·life-contract-last system instruction을 유지
- 각 wire payload의 system carrier와 user body 모두에 `sub_prompt`·일반 응답 계약·분석 부록·메모리 sentinel이 없음
- 각 wire 응답의 usage·status·finish reason을 보존하고 native+fallback usage를 합산하되 미제공 값은 `None`
- FINAL_REPLY native/legacy 상태와 LIFE_RECORD native/strict 상태가 양방향으로 cache를 오염시키지 않음

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_http_format_parity.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_structured_outputs.py -q`

Expected: LIFE_RECORD capability routing 부재로 FAIL.

- [ ] **Step 3: capability 기반 payload 분기 구현**

기존 response capability registry와 검증된 endpoint/profile 정보를 재사용해 `StructuredOneShotRequest`를 native schema 또는 strict JSON text로 직렬화한다. Task 7에서 확장한 capability key에 각 HTTP 요청의 request kind·schema ID·version을 넣는다. capability 거부 fallback은 같은 provider의 기존 오류 분류가 명시적 미지원을 판정한 경우에만 최대 한 번 수행하고 `StructuredOneShotRequest.system_instruction`을 그대로 유지하며 일반 `build_runtime_system_prompt()`로 다시 조립하지 않는다. 응답 status·finish reason·usage는 보존하되 응답·프롬프트 원문은 repr·예외·로그에 넣지 않는다.

`tests/test_life_record_http_format_parity.py`는 wire format별 실제 요청 payload를 캡처한다. `messages[0].content`, `instructions`, `system`, `systemInstruction.parts[].text`, `preamble` 등 각 공급자의 system carrier에서 현재 base 전체가 먼저, 고정 생활 기록 계약이 뒤에 있는지 확인한다. native 성공, 처음부터 strict JSON, native capability 거부 후 fallback을 각각 검증하고 system·user 양쪽에 제외 sentinel이 없음을 확인한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_http_format_parity.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_structured_outputs.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/http_llm_common.py src/ai/http_llm_ollama.py src/ai/http_llm_custom_providers.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py tests/conftest.py tests/test_life_record_http_format_parity.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_structured_outputs.py
git commit -m "feat: route life record requests by capability"
```

## Task 9: 최신 생활 기록 임시 대화 컨텍스트 구현

**Files:**
- Modify: `src/ai/memory_context_builder.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/core/bridge_workers.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Modify: `src/core/bridge_mixins/attachments.py`
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
- record block은 사용자 주도의 일반 텍스트·첨부 대화 요청에 포함
- 사용자 일반 FINAL_REPLY 텍스트·첨부와 그 리롤·수정만 명시적 opt-in
- `/note`, `/diary`, Markdown 생성, SUMMARY·DECISION·기타 one-shot, 약속·선제·자리비움은 기본값으로 비포함
- `history_user_content`는 원래 사용자 메시지이고 생활 기록 블록이 아님
- SDK/HTTP history와 `conversation_buffer`에는 생활 기록 텍스트가 축적되지 않음
- 리롤은 실행 시점의 최신 저장 기록을 다시 읽음
- `memory_manager`가 없어도 생활 기록 블록은 조기 return 전에 포함
- Gemini와 HTTP client에 manager를 바인딩했을 때 동일한 블록이 생성됨
- request scope는 불변 요청 값이며 동시 요청 중 전역 client flag를 변경하지 않음

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

`build_memory_context(client, ..., include_life_record_context: bool = False)`와 provider-neutral send request에 기본 `False`인 명시적 scope를 추가한다. `chat_flow.py`·`attachments.py`의 사용자 요청 `_start_ai_worker`/첨부 worker 생성과 리롤·수정 경로만 불변 request에 `include_life_record_context=True`를 넣는다. `/note`, `/diary`, Markdown·summary·decision one-shot과 약속·선제·자리비움 worker는 기본값을 유지한다. opt-in일 때만 진입 직후 `client.life_record_manager`와 `client.settings`를 읽어 블록을 가장 먼저 조합한다. `memory_manager`가 없는 조기 return에서도 블록을 보존하고, 기존 `history_user_content=original_message` 경계를 바꾸지 않는다. manager 부재·읽기 오류는 빈 블록으로 처리하며 전역 client 상태는 바꾸지 않는다. Task 14에서는 동일 manager를 실제 Gemini 또는 HTTP `llm_client.life_record_manager`에 명시적으로 바인딩한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_chat_context.py tests/test_bridge_context_compaction.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ai/memory_context_builder.py src/ai/llm_provider.py src/ai/llm_client.py src/ai/http_llm_common.py src/core/bridge_workers.py src/core/bridge_mixins/chat_flow.py src/core/bridge_mixins/attachments.py tests/test_life_record_chat_context.py tests/test_bridge_context_compaction.py
git commit -m "feat: inject latest life record ephemerally"
```

## Task 10A: 첫 일반 채팅 판정과 요청 보류 상태 기계 구현

**Files:**
- Create: `src/core/bridge_mixins/life_records.py`
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Modify: `src/core/bridge_mixins/attachments.py`
- Modify: `src/core/bridge_mixins/promise.py`
- Modify: `src/core/bridge_mixins/proactive.py`
- Modify: `src/core/bridge_mixins/away.py`
- Create: `tests/test_life_record_request_gate.py`
- Modify: `tests/test_chat_attachments.py`
- Modify: `tests/test_bridge_attachment_slots.py`

- [ ] **Step 1: 첫 요청 상태 기계 테스트 작성**

가짜 manager/mood와 prepared request를 사용해 다음을 검증한다.

- `/note`, `/obs`, `/diary`는 생활 기록 후보를 소비하지 않음
- 첫 일반 텍스트와 첫 첨부 채팅은 후보를 소비함
- 기능 꺼짐, 후보 없음, 59분, 0분 이하, 빈 world는 LLM 호출 없이 즉시 기존 답변 시작
- `life_records_writable=False`와 사유 코드별(session lease 없음, timezone 없음, tracker degraded) 자동 생성 차단·기존 기록 context 유지. timezone 없음만 UTC view로 폴백하고 나머지는 유효한 현재 view timezone 유지
- 정확히 60분은 생성 시도
- 복귀 종료 시각은 앱 시작이 아니라 첫 일반 채팅 수신 시각
- 텍스트·첨부 slot 최상단에서 Task 1B clock의 정수 초 `received_at` 캡처; 첨부 파싱에 지연이 있어도 같은 값 유지
- mood snapshot은 `mood_manager.on_user_message()` 전에 캡처
- `snapshot_life_mood()`가 정확히 여섯 canonical 필드만 불변 복사하고 raw `profile`, `expression_traits`, `updated_at` 제외
- 요청 수락 시 `resolve_prompt_language()`를 한 번 호출해 `ko|en|ja`를 prepared request에 고정; invalid/auto locale도 resolved 값으로 정규화
- 동일 실행 세션에서 성공/실패/생략 뒤 자동 판정은 한 번뿐
- 첫 답변 리롤과 첫 사용자 메시지 수정·재전송은 자동 생성을 다시 예약하지 않음
- 판정 대상이면 conversation append, `on_user_message`, AIWorker 시작 전에 prepared request를 정확히 한 개 보류
- `idle` 외 상태에서 두 번째 text·attachment·slash·reroll·edit·manual regeneration을 부수효과 전에 거부
- 거부 요청은 calendar count, head-pat drain, mood, conversation, attachment session, 후보 상태를 변경하지 않음
- 자동 생성 중 promise·proactive·away tick은 공통 arbiter 때문에 시작되지 않음
- idle의 도구 명령은 후보를 소비하지 않지만 busy 상태의 명령은 실행하지 않음
- Python stage allow-list가 `life_record`, `life_record_regeneration`, `thinking`, 기존 `searching`을 보존
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

`LifeRecordBridgeState`에는 후보, 자동 판정 완료 여부, `life_records_writable`, 안정적인 read-only 사유 코드, phase(`idle|auto_generating|resuming_reply|normal_reply|manual_regenerating|shutting_down`), 단조 증가 `operation_id`, 보류된 prepared request, 별도 life worker 참조, 선행 token usage를 둔다. phase 변경은 GUI 스레드에서만 수행한다. `try_begin_operation()`, `matches_operation()`, `take_pending()`으로 모든 진입점과 callback을 통제하고 raw 사용자 본문은 로그에 쓰지 않는다. writable capability·기능 설정·정규화된 임계값·candidate·world 존재·구간 양수를 순서대로 판정하고 어떤 결과든 해당 세션의 자동 판정은 완료 처리한다.

- [ ] **Step 4: 텍스트·첨부 공통 진입점으로 최소 리팩터링**

`chat_flow.py`와 `attachments.py`는 slot 진입 즉시 `received_at`을 캡처하고 arbiter busy 검사를 어떤 명령 판정·캘린더·첨부 파싱보다 먼저 수행한다. idle이면 도구 명령을 기존 흐름으로 보내며 후보는 소비하지 않는다. 일반 요청이면 첨부·mood·token·head-pat 입력을 deep copy한 불변 요청을 만든다.

```python
@dataclass(frozen=True)
class PreparedChatRequest:
    received_at: datetime
    language: Literal["ko", "en", "ja"]
    mood_snapshot: LifeMoodSnapshot
    # 원문, 첨부, head-pat, token 등 일반 응답 commit에 필요한 불변 snapshot


def _dispatch_general_request(self, prepared_request: PreparedChatRequest) -> None:
    """필요하면 생활 기록을 먼저 만든 뒤 준비된 일반 요청을 시작한다."""
```

요청 수락 직후 away 활동 시각을 갱신하고 대기 proactive를 취소한다. conversation append, `on_user_message`, `_last_request_payload`, head-pat drain, calendar count, attachment session 변경, AIWorker 시작은 생활 기록 판정 후 기존 순서를 유지하는 단일 idempotent commit 함수로 모은다. 기존 GUI 스레드 `worker.wait()` 경로는 제거하고 busy 요청을 거부한다. promise·proactive·away의 idle 판정도 `self.worker.isRunning()`이 아니라 같은 arbiter를 사용한다.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_life_record_request_gate.py tests/test_chat_attachments.py tests/test_bridge_attachment_slots.py -q`

Expected: PASS.

- [ ] **Step 6: 커밋**

```text
git add src/core/bridge_mixins/life_records.py src/core/bridge_state.py src/core/bridge.py src/core/bridge_mixins/chat_flow.py src/core/bridge_mixins/attachments.py src/core/bridge_mixins/promise.py src/core/bridge_mixins/proactive.py src/core/bridge_mixins/away.py tests/test_life_record_request_gate.py tests/test_chat_attachments.py tests/test_bridge_attachment_slots.py
git commit -m "feat: gate the first chat for life records"
```

## Task 10B: 생활 기록 worker·저장·답변 재개 파이프라인 구현

**Files:**
- Modify: `src/core/bridge_workers.py`
- Modify: `src/core/bridge_mixins/life_records.py`
- Modify: `src/core/bridge_state.py`
- Modify: `src/core/bridge.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Modify: `src/core/bridge_mixins/tts.py`
- Create: `tests/test_life_record_bridge_flow.py`
- Modify: `tests/test_bridge_token_usage.py`
- Modify: `tests/test_bridge_tts_streaming.py`

- [ ] **Step 1: 생성·재시도·답변 재개 테스트 작성**

다음을 검증한다.

- exact signal/event 순서: 시작 `stage=life_record → pending=True`; 성공 `save → items_updated → stage=thinking → answer worker`; 실패 `notice → stage=thinking → answer worker`; 중간 `pending=False` 없음
- prompt 생성 → `generate_life_record_once` → exact interval/timezone validator 순서
- 첫 출력 검증 실패 시 오류 코드만 추가해 정확히 한 번 재호출하고 두 번째 성공 저장
- 내용 재시도는 `status=COMPLETE` 응답의 host validation 실패에만 한 번 허용하고 refusal·incomplete·max_tokens·LLM 오류는 재시도하지 않음
- 첫 시도와 두 번째 시도의 모든 생성 토큰을 누적해 일반 답변의 prior token usage에 전달
- 생성 성공은 원자 저장 성공 뒤에만 새 최신 기록을 답변 컨텍스트로 사용
- 검증/LLM/저장 실패는 기존 최신 기록이 있으면 그것을, 없으면 무기록으로 보류 요청 재개
- 생성 중 사용자 입력과 중복 생성 잠금
- `life_record_state.worker`가 자동·수동 worker를 `finished`까지 강하게 소유하고 기존 `self.worker`는 일반 답변·명령 전용
- result/error/finished 순서 교차와 중복 signal에서도 `take_pending(operation_id)`가 일반 답변을 정확히 한 번만 시작
- stale operation ID callback은 저장·notice·UI update·답변 재개를 모두 하지 않음
- prompt 작성, worker 생성/start, validator, manager save, UI payload 직렬화, 일반 request commit 예외가 단일 finalizer로 수렴
- GUI 스레드에서 `worker.wait()`를 호출하면 테스트 실패
- life worker 동안 promise·proactive·away가 idle로 오판하지 않고 보류된 일반 답변 완료 후 기존 queue drain
- `normal_reply`는 QThread 종료가 아니라 기존 응답·TTS 보류 처리와 최종 pending 해제가 끝날 때까지 유지한 뒤 `idle`로 전이
- non-TTS 성공·오류와 TTS 성공·오류 각각 operation ID가 일치할 때 최종 pending 정리 뒤 `idle` 전이·queue drain을 정확히 한 번 수행
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

Run: `python -m pytest tests/test_life_record_bridge_flow.py tests/test_bridge_token_usage.py tests/test_bridge_tts_streaming.py -q`

Expected: 전용 worker·재시도·토큰 전달 부재로 FAIL.

- [ ] **Step 3: 검증과 재시도의 단일 소유자인 worker 구현**

`LifeRecordWorker`만 정수 초 exact interval·timezone을 가진 채 Task 3 validator를 호출한다. `status=COMPLETE`인 첫 출력의 host 검증 오류일 때만 안정 오류 코드만 prompt 끝에 추가해 `generate_life_record_once`를 한 번 더 호출하고, provider 계층에서는 내용 검증이나 내용 재시도를 하지 않는다. capability 협상 usage와 두 내용 호출 usage는 제공된 값만 성공 여부와 무관하게 합산하고 미제공 필드는 `None`으로 유지한다.

- [ ] **Step 4: 저장 결과에 따른 보류 요청 재개 구현**

브리지는 manager authoritative 저장 성공을 확인한 뒤에만 새 레코드를 최신값으로 사용한다. 성공 시 활동 원문을 로그에 남기지 않고 public UI payload를 `life_record_items_updated`로 보낸다. 실패는 내부 예외 문장 대신 정해진 notice 코드만 보낸다. 자동·수동 worker는 별도 `life_record_state.worker`가 `finished`까지 소유하고 result/error는 operation ID가 일치할 때만 결과를 stash한다. 하나의 `finalize_life_record_operation()`이 결과를 확정하고 `take_pending()`으로 기존 conversation append → mood update → FINAL_REPLY opt-in AIWorker를 한 번만 시작한다. `auto_generating → resuming_reply → normal_reply` 사이에는 잠금과 pending을 유지한다. `chat_flow.py`의 non-TTS completion과 `tts.py`의 pending response finalizer가 공통 `finish_normal_operation(operation_id)`을 호출해 최종 pending 해제 후에만 idle 전이와 queue drain을 수행한다.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_life_record_bridge_flow.py tests/test_bridge_token_usage.py tests/test_bridge_tts_streaming.py -q`

Expected: PASS.

Run:

```powershell
$bridgeTests = Get-ChildItem tests -Filter 'test_bridge*.py' | ForEach-Object FullName
python -m pytest @bridgeTests -q
```

Expected: 기존 채팅·리롤·수정 흐름 회귀 없이 PASS.

- [ ] **Step 6: 커밋**

```text
git add src/core/bridge_workers.py src/core/bridge_mixins/life_records.py src/core/bridge_mixins/chat_flow.py src/core/bridge_mixins/tts.py src/core/bridge_state.py src/core/bridge.py tests/test_life_record_bridge_flow.py tests/test_bridge_token_usage.py tests/test_bridge_tts_streaming.py
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
- 재생성 구간의 현지 날짜·요일·timestamp offset·validator는 현재 view timezone이 아니라 저장된 record timezone 사용
- 현재 world와 현재 ENE 프로필 사용
- 실행 시점의 현재 resolved `ko|en|ja`를 다시 해석해 생성 언어로 사용
- 현재 `base_system_prompt.md`와 생활 기록 전용 우선 계약 사용, 일반 채팅용 `sub_prompt`·응답 계약·분석 부록·메모리 컨텍스트 제외
- 대상 자체는 이전 기록 컨텍스트에서 제외하고 바로 전 한 개만 사용
- 성공 시 같은 ID 원자 교체, `revision+1`, `updated_at` 갱신
- 실패/취소 시 기존 파일·메모리·일반 대화 컨텍스트 유지
- 재생성 중 채팅 및 중복 재생성 잠금
- 공통 arbiter가 normal→regen, auto→regen을 거부하고 regen→text/attachment/slash/reroll/edit/promise/proactive/away를 모두 부수효과 없이 거부
- `life_records_writable=False`인 lease 미보유·tracker degraded·timezone 실패 read-only 프로세스는 사유 코드로 재생성을 거부하고 원본 유지
- worker 참조는 `finished` 전까지 유지하며 stale result·취소·중복 signal은 원본과 최신 컨텍스트를 유지
- 재생성은 별도 채팅 답변을 만들지 않음
- 재생성 성공 뒤 리롤은 교체된 최신 기록을 사용
- 날짜 조회 slot은 Task 1B의 현재 `view_timezone`, resolved locale, request ID를 사용해 정렬·포맷한 public records와 전역 latest ID를 `life_record_items_updated`로 emit하고 읽기 오류는 안전한 notice 코드만 emit
- 재생성 성공도 교체된 public record·영향받는 날짜·latest ID를 emit해 열린 패널을 즉시 갱신

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_regeneration.py -q`

Expected: 브리지 slot 부재로 FAIL.

- [ ] **Step 3: 조회·재생성 slot과 signal 구현**

브리지에 최소 API를 추가한다.

```python
@pyqtSlot(str, str)
def request_life_records_for_date(self, iso_date: str, request_id: str) -> None: ...

@pyqtSlot(str)
def regenerate_latest_life_record(self, record_id: str) -> None: ...
```

signal payload는 요청 날짜·request ID·view timezone·resolved language·UI 렌더링에 필요한 public dict와 상태 코드만 전송한다. 수동 재생성은 저장된 record timezone으로 generation context를 만들고 같은 공통 arbiter와 별도 life worker 소유권을 사용하며 finalize 후에만 자동 queue를 다시 허용한다. session lease 미보유 read-only 프로세스는 조회만 허용한다. 사용자 활동 문장을 로그에 출력하지 않는다.

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
- Modify: `src/ui/settings_dialog.py`
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
- 생활 환경 편집기는 기존 2열 아래 전체 폭 카드이고 1024×768 available screen에서 설정창이 화면 밖으로 넘지 않음
- 레이블은 `setBuddy` 또는 명시적 accessible name으로 토글·분 입력·편집기와 연결

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_settings_ui.py tests/test_ui_i18n_smoke.py -q`

Expected: widget/locale key 부재로 FAIL.

- [ ] **Step 3: 기존 설정 패턴에 맞춰 UI 구현**

동작 탭의 기존 자리 비움 설정 인근에 생활 기록 그룹을 추가하고, 프롬프트 탭의 기존 편집기 공통 동작을 재사용하되 생활 환경 카드는 2열 아래 전체 폭으로 배치한다. `SettingsDialog`의 크기와 최소 크기를 현재 screen `availableGeometry` 이내로 제한한다. 라벨·입력의 buddy/accessible name을 연결한다. 설정 변경은 다음 일반 요청부터 manager가 최신값을 읽도록 하며 앱 재시작을 요구하지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_settings_ui.py tests/test_ui_i18n_smoke.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add src/ui/settings_tabs/behavior_tab.py src/ui/settings_dialog_values.py src/ui/settings_tabs/prompt_tab.py src/ui/settings_dialog_prompt.py src/ui/settings_dialog.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_ui_i18n_smoke.py tests/test_life_record_settings_ui.py
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
- renderer의 `nowProvider` 또는 Node VM의 고정 `Date`로 오늘을 결정해 시스템 날짜에 의존하지 않음
- 이전/다음/오늘/date input이 ISO 날짜를 브리지에 요청
- 선택 날짜와 겹치는 레코드를 전체 카드로 표시
- 같은 날 여러 레코드는 backend 정렬 순서 유지
- 자정 넘김 entry에는 날짜도 함께 표시
- 비어 있음과 읽기 오류 상태 분리
- 초기 loading, 기록 없음, 빈 world, 읽기·생성·저장·재생성 실패를 서로 다른 상태로 렌더링하고 빈 world는 설정 열기 행동, 재생성 실패는 원본 유지 안내 제공
- 생활 trigger의 `aria-controls/expanded`, 이름 있는 `role=region`, 열기 시 날짜 input focus, Escape/닫기 뒤 trigger focus 복귀
- 날짜 요청에 request ID를 붙이고 응답 날짜·ID가 현재 선택과 다르면 stale response 폐기
- 375×667 viewport에서 가로 overflow 없음, 날짜 행 wrap, 패널 내부 세로 scroll, 긴 문장 wrap
- 모든 날짜·닫기·재생성 조작의 44×44px hit target과 visible focus
- 조회·표시·자정 판정이 backend가 보낸 동일 view timezone을 사용
- HTML escape 적용으로 record 문자열이 markup으로 실행되지 않음

Node DOM helper의 모든 `subprocess.run()`에는 `timeout=20`을 지정하고 timeout·비정상 종료 시 stdout/stderr를 진단에 포함하되 생활 기록 원문 sentinel은 출력하지 않는다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_panel_assets.py tests/test_chat_ui_assets.py -q`

Expected: 신규 자산·DOM ID·문자열 부재로 FAIL.

- [ ] **Step 3: 패널 렌더러와 브리지 연결 구현**

`runtime_life_record_panel.js`는 날짜·request ID·loading/empty/error 상태와 카드 렌더링을 소유한다. record payload는 `textContent` 또는 기존 escape helper로만 출력한다. `runtime_bridge.js`는 `life_record_items_updated`, `life_record_notice`를 연결하고 패널을 열 때 현재 선택 날짜를 요청하며 stale 날짜·request ID 응답을 버린다. 패널/trigger ARIA와 focus lifecycle을 구현하고 CSS는 `min(420px, calc(100vw - 24px))`, 내부 scroll, wrap, 44px target, 375px 무가로스크롤을 보장한다.

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
- `life_records_writable=false` payload에서는 재생성 버튼 disabled와 안전한 read-only 사유 안내, backend 직접 호출도 동일 코드로 거부
- 확인 대화상자 취소 시 bridge 미호출, 승인 시 한 번 호출
- 확인 UI는 제목·설명이 연결된 `role=alertdialog`, 취소 기본 focus, Tab/Shift+Tab trap. 닫을 때 원래 재생성 trigger가 연결·표시 가능하면 그곳, 아니면 열린 패널의 날짜 input, 패널도 닫혔으면 생활 메뉴 trigger 순으로 focus 복귀
- 빈 world, 생성 실패, 저장/읽기 오류 안내 상태 분리
- 생성 중 `복귀 기록 정리 중…`, 일반 응답 중 `생각 중…`
- 재생성 중 `생활 기록 다시 만드는 중…`
- 진행·실패 상태는 `role=status`, `aria-live=polite`, `aria-atomic=true`
- 진행 중 textarea, send, attach, file input, edit, reroll, regenerate를 단일 lock으로 disabled; 패널 close·날짜 읽기 탐색은 허용하고 draft 보존
- 성공·실패·취소·거부·stale response에서 잠금과 기존 활성 상태를 정확히 한 번 복구
- `resolvedLanguage` 변경 시 `document.documentElement.lang`, visible 문구, ARIA 레이블, `Intl.DateTimeFormat` locale을 ko/en/ja로 함께 갱신
- 중복 클릭은 한 번의 backend 호출만 만듦

Node DOM helper는 Task 13A와 같은 고정 clock과 `timeout=20` subprocess 계약을 사용한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_ui_states.py tests/test_chat_ui_assets.py -q`

Expected: 재생성 및 life_record stage 처리 부재로 FAIL.

- [ ] **Step 3: 재생성 확인·오류 상태 구현**

`runtime_life_record_panel.js`는 latest ID와 busy state를 받아 재생성 버튼을 결정하고, 접근 가능한 alertdialog의 사용자 승인 뒤 bridge slot을 한 번만 호출한다. focus trap·복귀와 live status를 소유한다. 모든 표시·ARIA 안내 문구는 Task 12의 ko/en/ja locale key를 사용한다.

- [ ] **Step 4: 요청 단계 표시 확장**

`runtime_chat_panel_controls.js`의 stage 정규화에 `life_record`, `life_record_regeneration`, `thinking`을 추가하되 기존 검색·생각 단계 동작을 보존한다. 공통 generation lock 함수가 textarea·전송·첨부·file input·수정·리롤·재생성을 기존 활성 상태 snapshot과 함께 제어한다. stale operation 억제는 backend arbiter가 단독 소유하고 frontend에는 현재 작업의 signal만 전달한다. `runtime_bridge.js`는 idempotent local lock state로 완료·실패 signal을 정확히 한 번 복구한다. `runtime_ui_strings.js`는 backend `resolvedLanguage`로 `<html lang>`, visible/ARIA 문자열과 날짜 locale을 함께 갱신한다.

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
- Modify: `main.py`
- Modify: `src/core/app.py`
- Modify: `src/core/overlay_window.py`
- Modify: `src/core/bridge_workers.py`
- Modify: `src/core/bridge_mixins/life_records.py`
- Modify: `tests/test_app_llm_bootstrap.py`
- Modify: `tests/test_app_quit_summary.py`
- Modify: `tests/test_bridge_worker_multimodal_capability.py`
- Create: `tests/test_life_record_app_lifecycle.py`

- [ ] **Step 1: 앱 통합 테스트 작성**

다음을 검증한다.

- 앱 시작 때 tracker가 이전 후보를 먼저 복구한 뒤 현재 `running` 세션 저장
- 새 `running` commit 실패/degraded tracker, session lease 미보유, IANA 해석 실패는 사유 코드와 `life_records_writable=False`를 bridge/UI에 전달해 자동 생성·수동 재생성을 fail-closed로 끈다. 채팅·열람은 계속하되 IANA 실패만 UTC view, 나머지는 유효한 현재 view timezone을 사용
- Task 1B `LocalTimeContext` 하나를 tracker, manager, bridge, 날짜 조회에 주입
- `LifeRecordManager`, 후보, provider, profile, mood, settings가 bridge에 바인딩
- 같은 `LifeRecordManager`가 실제 Gemini/HTTP `llm_client.life_record_manager`에도 바인딩되어 `build_memory_context()`가 읽을 수 있음
- 주입 가능한 QTimer factory의 interval이 60000이고 실제 대기 없이 timeout handler 직접 호출로 현재 세션 heartbeat 검증
- backend UI payload에 locale key와 해석된 `resolvedLanguage`(ko/en/ja) 포함
- tray 종료와 `QApplication.aboutToQuit` fallback이 연속 호출돼도 종료 finalizer와 `stop_session()`은 한 번만 실행
- 자동 생성·수동 재생성·일반 답변 worker 각각 실행 중 종료 시 `begin_shutdown → operation 무효화 → cooperative cancel/drain → timer stop → stop_session → overlay/tray teardown → session lease 해제` 순서
- shutdown 뒤 늦은 result/error는 저장·답변 재개·UI signal 없음, worker 종료 전 bridge/QObject 파괴 없음
- 일반 `AIWorker`와 `LifeRecordWorker`는 시작 전·네트워크 await 뒤·signal emit 전에 interruption을 확인하고 취소된 작업은 결과 signal을 emit하지 않음
- cancel 불가/timeout 강제 종료는 `stopped`를 쓰지 않고 기존 `running`을 남김
- stop 저장 실패에도 앱 종료는 지속하되 안전 코드만 로그
- tracker/records 파일 오류가 앱 시작·일반 채팅을 막지 않음
- UI 문자열 payload에 ko/en/ja 생활 기록 키와 resolved language 포함

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_life_record_app_lifecycle.py tests/test_app_llm_bootstrap.py tests/test_app_quit_summary.py tests/test_bridge_worker_multimodal_capability.py -q`

Expected: lifecycle wiring 부재로 FAIL.

- [ ] **Step 3: 앱 초기화·종료 순서 구현**

`app.py`가 Task 1B의 `LocalTimeContext`와 데이터 루트의 두 JSON 경로를 생성자에 주입하고, 새 `running` authoritative commit에 성공하고 session lease를 보유한 `start_session()` 결과만 메모리 후보로 보관한다. degraded·lease 미보유·timezone 실패 상태는 bridge에 단일 `life_records_writable=False`와 정확한 사유 코드(`session_tracker_degraded`, `session_lease_unavailable`, `timezone_unavailable`)로 전달한다. 생성한 manager는 bridge뿐 아니라 공급자 종류와 무관하게 실제 `llm_client.life_record_manager`에도 명시적으로 설정한다. 하트비트 QTimer는 성공적으로 현재 세션을 연 뒤 시작한다.

`_finish_quit_application()`의 첫 단계는 `bridge.begin_shutdown()`이다. 새 요청을 차단하고 operation을 무효화한 뒤 모든 일반·생활 worker에 `requestInterruption()`을 보내고 비차단 signal 기반으로 종료를 drain한다. `bridge_workers.py`의 worker는 시작 전, 네트워크 await 뒤, result/error signal 직전에 interruption을 확인해 취소 결과를 방출하지 않는다. 완료된 경우에만 timer를 멈추고 teardown 직전 마지막 비차단 단계에서 멱등 `stop_session()`을 commit한 뒤 overlay·tray를 정리하고 마지막에 session lease를 해제한다. 제한 시간 내 drain 실패로 강제 종료하면 `running`을 보존한다. tray 경로를 주 finalizer로 사용하고 `QApplication.aboutToQuit`을 동일 멱등 finalizer의 fallback으로 연결한다. 오류는 예외 본문 대신 안정 코드만 기록한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_life_record_app_lifecycle.py tests/test_app_llm_bootstrap.py tests/test_app_quit_summary.py tests/test_bridge_worker_multimodal_capability.py -q`

Expected: PASS.

- [ ] **Step 5: 커밋**

```text
git add main.py src/core/app.py src/core/overlay_window.py src/core/bridge_workers.py src/core/bridge_mixins/life_records.py tests/test_app_llm_bootstrap.py tests/test_app_quit_summary.py tests/test_bridge_worker_multimodal_capability.py tests/test_life_record_app_lifecycle.py
git commit -m "feat: wire life records into app lifecycle"
```

## Task 15: 대표 시나리오·회귀·문서·개인정보 검증

이 Task는 새 구현을 소유하지 않는 acceptance verification 단계다. E2E에서 결함을 발견하면 소유 Task의 테스트·구현 범위로 돌아가 별도 `fix:` 커밋으로 고친 뒤 다시 실행한다. 이미 공개된 커밋을 amend/rebase하지 않는다.

**Files:**
- Create: `tests/test_life_record_end_to_end.py`
- Modify: `README.md`
- Modify: `README.ko.md`
- Modify: `README.ja.md`
- Modify: `TESTING.md`
- Create: `docs/life_records.md`
- Modify: `tests/test_build_windows_release.py`
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

같은 파일에서 정상 종료, 비정상 종료, 명령 선행, 첨부 첫 채팅, 생성 실패 fallback, 수동 재생성 성공·실패, 날짜 양쪽 조회, 리롤 비재생성을 잇는 사용자 여정을 검증한다. 자동 생성 중 두 번째 요청·자동 queue, 수동 재생성과 정상 답변의 양방향 잠금, worker result와 종료의 교차도 포함한다.

- [ ] **Step 2: 완성된 사용자 여정 통과 확인**

Run: `python -m pytest tests/test_life_record_end_to_end.py -q`

Expected: 앞선 Task의 단위·통합 테스트에서 모든 연결을 구현했으므로 PASS. 실패하면 이 Task에서 임의 연결 코드를 추가하지 말고, 실패를 소유하는 선행 Task에 최소 실패 테스트를 추가하고 별도 `fix:` 커밋으로 보완한 뒤 다시 실행한다.

- [ ] **Step 3: README 세 언어에 운영 정보를 추가**

다음만 문서화한다.

- 기본 비활성화 및 60분 기본 임계값
- 자유형 생활 환경 편집 위치
- 첫 일반 채팅에서 2회 호출될 수 있음과 토큰 합산
- `··· → 생활` 날짜 조회와 최신 기록만 재생성 가능
- 런타임 파일 세 개와 백업 권장
- 손상 파일·빈 world·생성 실패 시 일반 채팅은 계속됨

문서 예시는 중립적인 합성 문장만 사용한다.

`docs/life_records.md`와 `TESTING.md`에는 권위 저장소와 Store cache 의미, schema·손상 복구, 시간대 의존성, 집중 테스트, capability fallback, 로그 금지, release smoke 절차를 기록한다.

- [ ] **Step 4: 집중 테스트 실행**

Run:

```text
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_local_time.py tests/test_life_session_tracker.py tests/test_life_record_types.py tests/test_life_record_manager.py tests/test_life_record_prompt.py tests/test_life_record_llm_contract.py tests/test_life_record_http_native_providers.py tests/test_life_record_http_format_parity.py tests/test_life_record_chat_context.py tests/test_life_record_request_gate.py tests/test_life_record_bridge_flow.py tests/test_life_record_regeneration.py tests/test_life_record_settings_ui.py tests/test_life_record_panel_assets.py tests/test_life_record_ui_states.py tests/test_life_record_app_lifecycle.py tests/test_life_record_end_to_end.py tests/test_build_windows_release.py -q
```

Expected: PASS.

- [ ] **Step 5: 실제 CI 게이트와 전체 회귀 실행**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m ruff check . --select E9,F63,F7,F82
python -m coverage run --source=src --omit="src/core/app.py,src/core/audio_player.py,src/core/global_ptt.py,src/core/overlay_window.py,src/core/bridge_workers.py,src/core/bridge_mixins/attachments.py,src/core/bridge_mixins/away.py,src/core/bridge_mixins/memory_summary.py,src/core/bridge_mixins/mood.py,src/core/bridge_mixins/obsidian.py,src/ui/drag_bar.py,src/ui/settings_dialog_hotkeys.py,src/ui/settings_dialog_profile.py,src/ui/settings_dialog_prompt.py,src/ui/settings_dialog_theme.py,src/ui/settings_dialog_tts.py,src/ui/settings_dialog_widgets.py,src/ai/http_llm_clients.py,src/ai/http_llm_common.py,src/ai/http_llm_openai.py,src/ai/http_llm_custom_providers.py,src/ai/http_llm_anthropic.py,src/ai/http_llm_ollama.py,src/ai/llm_client.py" -m pytest -q
python -m coverage report --show-missing --skip-empty --fail-under=80
```

Expected: ruff PASS, 전체 테스트 실패 0개, 선별 coverage 80% 이상. GitHub Actions의 Linux·Windows job도 모두 green이어야 완료다. 전체 suite는 10분 이상 timeout을 허용하고 Task별 반복 실행은 집중 묶음만 사용한다.

- [ ] **Step 6: UTF-8 BOM과 런타임 파일 추적 여부 확인**

Run:

```powershell
$committedChanged = @(git diff --name-only "codex-ene-life-record-v1-base..HEAD")
$stagedChanged = @(git diff --cached --name-only --diff-filter=ACMR)
$workingChanged = @(git diff --name-only --diff-filter=ACMR)
$changed = @($committedChanged + $stagedChanged + $workingChanged | Sort-Object -Unique)
$textExtensions = @('.py', '.js', '.css', '.html', '.md', '.json', '.txt', '.yml', '.yaml')
$utf8Strict = [Text.UTF8Encoding]::new($false, $true)
$invalidUtf8 = foreach ($path in $changed) {
    if ((Test-Path -LiteralPath $path) -and $textExtensions -contains [IO.Path]::GetExtension($path).ToLowerInvariant()) {
        $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path))
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $path; continue }
        try { [void]$utf8Strict.GetString($bytes) } catch { $path }
    }
}
if ($invalidUtf8) { $invalidUtf8; throw 'UTF-8 without BOM이 아닌 변경 텍스트 파일이 있습니다.' }
$trackedRuntime = @(git ls-files -- memory.json user_profile.json ene_profile.json config.json api_keys.json obs_config.json mood_state.json calendar.json diary.json life_records.json life_session_state.json life_session_state.lock api_key.txt 'prompts/base_system_prompt.md' 'prompts/sub_prompt_body.md' 'prompts/analysis_system_appendix.md' 'prompts/emotion_guides.md' 'prompts/life_world.md' '.env*')
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
$secretPattern = @'
(?i)(sk-[a-z0-9_-]{20,}|AIza[a-z0-9_-]{20,}|api[_-]?key\s*[:=]\s*["'][^"']+|secret\s*[:=]\s*["'][^"']+)
'@
$privacyPattern = @'
(실제 대화|건강|취업|자소서|일정|생일|직업|전공|user_profile|calendar\.json|diary\.json)
'@
foreach ($path in $changed) {
    if (Test-Path -LiteralPath $path) {
        rg -n $secretPattern -- $path
        if ($LASTEXITCODE -eq 0) { throw "비밀값 후보: $path" }
        if ($LASTEXITCODE -ge 2) { throw "비밀값 검색 실패: $path" }
    }
}
($changed -join "`n") | rg -n $secretPattern
if ($LASTEXITCODE -eq 0) { throw '변경 경로명에 비밀값 후보가 있습니다.' }
if ($LASTEXITCODE -ge 2) { throw '경로명 검색이 실패했습니다.' }
($changed -join "`n") | rg -n $privacyPattern
if ($LASTEXITCODE -ge 2) { throw '변경 경로 개인정보 후보 검색이 실패했습니다.' }
foreach ($path in $changed) {
    if (Test-Path -LiteralPath $path) {
        rg -n $privacyPattern -- $path
        if ($LASTEXITCODE -ge 2) { throw "개인정보 후보 검색 실패: $path" }
    }
}
```

Expected: 첫 검색은 0건. 두 번째 검색은 구현상 필요한 일반 키 이름도 잡힐 수 있으므로 모든 결과를 사람이 검토하고, 실제 사용자 이름·실제 대화 문장·건강/일정/취업/프로필 정보가 없음을 확인한다.

- [ ] **Step 8: bundle·release readiness smoke 검증**

Run:

```powershell
$bundleJson = @'
import json
from pathlib import Path
from scripts.build_windows_release import PYINSTALLER_COLLECT_ALL, collect_data_mappings
root = Path.cwd()
print(json.dumps({
    "mappings": [[source.relative_to(root).as_posix(), target.replace("\\", "/")] for source, target in collect_data_mappings(root)],
    "collect_all": list(PYINSTALLER_COLLECT_ALL),
}))
'@ | python -
$bundle = $bundleJson | ConvertFrom-Json
if (-not (Test-Path -LiteralPath 'prompts/defaults/life_world.md')) { throw '기본 생활 환경이 없습니다.' }
if (-not (Test-Path -LiteralPath 'assets/web/runtime_life_record_panel.js')) { throw '생활 기록 웹 자산이 없습니다.' }
if ('tzdata' -notin @($bundle.collect_all)) { throw 'tzdata collect-all이 없습니다.' }
$mappingSources = @($bundle.mappings | ForEach-Object { $_[0] })
$mappingTargets = @($bundle.mappings | ForEach-Object { $_[1] })
if ('prompts/defaults' -notin $mappingSources -or 'assets/web' -notin $mappingSources -or 'prompts/defaults' -notin $mappingTargets -or 'assets/web' -notin $mappingTargets) { throw '필수 bundle mapping이 없습니다.' }
$forbiddenMappings = @('life_records.json', 'life_session_state.json', 'prompts/base_system_prompt.md', 'prompts/sub_prompt_body.md', 'prompts/analysis_system_appendix.md', 'prompts/emotion_guides.md', 'prompts/life_world.md')
foreach ($path in $forbiddenMappings) { if ($path -in $mappingSources -or $path -in $mappingTargets) { throw "사용자 runtime mapping 포함: $path" } }
Write-Output 'RELEASE_MAPPING_OK'
```

Expected: `RELEASE_MAPPING_OK` 한 줄.

실제 Microsoft Store Python smoke는 release 전에 Store 브리지를 우회하지 않는 전용 상대 경로에서 수행한다.

1. Microsoft Store Python 실행 파일로 앱 경로 유틸리티 테스트를 실행해 Store runtime임을 먼저 확인하고 `ENE_USER_DATA_DIR`가 설정되지 않았음을 확인한다. 이 환경 변수를 설정하면 Store visible 브리지가 비활성화되므로 disposable override를 사용하지 않는다.
2. 앱 경로 헬퍼로 runtime·visible ENE 사용자 데이터 루트를 각각 구한 뒤, 한 번만 만든 GUID를 사용해 두 루트 아래 동일한 상대 경로 `store_smoke/<GUID>/life_records.json`을 만든다. 두 절대 경로가 각각 기대한 ENE 루트의 하위이고 상대 경로 첫 구간이 정확히 `store_smoke`인지 검사하지 못하면 즉시 중단한다.
3. manager로 레코드를 저장하고 visible Roaming 권위 파일이 UTF-8 JSON 완성본인지 확인한다. runtime cache를 의도적으로 오래된 유효 JSON으로 바꾼 뒤 새 프로세스에서 읽어 visible 최신값이 반환되고 cache가 복구되는지 확인한다.
4. visible 파일을 손상시킨 경우 runtime cache가 반환되지 않고 `read_error`가 보고되는지 확인한다. smoke 중 생성한 원문이나 응답은 출력·로그·release asset에 포함하지 않는다.
5. 종료 시 앞서 검증한 두 `store_smoke/<GUID>` 디렉터리만 `-LiteralPath`로 제거한다. 삭제 직전에도 각 resolved 경로가 기대한 ENE 루트 아래이고 마지막 두 구간이 `store_smoke/<GUID>`인지 다시 검사하며, 검사가 실패하면 광범위한 정리를 시도하지 않고 수동 정리 대상으로 보고한다.

Expected: authoritative 최신값 복구, stale cache 역덮어쓰기 없음, 손상 visible에서 fail-closed. 이 계획은 실제 release/tag 생성은 수행하지 않는다.

release/tag를 별도로 만들기 전에는 `docs/life_records.md` 절차에 따라 전체 tracked tree, 전체 Git history, tag가 가리킬 commit, release archive 파일 목록과 압축 내부를 검사한다. 민감 데이터 발견 시 release를 중단하고 history rewrite 필요 여부를 먼저 판단한다.

- [ ] **Step 9: diff와 최종 상태 검토**

Run:

```powershell
git diff --check codex-ene-life-record-v1-base..HEAD
git diff --cached --check
git diff --check
```

Expected: 출력 없음.

Run: `git status --short`

Expected: 의도한 소스·테스트·README 변경만 표시되고 런타임 파일과 빌드 산출물은 없음.

- [ ] **Step 10: 최종 커밋**

```text
git add tests/test_life_record_end_to_end.py tests/test_build_windows_release.py README.md README.ko.md README.ja.md TESTING.md docs/life_records.md
git commit -m "test: verify ENE life record workflow"
```

- [ ] **Step 11: 기준 태그 정리와 최종 상태 확인**

Run:

```powershell
git diff --check codex-ene-life-record-v1-base..HEAD
git tag -d codex-ene-life-record-v1-base
git status --short
```

Expected: diff 오류 없음, 로컬 기준 태그 삭제 성공, 의도하지 않은 변경·런타임 파일·빌드 산출물 없음.

## 최종 수동 검증 체크리스트

- [ ] 새 설치 기본값에서 생활 기록이 생성되지 않고 기존 채팅이 동일하게 동작한다.
- [ ] 기능을 켜고 생활 환경을 저장한 뒤 ENE를 정상 종료한다.
- [ ] 가상 또는 조정된 clock으로 60분 미만 복귀는 생성하지 않고 정확히 60분은 생성한다.
- [ ] 전날 23:00 종료, 다음 날 10:00 첫 일반 채팅에서 11시간 전체가 공백 없이 표시된다.
- [ ] 앱만 먼저 실행해 두었다가 나중에 채팅하면 종료 시각부터 그 첫 채팅 시각까지 기록된다.
- [ ] `/note`, `/obs`, `/diary` 후 첫 일반 채팅에서 한 번 생성된다.
- [ ] 첫 첨부 채팅도 동일하게 한 번 생성된다.
- [ ] 자동 생성 중 두 번째 텍스트·첨부·명령·리롤·수정과 약속·선제·자리비움이 실행되지 않고 첫 답변 뒤 정상 복구된다.
- [ ] 생성 화면이 `복귀 기록 정리 중…`에서 `생각 중…`으로 전환되고 첫 답변이 최신 기록을 안다.
- [ ] 첫 답변 리롤과 첫 메시지 수정은 생활 기록을 자동 재생성하지 않는다.
- [ ] `··· → 생활`에서 오늘·이전·다음·날짜 선택이 동작하고 자정 넘김 기록이 양쪽 날짜에 전체로 보인다.
- [ ] 최신 카드만 재생성 버튼을 가지며 취소·실패 시 원본이 보존되고 성공 시 revision이 증가한다.
- [ ] 기능을 끄면 저장 데이터는 남지만 일반 대화 컨텍스트에는 들어가지 않는다.
- [ ] 빈 생활 환경, 공급자 오류, 저장 오류, 손상 기록 파일에서도 일반 채팅은 계속된다.
- [ ] 앱 강제 종료 뒤 다음 실행에서 마지막 하트비트 기준 후보가 만들어지고 약 1분 오차 안내가 성립한다.
- [ ] 키보드만으로 생활 패널 열기·날짜 이동·Escape 닫기·재생성 취소/승인을 수행하고 초점이 원래 trigger로 돌아온다.
- [ ] 스크린리더가 패널 제목, 재생성 확인창, 진행·실패 상태를 중복 없이 읽는다.
- [ ] 375×667 웹에서 가로 스크롤 없이 날짜와 카드가 보이고 모든 주요 버튼 hit target이 44px 이상이다.
- [ ] 1024×768 화면에서 설정창 전체와 아래쪽 전체 폭 생활 환경 편집기를 열고 저장할 수 있다.
- [ ] ko/en/ja 런타임 전환 시 `<html lang>`, visible/ARIA 문구, 날짜·시간 포맷과 새 기록 언어가 함께 바뀐다.
- [ ] 기록 당시 timezone과 현재 view timezone이 다른 자정 인접 기록, DST 23/25시간 날짜를 올바르게 조회한다.
- [ ] Microsoft Store Python에서는 visible 권위 파일 저장 뒤 runtime cache가 복구되며 stale cache가 visible을 덮어쓰지 않는다.
