# 대화 생성 진행 확장

능력 `chat_progress_v1`을 협상한 연결에서만 사용한다. 오디오·캐릭터 능력과 독립적이며 기본 대화 순서와 입력 잠금을 변경하지 않는다.

## 형식

기존 확장 봉투 `protocol_version=1`, `type`, `registration_generation`(1 이상 안전 정수), `server_epoch`·`connection_generation`(UUID)에 현재 `conversation_id`(UUID)를 추가한다.

- 휴대폰 → PC: `chat_progress_request`. 추가 본문은 없다.
- PC → 휴대폰: `chat_progress_state`. `progress_revision`(0~9,007,199,254,740,991 정수), `phase`가 필수다.
- phase는 `idle/preparing/generating/text_ready` 중 하나다. idle은 request_id 키를 금지한다(null도 금지). 그 외에는 UUID `request_id`가 필수다.
- 두 메시지의 UTF-8 원문은 2,048바이트 이하이며 알 수 없는 필드 제거 전 크기를 검사한다. 기존 알 수 없는 필드 정책은 유지한다.
- 등록·서버 실행·연결·대화 불일치, 미협상·잘못된 방향, boolean/소수/문자열 정수는 거절한다.

## 수명과 표시

입력 준비 → generating → 유효 최종 답변 수락 시 text_ready → 해당 요청 종료 시 idle이다. 첫 토큰·PCM은 최종 답변 수락이 아니다. TTS 준비·재생 중에는 text_ready를 유지하며 기본 processing/작업 gate/원장은 기존 완료 정책을 따른다. 상태에 본문·생각·설정 원문을 넣지 않는다.

현재 대화 내에서 의미가 바뀔 때만 revision을 증가시킨다. 같은 상태 재발행은 멱등이다. 대화 초기화 시 idle/revision 0으로 시작한다. revision 소진 시 되감거나 다른 상태를 같은 revision으로 보내지 말고 기능 오류로 전환한다.

## 조회와 지연 프레임

1. 현재 연결의 Ready·ExtensionsReady와 완성 대화 스냅샷을 확인한 뒤 한 번 조회한다. 대화 변경 시 새 동기화 뒤 다시 조회한다.
2. 최신 상태 후보는 현재 범위의 한 개만 보관한다. active는 기본 processing의 request_id와 일치할 때만 표시하고, idle도 기본 idle과 일치할 때만 확정한다. 기본 이벤트보다 먼저 온 후보는 이후 재평가한다.
3. 등록·epoch·연결·대화가 바뀌면 revision·후보·조회 기한을 초기화한다. 낮은 revision은 무시하고 같은 revision의 상충 내용은 오류다. 충돌은 더 높은 revision 또는 새 연결 조회로만 복구한다.
4. 조회 전송 후 5초 미응답이면 비치명 오류와 중립 `처리 중…`으로 복귀한다. 자동 재조회 루프는 만들지 않고 늦은 유효 이벤트로 회복할 수 있다.
5. `extension_error.feature=chat_progress_v1`은 이 기능만 오류로 처리한다. 기본 헤더의 비동기 해독·연결 종료 뒤 늦은 콜백은 현재 범위를 되돌리지 못한다.

text_ready는 생성·재생성 문구만 제거한다. 음성 상태와 보내기/수정/리롤의 기존 잠금은 유지한다. 구형 PC에는 `처리 중…`을 사용하며 구형 APK에는 진행 확장 프레임을 보내지 않는다.
