import pytest

pytest.importorskip("google.genai")

from src.ai.llm_client import GeminiClient


def test_parse_summary_response_extracts_summary_and_facts():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[SUMMARY]
- 오늘은 프로젝트 일정과 우선순위를 정리했다.

[MASTER_INFO]
- [goal] 이번 주 안에 릴리즈 후보를 만들고 싶다.
- [preference] 짧고 명확한 설명을 선호한다.

[ENE_INFO]
- [speaking_style] 짧고 단정한 말투를 유지한다.
- [relationship_tone] 사용자를 다정하게 챙기는 편이다.

[MEMORY_META]
- memory_type: task
- importance_reason: repeated_topic
- confidence: 0.82
- entity_names: ENE, Obsidian
- aliases: 릴리즈 후보, release candidate
- trigger_terms: 릴리스, 후보, 일정
""".strip()

    summary, user_facts, ene_facts, memory_meta = client._parse_summary_response(response_text)

    assert "프로젝트 일정과 우선순위" in summary
    assert "[goal] 이번 주 안에 릴리즈 후보를 만들고 싶다." in user_facts
    assert "[preference] 짧고 명확한 설명을 선호한다." in user_facts
    assert "[speaking_style] 짧고 단정한 말투를 유지한다." in ene_facts
    assert "[relationship_tone] 사용자를 다정하게 챙기는 편이다." in ene_facts
    assert memory_meta == {
        "memory_type": "task",
        "importance_reason": "repeated_topic",
        "confidence": 0.82,
        "entity_names": ["ENE", "Obsidian"],
        "aliases": ["릴리즈 후보", "release candidate"],
        "trigger_terms": ["릴리스", "후보", "일정"],
    }


def test_parse_summary_response_ignores_none_facts():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[SUMMARY]
- 테스트 대화 요약

[MASTER_INFO]
- none

[ENE_INFO]
- none

[MEMORY_META]
- none
""".strip()

    summary, user_facts, ene_facts, memory_meta = client._parse_summary_response(response_text)

    assert summary == "테스트 대화 요약"
    assert user_facts == []
    assert ene_facts == []
    assert memory_meta == {}


def test_parse_summary_response_with_topic_memory_extracts_topic_hints():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[SUMMARY]
- A neutral project checkpoint was reviewed.

[MASTER_INFO]
- none

[ENE_INFO]
- none

[MEMORY_META]
- memory_type: task
- confidence: 0.84

[TOPIC_MEMORY]
- keyword: Project Alpha
  subject: review checklist
  type: status_flow
  state: active
  text: Project Alpha review checklist is ready.
  aliases: Alpha checklist
  retrieval_terms: review, checklist
  confidence: 0.82
""".strip()

    summary, user_facts, ene_facts, memory_meta, topic_hints = (
        client._parse_summary_response_with_topic_memory(response_text)
    )

    assert summary == "A neutral project checkpoint was reviewed."
    assert user_facts == []
    assert ene_facts == []
    assert memory_meta == {"memory_type": "task", "confidence": 0.84}
    assert len(topic_hints) == 1
    assert topic_hints[0].to_dict() == {
        "keyword": "Project Alpha",
        "subject": "review checklist",
        "type": "status_flow",
        "state": "active",
        "text": "Project Alpha review checklist is ready.",
        "aliases": ["Alpha checklist"],
        "retrieval_terms": ["review", "checklist"],
        "confidence": 0.82,
    }
