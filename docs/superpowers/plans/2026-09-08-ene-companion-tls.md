# ENE LAN 동반 앱 HTTPS/WSS 구현 계획

> **실행 에이전트 지침:** `@superpowers:executing-plans`로 체크박스 순서대로 직접 구현한다. 사용자가 지정한 순차 실행을 유지하며 각 실패 테스트→최소 구현→동일 테스트 통과를 기록한다. 구현을 여러 에이전트로 나누지 않고 계획과 최종 보안 경계만 집중 검토한다.

**목표:** 기존 PC·Android 텍스트 기반의 모든 연결을 QR로 신원을 확인하는 HTTPS/WSS로 전환한다.

**아키텍처:** PC별 CA와 단기 서버 인증서를 보관하고, 앱은 QR의 CA와 고정 TLS 서버 이름만 신뢰한다. 실제 LAN 주소는 이름 검증과 분리한다. 기존 Qt 수락·원장·전체 동기화 규칙은 유지한다.

**기술 스택:** Python 3.11/3.12·stdlib ssl·cryptography 50.0.1·aiohttp, Windows 보안 API의 제한된 ctypes 래퍼, Kotlin·플랫폼 TrustManagerFactory·OkHttp 5.3.2·Keystore. TLS 시험 인증서는 실행 때 생성하며 개인키를 fixture로 커밋하지 않는다.

## 1. 실행 기준

