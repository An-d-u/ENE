# ENE 캐릭터·자동 음성 출력 구현 계획

> **구현 에이전트:** 필수 하위 스킬은 @superpowers:executing-plans다. 사용자 실행 규칙에 따라 현재 작업에서 순차 직접 구현하고, 아래 체크박스로 진행을 기록한다. 작업별 에이전트 생성은 하지 않는다. 테스트에는 @superpowers:test-driven-development, 완료 확인에는 @superpowers:verification-before-completion을 적용한다.

**목표:** 실제 PC ENE 대화에 연결된 Android 앱에서 PC 생성 음성의 자동 출력 전환, Live2D 표시·립싱크, 쓰다듬기와 공통 움직임 설정 연동을 구현한다.

**구조:** 기존 텍스트/TLS 계약을 유지하고 협상된 확장 제어만 WSS에 추가한다. PC가 작업·출력·캐릭터 상태를 소유하며 음성과 모델 데이터는 별도의 인증된 HTTPS 경로로 보낸다. Android는 네이티브 PCM 재생과 앱 내부 콘텐츠 전용 WebView를 사용한다.

**기술:** 기존 Python/PyQt6/aiohttp/pytest/Node VM, Kotlin 2.2.21/Compose/Coroutines/OkHttp 5.3.2, Android AudioTrack·AudioManager, AndroidX WebKit 1.15.0. 기존 Live2D 웹 라이브러리는 출처·버전·권리 확인 후 그대로 고정한다.

**검토 상태:** 계획 문서 리뷰 승인. A0~A4와 B1~B4 완료, B5부터 순차 진행 중. 실기기 시험은 보류한다.

---

## 1. 실행 기준과 경로

승인 명세: [캐릭터·음성 확장 설계](../specs/2026-09-16-ene-companion-media-design.md). 선행 작업: [텍스트 LAN 구현 계획](2026-09-08-ene-companion-lan-v1.md) Task 7~10. TLS 기준: [TLS 설계](../specs/2026-09-08-ene-companion-tls-design.md).

- `PC`는 기존 ENE `.worktrees/companion-lan-v1` 작업 트리다. 브랜치 `codex/companion-lan-v1`, 계획 작성 전 HEAD `6624f96e`. 원본 `main`은 수정하지 않는다.
- `APP`은 ENE의 형제 디렉터리 `ENE_APP` 독립 저장소다. 브랜치 `codex/companion-tls-v1`, HEAD `d6671e8`. 두 저장소에 각각 커밋하며 push·릴리스·저장소 생성은 하지 않는다.
- 아래 경로는 각 저장소 루트 기준이다. 반복을 줄이기 위해 `K`는 APP `app/src/main/java/dev/ene/companion`, `T`는 APP `app/src/test/java/dev/ene/companion`, `I`는 APP `app/src/androidTest/java/dev/ene/companion`로 고정한다. 예를 들어 `K/audio/PcmPlayer.kt`는 APP `app/src/main/java/dev/ene/companion/audio/PcmPlayer.kt`다.
- 실제 단말 설치, adb, 실기기 시험, 방화벽 변경, Tailscale, 유료 AI/TTS 호출은 실행하지 않는다. instrumentation은 컴파일만 하고 미실시로 기록한다.
- 현재 Android Task 5에 구현된 전체 대화·초안·접수 복구·전경 연결을 다시 만들지 않는다. 기존 계획의 오래된 `EneApp.kt`/별도 ChatViewModel 가정 대신 실제 `EneApplication.kt`와 `ConnectionRepository.kt`를 사용한다.
- 승인되지 않은 SDK·모델의 재배포는 하지 않는다. 권리 확인이 막히면 해당 자산 포함만 중단하고 상태 기계·가상 렌더러 시험은 계속한다. 완성된 Live2D 연동으로 표시하지 않는다.

복잡도는 높으며 의존성이 순차적이다. 결과를 `A 실제 대화`, `B 음성`, `C 캐릭터 표시`, `D 상호작용`, `E 통합` 체크포인트로 나눈다. 전체 테스트는 A/B/D/E 통합 시점에만 실행하고 그 외에는 해당 작업 집중 테스트를 사용한다.

## 2. 파일 구조와 소유권

| 경계 | 생성할 파일 | 수정할 기존 파일 |
| --- | --- | --- |
| 실제 대화 A | PC 기존 계획 Task 7~10의 파일 | 같은 계획의 한정된 bridge/앱/PC 채팅 경계 |
| 확장 계약 | 양쪽 `contracts/companion/v1/media.md`, `media_cases.json`; PC `src/core/companion/extension_protocol.py`; APP `K/protocol/ExtensionMessage.kt`, `ExtensionCodec.kt` | PC `protocol.py`, `session.py`, `gateway.py`, `adapter.py`; APP `K/protocol/ProtocolCodec.kt` |
| 음성 순수 상태·바이트 | PC `src/core/companion/audio_route.py`, `audio_buffer.py`; APP `K/audio/AudioSession.kt`, `PcmBuffer.kt`, `PlaybackClock.kt` | 직접 네트워크·Qt 의존 없음 |
| PC 음성 연결 | PC `src/core/companion/audio_coordinator.py`, `media_http.py`, `connection_resources.py` | PC `bridge_mixins/tts.py`, `bridge_mixins/companion.py`, `audio_player.py`, `companion/controller.py` |
| APP 음성·전송 | APP `K/audio/PcmPlayer.kt`, `AudioFocusController.kt`; `K/connection/MediaTransport.kt`, `ExtensionSession.kt` | APP `ConnectionRepository.kt`, `ConversationSession.kt`, `SessionExchange.kt`, `EneApplication.kt`, `MainActivity.kt` |
| 공유 렌더러 | PC `assets/web/runtime_character_host.js`, `character/index.html`, `character/entry.js`, `character/style.css`; `tools/export_companion_character.py` | PC 기존 캐릭터 runtime JS·`index.html`·`script.js` |
| PC 캐릭터 상태·자산 | PC `src/core/companion/character_state.py`, `character_assets.py`; `contracts/companion/character-runtime.json` | PC `overlay_window.py`, `bridge.py`, `bridge_mixins/companion.py`, `media_http.py` |
| APP 캐릭터 | APP `K/character/CharacterRepository.kt`, `CharacterCache.kt`, `CharacterWebView.kt`, `CharacterBridge.kt`; `app/src/main/assets/character/`의 명시적 파일 묶음 | APP `K/ui/ConnectionScreen.kt`, `gradle/libs.versions.toml`, `app/build.gradle.kts`, `app/gradle.lockfile`, `gradle/verification-metadata.xml` |
| 설정·입력 | PC `src/core/companion/character_controls.py`, `head_pat.py`; APP `K/character/CharacterControls.kt`, `K/ui/CharacterSettingsSheet.kt` | PC `settings.py`, `app.py`, `overlay_window.py`, `bridge_mixins/live2d_parameters.py`, `bridge_mixins/mood.py`, `src/ui/settings_dialog.py`, `settings_dialog_values.py`, `live2d_parameter_window.py`; 양쪽 캐릭터 어댑터 |

PC 경로 표의 축약 파일명은 모두 `src/core/` 아래다. 신규 테스트 파일은 각 작업에 정확히 적는다. 큰 기존 파일은 연결 지점만 수정하고 새 상태 기계를 그 안에 넣지 않는다.

스레드 규칙: PC 상태/출력 결정/설정 커밋은 Qt, HTTPS와 socket은 기존 asyncio 루프, 자산 읽기·해시는 취소 가능한 제한된 worker다. Android 연결·상태는 기존 직렬 수명, HTTP/파일/AudioTrack 쓰기는 별도 IO, WebView는 Main이다. Qt signal 한 개에 PCM 조각마다 무한 queued 이벤트를 쌓지 않고 한도 있는 mailbox와 최대 한 개의 깨우기 신호를 사용한다.

## 3. 구현할 계약

### 3.1 공통 봉투와 협상

기존 `hello.capabilities`와 `ready.capabilities`는 교집합을 사용한다. `character_controls_v1`은 `character_v1`도 있을 때만 유효하다. 모듈이 실제 연결되기 전에는 능력을 광고하지 않는다. 구형 앱/PC에는 새로운 message type을 보내지 않는다.

확장 능력이 하나라도 있으면 ready 다음에 `extensions_ready`를 보내며 기존 ready의 필수 필드를 바꾸지 않는다. 확장 봉투 `X`는 `protocol_version=1`, `type`, `registration_generation`(양의 안전 정수), `server_epoch`(UUID), `connection_generation`(UUID)다. gateway_generation은 PC 내부 AdmissionContext로 추가 검증한다. 연결 식별자를 URL에 넣지 않는다. 미협상 확장·다른 세대는 실행하지 않으며 base 대화 `event_seq`와 revision을 변경하지 않는다.

UUID는 기존 계약 검사기를 재사용하고 숫자는 boolean과 구분한다. 문자열은 UTF-8·surrogate·깊이 제한을 유지한다. 고정 오류 코드는 64자 이내다. 알 수 없는 최상위 필드는 기존 허용 목록으로 제거하되, 설정 patch의 알 수 없는 키는 전체 거절한다.

