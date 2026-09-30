# 마지막 대화 조작 확장

기본 프로토콜 1의 독립 기능 `chat_actions_v1`이다. 미협상 연결에는 전송하지 않는다. 음성·캐릭터는 필요하지 않다.

공통 필드: `registration_generation`, `server_epoch`, `connection_generation`, `conversation_id`. 기존 UUID·안전 정수·TLS 인증 검사를 적용한다.

- `chat_actions_request` (폰→PC): `query_id` UUID, `refresh` boolean. true이면 조회 수신 이후의 새로운 전체 캡처 전송을 요구한다.
- `chat_actions_state` (PC→폰): 대화 revision/event_seq, 단조 증가 state_seq, user_message_id/assistant_message_id, edit_allowed/edit_reason, reroll_allowed/reroll_reason. query_id/snapshot_id는 자동 알림에서 null이다. 새 캡처 응답은 해당 query_id와 전송 완료한 snapshot_id를 돌려준다.
- `chat_action` (폰→PC): request_id, kind(edit/reroll), target_message_id, expected_revision. edit만 text를 갖는다. 본문은 비공백 UTF-8 16,384바이트 이하이고 PC 전용 명령은 불가다.

조회·상태 프레임 상한은 2,048바이트, 조작은 65,536바이트다. 본문 한도는 별도로 적용한다. 사유는 ready/no_target/busy/ai_unavailable/unsupported_command/text_too_large다. 허용 true이면 대상 ID와 ready 사유가 필요하다. 공개 상태에 메시지 본문이나 첨부 경로를 넣지 않는다.

결과는 기존 request_status, 재접속 조회는 sync_request.pending_request_ids(최대 1)를 쓴다. 동일 request_id/본문은 기존 결과만 반환하며 새로운 생성은 하지 않는다. 서로 다른 본문은 충돌이다. 마지막 쌍만 수정하며 성공은 동일 ID 교체, 실패는 PC 원본 복원이다.

terminal/unknown 뒤 폰은 fresh 조회를 보내고 설치된 snapshot_id·대화·revision·event_seq가 해당 응답과 일치할 때만 다음 조작을 허용한다. 이전 캡처·다른 query_id·늦은 상태로는 잠금을 풀지 않는다. unknown 요청을 자동 재전송하지 않는다. 합성 사례는 chat_actions_cases.json을 양쪽에서 동일하게 검증한다.
