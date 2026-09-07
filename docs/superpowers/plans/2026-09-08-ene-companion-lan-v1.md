# ENE 안드로이드 LAN 동반 앱 V1 구현 계획

> **실행 에이전트 지침:** `@superpowers:executing-plans`로 체크박스 순서대로 직접 구현한다. 독립 작업의 병렬화는 사용자 실행 규칙을 만족할 때만 `@superpowers:subagent-driven-development`로 전환한다. 기본값은 순차 직접 구현이며 작업마다 별도 리뷰 에이전트를 만들지 않는다.

**목표:** 실행 중인 PC ENE와 Android 한 대가 개인 LAN에서 안전한 수락·중복 방지 규칙으로 현재 대화 전체를 공유하는 텍스트 앱을 만든다.

**아키텍처:** PC Qt 메인 스레드가 표시용 대화 기록·요청 원장·AI 작업 상태를 소유한다. 별도 aiohttp 루프의 게이트웨이는 인증된 불변 요청을 Qt로 전달하며, Android Kotlin/Compose 앱은 전체 스냅샷과 순서 있는 변경을 메모리에서 적용한다. PC와 APK는 독립 저장소이며 기본 텍스트 계약을 고정하고 향후 표현 기능은 별도로 협상한다.

**기술 스택:** Python/PyQt6/aiohttp, Kotlin/Compose/Coroutines/Serialization/OkHttp, CameraX와 번들형 ML Kit QR 인식, Android Keystore, pytest·Node 기반 기존 UI 테스트·Android 단위/계측 테스트.

---

## 1. 기준과 실행 원칙

- 승인 명세: [2026-09-07 설계](../specs/2026-09-07-ene-companion-lan-v1-design.md). 과거 모바일 원격 APK 명세와 실패한 작업 브랜치는 구현 원본으로 사용하지 않는다.
- 코드 확인 기준: `b80cef1e` — Fish Audio TTS 추가를 포함한다. 계획 시작 시 작업 트리는 깨끗했다. 실제 구현 시작 때 이후 변경과 충돌 여부를 다시 확인한다.
- 이 파일은 계획이다. 체크박스의 테스트·빌드·실기기 시험은 아직 실행하지 않았다. 문서 검토 승인은 앱 동작 검증을 의미하지 않는다.
- 이 문서의 `ENE/`는 PC 저장소의 실행 작업 트리, `ENE_APP/`는 사용자가 지정한 독립 Android 저장소를 뜻한다. 실제 개인 경로·주소·단말 식별자를 문서에 기록하지 않는다.
- Android 폴더는 현재 비어 있고 Git 저장소가 아니다. 기존 쓰기 허용 범위 밖이므로 파일 생성 전에 도구의 권한 승인 절차를 사용한다. PC 폴더 안으로 옮겨 우회하지 않는다.
- PC 내부 기능 변경은 텍스트 계약을 유지하면 구버전 앱이 활용한다. 음성·Live2D·쓰다듬기·모바일 설정·외부 접속·Tailscale·알림·첨부 업로드는 이 계획에서 구현하지 않는다.
- 일반 작업은 집중 테스트만 한다. 핵심 대화 통합, 전체 연결 통합, 최종 인수에서 전체 테스트와 통합 리뷰를 한다. 단계별 새 테스트는 실패 확인 후 구현하고 같은 명령으로 통과를 확인한다. `@superpowers:test-driven-development`, 완료·커밋 전 `@superpowers:verification-before-completion`을 적용한다.
- 체크박스는 한 번에 하나씩 처리한다. 긴 구현 항목은 아래에 명시된 테스트 사례별로 나누어 실패→최소 구현→통과를 반복한다. 실패를 건너뛰거나 검증 없이 다음 체크포인트로 이동하지 않는다.
- 현재 작업에서는 계획 문서만 작성한다. 기능 구현용 작업 트리·Android 저장소 생성·설치·방화벽 변경·단말 설치는 후속 실행 단계다.

## 2. 빌드 기준과 의존성

최신 버전 자동 추종이 아닌 아래 재현 가능한 조합을 초기 기준으로 사용한다. 실제 의존성 해석·APK 빌드가 검증되기 전에는 호환 완료로 표시하지 않는다. 알려진 취약점이나 해석 충돌로 변경해야 한다면 원인과 새 고정값을 이 계획 및 버전 카탈로그에 함께 기록한다.

| 항목 | 초기 고정값·선택 |
| --- | --- |
| PC Python | 기존 CI의 3.11 유지, 현재 로컬 3.12도 검증 |
| PC aiohttp·Qt | 기존 요구조건 유지. 현재 확인값 aiohttp 3.14.1, PyQt6 6.11.0. 관련 없는 의존성 일괄 업그레이드 금지 |
| PC QR 생성 | `qrcode==8.2`, 이미지 파일 저장 없이 행렬을 QImage로 그림 |
| Android SDK | `minSdk=26`, `compileSdk=36`, `targetSdk=36`, Build Tools 35.0.0 |
| Gradle / AGP | Wrapper 8.13 / Android Gradle Plugin 8.13.2 |
| Kotlin 플러그인 | Android·Compose compiler·Serialization 모두 2.2.21 |
| JDK | 현재 설치된 JDK 21로 Gradle 실행, Java/Kotlin 바이트코드 대상 17 |
| Compose | BOM 2025.12.00, Material3·UI·UI tooling·UI test를 동일 BOM으로 관리 |
| AndroidX | Activity Compose 1.11.0, Lifecycle runtime-compose·viewmodel-compose·process 2.9.4 |
| 비동기·직렬화 | Coroutines Android·test 1.10.2, Serialization JSON 1.9.0 |
| HTTP/WS | OkHttp·MockWebServer3 5.3.2, HTTP 로깅 인터셉터 없음 |
| QR 카메라 | CameraX camera-camera2·camera-lifecycle·camera-view 1.5.3, ML Kit barcode-scanning 17.3.0 번들형 |
| 테스트 | JUnit 4.13.2, AndroidX test runner 1.6.2·ext junit 1.2.1·core 1.6.1, Compose ui-test-junit4 |

현재 Android SDK 36·Build Tools 35.0.0/36.0.0·cmdline-tools·JDK 21이 설치되어 있다. 전역 Gradle은 발견하지 못했으므로 검증한 공식 배포로 Wrapper를 생성한다. 기존 `JAVA_HOME`을 다른 용도로 덮어쓰지 않고, SDK 위치는 커밋하지 않는 `ENE_APP/local.properties`에서 설정한다. 실제 단말이 API 26 미만이면 설치 가능하다고 가정하지 않고 지원 하한 변경을 사용자와 결정한다.

target 36 기준으로 `INTERNET`, `ACCESS_NETWORK_STATE`, 요청 시 `CAMERA`를 사용한다. `ACCESS_LOCAL_NETWORK` 런타임 요청은 이 조합에 억지로 추가하지 않는다. target 37 이상으로 올릴 때 LAN 권한 처리를 별도 변경·검증한다. APK 배포는 개인 설치용이며 앱스토어 제출 요건을 충족한다고 주장하지 않는다.

