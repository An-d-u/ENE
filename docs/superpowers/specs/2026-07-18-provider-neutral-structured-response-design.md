# ENE 제공자 중립 구조화 응답 계약 설계

- 작성일: 2026-07-18
- 상태: 사용자 설계 승인 완료, 구현 계획 작성 전
- 범위: 최종 일반 대화 응답의 형식 강제, 검증, 제한 복구, 기존 태그 호환

## 1. 배경

ENE는 최종 LLM 응답 한 번에서 사용자에게 보일 답변과 감정, TTS, 일정, 기분 분석, 약속, 생각, 목표 업데이트, 선제 대화 예약, 제스처를 함께 받는다. 현재는 시스템 프롬프트가 태그 형식을 요청하고 정규식 파서가 이를 분리한다.

이 방식은 모델이 태그를 누락하거나 닫지 않으면 기능이 간헐적으로 사라질 수 있다. 특히 생각 기능이 활성화되어도 `[subconscious]` 블록이 비어 있거나 없으면 UI에 전달할 `thought`가 없어 버튼이 생성되지 않는다. 반대로 닫히지 않은 제어 블록은 사용자 화면에 노출될 위험이 있다.

일부 제공자는 JSON Schema 기반 구조화 출력을 지원하지만 제공자, API 형식, 모델, 엔드포인트마다 지원 수준이 다르다. 따라서 모든 제공자에 동일한 원시 요청을 보내는 대신, ENE 내부 계약은 하나로 유지하고 제공자별로 가능한 가장 강한 출력 방식을 선택해야 한다.

여기서 `thought`는 사용자에게 표시하기 위해 캐릭터가 생성한 짧은 내면 반응이다. 제공자의 비공개 추론 토큰이나 원시 chain-of-thought를 요청하거나 노출하는 기능이 아니다.

## 2. 목표

- 최종 일반 대화 응답을 하나의 제공자 중립 `ResponseEnvelopeV1`로 표현한다.
- 네이티브 구조화 출력을 지원하는 제공자와 모델에는 해당 기능을 사용한다.
- 네이티브 구조화를 지원하지 않는 모델도 기존 태그 계약으로 계속 사용할 수 있게 한다.
- 생각 기능이 활성화된 응답에서는 비어 있지 않은 `thought`를 검증하고, 누락 시 원래 답변을 바꾸지 않은 채 한 번만 제한 복구한다.
- TTS 언어가 답변 언어와 다를 때만 `tts_text`를 필수로 검증하고 제한 복구한다.
- 일정, 약속, 목표, 기분 분석, 선제 예약 같은 부작용 데이터는 검증이 끝난 뒤 정확히 한 번만 기존 소비부에 전달한다.
- 현재 `LLM_RESPONSE_TUPLE` 10개 값과 `bridge_workers` 이하의 소비 인터페이스를 유지한다.
- 응답 원문이나 실제 사용자 대화를 진단 로그와 테스트 fixture에 남기지 않는다.

## 3. 비목표

- 선제 대화 예약의 시간 계산, 최소 지연, 취소 정책 자체를 변경하지 않는다.
- 생각 버튼의 UI 디자인이나 배치 방식을 변경하지 않는다.
- 요약, 웹 검색 판단, 일기, 노트 계획 등 최종 일반 대화가 아닌 one-shot 출력 형식을 변경하지 않는다.
- 제공자의 비공개 reasoning token을 `thought` 또는 `analysis`로 사용하지 않는다.
- 스트리밍 구조화 출력을 새로 도입하지 않는다. 현재 비스트리밍 최종 응답 경로만 다룬다.
- V1에서 새 사용자용 설정 화면을 추가하지 않는다.
- 베타 API 엔드포인트로 자동 전환하지 않는다.

## 4. 확정한 접근

선택한 방식은 **공통 응답 계약 + API 형식별 어댑터 + 기존 태그 최종 폴백**이다.

