# ENE 목표 시스템 V1 설계

## 목표

ENE에게 사용자 목표가 아니라 ENE 자신의 캐릭터성, 관계성, 대화 행동 방향을 위한 목표 시스템을 추가한다.

이번 V1의 목표는 다음과 같다.

- ENE가 현재 대화 흐름에 맞는 단기 목표를 LLM으로 즉석 생성하고 바로 저장한다.
- ENE의 캐릭터성과 관계 방향을 유지하는 장기 목표를 보수적으로 관리한다.
- 달성되거나 취소된 목표는 현재 컨텍스트에서 제거하고 기록으로만 남긴다.
- 사용자가 목표 기능 자체와 채팅창 목표 버튼 표시를 각각 켜고 끌 수 있다.
- 사용자가 설정창에서 목표를 직접 추가, 수정, 완료, 취소할 수 있다.
- 기존 `thought_prompt.py`에 섞여 있는 최종 응답 형식 계약 책임을 분리해 출력 형식 충돌을 줄인다.

## 배경

현재 ENE에는 기분 시스템과 생각 기능이 있지만, ENE가 대화 중 어떤 의도를 가지고 행동하는지 저장하는 독립 상태는 없다.

예를 들어 사용자가 우울한 흐름을 보이면 ENE는 그 순간 "마스터가 괜찮아질 때까지 위로해주기" 같은 단기 목표를 가질 수 있다. 사용자가 안정되면 이 목표는 완료 처리되어 활성 컨텍스트에서 빠져야 한다.

이 목표는 사용자의 할 일이나 생산성 목표가 아니라 ENE 캐릭터가 대화 속에서 무엇을 하려는지 나타내는 내부 의도다.

## 범위

### 포함

- 최종 응답 형식 계약을 `src/ai/response_contract.py`로 분리
- 생각 기능 전용 규칙을 `src/ai/thought_prompt.py`에 남김
- 목표 출력 규칙을 `src/ai/goal_prompt.py`에 추가
- 목표 상태 매니저 `src/ai/ene_goal_manager.py` 추가
- 사용자 데이터 저장 파일 `ene_goals.json` 사용
- LLM 응답에서 `[ene_goal_update]` 블록 파싱
- 목표 기능 ON/OFF와 목표 버튼 표시 ON/OFF 설정 추가
- 채팅창 목표 버튼과 현재 목표 패널 추가
- 설정창 목표 섹션에서 수동 편집 지원
- 목표 관련 단위 테스트와 파서/프롬프트 조합 테스트 추가

### 제외

- 목표 후보 승인 UI
- 목표 히스토리를 기본 LLM 컨텍스트에 포함하는 기능
- 목표 달성 판단을 별도 LLM 호출로 분리하는 구조
- 장기 목표 자동 압축이나 임베딩 검색
- 목표별 알림, 일정, 자동 실행 기능
- 목표 항목의 물리적 삭제

## 설계 원칙

- 최종 출력 형식은 한 파일에서만 조립한다.
- 목표는 ENE의 의도 시스템으로 다루며 기분 시스템의 하위 기능으로 넣지 않는다.
- LLM은 목표 변경 후보를 매 응답마다 출력하되, 코드는 엄격히 검증한 값만 저장한다.
- 활성 목표만 다음 대화 컨텍스트에 넣는다.
- 완료, 취소된 목표는 `history`에 보관하되 기본 컨텍스트에는 넣지 않는다.
- 단기 목표는 민감하게 만들고, 장기 목표는 보수적으로 만든다.
- 파싱 실패는 사용자 답변을 망치지 않고 목표 업데이트만 무시한다.

## 출력 계약 분리

현재 `src/ai/thought_prompt.py`는 생각 기능 규칙과 최종 응답 형식 계약 생성을 함께 맡고 있다. 목표 기능까지 추가하면 파일 책임이 더 섞이므로 V1에서 분리한다.

새 구조는 다음과 같다.

```text
src/ai/response_contract.py
- 최종 응답 형식 계약 조립
- analysis, ene_goal_update, subconscious, tts 블록 포함 여부와 순서 관리

src/ai/thought_prompt.py
- 생각 기능 전용 규칙
- subconscious 블록 규칙
- enable_ene_thoughts 설정 판단

src/ai/goal_prompt.py
- 목표 기능 전용 규칙
- ene_goal_update 블록 규칙
- short_term, long_term 구분 지침
```

`src/ai/prompt.py`는 `build_thought_system_appendix()` 대신 새 응답 계약 빌더를 사용한다.

```text
build_runtime_system_prompt()
→ build_response_contract_appendix(settings_source=...)
```