| 메시지 | 방향 | X 이외 필수 필드 |
| --- | --- | --- |
| `extensions_ready` | PC→APP | `capabilities`(최대 3개) |
| `audio_availability` | APP→PC | `available`(bool), `conversation_id`, `reason`(고정 코드) |
| `audio_status` | PC→APP | `mode`(`disabled/pc_only/auto`), `reason` |
| `audio_offer` | PC→APP | `conversation_id`, `message_id`, `operation_id`, `utterance_id`(모두 UUID), `sample_rate`, `channels`, `sample_width=2`, `prepare_timeout_ms=2000` |
| `audio_prepared` | APP→PC | 위 4개 참조 ID, `buffered_frames`(0~rate×4) |
| `audio_rejected` | APP→PC | 위 참조 ID, `reason` |
| `audio_start` | PC→APP | 위 참조 ID; 재생 허가가 아닌 다른 메시지로 시작하지 않음 |
| `audio_started` | APP→PC | 위 참조 ID, `played_frames=0` |
| `audio_source_end` | PC→APP | 위 참조 ID, `total_frames`(0~rate×180) |
| `audio_progress` | APP→PC | 위 참조 ID, `played_frames`, `mouth_open`(유한 0~1) |
| `audio_progress_ack` | PC→APP | 위 참조 ID, 수락한 `played_frames`; APP의 반쪽 제어 단절 감지에 사용 |
| `audio_finished` | APP→PC | 위 참조 ID, `played_frames` |
| `audio_cancel` | 양방향 | 위 참조 ID, `reason` |
| `character_changed` | PC→APP | `state_revision`(양수), `model_version`(SHA-256 또는 null), `reason` |
| `character_snapshot_request` | APP→PC | 추가 필드 없음; 합쳐서 요청하며 동시 1개 |
| `character_action` | PC→APP | `action_seq`(단조 증가), `model_version`, `kind`(`expression/gesture`), `action_id`(공개 허용 ID), `duration_ms`(0~30000) |
| `character_playback` | PC→APP | `conversation_id`, `message_id`, `utterance_id`, `output`(`pc/phone/none`), `played_ms`(0~180000), `mouth_open`, `active`(bool) |
| `head_pat` | APP→PC | `model_version`, `interaction_id`(UUID), `interaction_no`(단조 증가), `seq`, `phase`(`start/update/end/cancel`), `intensity`(0~1) |
| `head_pat_state` | PC→APP | 같은 세션/모델/순서 필드, `source`(`pc/phone`), `phase`(`accepted/update/ended/cancelled/rejected`), `intensity`, `reason` |
| `character_settings_patch` | APP→PC | `model_version`, `command_id`(UUID), `expected_revision`, `changes`(아래 허용 키), `parameters`(ID→수치/null; null은 보정 삭제) |
| `character_settings_result` | PC→APP | `command_id`, `status`(`accepted/conflict/rejected`), `settings_revision`, `reason` |
| `extension_error` | PC→APP | `feature`(협상된 능력), `code`, 선택적 `command_id`; 채팅의 치명적 `error`와 구분 |

음성 참조 묶음은 `AudioRef`로 운반한다. `operation_id`는 PC가 실제 내부 작업 ID와 맵핑하는 공개 UUID이며 최신 전역 요청에서 재구성하지 않는다. 처리 예외의 원문·파일 경로·토큰은 봉투에 넣지 않는다. 제어 메시지 총 64KiB, 진행/입력 갱신은 2KiB 이하, settings patch는 48KiB 이하·보정 256개로 제한한다.

### 3.2 HTTPS와 캐릭터 스냅샷

모든 경로는 `Authorization: Bearer ...`, `X-ENE-Connection`에 현재 연결 UUID를 요구한다. 기존 TLS 검증을 재사용하고 `Cache-Control: no-store`, 압축 없음, query/Origin/Range/redirect 거절을 적용한다. 인증 401, 구연결/없는 자산 404, 정책 위반 400, 제한 429, 취소된 음성 410을 사용하고 고정 코드만 반환한다.

- `GET /companion/v1/audio/{utterance_id}`: `Content-Type: application/octet-stream`, `X-ENE-Audio-Format: pcm_s16le`, `X-ENE-Sample-Rate`, `X-ENE-Channels`. 프레임 정렬된 PCM만 읽고 offer와 헤더 일치를 검사한다. HTTP 종료와 `audio_source_end.total_frames`가 모두 일치해야 정상 종료다. 동시 1개·음성 ID당 최초 소비 1회; 재접속·Range 재생 없음.
- `GET /companion/v1/character/manifest`: 스냅샷 `{model_id, model_version, runtime_version, state_revision, settings_revision, action_seq, settings, parameters, parameter_catalog, expression_ids, gesture_ids, default_expression, assets, entry_asset_id, status}`. `action_seq`는 캡처 시점의 마지막 일회성 사건 번호다. 미지원/모델 없음은 `status`와 빈 목록, null 모델 ID로 표현한다. 전체 256KiB.
- `assets` 원소는 `{id, sha256, size, mime}`. `parameter_catalog`는 최대 256개 `{id,min,max,default}`이고 표시 문자열도 길이 128 이내다. 순서 변화가 버전을 바꾸지 않도록 정렬한다. 모델 경로나 표시 이름은 포함하지 않는다.
- `GET /companion/v1/character/assets/{asset_id}`: 현재 manifest에 있는 자산만 제공한다. 자산 ID는 원본 바이트 SHA-256, 전달 해시는 안전한 참조로 변환한 뒤 계산한다. JSON 내 파일 참조는 같은 자산 묶음의 ID 상대 경로로 바꾸고 원래 파일명을 보내지 않는다. 지원하지 않는 선택적 Sound 참조는 제거하고 그 음향 파일은 전달하지 않는다.

모델 버전은 변환된 manifest의 불변 자산 목록과 실행부 버전의 해시다. 동일 바이트/실행부는 서버 재시작 후에도 같은 버전을 유지한다. 조회 중 현재 버전이 바뀌면 다운로드를 취소하고 새 manifest로 시작한다. 프리뷰/서버별 자산을 섞지 않는다. 파일 변경 경합에 대비해 파일 핸들과 메타데이터를 확인하고 실제 전달 바이트의 해시를 검증한다. 검증 중 변경되면 제공하지 않는다.

한 연결의 HTTP는 음성 1개+자산 2개+manifest 1개 이내다. 인증 이후 데이터 요청 제한은 초당 8개·버스트 16개, 제어 확장 제한은 초당 30개·버스트 60개다. 대화 전송 제한과 분리한다. asset 읽기 유휴 10초·총 60초, 전체 모델 받기 5분 한도다. 미인증 경로는 기존 preauth 제한을 적용한다.

### 3.3 수치·상태 규칙

| 경계 | 고정 값 |
| --- | --- |
| 음성 | PCM16LE, 채널 1/2, rate 8000~48000, 조각 최대 32768바이트, 180초·36MiB 이하 |
| 전송 메모리 | 각 PC/APP의 새 전송 대기 버퍼 합계 `min(rate×channels×2×4, 1MiB)`; 중복 prefix도 합산 |
| 음성 준비 | 200ms 또는 EOF인 더 짧은 전체 음성, PC 제안 2초, APP 준비 후 허가 3초 |
| 진행 | 실제 위치 조회 50ms, 전송 100~500ms 간격, 보고 누락 또는 위치 정지 5초면 취소 |
| 반대편 입 모양 | 최대 10Hz, 마지막 갱신 750ms 초과면 입을 닫음 |
| 모델 | 파일 256개, 합계 128MiB, 한 파일 32MiB, 텍스처 한 변 8192px, manifest 256KiB |
| 캐시 | 서버 신원별, 앱 전체 256MiB·최대 두 버전, 준비 중 파일도 합산, 백업 제외 |
| 입력 | 쓰다듬기 갱신 10Hz 이하, 유휴 2초, 완료 ID 256개+연결별 최대 수락 번호 |

PC에 이미 완성된 WAV가 있는 경우 원본 immutable bytes 한 개를 최대 36MiB까지 참조하고, 네트워크 쓰기는 소비 속도에 맞춰 조각 단위로 수행한다. 완성 음성 전체를 4초 큐에 한 번에 넣지 않는다. 생성 중 스트림은 작은 prefix를 보존하되 PC 전환 전 포화가 임박하면 폰 제안을 취소하고 그 prefix부터 PC sink로 한 번만 전달한다. 폰 확정 이후 포화는 취소이며 동일 발화를 PC에서 재생하지 않는다.

출력 상태는 `PC`, `OFFERED`, `PHONE_COMMITTED`, `PLAYING`, `DONE`이다. `PHONE_COMMITTED`는 start를 socket에 넘기기 전에 Qt에서 기록한다. `send` 결과 유실/실패 후 PC로 되돌리지 않는다. 진행 watchdog은 PC/APP 모두 단조 시계를 사용한다. APP은 100~500ms 간격으로 보낸 progress에 대한 ACK가 5초 동안 없으면 중단한다. 기본 heartbeat의 nonce나 주기를 바꾸지 않는다.