중앙의 논리 계약과 검증기는 제공자와 무관하다. OpenAI Responses, OpenAI-compatible, Gemini, Anthropic, Ollama 어댑터가 각 API의 요청 인코딩과 응답 추출 차이를 흡수한다. OpenRouter와 DeepSeek는 같은 OpenAI-compatible wire format을 사용하더라도 서로 다른 지원 능력 정책을 갖는다. Custom API는 사용자가 고른 wire format의 어댑터를 재사용한다.

구조화 경로와 태그 경로는 같은 의미 규칙을 사용하지만 출력 형식 지침을 동시에 사용하지 않는다. 구조화 요청에는 JSON Schema와 의미 규칙만 넣고, 태그 요청에는 현재 태그 형식 부록과 의미 규칙을 넣는다.

## 5. 공통 데이터 계약

### 5.1 최상위 필드

`ResponseEnvelopeV1`은 현재 파서의 반환 순서와 일대일 대응한다.

| 필드 | JSON 타입 | 비활성·없음 표현 | 기존 반환값 |
|---|---|---|---|
| `reply` | string | 허용하지 않음 | 0: 표시 답변 |
| `emotion` | string | `"normal"` | 1: 감정 |
| `tts_text` | string | `""` | 2: TTS 텍스트 또는 `None` |
| `events` | array<object> | `[]` | 3: 일정 후보 |
| `analysis` | object | 모든 값이 빈 문자열인 객체 | 4: 분석 딕셔너리 |
| `promises` | array<object> | `[]` | 5: 약속 후보 |
| `thought` | string | `""` | 6: 표시용 생각 |
| `goal_update` | object | `action="none"`과 나머지 빈 문자열 | 7: 목표 업데이트 |
| `proactive_conversations` | array<object> | `[]` | 8: 선제 대화 예약 후보 |
| `gesture` | string | `""` | 9: 제스처 |

제공자 교집합을 유지하기 위해 최상위 10개 키는 모두 `required`로 두고, 모든 object에는 `additionalProperties: false`를 사용한다. `null`, `oneOf`, 조건부 스키마, `pattern`, `minLength`처럼 제공자별 차이가 큰 제약은 공통 스키마에 사용하지 않는다. 내용 필수 여부와 조건부 필드 규칙은 로컬 도메인 검증기가 담당한다.

스키마 버전은 요청과 capability cache에서 사용하는 내부 상수이며 모델 출력 필드로 추가하지 않는다.

### 5.2 하위 객체

strict schema의 교집합을 위해 하위 객체도 선언한 모든 키를 `required`로 두고 사용하지 않는 값은 빈 문자열로 표현한다. 디코더는 검증 후 빈 값만 가진 메타데이터를 기존 소비부가 기대하는 `{}` 또는 `[]`로 정규화한다.

- `events[]`: `date`, `title`, `description`
- `analysis`: `user_emotion`, `user_intent`, `interaction_effect`, `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`, `confidence`, `flags`
- `promises[]`: `trigger_at`, `title`, `source`, `source_excerpt`
- `goal_update`: `action`, `type`, `id`, `title`, `reason`, `completion_reason`
- `proactive_conversations[]`: `trigger_at`, `title`, `generation_prompt`, `source_excerpt`, `reason`, `cooldown_key`

`goal_update.action`은 `none`, `create`, `update`, `complete`, `cancel` 중 하나다. `type`은 빈 문자열, `short_term`, `long_term` 중 하나다. 동작별 필수값은 로컬 검증기가 검사한다.

`proactive_conversations`는 현재 동작과 동일하게 최대 한 항목만 허용한다. `gesture`는 빈 문자열 또는 `nod`, `bow`, `shake`, `surprise`, `tilt`, `sway`만 허용한다. `emotion`은 런타임에서 사용할 수 있는 감정 목록으로 검증하고 잘못된 값은 `normal`로 정규화한다.

