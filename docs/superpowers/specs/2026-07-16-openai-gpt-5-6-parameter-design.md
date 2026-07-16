# OpenAI GPT-5.6 모델별 파라미터 설계

## 배경

ENE의 OpenAI Responses API 클라이언트는 현재 모든 모델 요청에 `temperature`와 `top_p`를 포함한다. `gpt-5.6-sol`은 이 파라미터가 포함된 요청을 거부하므로 대화 요청이 HTTP 400으로 실패한다.

OpenAI 공식 문서에 따르면 `gpt-5.6`은 `gpt-5.6-sol`의 별칭이며, GPT-5.6 계열은 Responses API에서 `reasoning.effort`를 지원한다. ENE는 GPT-5.6 계열에서 샘플링 설정 대신 추론 강도를 제공해야 한다.

- 모델 가이드: https://developers.openai.com/api/docs/guides/latest-model
- Reasoning 모델 가이드: https://developers.openai.com/api/docs/guides/reasoning
- Responses API 생성 참조: https://developers.openai.com/api/reference/resources/responses/methods/create

## 목표

- OpenAI 공식 공급자에서 GPT-5.6 계열 요청이 지원하지 않는 샘플링 파라미터 때문에 실패하지 않게 한다.
- 모델명 자유 입력 방식을 유지한다.
- 선택한 모델의 기능에 맞춰 설정 UI를 동적으로 변경한다.
- GPT-5.6에서 기존 `temperature`와 `top_p` 값을 삭제하지 않고 보존한다.
- 일반 대화와 one-shot 요청에 같은 모델 정책을 적용한다.

## 비목표

- 모델명을 고정 선택 목록으로 교체하지 않는다.
- OpenAI Models API를 호출해 모델 목록을 동적으로 내려받지 않는다.
- Custom API 또는 다른 LLM 공급자의 파라미터 동작을 변경하지 않는다.
- 지원하지 않는 파라미터 오류를 자동 재시도하거나 조용히 숨기지 않는다.
- GPT-5.6 외 모델의 전체 기능 카탈로그를 이번 작업에서 구축하지 않는다.

## 승인된 사용자 경험

### 기존 모델

OpenAI 공급자에서 GPT-5.6 계열이 아닌 모델명을 입력하면 현재와 같이 다음 설정을 사용할 수 있다.

- Temperature
- Top P
- Max Tokens

추론 강도 항목은 표시하지 않는다.

### GPT-5.6 계열

OpenAI 공급자에서 GPT-5.6 계열 모델명을 입력하면 UI가 즉시 다음 상태로 바뀐다.

- Temperature: 비활성화
- Top P: 비활성화
- Max Tokens: 활성화 유지
- 추론 강도: 표시 및 활성화

비활성화된 항목은 숨기지 않는다. 사용자가 모델별 차이를 이해할 수 있도록 다음 의미의 안내를 표시한다.

> 현재 모델에서는 Temperature와 Top P를 지원하지 않습니다. 대신 추론 강도를 조정할 수 있습니다.

추론 강도 선택지는 OpenAI GPT-5.6 지원 범위에 맞춰 다음 값을 제공한다.

- 없음: `none`
- 낮음: `low`
- 보통: `medium`
- 높음: `high`
- 매우 높음: `xhigh`
- 최대: `max`

새 GPT-5.6 모델 설정의 기본값은 대화형 앱의 응답 시간과 비용을 고려해 `low`로 한다.

### 설정값 보존

GPT-5.6을 선택해도 해당 모델 또는 이전 모델에 저장된 `temperature`와 `top_p` 값을 삭제하거나 덮어쓰지 않는다. GPT-5.6 요청에서는 두 값만 사용하지 않는다. 사용자가 샘플링 파라미터를 지원하는 모델로 돌아가면 저장된 값이 다시 표시되고 요청에 사용된다.

## 모델 정책

모델 판별과 파라미터 지원 여부를 UI와 HTTP 클라이언트가 각각 구현하지 않는다. 공급자와 모델명을 입력받아 정책을 반환하는 작은 공용 모듈을 둔다.

GPT-5.6 계열은 정규화된 모델명이 다음 규칙을 만족할 때로 정의한다.

```text
provider == "openai"
model_name matches ^gpt-5\.6(?:$|-)
```

이 규칙은 다음 모델명을 포함한다.

- `gpt-5.6`
- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `gpt-5.6-luna`
- 위 이름 뒤에 하이픈으로 버전이 추가된 스냅샷

대소문자와 앞뒤 공백은 정규화한다. `gpt-5.60`, `gpt-5.5`, Custom API의 동일 문자열은 GPT-5.6 공식 공급자 정책으로 분류하지 않는다.

정책 결과는 최소한 다음 정보를 제공한다.

```text
supports_temperature
supports_top_p
supports_reasoning_effort
default_reasoning_effort
allowed_reasoning_efforts
```

이번 범위에서는 OpenAI GPT-5.6 정책과 기존 동작을 나타내는 기본 정책만 둔다. 향후 모델 정책은 같은 경계에 추가할 수 있다.