공통 설정의 `settings_revision`과 캐릭터 `state_revision`을 분리한다. 모바일 patch는 오래된 settings_revision이면 항상 충돌이다. PC 설정 창은 열 때 baseline과 수정 키를 보관하고 키별 마지막 변경 revision으로 검증한다. 겹치지 않는 수정은 최신 상태에 병합하되 겹치는 키가 외부에서 바뀌었으면 저장하지 않고 갱신한다. 제스처/표정이 바뀌었다는 이유로 설정 저장을 거절하지 않는다.

## 4. 검증·커밋 공통 규칙

각 작업은 `실패 사례 추가 → 아래 집중 명령으로 의도한 실패 확인 → 최소 구현 → 같은 명령 통과 → diff/개인정보 검사 → 명시한 파일만 커밋` 순서다. ImportError 같은 최초 실패를 확인한 뒤 실제 동작 assertion으로 검증한다. 기존 테스트가 환경 문제로 실패하면 원인을 구분하고 새 기능의 실패 증거로 세지 않는다.

PC 집중 명령은 PC 루트, Gradle은 APP 루트에서 실행한다. Android 명령에 적힌 `--offline --dependency-verification strict --console=plain` 옵션을 유지한다. 새 의존성을 처음 받는 C3만 공식 저장소 네트워크를 허용하고 검증 해시/lock을 갱신한 뒤 다시 offline strict로 확인한다. 기존 의존성 해시 변경을 자동 승인하지 않는다.

모든 신규·수정 문서는 UTF-8 BOM 없이, 주석·설명은 한국어로 쓴다. 테스트는 직접 만든 중립 문장, 메모리에서 생성한 PCM, 안전한 시험 JSON만 사용한다. 실제 모델·설정·사용 기록·API 키를 읽지 않는다. 커밋 전에 변경분에서 실제 이름/대화/생일/건강/일정/취업/프로필과 키 패턴을 검색하고 사람이 후보를 확인한다. 발견 시 커밋을 중단한다. `git add .`나 바이너리 산출물 추가를 하지 않는다.

아래는 구현 예정 코드/테스트 기준이며 이번 계획 작성에서 실행·통과한 결과가 아니다.

## 5. A — 실제 ENE 대화 선행 통합

### A0. 작업 기준 확인

**파일:** 수정 없음. 기존 계획과 두 저장소 상태만 확인한다.

- [x] 양쪽 `git status --short`, `git log -1 --oneline`을 읽고 관련 사용자 변경이 있으면 보존한다. 새 worktree/저장소를 만들지 않는다.
- [x] PC `python -m pytest tests/test_companion_protocol.py tests/test_companion_adapter.py tests/test_companion_gateway.py tests/test_companion_tls_gateway.py -q`를 실행한다. 결과: 96개 통과.
- [x] APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.ConnectionRepositoryTest" --tests "dev.ene.companion.TlsTransportTest" --offline --dependency-verification strict --console=plain`를 실행한다. 결과: 기존 연결 24개, TLS 9개 통과.
- [x] Task 6과 계측 시험은 미완료로 유지한다. 설치·방화벽 변경 없이 자동 검증만 실행했다.

PC의 최초 기준 실행은 임시 폴더 생성 권한 때문에 58개 통과/38개 준비 오류였다. 신규 전용 basetemp와 권한 조정 후 같은 기준 시험 96개가 통과했다. 기능 코드 수정으로 해결한 오류는 아니다. 기준 HEAD는 PC `2916ccef`, APP `d6671e8`, 원본 PC `main`은 `c620a057`이다.

### A1. 공개 대화와 요청 소유권

**파일:** PC `src/core/bridge_mixins/companion.py`, `tests/test_companion_bridge_transcript.py` 생성. 기존 계획 Task 7의 정확한 수정 파일을 사용한다.

- [x] 기존 계획 Task 7의 체크리스트를 실행한다. 특히 공개 전 TTS 대기·실패·자동 요약·초기화 후 전체 기록의 일치와 늦은 콜백 폐기를 먼저 실패 테스트로 만든다.
- [x] `python -m pytest tests/test_companion_bridge_transcript.py -q`로 실패를 확인한다. 최초 12개 실패, 추가 파일/첨부 분류 8개 실패를 확인했다.
- [x] 내부 operation에서 불변 RequestRef와 공개 message_id를 운반하고 공개 전/후 상태를 조회할 수 있게 한다. 모바일 비활성 상태에서도 공개 기록은 유지한다.
- [x] 같은 명령과 기존 계획 Task 7의 명시된 회귀 명령을 실행한다. 결과: 신규 22개 포함 196개 통과. 생활 기록·첨부·파일 명령·pending 회귀까지 합쳐 314개 통과.
- [x] 해당 파일만 `feat: 현재 대화의 공개 기록 경계 추가`로 커밋한다.

A1에서 `PreparedChatRequest`에 선택적 불변 참조를 추가하기 위해 `bridge_mixins/life_records.py`도 수정했다. 자동 발화 세 경로는 공통 `_start_ai_worker`에서 소유권을 받으므로 개별 파일은 바꾸지 않았다. 기존 파일 명령 테스트 대역은 새 인자에 맞춰 수정했다. 공개 이벤트와 PC 전용 표시를 분리했으며 PC의 ID 기반 렌더링 전환은 A3에서 수행한다. 공개 메시지 ID 대응을 추가했지만 편집·리롤의 수락 검사는 아직 A3 범위다.

### A2. 공통 수락과 중복 방지

**파일:** PC `tests/test_companion_admission.py`, `test_companion_request_lifecycle.py`; 나머지는 기존 계획 Task 8의 생성/수정 파일이다.

- [x] 같은 request ID 재전송·PC와 폰 동시 입력·준비 중 취소의 worker/기억/기분 처리 횟수 테스트를 추가한다.
- [x] `python -m pytest tests/test_companion_admission.py tests/test_companion_request_lifecycle.py -q`의 의도한 실패를 확인한다. 접수 API 부재 19개 실패 후, 준비 예외·취소·완료/실패 알림 재진입·종료 중 TTS 표시의 단언 실패를 확인했다.
- [x] 기존 Task 8의 단일 gate와 원장 수락 규칙을 구현한다. 음성 확장을 위한 별도 AI queue를 만들지 않는다.
- [x] 위 명령과 기존 Task 8 회귀를 통과시킨다. `feat: PC 모바일 공통 접수와 중복 방지 연결`로 커밋한다.

A2 검증: 신규 접수·수명 33개, A1·Qt adapter·기존 프로토콜/원장/공개 기록·생활 기록·첨부·기분·TTS·파일 명령을 합쳐 321개 통과. 변경 핵심 파일의 `ruff --select E9,F63,F7,F82` 검사도 통과했다. 예약 상태에서는 사용자 기록/일반 AI 작업을 시작하지 않고, 준비 성공·실패 후 한 번만 commit한다. 명시적인 준비 취소·종료는 실패로 마감한다. 완료/실패 신호 안에서 다음 요청이 들어와도 새 worker와 처리 표시를 보존한다. 네트워크 연결 해제/서버 재시작 자체는 이미 예약한 요청을 취소하지 않는다. 공통 Qt 시험 앱은 후속 UI 시험과 충돌하지 않도록 화면 없는 QApplication을 사용한다. PC의 기존 화면 입력 확인 방식은 A3에서 변경한다.

### A3. PC 표시·편집·리롤 경계

**파일:** PC `assets/web/runtime_companion_chat.js`, `tests/test_companion_pc_ui.py`, `test_companion_edit_reroll.py`; 기존 Task 9의 수정 파일.

- [x] 초안 보존, 표시보다 늦은 수락, 폰 입력의 PC 렌더링, stale 편집/리롤 대상 테스트를 만든다.
- [x] `python -m pytest tests/test_companion_pc_ui.py tests/test_companion_edit_reroll.py -q`로 실패를 확인한다.
- [x] Task 9의 단일 공개 표시 이벤트와 ID 기반 갱신을 구현하고 같은 명령 및 그 작업의 UI 집중 회귀를 통과시킨다.
- [x] `fix: 공유 대화의 입력 보존과 편집 대상 검증`으로 커밋한다. 전체 테스트는 바로 다음 A4와 묶어 한 번만 실행한다.

A3 검증: PC UI 12개와 표시/편집 경계 21개를 포함한 UI·공개 기록·접수 회귀 270개 통과. 변경 Python 파일의 `ruff --select E9,F63,F7,F82` 통과. 실제 전송/PTT/편집 진입 함수를 Node VM에서 실행했다. 첨부 삭제 뒤 PC 상태 재적용, 동기 완료 순서, 실패한 재생성의 원래 ID/기록/PC 메타데이터 복원, 생성 실패 전 예약 항목 보존, 초기화 뒤 늦은 결과 폐기를 추가 검증했다.

PC 전용 정보는 새 `bridge_mixins/companion_pc.py`에 분리했다. 기존 `attachments.py`의 메시지 ID를 공개 ID와 일치시키고, 예약/선제 항목 삭제 helper는 수락된 재생성의 원본 payload를 받을 수 있도록 최소 수정했다. 편집·리롤 명령은 응답과 UI 초안을 정확히 연결할 선택적 요청 UUID를 추가한다. V1 편집/리롤 대상은 현재 마지막 일반 사용자/답변 쌍이다. 기존 PC 파일 명령의 새 전송은 유지하지만, 공개 일반 메시지를 파일 명령으로 바꾸는 편집은 원문 공개를 방지하기 위해 부작용 없이 거절한다. 파일 명령은 새 입력으로 실행한다. 실기기/UI 수동 인수는 아직 수행하지 않았다.