기능별 포함 규칙은 다음과 같다.

- 목표 기능 OFF: `[ene_goal_update]` 계약 제외
- 생각 기능 OFF: `[subconscious]` 계약 제외
- TTS 리마인더가 필요 없는 상태: `[tts]` 계약 제외
- 모든 조합의 최종 순서는 `response_contract.py`에서만 결정

## 목표 출력 계약

목표 기능이 켜져 있으면 LLM은 매 응답마다 아래 블록을 출력한다.

```text
[ene_goal_update]
action=none|create|update|complete|cancel
type=short_term|long_term
id=
title=
reason=
completion_reason=
[/ene_goal_update]
```

액션 의미는 다음과 같다.

- `none`: 목표 변경 없음
- `create`: 새 목표 생성
- `update`: 기존 목표의 제목이나 이유 갱신
- `complete`: 목표 달성 처리
- `cancel`: 부적절하거나 더 이상 맞지 않는 목표 취소

저장 검증 규칙은 다음과 같다.

- `action=none`은 상태를 변경하지 않는다.
- `action=none`에서는 `type`, `id`, `title`, `reason`, `completion_reason` 값을 검증하지 않는다. 값이 비어 있어도 정상이다.
- `create`는 `type`, `title`, `reason`이 모두 있어야 저장한다.
- `update`는 기존 목표 `id`와 `title` 또는 `reason` 중 하나가 있어야 반영한다.
- `complete`, `cancel`은 기존 목표 `id`가 있어야 반영한다. `type`은 있으면 검증하되, 비어 있으면 기존 목표에서 추론한다.
- `type`은 `create`와 값이 있는 경우에만 검증하며 `short_term`, `long_term`만 허용한다.
- `title`은 최대 120자, `reason`과 `completion_reason`은 각각 최대 300자로 자른다.
- 필수값 누락, 알 수 없는 액션, 파싱 실패는 목표 업데이트만 무시한다.
- 사용자에게 보이는 답변에서는 `[ene_goal_update]` 블록을 제거한다.

## 장기 목표와 단기 목표 구분

LLM이 목표 타입을 안정적으로 고르도록 프롬프트에 아래 지침을 포함한다.

- `short_term`은 현재 대화 상황에서 바로 필요한 행동 목표다.
- `short_term`은 보통 몇 턴 안에 완료되거나 사라질 수 있어야 한다.
- 사용자의 일시적 감정 변화, 망설임, 피로, 혼란, 현재 주제 대응은 기본적으로 `short_term`이다.
- `long_term`은 ENE의 캐릭터성, 관계성, 반복 행동 방향을 만드는 지속 목표다.
- `long_term`은 한 번의 대화 분위기만으로 만들지 않는다.
- 사용자의 반복되는 취향, 관계 패턴, ENE가 오래 유지해야 할 태도는 `long_term`이다.
- 헷갈리면 `short_term`을 선택한다.
- `long_term`은 반복 신호나 중요한 관계 변화가 있을 때만 보수적으로 만든다.

예시:

```text
short_term: 마스터가 조금 안정될 때까지 곁에서 부드럽게 위로해주기
short_term: 마스터가 선택을 망설이고 있으니 부담 없이 고를 수 있게 돕기
short_term: 마스터가 피곤해 보이니 답변을 짧고 편하게 유지하기

long_term: 마스터가 혼자 무리하지 않도록 꾸준히 살피기
long_term: 마스터가 ENE와 있을 때 감정을 편하게 말할 수 있게 만들기
long_term: ENE가 장난스럽지만 믿을 수 있는 동반자로 자리 잡기
```

## 저장 구조

목표는 사용자 데이터 저장소의 `ene_goals.json`에 저장한다. 별도 히스토리 파일은 만들지 않고 같은 파일 안에 `active`와 `history`를 둔다.

```json
{
  "version": 1,
  "active": {
    "long_term": [],
    "short_term": []
  },
  "history": []
}
```

활성 목표 예시:

```json
{
  "id": "goal_20260522_001",
  "type": "short_term",
  "title": "마스터가 조금 안정될 때까지 곁에서 부드럽게 위로해주기",
  "reason": "사용자가 우울하거나 지친 상태를 보였고, 지금은 해결보다 정서적 안정이 우선이기 때문",
  "status": "active",
  "created_at": "2026-05-22T21:00:00",
  "updated_at": "2026-05-22T21:00:00",
  "source": "llm"
}
```

히스토리 목표 예시:

