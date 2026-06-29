from src.ai.summary_parser import is_complete_summary_response


def test_summary_response_is_incomplete_when_memory_meta_section_is_missing():
    response_text = """
[SUMMARY]
- 테스트 대화를 요약했다.

[MASTER_INFO]
- none

[ENE_INFO]
- none
""".strip()

    assert is_complete_summary_response(response_text) is False


def test_summary_response_is_complete_with_empty_fact_sections():
    response_text = """
[SUMMARY]
- 테스트 대화를 요약했다.

[MASTER_INFO]
- none

[ENE_INFO]
- none

[MEMORY_META]
- none
""".strip()

    assert is_complete_summary_response(response_text) is True
