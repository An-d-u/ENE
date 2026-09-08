# ENE 동반 앱 텍스트 계약 V1

상태: LAN V1 구현 원본. Python과 Kotlin이 동일한 `cases.json`을 사용한다. 앱의 화면·네트워크·실기기 검증 완료를 뜻하지 않는다.

## 기본 규칙

- HTTP/WS 평문, 신뢰하는 개인 LAN 전용이다. TLS·외부 중계·임의 WebBridge 호출은 제공하지 않는다.
- JSON UTF-8. 모든 WS 메시지에 `type` 문자열과 실제 정수 `protocol_version:1`이 필요하다. 숫자 모양 문자열·소수·불리언을 정수로 취급하지 않는다.
- UUID는 표준 하이픈 문자열이며 소문자로 정규화한다. 시퀀스·개정은 0~9007199254740991이다. 등록 세대는 1 이상이다.
- 알려진 종류의 추가 선택 필드는 무시한다. 필수 키 누락·자료형 오류는 `invalid_message`, 미지원 버전은 `unsupported_version`, 미지 종류는 `unsupported_command`다.
- JSON 최대 깊이 16. 일반 메시지 UTF-8 65536바이트, 인증 전 첫 본문 8192바이트, 전송 텍스트 16384바이트다. 공백만 있는 입력과 짝이 맞지 않는 UTF-16 surrogate를 거절하되 정상 텍스트의 공백·개행은 변형하지 않는다.
- 코드 문자열은 소문자 영문 시작, 영문·숫자·밑줄 64자 이내다. 기능 이름은 영문 소문자 시작, 영문·숫자·밑줄·점·콜론·하이픈 64자 이내, 기능 목록 최대 32개다. 기능 중복은 거절한다. V1은 빈 목록을 사용한다.
- 바이트 크기 초과는 `message_too_large` 또는 `text_too_large`다. 오류 메시지에 원문·토큰·서버 예외 상세를 포함하지 않는다.

## 경로와 인증

| 경로 | 동작 |
| --- | --- |
| `GET /companion/v1/info` | 인증 없이 `server_id`, `protocol_versions:[1]`만 반환, 캐시 금지 |
| `GET /companion/v1/pair` | 페어링 전용 WS. 첫 본문 `pair_request`로 QR 암호 전달. PC 로컬 승인만 가능 |
| `GET /companion/v1/ws` | 일반 WS. `Authorization: Bearer` 토큰 검사 후 hello, ready, 전체 동기화 |

Origin 헤더가 있는 브라우저 연결은 거절한다. 리다이렉트·시스템 프록시·URL 쿼리 자격증명을 사용하지 않는다. 먼저 정보 경로의 PC ID가 일치하는지 확인하지만 이것이 평문 서버의 암호학적 인증은 아니다.

QR은 `protocol_version, server_id, pairing_id, expires_at, secret, addresses:[{host,port}]`이며 최대 2048바이트·IPv4 주소 후보 8개다. secret/token은 난수 32바이트의 패딩 없는 base64url 문자열이다. QR 유효 시간은 서버 단조 시계로 120초, 최초 유효 연결에 묶고 거절·종료·만료·재발급·소비 후 재사용하지 않는다. 새 등록을 내구 저장하고 Qt 장벽을 확정한 뒤 구등록을 폐기하고 새 토큰을 한 번만 보낸다.

주소당 연결/정보 조회 3초, 첫 hello/pair_request 5초, WS 종료 유예 2초다. 같은 등록의 새 소켓은 인증과 hello 검증 후에만 구소켓을 교체한다. 구소켓의 늦은 callback/미수락 요청은 무효이며 이미 예약/수락한 작업과 원장은 유지한다.

## 메시지 필드

아래 표의 필드는 공통 `type, protocol_version` 외의 필드다. 물음표는 선택 키이며 생략과 null은 다르다. 선택 키도 있으면 올바른 자료형이어야 한다.

| 종류 | 필드 |
| --- | --- |
| `pair_request` | pairing_id:UUID, secret:난수 문자열, device_name:공백 아닌 문자열(최대 80 유니코드 코드 포인트) |
| `pair_pending` | pairing_id:UUID |
| `pair_failed` | pairing_id:UUID, code:오류 코드 |
| `pair_approved` | pairing_id/server_id/device_id:UUID, registration_generation:양의 정수, token:난수 문자열 |
| `hello` | capabilities?:기능 목록, 생략하면 [] |
| `ready` | server_id/server_epoch/conversation_id:UUID, registration_generation:양의 정수, capabilities?:기능 목록, 생략하면 [] |
| `sync_request` | pending_request_ids?:UUID 목록(최대 1개), 생략하면 [] |
| `snapshot_begin` | server_epoch/conversation_id/snapshot_id:UUID, event_seq/conversation_revision:정수, part_count/byte_count/message_count:정수, sha256:소문자 16진수 64자 |
| `snapshot_part` | server_epoch/conversation_id/snapshot_id:UUID, index:정수, data_base64:표준 패딩 포함 base64 |
| `snapshot_end` | server_epoch/conversation_id/snapshot_id:UUID, part_count/byte_count:정수, sha256:소문자 16진수 64자 |
| `event` | server_epoch/conversation_id:UUID, event_seq/conversation_revision:정수, op:append 또는 processing, payload:아래 공개 메시지 또는 처리 상태 |
| `resync_required` | server_epoch/conversation_id:UUID, reason:reset 또는 replace 또는 large_event 또는 gap |
| `send_text` | server_epoch/conversation_id/request_id:UUID, text:공백 아닌 텍스트 |
| `request_status` | server_epoch/conversation_id/request_id:UUID, state:unknown/reserved/accepted/completed/failed/rejected, message_id?:UUID, code?:오류 코드 |
| `ping` / `pong` | nonce:UUID |
| `error` | code:오류 코드, request_id?:UUID |

