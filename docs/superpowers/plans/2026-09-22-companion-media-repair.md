# 동반 앱 캐릭터·음성 출력 보완 구현 계획

> **실행 에이전트:** `superpowers:executing-plans`로 이 세션에서 순차 직접 구현한다. 각 수정에는 `superpowers:test-driven-development`, 완료 판단 전에는 `superpowers:verification-before-completion`을 적용한다. 사용자와 확정한 실행 방식에 따라 작업별 구현 에이전트를 나누지 않는다.

**목표:** CSP를 유지하면서 캐릭터 초기화를 고치고, 스트리밍 휴대폰 전환·수동 출력 선택·실패 사유 표시를 검증한 뒤 로컬 개발 APK를 재빌드한다.

**구조:** 기존 Qt TTS 브리지에서 발화별 정책을 캡처하고 기존 출력 조정기에서 PC 대체 허용 여부를 집행한다. 메시지 공개와 첫 PCM 전달 순서를 고치며, 기존 프로토콜의 선택 진단 필드만 확장한다. 공유 캐릭터 자산은 ENE의 허용 목록·해시 검사 후 ENE_APP으로 내보낸다.

**기술:** Python 3.11 호환 코드·로컬 Python 3.12, PyQt6, pytest, Node.js VM, Pixi 7.3.0, Kotlin/Compose, Gradle, JDK 21, Android SDK 36.

---

기준: [사용자가 승인한 설계](../specs/2026-09-22-companion-media-repair-design.md). 작성 당시 ENE는 `d8e4a67`, ENE_APP은 `e4677a3`이며 두 작업 트리는 깨끗하다. 구현 시작 시 다시 확인한다. 이 계획의 체크박스는 구현 완료 기록이 아니다.

## 공통 실행·보존 규칙

- 기존 최종 ENE·ENE_APP 폴더를 이동하거나 원본 저장소·백업을 삭제하지 않는다. 계획 작성은 현재 폴더의 문서만 변경한다. 구현 착수 시 `using-git-worktrees` 절차로 격리 위치를 확인하되, 기존 폴더를 다른 저장소로 교체하지 않는다. 작업 브랜치를 만들면 `codex/companion-media-repair`를 사용한다. 이미 존재하면 내용을 확인하고 덮어쓰지 않는다.
- 아래 경로는 각 저장소 루트 기준이다. 실제 구현 위치가 격리 작업 트리라면 `$eneRoot`·`$androidRoot`는 그 위치로, `$eneSourceRoot`·`$androidSourceRoot`는 기존 최종 폴더로 지정한다. Python은 기존 ENE 가상환경을 명시적으로 호출하며 재설치·이동하지 않는다.
- ENE_APP 쓰기·Gradle 실행 및 Git 메타데이터 쓰기는 필요한 파일시스템 승인을 거쳐 수행한다. 접근 거부를 다른 경로로 우회하지 않는다.
- 실제 사용자 대화·모델명·기기 식별자·개인 경로를 테스트와 문서에 넣지 않는다. 기존 합성 fixture를 사용한다. Core·모델·설정·비밀키·APK·빌드 산출물은 Git에 추가하지 않는다.
- 변경 전 관련 집중 테스트만 실행하고, 각 작업은 실패 재현 → 최소 구현 → 집중 통과로 진행한다. 전체 검증은 통합 후 한 번 실행하며 수정이 생기면 영향 범위를 재검증한다. 테스트 제외나 검증 기준 완화로 통과시키지 않는다.
- Windows pytest 임시 폴더는 저장소 밖에 매번 새로 만든다. ACL 오류가 나면 테스트 전제를 바꾸지 말고 허용된 권한으로 다시 실행한다. 외부 명령 실패 코드를 후속 성공 명령으로 가리지 않는다.
- 로컬 커밋은 아래 작업 단위로 나누고 메시지는 영어로 작성한다. 매번 정확한 변경 경로만 스테이징하고 개인정보 후보·키 패턴·바이너리 포함 여부를 검사한다. 원격 push·태그·릴리스·실기기 설치는 실행하지 않는다.

검증 명령의 변수는 각 PowerShell 실행에서 다시 준비한다. 기본 위치에서 시작하는 경우:

```powershell
$eneSourceRoot = (git rev-parse --show-toplevel).Trim()
$androidSourceRoot = Join-Path (Split-Path -Parent $eneSourceRoot) 'ENE_APP'
$eneRoot = $eneSourceRoot
$androidRoot = $androidSourceRoot
$py = Join-Path $eneSourceRoot '.venv/Scripts/python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$env:QT_QPA_PLATFORM = 'offscreen'
$testRun = Join-Path $env:TEMP ('ene-media-' + [guid]::NewGuid().ToString('N'))
```