### 5.3 기능별 요구사항

매 최종 대화 요청은 설정을 읽어 `ResponseRequirements`를 만든다.

- `reply`: 항상 비어 있지 않아야 한다.
- `thought`: 생각 기능이 활성화된 경우 비어 있지 않아야 한다. 비활성화된 경우 디코더가 빈 문자열로 강제한다.
- `tts_text`: TTS 언어와 답변 언어가 다를 때만 비어 있지 않아야 한다. 언어가 같으면 모델 값을 사용하지 않고 `reply`를 기존 TTS 경로에 전달한다.
- `analysis`, `events`, `promises`, `goal_update`, `proactive_conversations`, `gesture`: 각 기능이 비활성화되면 빈 값으로 강제한다. 활성화되어도 실제 행동이 없을 수 있다.
- 부작용 객체는 현재 관리자 규칙에 맞는 필수값을 갖춘 경우에만 유효하다.

## 6. 구성 요소와 책임

### 6.1 응답 요구사항 생성기

현재 설정에서 다음 값을 한 번 읽어 불변 요청 컨텍스트로 만든다.

- 최종 대화 여부
- 응답 언어와 TTS 언어
- 생각, 분석, 목표, 선제 대화, 제스처, 일정 인식, 약속 인식 활성화 여부
- 현재 허용 감정과 선제 대화 cooldown key

제공자 요청, 도메인 검증, 복구 요청이 모두 같은 요구사항 스냅샷을 사용한다. 호출 도중 설정이 바뀌어도 한 턴 안에서 계약이 달라지지 않는다.

### 6.2 계약 생성기

현재 `response_contract.py`의 의미 규칙과 태그 예시를 다음 책임으로 분리한다.

- 제공자 중립 의미 규칙
- 고정 `ResponseEnvelopeV1` JSON Schema
- 기존 태그 형식 부록
- 생각/TTS 누락 복구용 축소 계약

JSON Schema의 구조는 고정해 제공자 측 스키마 컴파일 캐시를 재사용한다. 기능 활성화 여부와 언어별 의미 규칙은 시스템 프롬프트와 로컬 `ResponseRequirements`로 처리한다.

### 6.3 지원 능력 판별기

응답 방식 우선순위는 다음과 같다.

1. `json_schema`
2. `strict_tool`
3. `json_object`
4. `legacy_tags`

capability key는 `(provider, wire_format, endpoint_fingerprint, model, schema_version)`이다. 엔드포인트 원문은 저장하지 않고 process-local fingerprint만 사용한다. 캐시는 프로세스 메모리에만 두며 실제 대화를 probe 요청으로 보내지 않는다.

알려진 공식 제공자는 어댑터의 보수적인 기본 capability로 시작한다. API가 생성 시작 전에 명시적인 unsupported/unknown parameter 오류를 반환한 경우에만 해당 key를 `legacy_tags`로 낮추고 같은 턴을 한 번 다시 요청한다. 429, timeout, 5xx, 안전 거절, 출력 길이 초과, 모델이 만든 잘못된 JSON은 미지원 증거로 사용하지 않는다.

내부 설정 `structured_response_mode`는 `auto`와 `legacy`만 제공한다. 기본은 `auto`이고, `legacy`는 네이티브 구조화만 끄는 긴급 전환 수단이다. V1에는 이 설정을 위한 새 UI를 만들지 않는다.

임의 Custom API의 지원 능력은 안전하게 추론할 수 없으므로 `auto`에서 기본 `legacy_tags`를 사용한다. 이미 공식 어댑터로 식별할 수 있는 알려진 endpoint profile만 해당 네이티브 경로를 사용할 수 있다. 이 제한은 호환성을 우선하며, Custom API의 명시적 네이티브 opt-in UI는 V1 범위 밖이다.

### 6.4 API 형식별 어댑터

각 어댑터는 다음 인터페이스 책임을 갖는다.

