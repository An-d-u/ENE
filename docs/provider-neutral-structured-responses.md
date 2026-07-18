# 제공자 중립 구조화 응답 운영 가이드

이 문서는 ENE의 일반 대화 응답에서 생각, TTS, 감정, 일정, 약속, 목표, 선제 대화 같은 부가 필드를 안정적으로 전달하는 V1 운영 정책을 설명한다. 요약, 판단, 마크다운 생성처럼 일반 대화가 아닌 one-shot 출력에는 이 계약을 적용하지 않는다.

## 응답 모드 설정

내부 설정 `structured_response_mode`는 다음 두 값만 사용한다. V1에는 별도 선택 UI가 없다.

| 값 | 의미 |
|---|---|
| `auto` | 기본값. 제공자·형식·공식 endpoint에 맞는 가장 강한 지원 모드를 선택하고, 명시적인 미지원이 확인될 때만 해당 조합을 기존 태그 방식으로 낮춘다. 사전 probe 요청은 보내지 않는다. |
| `legacy` | 긴급 호환 모드. 네이티브 구조화를 모두 끄고 기존 태그 계약과 파서를 사용한다. 구조화 파라미터와 특정 모델의 호환 문제가 의심될 때 임시로 사용한다. |

`legacy`는 기존 모델을 계속 사용할 수 있게 하는 안전장치이지 장기 기본값이 아니다. 문제를 재현할 수 있으면 먼저 `auto`의 진단 결과를 확인하고, 서비스 복구가 급할 때만 `legacy`로 전환한다.

## 제공자별 V1 우선 모드

| 제공자·형식 | `auto`의 우선 모드 | 운영 메모 |
|---|---|---|
| OpenAI Responses | `json_schema` | `text.format`의 strict JSON Schema를 사용한다. refusal과 incomplete 상태는 구조화 미지원과 구분한다. |
| OpenAI Chat Completions 공식 endpoint | `json_schema` | strict `response_format.json_schema`를 사용한다. |
| Gemini | `json_schema` | JSON MIME type과 response JSON schema를 채팅 설정에 포함한다. mode 또는 schema signature가 바뀌면 세션을 다시 만든다. |
| Anthropic Messages | `json_schema` | `output_config.format`을 사용한다. refusal과 `max_tokens` 종료는 정상 JSON으로 채택하지 않는다. |
| OpenRouter Chat Completions | `json_schema` | `provider.require_parameters=true`로 실제 라우팅 제공자의 파라미터 지원을 요구한다. 지원 route가 없다는 명시적 응답만 태그로 하향한다. |
| DeepSeek 안정 API | `json_object` | JSON object 생성을 요청하고 키와 타입은 ENE가 검증한다. |
| 사용자가 명시한 DeepSeek beta endpoint | `strict_tool` | runtime은 strict tool을 지원한다. endpoint를 beta로 자동 변경하지 않는다. |
| 로컬 Ollama의 정확한 `/api/chat` | `json_schema` | schema object를 `format`으로 보내고 `message.content`를 다시 검증한다. loopback endpoint만 자동 인식한다. |
| Ollama Cloud | `legacy_tags` | V1에서는 네이티브 capability를 자동 가정하지 않는다. |
| 임의 Custom API | `legacy_tags` | `openai_chat`, `openai_responses`, `anthropic`, `mistral`, `google_cloud`, `cohere`, `ollama` wire format 모두 기본 태그 방식이다. |
| 공식 endpoint로 정확히 식별된 Custom API | 해당 named provider의 모드 | scheme, host, port, path가 공식 profile과 정확히 맞을 때만 네이티브 어댑터를 재사용한다. |

OpenAI-compatible 형식이라는 이유만으로 OpenRouter, DeepSeek, 임의 Custom API를 같은 capability로 취급하지 않는다. capability는 제공자, wire format, endpoint의 원문 없는 fingerprint, 모델, schema version 조합별로 분리한다.

## 명시적 미지원과 일시 오류

구조화 모드를 낮추는 근거는 API가 생성 시작 전에 반환한 명시적인 unsupported 또는 unknown parameter 오류뿐이다. ENE가 인식하는 해당 400·404·422 응답이면 그 조합을 프로세스 메모리에서 `legacy_tags`로 기록하고 같은 턴을 한 번 다시 요청한다.

다음 상황은 구조화 미지원의 증거가 아니므로 capability를 바꾸지 않는다.

- 429 rate limit
- timeout 또는 연결 오류
- 5xx 제공자 장애
- 안전 정책에 따른 refusal 또는 content filter
- 출력 길이 초과나 잘린 응답
- 모델이 만든 잘못된 JSON, 잘못된 필드 타입, 빈 응답

잘못된 JSON이나 유효한 `reply` 부재는 같은 모드에서 전체 응답을 최대 한 번 재생성한다. 두 번째 응답도 유효하지 않으면 기존 오류 처리로 종료하며, 이를 이유로 capability를 영구 하향하지 않는다. process-local 하향 기록은 애플리케이션을 다시 시작하면 초기화된다.

## thought와 TTS 제한 복구

유효한 표시 답변이 있지만 활성화된 `thought` 또는 번역 TTS가 누락된 경우, ENE는 원래 답변을 바꾸지 않고 누락 필드만 한 번 복구한다.