각 pytest 실행에는 새 `$testRun`을 생성한다. JDK/SDK는 현재 설치를 사용하며 전체 환경변수나 `local.properties` 내용을 로그에 덤프하지 않는다.

## 작업 0. 착수 상태와 로컬 산출물 보존

**대상:** 두 저장소 Git 상태, 기존 로컬 Core, ENE_APP의 `app/build/outputs/apk/debug/app-debug.apk`, 기존 가상환경·SDK. 추적 소스 변경 없음.

- [ ] **0.1** 두 저장소에서 `git status --short --branch`, `git log -3 --oneline`, `git worktree list --porcelain`을 확인한다. 새 미커밋 변경은 보존하고 겹치는 변경이 있으면 사용자에게 확인한다. 최종 폴더와 작업 트리 변수를 실제 위치로 고정한다.
- [ ] **0.2** ENE `backups/`가 제외되는지 확인하고, 시각과 임의 식별자를 붙인 새 하위 폴더를 만든다. 기존 APK가 있으면 원본 이름·길이·SHA-256을 기록하고 `Copy-Item -LiteralPath`로 복사한 뒤 두 해시를 대조한다. 원본이 없으면 없음을 기록하며 실패한 백업 상태에서 APK를 덮어쓰지 않는다.
- [ ] **0.3** 두 Core 경로의 존재·크기·SHA-256과 `git check-ignore -v`를 확인한다. 기준 해시는 설계가 참조한 기존 manifest에서 읽는다. 격리 작업 트리에 Core가 필요하면 기존 최종 폴더의 같은 파일만 복사하고 해시를 대조한다. 재다운로드·모델 복사·런타임 설정 복사는 불필요하다.
- [ ] **0.4** 기존 ENE 음성 경로 집중 테스트와 Android 음성/확장 단위 테스트를 실행해 출발 상태를 기록한다. 이 시점에 기존의 PC 고정 테스트가 통과하는 것은 원인 확인이지 수정 완료가 아니다.

```powershell
& $py -m pytest tests/test_companion_tts_routing.py tests/test_companion_audio_route.py tests/test_companion_audio_coordinator.py -q -p no:cacheprovider --basetemp $testRun
```

