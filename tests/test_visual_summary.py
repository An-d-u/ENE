"""합성 장면 설명의 분리와 화면 권한 수명을 검증한다."""
import json
from types import SimpleNamespace

from src.ai.response_protocol import ProviderResponse, ResponseMode, ResponseStatus
from src.ai.visual_summary import extract_visual_summary, summary_schema
from src.core.screen_frame import ScreenFrame
from src.core.bridge_mixins.visual_context import VisualContextBridgeMixin


def test_structured_summary_does_not_enter_reply_or_modify_original_schema():
    schema = {"properties": {"reply": {"type": "string"}}, "required": ["reply"]}
    assert summary_schema(schema)["required"] == ["reply", "visual_summary"]
    assert schema["required"] == ["reply"]
    raw = ProviderResponse(json.dumps({"reply": "합성 답변", "visual_summary": "파란 도형이 오른쪽에 있다."}),
                           ResponseStatus.COMPLETE, ResponseMode.JSON_SCHEMA)
    clean, summary = extract_visual_summary(raw, raw.mode)
    assert json.loads(clean.carrier) == {"reply": "합성 답변"}
    assert summary == "파란 도형이 오른쪽에 있다."
    assert clean.status is ResponseStatus.COMPLETE


def test_legacy_summary_is_bounded_and_unfinished_block_is_removed():
    text, summary = extract_visual_summary("답변[visual_summary]" + "가" * 400 + "[/visual_summary]", ResponseMode.LEGACY_TAGS)
    assert text == "답변" and len(summary) == 200
    assert extract_visual_summary("답변[visual_summary]미완성", ResponseMode.LEGACY_TAGS) == ("답변", "")
    assert extract_visual_summary('{"reply":"응답","visual_summary":{}}', ResponseMode.JSON_OBJECT)[1] == ""


def test_summary_requires_live_frame_and_is_removed_on_close():
    allowed = True
    frame = ScreenFrame(b"synthetic", lambda: allowed, source="후면 카메라")
    frame.visual_summary = "노란 상자가 놓여 있다."
    assert frame.summary_note().startswith("후면 카메라 · ")
    allowed = False
    assert frame.summary_note() == ""
    frame.close()
    assert frame.visual_summary == ""


def test_followups_use_only_the_prior_window_including_text_only_turns():
    bridge = VisualContextBridgeMixin()
    bridge.settings = {"visual_context_turns": 2}
    messages = {}
    bridge.chat_state = SimpleNamespace(pc_messages=messages, public_user_ids={})
    def add(role, key, summary=""):
        messages[key] = dict(role=role, id=key, visual_summary=summary)
        if role == "user":
            bridge.chat_state.public_user_ids[key] = key
        return SimpleNamespace(key=key, source="pc")
    first = add("user", "q1")
    add("assistant", "a1", "합성 장면 A")
    second = add("user", "q2")
    add("assistant", "a2")
    add("assistant", "automatic")
    third = add("user", "q3")
    assert "합성 장면 A" in bridge._with_visual_context("질문", second)
    assert "합성 장면 A" in bridge._with_visual_context("질문", third)
    fourth = add("user", "q4")
    assert bridge._with_visual_context("질문", fourth) == "질문"
    assert bridge._with_visual_context("질문", first) == "질문"
    bridge.settings["visual_context_turns"] = 0
    assert bridge._with_visual_context("질문", second) == "질문"
    assert messages["a1"]["visual_summary"] == "합성 장면 A"