버전·사용 방식의 확인 출처: [AGP 8.13](https://developer.android.com/build/releases/agp-8-13-0-release-notes), [Gradle JDK 호환성](https://docs.gradle.org/current/userguide/compatibility.html), [Compose 2025.12](https://developer.android.com/blog/posts/whats-new-in-the-jetpack-compose-december-release), [Activity](https://developer.android.com/jetpack/androidx/releases/activity), [Lifecycle](https://developer.android.com/jetpack/androidx/releases/lifecycle), [Coroutines](https://github.com/Kotlin/kotlinx.coroutines/releases), [Serialization](https://github.com/Kotlin/kotlinx.serialization/releases), [OkHttp 변경 이력](https://github.com/lysine-dev/okhttp/blob/main/CHANGELOG.md), [CameraX](https://developer.android.com/jetpack/androidx/releases/camera), [ML Kit](https://developers.google.com/ml-kit/vision/barcode-scanning/android), [LAN 권한](https://developer.android.com/privacy-and-security/local-network-permission), [qrcode 8.2](https://pypi.org/project/qrcode/8.2/).

## 3. 파일 배치와 책임

아래는 생성·수정할 정확한 저장소 상대 경로다. 디렉터리는 책임 묶음이며 추상 팩토리·범용 플러그인·별도 DI 프레임워크를 도입하지 않는다.

### PC 신규 파일

| 파일 | 책임 |
| --- | --- |
| `ENE/contracts/companion/v1/protocol.md` | 양쪽이 복사해 사용하는 통신 규격 원본 |
| `ENE/contracts/companion/v1/cases.json` | 정상·오류·경계·구버전 가상 계약 사례 |
| `ENE/src/core/companion/__init__.py` | 패키지, 시작 부수효과 없음 |
| `ENE/src/core/companion/protocol.py` | 메시지 파싱, 자료형·길이·범위 검증, 안전한 공개 직렬화 |
| `ENE/src/core/companion/transcript.py` | 불변 공개 메시지·현재 기록·개정·스냅샷 |
| `ENE/src/core/companion/requests.py` | Qt 소유 요청 원장·요청 참조·결과 모델 |
| `ENE/src/core/companion/pairing.py` | 단조 시계 기반 QR·승인·기기 등록 상태 기계 |
| `ENE/src/core/companion/storage.py` | PC 식별자·토큰 해시·등록 세대의 원자적 보관 |
| `ENE/src/core/companion/network.py` | 활성 IPv4 후보·바인딩 설정 정규화 |
| `ENE/src/core/companion/gateway.py` | aiohttp 경로, 인증, 메시지 수신·송신 및 제한 |
| `ENE/src/core/companion/session.py` | 연결별 heartbeat·스냅샷 송신·이벤트 큐 |
| `ENE/src/core/companion/adapter.py` | Qt queued signal과 서버 루프 간 불변 요청·응답 전달 |
| `ENE/src/core/companion/controller.py` | Qt 소유 활성화·등록 교체 장벽·서버 시작/종료 조정 |
| `ENE/src/core/bridge_mixins/companion.py` | 공통 수락과 공개 표시 기록의 기존 WebBridge 연결 |
| `ENE/src/ui/companion_dialog.py` | 로컬 전용 활성화·포트·QR·승인·등록 해제 대화상자 |
| `ENE/assets/web/runtime_companion_chat.js` | PC의 메시지 ID·개정·접수 결과 및 확정 표시 적용 |
| `ENE/tests/companion_helpers.py` | 가상 시계·가상 대화/AI·신호 및 계수기 대역 |
| `ENE/tools/companion_smoke.py` | 임시 저장소·가상 대화 전용 개발 실행 진입점 |
| `ENE/tools/companion_fault_proxy.py` | 가상 LAN 시험용 제한된 TCP 패킷 드롭 도구 |
| `ENE/docs/companion-lan-v1-acceptance.md` | 자동/실기기 시험 결과와 검증된 두 커밋·APK 해시 |
| `ENE/docs/companion-lan-v1-setup.md` | 설치·등록·방화벽 범위·복구·업데이트 안내 |

### PC 기존 수정 경계

| 기존 파일·지점 | 수정 내용 |
| --- | --- |
| `ENE/src/core/bridge.py`: `__init__`, `_append_conversation`, signal 선언 | 모바일 활성화 이전부터 공개 기록 생성. 내부 버퍼와 공개 표시를 분리 |
| `ENE/src/core/bridge_state.py`: `ChatBridgeState` | 현재 공개 세션·원장·활성 요청 참조를 Qt 소유로 연결 |
| `ENE/src/core/bridge_mixins/chat_flow.py`: `send_to_ai`, `_commit_prepared_chat_request`, `_on_response`, `_on_error`, 편집·리롤 | 공통 수락 결과, 실제 반영/공개 시점, 대상·작업 참조 검증 |
| `ENE/src/core/bridge_mixins/life_records.py`: `PreparedChatRequest`, `_dispatch_general_request`, 재개·실패 경로 | 불변 요청 참조 운반, 준비 예약과 실제 기록 반영 구분 |
| `ENE/src/core/bridge_mixins/attachments.py`: 첨부 준비·commit | PC 첨부 수락 결과와 공개 텍스트/미지원 표시, 파일은 모바일에 미전송 |
| `ENE/src/core/bridge_mixins/tts.py`: `_flush_pending_response_if_any`, 오류/중단 | 지연된 답변이 올바른 요청으로 한 번만 공개되도록 연결. 음성 전송 추가 없음 |
| `ENE/src/core/bridge_mixins/memory_summary.py`: 요약·`clear_conversation` | 요약은 공개 기록 보존, 명시적 reset만 새 대화·원장 생성 |
| `ENE/src/core/bridge_mixins/obsidian.py`, `away.py`, `proactive.py`, `promise.py` | 공개 답변·로컬 안내·내부 자동 프롬프트 구분, 생성 작업 참조 전달 |
| `ENE/assets/web/runtime_chat_flow.js`, `runtime_bridge.js`, `runtime_message_rendering.js`, `runtime_chat_panel_controls.js`, `index.html` | 낙관적 초안 삭제 제거, ID 기반 표시/편집/리롤, 새 모듈 로드 |
| `ENE/src/core/app.py`: 초기화·`_connect_signals`·설정 변경·종료 finalizer | controller 생성·시작, 트레이 대화상자, 기존 비차단 종료와 통합 |
| `ENE/src/core/tray_icon.py`, `settings.py`, `src/locales/ko.json`, `en.json`, `ja.json` | 모바일 연결 메뉴·기본 꺼짐/포트·언어별 표시 문구. 새 키를 세 언어에 함께 추가해 키 이름이 화면에 노출되지 않도록 유지 |
| `ENE/requirements.txt`, `.gitignore`, `.github/workflows/ci.yml` | QR 의존성, 등록 실행 파일 제외, 새 테스트 포함. 기존 provider 설정 보존 |

PC 테스트 신규 파일은 각 Task에 명시한다. 기존 테스트를 무조건 다시 작성하지 않고 해당 경계의 기대값만 변경한다.

### Android 신규 파일

패키지는 개인 도메인을 주장하지 않는 `dev.ene.companion`, 애플리케이션 ID도 동일하게 고정한다. 독립 `app` 모듈 하나로 시작한다.

- 빌드: `ENE_APP/settings.gradle.kts`, `build.gradle.kts`, `gradle.properties`, `gradle/libs.versions.toml`, `gradle/wrapper/gradle-wrapper.properties`, `gradle/wrapper/gradle-wrapper.jar`, `gradlew`, `gradlew.bat`, `app/build.gradle.kts`, `app/proguard-rules.pro`, `.gitignore`, `.gitattributes`, `.github/workflows/android.yml`.
- 계약: `ENE_APP/contracts/companion/v1/protocol.md`, `cases.json` — PC 원본의 바이트 동일 사본. 앱 단위 테스트 resources에 이 디렉터리를 연결한다.
- 앱 진입: `ENE_APP/app/src/main/AndroidManifest.xml`, `java/dev/ene/companion/MainActivity.kt`, `java/dev/ene/companion/EneApplication.kt`.
- 프로토콜: `ENE_APP/app/src/main/java/dev/ene/companion/protocol/WireMessage.kt`, `ProtocolCodec.kt`, `SnapshotAssembler.kt`.
- 연결: `ENE_APP/app/src/main/java/dev/ene/companion/connection/ConnectionState.kt`, `ConnectionRepository.kt`, `CompanionSocket.kt`, `EndpointResolver.kt`, `Heartbeat.kt`.
- 등록: `ENE_APP/app/src/main/java/dev/ene/companion/pairing/PairingQr.kt`, `QrScanner.kt`, `PairingScreen.kt`.
- 보관: `ENE_APP/app/src/main/java/dev/ene/companion/storage/TokenStore.kt`, `ConnectionSettingsStore.kt`.
- 대화: `ENE_APP/app/src/main/java/dev/ene/companion/chat/ChatViewModel.kt`, `ChatScreen.kt`.
- 공통 UI: `ENE_APP/app/src/main/java/dev/ene/companion/ui/EneApp.kt`, `ConnectionScreen.kt`, `Theme.kt`.
- 리소스: `ENE_APP/app/src/main/res/values/strings.xml`, `themes.xml`, `res/xml/network_security_config.xml`, `backup_rules.xml`, `data_extraction_rules.xml`.
- 단위 테스트 기본 디렉터리: `ENE_APP/app/src/test/java/dev/ene/companion/`. 계측 테스트 기본 디렉터리: `ENE_APP/app/src/androidTest/java/dev/ene/companion/`. 각 Task의 파일은 이 루트에 실제로 생성한다.
- 안내: `ENE_APP/docs/build-and-install.md`, `ENE_APP/docs/compatibility.md`. 새 README 작성은 별도 필요 시 해당 스킬을 사용한다.

## 4. 구현할 통신 계약

### 4.1 경로·구조·한도

모든 JSON은 UTF-8이며 숫자는 실제 정수만 허용한다. Python의 `bool`을 `int`로 허용하지 않는다. 버전·ID·길이·자료형 검사 전에 임의 객체를 WebBridge에 전달하지 않는다. 메시지별 필수 키를 명시하고 선택 키 추가만 허용한다. 파싱 오류 응답에는 원문·예외 문자열을 넣지 않는다.

| 항목 | 값 |
| --- | --- |
| PC 정보 | `GET /companion/v1/info`, 인증 없이 `server_id`, `protocol_versions:[1]`만 제공, cache 금지 |
| 페어링 | `GET /companion/v1/pair` WebSocket. 첫 `pair_request` 본문에 QR 암호. 일반 대화 접근 없음 |
| 일반 연결 | `GET /companion/v1/ws` WebSocket, `Authorization: Bearer` 헤더. 성공 후 hello 교환 전 채팅 금지 |
| 거절 | 등록·명령 HTTP 경로를 더 만들지 않음. Origin 헤더가 있는 브라우저 요청은 거절, CORS 미개방 |
| QR | `protocol_version`, `server_id`, `pairing_id`, `expires_at`(UTC RFC3339), `secret`(난수 32바이트 base64url), `addresses:[{host,port}]`. 최대 2 KiB, 주소 최대 8개 |
| 연결 제한 | 주소당 연결/정보 조회 3초, 최초 hello/페어링 메시지 5초, QR 120초, 정상 WS 종료 유예 2초 |
| 생존 확인 | 양쪽 앱 수준 `ping` 15초, 대응 `pong` 10초. nonce와 현재 연결 세대로 검증, 단조 시계 |
| 수신 크기 | 일반 JSON 최대 64 KiB, 인증 전 첫 본문 최대 8 KiB, 입력 텍스트 UTF-8 최대 16 KiB |
| 스냅샷 | 직렬화 데이터 최대 32 MiB·공개 메시지 최대 50,000개, 부분 raw 바이트 32 KiB를 base64로 전송, 전체 수신 120초·진행 무응답 10초 |
| 단일 PC 메시지 | 전송 가능한 텍스트 최대 1 MiB. 초과해도 PC 기록을 자르지 않고 모바일 동기화를 명시적으로 실패 처리 |
| 이벤트 대기열 | 연결당 256개 또는 4 MiB 중 먼저 초과하면 `slow_consumer` 후 종료·전체 재동기화 |
| 인증 전 자원 | 동시 연결 전체 8개/주소당 2개, 시도 분당 전체 60회/주소당 10회, 승인 대기 1개 |
| 인증 후 명령 | 초당 10개/버스트 20개. heartbeat 응답은 별도 제어 처리하되 비정상 폭주는 종료 |

스냅샷 자원은 이벤트 대기열과 별도로 제한한다. 활성 일반 연결마다 캡처 대기·직렬화·송신을 포함한 스냅샷 작업은 한 개만 유지한다. 같은 상태에 대한 중복 `sync_request`는 진행 중 작업으로 병합한다. 편집/reset으로 무효화되면 세대를 올리고 기존 작업을 취소·정리한 뒤 최신 상태의 재동기화 한 건만 시작한다. 이미 Qt 큐에 있는 캡처의 늦은 결과는 폐기하며, 결과가 돌아오기 전에 새 캡처를 계속 추가하지 않는다. Android 조립기도 하나만 유지한다. 32 MiB는 직렬화 데이터 한도이지 전체 프로세스 메모리 한도가 아니므로 파싱 객체·직렬화 복사본을 포함한 최대 메모리는 긴 대화 시험에서 별도로 측정한다.

64 KiB는 양쪽의 애플리케이션 메시지 한도다. PC는 aiohttp 수신 한도를 적용하고 송신 전에도 검사한다. Android는 callback에서 검사 후 한도가 있는 처리 대기열로 전달한다. 다만 OkHttp 5.3.2는 메시지 전체를 버퍼링한 뒤 callback하므로 이 검사만으로 악의적인 서버의 초대형 메시지에 대한 수신 전 메모리 상한을 보장하지 않는다([해당 버전 구현](https://raw.githubusercontent.com/square/okhttp/parent-5.3.2/okhttp/src/commonJvmAndroid/kotlin/okhttp3/internal/ws/WebSocketReader.kt)). V1의 신뢰하는 PC·개인 LAN 범위와 이 잔여 한계를 안내하며, 자체 WebSocket 구현을 추가하지 않는다.

주소 편집은 호스트와 1~65535 포트만 허용한다. scheme·userinfo·path·query 입력은 거절한다. IPv4 바인딩을 유지하고 IPv6 전용 대상은 미지원 안내를 낸다. 인증정보를 보낼 때 HTTP 리다이렉트·시스템 프록시·자동 자격증명 공급자를 사용하지 않는다. 후보마다 `/info`의 PC 식별자가 일치해야 토큰을 보내며, 불일치 대상에는 토큰을 보내지 않고 다음 후보 또는 재등록 안내로 진행한다. 이 절차는 평문 환경의 암호학적 서버 인증은 아니다.

### 4.2 메시지 표

모든 WS 메시지는 `type`, `protocol_version:1`을 가진다. UUID는 문자열, 시퀀스·개정은 0~2^53-1 범위의 정수다. 목록에 없는 명령은 `unsupported_command`다. 알려진 메시지의 미지 선택 키는 한도 내에서 무시한다.

| 메시지 | 추가 필드·의미 |
| --- | --- |
| `pair_request` | `pairing_id`, `secret`, `device_name`(최대 80자). 표시명은 신원 증명이 아님 |
| `pair_pending` / `pair_failed` | `pairing_id`, 후자는 `code`. 승인/거절은 PC 로컬에서만 |
| `pair_approved` | `pairing_id`, `server_id`, `device_id`, `registration_generation`, `token`. 내구 저장·교체 완료 후 해당 소켓에 단 한 번 |
| `hello` | 앱→PC, `capabilities:[]` 선택. 누락도 기본 텍스트만 지원 |
| `ready` | PC→앱, `server_id`, `server_epoch`, `conversation_id`, `registration_generation`, `capabilities:[]`. 아직 전송 활성화하지 않음 |
| `sync_request` | 앱→PC, 선택적 `pending_request_ids`(최대 1개). 서버가 현재 대화 스냅샷을 캡처 |
| `snapshot_begin` | `server_epoch`, `conversation_id`, `snapshot_id`, `event_seq`, `conversation_revision`, `part_count`, `byte_count`, `message_count`, `sha256` |
| `snapshot_part` | 동일 실행·대화·스냅샷 ID, `index`(0부터), `data_base64` |
| `snapshot_end` | 동일 ID, `part_count`, `byte_count`, `sha256`. 순번·총량·완료·해시를 검증한 뒤 원자 교체 |
| `event` | 실행·대화 ID, `event_seq`, `conversation_revision`, `op:append|processing`, `payload` |
| `resync_required` | 실행·대화 ID와 `reason:reset|replace|large_event|gap`. 현재 조립을 취소하고 새 sync를 요청, 자체는 시퀀스를 소비하지 않음 |
| `send_text` | `server_epoch`, `conversation_id`, `request_id`, `text` |
| `request_status` | 해당 실행·대화·`request_id`, `state:unknown|reserved|accepted|completed|failed|rejected`, 선택적 `message_id`, `code` |
| `ping` / `pong` | `nonce` UUID. pending ping과 일치하는 pong만 인정, 이벤트 순서/원장에 미반영 |
| `error` | 안정적인 `code`, 선택적 `request_id`. 본문·토큰·서버 예외 상세 없음 |

`snapshot` 원본 JSON은 `messages`, `processing`을 갖는다. 메시지는 `id`, `role:user|assistant`, `text`, `displayed_at`(UTC RFC3339), 선택적 `request_id`, `attachment_unsupported:true`만 포함한다. 처리 상태는 `phase:idle|preparing|responding`, 선택적 현재 요청 ID다. thought·감정 분석·모델 설정·메모리 원문·첨부 바이너리·생성된 로컬 경로 메타데이터는 허용 목록에 없다.

크기 때문에 단일 `append` 이벤트를 보낼 수 없으면 해당 변경의 시퀀스를 기록한 뒤 `large_event`로 전체 스냅샷을 요구한다. 대화 전체는 정상적으로 분할해 보낸다. 편집·리롤·reset도 무효화 알림 후 새 스냅샷으로 수렴한다. 미래 음성·캐릭터 이벤트는 이 텍스트 시퀀스를 소비하지 않는다. snapshot 해시는 조립 검증용이며 전송 보안 수단이 아니다.

### 4.3 수락과 공개 경계

Qt 수락 순서: 등록·게이트웨이 세대 → 실행·대화 ID → 입력 검증 → 동일 요청 ID 조회 → 기존 작업 상태 확인 → 원장 예약 → 기존 `_dispatch_general_request` 경로. 같은 ID/같은 본문은 busy 검사보다 먼저 기존 상태를 반환한다. 같은 ID/다른 본문은 `request_conflict`. `/note`, `/diary`, `/obs` 및 기존 명령 파서가 인식하는 파일 명령은 모바일에서 부수효과 전에 거절한다. PC의 기존 명령 동작은 유지한다.

`reserved`는 생활 기록 선행 준비를 포함한 수락 예약이다. 사용자 메시지가 공개 기록에 실제 반영된 뒤만 `accepted`를 발행한다. 준비 실패 시 명확한 `failed` 상태로 끝내고 자동 재실행하지 않는다. 재접속은 전체 동기화 후 원장 조회부터 하며 `unknown`일 때만 같은 실행·대화·등록의 같은 ID·본문으로 재시도한다. 초기화/실행/기기 변경은 자동 재전송을 차단한다.

`PreparedChatRequest`에 선택적인 불변 `RequestRef`를 추가한다. 신규 요청 참조에는 실행·대화·요청 ID·발신 출처를 넣고 실제 작업 ID와 묶는다. AI/TTS 완료 콜백이 전역의 최신 `_last_request_payload`를 보고 메시지 정체성을 추정하지 않는다. 게이트웨이 세대는 접수 차단용이지 원장 키가 아니다.

공개 처리 분류는 다음으로 고정한다.

| 원래 경로 | 공개 기록·PC UI 처리 |
| --- | --- |
| 일반 텍스트/PTT·모바일 텍스트 | 실제 사용자 commit 때 ID 있는 사용자 메시지를 한 번 게시 |
| PC 첨부 입력 | 사용자 텍스트와 첨부 미지원 표시만 모바일 공개. PC의 기존 첨부 UI는 보존 |
| 정상 AI 답변 | TTS 대기와 무관한 내부 buffer append에서는 미공개, 실제 PC 표시 경계에서 게시 |
| TTS 지연·실패·중단 | 같은 요청 참조로 공개 여부 확인, 늦은 callback 중복/구대화 반영 금지 |
| 리롤·편집 | 수락 시 대상 ID+expected revision 확인, 성공/실패의 최종 결과를 같은 ID에 반영 |
| 자동 선제 대화·약속·away | 표시한 ENE 답변만 게시, 내부 생성 프롬프트를 사용자 메시지로 공개하지 않음 |
| 로컬 파일 명령 | PC 명령 기능은 유지. 파일 원문 preview·경로 메타데이터는 모바일에 중립적인 미지원 표시, 일반적인 결과 안내만 공개 |
| 토스트·처리 단계·검증 거절 | 채팅 답변으로 오인하지 않도록 로컬 알림 또는 제어 결과로 처리 |

`message_received`를 서버에서 무조건 구독해 모든 문자열을 내보내지 않는다. 새 표시 helper에서 공개 DTO와 PC 전용 표시 정보(thought·emotion·첨부)를 분리한다. 일반 대화는 ID 기반 `chat_display_event`로 PC에 전달하고, 옛 signal은 분류된 로컬 안내에만 남긴다. PC가 두 signal을 통해 같은 답변을 두 번 그리지 않게 테스트한다.

## 5. Task 0 — 실행 환경·저장소 준비

**파일:** 이 단계는 PC 작업 트리와 `ENE_APP/` 준비, 후속 파일 목록은 Task 1. 기존 파일 임의 변경 없음.

- [ ] `git status --short --branch`, `git log -3 --oneline`, `git worktree list`로 변경·기준을 확인한다. `@superpowers:using-git-worktrees`에 따라 PC 기능 브랜치 `codex/companion-lan-v1`을 현재 승인된 코드에서 준비한다. 이전 실패 브랜치나 기존 작업 트리를 삭제·재사용하지 않는다. Android는 지정된 `ENE_APP/`에서 작업한다.
- [ ] Android 경로 쓰기 권한 확보 후 폴더가 여전히 비어 있는지 확인한다. 빈 경우에만 그 폴더를 cwd로 `git init -b main`을 실행한다. 이미 저장소나 파일이 생겼으면 보존하고 기존 상태에 맞춘다. 원격 저장소 생성·push는 하지 않는다.
- [ ] PC에서 `python --version`, `python -m pytest --version`, `node --version`; Android 빌드 환경에서 `java -version`, SDK platform/build-tools 존재를 확인한다. 필요한 다운로드·설치는 도구의 승인 범위 안에서 수행하며 실제 설정·키 파일을 읽지 않는다.
- [ ] PC 기준선으로 `python -m pytest -q`를 한 번 실행해 기존 실패를 기록한다. Linux/headless 환경은 `QT_QPA_PLATFORM=offscreen`을 사용한다. 기존 실패는 이번 기능의 성공/실패와 분리한다. 계획 작성만으로 이 명령의 통과를 기록하지 않는다.

## 6. Task 1 — Android 최소 빌드와 재현 가능한 도구

**생성:** §3 Android 빌드 파일, `MainActivity.kt`, `EneApplication.kt`, `AndroidManifest.xml`, `res/values/strings.xml`, `themes.xml`, `app/src/test/java/dev/ene/companion/SmokeTest.kt`.

- [ ] 공식 Gradle 8.13 배포의 SHA-256을 확인하고 임시 폴더에서 실행해 `gradle wrapper --gradle-version 8.13 --distribution-type bin`으로 Wrapper를 생성한다. Wrapper JAR·scripts·distributionSha256Sum은 확인된 생성물만 추적한다. 무관한 저장소의 wrapper를 복사하거나 JAR을 직접 작성하지 않는다.
- [ ] 아래 최소 설정으로 `app` 모듈과 §2의 버전 카탈로그를 만든다. 플랫폼/앱 플러그인과 Compose compiler 버전은 섞지 않는다. release는 우선 `isMinifyEnabled=false`, 디버그와 같은 계약으로 테스트한다. 서명 비밀은 Gradle 파일에 쓰지 않는다.

```kotlin
android {
    namespace = "dev.ene.companion"
    compileSdk = 36
    buildToolsVersion = "35.0.0"
    defaultConfig {
        applicationId = "dev.ene.companion"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
```

- [ ] `.gitignore`에 `local.properties`, `.gradle/`, `.kotlin/`, `**/build/`, `.idea/`, `*.apk`, `*.aab`, `*.jks`, `*.keystore`, `.env*`, `keystore.properties`를 넣는다. wrapper JAR만 의도적인 빌드 도구 예외다. `.gitattributes`로 `gradlew` LF를 유지한다.
- [ ] Android cwd에서 `.\gradlew.bat --version`, `.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`를 실행한다. 기대: 고정 Gradle/JDK 확인, 최소 테스트 통과, `app/build/outputs/apk/debug/app-debug.apk` 생성. 첫 단계는 구조 부트스트랩이므로 빈 모듈의 빌드 실패를 기능 TDD 성공으로 세지 않는다.
- [ ] Android에서 생성 파일만 검토·개인정보 검사 후 `chore: 안드로이드 동반 앱 빌드 기반 추가`로 커밋한다. Gradle 의존성 lock/verification metadata를 생성·검토하고 고정값을 추적한다.

## 7. Task 2 — 양쪽 텍스트 계약과 순수 상태 모델

**생성:** 두 저장소 `contracts/companion/v1/protocol.md`, `cases.json`; PC `protocol.py`, `transcript.py`, `requests.py`, `tests/companion_helpers.py`, `tests/test_companion_protocol.py`, `tests/test_companion_transcript.py`, `tests/test_companion_requests.py`; Android `protocol/WireMessage.kt`, `ProtocolCodec.kt`, `SnapshotAssembler.kt`, 단위 테스트 `ProtocolCodecTest.kt`, `SnapshotAssemblerTest.kt`.

- [ ] §4를 규격 원본으로 옮기고 가상 사례를 작성한다. valid/invalid 메시지마다 입력·기대 오류/정규화 결과를 넣는다. UUID·한글·이모지 UTF-8 경계, 잘못된 정수/역할/버전, 선택 키, capabilities 누락, 부분 순서·해시 오류를 포함한다. 자격증명 사례는 실행 중 생성하며 유효 키처럼 보이는 문자열을 문서에 넣지 않는다.
- [ ] 공개 기록 테스트를 먼저 작성한다. `append_user`, `publish_assistant`, `replace`, `reset`, `capture`는 불변 결과를 반환하고 원장은 재전송을 조회할 수 있어야 한다. helper의 시계·UUID·가상 worker는 주입하며 실제 기억/설정/네트워크를 읽지 않는다.

```python
def test_gateway_recreation_does_not_reexecute_reserved_request():
    from src.core.companion.requests import RequestLedger

    ledger = RequestLedger()
    key = (1, "epoch-a", "conversation-a", "request-a")
    first = ledger.reserve(key, "body-hash")
    second = ledger.reserve(key, "body-hash")
    assert first.is_new is True
    assert second.is_new is False
    assert second.state == "reserved"
```

- [ ] PC에서 `python -m pytest tests/test_companion_protocol.py tests/test_companion_transcript.py tests/test_companion_requests.py -q`, Android에서 `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.ProtocolCodecTest" --tests "dev.ene.companion.SnapshotAssemblerTest"`를 실행해 해당 모델/검증기가 없거나 요구 동작이 틀려 실패함을 확인한다. 문법/의존성 실패는 먼저 수정한다.
- [ ] dataclass·엄격 파서와 Kotlin 명시적 DTO를 구현한다. SnapshotAssembler는 빈 메모리의 임시 버퍼에 조립→검증→원자 교체하고 기존 화면 목록을 직접 수정하지 않는다. `WireMessage`의 `type` 분기로 허용한 subtype만 해석한다. 원장 body hash는 파서가 확정한 전송 text의 UTF-8 해시이며 양쪽 문자를 추가 변형하지 않는다.
- [ ] 같은 두 명령을 다시 실행해 통과를 확인하고 가상 메시지 5,000개·단일 1 MiB 경계·총량 초과 오류를 추가한다. PowerShell `Get-FileHash`로 두 계약 파일 사본이 각각 같은 SHA-256인지 확인한다. PC/Android 각각 `feat: 동반 앱 텍스트 계약과 상태 모델 추가`로 커밋한다.

## 8. Task 3 — PC 페어링·내구 보관·주소

**생성:** PC `pairing.py`, `storage.py`, `network.py`; `tests/test_companion_pairing.py`, `tests/test_companion_storage.py`, `tests/test_companion_network.py`.

**수정:** PC `requirements.txt`, `.gitignore`.

- [ ] 주입 가능한 단조 시계·난수 생성기·저장 대역으로 QR 120초/재발급/거절/소켓 종료/동시 두 요청/기기 교체/내구 저장 실패 테스트를 쓴다. Storage는 `tmp_path`만 사용하고 첫 승인 전 기존 등록이 바뀌지 않아야 한다.
- [ ] `python -m pytest tests/test_companion_pairing.py tests/test_companion_storage.py tests/test_companion_network.py -q`로 실패를 확인한다.
- [ ] `get_user_file("companion_registration.json")`와 기존 `save_json_data_atomic`을 사용한다. 파일에는 안정적 `server_id`, 등록 세대, 기기 ID, SHA-256 토큰 해시만 저장한다. 키가 없는 초기 상태와 토큰 폐기를 구분한다. 파일 쓰기는 서버 루프에서 직렬화해 수행하며 Qt 객체에 접근하지 않는다. 해시 검증은 `hmac.compare_digest`; 토큰 원문은 승인 전송을 위한 수명에만 보유한다.
- [ ] `QNetworkInterface`를 Qt 쪽에서 조회해 활성·실행 중·비루프백 IPv4를 불변 후보로 만든다. `0.0.0.0`, 루프백, 멀티캐스트·미지정·연결 끊긴 주소를 제외하고 성공 후보 우선·중복 제거·최대 8개를 유지한다. 특정 사설 대역이나 SSID를 강제하지 않는다. QR은 `qrcode==8.2` 행렬로 메모리에만 생성한다.
- [ ] 위 테스트를 다시 실행한다. 등록 파일과 임시 파일이 `.gitignore`로 제외되는지 `git check-ignore`로 확인한다. 변경 파일을 명시해 `feat: 모바일 페어링과 등록 보관 추가`로 커밋한다.

## 9. Task 4 — 가상 어댑터로 실제 게이트웨이 연결

**생성:** PC `gateway.py`, `session.py`, `adapter.py`, `controller.py`, `ui/companion_dialog.py`, `tools/companion_smoke.py`; `tests/test_companion_gateway.py`, `tests/test_companion_session.py`, `tests/test_companion_adapter.py`, `tests/test_companion_dialog.py`.

- [ ] 실제 loopback 포트 0을 사용하는 테스트를 작성한다. production 포트는 8765이며 테스트의 port 0을 사용자 설정으로 노출하지 않는다. `/info` 최소 정보, 무인증/Origin 거절, QR 승낙 전 데이터 차단, header 인증, hello timeout, heartbeat·rate/size 제한·느린 수신자를 검증한다. 테스트 coroutine은 `asyncio.run`으로 실행해 새 pytest 플러그인을 추가하지 않는다.
- [ ] `python -m pytest tests/test_companion_gateway.py tests/test_companion_session.py tests/test_companion_adapter.py tests/test_companion_dialog.py -q`를 실행해 실패를 확인한다.
- [ ] adapter의 Qt `queued` signal에 불변 요청과 서버가 만든 correlation ID를 전달하고, 결과는 `loop.call_soon_threadsafe`로 돌려준다. GUI 스레드에서 Future 결과를 기다리지 않는다. controller는 Qt에서 서버 세대의 유효성을 확정한다. 승인 교체는 Qt 구등록 신규 수락 일시 차단→서버 저장 성공→Qt 등록 세대 확정→구연결 폐기→새 토큰 전송의 순서다. 저장 실패는 이전 등록을 다시 활성화하고 신규 승인을 실패 처리한다.
- [ ] session은 수신 작업·한 개의 순서 있는 writer·heartbeat timer를 분리한다. snapshot을 부분 단위로 보내 제어 메시지를 처리할 기회를 보장하고, 수정 가능한 Qt 목록을 직접 순회하지 않는다. 종료는 Qt 차단 확인 후 서버 task cancel/await→소켓/runner 종료→스레드 정리다. 종료 중 controller를 먼저 파괴하지 않는다.
- [ ] §4.1의 스냅샷 한 개 제한을 구현한다. 중복 sync는 병합하고 무효화 요청은 최신 한 건만 보관한다. 취소된 Qt 캡처/직렬화 결과를 세대로 거르고 이전 버퍼·구독을 해제한 뒤 교체한다. 큰 스냅샷을 보내는 동안 반복 sync·편집·reset을 주입해 동시 캡처/직렬화/송신 작업이 각각 한 개를 넘지 않는지, 해제되지 않은 버퍼가 요청 수에 비례해 쌓이지 않는지, 변경이 멈춘 뒤 최종 대화로 수렴하는지 검증한다.
- [ ] 같은 등록의 새 일반 소켓은 토큰과 hello 검증을 모두 통과한 뒤 현재 소켓을 교체한다. 서버가 만든 연결 세대를 바꾸고 구소켓의 신규 명령·늦은 callback·heartbeat·writer·구독을 무효화한다. Qt에 아직 수락되지 않은 구연결 요청도 재검증해 거절하지만 이미 예약/수락한 작업과 원장은 유지하고 결과는 현재 연결에서 복구한다. 구소켓 정리를 완료하기 전 교체 요청은 제한하여 종료 대기 소켓이 누적되지 않게 한다. 두 연결 경합·잘못된 토큰·hello timeout·구소켓의 늦은 종료 이벤트로 정상 연결이 끊기지 않는 테스트를 추가한다.
- [ ] 개발 실행 `python -m tools.companion_smoke`를 만든다. `TemporaryDirectory`와 가상 어댑터만 생성하고 실제 Settings/기억/LLM을 초기화하지 않는다. QDialog에 활성화·주소·QR·승인·거절·등록 해제·합성 응답 계수기를 제공한다. 자동 승인은 만들지 않는다. 위 테스트와 포트 충돌/시작 실패를 통과시킨 후 `feat: 동반 앱 게이트웨이와 연결 검증 화면 추가`로 커밋한다.

## 10. Task 5 — Android QR·토큰 보관·재연결

**생성:** Android §3의 `connection/`, `pairing/`, `storage/`, `ui/ConnectionScreen.kt`, `ui/EneApp.kt`, `ui/Theme.kt`, 세 XML 정책 파일; 단위 테스트 `ConnectionRepositoryTest.kt`, `PairingQrTest.kt`, `HeartbeatTest.kt`; 계측 테스트 `TokenStoreTest.kt`, `PairingPermissionTest.kt`.

- [ ] 단위 테스트부터 작성한다. 가상 socket/clock으로 후보 1 실패→후보 2 성공, 다른 server_id에 토큰 미전달, 미지 401/명확한 인증 폐기 구분, QR 오류·만료, 연결 시도 하나, 세대가 지난 callback 무시, heartbeat 15/10초·backoff 1/2/4/8/16/30초+jitter를 검증한다.
- [ ] `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.ConnectionRepositoryTest" --tests "dev.ene.companion.PairingQrTest" --tests "dev.ene.companion.HeartbeatTest"`로 실패를 확인한다.
- [ ] `ConnectionRepository`를 application 수명 객체로 생성하고 전경 상태에 따라 연결을 유지한다. 화면 회전은 재접속하지 않고 실제 백그라운드→전경 복귀는 새 세대로 인증·전체 sync 한다. OkHttp callback은 단일 coroutine 처리 경로로 보내 상태를 변경한다. 실패 시 socket을 cancel하고 app 단위 재시도만 수행한다. 다음 설정을 적용한다.

```kotlin
val client = okhttp3.OkHttpClient.Builder()
    .followRedirects(false)
    .followSslRedirects(false)
    .retryOnConnectionFailure(false)
    .proxy(java.net.Proxy.NO_PROXY)
    .connectTimeout(3, java.util.concurrent.TimeUnit.SECONDS)
    .build()
```

- [ ] callback 메시지는 크기 검사 뒤 최대 256개/4 MiB의 대기열에 넣으며, 가득 차면 무제한 coroutine을 만들거나 내용을 조용히 버리지 않고 연결을 닫아 전체 재동기화한다. 스냅샷 조립은 하나만 유지하고 구연결·구스냅샷 부분은 폐기한다. 과속 서버·불완전 snapshot·교체 중 늦은 부분 도착 테스트에서 작업/버퍼 누적이 없음을 확인한다. callback 전 OkHttp 내부 버퍼까지 이 한도로 제한했다고 주장하지 않는다.
- [ ] Keystore AES/GCM/NoPadding 키로 토큰을 암호화해 앱 전용 `noBackupFilesDir`에 nonce와 암호문만 원자적으로 저장한다. `TokenStore`는 키 손실·복호화 실패 시 재등록 결과를 반환한다. 주소 목록·PC ID만 별도 보관한다. Manifest backup 비활성화와 두 OS 세대의 backup/data extraction 제외 규칙을 모두 설정한다. transcript/초안/QR/token을 Bundle·SavedStateHandle·로그로 보내지 않는다.
- [ ] CameraX Preview+ImageAnalysis와 번들형 ML Kit의 QR 형식만 사용한다. ImageProxy는 성공/실패 모두 닫고, 최초 유효 결과 후 analyzer를 멈춘다. 카메라 이미지를 파일로 저장하지 않는다. 권한 거절은 설명·재시도 버튼으로 처리한다. QR 결과는 ViewModel/Repository 메모리로 직접 전달한다. 임의 웹페이지를 열지 않는다.
- [ ] 조기 연결 시험을 위해 ConnectionScreen에 최소 텍스트 입력·전송·메시지 목록을 붙인다. Repository의 `send_text`와 SnapshotAssembler를 그대로 사용하고 UI만 Task 11에서 ChatScreen으로 옮긴다. 별도의 임시 통신 규격이나 자동 페어링 경로를 만들지 않는다.
- [ ] `network_security_config.xml`에서 V1 cleartext를 명시 허용하고 연결/등록 화면에 승인된 평문 전송 제한을 표시한다. 위 단위 테스트를 통과시킨 뒤 `.\gradlew.bat :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=dev.ene.companion.TokenStoreTest,dev.ene.companion.PairingPermissionTest`로 단말 보관·권한 시험을 수행한다. 단말이 없으면 미검증으로 기록한다. `feat: QR 등록과 전경 재연결 구현`으로 커밋한다.

## 11. Task 6 — 조기 실제 휴대폰 연결 체크포인트

**생성:** PC `docs/companion-lan-v1-acceptance.md` 초기 결과표; Android `docs/build-and-install.md` 초기 설치 안내.

- [ ] Android에서 `.\gradlew.bat :app:assembleDebug`를 실행한다. 개발 APK임을 표시하고 사용자 단말 선택·설치 동의를 확인한다. 단말 하나를 명확히 선택한 뒤 `adb devices -l`, `adb install -r app/build/outputs/apk/debug/app-debug.apk`로 설치한다. 실제 단말 serial은 문서/커밋에 넣지 않는다.
- [ ] PC에서 `python -m tools.companion_smoke`를 실행하고 사용자 Android가 PC와 같은 개인 LAN인지 확인한다. PC 유선도 허용한다. 방화벽이 막으면 사용자에게 개인 프로필·해당 실행 파일/포트·로컬 서브넷 범위의 설정만 안내한다. 여기서 전체 방화벽 해제나 Tailscale 설치를 하지 않는다.
- [ ] QR 스캔→PC 승인→가상 메시지 왕복→앱 전경 복귀→현재 전체 재동기화를 확인한다. 임시 채팅 입력/표시는 Task 5의 연결 화면에서 최소 TextField·목록으로 제공하며 실제 ENE·개인 데이터는 쓰지 않는다. 승인 거절·QR 만료·두 번째 주소 후보·카메라 거절 후 복구도 확인한다.
- [ ] 실제 결과를 기기 OS/API·앱 버전·두 저장소 커밋·성공/실패/미검증으로 기록한다. 조기 연결이 막혔으면 이 체크포인트를 성공 처리하지 않는다. 단말 접근이 없으면 진행 가능한 단위 작업과 실기기 검증 일정을 사용자와 정한 뒤 실제 ENE 통합을 확대한다.
- [ ] 가상 응답 계수와 화면 기록이 왕복당 한 번 증가함을 확인한다. 이 시험은 실제 AI/TTS/기억 통합의 증거가 아니다. 개인정보 없이 결과 문서만 `docs: 초기 LAN 실기기 연결 결과 기록`으로 해당 저장소에 커밋한다.

## 12. Task 7 — PC 현재 대화와 공개 표시 경계

**생성:** PC `src/core/bridge_mixins/companion.py`, `tests/test_companion_bridge_transcript.py`.

**수정:** PC `bridge.py`, `bridge_state.py`; `bridge_mixins/chat_flow.py`, `tts.py`, `memory_summary.py`, `attachments.py`, `obsidian.py`, `away.py`, `proactive.py`, `promise.py` — §3에 적은 경로만 사용한다.

- [ ] `WebBridge`를 모바일 비활성 상태로 생성하고 가상 현재 대화를 쌓는 테스트를 쓴다. 자동/수동 요약 후 앞부분 보존, 나중에 활성화한 snapshot의 전체 기록, 명시적 reset의 새 ID, 내부 프롬프트/생각/첨부/로컬 경로 메타데이터 미포함을 검증한다. 실제 사용자 문장을 fixture로 복사하지 않는다.
- [ ] `python -m pytest tests/test_companion_bridge_transcript.py -q`로 실패를 확인한다. signal을 호출했는지뿐 아니라 완성된 공개 snapshot의 역할·본문·메시지 수·ID를 비교한다.
- [ ] `WebBridge.__init__`에서 `ChatBridgeState`에 공개 transcript·ledger를 붙인다. `_append_conversation`은 기존 AI buffer 책임만 유지하고 사용자 commit 및 실제 답변 표시 helper가 별도로 공개 기록을 변경한다. 순수 데이터 모델을 WebBridge 내부로 다시 복제하지 않는다.
- [ ] §4.3의 각 경로를 한 사례씩 연결한다. 답변 helper는 `RequestRef`와 공개 텍스트를 받고 현재 실행/대화와 맞는지 검증한 다음 한 번만 게시한다. 기존 `_pending_response` tuple을 확장할 때 TTS helper/test에서 같은 참조를 운반한다. Fish Audio를 포함한 TTS 공급자 생성 로직은 건드리지 않는다.
- [ ] 편집·리롤·초기화 후 실제 PC와 일치하는 최종 기록을 유지할 수 있도록 메시지 ID와 원본 요청의 대응을 저장한다. source가 자동 생성인 경우 사용자 메시지를 만들지 않는다. PC 로컬 notice와 공개 대화 helper를 구분하되 기존 알림을 없애지 않는다. PC 첨부 표시 정보는 기존 attachment 경로에 유지하고 공개 DTO에 넣지 않는다.
- [ ] `python -m pytest tests/test_companion_bridge_transcript.py tests/test_bridge_reply_lifecycle.py tests/test_bridge_tts_streaming.py tests/test_app_tts_bootstrap.py tests/test_fish_audio_tts.py tests/test_bridge_proactive_conversation.py tests/test_bridge_promise_reminders.py tests/test_bridge_context_compaction.py -q`로 확인한다. 새 경계와 직접 연관된 기존 테스트만 보완하고 `feat: 현재 대화의 공개 기록 경계 추가`로 커밋한다.

## 13. Task 8 — 공통 수락·원장·지연 작업 연결

**생성:** PC `tests/test_companion_admission.py`, `tests/test_companion_request_lifecycle.py`.

**수정:** PC `src/core/bridge_mixins/companion.py`, `chat_flow.py`, `life_records.py`, `attachments.py`; `src/core/companion/requests.py`, `adapter.py`.

- [ ] 가상 worker 생성 횟수, 기억 처리 횟수, 기분 처리 횟수, 공개 사용자 메시지 수를 각각 세는 테스트 harness를 만든다. PC/모바일 동시 전송, 같은 ID의 pending/완료 재전송, 다른 본문 충돌, busy, stale session, 잘못된 등록·게이트웨이 세대, 모바일 파일 명령 차단을 테스트한다. 명확한 검증 거절은 카운터가 전부 0이어야 한다.
- [ ] `python -m pytest tests/test_companion_admission.py tests/test_companion_request_lifecycle.py -q`로 실패를 확인한다.
- [ ] 공통 `submit_chat_request`와 모바일 전용 `submit_mobile_text`를 구현한다. 모바일이 QWebChannel 슬롯을 직접 선택하게 하지 않는다. PC 기존 `send_to_ai` 및 첨부 진입점은 동일 내부 수락 결과를 사용하되 기존 파일 명령 분기는 PC에만 남긴다. 입력 정규화 후 동기적 `AdmissionResult`를 반환하고 준비 중 최종 accepted는 별도 signal로 전달한다.

```python
def classify_existing_request(ledger, key, body_hash):
    existing = ledger.lookup(key)
    if existing is None:
        return None
    if existing.body_hash != body_hash:
        return {"state": "rejected", "code": "request_conflict"}
    return existing.public_status()
```

- [ ] §4.3 수락 순서대로 검사한다. `LifeRecordBridgeState.try_begin_operation`을 유일한 작업 잠금으로 유지하고 별도 AI queue/lock를 도입하지 않는다. ledger의 새 예약과 기존 gate 진입은 같은 Qt event 처리에서 완료한다. gate 거절은 예약을 정리하고 확정 거절을 반환한다. `_commit_prepared_chat_request` 및 첨부 commit에서 사용자 기록 반영 직후 ledger를 accepted로 바꾼다.
- [ ] 생활 기록 준비 성공·실패·취소·일반 대화 재개의 모든 결과를 원장에 반영한다. AI/TTS 완료는 해당 operation/ref로 갱신한다. 접수 직후 응답 유실은 snapshot의 `request_id`와 `request_status`로 복구한다. 게이트웨이 교체는 원장과 진행 중 준비를 초기화하지 않으며 기존 gate가 idle이 될 때까지 새 요청을 거절한다.
- [ ] `python -m pytest tests/test_companion_admission.py tests/test_companion_request_lifecycle.py tests/test_life_record_request_gate.py tests/test_life_record_bridge_flow.py tests/test_life_record_end_to_end.py tests/test_chat_attachments.py tests/test_bridge_request_pending.py tests/test_bridge_mood_flow.py -q`로 통과를 확인한다. `feat: PC 모바일 공통 접수와 중복 방지 연결`로 커밋한다.

## 14. Task 9 — PC 입력 보존·ID 표시·편집과 리롤

**생성:** PC `assets/web/runtime_companion_chat.js`, `tests/test_companion_pc_ui.py`, `tests/test_companion_edit_reroll.py`.

**수정:** PC `assets/web/runtime_chat_flow.js`, `runtime_bridge.js`, `runtime_message_rendering.js`, `runtime_chat_panel_controls.js`, `index.html`; `src/core/bridge_mixins/chat_flow.py`, `companion.py`.

- [ ] 기존 Node VM/DOM 대역 방식으로 실행형 UI 테스트를 쓴다. 단순 소스 문자열 검사가 아니라 거절 후 입력/첨부 보존, 접수 뒤 한 번만 렌더링, 모바일 입력의 PC 표시, 수락 응답보다 먼저 도착한 표시 이벤트, PTT 거절 시 초안 보존을 검증한다. 접수 대기 동안 사용자가 입력을 바꿨으면 이전 요청의 ACK가 새 초안을 지우지 않아야 한다.
- [ ] `python -m pytest tests/test_companion_pc_ui.py tests/test_companion_edit_reroll.py -q`로 실패를 확인한다.
- [ ] PC 입력에서 요청 ID와 전송한 초안 버전을 캡처한다. `reserved`이면 준비 상태를 보이고 초안 사본을 보존한다. `accepted`에서 해당 버전만 지우고, ID로 중복 렌더링을 막는다. 첨부도 같은 수락 결과에 따라 정리한다. `chat_display_event`가 사용자/답변을 그리는 유일한 일반 대화 경로가 되도록 옛 `message_received`의 중복 렌더링을 제거한다. PC 전용 thought·emotion·첨부 UI는 기존 표현 함수에 전달한다.
- [ ] PC 편집 시작 시 아래 명령의 session/target/revision을 고정한다. 리롤은 클릭한 답변의 ID·개정을 사용한다. 최신 메시지가 바뀌었다는 이유로 target을 새 ID로 덮어쓰지 않는다.

```json
{
  "server_epoch": "00000000-0000-4000-8000-000000000001",
  "conversation_id": "00000000-0000-4000-8000-000000000002",
  "target_message_id": "00000000-0000-4000-8000-000000000003",
  "expected_revision": 4,
  "text": "가상 도형의 색상을 파란색으로 바꿉니다."
}
```

- [ ] Qt 수락에서 대상 ID·개정·대응 원본 요청·busy를 확인한 다음에만 기록/AI/기억을 변경한다. 거절 시 `stale_target`/`stale_session` 및 현재 상태를 돌려주며 원래 말풍선·편집 초안을 보존한다. 편집/리롤 실패의 복원·오류 표시를 ID로 적용하고 앱에는 resync 알림을 보낸다. PC 상태 재적용은 첨부·생각 UI를 불필요하게 제거하지 않도록 ID 기반 갱신한다.
- [ ] `python -m pytest tests/test_companion_pc_ui.py tests/test_companion_edit_reroll.py tests/test_chat_ui_assets.py tests/test_chat_attachment_assets.py tests/test_life_record_ui_states.py -q`를 통과시킨다. 이어서 핵심 대화 경계 체크포인트로 `python -m pytest -q` 및 `python -m ruff check . --select E9,F63,F7,F82`를 실행한다. 전체 결과와 남은 기존 실패를 분리 기록하고 `fix: 공유 대화의 입력 보존과 편집 대상 검증`으로 커밋한다.

## 15. Task 10 — 실제 ENE 서버 수명·등록 장벽·PC 조작 UI

**생성:** PC `tests/test_companion_app_lifecycle.py`, `tests/test_companion_revocation.py`.

**수정:** PC `src/core/app.py`, `tray_icon.py`, `settings.py`, `src/locales/ko.json`, `en.json`, `ja.json`, `src/ui/companion_dialog.py`, `src/core/companion/controller.py`, `adapter.py`, `gateway.py`, `storage.py`.

- [ ] 기본 꺼짐, 활성화 저장, 재실행 자동 시작, 실제 리슨 전 QR 금지, 포트 충돌, 등록 저장 실패, 등록/일반 소켓 교체 시 Qt 대기 요청, 종료 직전 완료, gateway만 재시작, 20회 시작/종료 테스트를 쓴다. 파일·포트는 임시 자원으로 격리하고 실제 ENE 설정 파일을 쓰지 않는다.
- [ ] `python -m pytest tests/test_companion_app_lifecycle.py tests/test_companion_revocation.py -q`로 실패를 확인한다.
- [ ] `Settings.DEFAULT_CONFIG`에 `companion_enabled=False`, `companion_port=8765` 두 설정만 추가한다. API 키/등록 토큰을 기존 설정 export에 섞지 않는다. 트레이에 `companion_requested`와 연결 메뉴를 추가하고 `_connect_signals`에서 전용 dialog를 연다. 새 표시 키는 ko/en/ja에 함께 추가한다. 기존 번역 조회는 선택 언어→영어→키 순서이며 한국어 자동 fallback이라고 가정하지 않는다. 기존 설정 dialog의 TTS 화면을 개편하지 않는다.
- [ ] ENEApplication이 기존 bridge의 대화/원장을 adapter에 연결한 controller를 소유한다. 가상 smoke 어댑터는 실제 앱에서 import/선택할 수 없게 한다. 최초 리슨 성공 뒤 실제 주소와 QR을 보이고, 연결 끄기/등록 해제/새 QR/기기 교체를 구분한다. 저장 오류는 기존 등록을 유지하고 UI에 실패를 명확히 표시한다.
- [ ] 종료 finalizer의 가장 앞에서 Qt의 새 모바일 수락을 차단한다. gateway 스레드를 기존 shutdown drain 대상에 포함하고 정리 신호를 받은 뒤 참조를 해제한다. 일반 종료에서 GUI 스레드의 무한 `join`/`wait`를 금지한다. `aboutToQuit` 비상 경로는 이미 Qt 안에서 권한을 무효화하고 새 queued ACK에 의존하지 않는 bounded cleanup을 사용한다. 정리 실패를 정상 종료 완료로 숨기지 않는다.
- [ ] 위 테스트와 `python -m pytest tests/test_app_quit_summary.py tests/test_life_record_app_lifecycle.py tests/test_settings.py tests/test_app_tts_bootstrap.py tests/test_fish_audio_settings_ui.py tests/test_i18n.py tests/test_ui_i18n_smoke.py -q`를 실행한다. 종료/교체 뒤 구토큰·구세대 queued 요청은 수락되지 않고, 이미 예약된 같은 요청은 gateway 재시작 후 재실행되지 않아야 한다. `feat: ENE 모바일 연결 설정과 서버 수명 통합`으로 커밋한다.

## 16. Task 11 — Android 전체 대화 화면과 전송 복구

**생성:** Android `chat/ChatViewModel.kt`, `ChatScreen.kt`; 단위 테스트 `ChatViewModelTest.kt`, `ReplayRecoveryTest.kt`; 계측 테스트 `ChatScreenTest.kt`, `AppLifecycleTest.kt`.

**수정:** Android `ConnectionRepository.kt`, `SnapshotAssembler.kt`, `ConnectionScreen.kt`, `EneApp.kt`, `MainActivity.kt`, `strings.xml`.

- [ ] 순수 ViewModel 테스트로 전송 전/후 끊김, reserved/accepted 구분, ACK 유실 후 snapshot에서 같은 request ID 발견, unknown 재시도, 다른 실행/대화/등록의 자동 재시도 차단, 초안 보존을 검증한다. lifecycle 테스트는 회전 시 socket 1개·요청 1개, 프로세스 종료 후 텍스트 복원 없음, 전경 복귀의 새 sync를 검증한다.
- [ ] `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.ChatViewModelTest" --tests "dev.ene.companion.ReplayRecoveryTest"`로 실패를 확인한다.
- [ ] `ChatViewModel`에 transcript·초안·미확정 전송 1개를 일반 메모리 상태로 둔다. SavedStateHandle/rememberSaveable/텍스트 파일을 사용하지 않는다. 텍스트 전송 버튼은 동기화 완료+idle에서만 켜되 서버 판단이 최종이다. 확정 거절 뒤 사용자 재전송은 새 ID, 불확실한 재전송은 같은 ID를 사용한다. 프로세스 종료는 미확정 자동 재전송을 복원하지 않는다.
- [ ] Compose `LazyColumn`의 key를 메시지 ID로 하고 긴 현재 대화를 지연 렌더링한다. 일부 snapshot을 완성 기록처럼 표시하지 않는다. 오류 시 기존 목록은 오래된 기록임을 표시하며 빈 대화로 덮어쓰지 않는다. 읽던 위치는 가능한 메시지 ID 기준으로 유지하고 이미 아래에 있을 때만 새 답변으로 이동한다. 텍스트 선택·줄바꿈·키보드/화면 inset·48dp 터치 영역·접근성 라벨을 확인한다. 음성/캐릭터/파일 버튼은 넣지 않는다.
- [ ] 등록 실패·인증 폐기·버전 불일치·주소 변경·재연결·서버 busy 문구는 한국어 코드 매핑으로 표시한다. `/info`의 일시적 실패나 일반 네트워크 timeout은 토큰을 지우지 않는다. 사용자가 로컬 등록 해제 시 해당 서버 토큰·대화·대기 요청을 지우며 PC 등록 폐기는 PC에서 한다는 안내를 구분한다.
- [ ] 위 단위 테스트 후 `.\gradlew.bat :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=dev.ene.companion.ChatScreenTest,dev.ene.companion.AppLifecycleTest`를 실행한다. 5,000개와 이모지/긴 단일 메시지에서 전체 내용·스크롤을 확인한다. `feat: 전체 대화 표시와 전송 복구 UI 구현`으로 커밋한다.

## 17. Task 12 — 양쪽 통합·무응답 단절·호환 계약

**생성:** PC `tools/companion_fault_proxy.py`, `tests/test_companion_end_to_end.py`, `tests/test_companion_compatibility.py`; Android 단위 테스트 `CompanionInteropTest.kt`.

**수정:** 두 계약 사본, 각 구현 파일 중 실패를 재현한 경계만; PC `docs/companion-lan-v1-acceptance.md`.

- [ ] 실제 socket/Qt adapter와 가상 worker로 통합 실패 테스트를 만든다. 수락 직후 ACK 유실, 생활 기록 준비 중 끊김, gateway 재생성, snapshot 중 reset/편집, 초기화 직전 Qt 큐에 있던 send, 등록 교체 장벽, 길이·속도 제한을 자동 검증한다. 테스트 제어점은 테스트 adapter/주입 clock에 두고 production 원격 명령으로 노출하지 않는다.
- [ ] PC `python -m pytest tests/test_companion_end_to_end.py tests/test_companion_compatibility.py -q`, Android `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.CompanionInteropTest"`로 실패를 확인한다. Android 단위 시험은 MockWebServer3와 동일 계약 사례로 실제 HTTP/WS 클라이언트를 구동하고 인증 헤더·호환 이벤트·재시도를 검증한다. 이는 실제 PC와의 통합 성공을 대신하지 않는다. PC↔APK 실제 왕복은 Task 6과 최종 실기기 인수에서 별도로 확인한다. 테스트 서버는 fixture 종료 시 닫고 포트·종료 timeout을 둔다.
- [ ] `companion_fault_proxy.py`는 지정한 PC 로컬 gateway 한 곳에만 전달하는 테스트 TCP 프록시로 만든다. outbound/inbound/both 방향을 로컬 제어로 드롭하고 소켓은 열어 둔다. 원격 제어 API나 임의 목적지 open proxy 기능을 만들지 않는다. 인증정보·payload를 출력하거나 기록하지 않는다. 실기기에서는 QR 주소 후보를 테스트 adapter의 프록시 endpoint로 만드는 별도 개발 설정만 사용한다.
- [ ] 가상 시계에서 정확한 15/10초를, 실제 전경 단말에서 약 25초 내 재연결 표시를 확인한다. 큰 snapshot 수신 중 heartbeat가 굶지 않아야 한다. API36 기본 권한 조합과 실제 단말의 권한 거절/복구를 검증한다. 타깃을 시험 없이 37로 바꾸지 않는다.
- [ ] 기본 `capabilities` 누락/빈 목록을 보내는 고정 V1 client로 인증·전체 기록·전송을 확인한다. 선택 필드 추가는 수용하고 잘못된 필수 필드/미지원 버전은 거절한다. 확장 이벤트 미전송과 대화 event_seq 연속성을 확인한다. 양쪽 계약 파일 SHA-256을 비교하고 각각의 계약 테스트를 통과시킨다.
- [ ] 통합 체크포인트: PC `python -m pytest -q`, `python -m ruff check . --select E9,F63,F7,F82`; Android `.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug`, `.\gradlew.bat :app:connectedDebugAndroidTest`. `@superpowers:requesting-code-review`로 현재 통합 diff 중심의 리뷰를 한 번 수행한다. Critical/Important를 수정·재검증하고 `test: 모바일 동기화와 수명 통합 검증`으로 두 저장소를 각각 커밋한다.

## 18. Task 13 — CI·서명 APK·실기기 인수와 인계

**생성/수정:** Android `.github/workflows/android.yml`, `app/build.gradle.kts`, `docs/build-and-install.md`, `docs/compatibility.md`; PC `.github/workflows/ci.yml`, `docs/companion-lan-v1-setup.md`, `docs/companion-lan-v1-acceptance.md`.

- [ ] Android CI에 JDK 21·SDK 36·Wrapper 무결성 확인·`testDebugUnitTest lintDebug assembleDebug`를 넣는다. PC CI의 Windows/Linux 전체 테스트와 기존 coverage 기준은 낮추지 않는다. Python Node 실행형 UI 테스트에서 Node 유무를 확인한다. 비밀정보 없는 로컬 명령 재현을 먼저 하고 GitHub 게시/원격 CI 실행은 사용자가 저장소 업로드를 승인한 이후로 남긴다.
- [ ] 개인 설치용 release 서명키의 위치·비밀번호·백업 소유권을 사용자와 확정한다. 기존 키가 있으면 사용자 지정 키를 사용하고, 없으면 저장소 밖에서 안전하게 생성하는 절차를 안내한다. 서명키나 비밀번호를 문서/명령 기록에 넣지 않는다. Gradle은 로컬 비밀 파일 또는 사용자가 주입한 값만 참조하고, 키가 없으면 unsigned APK를 배포 완료로 표시하지 않는다.
- [ ] Android cwd에서 `.\gradlew.bat :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease`를 실행한다. `app/build/outputs/apk/release/app-release.apk`에 대해 SDK Build Tools의 `apksigner verify --verbose`와 `Get-FileHash -Algorithm SHA256`를 수행한다. `applicationId`·versionCode·debuggable=false·권한·네트워크/backup 설정을 APK Analyzer로 확인한다. 로컬 키 설정이 없어 다른 산출물 이름이 생기면 서명 완료 기준을 만족하도록 수정 후 다시 빌드한다.
- [ ] 실제 ENE 시험 전에 소스 작업 트리의 `main.py` 절대 경로를 확인하고, `New-Item -ItemType Directory`로 고유한 빈 임시 시험 폴더를 만든다. 자식 프로세스의 cwd와 `ENE_USER_DATA_DIR`를 모두 그 폴더로 설정한 다음 확인한 절대 경로의 `main.py`를 실행한다. 환경 변수는 Python import 전에 적용하고 부모 환경을 바꿨으면 종료 시 원래 값으로 복구한다. `Settings._migrate_legacy_embedding_key_file`이 cwd의 옛 키 파일을 읽고 삭제할 수 있으므로 데이터 환경 변수만 바꾸고 개인 작업 폴더에서 실행하지 않는다. 기존 config/키/기억/프로필/개인 프롬프트를 복사하지 않는다. 시험용 provider는 사용자 동의로 별도 설정하고 시험 폴더 정리는 정확한 경로·내용 확인 후 별도 처리한다.
- [ ] 최종 release APK를 실제 Android에 설치하여 승인 명세 §11의 모든 필수 시나리오를 수행한다. fake 기반 검증과 실제 ENE 통합 결과를 별도 열로 기록한다. 실제 AI가 필요한 시험은 사용자 승인한 가상 대화·격리된 실행 데이터만 사용하며 외부 API 사용 비용을 알린다. 기존 개인 기억·대화로 테스트하지 않는다. 실제 단말이 없거나 시나리오가 남으면 해당 항목은 미검증이며 전체 완료가 아니다.
- [ ] 동일 보관 정책의 debug 테스트 앱에서 가상 canary 문장·토큰을 사용한 뒤 process kill 후 `run-as`로 앱 전용 파일/캐시·로그를 검사한다. non-debuggable release에는 `run-as`를 요구하거나 debuggable을 켜지 않고 APK Analyzer와 패키징 검사를 별도로 적용한다. 실제 사용자 앱 데이터나 전체 logcat을 수집하지 않는다. APK에 제공자 키·설정·프롬프트·모델·개인 대화가 없는지 확인하고 decoder/QR 이미지가 남지 않는지도 검사한다.
- [ ] 최종 PC 전체 테스트·Android 단위/lint/build·실기기 결과와 두 저장소 커밋·지원 프로토콜·APK SHA-256을 인수 문서에 기록한다. 설치 안내에는 PC 켜짐 필요, 개인 LAN, 수동 주소 수정, 제한된 방화벽 안내, QR 재등록, 프로세스 종료 시 초안 소실, 평문 전송 한계, 구버전 호환을 포함한다. 성공한 테스트 수를 추측하지 않는다.
- [ ] 두 저장소에서 `git diff --check`, 변경 파일 목록·개인정보 후보·API 키 패턴 검사를 하고 해당 소스/문서만 커밋한다. 빌드/로그/스크린샷/키/실행 데이터는 stage하지 않는다. 최종 통합은 `@superpowers:finishing-a-development-branch`에 따라 사용자에게 인계한다. GitHub 저장소 생성·push·태그·Release asset 업로드는 별도 승인 대상이며, 태그/Release 전에는 전체 히스토리와 asset 개인정보 검사도 수행한다.

## 19. 공통 커밋·검증 명령 규칙

각 Task의 테스트 명령은 해당 저장소 cwd에서 실행한다. PowerShell에서는 새 변수명에 작업 전용 접두어를 쓰고 시스템 경로 변수를 다른 뜻으로 사용하지 않는다. 파일 편집은 `apply_patch`, UTF-8 BOM 없음으로 한다. 모든 새 주석·설명은 한국어다.

Task 마지막의 커밋은 다음 순서다. `<Task 파일>` 같은 placeholder 명령을 그대로 실행하지 않고 Task의 실제 변경 파일을 열거한다. 문서/계약 경로가 ignore될 때에는 그 문서만 정확히 지정하여 `git add -f` 하고 ignore 규칙 전체를 풀지 않는다.

1. `git status --short`, `git diff --check` 및 해당 집중 테스트의 실제 결과 확인.
2. 변경 파일에서 이름·생일·건강·일정·취업·프로필·실제 대화 후보와 API 키/이메일/개인 경로 패턴 검색. 일반 기술 설명과 민감 내용을 구분해 확인.
3. 실제 변경 파일만 `git add -- ...`로 준비하고 `git diff --cached --name-only`, `git diff --cached --check`로 범위 검증. 무관한 변경이 있으면 커밋하지 않는다.
4. Task에 적은 한국어 메시지로 저장소별 커밋. 원격 push는 하지 않는다.

Task 2 이후의 핵심 검증 추적표:

| 승인 명세의 위험 | 자동 검증 위치 | 실기기 확인 |
| --- | --- | --- |
| QR 수명·승인·교체 | Task 3/4/10 pairing·revocation | Task 6/13 |
| 요약 이후 전체 대화·늦은 최초 연결 | Task 7 transcript | Task 13 |
| 동시 입력·초안 손실·중복 AI/기억 | Task 8/9/12 admission·PC UI·E2E | Task 13 |
| 준비 중 끊김·gateway만 재시작 | Task 8/10/12 lifecycle | Task 13 |
| 오래된 편집·리롤·reset 경합 | Task 9/12 target·E2E | Task 13 |
| snapshot 부분/수명·5,000개·크기 초과 | Task 2/11/12 assembler·UI | Task 13 |
| 무응답 단절·회전·전경·프로세스 재생성 | Task 5/11/12 lifecycle·heartbeat | Task 6/12/13 |
| TTS 표시 타이밍·Fish Audio 보존 | Task 7/9 기존 회귀 | Task 13, 음성은 PC에서만 |
| 비밀 보관·backup·로그·APK | Task 5/13 storage·산출물 검사 | Task 13 |
| 구버전 텍스트 호환 | Task 2/12 고정 계약 | Task 13 |

## 20. 완료 조건과 후속 범위

완료는 두 저장소의 소스·테스트·설치 문서가 독립적으로 관리되고, 승인 명세의 필수 시험이 실제 단말에서 확인되며, 서명된 설치 APK와 검증 기록을 인계한 상태다. 단순 APK 빌드나 계획 리뷰 승인으로 완료를 선언하지 않는다.

V1 다음의 TTS·Live2D·쓰다듬기·기분 표시·공통 설정은 승인 설계 §12를 기준으로 별도 계획을 작성한다. 현재 계획에서는 capabilities 기본값과 텍스트 계약 보존만 준비한다. 모델 다운로드·WebView 렌더러·음성 재생·설정 원격 수정·화면 스트리밍·Tailscale 구현은 추가하지 않는다.
