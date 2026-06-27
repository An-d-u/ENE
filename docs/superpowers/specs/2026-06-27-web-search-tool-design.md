# ENE 웹 검색 도구 V1 설계

## 목표

ENE가 최신 정보가 필요한 질문에 대해 웹 검색 결과를 참고해 답변할 수 있게 한다. V1은 빠르게 쓸 수 있는 제품 기능을 우선하며, 검색 백엔드는 Tavily를 기본값으로 둔다. 다만 OpenAI, Gemini, Anthropic, OpenRouter, Ollama, Custom API 제공자에 같은 방식으로 확장할 수 있도록 ENE 내부 검색 인터페이스를 공통화한다.

## 비목표

- Brave Search 어댑터 구현
- DuckDuckGo 일반 검색 스크래핑
- Gemini Google Search Grounding 네이티브 연동
- OpenAI `web_search` 네이티브 연동
- 검색 결과 전용 UI 패널
- 검색 결과 캐시
- 도메인 allow/block list

위 항목은 V2 후보로 둔다.

## 사용자 경험

검색 기능은 설정에서 켜고 끌 수 있다. 자동 검색이 켜져 있으면 ENE는 사용자의 메시지가 최신 정보, 웹 정보, 특정 사이트 정보, 가격, 일정, 규정, 릴리스 정보처럼 현재성이 중요한 질문인지 먼저 판단한다. 검색이 필요하다고 판단되면 ENE가 검색을 실행한 뒤, 검색 결과를 모델 컨텍스트에 넣고 최종 답변을 생성한다.

수동 검색 명령도 제공한다.

```text
/search 검색어
```

수동 검색은 자동 판단을 건너뛰고 바로 검색을 실행한다. 검색 결과가 없거나 실패하면 ENE는 실패를 짧게 알리고, 기존 지식으로 답할 수 있는 범위와 한계를 함께 말한다.

## 설정

V1에서 추가할 설정값은 다음과 같다.

```json
{
  "web_search_enabled": false,
  "web_search_auto_enabled": true,
  "web_search_provider": "tavily",
  "web_search_max_results": 5,
  "web_search_timeout_sec": 12
}
```

Tavily API 키는 비밀 설정 파일에 저장한다.

```json
{
  "web_search_api_keys": {
    "tavily": ""
  }
}
```

기본값은 보수적으로 둔다. 기능은 사용자가 명시적으로 켰을 때만 동작한다.

## 아키텍처

새 모듈을 추가한다.

```text
src/ai/search_tool.py
  SearchQuery
  SearchResult
  SearchResponse
  SearchProvider
  TavilySearchProvider
  SearchTool

src/ai/tool_calling.py
  WebSearchDecision
  WebSearchToolRunner
  build_search_context_block
```

`search_tool.py`는 외부 검색 API와의 통신만 책임진다. `tool_calling.py`는 검색 필요 여부 판단, 검색 실행, 검색 결과를 프롬프트 블록으로 바꾸는 흐름을 책임진다. LLM 제공자별 클라이언트는 이 공통 계층을 호출해 검색 컨텍스트만 추가로 받는다.

## 데이터 흐름

일반 채팅 흐름은 다음 순서를 따른다.

1. 사용자가 메시지를 보낸다.
2. Bridge가 기존처럼 메모리 검색 입력을 구성한다.
3. LLM 클라이언트가 메모리 컨텍스트를 만든다.
4. 검색 기능이 꺼져 있으면 기존 흐름을 그대로 사용한다.
5. 검색 기능이 켜져 있고 자동 검색이 켜져 있으면 검색 필요 여부를 판단한다.
6. 검색이 필요하면 `SearchTool.search()`를 호출한다.
7. 검색 결과를 `[WEB_SEARCH_RESULTS]` 블록으로 변환한다.
8. 메모리 컨텍스트, 검색 컨텍스트, 사용자 메시지를 합쳐 모델에 전달한다.
9. 모델은 검색 결과에 포함된 URL만 출처로 사용해 답변한다.

수동 `/search` 명령은 5번의 자동 판단을 건너뛰고 바로 6번으로 이동한다.

## 검색 결과 컨텍스트

모델에 주입하는 검색 결과는 간결한 텍스트 블록으로 만든다.

```text
[WEB_SEARCH_RESULTS]
Query: ...
Provider: tavily

1. 제목
URL: https://example.com
Published: 2026-06-20
Snippet: ...

2. 제목
URL: https://example.org
Snippet: ...
[/WEB_SEARCH_RESULTS]
```