공개 메시지: `id:UUID, role:user|assistant, text:문자열, displayed_at:UTC RFC3339(Z), request_id?:UUID, attachment_unsupported?:true`.
처리 상태: `phase:idle|preparing|responding, request_id?:UUID`. idle에는 request_id를 넣지 않는다.
스냅샷 본문: `messages:[공개 메시지], processing:처리 상태`.

공개 허용 목록 밖의 thought·감정 분석·첨부 원본·로컬 경로·모델 설정·기억 원문은 송신하지 않는다. 기존 메시지의 추가 선택 키를 해석기가 받아들인다는 사실을 서버의 임의 정보 공개 허가로 해석하지 않는다.

## 동기화와 자원

- 공개 메시지 최대 50000개, 단일 공개 텍스트 UTF-8 최대 1048576바이트, 스냅샷 직렬화 총량 최대 33554432바이트. 초과는 `snapshot_too_large`이며 PC 기록은 자르지 않는다.
- 스냅샷 원본 바이트를 최대 32768바이트씩 나누어 base64로 보낸다. part_count는 byte_count/32768의 올림(1~1024), index는 0부터 순서대로다. 전체 수신 120초·유효 부분 진행 무응답 10초다.
- begin/end의 총량·해시가 같고 모든 부분의 합계·순서·SHA-256이 맞아야 본문을 해석해 원자 교체한다. 해시는 PC의 실제 직렬화 바이트 기준이며 Kotlin에서 다시 JSON을 직렬화하여 비교하지 않는다.
- 구스냅샷 부분은 무시한다. 현재 스냅샷의 누락·중복·잘못된 해시·내용 개수는 `invalid_snapshot`, 기한 초과는 `snapshot_timeout`으로 조립을 폐기한다. 실패 시 기존 완성 대화를 지우지 않는다.
- 연결마다 캡처 대기/직렬화/송신 작업 한 개, 앱 조립기 한 개만 유지한다. 중복 sync는 병합하고 편집/reset은 이전 자원 정리 뒤 최신 한 건으로 대체한다. 늦은 캡처 결과는 세대로 폐기한다.
- 이벤트 큐와 앱 callback 처리 큐는 각각 최대 256개/4194304바이트다. 초과는 `slow_consumer` 종료 후 전체 재동기화다. 무제한 task를 만들지 않는다.
- 32 MiB는 직렬화 데이터 상한이지 모든 객체/복사본을 포함한 메모리 상한은 아니다. OkHttp는 callback 전에 메시지를 버퍼링하므로 callback 크기 검사만으로 악의적인 서버에 대한 수신 전 메모리 상한을 보장하지 않는다.
- 스냅샷 캡처와 이벤트 구독 사이 누락을 없앤다. 이후 event_seq는 연속 적용, 중복은 무시, 누락은 전체 sync한다. 추가/교체는 개정을 올리고 처리 상태 변화는 이벤트 번호만 올린다.
- 편집/reset/너무 큰 append는 resync_required로 무효화한다. 그 알림 자체나 미래 음성/캐릭터 이벤트는 기본 텍스트 event_seq를 소비하지 않는다.
- 인증 전 연결 전체 8개/주소당 2개, 시도 분당 전체 60회/주소당 10회, 승인 대기 한 개. 인증 후 명령 초당 10개/버스트 20개다.
- 양쪽 앱 수준 ping은 15초, 동일 nonce의 pong 기한 10초다. 정상 전경 실행에서 약 25초 이내 단절 감지. 구연결 timer와 다른 데이터 수신으로 기한을 갱신하지 않는다.

## 수락과 원장

Qt 검사 순서: 등록/게이트웨이/연결 세대 → 실행/대화 → 입력/모바일 파일 명령 금지 → 동일 요청 조회 → 기존 단일 작업 gate → 예약 → 기존 처리 경로.
같은 `(registration_generation, server_epoch, conversation_id, request_id)`와 같은 text UTF-8 SHA-256은 이전 상태를 반환한다. 다른 본문은 `request_conflict`다. gateway/socket 세대는 원장 키에 넣지 않는다.

reserved는 준비 예약, accepted는 공개 사용자 메시지 반영 완료다. 예약 중 준비 실패도 failed로 확정한다. accepted 이후 completed/failed로 종료하며 이미 끝난 결과를 오래된 callback으로 되돌리지 않는다. AI 실패를 자동 재호출하지 않는다. 같은 대화 동안 원장을 만료시키지 않고 요약·게이트웨이/소켓 교체도 원장을 유지한다.

재접속은 전체 sync 및 미확정 요청 조회부터 한다. 같은 등록/실행/대화의 unknown만 같은 ID/본문으로 재시도한다. 확정 거절 후 사용자 재전송은 새 ID다. 프로세스 종료를 넘는 대화·초안·미확정 전송은 앱에 저장하지 않는다.

## 계약 사례와 변경

`cases.json`의 개별 사례는 메시지 하나의 해석/정규화 규칙을 검증한다. 실제 스냅샷 왕복·원장 상태 전이·연결은 별도 테스트다. 키/토큰 사례는 테스트 실행 중 생성한다. 기본 텍스트의 필수 의미를 바꾸지 않으며 새 기능은 양쪽 capabilities 교집합에서만 별도 지원한다. 이 원본과 Android 사본의 SHA-256을 각 변경에서 비교한다.