- 선택한 응답 방식에 맞게 기존 요청 payload에 구조화 설정을 추가한다.
- 텍스트, JSON 문자열, tool/function arguments, refusal을 제공자 응답에서 추출한다.
- `finish_reason`, `stop_reason`, status, 후보 부재, 출력 절단을 공통 종료 상태로 변환한다.
- 명시적 구조화 미지원 오류만 분류한다.
- 요청 본문이나 응답 원문을 로그에 남기지 않는다.

어댑터는 제공자 클라이언트의 인증, 이미지 변환, 메모리 구성, 웹 검색 문맥 조합을 소유하지 않는다. 기존 클라이언트가 만든 요청에 응답 계약만 적용한다.

### 6.5 envelope 디코더와 검증기

디코더는 다음 순서를 지킨다.

1. 제공자 종료 상태 확인
2. 구조화 carrier 추출
3. JSON 문법과 고정 스키마 검증
4. `present_fields` 기록
5. `ResponseRequirements` 기반 도메인 검증
6. 비활성 필드 제거와 기존 자료형 정규화
7. 기존 10개 `LLM_RESPONSE_TUPLE`로 변환

태그 경로는 기존 `parse_llm_response`를 호출한 뒤 같은 도메인 검증과 정규화를 거친다. 닫히지 않은 thought/TTS/analysis/goal/proactive 제어 블록은 사용자에게 보이는 `reply`에서 제거하고 해당 메타데이터를 누락으로 취급한다.

### 6.6 턴 사용량 누산기

기본 호출, 미지원 하향 호출, 전체 재생성, 제한 복구의 input/output/total token을 한 턴 단위로 합산한다. 개별 호출에는 응답 방식과 실패 이유 코드만 연결하고 원문은 저장하지 않는다. 기존 `get_last_token_usage()`는 최종 합산값을 반환해야 한다.

## 7. 제공자별 정책

| 제공자·형식 | V1 우선 경로 | 폴백과 제한 |
|---|---|---|
| OpenAI Responses | `text.format`의 strict JSON Schema | refusal과 incomplete status를 먼저 처리하고, 명시적 미지원만 태그로 하향 |
| Gemini | SDK의 JSON MIME type과 response JSON schema | 채팅 세션 config에 계약이 포함되므로 mode 또는 schema signature 변경 시 세션 재생성 |
| Anthropic Messages | `output_config.format` JSON Schema | `refusal`과 `max_tokens` 종료를 정상 JSON으로 취급하지 않음 |
| OpenRouter Chat Completions | strict `response_format.json_schema` | `provider.require_parameters=true`로 실제 라우팅 제공자의 지원을 요구하고, 지원 route 부재 시 태그로 하향 |
| DeepSeek Chat Completions | 안정 API의 `json_object` | 키와 타입은 로컬 검증. strict tool은 사용자가 이미 beta endpoint를 명시한 profile에서만 사용하며 자동 endpoint 변경 금지 |
| 로컬 Ollama | `/api/chat`의 schema object `format` | `message.content` JSON을 다시 검증. structured output 미지원 Ollama Cloud는 태그 사용 |
| Custom API | 선택 wire format의 어댑터 | 알 수 없는 endpoint는 `auto`에서도 태그 사용. 알려진 profile만 네이티브 사용 |

OpenAI-compatible이라는 이유만으로 OpenRouter, DeepSeek, 임의 Custom API를 같은 capability로 간주하지 않는다.

## 8. 정상 데이터 흐름

