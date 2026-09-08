# 동반 앱 HTTPS/WSS 전환 검증

검증일: 2026-09-08. 범위는 [TLS 구현 계획](superpowers/plans/2026-09-08-ene-companion-tls.md)의 T1~T6다. 실제 동반 앱 전체 출시 완료가 아니다.

## 구현과 검증

| 범위 | 확인 결과 |
| --- | --- |
| PC TLS 신원 | PC별 P-256 CA·단기 서버 인증서, 엄격한 QR CA 형식·고정 이름 |
| PC 보관 | 현재 사용자/SYSTEM DACL, 원자 저장·OS 배타 잠금·임시 PEM 정리 |
| PC 네트워크 | HTTPS/WSS 전용, TLS 1.2+, 갱신·종료·만료·오래된 TLS 협상 정리 |
| PC 복구 | OFF 상태 명시 확인, 기존 등록 폐기/세대 증가 후 새 CA 저장 |
| Android | QR CA 하나·플랫폼 체인/기본 이름 검증, 주소 분리, TLS 필수 전송, 토큰/CA 단일 암호화 등록 |
| PC 동반 앱 강화 시험 | 229개 통과·1개 건너뜀, asyncio debug 및 경고 오류화 |
| PC 전체 회귀 시험 | 3,478개 통과·1개 건너뜀, 67.55초 |
| PC Ruff | E9/F63/F7/F82 통과 |
| Android JVM | 60개 통과 |
| Android 검사/빌드 | Lint 오류 0·경고 23, debug APK/기기 시험 코드 빌드 성공 |
| Android Keystore 기기 시험 | 6개 컴파일·시험 APK 생성, 실제 단말 실행 미검증 |

PC에서 건너뛴 1개는 계정의 심볼릭 링크 생성 권한 부재다. Windows DACL/배타 잠금은 실제로 검증했으나 POSIX 분기는 이 호스트에서 실행하지 않았다. 비동기 강화 실행에서 설치된 aiohttp 3.14.1의 기존 `Request._transport_sockname` DeprecationWarning 한 종류만 제외했다. 다른 자원 경고는 제외하지 않았다.

전체 PC 시험은 새 임시 cwd와 `ENE_USER_DATA_DIR`를 import 전에 지정했다. 첫 실행은 기존 UI 시험의 상대 `src/locales` 경로 때문에 6개가 실패했다. 임시 cwd에 공개 번역 리소스만 복사한 후 전체 재실행이 통과했다. 개인 설정·키·기억·프로필은 복사하지 않았다. 실제 앱을 시험할 때도 cwd의 옛 키 마이그레이션을 피하려면 데이터 환경 변수만이 아니라 cwd도 격리해야 한다.

Android Lint 캐시 부재 및 로컬 SDK 경로 이스케이프 오류를 분리 해결한 후 오프라인 검증을 통과했다. 경고는 고정 의존성의 업데이트 안내 22개와 후속 UI 단계의 앱 아이콘 1개다. 관련 없는 버전 일괄 변경이나 경고 baseline은 추가하지 않았다.

## 통합 시험의 의미

`test_full_controller_qt_approval_socket_echo_and_duplicate_recovery`는 실제 Qt·TLS 루프백 소켓으로 QR→PC 승인→WSS 인증→전체 sync→가상 응답→동일 요청 재전송을 검증했다. 가상 응답은 한 번만 실행되고 전체 기록 2개가 복원된다. 이것은 Python 시험 클라이언트와 가상 대화 소유자의 통합이며 실제 Android 단말·ENE AI/기억 동작의 증거가 아니다.

보안 리뷰에서 발견한 PC 갱신 전/후 만료 판단 경합과 Android 연결 협상 중 CA 만료 경합은 각각 실패 테스트로 재현하고 수정했다. Android에서는 기본 이름 검증을 유지하는 CA 날짜 검사 래퍼와 유휴 풀 0·HTTPS 연결 확보 검사를 함께 사용한다. OkHttp 5.3.2 WebSocket의 감시 기능 제외에 따른 보완이며 검증 무시는 없다. [TLS 설계 보완](superpowers/specs/2026-09-08-ene-companion-tls-design.md)

## 계약 및 저장소

두 독립 저장소의 계약 사본은 바이트 단위로 같다.

| 파일 | SHA-256 |
| --- | --- |
| protocol.md | `03E7B992CAA85426831ED4302FCC1C7BB37E6EC4BC33E04ED63165FC8061AC4F` |
| cases.json | `92C4FDEAE5CCCCA75ED57156A65A31CD9A03FDBEF0A79C14D06FF3485F495E21` |
| tls_cases.json | `4B42A8B42D0920724328225A4CBC99640D92E5A919F9A427E23EA9476B54711B` |

PC 구현 커밋은 `fe20886e`(모델/계약), `7b080bbb`(보호 보관), `911e9fe4`(서버/수명)이다. Android T4/T5는 `6e2e7dd`로 커밋했다. 기존 미커밋 Task 5 전송·보관 기반과 같은 빌드 설정을 사용하므로 하나의 검증 가능한 로컬 커밋으로 기록했다. Android 자체 인계 문서는 독립 저장소의 `docs/tls-transport.md`다. 원본 PC 작업 폴더·Fish Audio 변경은 보존했으며 병합·push·태그·Release·APK 업로드를 수행하지 않았다.

## 재개 지점

[기본 계획 Task 5](superpowers/plans/2026-09-08-ene-companion-lan-v1.md)의 연결 Repository·전경 수명·QR 카메라·최소 채팅 화면을 이어서 구현한다. 이 단계부터는 반드시 `TrustedServer`가 있는 전송과 TLS 등록 형식을 사용하며 평문 클라이언트를 새로 만들지 않는다. 현재 APK는 기본 개발 화면이다.

후속 단말 선택/설치 승인과 조기 가상 LAN 인수를 거친 후 실제 ENE 대화 경계·공통 접수·트레이/종료 통합을 진행한다. 출시 서명·실기기 Keystore·LAN·실제 ENE·성능 검증은 미완료다. 공용 인터넷 서비스의 TLS 협상 전 전체 소켓 자원 방어까지 검증한 것으로 해석하지 않는다. 외부 접속·Tailscale·TTS·Live2D는 이번 TLS 전환 범위에 추가하지 않았다.