ENE_APP 작업 루트:

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests dev.ene.companion.ExtensionSessionTest --tests dev.ene.companion.ExtensionCodecTest --offline --dependency-verification strict --console=plain
```

예상: 현재 구현 기준 집중 테스트 통과. 기존 실패가 있으면 이후 변경의 실패와 구분해 원인을 확인한 뒤 진행한다.

## 작업 1. CSP 호환 캐릭터 초기화

**파일:**

- 신설: ENE `assets/web/lib/pixi-unsafe-eval.min.js`, `tests/companion_pixi_csp_harness.js`, `tests/test_companion_character_csp.py`.
- 수정: ENE `assets/web/character/index.html`, `assets/web/character/notices/THIRD-PARTY.md`, `contracts/companion/character-runtime.json`, `tools/export_companion_character.py`, `tests/test_companion_character_export.py`.
- 내보내기: ENE_APP `app/src/main/assets/character/`의 변경된 허용 파일과 `import-manifest.json`.
- 수정: ENE_APP `app/src/test/java/dev/ene/companion/CharacterRuntimeTest.kt`. MIT 고지가 기존 `Pixi-MIT.txt`와 다르면 새 고지 파일을 명시적으로 추가한다.

- [ ] **1.1** 실제 Pixi를 읽는 아래 Node 검사기를 만들고 pytest에서 실행한다. CSP 검사는 가짜 `ShaderSystem`으로 대체하지 않는다. 처음에는 호환 모듈 없이 초기화 오류로 실패하는 것을 기록한다.

```javascript
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.resolve(__dirname, '../assets/web');
const context = vm.createContext({ console }, {
    codeGeneration: { strings: false, wasm: true }
});
vm.runInContext(fs.readFileSync(path.join(web, 'lib/pixi.min.js'), 'utf8'), context);
assert.throws(() => vm.runInContext('new Function("return 1")', context));
const shim = path.join(web, 'lib/pixi-unsafe-eval.min.js');
if (fs.existsSync(shim)) vm.runInContext(fs.readFileSync(shim, 'utf8'), context);
vm.runInContext('PIXI.ShaderSystem.prototype.systemCheck.call({})', context);
assert.throws(() => vm.runInContext('new Function("return 1")', context));
```

- [ ] **1.2** pytest에 HTML 로드 순서가 `pixi → 호환 모듈 → Core → 표시 라이브러리`인지, CSP에 JavaScript `'unsafe-eval'`이 없는지 확인하는 검사를 추가한다. 기존 `'wasm-unsafe-eval'`을 잘못 금지하지 않는다.
- [ ] **1.3** 공식 npm 배포의 `@pixi/unsafe-eval@7.3.0` 메타데이터·패키지 무결성·MIT 고지·브라우저 번들을 확인한다. [공식 사용 안내](https://api.pixijs.io/@pixi/unsafe-eval.html)를 기준으로 고정 버전만 가져온다. 해당 버전/공식 출처를 검증하지 못하면 멈추며 최신 버전으로 대체하지 않는다. 받은 정적 파일의 SHA-256을 manifest에 기록하고 무결성 검사를 생략하지 않는다.
- [ ] **1.4** HTML과 내보내기 허용 목록을 수정한다. `libraries`의 기존 3개 고정 검사는 정확한 새 목록과 일치하도록 수정한다. 파일 개수만 늘려 허용하거나 임의 파일을 받아들이지 않는다. `local_only_files`는 기존 Core 한 개 그대로 유지한다.
- [ ] **1.5** ENE 검사를 통과시킨 뒤 공식 내보내기 도구로 ENE_APP을 갱신한다. Android의 20개 고정 검사는 실제 확정된 전체 허용 목록으로 갱신한다. 기존 Core가 내보내기 전후 동일한지 검사한다.

```powershell
& $py -m pytest tests/test_companion_character_csp.py tests/test_companion_character_export.py tests/test_companion_character_entry.py tests/test_companion_character_runtime.py -q -p no:cacheprovider --basetemp $testRun
& $py -m tools.export_companion_character --check --require-core
& $py -m tools.export_companion_character --android-root $androidRoot --require-core
```

각 명령의 종료 코드 0을 따로 확인한다. Android에서는 `:app:testDebugUnitTest --tests dev.ene.companion.CharacterRuntimeTest`에 공통 offline/strict 옵션을 붙여 실행한다.

- [ ] **1.6** 검증된 변경만 두 저장소에 각각 커밋한다. ENE: `fix: initialize companion character under strict CSP`, ENE_APP: `fix: import CSP-compatible character runtime`. 단말 렌더링 성공으로 보고하지 않는다.

## 작업 2. 첫 PCM과 공개 메시지의 처리 순서 수정

**수정:** ENE `src/core/companion/audio_bridge.py`, `src/core/bridge_mixins/tts.py`, `tests/test_companion_tts_routing.py`, 필요 시 `tests/test_bridge_tts_streaming.py`의 관련 기대. 다른 채팅·리롤 소스는 변경하지 않는다.

- [ ] **2.1** 기존 `test_hidden_stream_stays_pc_even_after_message_becomes_public`을 다음 검증으로 대체한다. fixture의 실제 `start_reply`와 완료 처리까지 사용하며 공개 ID를 테스트에서 미리 넣지 않는다.

```python
def test_pending_stream_publishes_before_offer_and_waits_for_phone(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    result = stream_reply(routed_bridge, published=False)
    assert played == [] and transfers == []
    assert result.request_ref.key not in bridge.chat_state.public_assistant_ids
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    offer = next(item for item in transfers if item.kind == "offer")
    assert offer.ref.message_id == bridge.chat_state.public_assistant_ids[result.request_ref.key]
    assert bridge.life_record_state.phase == "normal_reply"
    bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=2400))
    jobs[0].stream_finished.emit()
    assert bridge.life_record_state.phase == "normal_reply" and played == []
    bridge.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=2400))
    assert bridge.life_record_state.phase == "idle" and played == []