### A4. 실제 앱 수명과 선행 통합 체크포인트

**파일:** PC `tests/test_companion_app_lifecycle.py`, `test_companion_revocation.py`; 기존 Task 10의 수정 파일. APP 신규 구현 없음.

- [x] 기본 비활성, 리슨 성공 뒤 QR, gateway 재시작, queued 구등록 명령 차단, 20회 시작/종료 테스트를 추가한다.
- [x] `python -m pytest tests/test_companion_app_lifecycle.py tests/test_companion_revocation.py -q`로 실패를 확인한다.
- [x] Task 10을 구현하되 기존 TLS controller/identity를 재사용한다. 실제 앱이 smoke 가상 어댑터를 가져오지 않도록 한다.
- [x] 위 명령, 기존 Task 10의 집중 회귀, `python -m pytest -q`, `python -m ruff check . --select E9,F63,F7,F82`를 실행한다. 예상: 새 실패/스레드·socket 누수 없음.
- [x] `feat: ENE 모바일 연결 설정과 서버 수명 통합`으로 커밋한다. 실제 단말 왕복은 미검증으로 기록한다.

A4/A 통합 검증: 전체 PC 3,585개 통과·1개 건너뜀, `ruff --select E9,F63,F7,F82` 통과. A4 신규 19개에는 실제 TLS 서버 20회 반복, 포트 반환, 설정 저장 실패, 실제 WebBridge+가상 provider+TLS 소켓의 QR 승인/대화/중복 전송, 비상 종료 시 Qt ACK 없는 해제를 포함한다. 기존 서버·등록·앱 종료·설정·번역 집중 회귀 253개도 통과했다. 첫 전체 실행의 실패 3개는 옛 표시 신호/앱 대역의 계약을 갱신하여 해소한 뒤 전체를 재실행했다.

통합 명세·품질 검토는 요청대로 단일 에이전트가 변경 범위와 검토 체크리스트를 대조했다. 종료 시 Qt 수락 권한을 먼저 폐기하고, 차단 뒤 새로 생성된 네트워크 호출도 즉시 거절하도록 보완했다. 일반 종료는 기존 비차단 drain에 참여하며, aboutToQuit 비상 경로에만 최대 200ms join을 허용한다. 제한 시간 초과는 고정 경고 코드로 남기고 정상 세션 종료로 기록하지 않는다. 연결 설정 저장은 기존 실패를 삼키는 Settings.save 대신 비밀 파일을 건드리지 않는 원자 저장 경계를 추가했다. 기존 TLS 등록 저장·실패 복원 구현은 그대로 재사용했다. 트레이의 새 표시 키와 새 오류 두 종류는 ko/en/ja에 함께 추가했고, 기존 연결 dialog의 한국어 설명은 유지했다. 원본 main·Android 소스는 A 단계에서 수정하지 않았고, 실기기 설치·왕복·오디오·캐릭터 시험은 미실시다.

## 6. B — PC 생성 음성과 자동 출력

### B1. 양쪽 확장 계약

**파일:** §2 확장 계약 파일; PC `tests/test_companion_extension_protocol.py`, APP `T/ExtensionCodecTest.kt` 생성. 기존 양쪽 `protocol.md`에 확장 링크만 추가한다.

- [x] §3 봉투/메시지/한도별 합성 사례를 양쪽 동일한 `media_cases.json`에 작성한다. 미협상, 구세대, boolean 정수, NaN/무한대, 잘못된 참조와 text event_seq 보존 사례를 포함한다.
- [x] PC `python -m pytest tests/test_companion_extension_protocol.py -q`, APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.ExtensionCodecTest" --offline --dependency-verification strict --console=plain`의 실패를 확인한다.
- [x] PC `extension_protocol.py`와 APP `ExtensionCodec.kt`를 기본 해석기에 연결한다. Android 직렬화 하위 메시지는 `ExtensionMessage.kt`에 둔다. 새 예외는 원문을 보관하지 않는다.
- [x] 기존 `cases.json`을 수정하지 않고 신규·기존 ProtocolCodec/companion_protocol 테스트를 함께 통과시킨다. 양쪽 계약 파일 SHA-256 일치를 확인한다.
- [x] 각 저장소의 계약/해석기/테스트만 `feat: 동반 앱 미디어 확장 계약 추가`로 커밋한다.

B1 검증: 공통 사례 97개, PC 확장 110개 포함 기본 프로토콜·세션·gateway 194개 통과. Android 확장 4개/기존 계약 4개/ConnectionRepository 24개 통과(각 테스트 내 공통 사례 반복 포함). Kotlin 직렬화 증분 컴파일의 내부 오류는 증분을 끈 재컴파일 후 정상 옵션에서도 해소됐으며 의존성 버전을 바꾸지 않았다. 모델 없음의 필수 null 유지와 Python 큰 정수 변환의 안전한 오류를 추가 검증했다. media.md/media_cases.json/protocol.md의 양쪽 SHA-256 일치, 기존 cases.json 변경 없음, PC 정적 검사 통과. 해석기와 순수 권한 검사만 연결한 단계로, 실제 세션의 능력 광고는 아직 빈 목록이다. 음성·캐릭터 조정기가 준비된 뒤 B7/C/D에서 수신 실행 경계를 연결한다.

### B2. 순수 출력 상태 기계

**파일:** PC `src/core/companion/audio_route.py`, `tests/test_companion_audio_route.py`; APP `K/audio/AudioSession.kt`, `T/AudioSessionTest.kt` 생성.

- [x] 가상 시계로 허가 전 시간 초과, 준비 이후 focus 상실, 허가 전송 실패, 중복 ACK, 구세대 종료, 5초 무진행을 테스트한다. 아래 핵심 불변식을 실행 사례로 만든다.

```python
def test_start_delivery_uncertainty_never_falls_back_to_pc():
    route = AudioRoute()
    assert route.offer(now_ms=0, phone_eligible=True) == "offer_phone"
    assert route.prepared(now_ms=100) == "send_start"
    assert route.target == "phone"
    assert route.delivery_failed() == "cancel"
    assert route.target == "phone"
    assert route.finish() == "complete_once"
    assert route.finish() == "ignore"
```

- [x] PC `python -m pytest tests/test_companion_audio_route.py -q`, APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.AudioSessionTest" --offline --dependency-verification strict --console=plain`로 실패를 확인한다.
- [x] `AudioRoute`는 출력 명령 문자열을 반환하는 순수 상태 기계로 구현하고 Qt/socket을 직접 호출하지 않는다. 전이의 핵심은 다음과 같다.

```python
def prepared(self, now_ms):
    if self.state != "OFFERED":
        return "ignore"
    if now_ms >= self.deadline_ms:
        self.state, self.target = "PC", "pc"
        return "play_pc"
    self.state, self.target = "PHONE_COMMITTED", "phone"
    return "send_start"
```

- [x] APP은 `PREPARING/WAITING_START/PLAYING/DONE`과 세대·AudioRef를 검사한다. 허가 만료/중복 허가가 `player.play()`를 추가 호출하지 않음을 fake sink로 확인한다.
- [x] 두 집중 명령을 통과시키고 양쪽 `feat: 음성별 자동 출력과 중복 재생 차단`으로 커밋한다.

B2 검증: PC 15개, Android 11개 통과. 순수 상태와 가상 sink로 허가 전 PC 전환/허가 후 재생 취소, 중복 시작 차단, 세대와 발화 참조, 실제 진행 정지와 진행 ACK 단절, 지연 응답의 만료 복구 금지를 확인했다. 실제 네트워크·AudioTrack 연결은 B4~B7에서 수행한다.

### B3. PCM 검사와 제한된 버퍼

**파일:** PC `src/core/companion/audio_buffer.py`, `tests/test_companion_audio_buffer.py`; APP `K/audio/PcmBuffer.kt`, `PlaybackClock.kt`, `T/PcmBufferTest.kt`, `PlaybackClockTest.kt` 생성.

- [x] 메모리 WAV의 헤더/알 수 없는 chunk/홀수 padding/잘린 프레임, 8/48kHz·모노/스테레오, PCM 이외 형식 거절, 4초 상한, 재생 위치 역전·reset을 테스트한다.
- [x] PC `python -m pytest tests/test_companion_audio_buffer.py -q`, APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.PcmBufferTest" --tests "dev.ene.companion.PlaybackClockTest" --offline --dependency-verification strict --console=plain`의 실패를 확인한다.
- [x] PC 완성 WAV는 stdlib `wave`로 무압축 PCM16만 수락하고 원본 bytes 참조+cursor로 제공한다. 스트림은 프레임 정렬된 bounded deque, prefix 보관과 전송 대기를 중복 복제하지 않는다. 반환은 `accepted/full/invalid/closed`로 명확히 구분한다.
- [x] APP은 50ms PCM 구간의 RMS를 계산해 `mouth_open=min(1, rms×3)`로 사용한다. 실제 소비한 frame 구간만 적용하고 stereo는 전체 sample RMS를 사용한다. 구간별 값은 재생/입모양 적용 후 버린다.
- [x] AudioTrack 누적 위치는 음성별로 초기화하고 unsigned 32비트 playback head를 Long으로 확장한다. 실제 쓰기보다 큰 위치·이전 player의 callback을 거절한다.
- [x] 같은 명령 통과 후 양쪽 `feat: 제한된 PCM 버퍼와 재생 시계 추가`로 커밋한다.