1. 대화 호출이 `ResponseRequirements`를 만든다.
2. capability resolver가 가장 강한 지원 방식을 고른다.
3. 계약 생성기가 의미 규칙과 해당 출력 계약을 만든다.
4. 기존 클라이언트가 메모리, 이미지, 사용자 입력과 함께 요청을 한 번 전송한다.
5. 어댑터가 종료 상태와 응답 carrier를 추출한다.
6. envelope 디코더가 구조와 도메인 규칙을 검증한다.
7. 필요한 경우에만 생각/TTS 제한 복구를 한 번 수행한다.
8. 최종 envelope를 기존 10개 튜플로 변환한다.
9. `bridge_workers`와 `chat_flow`가 기존 순서로 UI, TTS, 목표, 일정, 약속, 기분, 선제 대화 소비부에 전달한다.
10. 검증이 완료된 envelope는 한 번만 emit한다. 재요청 또는 복구 중에는 어떤 부작용도 적용하지 않는다.

## 9. 히스토리 정책

제공자가 반환한 JSON envelope, tool call, 태그 원문은 다음 대화의 assistant history로 보존하지 않는다. 검증 후 사용자에게 실제 표시한 `reply`만 저장한다.

HTTP 클라이언트는 `_assistant_history_content_for_response`에서 정규화된 `reply`를 사용한다. Gemini SDK 채팅 세션도 직전 assistant history를 같은 `reply`로 교체하거나 정규화된 visible conversation으로 재구성한다. 기존 브릿지의 visible conversation 기반 history refresh와 같은 의미를 유지한다.

이 정책은 다음을 방지한다.

- 생각과 제어 메타데이터의 불필요한 재전송
- JSON과 태그 형식이 혼합된 후속 프롬프트
- 이전 예약 또는 목표 지시가 다음 응답에서 다시 생성되는 현상
- 구조화 형식 자체가 대화 문체에 섞이는 현상

## 10. 실패 처리

### 10.1 기능별 처리 표

| 실패 | 처리 |
|---|---|
| 구조화 파라미터 명시적 미지원 | capability를 태그로 낮추고 같은 턴을 1회 재요청 |
| 유효한 `reply`, 활성 thought 누락 | 원래 `reply`를 보존하고 thought만 제한 복구 |
| 유효한 `reply`, 필수 번역 TTS 누락 | 같은 제한 복구에서 `tts_text`만 요청 |
| 동일 언어 TTS 누락 | 원격 복구 없이 `reply`를 TTS 값으로 사용 |
| 감정 또는 제스처 오류 | 각각 `normal`, 빈 문자열로 로컬 보정 |
| analysis, event, promise, goal, proactive 오류 | 잘못된 항목만 폐기하고 부작용 실행 안 함 |
| `reply` 부재, JSON 절단·파손 | 안전 거절이 아니면 같은 구조화 방식으로 전체 응답 1회 재생성 |
| 안전 거절·콘텐츠 필터 | 복구와 태그 하향 없이 제공자 거절 또는 기존 안전 안내 표시 |
| 429, timeout, 5xx | 기존 전송 오류 정책만 사용하고 capability를 변경하지 않음 |

출력 길이 초과로 전체 재생성할 때는 제공자가 허용하는 범위에서 출력 예산을 늘리되, 부작용은 재생성된 최종 envelope에만 적용한다. 두 번째 전체 응답도 유효하지 않으면 기존 빈 응답·오류 처리로 종료한다.

### 10.2 제한 복구

제한 복구는 다음 규칙을 모두 만족해야 한다.

- 한 턴에 최대 한 번 수행한다.
- thought와 번역 TTS가 함께 누락되면 한 호출로 함께 요청한다.
- 같은 제공자와 모델을 사용하되 전체 history, 메모리, 이미지, 프로필은 보내지 않는다.
- 입력은 검증된 원래 `reply`, 필요한 출력 언어, 누락된 필드 이름과 축소 계약뿐이다.
- 네이티브 경로는 누락 필드만 가진 작은 schema를 사용한다.
- 태그 경로는 thought/TTS 전용 최소 태그 계약을 사용한다.
- 원래 primary `reply`는 정규화가 끝난 문자열 그대로 유지한다. 복구 응답이 반환한 reply나 다른 필드는 사용하지 않는다.
- allowlist에 든 누락 필드만 병합한다. analysis, event, promise, goal, proactive, emotion, gesture는 원격 복구하지 않는다.
- 짧은 전용 timeout 안에 실패하면 정상 reply를 표시하고 해당 부가기능만 생략한다.