```

- [ ] **2.2** 같은 fixture에서 공개 이벤트와 `publish_audio` 호출을 함께 기록해 공개 이벤트가 제안보다 앞서는지 검사한다. 공개 함수 호출 시 완료가 먼저 풀리지 않는지, 첫 PCM이 전달 데이터에서 유실/중복되지 않는지 추가한다. 기존 코드에서 PC 재생 시작 또는 휴대폰 제안 부재로 실패해야 한다.
- [ ] **2.3** 브리지에 발화 소유권·형식을 보관하는 작은 대기 상태를 둔다. 형식만으로 공개하거나 PC를 시작하지 않는다. 첫 유효 PCM에서 작업을 재검증하고 `_held`로 완료를 보류한 다음 `_flush_pending_response_if_any()`를 호출한다. 얻은 실제 ID로 조정기를 시작하고 첫 PCM을 한 번 전달한다.
- [ ] **2.4** 스트리밍 훅의 반환 계약을 정리한다. PC로 결정된 발화만 `False`로 기존 PC 경로를 통과시키고, 휴대폰 대기·휴대폰 소유·차단·취소 뒤 늦은 콜백은 `True`로 소비한다. 취소하면서 대기 상태를 지워 늦은 PCM이 PC로 새는 일이 없도록 작업 ID에 결합한 종료 표식을 유지한다. 새 작업 바인딩 때만 이전 표식을 정리한다.
- [ ] **2.5** 형식만 온 종료·빈 조각·프레임 불일치·첫 PCM 전 생성 오류·PTT·초기화·작업 교체·연결 세대 변경을 시험한다. 남은 답변은 기존 복구 표시 절차로 전달하고 완료는 한 번 처리한다. 비공개 파일 결과의 공개 금지는 기존 테스트로 유지한다.

```powershell
& $py -m pytest tests/test_companion_tts_routing.py tests/test_bridge_tts_streaming.py tests/test_companion_audio_coordinator.py -q -p no:cacheprovider --basetemp $testRun
```

- [ ] **2.6** 집중 검증 후 `fix: route pending TTS streams after message publication`으로 커밋한다.

## 작업 3. 발화별 출력 정책과 PC 대체 차단

**수정:** ENE `src/core/companion/audio_route.py`, `audio_coordinator.py`, `audio_bridge.py`, `src/core/bridge_mixins/tts.py`, `src/core/bridge.py`, `src/core/settings.py`, `src/core/app_tts_bootstrap.py`.

**테스트:** `tests/test_companion_audio_route.py`, `tests/test_companion_audio_coordinator.py`, `tests/test_companion_tts_routing.py`, `tests/test_settings.py`, `tests/test_app_tts_bootstrap.py`.

- [ ] **3.1** `AudioRoute(allow_pc_fallback=False)`의 제안 거절·준비 제한·전송 실패·휴대폰 부적격 경로에서 `play_pc`가 나오지 않는 테스트를 먼저 추가한다. 생성자 기본값은 기존 호출자 호환을 위해 `True`다.

```python
@pytest.mark.parametrize("failure", ["rejected", "delivery_failed"])
def test_phone_only_prepare_failure_cancels_without_pc(failure):
    route = AudioRoute(allow_pc_fallback=False)
    assert route.offer(now_ms=0, phone_eligible=True) == "offer_phone"
    assert getattr(route, failure)() == "cancel"
    assert route.finish() == "complete_once"
    assert route.finish() == "ignore"
```

- [ ] **3.2** `begin_wave`·`begin_stream`에 `allow_pc_fallback=True`를 추가하고 발화 route로 전달한다. `_fallback` 자체도 이를 검사해 수동 휴대폰이면 PC sink를 호출하지 않고 취소·완료한다. `receive`, `tick`, `_offer`, `_delivery_failed`, `disconnected`, 큐 포화처럼 route를 우회하는 분기도 검사한다. `invalid_pcm`은 자동 모드에서도 PC로 원시 데이터를 넘기지 않고 취소한다.
- [ ] **3.3** 설정 기본값과 공통 정규화 함수를 추가한다. 함수는 Qt 없는 기존 `audio_route.py`에 두어 설정·브리지에서 같은 검사를 사용한다.

```python
def normalize_output_target(value):
    return value if isinstance(value, str) and value in {"auto", "pc", "phone"} else "auto"
```

`Settings.DEFAULT_CONFIG`·로드 정규화·브리지 초기값에 `tts_output_target="auto"`를 넣는다. `apply_tts_runtime_to_bridge`는 설정에서 읽어 브리지에 반영한다. 이 단계에서 UI는 아직 추가하지 않는다.

- [ ] **3.4** `_Intent`에 `output_target`을 저장한다. 작업 생성 전에 정책을 읽고 worker에 결합한다. PC 선택은 휴대폰을 제안하지 않는다. 수동 휴대폰은 연결/기능 부재·비공개 결과·미지원 WAV/PCM에서 소비 후 중단 처리하며, `None`/`False`를 반환해 기존 PC 코드가 실행되게 하지 않는다.
- [ ] **3.5** `_play_tts`의 브라우저 조기 분기를 worker 정책 캡처보다 앞선 사전 검사로 보호한다. 수동 휴대폰이면 `build_request`와 `_play_browser_tts`/JavaScript 호출 전에 차단하고 텍스트 표시·완료만 처리한다. 비공개 결과도 휴대폰용 공개 ID를 만들지 않는다.
- [ ] **3.6** WAV/스트리밍의 PC·자동·휴대폰 매트릭스를 검사한다. 수동 휴대폰은 미연결, 거절, 2초 제한, HTTP 실패, 큐 포화, 시작 송신 불확실, 진행 정지, 취소/단절 후 늦은 데이터에서 PC `play/start_stream/append_stream_pcm` 호출이 모두 0회여야 한다. 자동의 정상 PCM 대체는 바이트 일치·생성 1회·완료 1회를 유지한다.
- [ ] **3.7** 정책 변경을 생성 대기·형식 수신 후·준비 중·시작 확정 후·재생 중으로 나누어 현재 발화가 최초 정책을 유지하는지 검사한다. 그 다음 새 발화에만 바뀐 값을 적용한다. 자동과 수동 모두 TTS 해제·명시적 중단은 기존대로 우선한다.

```powershell
& $py -m pytest tests/test_companion_audio_route.py tests/test_companion_audio_coordinator.py tests/test_companion_tts_routing.py tests/test_settings.py tests/test_app_tts_bootstrap.py -q -p no:cacheprovider --basetemp $testRun
```

- [ ] **3.8** 통과 후 `feat: enforce per-utterance audio output preferences`로 커밋한다.

## 작업 4. 호환 가능한 상태 계약과 공통 진단

**수정:** ENE `src/core/companion/extension_protocol.py`, `audio_coordinator.py`, `audio_bridge.py`, `src/core/bridge_mixins/companion.py`, `src/core/bridge.py`, `contracts/companion/v1/media.md`, `media_cases.json`, `tests/test_companion_extension_protocol.py`, `tests/test_companion_tts_routing.py`.

**수정:** ENE_APP `app/src/main/java/dev/ene/companion/protocol/ExtensionMessage.kt`, `ExtensionCodec.kt`, `contracts/companion/v1/media.md`, `media_cases.json`, `app/src/test/java/dev/ene/companion/ExtensionCodecTest.kt`.

- [ ] **4.1** 기존 `audio_status` 정상 fixture는 유지하고 확장 필드 정상/부분 누락/전체 누락/잘못된 값 사례를 추가한다. Python과 Kotlin이 같은 합성 사례를 읽게 한다. 새 필드가 있으면 각각 검사하고, 없으면 그대로 생략한다. 명시적 `null`, 잘못된 타입/열거값은 `invalid_message`다. 부분 정보로 빠진 값을 추측하지 않는다.

Python 정규화 분기에 추가할 핵심 검사:

```python
for key, choices in {
    "preference": {"auto", "pc", "phone"},
    "output": {"none", "pc", "phone"},
    "state": {"idle", "preparing", "playing", "stopped"},
}.items():
    if key in body:
        result[key] = _choice(body[key], choices)