- 복구 입력에는 검증된 원래 `reply`, 응답 언어, TTS 언어, 누락 필드와 축소 계약만 포함한다.
- 대화 history, 메모리, 이미지, 프로필은 복구 요청에 다시 보내지 않는다.
- thought와 번역 TTS가 함께 누락되면 한 요청에서 함께 복구한다.
- 복구 응답의 `reply`, 감정, 일정, 약속, 목표, 분석, 선제 대화, 제스처는 병합하지 않는다.
- 같은 언어 TTS는 별도 복구 없이 원래 `reply`를 읽을 텍스트로 사용한다.
- 복구가 timeout, 거절, 잘못된 형식 등으로 실패해도 원래 `reply`는 표시한다. 실패한 `thought` 또는 번역 TTS만 빈 값으로 남긴다.
- 재생성이나 복구 중에는 UI 신호와 일정·약속·목표 같은 부작용을 실행하지 않는다. 최종 검증된 결과만 한 번 전달한다.

`thought`는 사용자에게 생각 버튼으로 보여 줄 수 있는 짧고 공개 가능한 캐릭터 반응이다. 제공자의 비공개 reasoning token, raw chain-of-thought, 단계별 숨은 추론을 요청하거나 노출하는 필드가 아니다.

기존 태그 전용 모델도 동일한 10개 응답 tuple과 UI 경로를 사용한다. 닫히지 않은 thought, TTS, 분석, 목표, 선제 대화 제어 블록은 표시 답변과 TTS에서 제거하며, 블록 안의 텍스트를 일반 답변으로 승격하지 않는다.

## 내용 없는 진단 항목

현재 final reply 경로의 로그에서 직접 확인할 수 있는 항목은 다음과 같다.

- 선택된 response mode, schema version, `repair_performed`
- 요청 메시지, 표시 답변, TTS, thought의 문자 수
- 일정, 분석, 약속, 목표, 선제 대화 항목 수
- 제공자가 사용량을 반환한 경우 합산 input, output, total token 수
- 일부 실패 경로의 고정된 category와 예외 클래스 이름

현재 로그는 모든 제공자에 대해 provider·model 범주, endpoint fingerprint, 구조화 미지원의 세부 코드, 누락 필드 이름, primary·downgrade·regeneration·repair별 호출 횟수를 공통으로 노출하지 않는다. 최종 mode가 `legacy_tags`라는 사실만으로 기본 태그 정책, 명시적 미지원 하향, process-local cache 중 어느 원인인지 구분할 수도 없다.

다음 내용은 로그에 남기지 않는다.

- 실제 사용자 메시지와 assistant 답변
- thought, TTS, 분석, 일정, 약속, 목표, 선제 대화 내용
- 전체 요청 payload, 응답 JSON, tool arguments
- 메모리, 프로필, 이미지 내용
- endpoint 원문, query string, API key

## 문제 해결 순서

1. `structured_response_mode`가 `auto`인지 설정에서 확인한다. 긴급 `legacy`가 남아 있으면 네이티브 구조화가 사용되지 않는다.
2. final reply 로그의 response mode, schema version, `repair_performed`, 문자 수와 항목 수를 확인한다. provider·model·endpoint 원문이나 실제 대화 내용은 이 로그에서 확인할 수 없다.
3. `auto`인데 최종 mode가 `legacy_tags`라면 임의 Custom API·Ollama Cloud의 기본 정책인지, 공식 profile인지, 이전의 명시적 미지원 판정이 process-local cache에 남은 것인지 설정과 endpoint를 별도로 확인한다. 현재 로그만으로 세 원인을 구분할 수 없다.
4. 명시적 400·404·422 구조화 파라미터 미지원과 429·timeout·5xx·refusal·malformed output은 서로 다른 정책으로 처리된다. 안전한 status, category, 예외 클래스가 남은 경로에서는 이를 참고하되, 세부 미지원 코드나 시도별 횟수가 로그에 있다고 가정하지 않는다.
5. 생각 기능 설정이 활성화되어 있는지 확인한 뒤 `repair_performed`와 thought 문자 수를 확인한다. 복구가 수행됐는데 문자 수가 0이면 원래 reply를 보존한 안전 실패일 수 있으며, 누락 필드 이름은 현재 로그에 직접 표시되지 않는다.
6. 일정·약속·목표가 중복되면 최종 항목 수와 실제 관리자 저장 결과를 확인한다. primary, regeneration, repair별 호출 횟수는 현재 로그에서 확인할 수 없고, 중간 시도의 내용은 로그나 관리자 입력으로 사용하면 안 된다.
7. 공식 endpoint를 쓰는 Custom API라면 설정에 저장된 scheme, host, port, path가 정확한 profile인지 확인한다. 비슷한 도메인이나 추가 path/query는 공식 profile로 간주하지 않는다.
8. 실제 대화가 아닌 합성 입력으로 재현한다. 서비스 복구가 급하고 네이티브 파라미터 호환이 원인으로 확인되면 `legacy`로 임시 전환한다.
9. 원인을 수정한 뒤 애플리케이션을 다시 시작해 process-local capability 하향 기록을 비우고 `auto`에서 다시 검증한다.

## V2 후보

V2에서는 다음 항목을 별도 설계와 검증 후 검토한다.

- 설정 UI에서 `auto`와 `legacy`를 직접 선택하고 현재 실제 mode를 확인하는 기능
- Ollama Cloud 모델별 네이티브 structured output capability 판별
- DeepSeek beta profile을 직접 선택하고 endpoint와 모델 조합을 검증하는 UI

DeepSeek beta의 runtime strict-tool 처리 자체는 V1에 포함되어 있다. V2 후보는 사용자가 이 profile을 명시적이고 안전하게 선택·검증하는 UI다.
