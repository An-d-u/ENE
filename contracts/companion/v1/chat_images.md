# chat_images_v1: 모바일 사진 입력

이 선택적 확장은 기본 v1 스냅샷·텍스트 상한·요청 원장을 변경하지 않는다. hello/ready/extensions_ready에서 협상하며 실행부가 준비된 서버만 광고한다. 구형 클라이언트에는 보내지 않는다.

## 공통 봉투

모든 메시지: type, protocol_version=1, registration_generation(1 이상 정수), server_epoch/connection_generation/conversation_id(UUID). 현재 등록·실행·연결·대화와 모두 일치해야 한다. 방향·협상 검사를 먼저 수행한다. 기존 65536바이트 봉투 및 16384바이트 UTF-8 전송 텍스트 상한을 유지한다. SHA-256은 소문자 64자리 hex다. 정상·비정상 공통 사례는 chat_images_cases.json이다.

## 메시지

| 방향 | type | 추가 필수 필드 |
| --- | --- | --- |
| 폰→PC | input_reserve | command_id(UUID), purpose=image, byte_length(1..4194304), sha256 |
| PC→폰 | input_reserved | command_id, purpose=image, upload_id(UUID) |
| 폰→PC | input_cancel | command_id, purpose=image, upload_id |
| 폰→PC | chat_images_send | request_id(UUID), text(빈 문자열 허용), images(1..4) |
| 폰→PC | chat_images_limits_request | query_id(UUID) |
| PC→폰 | chat_images_limits | query_id, allowed(bool), reason(고정 코드), max_count=4 |
| 폰→PC | chat_images_request | query_id, message_id(UUID), conversation_revision(0 이상) |
| PC→폰 | chat_images_state | query_id, message_id, conversation_revision, attachment_revision(0 이상), images(0..4) |
| PC→폰 | chat_images_invalidated | message_id, attachment_revision |

전송 images 원소: upload_id, sha256, byte_length(1..4194304), mime(image/png 또는 image/jpeg). 순서를 유지하며 같은 upload_id를 중복 참조하지 않는다.
상태 images 원소: id(UUID), width/height(1..2048), mime(image/png 또는 image/jpeg). 중복 id 금지.
allowed=true는 reason=ready와 동치다. 알려진 비지원 모델·busy·AI 미초기화 사유를 고정 코드로 제공한다.
명령 실패는 기존 extension_error(feature=chat_images_v1, code, 해당 command_id 또는 query_id)로 알린다. 조회 응답 5초, 예약 응답 5초를 넘기면 자동 반복하지 않고 오류를 표시한다.

## 제한된 HTTPS

PUT /companion/v1/input/{upload_id}. 기존 PC CA·고정 TLS 이름을 검증하고 리다이렉트/자동 재시도를 금지한다. Authorization: Bearer 등록 토큰, X-ENE-Connection: 현재 WSS 연결 UUID, Content-Type: application/octet-stream, 명시 Content-Length가 필수다. 쿼리·Origin·Range·Transfer-Encoding·Content-Encoding·인코딩된 임의 경로를 거절한다. URL에 토큰을 넣지 않는다.

인증된 현재 WSS에서 발급된 동일 연결 예약만 사용한다. 선언 길이를 읽기 전에 검사하고 증분 수신 때도 검사한다. 원문은 메모리의 유한 버퍼만 사용한다. SHA·길이·실제 정지 JPEG/PNG·픽셀 디코드·긴 변2048 제한을 확인한 뒤에만 ready. 성공 200, JSON {"status":"ready"}, Cache-Control:no-store. 실패는 기존 고정 code JSON 및 400/401/404/408/409/429. 서버 예외/파일경로/입력 본문은 응답·로그에 넣지 않는다.

한 연결 동시 업로드1개, 보류 이미지4개/16MiB, PCM과 합산 17737216바이트(16777216+960000) 예약 한도다. 이전 연결 검증 worker가 남아도 공유 총예산에 포함한다. 예약 TTL120초, HTTP 유휴10초/총60초. 업로드 HTTP rate는 별도 초당2·burst8, 썸네일은 별도 제한을 쓴다. 단절·취소·등록/대화 교체·실패·만료는 미수락 자료를 폐기한다. 완료 시 현재 세대를 재검사한다.

## 수락·중복·복구

chat_images_send는 전부 검증된 참조를 기존 Qt 예약 gate에서 원자 이전한다. 업로드 성공은 메시지 수락이 아니다. 원장 키는 기존 등록/실행/대화/request_id. 지문은 text와 순서 있는 sha256/mime/byte_length이며 임시 upload_id는 제외한다. 같은 ID 다른 내용은 request_conflict. 사진만 보내면 기존 PC 첨부 기본 문구를 사용한다. 일부 오류를 텍스트 전용 요청으로 바꾸지 않는다.

응답은 기존 request_status. reserved/accepted 이후 소켓 종료가 PC 소유 첨부를 삭제하지 않는다. 재연결은 전체 동기화와 같은 request_id 원장 조회 우선. unknown이 확인된 같은 등록/실행/대화에서만 사용자의 재시도로 같은 ID·같은 내용 재업로드를 허용한다. 결과 불명/세대 변경 후 자동 새 요청을 만들지 않는다.

## 공개 첨부

이번 기능으로 수락된 사진만 공개하며 과거 PC 전용 사진/문서는 노출하지 않는다. 기본 attachment_unsupported 표식은 보존한다. 메타데이터는 현재 공개 message_id와 대화 revision을 대조해 병합한다. 조기/지연 응답은 다른 메시지에 붙이지 않는다. 현재 보이는 메시지의 조회로 복구하며 메타데이터 실패가 본문을 삭제하지 않는다.

GET /companion/v1/chat-images/{message_id}/{image_id}: 동일 토큰·연결 검증, 현재 공개 첨부만. 썸네일 긴 변320px/128KiB, Cache-Control:no-store, MIME PNG/JPEG. 앱 캐시 총8MiB 이하. 삭제revision/등록/대화 변경 시 표시와 캐시를 무효화한다. 수정은 텍스트만, 리롤은 같은 PC 보관 사진을 사용한다.

## Android 준비와 개인정보

시스템 Photo Picker(하위버전 문서선택 fallback), 앱에서 다시4장 제한. 원본≤32MiB/변32768/100M픽셀, bounds 우선과 sample decode, 실제 픽셀 회전, EXIF·원래파일명·경로 제거. 정지 사진을 한 장씩 UI 밖에서 JPEG/PNG로 재인코딩(긴변2048/장4MiB). 선택만으로 업로드하지 않는다. 전송하면 PC 설정의 이미지 지원 LLM 제공자에게 전달될 수 있음을 안내한다.

초안 사진은 no-backup 앱 임시 영역만 사용한다. 같은 프로세스 회전·picker왕복·단절에서 유지, 제거·수락확인·등록교체·명시취소 시 회수. 프로세스 종료 잔여물은 다음 시작 시 그 임시 영역에서만 정리한다. 사용자 원본은 변경/삭제하지 않는다.