```

실제 함수의 입력 변수 이름에 맞춰 연결한다. Kotlin `AudioStatus`에는 `String? = null` 필드 세 개를 뒤에 추가하고 정규화에서 존재하는 필드만 검증한다. 기존 직렬화의 `explicitNulls=false`를 유지한다. `mode` 값이나 프로토콜 버전은 늘리지 않는다.

- [ ] **4.2** 구형 계약에서는 추가 필드만 제거된 상태가 기존 `mode/reason`과 정확히 같은지 검사한다. 새 APK가 구형 PC 메시지를 받으면 상세 상태는 미제공으로 남겨야 한다. 변경 전 Android 정규화 동작을 고정한 독립 검사로 구형 APK가 선택 필드를 무시하는 것을 검증한다. 새 정규화기의 출력에서 필드를 지워 비교하는 것만으로 구형 호환을 입증하지 않는다.
- [ ] **4.3** 조정기의 실패 전환에 원인 코드를 넘겨 `pc_fallback`만 남는 문제를 고친다. 기존 완료 콜백의 `pc_fallback` 소유권 의미는 유지하고, 선택적인 상태 알림 콜백으로 원인을 별도로 전달한다. 콜백에는 현재 `AudioRef`와 제한된 코드만 전달한다. 브리지는 현재 발화와 일치하는 알림만 반영한다.
- [ ] **4.4** 브리지에 읽기 전용 상태 조회와 `audio_output_status_changed` 신호를 추가한다. 휴대폰 연결이 없어도 PC 로컬 상태를 갱신하며, 유효한 확장 연결이 있을 때만 `audio_status`를 보낸다. 실제 휴대폰 준비·재생 중에는 캡처된 정책의 수신 허용 모드를 유지하고 저장된 다음 선택만 `preference`에 반영한다.
- [ ] **4.5** 진단 코드와 상태 우선순위를 아래 기준으로 고정한다. 상태를 매 tick 재발행하지 않고 값이 바뀔 때만 알린다. 같은 가용성 재보고로 마지막 실패를 지우지 않는다.

| 상황 | 대표 코드 | 출력·상태 처리 |
| --- | --- | --- |
| TTS 해제 / 수동 PC | `tts_disabled` / `manual_pc` | 해제는 `none/idle`, PC는 실제 시작 통지 전 `none/idle` |
| 연결·전경·동기화·기능 부족 | `phone_disconnected`, `phone_inactive`, `phone_syncing`, `audio_not_negotiated` | 자동의 PC 대체 사유 또는 휴대폰의 `none/stopped` |
| 공급자·형식·비공개 결과 | `browser_tts`, `unsupported_format`, `private_result` | 정책에 따라 PC 또는 `none/stopped` |
| 휴대폰 준비 / 준비 제한 | `phone_preparing` / `prepare_timeout` | 준비는 `none/preparing`, 시작 확정 후 `phone/preparing` |
| 포커스·전송·버퍼 | 기존 `focus_denied`, `delivery_failed`, `buffer_full`, `invalid_pcm` | 자동의 확정 전 대체 또는 중단; 수동 휴대폰은 항상 중단 |
| 시작 / 정상 종료 / 진행 정지 | `playing`, `finished`, `playback_timeout` | 시작 보고 후 `playing`, 정상 종료는 `none/idle`, 오류는 `none/stopped` |

기존 Android HTTP/오디오 오류의 검증된 코드는 보존해 더 구체적인 설명에 사용한다. 알 수 없는 유효 코드는 일반 오류 문구로 표시한다. 오류 원문·토큰·경로·음성/대화는 넣지 않는다. 연결 해제가 재생 중 표시보다 우선하며 새 발화/관련 상태 변경 시에만 이전 중단 사유를 해제한다.

- [ ] **4.6** 가용성 사유 저장, 미연결 PC 상태, 오래된 작업/연결 상태 무시, 설정 변경 중 구형 APK의 `mode=auto` 유지 테스트를 추가한다. 공통 fixture는 검토된 변경만 두 저장소에 반영하고 파일 해시를 대조한다.

```powershell
& $py -m pytest tests/test_companion_extension_protocol.py tests/test_companion_tts_routing.py tests/test_companion_extension_session.py -q -p no:cacheprovider --basetemp $testRun
```

Android: `:app:testDebugUnitTest --tests dev.ene.companion.ExtensionCodecTest --tests dev.ene.companion.ProtocolCodecTest`에 공통 옵션을 사용한다.

- [ ] **4.7** ENE `feat: report companion audio routing decisions`, ENE_APP `feat: accept compatible audio routing diagnostics`로 각각 커밋한다.

## 작업 5. Android 출력 상태와 구체적 실패 사유 표시

**수정:** ENE_APP `app/src/main/java/dev/ene/companion/connection/ExtensionSession.kt`, `ConnectionState.kt`, `ConnectionRepository.kt`, `ui/ConnectionScreen.kt`.

**테스트:** `app/src/test/java/dev/ene/companion/ExtensionSessionTest.kt`, `ConnectionRepositoryTest.kt`, `AudioLifecycleTest.kt`; 신설 `AudioOutputStatusTest.kt`.

- [ ] **5.1** 문자열 하나인 출력 상태를 `preference/output/state/reason`을 담는 불변 표시 값으로 바꿀 테스트부터 만든다. 구형 상세 정보 없음, 준비 중, 수동 휴대폰 실패, PC 수동 선택, 연결 해제에서 잘못된 PC 재생 문구가 나타나지 않아야 한다.
- [ ] **5.2** 다음 표시 자료형을 `ConnectionState.kt`에 추가하고 `onOutput`·저장소·화면까지 연결한다. 상태값과 번역 문구를 섞어 저장하지 않는다.

```kotlin
data class AudioOutputStatus(
    val preference: String? = null,
    val output: String? = null,
    val state: String? = null,
    val reason: String? = null,
)
```

- [ ] **5.3** `AudioStatus`를 받은 뒤 `reason`과 선택 필드를 유지한다. `mode`만 기존 수신 허용 판단에 사용한다. `preference=pc`라는 이유로 이미 준비/재생 중인 음성을 취소하지 않는다. 실제 `mode=disabled/pc_only`의 기존 명시적 취소 규칙은 유지한다.
- [ ] **5.4** Android 자체 포커스/HTTP/오디오 실패도 표시 값에 반영한다. 실제 플레이어 상태가 없는 단순 `auto`를 PC 재생으로 표시하지 않는다. 같은 연결의 일반 준비 가능 상태가 즉시 실패 문구를 덮어쓰지 않게 한다. `ConnectionRepository`의 `active === record` 검사를 그대로 유지한다.
- [ ] **5.5** 가용성 중복 억제는 `(context, available)`뿐 아니라 사유도 비교한다. 비활성→동기화 중처럼 `false`는 같아도 원인이 달라지면 전달한다. 기능 미협상 상태에서는 지원하지 않는 확장 명령을 보내지 않고 로컬 연결 상태로 설명한다.
- [ ] **5.6** `AudioFixture`의 출력 목록 타입을 바꾸고 전체 사용처를 갱신한다. `mode=auto, preference=pc`를 생성 대기/준비/재생 중 보내도 시작 횟수·소비 프레임·자원 해제가 변하지 않는지 검사한다. 캐릭터 콜백 실패와 오디오 상태 콜백 실패가 재생 수명을 망가뜨리지 않는지도 유지한다.

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests dev.ene.companion.ExtensionSessionTest --tests dev.ene.companion.ConnectionRepositoryTest --tests dev.ene.companion.AudioLifecycleTest --tests dev.ene.companion.AudioOutputStatusTest --offline --dependency-verification strict --console=plain
```

