import sys
import types


google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.ai.http_llm_clients import OpenAICompatibleClient
from src.ai.llm_client import GeminiClient
from src.ai.response_cleanup import extract_goal_update_metadata


def test_extract_goal_update_metadata_removes_block_and_parses_keys():
    text = """[analysis]
user_intent=seek_comfort
[/analysis]

[ene_goal_update]
action=create
type=short_term
id=
title=마스터가 안정될 때까지 위로하기
reason=사용자가 우울해 보임
completion_reason=
[/ene_goal_update]

괜찮아요. 제가 여기 있을게요. [smile]"""

    cleaned, update = extract_goal_update_metadata(text)

    assert "[ene_goal_update]" not in cleaned
    assert update["action"] == "create"
    assert update["type"] == "short_term"
    assert update["id"] == ""
    assert update["title"] == "마스터가 안정될 때까지 위로하기"
    assert update["reason"] == "사용자가 우울해 보임"
    assert update["completion_reason"] == ""


def test_extract_goal_update_metadata_keeps_empty_fields_for_none_action():
    text = """[ene_goal_update]
action=none
type=
id=
title=
reason=
completion_reason=
[/ene_goal_update]

좋아요. [smile]"""

    cleaned, update = extract_goal_update_metadata(text)

    assert cleaned == "좋아요. [smile]"
    assert update == {
        "action": "none",
        "type": "",
        "id": "",
        "title": "",
        "reason": "",
        "completion_reason": "",
    }


def test_extract_goal_update_metadata_removes_all_blocks_and_parses_only_first():
    text = """[ene_goal_update]
action=create
type=short_term
title=첫 번째 목표
[/ene_goal_update]
보이는 본문
[ene_goal_update]
action=complete
type=long_term
title=두 번째 목표
[/ene_goal_update]"""

    cleaned, update = extract_goal_update_metadata(text)

    assert "[ene_goal_update]" not in cleaned
    assert "[/ene_goal_update]" not in cleaned
    assert cleaned == "보이는 본문"
    assert update["action"] == "create"
    assert update["type"] == "short_term"
    assert update["title"] == "첫 번째 목표"


def test_extract_goal_update_metadata_removes_unclosed_block_to_end():
    text = """좋아요.
[ene_goal_update]
action=create
type=short_term
title=노출되면 안 되는 목표
reason=태그가 닫히지 않음"""

    cleaned, update = extract_goal_update_metadata(text)

    assert cleaned == "좋아요."
    assert update == {}
    assert "노출되면 안 되는 목표" not in cleaned


def test_extract_goal_update_metadata_removes_trailing_unclosed_block_after_closed_block():
    text = """[ene_goal_update]
action=create
type=short_term
title=첫 번째 목표
[/ene_goal_update]
보이는 본문
[ene_goal_update]
action=update
title=노출되면 안 되는 목표"""

    cleaned, update = extract_goal_update_metadata(text)

    assert cleaned == "보이는 본문"
    assert update["action"] == "create"
    assert update["type"] == "short_term"
    assert update["title"] == "첫 번째 목표"
    assert "노출되면 안 되는 목표" not in cleaned


def test_extract_goal_update_metadata_ignores_unknown_keys():
    text = """[ene_goal_update]
action=update
type=short_term
scope=long_term
unexpected=value
id=goal-1
[/ene_goal_update]
좋아요."""

    cleaned, update = extract_goal_update_metadata(text)

    assert cleaned == "좋아요."
    assert update == {
        "action": "update",
        "type": "short_term",
        "id": "goal-1",
    }


def test_gemini_parse_response_returns_goal_update_metadata():
    client = object.__new__(GeminiClient)
    client.settings = {"ui_language": "ko"}

    parsed = GeminiClient._parse_response(
        client,
        "[ene_goal_update]\naction=none\n[/ene_goal_update]\n좋아요. [smile]",
    )

    assert len(parsed) == 11
    clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive, gesture, mood = parsed
    assert clean_text == "좋아요."
    assert emotion == "smile"
    assert tts_text is None
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""
    assert goal_update["action"] == "none"
    assert proactive == []
    assert gesture == ""


def test_http_parse_response_returns_goal_update_metadata():
    client = object.__new__(OpenAICompatibleClient)
    client.settings = {"ui_language": "ko"}

    parsed = client._parse_response(
        "[ene_goal_update]\naction=none\n[/ene_goal_update]\n좋아요. [smile]"
    )

    assert len(parsed) == 11
    assert parsed[7]["action"] == "none"
    assert parsed[8] == []
    assert parsed[9] == ""
