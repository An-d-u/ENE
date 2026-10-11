# stt_input_v1: 휴대폰 녹음의 PC 전사

기본 채팅 원장과 독립인 선택적 확장이다. chat_images_v1 없이도 협상 가능하다. 공통 봉투·TLS·업로드 수명은 chat_images.md와 같으며 purpose=pcm 예약은 stt_input_v1만 요구한다.

## 메시지

모든 메시지는 type/protocol_version/registration_generation/server_epoch/connection_generation/conversation_id 필수. 등록은 양의 정수, 나머지 식별자는 UUID다. 정상·비정상 사례는 stt_input_cases.json.

| 방향 | type | 추가 필수 필드 |
| --- | --- | --- |
| 폰→PC | stt_limits_request | query_id |
| PC→폰 | stt_limits | query_id, min_ms, max_ms, sample_rate=16000, channels=1, sample_width=2, allowed, reason |
| 폰→PC | stt_begin | command_id |
| PC→폰 | stt_ready | command_id, min_ms, max_ms |
| 폰→PC | input_reserve | command_id, purpose=pcm, byte_length, sha256 |
| PC→폰 | input_reserved | command_id, purpose=pcm, upload_id |
| 폰→PC | input_cancel | command_id, purpose=pcm, upload_id |
| 폰→PC | stt_transcribe | command_id, upload_id, byte_length, sha256 |
| PC→폰 | stt_result | command_id, status, text, reason |
| 폰→PC | stt_cancel | command_id |

query_id/command_id/upload_id는 UUID. min_ms=0..30000, max_ms=max(1,min_ms)..30000. allowed=true와 reason=ready는 동치다.
PCM16LE 16kHz 모노, 길이2..960000 짝수, 최대30초. 입력 파일·WAV 헤더를 받지 않는다. SHA 소문자64hex. 업로드 예약 명령 ID와 인식 명령 ID는 별개이며 입력 참조는 같은 연결에서 검증한다.

status는 complete/failed/cancelled. complete는 비어있지 않은 UTF8 16384바이트 이하 text, 다른 상태는 빈 text. reason은 고정 코드. 실패 예외·녹음·인식 원문은 로그/진단에 남기지 않는다. 구문/현재 권한 오류는 extension_error(feature=stt_input_v1, code, command_id 또는 query_id). 조회/시작 ACK는5초, 모델준비+인식은120초, HTTP 전송은 별도 유휴10초/총60초.

## 녹음 수명

사용자가 + → 음성 입력을 선택할 때만 권한 요청. 시작 시 PC 최소/최대 길이와 모델·장치·언어 설정을 고정하되 폰에는 녹음 제한만 전달한다. PC PTT 단축키 설정과 독립이며 PC 마이크를 열지 않는다. AudioRecord 초기화/형식 실패는 명시 오류.

유한 메모리로 전경 녹음한다. 최대 길이 도달은 녹음만 정지하고 완료/취소를 기다린다. 완료 후 PC 전사, 자동 LLM 전송0회. Activity stop/잠금/홈/단절/권한 철회/다른 기기 응답·TTS 시작에서 취소·마이크 해제, 복귀 자동녹음 없음. 기존 음성 출력 선택이나 fallback 정책은 바꾸지 않는다.

## PC worker

기존 faster-whisper 모델 준비와 CPU 복구 경로를 공유한다. 외부 전사 API 없음. 로컬 모델 미설치 시 기존 모델 다운로드가 필요할 수 있으며 실패를 숨기지 않는다.

PC PTT와 모바일 추론은 하나의 실행권을 공유한다. 뒤 요청은 busy, 무제한 큐/복제 모델 없음. 모델 설정 변경은 실행 중 모델을 교체하지 않고 다음 작업으로 적용한다. transcribe 반환 뒤 segment iterable 순회까지 실행권 유지. 네트워크/Qt 스레드에서 추론하지 않는다.

cancel/timeout/대화·연결 세대 변경은 결과 적용권만 먼저 취소한다. 중단 불가 네이티브 worker는 실제 종료까지 실행권과 입력을 보유하고 이후 회수한다. 오래된 결과를 새 연결에 전달하지 않는다. 같은 command_id는 중복 실행하지 않는다. 완료/취소 자료는 현재 연결의 bounded 상태로만 관리한다.

## 초안과 개인정보

녹음 시작 시 draft identity+revision 캡처. 그대로이면 결과를 초안 끝에 추가, 달라졌으면 명시 추가 영역에 보관한다. 문자열만 비교하지 않으며 수정후되돌림·전송후같은문구도 새 revision이다. 합친 초안16KiB초과/빈결과는 오류이며 자르지 않는다. 이전 연결/취소 결과는 폐기, 끊긴 전사는 자동 재실행하지 않는다.

APP/PC 모두 새로운 녹음 파일을 만들지 않는다. 메모리 참조는 각 소유자 종료 시 해제한다. OS/네이티브 사본의 물리적 완전삭제를 보장하지 않는다. 미전송 텍스트는 프로세스수명만 유지, 실제 전송한 텍스트만 기존 대화 정책을 따른다.
