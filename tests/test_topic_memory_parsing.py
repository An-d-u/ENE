from src.ai.knowledge_map_types import TopicMemoryHint
from src.ai.summary_parser import (
    is_complete_summary_response,
    parse_summary_response,
    parse_summary_response_with_topic_memory,
    parse_summary_topic_memory,
    parse_topic_memory_hints,
)


def _complete_response(topic_memory: str = "") -> str:
    topic_section = f"\n\n{topic_memory}" if topic_memory else ""
    return f"""
[SUMMARY]
- A neutral project update was reviewed.

[MASTER_INFO]
- none

[ENE_INFO]
- none

[MEMORY_META]
- memory_type: task
- confidence: 0.7
{topic_section}
""".strip()


def test_parse_summary_topic_memory_returns_empty_list_when_section_is_missing():
    assert parse_summary_topic_memory(_complete_response()) == []


def test_parse_topic_memory_hints_parses_multiple_bullet_blocks():
    hints = parse_topic_memory_hints(
        [
            "- keyword: Project Alpha",
            "  subject: launch plan",
            "  type: status_flow",
            "  state: active",
            "  text: Project Alpha launch plan is ready for review.",
            "  aliases: Alpha plan, Launch Alpha",
            "  retrieval_terms: launch, review, plan",
            "  confidence: 0.82",
            "- keyword: Project Beta",
            "  subject: onboarding checklist",
            "  text: Project Beta onboarding checklist needs one more review.",
            "  retrieval_terms: onboarding, checklist",
        ]
    )

    assert len(hints) == 2
    assert hints[0] == TopicMemoryHint(
        keyword="Project Alpha",
        subject="launch plan",
        type="status_flow",
        state="active",
        text="Project Alpha launch plan is ready for review.",
        aliases=["Alpha plan", "Launch Alpha"],
        retrieval_terms=["launch", "review", "plan"],
        confidence=0.82,
    )
    assert hints[1].keyword == "Project Beta"
    assert hints[1].type == "status_flow"
    assert hints[1].state == "active"
    assert hints[1].confidence == 0.5


def test_parse_topic_memory_hints_parses_pipe_delimited_single_line():
    hints = parse_topic_memory_hints(
        [
            "- keyword: Project Gamma | subject: review queue | type: status_flow | "
            "state: active | text: Project Gamma review queue is ready. | "
            "retrieval_terms: review, queue"
        ]
    )

    assert len(hints) == 1
    assert hints[0].keyword == "Project Gamma"
    assert hints[0].subject == "review queue"
    assert hints[0].text == "Project Gamma review queue is ready."
    assert hints[0].retrieval_terms == ["review", "queue"]


def test_parse_topic_memory_hints_keeps_bulleted_fields_in_one_hint():
    hints = parse_topic_memory_hints(
        [
            "- keyword: Project Theta",
            "- subject: launch plan",
            "- text: Project Theta launch plan is ready.",
            "- aliases: Theta plan, Launch Theta",
            "- retrieval_terms: theta, launch, plan",
            "- confidence: 0.73",
        ]
    )

    assert len(hints) == 1
    assert hints[0] == TopicMemoryHint(
        keyword="Project Theta",
        subject="launch plan",
        type="status_flow",
        state="active",
        text="Project Theta launch plan is ready.",
        aliases=["Theta plan", "Launch Theta"],
        retrieval_terms=["theta", "launch", "plan"],
        confidence=0.73,
    )


def test_parse_topic_memory_hints_flushes_previous_hint_at_next_bulleted_keyword():
    hints = parse_topic_memory_hints(
        [
            "- keyword: Project Iota",
            "- subject: first plan",
            "- text: Project Iota first plan is ready.",
            "- keyword: Project Kappa",
            "- subject: second plan",
            "- text: Project Kappa second plan is ready.",
        ]
    )

    assert len(hints) == 2
    assert hints[0].keyword == "Project Iota"
    assert hints[0].subject == "first plan"
    assert hints[1].keyword == "Project Kappa"
    assert hints[1].subject == "second plan"


def test_parse_summary_topic_memory_treats_none_section_as_empty():
    response_text = _complete_response(
        """
[TOPIC_MEMORY]
- none
""".strip()
    )

    assert parse_summary_topic_memory(response_text) == []


def test_parse_topic_memory_hints_discards_items_missing_required_fields():
    hints = parse_topic_memory_hints(
        [
            "- subject: Missing keyword",
            "- text: This item should be discarded.",
            "- keyword: Project Delta",
            "  subject: status board",
            "  text: Project Delta status board is current.",
            "- keyword: Missing Subject",
            "  text: This item should be discarded.",
            "- keyword: Missing Text",
            "  subject: incomplete item",
        ]
    )

    assert [hint.keyword for hint in hints] == ["Project Delta"]


def test_parse_topic_memory_hints_clamps_and_defaults_confidence():
    hints = parse_topic_memory_hints(
        [
            "- keyword: High Confidence",
            "  subject: bounds",
            "  text: High confidence is clamped.",
            "  confidence: 1.7",
            "- keyword: Low Confidence",
            "  subject: bounds",
            "  text: Low confidence is clamped.",
            "  confidence: -0.2",
            "- keyword: Invalid Confidence",
            "  subject: fallback",
            "  text: Invalid confidence uses the default.",
            "  confidence: not-a-number",
        ]
    )

    assert [hint.confidence for hint in hints] == [1.0, 0.0, 0.5]


def test_parse_topic_memory_hints_normalizes_aliases_and_retrieval_terms():
    hints = parse_topic_memory_hints(
        [
            "- keyword: Project Echo",
            "  subject: duplicate terms",
            "  text: Project Echo has duplicate search terms.",
            "  aliases: Echo Plan, echo plan, Review Echo",
            "  retrieval_terms: review, review, echo",
        ]
    )

    assert hints[0].aliases == ["Echo Plan", "Review Echo"]
    assert hints[0].retrieval_terms == ["review", "echo"]


def test_parse_summary_response_still_returns_four_tuple():
    parsed = parse_summary_response(_complete_response())

    assert isinstance(parsed, tuple)
    assert len(parsed) == 4


def test_parse_summary_response_with_topic_memory_returns_five_tuple():
    parsed = parse_summary_response_with_topic_memory(
        _complete_response(
            """
[TOPIC_MEMORY]
- keyword: Project Zeta
  subject: release notes
  text: Project Zeta release notes are ready.
""".strip()
        )
    )

    assert isinstance(parsed, tuple)
    assert len(parsed) == 5
    summary, user_facts, ene_facts, memory_meta, topic_hints = parsed
    assert summary == "A neutral project update was reviewed."
    assert user_facts == []
    assert ene_facts == []
    assert memory_meta == {"memory_type": "task", "confidence": 0.7}
    assert [hint.keyword for hint in topic_hints] == ["Project Zeta"]


def test_topic_memory_section_is_optional_for_completeness():
    assert is_complete_summary_response(_complete_response()) is True


def test_parse_summary_topic_memory_recognizes_supported_section_labels():
    labels = ["TOPIC_MEMORY", "TOPIC MEMORY", "[주제 기억]"]

    for label in labels:
        response_text = _complete_response(
            f"""
{label}
- keyword: Label Example
  subject: section label
  text: The section label is recognized.
""".strip()
        )

        assert [hint.keyword for hint in parse_summary_topic_memory(response_text)] == ["Label Example"]
