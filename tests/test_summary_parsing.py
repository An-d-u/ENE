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