### 10.3 태그 안전 정리

기존 태그 호환 파서는 완전히 닫힌 유효 블록만 메타데이터로 채택한다. 닫히지 않은 reserved control block은 시작 태그부터 응답 끝까지 화면과 TTS에서 제거한다. 적용 대상은 thought alias, `tts`, `analysis`, `ene_goal_update`, `proactive_conversation`이다.

예약·목표·분석 블록 안의 텍스트를 표시 답변으로 승격하지 않는다. thought 블록만 있고 표시 답변이 없는 경우도 유효한 reply로 간주하지 않는다.

## 11. 부작용 경계

검증기와 복구기는 데이터를 만들거나 저장하지 않는다. 최종 envelope를 기존 10개 튜플로 변환한 뒤 브릿지가 현재 관리자에 전달한다.

- 일정: `date`와 `title`이 유효한 항목만 전달
- 약속: `trigger_at`과 `title`이 유효한 항목만 전달
- 목표: action별 필수값을 충족한 update만 전달, 아니면 `action=none`
- 분석: 허용 key의 비어 있지 않은 문자열만 전달
- 선제 대화: `trigger_at`, `title`, `generation_prompt`와 허용 cooldown key를 갖춘 최대 한 항목만 전달

재요청과 복구가 모두 끝나기 전에 bridge signal을 emit하지 않으므로 같은 턴의 후보가 중복 저장되지 않는다. 기존 manager의 중복 방지와 리롤 추적 동작은 유지한다.

## 12. 로깅과 개인정보

허용 로그:

- provider와 모델 식별자
- 선택한 response mode
- schema version
- 종료 상태와 오류 분류 코드
- 누락 또는 잘못된 필드 경로
- primary/retry/repair 호출 횟수와 합산 토큰 사용량
- 원문을 포함하지 않는 process-local fingerprint와 길이

금지 로그:

- 실제 user message와 assistant reply
- thought, analysis, TTS, 목표, 일정, 약속, 선제 대화 내용
- 전체 요청 payload와 전체 응답 JSON/tool arguments
- 메모리, 프로필, 첨부 이미지 내용

테스트와 문서 예시는 실제 대화가 아닌 완전히 합성한 중립 데이터만 사용한다. 런타임 설정 파일과 API 키 파일은 커밋하지 않는다.

## 13. 테스트 전략

### 13.1 계약 단위 테스트

- 유효한 envelope를 기존 10개 튜플로 정확히 변환한다.
- 모든 object가 extra key를 거부한다.
- 활성 thought와 번역 TTS의 내용 필수 조건을 검증한다.
- 비활성 기능을 빈 값으로 정규화한다.
- goal action별 필수값과 proactive 최대 한 항목을 검증한다.
- 감정과 제스처의 잘못된 값을 안전한 기본값으로 바꾼다.
- 닫히지 않은 제어 블록이 reply와 TTS에 남지 않는다.

### 13.2 어댑터 단위 테스트

각 공식 제공자와 Custom API wire format에 대해 다음을 mock 경계에서 검증한다.

- final reply 요청에만 올바른 네이티브 payload가 추가된다.
- one-shot, summary, decision, markdown 생성에는 ENE envelope가 적용되지 않는다.
- JSON text, function/tool arguments, refusal, 후보 부재, length 종료를 정확히 추출한다.
- OpenAI Responses의 완료 status를 올바르게 직렬화하고 해석한다.
- OpenRouter native 요청은 parameter-support routing을 요구한다.
- Gemini mode/schema 변경이 chat session signature에 반영된다.
- Ollama Cloud와 알려지지 않은 Custom API는 태그 경로를 사용한다.