검색 결과 원문 전체를 무조건 넣지 않는다. V1은 제목, URL, 스니펫, 게시일 정도로 시작한다. 검색 API가 원문 추출을 제공하더라도 기본값은 꺼두고, 필요할 때만 V2에서 다룬다.

## 도구 호출 방식

V1은 ENE 내부에 `search_web` 도구 호출 런타임을 만든다. 다만 모든 제공자와 커스텀 엔드포인트가 네이티브 Function Calling을 안정적으로 지원한다고 가정하지 않는다. 그래서 V1의 기본 경로는 제공자 공통으로 동작하는 1회 구조화 판단과 ENE 실행 도구를 사용한다.

네이티브 Function Calling을 지원하는 제공자는 이후 같은 `search_web` 스키마를 provider adapter에 연결할 수 있다. 네이티브 호출을 쓰든, 구조화 판단 fallback을 쓰든, ENE 내부 실행 결과는 `SearchResponse`로 통일한다.

## 자동 검색 판단

판단 결과 예시는 다음과 같다.

```json
{
  "should_search": true,
  "query": "Tavily API pricing 2026",
  "reason": "사용자가 현재 가격 정보를 묻고 있음"
}
```

판단 호출이 실패하거나 JSON 파싱이 실패하면 검색하지 않고 기존 답변 흐름으로 진행한다. 수동 `/search`는 판단 호출을 사용하지 않는다.

## 제공자별 확장 전략

V1은 모든 제공자에 동일한 검색 결과 주입 방식을 적용한다.

- Gemini: V1은 공통 검색 결과 주입을 사용한다. Google Search Grounding 네이티브 연동은 V2에서 별도 어댑터로 추가한다.
- OpenAI: V1은 공통 검색 결과 주입을 사용한다. Responses API `web_search` 네이티브 연동은 V2에서 추가한다.
- Anthropic/OpenRouter/Custom API/Ollama: V1은 공통 검색 결과 주입을 사용한다.

이 구조를 먼저 만들면, V2에서 네이티브 검색 도구를 추가하더라도 ENE 내부의 `SearchResponse` 형식은 유지할 수 있다.

## 오류 처리

- API 키가 없으면 검색을 실행하지 않고 검색 비활성 상태로 처리한다.
- Tavily HTTP 오류는 사용자에게 짧은 안내로 노출하고, 상세 오류는 로그에만 남긴다.
- 타임아웃은 `web_search_timeout_sec` 설정을 따른다.
- 검색 결과가 비어 있으면 모델에 빈 검색 블록을 넣지 않는다.
- 검색 실패가 일반 채팅 실패로 이어지지 않게 한다.

## 개인정보와 안전

검색 쿼리는 사용자의 최신 메시지에서 필요한 내용만 재작성한다. 장기 기억 원문, 프로필 원문, 전체 대화 히스토리를 검색 API로 보내지 않는다. 자동 검색 판단에도 최근 메시지와 최소한의 대화 맥락만 사용한다.

테스트, 문서, 예시에는 실제 사용자 대화나 개인정보를 넣지 않는다. 모든 fixture는 중립적인 가상 문장으로 작성한다.

## 테스트 계획

- 설정 기본값과 비밀 설정 병합 테스트
- Tavily 요청 payload 구성 테스트
- Tavily 응답 정규화 테스트
- API 키 없음, 타임아웃, HTTP 오류 fallback 테스트
- `/search` 명령이 자동 판단 없이 검색을 실행하는 테스트
- 자동 검색 판단이 `should_search=false`일 때 기존 흐름을 유지하는 테스트
- 검색 결과 블록이 URL과 스니펫을 안정적으로 포맷하는 테스트
- LLM 클라이언트가 검색 결과 컨텍스트를 메모리 컨텍스트와 함께 전달하는 테스트

## 성공 기준

- 사용자가 검색 기능을 켜고 Tavily API 키를 넣으면 `/search` 명령으로 최신 웹 검색 답변을 받을 수 있다.
- 자동 검색이 켜져 있으면 현재성이 중요한 질문에서 검색 결과가 답변에 반영된다.
- 검색 실패가 일반 채팅 실패로 번지지 않는다.
- 기존 메모리 검색, 이미지 첨부, 요약, TTS 흐름이 깨지지 않는다.