- [ ] **5.7** 통과 후 `feat: explain phone audio readiness and playback failures`로 커밋한다.

## 작업 6. PC 설정 선택·상태 표시·저장 연결

**수정:** ENE `src/ui/settings_tabs/tts_tab.py`, `src/ui/settings_dialog_tts.py`, `src/ui/settings_dialog_values.py`, `src/ui/settings_dialog.py`, `src/core/app.py`, `src/core/app_tts_bootstrap.py`, `src/locales/ko.json`, `en.json`, `ja.json`.

**테스트:** 신설 `tests/test_tts_output_settings_ui.py`; 수정 `tests/test_app_tts_bootstrap.py`, `tests/test_ui_i18n_smoke.py`의 해당 범위.

- [ ] **6.1** 기존 `tests/test_fish_audio_settings_ui.py`의 격리된 설정창 fixture 방식을 사용한다. 오디오 장치 조회와 사용자 파일 경로는 합성/임시 값으로 대체한다. 기본값, 세 선택의 수집/복원, 잘못된 값, 취소, 재시작 로드 테스트를 먼저 작성한다.
- [ ] **6.2** 재생 그룹에 `tts_output_target_combo`와 상태 라벨을 넣고 기존 번역 바인딩을 사용한다. 자동/PC/휴대폰 항목 데이터는 정확히 `auto/pc/phone`이다. 기존 출력 장치는 PC용임을 표시하고, 다음 발화 적용·휴대폰 대체 금지 설명을 추가한다.
- [ ] **6.3** 값 로드·수집에 새 키를 연결한다. 상태 라벨은 브리지 스냅샷으로 초기화하고 신호를 받아 갱신한다. 설정창 반복 열기/닫기에서 중복 연결이나 삭제된 위젯 호출이 없게 기존 객체 수명에 맞춰 연결/해제한다. 언어 변경 때 마지막 상태도 다시 번역한다.
- [ ] **6.4** `_on_settings_changed`의 저장 성공 뒤 브리지 출력 선호만 갱신한다. **새 키를 기존 `old_tts_config/new_tts_config`의 재생기 재생성 비교에 넣지 않는다.** 선호만 바꿔 공급자·플레이어를 재생성하거나 현재 발화를 취소하면 안 된다. `_on_settings_preview`는 새 키를 적용하지 않고 취소해도 현재 정책이 유지된다.
- [ ] **6.5** 실제 저장 처리 경로를 사용하는 테스트에서 공급자 재생성 횟수 0, 현재 발화 정책 유지, 다음 발화에 새 정책 적용을 확인한다. 공급자 자체 변경/TTS 해제는 기존 테스트를 유지한다. 미연결 PC에서 상태 사유가 보이고 영어/일본어 UI에 새 한국어 문구가 섞이지 않는지 검사한다.