```json
{
  "id": "goal_20260522_001",
  "type": "short_term",
  "title": "마스터가 조금 안정될 때까지 곁에서 부드럽게 위로해주기",
  "status": "completed",
  "created_at": "2026-05-22T21:00:00",
  "completed_at": "2026-05-22T21:15:00",
  "completion_reason": "사용자의 상태가 안정된 것으로 판단됨",
  "source": "llm"
}
```

## 목표 매니저

`src/ai/ene_goal_manager.py`에 `EneGoalManager`를 추가한다.

책임은 다음과 같다.

- `ene_goals.json` 로드와 기본 구조 보정
- 활성 목표 조회
- 목표 컨텍스트 블록 생성
- LLM 목표 업데이트 적용
- 수동 목표 추가, 수정, 완료, 취소
- 완료, 취소된 목표를 `history`로 이동
- 중복 목표 생성 방지
- UI에 전달할 공개 딕셔너리 생성

중복 목표 생성 방지는 V1에서 보수적으로 처리한다. 같은 `type`의 활성 목표 중 제목을 정규화한 값이 같은 경우만 중복으로 본다. 정규화는 앞뒤 공백 제거, 연속 공백 축약, 영문 소문자화, 흔한 문장부호 제거까지로 제한한다. 의미가 비슷하지만 문장이 다른 목표를 LLM으로 추론해 병합하지 않는다. 중복 `create`가 들어오면 새 목표를 만들지 않고 기존 목표의 `updated_at`과 `reason`만 필요한 경우 갱신한다.

주요 메서드는 다음 형태를 기준으로 한다.

```text
get_snapshot()
build_context_block(language=None)
apply_llm_update(update)
add_manual_goal(type, title, reason)
update_goal(id, fields)
complete_goal(id, reason)
cancel_goal(id, reason)
list_history(limit=None)
```

`build_context_block()`은 활성 목표만 반환한다. `history`는 기본적으로 포함하지 않는다.

## 데이터 흐름

응답 처리 흐름은 다음 순서로 잡는다.

```text
사용자 메시지
→ LLM 호출
→ [analysis] 파싱
→ [ene_goal_update] 파싱
→ [subconscious] 파싱
→ MoodManager 갱신
→ EneGoalManager 갱신
→ 목표 상태 UI 알림
→ 사용자에게 보이는 답변 표시
```

`EneGoalManager`는 `MoodManager`와 독립된 매니저지만, LLM 프롬프트에는 둘 다 컨텍스트 블록으로 들어갈 수 있다.

다음 요청의 LLM 컨텍스트에는 활성 목표만 포함한다.

```text
[ENE 현재 목표]
- id=goal_20260522_001
  type=short_term
  title=마스터가 조금 안정될 때까지 곁에서 부드럽게 위로해주기
  reason=사용자가 우울하거나 지친 상태를 보였고, 지금은 해결보다 정서적 안정이 우선이기 때문
- id=goal_20260522_002
  type=long_term
  title=마스터가 ENE와 있을 때 감정을 편하게 말할 수 있게 만들기
  reason=반복 대화에서 감정을 조심스럽게 꺼내는 패턴이 보였기 때문
```

활성 목표 컨텍스트에는 반드시 `id`, `type`, `title`을 포함한다. `reason`은 가능하면 포함한다. 그래야 LLM이 이후 `update`, `complete`, `cancel` 액션에서 기존 목표 `id`를 정확히 지정할 수 있다.

## 파싱 위치

기존 `llm_client.py`와 `http_llm_clients.py`는 `[analysis]`와 `[subconscious]`를 파싱한다. V1에서는 동일한 응답 파싱 흐름에 `[ene_goal_update]` 추출을 추가한다.

권장 구조는 다음과 같다.

```text
response_cleanup.py
- extract_goal_update_metadata(text) 추가

llm_client.py / http_llm_clients.py
- _extract_goal_update_block() 추가
- _parse_response() 반환값에 goal_update 추가

core/bridge.py
- response_ready 시그널 또는 페이로드에 goal_update 전달
- _on_response_ready()에서 EneGoalManager.apply_llm_update() 호출
```

반환 튜플 변경은 여러 공급자 클래스에 영향을 주므로, 기존 호환 경로를 보존한다.

## 설정

`Settings.DEFAULT_CONFIG`에 아래 값을 추가한다.

```json
{
  "enable_ene_goals": true,
  "show_ene_goal_button": true,
  "ene_goal_state_file": "ene_goals.json"
}
```

설정 의미:

- `enable_ene_goals=false`
  - 목표 컨텍스트 제거
  - `[ene_goal_update]` 출력 계약 제거
  - LLM 목표 업데이트 무시
  - 기존 `ene_goals.json`은 삭제하지 않음