## 설정 데이터

현재 `llm_model_params[provider][model_name]` 구조를 유지하고 모델별 설정에 `reasoning_effort`를 선택적으로 추가한다.

```json
{
  "llm_model_params": {
    "openai": {
      "gpt-5.6-sol": {
        "temperature": 0.9,
        "top_p": 1.0,
        "max_tokens": 2048,
        "reasoning_effort": "low"
      }
    }
  }
}
```

`temperature`와 `top_p`는 값 보존과 다른 모델로 전환할 때의 복원을 위해 계속 저장한다. GPT-5.6 페이로드 생성 단계에서만 제외한다.

기존 설정에 `reasoning_effort`가 없고 선택 모델이 GPT-5.6 계열이면 `low`를 사용한다. 허용 목록에 없는 값은 저장 또는 로드 시 `low`로 정규화한다. GPT-5.6이 아닌 모델에는 `reasoning` 필드를 전송하지 않는다.

## 요청 생성

일반 대화와 one-shot 요청은 공통 페이로드 보정 함수를 사용한다. 기본 페이로드를 만든 뒤 모델 정책에 따라 선택적 생성 파라미터를 추가한다.

OpenAI GPT-5.6 요청에는 다음 규칙을 적용한다.

- `temperature`를 포함하지 않는다.
- `top_p`를 포함하지 않는다.
- `reasoning: {"effort": <저장값 또는 low>}`를 포함한다.
- `max_tokens`가 0보다 크면 기존처럼 `max_output_tokens`를 포함한다.

다른 OpenAI 모델은 현재 동작을 유지한다. Custom API가 OpenAI Responses 형식을 사용하더라도 이번 OpenAI 공식 모델 정책을 자동 적용하지 않는다.

## 오류 처리

모델 정책이 적용된 뒤에도 API가 파라미터 오류를 반환하면 현재의 상세 오류 메시지를 유지한다. 자동 재시도는 하지 않는다. 자동 재시도는 잘못된 모델 분류나 새로운 API 변경을 숨길 수 있기 때문이다.

UI에서 비활성화하더라도 런타임 요청 생성 단계에서 반드시 파라미터를 제거한다. 설정 파일 직접 수정, 이전 버전 설정 로드, UI를 거치지 않은 클라이언트 생성에도 안전해야 한다.

## 다국어 UI

다음 사용자 표시 문자열은 한국어, 영어, 일본어 로케일에 추가한다.

- 추론 강도 라벨
- 추론 강도 선택지 6개
- 현재 모델에서 Temperature와 Top P를 지원하지 않는다는 안내

기존 로케일 키 구조를 따르고 실제 사용자 데이터나 대화 문장을 예시에 사용하지 않는다.

## 테스트

### 모델 정책 단위 테스트

- OpenAI의 `gpt-5.6`, Sol, Terra, Luna 및 스냅샷을 GPT-5.6 정책으로 분류한다.
- 대소문자와 앞뒤 공백을 정규화한다.
- `gpt-5.60`, `gpt-5.5`를 GPT-5.6으로 오인하지 않는다.
- Custom API의 `gpt-5.6-sol`에는 OpenAI 공식 정책을 적용하지 않는다.

### 요청 페이로드 테스트

- GPT-5.6 일반 요청에 `temperature`와 `top_p`가 없다.
- GPT-5.6 일반 요청에 `reasoning.effort=low`와 `max_output_tokens`가 있다.
- GPT-5.6 one-shot 요청에도 같은 규칙이 적용된다.
- 저장된 유효 추론 강도가 요청에 반영된다.
- 다른 OpenAI 모델의 기존 샘플링 파라미터 동작은 유지된다.

### 설정 테스트

- 기존 설정에 추론 강도가 없으면 GPT-5.6에서 `low`를 사용한다.
- 유효한 추론 강도는 모델별로 저장하고 다시 로드한다.
- 잘못된 추론 강도는 `low`로 정규화한다.
- 비활성화된 Temperature와 Top P 값이 설정에서 보존된다.

### UI 테스트

- OpenAI GPT-5.6 모델명을 입력하면 Temperature와 Top P가 비활성화된다.
- 같은 상황에서 추론 강도가 표시되고 기본값이 낮음이다.
- 다른 모델로 전환하면 Temperature와 Top P가 다시 활성화되고 기존 값이 복원된다.
- Custom API와 다른 공급자 UI 동작은 바뀌지 않는다.
- 한국어, 영어, 일본어 문자열이 모두 존재한다.

## 완료 기준

- `gpt-5.6-sol`을 선택한 OpenAI Responses 요청이 `temperature` 또는 `top_p`를 포함하지 않는다.
- 일반 대화와 one-shot 경로 모두 동일한 정책 테스트를 통과한다.
- GPT-5.6 선택 시 UI가 승인된 동적 상태를 표시한다.
- 모델 전환 후 기존 샘플링 설정값이 보존된다.
- 다른 공급자와 기존 OpenAI 모델의 관련 회귀 테스트가 통과한다.
- 변경 파일은 UTF-8 BOM 없이 저장된다.