```powershell
& $py -m pytest tests/test_tts_output_settings_ui.py tests/test_app_tts_bootstrap.py tests/test_settings.py tests/test_ui_i18n_smoke.py tests/test_i18n.py tests/test_companion_tts_routing.py -q -p no:cacheprovider --basetemp $testRun
```

- [ ] **6.6** 통과 후 `feat: add manual TTS playback target controls`로 커밋한다.

## 작업 7. 통합 수명·안전성 검증과 현재 사용법

**수정/검증:** ENE `tests/test_companion_media_integration.py`, `tests/test_companion_media_resources.py`, `tests/test_companion_tts_routing.py`, `docs/companion-media-validation.md`; ENE_APP `app/src/test/java/dev/ene/companion/AudioLifecycleTest.kt`, `CharacterSessionTest.kt`, `docs/media-support.md`, `docs/build-and-install.md`.

- [ ] **7.1** 합성 GPT-SoVITS 스트리밍 작업 신호부터 공개 메시지·전송·소비 완료까지 연결해 검증한다. 자동의 준비 실패는 같은 PCM을 PC에 한 번만 보내고, 수동 휴대폰의 같은 실패는 PC 호출 0회다. 캐릭터 초기화 실패 상태에서도 음성 가용성과 채팅은 유지한다.
- [ ] **7.2** 설정 변경, 단절/재접속, PTT, 작업 교체, 생성 오류를 반복해 타이머·버퍼·worker·입력 게이트가 남지 않는지 검사한다. 이미 취소된 발화는 재접속·늦은 완료·늦은 PCM으로 부활하지 않아야 한다. 실제 네트워크·유료 AI/TTS·개인 대화를 호출하지 않는다.
- [ ] **7.3** 양쪽 공통 계약 파일의 해시와 수입 자산 manifest를 대조한다. Core 해시가 시작 때와 같은지, 모델/개인 파일이 새 추적 대상에 포함되지 않았는지 검사한다. 각 커밋 diff에서 불필요한 채팅/리롤 변경·보안 경계 완화가 없는지 검토한다.
- [ ] **7.4** 문서의 현재 사용법에 재생 기기 선택과 실패 사유를 추가한다. 과거 검증 기록은 그대로 두고 이번 결과를 새 절에 기록한다. 아직 수행하지 않은 수치·APK 해시·단말 성공을 먼저 적지 않는다.
- [ ] **7.5** 통합 후 ENE 전체 테스트와 CI에서 쓰는 기본 Ruff를 실행한다. 현재 로컬 Python 버전을 기록하고, 설치된 3.11 환경이 있으면 영향 테스트를 그 환경에서도 확인한다. 없는 환경을 검증했다고 보고하지 않으며 CI 설정은 변경하지 않는다.

