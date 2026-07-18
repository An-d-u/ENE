import asyncio
from types import SimpleNamespace

import pytest

from src.ai.llm_client import GeminiClient


def _combined_output(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _legacy_client(response_text: str):
    client = GeminiClient.__new__(GeminiClient)
    response = SimpleNamespace(text=response_text, usage_metadata=None)
    client.chat = SimpleNamespace(send_message=lambda _contents: response)
    client._refresh_chat_session_for_runtime_prompt_if_needed = lambda: None
    client._log_turn_token_usage = lambda _response, label="": None
    client._extract_response_text_or_empty = lambda response, label="": response.text
    return client


def test_text_turn_logs_omit_prompt_carrier_and_all_parsed_content(capsys):
    sentinels = {
        "prompt": "SYNTHETIC-GEMINI-PRIVATE-PROMPT",
        "carrier": "SYNTHETIC-GEMINI-PRIVATE-CARRIER",
        "reply": "SYNTHETIC-GEMINI-PRIVATE-REPLY",
        "tts": "SYNTHETIC-GEMINI-PRIVATE-TTS",
        "event": "SYNTHETIC-GEMINI-PRIVATE-EVENT",
        "analysis": "SYNTHETIC-GEMINI-PRIVATE-ANALYSIS",
        "promise": "SYNTHETIC-GEMINI-PRIVATE-PROMISE",
        "thought": "SYNTHETIC-GEMINI-PRIVATE-THOUGHT",
        "goal": "SYNTHETIC-GEMINI-PRIVATE-GOAL",
        "proactive": "SYNTHETIC-GEMINI-PRIVATE-PROACTIVE",
    }
    client = _legacy_client(sentinels["carrier"])
    client._parse_response = lambda _carrier: (
        sentinels["reply"],
        "normal",
        sentinels["tts"],
        [{"title": sentinels["event"]}],
        {"topic": sentinels["analysis"]},
        [{"title": sentinels["promise"]}],
        sentinels["thought"],
        {"title": sentinels["goal"]},
        [{"title": sentinels["proactive"]}],
        "",
    )

    result = client.send_message(sentinels["prompt"])

    assert result[0] == sentinels["reply"]
    combined = _combined_output(capsys)
    for sentinel in sentinels.values():
        assert sentinel not in combined
    assert "category=final_response" in combined
    assert "event_count=1" in combined


def test_empty_response_diagnostics_omit_sdk_repr_and_log_normalized_categories(
    capsys,
):
    sentinels = {
        "feedback": "SYNTHETIC-GEMINI-PRIVATE-PROMPT-FEEDBACK",
        "finish_message": "SYNTHETIC-GEMINI-PRIVATE-FINISH-MESSAGE",
        "safety": "SYNTHETIC-GEMINI-PRIVATE-SAFETY",
    }
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {}
    response = SimpleNamespace(
        text=None,
        prompt_feedback=SimpleNamespace(
            block_reason=SimpleNamespace(name="SAFETY"),
            detail=sentinels["feedback"],
        ),
        candidates=[
            SimpleNamespace(
                finish_reason=SimpleNamespace(name="MAX_TOKENS"),
                finish_message=sentinels["finish_message"],
                safety_ratings=[sentinels["safety"]],
            )
        ],
    )

    assert client._extract_response_text_or_empty(response, label="최종 응답") == ""

    combined = _combined_output(capsys)
    for sentinel in sentinels.values():
        assert sentinel not in combined
    assert "category=empty_response" in combined
    assert "candidate_count=1" in combined
    assert "finish_category=max_tokens" in combined
    assert "block_category=safety" in combined


def test_empty_response_diagnostics_never_invoke_hostile_magic_methods(capsys):
    sentinel = "SYNTHETIC-GEMINI-HOSTILE-MAGIC-METHOD"

    class HostileValue:
        def _fail(self):
            print(sentinel)
            raise RuntimeError("hostile hook")

        def __repr__(self):
            return self._fail()

        def __str__(self):
            return self._fail()

        def __len__(self):
            return self._fail()

        def __format__(self, _spec):
            return self._fail()

    client = GeminiClient.__new__(GeminiClient)
    client.settings = {}
    response = SimpleNamespace(
        text=HostileValue(),
        prompt_feedback=HostileValue(),
        candidates=HostileValue(),
    )

    assert client._extract_response_text_or_empty(response, label=HostileValue()) == ""
    assert sentinel not in _combined_output(capsys)


def test_provider_exception_log_omits_string_and_traceback_content(capsys):
    sentinel = "SYNTHETIC-GEMINI-PRIVATE-PROVIDER-EXCEPTION"

    class HostileProviderError(RuntimeError):
        def __str__(self):
            print(sentinel)
            raise RuntimeError("exception string hook")

    client = GeminiClient.__new__(GeminiClient)
    client.chat = SimpleNamespace(
        send_message=lambda _message: (_ for _ in ()).throw(
            HostileProviderError(sentinel)
        )
    )
    client._refresh_chat_session_for_runtime_prompt_if_needed = lambda: None
    client._log_turn_token_usage = lambda _response, label="": None

    with pytest.raises(HostileProviderError):
        client.send_message("SYNTHETIC-GEMINI-PRIVATE-ERROR-PROMPT")

    combined = _combined_output(capsys)
    assert sentinel not in combined
    assert "SYNTHETIC-GEMINI-PRIVATE-ERROR-PROMPT" not in combined
    assert "category=provider_error" in combined
    assert "exception_class=HostileProviderError" in combined
    assert "Traceback" not in combined


def test_multimodal_provider_error_returns_fixed_safe_fallback(monkeypatch, capsys):
    prompt_secret = "SYNTHETIC-GEMINI-PRIVATE-IMAGE-PROMPT"
    error_secret = "SYNTHETIC-GEMINI-PRIVATE-IMAGE-ERROR"

    class HostileProviderError(RuntimeError):
        def __str__(self):
            print(error_secret)
            raise RuntimeError("exception string hook")

    client = GeminiClient.__new__(GeminiClient)
    client.settings = {}
    client._last_token_usage = {}
    client._response_turn_usage_stack = []
    client.chat = SimpleNamespace(
        send_message=lambda _contents: (_ for _ in ()).throw(
            HostileProviderError(error_secret)
        )
    )
    client._build_memory_context = lambda *_args, **_kwargs: asyncio.sleep(
        0, result=""
    )
    client._create_web_search_decision_provider = lambda: None
    client._refresh_chat_session_for_runtime_prompt_if_needed = lambda: None
    client._log_turn_token_usage = lambda _response, label="": None
    monkeypatch.setattr(
        "PIL.Image.open", lambda _stream: SimpleNamespace(size=(1, 1))
    )

    result = asyncio.run(
        client.send_message_with_images(
            prompt_secret,
            [{"dataUrl": "data:image/png;base64,QUJD", "name": "synthetic.png"}],
        )
    )

    assert result[0] == "이미지를 처리하는 중에 문제가 생겼어요."
    combined = _combined_output(capsys)
    assert prompt_secret not in combined
    assert error_secret not in combined
    assert "category=multimodal_error" in combined
    assert "exception_class=HostileProviderError" in combined
    assert "Traceback" not in combined


def test_summary_logs_omit_summary_and_exception_content(capsys):
    summary_secret = "SYNTHETIC-GEMINI-PRIVATE-SUMMARY"
    exception_secret = "SYNTHETIC-GEMINI-PRIVATE-SUMMARY-ERROR"
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {}
    client.user_profile = None
    client.ene_profile = None
    client._request_summary_text = lambda _prompt: summary_secret
    client._parse_summary_response_with_topic_memory = lambda _response: (
        summary_secret,
        [],
        [],
        {},
        [],
    )

    result = asyncio.run(
        client.summarize_conversation([("user", "Synthetic input")])
    )
    assert summary_secret in result[0]
    assert summary_secret not in _combined_output(capsys)

    class HostileSummaryError(RuntimeError):
        def __str__(self):
            print(exception_secret)
            raise RuntimeError("exception string hook")

    client._request_summary_text = lambda _prompt: (_ for _ in ()).throw(
        HostileSummaryError(exception_secret)
    )
    fallback = asyncio.run(
        client.summarize_conversation([("user", "Synthetic failing input")])
    )

    assert fallback[0] == "대화 1개 메시지"
    combined = _combined_output(capsys)
    assert exception_secret not in combined
    assert "category=summary_error" in combined
    assert "exception_class=HostileSummaryError" in combined
    assert "Traceback" not in combined


def test_rollback_and_rebuild_errors_omit_exception_content(capsys):
    sentinel = "SYNTHETIC-GEMINI-PRIVATE-HISTORY-ERROR"

    class HostileHistoryError(RuntimeError):
        def __str__(self):
            print(sentinel)
            raise RuntimeError("exception string hook")

    rollback_client = GeminiClient.__new__(GeminiClient)
    rollback_client.get_conversation_history = lambda: [
        {"role": "user"},
        {"role": "model"},
    ]
    rollback_client._create_chat_session = lambda **_kwargs: (
        (_ for _ in ()).throw(HostileHistoryError(sentinel))
    )
    assert rollback_client.rollback_last_assistant_turn() is False

    rebuild_client = GeminiClient.__new__(GeminiClient)
    rebuild_client._create_chat_session = lambda **_kwargs: (
        (_ for _ in ()).throw(HostileHistoryError(sentinel))
    )
    assert (
        rebuild_client.rebuild_context_from_conversation(
            [("user", "Synthetic history content", "2099-01-01 00:00")]
        )
        is False
    )

    combined = _combined_output(capsys)
    assert sentinel not in combined
    assert "Traceback" not in combined
    assert "category=history_rollback_error" in combined
    assert "category=history_rebuild_error" in combined


@pytest.mark.parametrize("failure_stage", ["history_getter", "history_iter", "role"])
def test_rollback_catches_sdk_history_boundary_errors_without_stringifying(
    failure_stage,
    capsys,
):
    sentinel = f"SYNTHETIC-GEMINI-ROLLBACK-{failure_stage.upper()}"

    class HostileHistoryError(RuntimeError):
        def __str__(self):
            print(sentinel)
            raise RuntimeError("exception string hook")

    class HostileHistory:
        def __bool__(self):
            return True

        def __iter__(self):
            raise HostileHistoryError(sentinel)

    class HostileRoleItem:
        @property
        def role(self):
            raise HostileHistoryError(sentinel)

    client = GeminiClient.__new__(GeminiClient)
    if failure_stage == "history_getter":
        client.get_conversation_history = lambda: (_ for _ in ()).throw(
            HostileHistoryError(sentinel)
        )
    elif failure_stage == "history_iter":
        client.get_conversation_history = lambda: HostileHistory()
    else:
        client.get_conversation_history = lambda: [
            {"role": "user"},
            HostileRoleItem(),
        ]

    assert client.rollback_last_assistant_turn() is False

    combined = _combined_output(capsys)
    assert sentinel not in combined
    assert "Traceback" not in combined
    assert combined == "[LLM] category=history_rollback_error\n"


@pytest.mark.parametrize(
    ("goal_update", "expected_count"),
    [
        ({}, 0),
        ({"action": "synthetic"}, 1),
        ({"action": "synthetic", "title": "neutral"}, 1),
        (True, 0),
        (["synthetic"], 0),
    ],
)
def test_final_response_goal_count_matches_exact_nonempty_dict(
    goal_update,
    expected_count,
    capsys,
):
    client = GeminiClient.__new__(GeminiClient)
    payload = ("reply", "normal", None, [], {}, [], "", goal_update, [], "")

    client._log_final_response_metadata(payload, request_kind="text")

    assert f"goal_count={expected_count}" in _combined_output(capsys)


def test_final_response_goal_count_ignores_hostile_dict_subclass_methods(capsys):
    sentinel = "SYNTHETIC-GEMINI-HOSTILE-GOAL-DICT"

    class HostileGoalDict(dict):
        def _fail(self):
            print(sentinel)
            raise RuntimeError("goal hook")

        def __bool__(self):
            return self._fail()

        def __len__(self):
            return self._fail()

        def __str__(self):
            return self._fail()

        def __format__(self, _spec):
            return self._fail()
        def __repr__(self):
            return self._fail()


    client = GeminiClient.__new__(GeminiClient)
    goal_update = HostileGoalDict(action="synthetic")
    payload = ("reply", "normal", None, [], {}, [], "", goal_update, [], "")

    client._log_final_response_metadata(payload, request_kind="text")

    combined = _combined_output(capsys)
    assert sentinel not in combined
    assert "goal_count=0" in combined


def test_token_usage_log_rejects_untrusted_label_formatting(capsys):
    sentinel = "SYNTHETIC-GEMINI-PRIVATE-TOKEN-LABEL"

    class HostileLabel:
        def __format__(self, _spec):
            print(sentinel)
            raise RuntimeError("label format hook")

        def __str__(self):
            print(sentinel)
            raise RuntimeError("label string hook")

    client = GeminiClient.__new__(GeminiClient)
    client._last_token_usage = None

    client._log_turn_token_usage(
        {
            "usage_metadata": {
                "prompt_token_count": 3,
                "candidates_token_count": 2,
                "total_token_count": 5,
            }
        },
        label=HostileLabel(),
    )

    combined = _combined_output(capsys)
    assert sentinel not in combined
    assert "category=token_usage" in combined
    assert "input=3" in combined
    assert "output=2" in combined
    assert "total=5" in combined