### 13.3 capability와 오류 테스트

- 명시적인 unsupported parameter만 태그 하향과 cache 갱신을 유발한다.
- 429, timeout, 5xx, refusal, malformed output은 capability를 바꾸지 않는다.
- 같은 capability key는 명시적 미지원 뒤 반복 probe하지 않는다.
- endpoint 원문과 실제 대화가 capability cache 또는 로그에 들어가지 않는다.

### 13.4 복구 테스트

- primary reply가 제한 복구 전후 동일하다.
- thought/TTS 동시 누락도 복구 호출은 한 번뿐이다.
- 복구 요청에는 history, 메모리, 이미지, 프로필이 없다.
- 복구 응답의 추가 action 필드는 무시한다.
- 제한 timeout 또는 재검증 실패 시 reply를 반환하고 누락 기능만 비운다.
- primary, 전체 재생성, 복구 사용량을 정확히 합산한다.

### 13.5 통합·회귀 테스트

- `AIWorker`의 10개 응답 정규화와 signal 시그니처를 유지한다.
- 유효한 thought가 `message_received`를 통해 기존 생각 버튼 생성 경로에 전달된다.
- 태그 전용 모델의 thought도 같은 경로로 전달된다.
- 유효한 부작용 후보만 정확히 한 번 관리자에 전달된다.
- 리롤, 이미지 대화, 메모리 대화, context reset, visible history rebuild가 유지된다.
- 기존 전체 테스트와 신규 테스트가 모두 통과한다.

실제 API smoke test는 자동 테스트의 필수 조건으로 두지 않는다. 사용자가 명시적으로 실행할 때만 개인 데이터가 없는 합성 입력으로 제공자별 한 번씩 확인한다.

## 14. 출시와 호환성

- 기본 모드는 `auto`다.
- 알려진 네이티브 지원 경로는 구조화 출력을 우선 사용한다.
- 명시적 미지원 조합은 process-local cache에서 태그로 하향한다.
- 내부 `legacy` 전환은 모든 네이티브 구조화를 끄고 기존 태그 계약을 사용한다.
- 기존 태그 parser와 10개 tuple 인터페이스를 제거하지 않는다.
- 새로운 UI 설정은 추가하지 않는다.

## 15. 완료 기준

- 생각 기능 활성화 상태에서 primary thought 누락 시 정확히 한 번 제한 복구가 실행된다.
- 복구 성공 시 비어 있지 않은 thought가 기존 UI 버튼 경로에 전달된다.
- 복구 실패 시 원래 reply가 표시되고 thought만 생략된다.
- 닫히지 않은 thought 제어 블록이 사용자에게 노출되지 않는다.
- 번역 TTS만 내용 필수로 검증되고 동일 언어 TTS는 reply를 재사용한다.
- 네이티브 지원 모델은 제공자별 구조화 경로를 사용한다.
- 네이티브 미지원 모델은 기존 태그 방식으로 계속 대화할 수 있다.
- 구조화 미지원과 일시적 API 오류가 구분된다.
- goal, event, promise, analysis, proactive 데이터는 검증된 최종 응답에서만 한 번 적용된다.
- 후속 history에는 JSON, tool call, 태그 원문 대신 표시 reply만 남는다.
- 원문이 진단 로그와 테스트 fixture에 포함되지 않는다.
- 전체 자동 테스트가 통과한다.

## 16. 공식 문서 참고

- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- Anthropic Structured Outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Gemini Structured Outputs: https://ai.google.dev/gemini-api/docs/structured-output
- OpenRouter Structured Outputs: https://openrouter.ai/docs/guides/features/structured-outputs
- DeepSeek JSON Output: https://api-docs.deepseek.com/guides/json_mode/
- DeepSeek Tool Calls: https://api-docs.deepseek.com/guides/tool_calls/
- Ollama Structured Outputs: https://docs.ollama.com/capabilities/structured-outputs