```powershell
& $py -m pytest -q -p no:cacheprovider --basetemp $testRun
& $py -m ruff check . --select E9,F63,F7,F82
git diff --check
```

- [ ] **7.6** Android 전체 단위 테스트를 캐시 성공으로 대신하지 않고 실제 다시 실행한다. 실패·오류·제외 수와 결과 XML을 확인한다.

```powershell
.\gradlew.bat :app:testDebugUnitTest --rerun-tasks --offline --dependency-verification strict --console=plain
```

- [ ] **7.7** 변경 범위에 한정해 명세·코드 품질을 통합 검토한다. 중요한 오류는 수정하고 관련 검증을 다시 수행한다. 새 소스 변경이 생겼으면 문서 기록과 산출물 기준도 갱신한다. 검증된 문서/회귀 테스트만 `test: verify companion media routing lifecycle` 및 `docs: describe companion playback targets and diagnostics`처럼 실제 내용에 맞는 영어 메시지로 커밋한다.

## 작업 8. 로컬 APK 재빌드와 인계

**대상:** ENE_APP 기존 빌드 설정, 로컬 전용 `app/build/outputs/apk/debug/app-debug.apk`, 계측 APK, Git 제외된 검증 기록. 버전/서명/의존성 잠금을 불필요하게 변경하지 않는다.

- [ ] **8.1** 작업 0의 기존 APK 백업을 다시 해시 검사한다. 이미 최신 변경 뒤 생성된 파일이 있으면 그 파일도 덮어쓰기 전 새 이름으로 보존한다. Core는 시작 때의 기존 파일을 그대로 사용한다.
- [ ] **8.2** 아래 명령을 각각 실행하고 종료 코드와 빌드 결과를 확인한다. strict 검증·Core 검사를 끄지 않는다. 의존성 캐시 부족이면 필요한 공식 의존성과 네트워크 범위를 확인하고 승인 없이 대체 패키지를 가져오지 않는다.

```powershell
.\gradlew.bat :app:verifyLocalCore --offline --dependency-verification strict --console=plain
.\gradlew.bat :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest --offline --dependency-verification strict --console=plain
```

- [ ] **8.3** 개발 APK의 길이·수정 시각·SHA-256과 두 소스 커밋, dirty 여부를 로컬 기록에 남긴다. ZIP 항목을 열어 캐릭터 허용 파일·해시와 고지를 확인하고 개인 설정·등록 정보·개인키·모델 혼입을 검사한다. 개발 APK의 기존 디버그 서명은 유지하며 새 공개 서명·릴리스는 만들지 않는다.
- [ ] **8.4** 최종 `git status`와 Core·APK 제외 규칙을 확인한다. 격리 작업 트리를 사용했다면 검증된 브랜치/산출물 위치를 명시하고 사용자 최종 폴더에 적용하는 통합 단계를 별도로 확인한다. 원본 폴더를 삭제·교체하거나 과거 정리 전 이력을 합치지 않는다.
- [ ] **8.5** 새 APK 경로, 기존 APK 백업 위치, PC 재시작/새 APK 수동 업데이트 필요 여부, 테스트·Lint·빌드 결과를 간결히 보고한다. 실제 기기 설치는 실행하지 않는다. 캐릭터 외형·실제 오디오 출력·Android 수명 시험과 Live2D 출시 허가 확인은 미확인으로 남긴다. push·APK 업로드·릴리스 생성은 하지 않는다.

## 실행 체크포인트

1. 작업 1~2: 확인된 초기화·공개 순서 오류 수정과 집중 검증.
2. 작업 3~6: 출력 정책·양쪽 진단·설정 통합. 현재 발화/다음 선택 분리 검증.
3. 작업 7~8: 전체 자동 검증·기존 산출물 보존·로컬 APK 빌드·인계.

계획을 따른 결과가 명세와 충돌하거나 기존 사용자 데이터/변경을 덮어써야 한다면 해당 단계에서 중단하고 확인한다. 동일 원인 분석을 여러 에이전트에게 중복 맡기거나 매 작업마다 별도 리뷰 체인을 만들지 않는다.
