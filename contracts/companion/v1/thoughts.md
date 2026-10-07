# 메시지 생각 보기 확장

기본 텍스트 계약과 독립된 `message_thoughts_v1` capability다. 인증된 WSS에서 양쪽이 협상한 경우에만 사용한다. 기존 `PublicMessage`와 snapshot/event에는 생각을 추가하지 않는다.

## 허용 정보와 경계

현재 공개 기록에 있는 assistant 메시지 ID와 PC 표시 메시지가 일치할 때, PC의 생각 보기에서 표시하는 `thought` 문자열만 반환한다. local_only 메시지·사용자 메시지·내부 사고 컨텍스트·프롬프트·기억·감정 분석·첨부 원본은 제공하지 않는다. PC 설정 미리보기까지 포함한 실제 표시 활성값을 따른다. 기본 계약의 thought 비공개 규칙에 대한 예외는 이 명시적인 확장 응답뿐이다.

내용은 UTF-8 기준 8,192바이트 이하이며 잘라내지 않는다. 상한 초과는 PC 확인 안내로 표시한다. 응답 최악의 JSON 이스케이프 크기도 64KiB 프레임 이내다. 생각은 TTS 입력으로 사용하지 않으며 휴대폰 파일·로그·진단 문자열에 저장하지 않는다.

## 메시지

모든 메시지에는 `type`, `protocol_version: 1`, `registration_generation`(양의 정수), `server_epoch`·`connection_generation`·`conversation_id`(UUID)가 필요하다.

- `thought_request` (휴대폰→PC): `query_id`, `message_id`(UUID), `conversation_revision`(0 이상의 정수). 2KiB 상한.
- `thought_response` (PC→휴대폰): 요청의 query/message/revision을 그대로 돌려주고 `status`와 `text`를 추가. status는 `available`, `empty`, `stale`, `too_large`. available만 공백 아닌 text를 포함하며 나머지는 반드시 빈 문자열이다. 64KiB 상한.
- `thought_invalidated` (PC→휴대폰): 추가 필드 없음. PC 표시 갱신·표시 설정 변경 시 현재 생각 조회 결과를 비운다. 2KiB 상한.

PC는 revision이 현재와 다르면 `stale`, 공개 대상이 아니거나 표시가 꺼졌거나 내용이 없으면 `empty`, 상한 초과면 `too_large`를 반환한다. 서버 세션은 기존 협상·연결·방향·전송률 검사를 적용한다.

## 휴대폰 수명과 표시

화면에 보이는 ID 최대32개만 메모리에 보관한다. 공개 assistant만 조회하고 동시에 한 요청, 최소100ms 간격, 10초 응답 제한을 적용한다. 실패는 자동 무한 재시도하지 않고 해당 답변에 재시도 버튼을 제공한다. 스크롤로 화면을 벗어난 내용은 버리고 돌아오면 다시 조회한다.

연결·대화·revision·query ID·message ID가 모두 일치해야 응답을 적용한다. 답변 교체, 재동기화, PC 설정 변경 알림, 연결 종료 때 기존 내용과 대기 요청을 폐기한다. 갱신된 생각은 접힌 상태다. 과거 답변에서도 내용이 있는 경우 생각 보기/접기를 사용하며 마지막 쌍의 수정·리롤과 독립적이다.

구버전 PC/APK는 확장을 협상하지 않으므로 기존 채팅을 유지하고 생각 버튼을 표시하지 않는다. PC와 APK를 모두 이 확장 지원 버전으로 업데이트해야 한다.
