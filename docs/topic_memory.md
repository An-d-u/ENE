# 주제 기억 시스템

ENE의 주제 기억 시스템은 장기 기억 요약에 들어가기 어려운 작은 단서들을 키워드 중심으로 저장하고, 이후 관련 대화에서 필요한 항목만 컨텍스트에 주입하기 위한 보조 기억 계층이다.

## 목적

- 장기 기억 요약문에 과하게 압축될 수 있는 세부 단서를 보존한다.
- 사용자/ENE 성향 기록과 별개로 일반 주제, 물건, 작품, 계획, 상태 변화 같은 작은 정보들을 키워드별로 묶는다.
- 저장 전에는 항상 요약 확인 UI에서 후보를 확인하고 수정하거나 삭제할 수 있게 한다.
- 답변 생성 시에는 현재 메시지와 관련 있는 주제 기억만 검색해 프롬프트에 붙인다.

## 저장 파일

런타임 저장 파일은 `knowledge_map.json`이다. 이 파일은 사용자별 런타임 데이터이므로 커밋 대상이 아니다.

기본 구조는 다음과 같다.

```json
{
  "schema_version": 1,
  "topics": [
    {
      "id": "topic-1",
      "keyword": "Project Alpha",
      "aliases": ["Alpha Plan"],
      "retrieval_terms": ["planning", "review"],
      "clues": [
        {
          "id": "clue-1",
          "subject": "planning",
          "type": "status",
          "state": "active",
          "text": "Project Alpha planning is ready for review.",
          "confidence": 0.8,
          "source_memory_id": "memory-001",
          "history": []
        }
      ]
    }
  ],
  "last_updated": "2026-01-01T00:00:00+00:00"
}
```

문서와 테스트 예시는 모두 합성 데이터만 사용한다.

## 추출 흐름

1. 대화 요약 프롬프트가 `[TOPIC_MEMORY]` 섹션에 저장 후보를 요청한다.
2. LLM 응답 파서는 `keyword`, `subject`, `type`, `state`, `text`, `aliases`, `retrieval_terms`, `confidence`를 `TopicMemoryHint`로 정규화한다.
3. 수동 요약 확인 UI는 후보 목록을 표시한다.
4. 사용자는 각 후보의 필드를 수정하거나 후보를 삭제할 수 있다.
5. 저장 버튼을 누른 후보만 `KnowledgeMapManager`에 병합된다.
6. 자동 요약 경로는 주제 기억을 바로 저장하지 않는다.

## 병합 규칙

- 같은 `keyword` 또는 `aliases`로 단일 기존 topic을 찾으면 그 topic에 병합한다.
- 같은 topic 안에서 `subject`와 `type`이 같은 clue는 최신 값으로 교체하고, 이전 값은 `history`로 이동한다.
- 더 구체적이거나 최근 상태가 들어오면 기존 활성 clue가 갱신된다.
- 필수값이 부족한 후보는 저장하지 않는다.

## 검색과 컨텍스트 주입

답변 생성 전 공통 메모리 컨텍스트 빌더가 `knowledge_map_manager`를 확인한다.

- 설정값 `max_topic_memory_context`가 `0`이면 주제 기억 주입을 끈다.
- 기본값은 `2`이다.
- query가 비어 있으면 주제 기억 검색을 호출하지 않는다.
- 임베딩이 있으면 `async_search()`를 통해 의미 기반 검색을 사용한다.
- 임베딩 검색이 실패하면 직접 키워드 검색으로 되돌아간다.
- 검색 실패는 답변 생성을 막지 않고 로그만 남긴다.

컨텍스트 예시는 다음과 같다.

```text
[주제 기억]
- Project Alpha / planning: Project Alpha planning is ready for review.
```

영어 프롬프트에서는 `[Topic Memory]`, 일본어 프롬프트에서는 `[トピック記憶]` 라벨을 사용한다.

## 주요 코드 위치

- `src/ai/knowledge_map_types.py`: 주제 기억 데이터 모델
- `src/ai/knowledge_map.py`: 저장, 병합, 검색, 컨텍스트 블록 생성
- `src/ai/summary_parser.py`: `[TOPIC_MEMORY]` 파싱
- `src/ai/summary_prompt.py`: 추출 기준 프롬프트
- `src/core/bridge_mixins/memory_summary.py`: 승인된 후보 저장 연결
- `assets/web/runtime_message_helpers.js`: 요약 확인 UI의 후보 표시, 수정, 삭제, payload 수집
- `src/ai/memory_context_builder.py`: 관련 주제 기억 컨텍스트 주입

## 검증

관련 회귀 테스트는 다음 묶음으로 확인한다.

```powershell
python -m pytest tests/test_knowledge_map_types.py tests/test_knowledge_map_manager.py tests/test_topic_memory_parsing.py tests/test_summary_prompt.py tests/test_bridge_memory_metadata.py tests/test_chat_ui_assets.py tests/test_bridge_context_compaction.py tests/test_app_memory_bootstrap.py tests/test_app_llm_bootstrap.py tests/test_app_goal_manager.py tests/test_llm_provider.py -q
```