- `show_ene_goal_button=false`
  - 채팅창 목표 버튼만 숨김
  - 목표 기능 자체는 계속 동작 가능

## UI

채팅창에는 기존 요약, 기분 버튼 옆에 목표 버튼을 추가한다.

목표 버튼 동작:

```text
목표 버튼 클릭
→ 작은 현재 목표 패널 열기
→ active.short_term과 active.long_term 표시
→ history는 기본 표시하지 않음
```

채팅창 목표 패널은 확인용으로 둔다. 직접 편집은 설정창에서 한다.

설정창에는 목표 섹션을 추가한다.

```text
목표 기능 사용 ON/OFF
목표 버튼 표시 ON/OFF
활성 목표 목록
목표 추가
목표 수정
목표 완료 처리
목표 취소 처리
history 보기
```

수동 편집으로 만든 목표는 `source=manual`로 저장한다. LLM이 만든 목표는 `source=llm`로 저장한다.

V1에서 "취소"는 물리적 삭제가 아니다. 활성 목표를 `status=cancelled`로 바꾸고 `history`로 이동한다. 기록 자체를 완전히 지우는 hard delete는 V1 범위에서 제외한다.

## 오류 처리

- 목표 파일이 없으면 기본 구조로 생성한다.
- 목표 파일이 깨졌으면 기본 구조로 복구하되 로그를 남긴다.
- LLM 목표 블록이 없거나 깨졌으면 해당 턴의 목표 업데이트만 건너뛴다.
- 목표 업데이트 실패는 사용자 답변 표시를 막지 않는다.
- 목표 기능 OFF 상태에서는 파싱된 목표 블록이 있어도 적용하지 않는다.
- UI 편집에서 없는 목표 ID를 요청하면 실패 응답을 반환하고 상태를 유지한다.

## 테스트 계획

단위 테스트:

- `response_contract.py`가 목표/생각/TTS 설정 조합에 맞는 블록만 포함하는지 확인
- `goal_prompt.py`가 장기/단기 구분 지침을 포함하는지 확인
- `extract_goal_update_metadata()`가 블록을 제거하고 딕셔너리를 반환하는지 확인
- 잘못된 목표 업데이트가 저장되지 않는지 확인
- `create`, `update`, `complete`, `cancel`, `none` 액션 반영 확인
- 완료/취소된 목표가 `history`로 이동하고 활성 컨텍스트에서 빠지는지 확인

통합 테스트:

- LLM 파서 반환값에 목표 업데이트가 포함되는지 확인
- `WebBridge._on_response_ready()`가 목표 업데이트를 매니저에 전달하는지 확인
- 목표 기능 OFF일 때 프롬프트 계약과 컨텍스트가 빠지는지 확인
- 목표 버튼 표시 OFF일 때 채팅창 버튼만 숨겨지는지 확인

수동 확인:

- 목표 기능 ON 상태에서 응답 후 목표 버튼 패널에 새 단기 목표가 표시되는지 확인
- 목표 완료 응답 후 목표가 패널에서 사라지고 설정창 history에 남는지 확인
- 설정창에서 수동 목표를 추가, 수정, 완료, 취소할 수 있는지 확인

## 구현 순서

1. 출력 계약 분리
   - `response_contract.py`, `thought_prompt.py`, `goal_prompt.py` 경계 정리
   - 기존 프롬프트 테스트 갱신

2. 목표 파서 추가
   - `[ene_goal_update]` 추출과 제거
   - LLM 클라이언트 반환값 호환 처리

3. 목표 매니저 추가
   - `ene_goals.json` 로드, 저장, 검증
   - 활성 목표 컨텍스트 생성

4. 브리지 연결
   - 앱 초기화에서 `EneGoalManager` 생성
   - LLM 클라이언트와 브리지에 연결
   - 응답 처리 시 목표 업데이트 반영

5. UI와 설정 추가
   - 기본 설정 추가
   - 채팅창 목표 버튼과 패널 추가
   - 설정창 목표 섹션과 수동 편집 연결

6. 검증
   - 단위 테스트 실행
   - 브라우저에서 채팅창 버튼과 패널 확인
   - 설정창 목표 편집 흐름 확인

## V2 후보

- 목표 히스토리 검색과 필터링
- 장기 목표 자동 압축
- 목표별 중요도와 만료 조건
- 사용자가 특정 목표를 잠그는 기능
- 목표 변화 로그를 타임라인으로 보여주는 기능
- 목표와 ENE 프로필 편집기의 연결