B3 검증: PC 버퍼 21개와 B2 15개, Android 버퍼 6개/시계 3개/B2 11개 통과. 완성 WAV의 원본 참조 유지, 10초 음성 분할, 잘못된 PCM 헤더 필드, prefix 포함 용량·조각 개수·누적 길이, 부분 소비 시 실제 보관 메모리, RMS의 실제 소비 후 적용을 확인했다. Android buffer 예약량에는 이후 B6에서 native buffer와 HTTP scratch를 포함한다. 실제 장치 출력은 아직 연결하지 않았다. 형식/시계 확인에 [Python wave 문서](https://docs.python.org/3.12/library/wave.html)와 [Android AudioTrack 문서](https://developer.android.com/reference/android/media/AudioTrack#getPlaybackHeadPosition())를 참고했다.

### B4. 인증된 음성 전송과 연결 자원

**파일:** PC `src/core/companion/media_http.py`, `connection_resources.py`, `tests/test_companion_media_http.py`, `test_companion_extension_session.py`; 기존 `gateway.py`, `session.py`, `adapter.py` 수정. APP `K/connection/MediaTransport.kt`, `T/MediaTransportTest.kt` 생성.

- [x] 주 WSS 없는 토큰, 구연결, 소비자 중복, Range/Origin/query/redirect, CA 오류, 구등록, TLS 만료, 취소 중 write, 무응답 반쪽 연결 사례를 추가한다.
- [x] PC `python -m pytest tests/test_companion_media_http.py tests/test_companion_extension_session.py -q`, APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.MediaTransportTest" --offline --dependency-verification strict --console=plain`로 실패를 확인한다.
- [x] gateway가 hello 결과를 버리지 않고 capabilities 교집합을 보관하게 한다. `ConnectionResources`는 현재 연결의 하위 HTTP task/취소 토큰과 bounded buffer만 소유한다. Qt 상태에는 불변 명령으로 접근한다.
- [x] `media_http.py`는 §3.2 정책으로 인증·자원 예약을 먼저 처리한다. 주 WSS 취소는 HTTP를 먼저 취소하고 다음 연결을 받는다. headers/바이트를 읽을 때 기존 TLS identity 유효성 검사와 폐기 신호를 사용한다.
- [x] B1에서 정의한 `audio_progress_ack`를 PC 수락 직후 응답한다. APP은 자신의 progress에 맞는 ACK가 5초 없으면 오디오를 중단한다. 진짜 오래된 ACK의 반복이 생존 시간을 연장하지 않도록 최근 보낸 진행 위치와 대응시키고, 재생 위치 정지 watchdog도 별도로 검사한다. 기본 15초 heartbeat nonce나 주기를 변형하지 않는다.
- [x] APP MediaTransport는 같은 TrustedServer/검증된 Endpoint의 TLS client를 재사용한다. 웹 주소 문자열을 외부에서 받지 않고 고정 경로+검사된 ID로 요청을 구성한다. `ResponseBody`는 cancellation/finally에서 닫고 파일에 저장하지 않는다.
- [x] 위 명령과 기존 양쪽 TLS 테스트를 통과시키고 `feat: 연결에 종속된 인증 미디어 전송 추가`로 각각 커밋한다.

B4 검증: 새 PC HTTP 13개/확장 세션 5개를 포함한 gateway·session·adapter·TLS·등록 해제 81개 통과. Android MediaTransport 8개/TlsClient 6개/TlsTransport 9개/AudioSession 11개 통과. 실제 루프백 TLS에서 토큰만 있는 요청, 구연결, 중복 소비, Origin/Range/query와 별도 rate 제한, 정지된 write 도중 소켓 종료·등록 해제·연결 교체·TLS 만료 시 자원 회수를 확인했다. Qt 진입점의 확장 명령 허용과 수신 방향, 전송 대기 중 대화 초기화 시 옛 start 폐기를 추가 검증했다. Android 시험 서버를 PC와 같은 HTTP/1.1로 고정해 chunked 본문을 확인했다. 진행 ACK는 실제 소유자가 수락한 응답만 전달하며 가상 소유자로 검증했다. B5/B7에서 TTS·재생기를 연결하기 전이므로 기본 광고 능력은 여전히 비어 있다. 실제 PC↔Android 프로그램 왕복이나 실기기 재생으로 기록하지 않는다.

### B5. PC TTS 경계 연결

**파일:** PC `src/core/companion/audio_coordinator.py`, `tests/test_companion_audio_coordinator.py`, `test_companion_tts_routing.py`; 기존 `src/core/bridge_mixins/tts.py`, `companion.py`, `src/core/audio_player.py`, `companion/controller.py` 수정.

- [ ] 기존 가상 TTS worker와 PC/phone sink 계수를 사용해 “생성 1회, 한 출력만 시작”을 테스트한다. 완성 WAV 10초가 4초 큐 포화로 취소되지 않는 사례, 비스트림/스트림/브라우저/미지원형식/음성꺼짐을 포함한다. 포맷 통지 후 첫 PCM이 늦게 도착해도 준비 제한이 먼저 시작되지 않고 첫 유효 PCM/완성 음성부터 2초가 시작되는지 가상 시계로 확인한다.
- [ ] `python -m pytest tests/test_companion_audio_coordinator.py tests/test_companion_tts_routing.py -q`로 실패를 확인한다.
- [ ] `begin(AudioRef, format)`, `offer_pcm(ref, bytes)`, `source_end(ref)`, `cancel(ref, reason)` 경계를 기존 `_process_tts_stream_format`, `_process_tts_stream_chunk`, `_complete_tts_ready`에 연결한다. provider 생성 코드와 Fish Audio 설정을 변경하지 않는다.
- [ ] 음성 첫 출력 경계에서 공개 메시지가 확정되지 않은 기존 PC 표시 방식은 해당 음성을 PC로 고정한다. 폰 출력을 위해 PC 메시지 공개 시점 설정을 바꾸지 않는다. 공개된 메시지·동기화된 연결만 phone offer 대상으로 삼는다.
- [ ] start 허가 뒤 PC sink는 생성/재생하지 않는다. 준비 거절은 보존된 같은 bytes/prefix를 PC에 한 번 전달한다. 늦은 worker와 모든 종료 경로는 AudioRef 검사를 통과해야 한다.
- [ ] phone 재생에는 source 완료와 재생 완료가 둘 다 필요하다. 공급자 완료만으로 기존 reply gate를 풀지 않고 정상 finish/취소/watchdog의 단일 논리 완료에서 해제한다. PC 재생은 기존 completion을 그대로 사용한다.
- [ ] PC `AudioPlayer`에 현재 위치 조회만 추가한다. 완성 재생은 QMediaPlayer.position(), 스트림은 QAudioSink.processedUSecs()를 사용해 과거 타이머 기반 추측 대신 보고한다. 기존 PC 임시 재생 파일의 생성/정리 정책은 유지하며 확장 전송용 파일은 만들지 않는다.
- [ ] 위 집중 시험과 `tests/test_bridge_tts_streaming.py`, `test_bridge_reply_lifecycle.py`, `test_app_tts_bootstrap.py`, `test_fish_audio_tts.py`를 통과시킨다. `feat: PC TTS를 자동 출력 조정기에 연결`로 커밋한다.

### B6. Android 네이티브 출력

**파일:** APP `K/audio/PcmPlayer.kt`, `AudioFocusController.kt`, `T/PcmPlayerTest.kt`, `AudioFocusControllerTest.kt`, `I/AudioPlaybackTest.kt` 생성.

- [ ] AudioTrack/AudioManager를 얇은 interface로 감싸 가상 쓰기·부분 쓰기·초기화 실패·포커스 거절/지연/상실·이어폰 분리·5초 정지 테스트를 만든다.
- [ ] `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.PcmPlayerTest" --tests "dev.ene.companion.AudioFocusControllerTest" --offline --dependency-verification strict --console=plain`로 실패를 확인한다.
- [ ] AudioTrack MODE_STREAM/PCM16LE/검사된 rate·channel을 사용한다. 플레이어 buffer와 앱 deque 합계가 4초 한도 안에 들게 한다. native buffer는 최소 `getMinBufferSize`와 200ms 중 큰 값으로 만들고 한도 초과면 미지원으로 거절한다. 시작 전 write는 비차단으로 하며 native/앱 큐를 합쳐 200ms(또는 EOF의 짧은 전체 음성)를 준비하면 된다. native buffer가 빌 때까지 기다리는 준비 코드를 만들지 않는다.
- [ ] AudioFocusRequest는 USAGE_MEDIA/CONTENT_TYPE_SPEECH, GAIN_TRANSIENT, delayed gain 불허, willPauseWhenDucked=true로 구성한다. focus GRANTED 이후 prepared를 보내고 실제 play는 start를 받은 뒤에만 호출한다. 상실/분리/중단은 pause-resume이 아니라 stop/flush/release다.
- [ ] blocking write를 Main에서 하지 않는다. 중단 시 coroutine 취소뿐 아니라 native stop으로 write를 깨우고 reader/job을 회수한 뒤 release한다. 한 음성당 sink/receiver/focus listener는 하나다.
- [ ] EOF와 source_end frame 수가 일치하고 AudioTrack이 모든 frame을 소비한 뒤 audio_finished를 보낸다. 위치를 50ms마다 읽되 네트워크 보고는 100~500ms 간격으로 합친다.
- [ ] 위 JVM 시험과 `./gradlew.bat :app:assembleDebugAndroidTest --offline --dependency-verification strict --console=plain`를 실행한다. 계측은 컴파일만 됐다고 기록하고 `feat: Android PCM 재생과 오디오 포커스 연결`로 커밋한다.

### B7. 앱 수명·확장 수신 분기와 음성 체크포인트

**파일:** APP `K/connection/ExtensionSession.kt`, `T/ExtensionSessionTest.kt`, `AudioLifecycleTest.kt`; 기존 `ConnectionRepository.kt`, `ConversationSession.kt`, `SessionExchange.kt`, `EneApplication.kt`, `MainActivity.kt`, `K/ui/ConnectionScreen.kt` 수정. PC `tests/test_companion_media_integration.py` 생성.

- [ ] 큰 snapshot 중 확장 수신, 연결 변경 중 HTTP 완료, onPause와 focus callback 경합, 회전, 백그라운드 뒤 늦은 start, 기본 heartbeat와 progress ACK 동시 처리를 테스트한다.
- [ ] APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.ExtensionSessionTest" --tests "dev.ene.companion.AudioLifecycleTest" --offline --dependency-verification strict --console=plain`와 PC `python -m pytest tests/test_companion_media_integration.py -q`로 실패를 확인한다.
- [ ] 확장 메시지는 ConversationSession.consume에 넣기 전에 ExtensionSession으로 분기한다. 이 분기는 전체 snapshot 해석/다운로드/AudioTrack drain을 await하지 않고 bounded job을 시작한다. base message의 error/seq 규칙은 그대로 둔다.
- [ ] ProcessLifecycleOwner의 지연된 onStop만 믿지 않고 실제 Activity의 resumed 상태를 별도로 보고한다. onPause 즉시 준비 허가를 차단한다. 회전(`isChangingConfigurations`)은 연결/음성 소유자를 재생성하지 않고 새 Activity의 활성 상태를 재결합한다. 회전 동안 새 start는 허용하지 않는다.
- [ ] ExtensionSession은 주 연결 finally/forget/revoke/close에서 자식들을 회수한다. 대화 resync 중 availability=false, 대화 ID가 바뀌면 현재 음성 취소, 동일 대화의 재동기화는 새 offer만 막는다. UI에는 PC 출력/폰 출력/음성 미지원 상태만 표시하고 수동 선택은 추가하지 않는다.
- [ ] 가상 bridge+실제 TLS gateway+synthetic PCM으로 PC 통합을 확인한다. APP은 MockWebServer에서 같은 계약/인증/단절을 확인한다. 이를 두 프로그램 간 실제 왕복이라고 기록하지 않는다.
- [ ] PC 전체 pytest+Ruff와 APP `./gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest --offline --dependency-verification strict --console=plain`를 실행한다. 예상: 새 실패 없음. 양쪽 관련 변경만 `feat: 전경 수명과 자동 음성 출력 통합`으로 커밋한다.

## 7. C — 공유 Live2D와 캐릭터 표시

### C1. 캐릭터 실행부 분리와 고정된 묶음

**파일:** §2 공유 렌더러 파일; PC `tests/test_companion_character_runtime.py`, `test_companion_character_export.py` 생성. 기존 `runtime_bootstrap.js`, `runtime_live2d_model.js`, `runtime_motion_state.js`, `runtime_gesture_engine.js`, `runtime_head_pat.js`, `runtime_auto_blink_tracking.js`, `runtime_expression.js`, `runtime_lipsync.js`, `runtime_live2d_parameter_core.js`, `runtime_bridge.js`, `script.js`, `index.html`에서 실제 의존 지점만 수정한다.

- [ ] Node VM으로 PC 호스트/가상 Android 호스트에서 같은 캐릭터 scripts를 실행한다. 모델 로드, 표정·립싱크·제스처·reset, DOM에 채팅 패널이 없는 경우, dispose 후 timer/ticker/리스너 0개를 먼저 실패 테스트로 만든다.
- [ ] `python -m pytest tests/test_companion_character_runtime.py tests/test_companion_character_export.py -q`로 실패를 확인한다.
- [ ] 캐릭터 전용 진입점은 `createCharacter(host, canvas)`가 `applySnapshot`, `applyAction`, `applyPlayback`, `dispose`를 반환하도록 한다. 호스트는 `emitInput`과 안전한 모델 asset URL 생성만 제공한다. 대화/개인 설정 조회·임의 runJavaScript RPC를 노출하지 않는다.
- [ ] 기존 runtime 함수 본문을 재작성하지 않고 PC DOM/Qt 의존만 어댑터로 이동한다. PC 기본 모델 경로는 PC 호스트로 옮기며 Android entry에는 기본 개인 모델 경로가 없다. 전체 PC script 복사로 숨은 전역 의존을 해결하지 않는다.
- [ ] `contracts/companion/character-runtime.json`에 schema=1, runtime_version=1, 명시적 파일 목록·SHA-256·라이브러리 버전/출처/고지 파일을 기록한다. SDK 고지가 불충분하면 배포 파일 추가를 보류한다. `tools/export_companion_character.py --check`는 목록 누락·비허용 파일·hash 차이를 실패 처리한다.
- [ ] 위 명령과 `python -m pytest tests/test_chat_ui_assets.py tests/test_model_emotions.py -q`를 통과시킨다. `refactor: 캐릭터 실행부와 PC 호스트 분리`로 커밋한다.

### C2. PC 안전한 모델 목록과 공개 상태

**파일:** PC `src/core/companion/character_assets.py`, `character_state.py`, `tests/test_companion_character_assets.py`, `test_companion_character_state.py`; 기존 `media_http.py`, `overlay_window.py`, `bridge.py`, `bridge_mixins/companion.py` 수정.

- [ ] 임시 디렉터리에 직접 만든 model3 참조 JSON으로 경로 이탈, percent/이중 인코딩, 정션/링크, 외부 URL, Sound 제거, 변경 중 읽기, 해시·개수·크기·이미지 크기 제한을 시험한다. 바이너리 moc3 파싱을 가짜 JSON으로 성공 처리하지 않는다.
- [ ] `python -m pytest tests/test_companion_character_assets.py tests/test_companion_character_state.py -q`로 실패를 확인한다.
- [ ] 모델 루트는 PC 로컬 설정에서 선택된 것만 받는다. 참조 목록을 따라 허용 파일을 열고 §3.2로 변환한다. HTTP 핸들러에 임의 로컬 path 인자를 받는 API를 추가하지 않는다. hash/크기 제한은 읽는 동안에도 확인한다.
- [ ] Qt 캐릭터 렌더러가 현재 모델의 parameter min/max와 실제 사용 가능한 표정/제스처 ID를 준비 완료 시 보고하게 한다. 모델 버전과 로컬 실행 세대를 대조한다. 이 카탈로그를 앱이 제출한 데이터로 대체하지 않는다.
- [ ] PC expression/gesture 신호에서 공개 의미만 추출하고 순서 번호를 붙인다. 재연결 snapshot은 현재 기본 상태만 주고 지난 action을 재생하지 않는다. 모델 미지원은 캐릭터만 해제한다.
- [ ] 같은 집중 시험과 `tests/test_companion_media_http.py`, `test_bridge_live2d_parameters.py`를 통과시키고 `feat: 인증된 모델 자산과 캐릭터 상태 제공`으로 커밋한다.

### C3. Android 모델 캐시와 WebView 보안

**파일:** APP `K/character/CharacterRepository.kt`, `CharacterCache.kt`, `CharacterBridge.kt`, `CharacterWebView.kt`, `T/CharacterCacheTest.kt`, `CharacterBridgeTest.kt`, `I/CharacterWebViewTest.kt`; §2의 APP 의존성·asset 파일 수정/생성.

- [ ] 캐시 한도/임시 파일 합산/해시 mismatch/등록 교체/다운로드 중 모델 변경 테스트와 JS origin·iframe·초과 메시지·외부 경로 거절 테스트를 작성한다.
- [ ] `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.CharacterCacheTest" --tests "dev.ene.companion.CharacterBridgeTest" --offline --dependency-verification strict --console=plain`로 실패를 확인한다.
- [ ] WebKit 1.15.0을 Google Maven에서 고정 추가한다. minSdk 23 이상인 이 버전은 현재 앱 minSdk 26 안에 들며 필요한 API만 사용한다. 최신 버전이라는 주장은 하지 않는다. 기존 lock/hash를 보존하고 신규 항목의 출처와 SHA를 확인한다. [공식 WebKit 변경 이력](https://developer.android.com/jetpack/androidx/releases/webkit#1.15.0)
- [ ] noBackupFilesDir 아래 서버 신원별 cache에 `.part`를 만들고 모든 자산 검증 뒤 manifest를 원자적으로 활성화한다. 취소 시 part만 정리한다. 부족 공간이면 미사용 버전을 먼저 제거하고 불가능하면 실패한다. 등록 삭제/교체 후 남은 캐시를 다음 시작에서 표시하지 않는다.
- [ ] C1의 명시 목록을 검증한 다음 `tools/export_companion_character.py --android-root <APP의 검증된 절대 경로>`로 복사한다. APP에 import manifest를 함께 커밋하여 단독 checkout에서도 빌드되게 한다. 라이브러리 고지 원문은 번역으로 대체하지 않는다.
- [ ] 내부 출처는 `https://appassets.androidplatform.net` 하나, 문서는 `/character/index.html`, 자산은 `/models/{model_version}/assets/{asset_id}`로 고정한다. 허용 목록 밖 요청은 403으로 반환하고 네트워크로 통과시키지 않는다. file/content 접근·mixed content·외부 navigation·window open·다운로드·웹 저장소·서비스 worker를 금지한다.
- [ ] WebMessageListener의 지원 여부와 sourceOrigin/isMainFrame을 확인한다. 지원하지 않으면 캐릭터를 비활성화하며 안전하지 않은 addJavascriptInterface로 대체하지 않는다. 입력은 유형/세대/크기를 검사한 JSON만 허용한다. onRenderProcessGone는 정리 후 상태 복구 버튼을 보이며 무한 자동 재시작하지 않는다. [공식 WebView 메시지 API](https://developer.android.com/reference/androidx/webkit/WebViewCompat#addWebMessageListener(android.webkit.WebView,java.lang.String,java.util.Set,androidx.webkit.WebViewCompat.WebMessageListener))
- [ ] 같은 JVM 시험과 offline strict lint/debug/instrumentation 빌드를 실행한다. 계측은 미실시로 남기고 `feat: 검증된 캐릭터 캐시와 제한된 WebView 추가`로 커밋한다.

### C4. 캐릭터 화면과 기기별 립싱크

**파일:** APP `T/CharacterRepositoryTest.kt`, `CharacterPlaybackTest.kt`, `I/CharacterScreenTest.kt`; 기존 `K/ui/ConnectionScreen.kt`, `K/character/CharacterRepository.kt`, `CharacterWebView.kt`, `K/connection/ExtensionSession.kt`, `K/MainActivity.kt` 수정. PC `tests/test_companion_character_playback.py`, 기존 `audio_coordinator.py`, `character_state.py` 수정.

- [ ] snapshot/action 순서 공백, 같은 이벤트 중복, manifest 다운로드 도중 action, 새 모델 전 옛 action, 폰/PC 출력별 입 벌림, 750ms 무갱신, 화면 회전 후 state 재주입을 테스트한다.
- [ ] APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.CharacterRepositoryTest" --tests "dev.ene.companion.CharacterPlaybackTest" --offline --dependency-verification strict --console=plain`, PC `python -m pytest tests/test_companion_character_playback.py -q`로 실패를 확인한다.
- [ ] 기존 Compose 채팅 상단에 AndroidView 캐릭터 영역을 추가하고 목록/입력 상태를 유지한다. 작은 화면/가로 화면에서는 캐릭터 높이를 제한하고 입력창을 가리지 않는다. 모델 받기/미지원/재시도 상태를 텍스트로 표시한다.
- [ ] 음성 출력 기기의 실제 위치를 기준으로 입을 움직인다. 폰 로컬 PCM RMS와 반대편 `character_playback` 중 현재 출력 소유자 하나만 적용한다. 회전은 새 WebView에 현재 상태/위치를 주입하고 TTS 시작 메시지를 재전송하지 않는다.
- [ ] manifest/모델을 받거나 화면을 재생성하는 동안의 일회성 action은 재생 대기열에 쌓지 않고 번호만 관찰한다. snapshot 적용 시 마지막 관찰 번호와 snapshot.action_seq 중 큰 값을 기준으로 삼고 이전 action을 모두 폐기한다. 기본 표정·설정은 최신 snapshot으로 복원하며 다운로드 때문에 지나간 제스처를 나중에 몰아서 재생하지 않는다.
- [ ] 위 집중 시험, PC 캐릭터 Node VM 회귀, APP lint/build를 통과시킨다. `feat: 채팅 화면에 동기화된 캐릭터와 립싱크 연결`로 각각 커밋한다.

## 8. D — 공통 설정과 쓰다듬기

### D1. 검증·충돌·저장 원자성

**파일:** PC `src/core/companion/character_controls.py`, `tests/test_companion_character_controls.py`, `test_companion_character_settings_storage.py`; 기존 `src/core/settings.py`, `character_state.py` 수정. APP `K/character/CharacterControls.kt`, `T/CharacterControlsTest.kt` 생성.

허용 저장 키는 아래 값으로 고정한다. 전송 키도 동일 이름이며 `parameters`만 별도 객체다.

| 키 | 타입/허용 범위 |
| --- | --- |
| `enable_builtin_idle_motion`, `enable_auto_eye_blink`, `enable_idle_motion`, `enable_expressive_motion`, `enable_expressive_pose_transitions`, `enable_idle_synthetic_gestures`, `enable_head_pat` | bool |
| `idle_motion_strength`, `idle_motion_speed` | 각각 0.2~2.0, 0.5~2.0 |
| `expressive_motion_strength`, `expressive_motion_speed`, `expressive_motion_speech_boost` | 각각 0.2~2.5, 0.4~2.0, 0.0~2.5 |
| `synthetic_gesture_scale`, `idle_synthetic_gesture_frequency` | 0.5~3.0, `low/normal/high` |
| `head_pat_strength`, `head_pat_fade_in_ms`, `head_pat_fade_out_ms` | 0.5~2.5, 정수 50~1000, 정수 50~1200 |
| `head_pat_active_emotion_custom`, `head_pat_end_emotion_custom` | 현재 카탈로그 표정 ID 또는 빈 문자열(PC 기본값 사용) |
| `head_pat_end_emotion_duration_sec` | 정수 1~30 |
| `parameters` | 현재 카탈로그 ID→해당 min/max 내 유한 수치 또는 null; 최대 256개 |

- [ ] 경계값/알 수 없는 키/NaN/없는 param/구모델/구 revision/중복 command/저장 실패 테스트를 먼저 만든다. 저장 실패 시 메모리·파일·revision이 바뀌지 않음을 검사한다.
- [ ] PC `python -m pytest tests/test_companion_character_controls.py tests/test_companion_character_settings_storage.py -q`, APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.CharacterControlsTest" --offline --dependency-verification strict --console=plain`로 실패를 확인한다.
- [ ] 기존 Settings.save()는 실패를 출력하고 삼키므로 원격 성공 판단에 사용하지 않는다. `commit_character_settings(candidate)`는 현재 config 사본에 검증된 변경을 병합하고 config 파일만 atomic replace한 뒤 메모리에 반영한다. 예외를 호출자에게 전달하며 secret 파일은 읽거나 쓰지 않는다. 기존 다른 설정 save 의미는 바꾸지 않는다.
- [ ] command_id 처리 결과를 연결별 최대 256개 보관한다. revision 확인 전에 같은 명령/같은 본문은 결과만 반환하고 다른 본문은 conflict다. 응답 유실 후 자동 재전송은 하지 않는다. 캐시에서 사라진 구명령도 이전 expected_revision 때문에 재적용되지 않아야 한다.
- [ ] APP은 수정 중 모델/revision을 고정하고 성공/충돌 이후 manifest를 받아 확정한다. parameter favorites와 화면 확대는 변경에 넣지 않는다.
- [ ] 같은 명령 통과 후 `feat: 캐릭터 설정 검증과 원자적 저장 추가`로 각 저장소에 커밋한다.

### D2. PC 설정 창·매개변수 경계 통합

**파일:** PC `tests/test_companion_settings_conflict_ui.py`; 기존 `src/core/app.py`, `overlay_window.py`, `bridge_mixins/live2d_parameters.py`, `src/ui/settings_dialog.py`, `settings_dialog_values.py`, `live2d_parameter_window.py`, `assets/web/runtime_live2d_parameters.js`, `runtime_live2d_parameter_ui.js` 수정.

- [ ] PC 창을 연 뒤 폰이 같은/다른 키를 바꾼 사례, preview 뒤 외부 수정·취소, 저장 실패인데 성공 토스트가 뜨는 사례를 테스트한다.
- [ ] `python -m pytest tests/test_companion_settings_conflict_ui.py -q`로 실패를 확인한다.
- [ ] PC settings dialog의 baseline/dirty 공유 키와 settings_revision을 전달한다. `_saved=True`와 창 닫기는 커밋 성공 응답 이후로 이동한다. 겹친 키 충돌이면 창을 유지하고 최신 값을 알린다.
- [ ] `app._on_settings_changed`와 `overlay_window.apply_new_settings`의 전체 dict 저장 전에 공유 키를 분리한다. 공유 값은 D1 조정기에서 확정한 최신 값으로만 병합한다. preview는 PC 로컬 표시만 바꾸고 원격 상태/revision을 바꾸지 않는다. 취소 시 창을 열었던 옛 사본이 아니라 현재 확정값을 적용한다.
- [ ] 기존 parameter get/save 슬롯의 로컬 호출을 보존하되 결과를 돌려주는 검증 경계로 연결한다. 원격 parameter 변경은 현재 모델의 values만 병합하고 PC favorites/다른 모델 override를 지우지 않는다. 오래된 parameter 창도 같은 충돌 정책을 적용한다.
- [ ] 위 명령과 `tests/test_bridge_live2d_parameters.py`, `test_live2d_parameter_window.py`, `test_settings.py`, `test_fish_audio_settings_ui.py`를 통과시킨다. `fix: PC와 모바일 캐릭터 설정 충돌 차단`으로 커밋한다.

### D3. 권위 있는 쓰다듬기 세션

**파일:** PC `src/core/companion/head_pat.py`, `tests/test_companion_head_pat.py`; APP `T/HeadPatSessionTest.kt`; 기존 PC `bridge_mixins/mood.py`, `bridge_mixins/companion.py`, `character_state.py`, `runtime_head_pat.js`, `runtime_character_host.js`; APP `CharacterBridge.kt`, `CharacterControls.kt` 수정.

- [ ] 첫 세션 수락, PC/폰 동시 시작, end 중복/역전, 종료 유실, 번호 재사용, ID 캐시 축출 이후 재전송, 모델 교체, disabled를 테스트한다. 종료 계수는 수락된 세션당 최대 1이다.
- [ ] PC `python -m pytest tests/test_companion_head_pat.py -q`, APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.HeadPatSessionTest" --offline --dependency-verification strict --console=plain`로 실패를 확인한다.
- [ ] HeadPatCoordinator는 source별 현재 연결·최대 interaction_no와 활성 세션 1개를 관리한다. 새 start만 번호를 증가시키고 update/end는 같은 번호+증가 seq를 사용한다. 수락된 start 이후 정상 end에만 기존 계수 증가 함수를 호출한다.
- [ ] JS의 직접 `increment_head_pat_count_from_js()` 호출을 호스트 입력 경계로 바꾼다. PC와 폰 모두 예측 시각 효과와 확정 계수를 분리한다. 원격 echo는 입력 콜백을 발생시키지 않는다. busy/취소를 받으면 예측 효과만 정리한다.
- [ ] 움직임이 없는 활성 포인터도 최대 500ms마다 update를 보내 2초 lease가 끊기지 않게 한다. pointercancel/blur/modelchange/dispose를 cancel로 처리한다. 앱 Main에서 10Hz로 합치고 별도 무한 큐를 만들지 않는다.
- [ ] 위 집중 시험과 PC 캐릭터 Node VM 회귀, 기존 기분/생활 기록 회귀를 통과시킨다. `feat: PC 권위의 쓰다듬기 연동 추가`로 각각 커밋한다.

### D4. Android 공통 설정 화면과 통합 체크포인트

**파일:** APP `K/ui/CharacterSettingsSheet.kt`, `T/CharacterSettingsStateTest.kt`, `I/CharacterSettingsScreenTest.kt`; 기존 `K/ui/ConnectionScreen.kt`, `K/character/CharacterControls.kt` 수정. PC/APP 표시 문자열은 기존 언어 리소스 구조를 따른다.

- [ ] 허용 키만 노출, 값 범위·작업 중 버튼, slider release 시 한 번 전송, conflict 뒤 최신값, 키보드·접근성 라벨 테스트를 추가한다.
- [ ] `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.CharacterSettingsStateTest" --offline --dependency-verification strict --console=plain`로 실패를 확인한다.
- [ ] 캐릭터 영역의 설정 버튼으로 작은 bottom sheet를 연다. D1 키만 switch/slider/선택 목록으로 표시하고 parameter catalog의 유효 항목만 제공한다. 연결/모델 준비 전에는 비활성화하며 수동 음성 출력 항목은 만들지 않는다.
- [ ] 미리보기는 로컬 캐릭터에만 적용하고 확정/충돌/취소 시 현재 snapshot으로 복원한다. 48dp 터치 영역·설명 라벨·글자 확대를 적용하고 대화 초안/스크롤 상태를 보존한다.
- [ ] PC 전체 pytest+Ruff, APP 전체 unit/lint/debug/instrumentation 빌드를 실행한다. 공유 설정 저장·수명·상호작용 변경을 통합 리뷰하고 Important 이상을 수정한다.
- [ ] `feat: 모바일 캐릭터 공통 설정 화면 추가`로 커밋한다. 계측 실행/실제 손가락 입력/기기 음성은 미검증으로 남긴다.

## 9. E — 통합 검증과 인계

### E1. 기능 결합·보안 회귀

**파일:** PC `tests/test_companion_media_integration.py`, `test_companion_media_resources.py`; APP `T/MediaIntegrationTest.kt`, `MediaPrivacyPolicyTest.kt`; 양쪽 `media_cases.json` 보완.

- [ ] 실제 bridge 수락→가상 worker→공개 메시지→음성 offer→prepared/start→PCM→완료의 합성 흐름을 실행한다. 실제 gateway TLS는 사용하고 provider 호출은 fake로 고정한다.
- [ ] 20회 연결 교체/모델 변경/재생/취소에서 worker/socket/HTTP/body/WebView listener가 남지 않는지 확인한다. 포화·예외·반쪽 연결도 반복한다. PC-only/browser/disabled/구형 text client는 PC 기존 기능을 보존한다.
- [ ] PC `python -m pytest tests/test_companion_media_integration.py tests/test_companion_media_resources.py -q`, APP `./gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.MediaIntegrationTest" --tests "dev.ene.companion.MediaPrivacyPolicyTest" --offline --dependency-verification strict --console=plain`를 실행한다. 새 실패가 있으면 원인별 집중 테스트로 먼저 수정한다.
- [ ] 전체 체크포인트: PC `python -m pytest -q`와 `python -m ruff check . --select E9,F63,F7,F82`; APP `./gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest --offline --dependency-verification strict --console=plain`. 예상: 모든 신규/기존 자동 시험 통과 또는 기존 환경 실패를 분리한 명확한 미완료 기록.
- [ ] APK ZIP 항목을 검사해 private runtime 파일·인증 토큰·시험 CA/private key·개인 모델이 없는지 확인한다. 재배포 허용된 런타임 파일/고지와 대응 hash를 점검한다. instrumentation APK의 합성 시험 자산은 앱 APK와 구분한다.
- [ ] 결과를 남기고 `test: 캐릭터 음성 연동과 자원 정리 회귀 검증`으로 해당 파일만 커밋한다. 빌드 산출물은 커밋하지 않는다.

### E2. 문서·완료 표시

**파일:** PC `docs/companion-media-validation.md` 생성, `docs/companion-lan-v1-acceptance.md`·기존 텍스트 계획 진행 기록 수정. APP `docs/media-support.md` 생성, `docs/android-connection-validation.md`, `docs/build-and-install.md` 수정.

- [ ] 아래 인수표에 실제 수행 결과·명령·각 저장소 커밋·APK SHA-256을 적는다. 이전 성공 수를 복사하거나 실행하지 않은 테스트를 통과로 쓰지 않는다.
- [ ] 자동 전환 조건, 시작 후 대체 재생 금지, 브라우저/기타 형식의 PC 전용 예외, PCM/WAV와 모델 상한, 권리 제한, 재등록 캐시 삭제, 오류 복구를 사용자 관점에서 설명한다.
- [ ] 단말 미실시 항목을 유지한다. 서명·배포·설치 허가를 이 계획으로 추정하지 않는다. 기존 전체 V1 인수는 별도이며 이 계획의 자동 시험 완료로 대신 체크하지 않는다.
- [ ] 문서 링크·UTF-8 BOM·diff 검사·개인정보 후보 확인 후 양쪽 `docs: 캐릭터 음성 지원과 검증 경계 기록`으로 커밋한다.

| 승인 요구 | 자동 검증 | 나중의 단말 인수 |
| --- | --- | --- |
| 실제 현재 대화·중복 없는 접수 | A1~A4 실제 bridge 대역 시험 | PC↔APK 실제 LAN 왕복 |
| 자동 출력·같은 음성 재생 금지 | B2/B5/B7/E1 상태·횟수·단절 | 실제 PC/폰 소리, 홈/잠금/회전 |
| PCM·립싱크 | B3/B6/C4 위치/버퍼/EOF | Android별 AudioTrack·포커스·체감 지연 |
| Live2D·안전한 자산 | C1~C4 Node VM/hash/경로/계측 컴파일 | WebGL·메모리·발열·모델 외형 |
| 쓰다듬기·설정 일치 | D1~D4 순서/충돌/계수 | 터치 좌표·가로/글자 확대·실제 설정 왕복 |
| 개인정보/TLS·구버전 | B1/B4/E1 계약·APK 검사 | OS/카메라/Keystore·인증서 오류 화면 |

계획 작성 완료는 코드 구현 완료가 아니다. 실행을 시작하면 A0부터 순서대로 진행하고 A/B/D/E 체크포인트에서 결과를 공유한다. 실기기 인수 전 최종 표현은 “소스 구현 및 자동 검증 완료, 단말 인수 미실시”로 제한한다.