- 승인 명세: [TLS 설계](../specs/2026-09-08-ene-companion-tls-design.md). 2026-09-08 사용자 진행 승인으로 세부 설계 검토를 종료했다.
- PC 기준 커밋 `2113c34e`, `codex/companion-lan-v1` 작업 트리를 계속 사용한다. 사용자 원본 작업 폴더는 변경하지 않는다.
- Android는 별도 `ENE_APP/`에서 기존 Task 5 미커밋 변경을 보존한다. 작업 시작 시 별도 `codex/companion-tls-v1` 브랜치로 이어가며 폴더를 이동하지 않는다.
- 기본 계획의 Task 0~4 통과는 평문 개발 기반 결과다. Task 5는 31개 선택 시험과 빌드만 통과했고 화면·Repository·카메라·실기기 검증은 미완료다. 기존 미충족 정책 테스트를 숨기지 않고 TLS 차단 정책으로 전환한다.
- `cryptography==50.0.1`을 명시 의존성으로 추가한다. 설치된 49.0.0은 PKCS7 복호화 보안 수정 이전이므로 새 기반으로 고정하지 않는다. 해당 기능을 이 앱에서 쓰지는 않지만 최신 수정 버전으로 검증한다. 전역 설치는 바꾸지 않고 작업 전용 가상환경에 설치한다. [변경 이력](https://cryptography.io/en/50.0.1/changelog/)
- Android 테스트에만 `com.squareup.okhttp3:okhttp-tls:5.3.2`를 추가하고 잠금·SHA-256 검증 메타데이터를 갱신한다. 실제 앱은 플랫폼 CA 검증을 사용한다.
- 이 작업은 방화벽 변경·실제 단말 설치·외부 API 사용·GitHub 게시를 승인하지 않는다. 사용자 대화·등록키·설정은 시험에 사용하지 않는다.

## 2. 파일 책임

| PC 파일 | 책임 |
| --- | --- |
| `src/core/companion/tls_identity.py` | TLS 프로필·인증서 생성/검증·갱신 판단의 순수 모델 |
| `src/core/companion/private_files.py` | 보호 디렉터리·파일 권한·원자 저장·제한된 임시 파일 |
| `src/core/companion/windows_private_files.py` | 현재 SID·DACL 생성/검증. Windows에서만 로드 |
| `src/core/companion/tls_storage.py` | 신원 묶음 보관·등록 지문 일치·SSLContext 생성 |
| `src/core/companion/tls_listener.py` | TLS 전용 asyncio 서버 시작·5초 협상 제한·종료 |
| `src/core/companion/storage.py`, `pairing.py` | 등록 CA 지문, TLS QR, 구형 개발 등록의 재등록 |
| `src/core/companion/gateway.py`, `controller.py` | 필수 SSLContext, 갱신·차단·로컬 초기화 수명 |
| `src/ui/companion_dialog.py`, `tools/companion_smoke.py` | TLS/복구 안내와 가상 연결 시험 |
| `contracts/companion/v1/protocol.md`, `tls_cases.json` | 전송 필수 규격·공통 QR 사례 |
| `tests/test_companion_tls_identity.py`, `test_companion_private_files.py`, `test_companion_tls_storage.py`, `test_companion_tls_gateway.py` | PC TLS 집중 테스트 |
| `tests/companion_helpers.py`, 기존 `test_companion_pairing.py`, `test_companion_storage.py`, `test_companion_gateway.py`, `test_companion_adapter.py`, `test_companion_dialog.py` | 실제 TLS를 사용하는 기존 회귀 시험으로 전환 |
| `requirements.txt`, `.gitignore` | 고정 crypto 의존성·키/가상환경 산출물 제외 |

| Android 파일 (`ENE_APP/app/src/` 기준) | 책임 |
| --- | --- |
| `main/java/dev/ene/companion/connection/TrustedServer.kt` | CA·고정 이름·유효기간 검증, 불변 등록 신뢰 정보 |
| `main/java/dev/ene/companion/connection/TlsClient.kt` | 전용 trust store·실제 주소 매핑·HTTPS 전용 클라이언트 |
| `main/java/dev/ene/companion/connection/CompanionSocket.kt`, `EndpointResolver.kt` | TLS 필수 전송·분류 가능한 오류·수명 취소 |
| `main/java/dev/ene/companion/pairing/PairingQr.kt` | 필수 TLS QR 검증 |
| `main/java/dev/ene/companion/storage/TokenStore.kt` | 토큰과 CA를 단일 암호화 레코드로 보관 |
| `main/AndroidManifest.xml`, `main/res/xml/network_security_config.xml` | 앱 전체 평문 차단, 기존 백업 제외 유지 |
| `test/java/dev/ene/companion/TlsClientTest.kt`, `TrustedServerTest.kt`, `TlsTestCertificates.kt` | 실행 시 인증 키 생성·실제 HTTPS/WSS 검증 |
| 기존 `CompanionSocketTest.kt`, `PairingQrTest.kt`, `StoragePolicyTest.kt`, `androidTest/.../TokenStoreTest.kt` | 기존 기능의 TLS·보관 형식 회귀 |

Android 계약 사본은 `ENE_APP/contracts/companion/v1/`에 동일 바이트로 유지한다. 실제 구현에서 더 적합한 작은 파일 분리가 필요하면 변경 이유와 실제 파일명을 이 계획에 기록하며 범용 프레임워크를 추가하지 않는다.

## 3. Task T1 — 인증서 순수 모델과 전송 계약

진행 기록: 계획 집중 리뷰에서 중대 차단 사유 없음. PC 기존 동반 앱 156개 기준 시험 통과. 격리된 `.venv/`에 cryptography 50.0.1을 설치했으며 이 계획의 PC `python`은 `.venv/Scripts/python.exe`를 뜻한다. T1은 20개 새 시험의 모듈 부재 실패→구현 후 20개 통과→공통 계약 사례 포함 21개 통과를 확인했다. 현재 TLS 모델·계약만 구현되었고 네트워크는 아직 전환하지 않았다.

- [x] `test_companion_tls_identity.py`에 PC별 CA 독립성, P-256/SHA-256/CA pathLen=0, 서버 SAN·EKU·기간 상한·인증서 크기·비밀 repr·원자 모델 복원 테스트를 작성한다. `TlsIdentity.create(server_id, now)`, `TrustAnchor.parse(ca_certificate, server_id, now)` API를 기준으로 한다.
- [x] `python -m pytest tests/test_companion_tls_identity.py -q`로 새 기능 부재의 실패를 확인한다.
- [x] `tls_identity.py`를 구현한다. DER 전체 소비와 canonical base64를 검사하고 CA는 DER 768바이트 이하, QR은 2 KiB 이하로 제한한다. CA 3,650일, 서버 90일 이하·CA 만료 이하, notBefore 5분 여유, CA 만료 30일 이내에는 자동 갱신 중단, 서버 만료 30일 이내에는 갱신한다. 시간은 주입 가능하며 wall clock을 QR 단조 수명에 혼용하지 않는다.
- [x] 정상·변조/과대/후행 바이트·잘못된 키·서명·서버 이름·만료/미래 날짜의 실패 테스트를 추가하고 동일 명령으로 통과시킨다. 키를 모델에 보관할 때 `repr=False` 또는 안전한 `__repr__`를 사용한다.
- [x] `protocol.md`에 `transport:"tls_v1"`와 `ca_certificate`, 주소/고정 이름 분리, 평문 미지원·구형 재등록을 추가한다. `tls_cases.json`은 키가 없는 합성 QR 필드·인증서 변형 지시만 저장한다. CA 자체는 양쪽 테스트가 생성하므로 고정 유효기간 fixture를 만들지 않는다.
- [x] 계약 사본 동일성, UTF-8/BOM·민감정보·diff 검사를 확인하고 T1 파일만 `feat: 동반 앱 TLS 인증서 모델과 계약 추가`로 커밋한다.

인증서 검증의 최소 기대 예:

```python
identity = TlsIdentity.create(sample_id(1), now)
anchor = TrustAnchor.parse(identity.ca_certificate, sample_id(1), now)
assert anchor.hostname == f"ene-{sample_id(1)}.invalid"
assert len(anchor.der) <= 768
assert identity.leaf_not_after <= identity.ca_not_after
```

## 4. Task T2 — OS 보호 보관·등록 신뢰 연결

진행 기록: 보호 파일의 첫 14개 시험 실패→14개 통과, 신원 보관·단독 소유 추가 후 11개 실패→구현 후 통과를 확인했다. 최종 T1/T2/기존 등록 집중 시험은 74개 통과·1개 건너뜀이다. Windows 실제 DACL 및 OS 파일 잠금을 검증했다. 심볼릭 링크 생성은 시험 계정 권한 부족으로 건너뛰었고 POSIX 분기는 이 Windows 호스트에서 실행하지 않았다. 동시 ENE 실행이 신원을 덮어쓰지 않도록 보관 소유 기간 내내 `identity.lock`을 OS 배타 잠금하며 잠금 파일은 교체·삭제하지 않는다. 초기화 중단 표식(증가한 세대·빈 지문)은 재시작에도 옛 CA를 채택하지 않는다. 네트워크 인증 경로 전환은 T3에서 진행한다.

- [x] `test_companion_private_files.py`에서 생성 시 제한된 권한, 기존 과도한 권한 거절, 링크/재분석 지점 거절, 원자 저장 실패 전후, 임시 키 파일 정리를 작성한다. Windows 실제 API·POSIX 실제 mode를 각 OS에서 시험하며 운영체제를 속이는 광범위 mock은 사용하지 않는다.
- [x] `python -m pytest tests/test_companion_private_files.py -q`의 실패를 확인한 뒤 보호 파일 래퍼를 구현한다. Windows는 보안 속성을 넣어 디렉터리를 생성하고 현재 SID/SYSTEM 두 ACE·보호 DACL·소유자를 확인한다. 디렉터리 안 파일도 쓰기 전 권한을 제한하며 다른 사용자의 기존 폴더를 수리한다며 접근권을 넓히지 않는다.
- [x] `test_companion_tls_storage.py`와 기존 storage 시험에 재시작 동일 CA, 손상·개인키 불일치·루트 누락·지문 불일치·구형 등록·저장 결과 불명확을 추가하고 실패를 확인한다.
- [x] 등록 레코드에 선택 `ca_sha256`을 추가한다. `TlsIdentityStore`는 등록 파일 옆의 `companion_tls/identity.json`에 버전·PC ID·CA/서버 인증서·키를 하나의 제한된 크기 레코드로 원자 보관한다. 등록이 없는 첫 실행만 자동 생성하며 기존 지문/등록에 키가 없거나 구형 토큰이면 `tls_repair_required`다. 새 페어링 지문 결합 및 구형 토큰 네트워크 거절은 T3에서 필수 적용한다.
- [x] 로컬 초기화는 먼저 등록 세대를 증가시키고 토큰 폐기·CA 지문 비우기를 내구 확인한 뒤 새 신원을 저장하고 새 지문을 결합한다. 어느 단계에서 실패해도 기존 토큰을 새 CA에 결합하지 않는다. 초기화 함수는 네트워크 API가 아니며 T3의 로컬 UI만 호출한다.
- [x] SSLContext는 `ssl.PROTOCOL_TLS_SERVER`, `minimum_version=TLSv1_2`로 생성한다. PEM 로딩용 파일은 보호 폴더에서만 생성하고 `finally`에 닫기·삭제, 재시작 시 소유한 임시 파일만 정리한다. raw 예외나 개인키를 로그에 쓰지 않는다.
- [x] 집중 시험을 통과시키고 보관 파일·키가 Git에서 제외되는지 확인했다. `7b080bbb feat: PC TLS 신원 보호 보관 추가`로 해당 파일만 커밋했다.

## 5. Task T3 — TLS 전용 서버·갱신·로컬 복구

진행 기록: 실제 TLS gateway 전환의 필수 인자 부재 실패를 확인한 뒤 기본 통신·기존 gateway 25개 시험을 통과했다. Qt 경로의 필수 TLS 신뢰 및 안내 누락 실패→수정 후 pairing/dialog/adapter 29개 통과를 확인했다. 이후 갱신·재시도·만료·복구 시험을 추가했다. 최종 TLS gateway/gateway/pairing/dialog/adapter/session 집중 시험은 `PYTHONASYNCIODEBUG=1`·경고 오류화에서 **86개 통과**했다. 명시한 기존 aiohttp 내부 DeprecationWarning 한 종류 외에 자원 경고를 제외하지 않았다. 기본 Ruff 및 개인정보 후보·BOM 검사를 통과했다.

집중 리뷰: Critical 없음, Important 1건은 갱신 전 인증서의 만료 판단을 전환 잠금 대기 후에도 적용하는 경합이었다. 별도 회귀 시험에서 유효한 새 인증서까지 종료되는 실패를 재현한 뒤 잠금 안에서 현재 실행 상태·현재 인증서·현재 시각을 재검사하도록 수정했다. 해당 수정 재검토는 Ready다. Minor 검증 잔여였던 실제 소켓의 TLS 1.0/1.1·만료/미래 leaf 거절도 4개 시험으로 추가 통과했다. 구형 TLS 허용은 거절 시험 클라이언트에만 적용하며 실제 앱의 서버·클라이언트 하한은 낮추지 않는다.

실제 경합 보완: `asyncio.Server.close()`는 이미 진행 중인 TLS 협상을 즉시 끝내지 않는다. 리스너 교체 직후 늦게 TLS를 완료하고 HTTP keep-alive를 유지하면 이전 리스너의 종료가 지연되는 실패를 재현했다. `tls_listener.py`의 작은 공개 `asyncio.Protocol` 전달 래퍼가 닫힌 리스너의 늦은 `connection_made`를 즉시 닫도록 수정했고 재현 시험을 통과했다. 미완료 협상에는 5초 제한을 유지한다. HTTP 단계의 8개/주소당 2개 제한이 TLS 협상 이전 전체 소켓 수까지 제한한다는 뜻은 아니며, 공용/외부 네트워크 서비스의 자원 방어를 완료했다고 주장하지 않는다.

갱신 수명: 만료 감시는 최대 60초 간격과 실제 만료 시한 중 빠른 시점에 진행한다. 갱신 준비는 별도의 단일 작업·작업 스레드에서 수행해 디스크 작업 중에도 만료 감시가 계속된다. 종료는 준비 스레드를 실제 회수한 뒤 보관 잠금을 해제한다. 안전하게 기존 파일을 보존한 저장 실패만 60/120/300초 재시도하며 총 4번 실패하면 수동 조치를 안내한다. 저장 결과 불명확·교체 단계 오류는 차단한다. 같은 CA·등록·Qt 원장을 유지하며 QR/기존 소켓만 무효화한다. 세션 송수신·명령 접수에도 유효기간 검사를 추가했다.

로컬 복구: OFF 상태에서 확인창을 거친 인증서 초기화가 별도 PC 스레드에서 동작한다. 키 손실→시작 거절→로컬 초기화→재시작 성공과 대화/처리 상태 보존을 합성 데이터로 검증했다. 초기화는 가상 연결 도구에 연결했으며 아직 실제 ENE 화면 통합 및 Android 인수까지 완료한 것은 아니다.

- [x] 실제 TLS `/info`·QR·WSS, 평문·다른 CA/이름·만료/미래 leaf·TLS 1.0/1.1 거절·무응답 협상 정리 시험을 작성하고 기존 gateway harness를 전용 CA·고정 이름으로 전환했다.
- [x] 기능 부재 실패를 확인하고 구현했다. `ssl=False`나 호스트 검증 해제를 사용하지 않았다.
- [x] Gateway에 열린 TLS 신원 보관을 필수 인자로 요구한다. 지문 확인 및 TLS 1.2+ SSLContext를 만든 후 공개 `runner.server`/`loop.create_server`로 전용 리스너를 소유한다. HTTP 별도 포트는 없으며 종료·실패 시 자원을 정리한다.
- [x] PairingService는 활성 CA를 요구하며 새 등록·등록 해제에 같은 CA 지문을 보존한다. 구형 지문 없는 등록은 거절한다. controller는 신원 확인→Qt 장벽→TLS 시작 순서를 유지하며 TLS 오류는 모바일 서버만 종료한다.
- [x] 가상 시계로 갱신·실패·제한된 재시도·만료·CA 임박·stop 경합을 검증했다. CA 임박 시 갱신을 반복하지 않으며 만료 감시 및 세션 유효기간 검사는 계속한다.
- [x] 단일 갱신 준비와 등록 변경 공유 lock·Qt 장벽으로 QR/기존 소켓 종료 및 리스너 교체를 수행한다. 같은 등록·원장을 유지하며 불명확한 실패는 차단한다.
- [x] TLS 안내와 키 손실 로컬 초기화를 추가했다. OFF·명시 확인 후 별도 작업 스레드에서 처리하며 실제 앱 설정·대화를 삭제하지 않는다.
- [x] 관련 집중/비동기 강화 시험 86개 통과 후 `feat: 동반 앱 서버 TLS 전용 연결과 갱신 구현`으로 로컬 커밋한다. 최종 실제 ENE 및 Android 단말 인수는 후속 작업이다.

## 6. Task T4 — Android 신뢰와 실제 HTTPS/WSS

- [ ] `TrustedServerTest.kt`와 `TlsTestCertificates.kt`를 작성한다. 테스트 실행 때 CA/서버 키를 만들며 CA 복원·유효기간·형식·고정 이름·CA 범위·후행 DER를 검증한다. `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.TrustedServerTest"`로 실패를 확인한다.
- [ ] `TrustedServer`는 `serverId`, canonical CA 문자열, 고정 이름과 매 연결 유효성 검사를 제공한다. JVM `CertificateFactory`·`X509Certificate`를 쓰고 원본 CA의 단일 DER·서명·P-256 파라미터·keyCertSign·CA pathLen=0을 검사한다. 문자열 출력에는 인증서나 등록 상세를 넣지 않는다.
- [ ] `TlsClientTest.kt`에서 진짜 MockWebServer TLS 연결, 다른 CA·동일 CA 다른 이름·만료/미래 leaf·평문 서버 거절, 토큰 미전송, `/info` 뒤 서버 교체, 리다이렉트, client 교체, endpoint 변경을 작성한다. `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.TlsClientTest"`로 실패를 확인한다.
- [ ] 전용 빈 `KeyStore`에 QR CA 하나만 넣고 `TrustManagerFactory`로 `SSLContext`를 만든다. `ConnectionSpec`은 TLS 1.2/1.3만 허용한다. 기본 `HostnameVerifier`를 바꾸지 않는다. 전송 생성 시 `TrustedServer`를 필수 인자로 받고 신뢰 없는 기본 생성자를 제거한다.
- [ ] URL은 `https://ene-<id>.invalid:<port>/companion/v1/...`로 만들고 전용 `Dns`는 그 이름을 현재 endpoint의 IPv4로만 연결한다. 임의 이름 요청을 거절하고 endpoint가 바뀌면 새 client/pool을 사용한다. 수동 DNS 해석은 IO에서 timeout/cancel·최대 8개 IPv4 후보로 제한하며 내부 TLS 이름은 시스템 DNS에 보내지 않는다.
- [ ] SSL 검증 오류는 `tls_identity_invalid`/`tls_expired` 등 안전한 코드로 분리한다. 원본 예외를 화면·로그로 전달하지 않는다. 실제 HTTPS/WSS에서는 TLS 후에만 HTTP 토큰 헤더가 전송됨을 서버 수신 계수로 검증한다. 신뢰 확인 안 된 `401`은 등록 폐기로 처리하지 않는다.
- [ ] CA 유효성은 보관 복원·매 요청·소켓의 송수신 및 만료 타이머에서도 확인한다. 클라이언트/소켓을 닫으면 타이머와 진행 call이 함께 취소된다. 키가 다른 client 간 기존 TLS 세션·pool을 공유하지 않는다.
- [ ] 기존 `CompanionSocketTest.kt`를 TLS로 전환한 뒤 `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.TrustedServerTest" --tests "dev.ene.companion.TlsClientTest" --tests "dev.ene.companion.CompanionSocketTest"`를 통과시키고 `feat: Android QR 신뢰 기반 HTTPS WSS 전송 추가`로 커밋한다.

## 7. Task T5 — Android QR·보관·평문 차단

- [ ] `PairingQrTest.kt`를 공통 TLS 사례로 확대하고 `StoragePolicyTest.kt`에 실제 XML 파싱 기반의 `usesCleartextTraffic=false`/`cleartextTrafficPermitted=false`·허용 override 없음 검증을 추가한다. `DeviceCredentials`에 TLS 신뢰 정보 없는 구형 레코드 거절 시험을 추가한다.
- [ ] `.\gradlew.bat :app:testDebugUnitTest --tests "dev.ene.companion.PairingQrTest" --tests "dev.ene.companion.StoragePolicyTest" --tests "dev.ene.companion.DeviceCredentialsTest"`로 실패를 확인한다.
- [ ] QR에는 필수 `transport`·CA를 적용하고 QR 원문은 메모리로만 넘긴다. Keystore 암호화 내부 레코드에 전송 프로필·CA를 필수 포함하고 parse/save 양쪽에서 유효성을 검사한다. envelope/내부 버전을 구별하고 구형 레코드를 자동 승격하지 않는다. 원자 저장과 주소 별도 보관·백업 제외는 유지한다.
- [ ] Manifest와 network XML에 평문 차단만 추가한다. CAMERA는 기존 승인된 QR 기능에 맞춰 선언하되 실제 요청/카메라 분석기는 기본 Task 5에서 완성한다. SSL 오류 무시·debug 전용 평문 우회도 넣지 않는다.
- [ ] 계측 `TokenStoreTest`에 CA/토큰 원자 복원·키 손실·구형 형식 거절·백업 제외를 반영하고 `.\gradlew.bat :app:compileDebugAndroidTestKotlin`로 컴파일한다. 실제 단말이 없으면 실행 성공으로 기록하지 않는다.
- [ ] 단위 집중 시험과 `.\gradlew.bat :app:assembleDebug` 성공 후 문서/개인정보·키·산출물 검사를 수행한다. `feat: TLS QR 등록 보관과 평문 차단 적용`으로 커밋한다.

## 8. Task T6 — 통합 검증과 기본 작업 복귀

- [ ] 두 계약 디렉터리의 `protocol.md`, `cases.json`, `tls_cases.json` 바이트 동일성을 확인한다. old HTTP·검증 해제·기밀 로깅·실제 키 fixture가 남지 않았는지 현재 diff를 집중 리뷰한다.
- [ ] PC 동반 앱 전체 집중 시험 `python -m pytest tests/test_companion_*.py -q`는 PowerShell이 glob을 넘기지 않으므로 실제 파일 목록을 `rg --files tests -g 'test_companion_*.py'`로 얻어 명령 인자로 전달한다. 전체 인터페이스/수명 변경 체크포인트이므로 PC 전체 테스트도 격리된 실행 데이터와 임시 cwd 규칙으로 실행한다.
- [ ] Android `.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:compileDebugAndroidTestKotlin --offline --console=plain`을 실행한다. 미완성 Repository/UI 시험이나 단말 시험이 있다면 그대로 미완료로 기록한다.
- [ ] 실제 loopback Qt·TLS·클라이언트 통합에서 QR→PC 승인→WSS→전체 sync→가상 echo→중복 재시도 1회 실행을 확인한다. 자동 시험만으로 실제 Android의 LAN 성공을 주장하지 않는다.
- [ ] [기본 구현 계획](2026-09-08-ene-companion-lan-v1.md)의 Task 5 연결 Repository·카메라·최소 화면 작업을 재개할 수 있는 상태와 검증 결과를 기록한다. 기존 Task 6의 단말 선택/설치 승인 경계는 유지한다.
- [ ] 최종 개인정보 후보·UTF-8/BOM·`git diff --check` 및 커밋 범위 확인 후 `docs: 동반 앱 TLS 전환 검증 기록`으로 인계 문서를 커밋한다. 원격 push·태그·APK 업로드는 하지 않는다.

## 9. 검증·커밋 규칙

각 테스트는 해당 저장소 cwd에서 실행한다. Windows temp 접근 제한이 있으면 승인된 실행 권한으로 같은 시험을 수행하고 환경 오류를 코드 실패로 숨기지 않는다. 긴 테스트는 세션으로 실행해 진행 상황을 공유한다. 키·이름·실제 대화·생일·건강·일정·취업·프로필·API 키 패턴과 개인 경로를 커밋 전 검사한다. 실행 데이터·인증키·APK·스크린샷은 stage하지 않는다. 문서가 ignore되면 정확한 해당 문서만 `git add -f` 한다.

각 Task 완료는 실제 동일 명령의 통과 증거가 있을 때만 체크한다. 계획 리뷰 통과·계측 코드 컴파일·APK 빌드는 실제 단말 검증의 대체가 아니다. 일반 변경은 집중 테스트로 끝내고 전체 테스트는 T6의 통합 체크포인트에 한 번 수행한다.
