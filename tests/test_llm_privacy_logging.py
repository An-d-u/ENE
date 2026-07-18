import asyncio
import json
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication

from src.ai.calendar_manager import CalendarManager
from src.ai.memory_context_builder import build_memory_context
from src.ai.response_protocol import ResponseDeliveryMetadata
from src.core.bridge_mixins.chat_flow import ChatFlowBridgeMixin
from src.core.bridge_mixins.goals import GoalBridgeMixin
from src.core.bridge_mixins.obsidian import ObsidianBridgeMixin
from src.core.bridge_mixins.tts import TTSBridgeMixin
from src.core.bridge_workers import (
    AIWorker,
    ObsidianCheckedFilesWorker,
    ObsidianTreeWorker,
    StreamingTTSWorker,
    TTSWorker,
)
from tests.test_bridge_promise_reminders import build_promise_bridge_dummy


SAFE_METADATA = ResponseDeliveryMetadata(
    response_mode="json_schema",
    schema_version="1",
    promises_authoritative=True,
    repair_performed=False,
)


def _ensure_qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def _combined_output(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


class _LoggingClient:
    def __init__(self, payload):
        self.payload = payload

    def send_message(self, _message):
        return self.payload

    def get_last_response_delivery_metadata(self):
        return SAFE_METADATA

    def get_last_token_usage(self):
        return {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}


def test_final_reply_logs_are_content_free_and_include_current_metadata(capsys):
    _ensure_qt_app()
    secrets = {
        "user": "SYNTHETIC-USER-CONTENT-SENTINEL",
        "reply": "SYNTHETIC-REPLY-CONTENT-SENTINEL",
        "tts": "SYNTHETIC-TTS-CONTENT-SENTINEL",
        "thought": "SYNTHETIC-THOUGHT-CONTENT-SENTINEL",
        "analysis": "SYNTHETIC-ANALYSIS-CONTENT-SENTINEL",
        "event": "SYNTHETIC-EVENT-CONTENT-SENTINEL",
        "promise": "SYNTHETIC-PROMISE-CONTENT-SENTINEL",
        "goal": "SYNTHETIC-GOAL-CONTENT-SENTINEL",
        "proactive": "SYNTHETIC-PROACTIVE-CONTENT-SENTINEL",
    }
    payload = (
        secrets["reply"],
        "normal",
        secrets["tts"],
        [{"date": "2099-12-31", "title": secrets["event"], "description": ""}],
        {"user_intent": secrets["analysis"]},
        [{"title": secrets["promise"]}],
        secrets["thought"],
        {"action": "create", "title": secrets["goal"]},
        [{"title": secrets["proactive"]}],
        "nod",
    )

    worker = AIWorker(_LoggingClient(payload), secrets["user"], use_memory=False)
    worker.run()

    combined = _combined_output(capsys)
    for secret in secrets.values():
        assert secret not in combined
    assert "2099-12-31" not in combined
    assert "response_mode=json_schema" in combined
    assert "schema_version=1" in combined
    assert "repair_performed=false" in combined
    assert "reply_chars=32" in combined
    assert "event_count=1" in combined
    assert "goal_item_count=1" in combined


def test_provider_error_log_and_signal_omit_raw_exception_content(capsys):
    _ensure_qt_app()
    raw_error = "SYNTHETIC-PROVIDER-ERROR-BODY-SENTINEL"

    class FailingClient:
        def send_message(self, _message):
            raise RuntimeError(raw_error)

    errors = []
    worker = AIWorker(FailingClient(), "SYNTHETIC-PROVIDER-INPUT-SENTINEL", use_memory=False)
    worker.error_occurred.connect(errors.append)
    worker.run()

    combined = _combined_output(capsys)
    assert raw_error not in combined
    assert "SYNTHETIC-PROVIDER-INPUT-SENTINEL" not in combined
    assert "Traceback" not in combined
    assert "category=provider_error" in combined
    assert "exception_class=RuntimeError" in combined
    assert errors == ["provider_error"]


@pytest.mark.parametrize(
    ("llm_client", "expected_message"),
    [
        (
            object(),
            "현재 LLM 클라이언트는 /note 계획 생성을 지원하지 않습니다.",
        ),
        (
            SimpleNamespace(generate_note_command_plan=lambda *_args, **_kwargs: None),
            "현재 LLM 클라이언트는 /note 결과 보고 생성을 지원하지 않습니다.",
        ),
    ],
)
def test_note_capability_validation_keeps_fixed_user_message_and_safe_category(
    capsys,
    llm_client,
    expected_message,
):
    _ensure_qt_app()
    errors = []
    worker = AIWorker(
        llm_client,
        "SYNTHETIC-NOTE-MESSAGE-SENTINEL",
        note_request="SYNTHETIC-NOTE-REQUEST-SENTINEL",
        note_service=object(),
        obsidian_manager=object(),
    )
    worker.error_occurred.connect(errors.append)

    worker.run()

    combined = _combined_output(capsys)
    assert errors == [expected_message]
    assert expected_message not in combined
    assert "SYNTHETIC-NOTE-MESSAGE-SENTINEL" not in combined
    assert "SYNTHETIC-NOTE-REQUEST-SENTINEL" not in combined
    assert "category=validation_error" in combined


def test_obsidian_tree_worker_error_signal_uses_fixed_category(capsys):
    _ensure_qt_app()
    raw_error = "SYNTHETIC-OBSIDIAN-TREE-ERROR-SENTINEL"

    class FailingManager:
        def get_tree_json(self, **_kwargs):
            raise RuntimeError(raw_error)

    errors = []
    worker = ObsidianTreeWorker(FailingManager())
    worker.error_occurred.connect(errors.append)

    worker.run()

    combined = _combined_output(capsys)
    assert raw_error not in combined
    assert raw_error not in str(errors)
    assert errors == ["obsidian_tree_error"]


def test_obsidian_checked_files_worker_error_signal_omits_exception_and_paths(capsys):
    _ensure_qt_app()
    raw_error = "SYNTHETIC-OBSIDIAN-CHECKED-ERROR-SENTINEL"
    private_path = "private/SYNTHETIC-OBSIDIAN-PATH-SENTINEL.md"

    class FailingManager:
        def get_checked_file_contents(self, **_kwargs):
            raise RuntimeError(raw_error)

    errors = []
    worker = ObsidianCheckedFilesWorker(FailingManager(), [private_path])
    worker.error_occurred.connect(lambda category, signature: errors.append((category, signature)))

    worker.run()

    combined = _combined_output(capsys)
    assert raw_error not in combined
    assert private_path not in combined
    assert raw_error not in str(errors)
    assert private_path not in str(errors)
    assert errors == [("obsidian_checked_files_error", "")]


def test_tts_worker_logs_and_signal_omit_text_and_provider_error(capsys):
    _ensure_qt_app()
    text = "SYNTHETIC-TTS-WORKER-TEXT-SENTINEL"
    raw_error = "SYNTHETIC-TTS-PROVIDER-ERROR-SENTINEL"

    class FailingClient:
        async def generate_speech(self, _text):
            raise RuntimeError(raw_error)

    errors = []
    worker = TTSWorker(FailingClient(), text)
    worker.error_occurred.connect(errors.append)
    worker.run()

    combined = _combined_output(capsys)
    assert text not in combined
    assert raw_error not in combined
    assert "Traceback" not in combined
    assert "category=tts_error" in combined
    assert "exception_class=RuntimeError" in combined
    assert errors == ["tts_error"]


def test_streaming_tts_worker_logs_and_signal_omit_text_and_provider_error(capsys):
    _ensure_qt_app()
    text = "SYNTHETIC-STREAMING-TTS-TEXT-SENTINEL"
    raw_error = "SYNTHETIC-STREAMING-TTS-ERROR-SENTINEL"

    class FailingClient:
        async def stream_speech(self, _text):
            if False:
                yield b""
            raise RuntimeError(raw_error)

    errors = []
    worker = StreamingTTSWorker(FailingClient(), text)
    worker.error_occurred.connect(errors.append)
    worker.run()

    combined = _combined_output(capsys)
    assert text not in combined
    assert raw_error not in combined
    assert "Traceback" not in combined
    assert "category=tts_stream_error" in combined
    assert "exception_class=RuntimeError" in combined
    assert errors == ["tts_stream_error"]


def test_calendar_manager_logs_omit_schedule_content(capsys, tmp_path):
    event_date = "2099-10-23"
    event_title = "SYNTHETIC-CALENDAR-TITLE-SENTINEL"
    event_description = "SYNTHETIC-CALENDAR-DESCRIPTION-SENTINEL"
    manager = CalendarManager(tmp_path / "calendar.json")

    event = manager.add_event(event_date, event_title, event_description)

    combined = _combined_output(capsys)
    assert event.title == event_title
    assert event.description == event_description
    assert event_date not in combined
    assert event_title not in combined
    assert event_description not in combined
    assert "category=event_added" in combined


def test_memory_context_logs_omit_memory_and_provider_exception_content(capsys):
    memory_secret = "SYNTHETIC-MEMORY-CONTENT-SENTINEL"
    raw_error = "SYNTHETIC-MEMORY-PROVIDER-ERROR-SENTINEL"
    memory = SimpleNamespace(summary=memory_secret, timestamp="2099-08-14T12:00:00")

    class MemoryManager:
        def get_important(self):
            return [memory]

        async def find_similar(self, *_args, **_kwargs):
            raise RuntimeError(raw_error)

        def get_recent(self, count=2):
            return [memory]

    client = SimpleNamespace(
        settings={
            "ui_language": "ko",
            "memory_activation_enabled": False,
            "max_raw_chunks_in_context": 0,
            "max_topic_memory_context": 0,
        },
        memory_manager=MemoryManager(),
    )

    context = asyncio.run(build_memory_context(client, "SYNTHETIC-MEMORY-QUERY-SENTINEL"))

    combined = _combined_output(capsys)
    assert memory_secret in context
    assert memory_secret not in combined
    assert raw_error not in combined
    assert "SYNTHETIC-MEMORY-QUERY-SENTINEL" not in combined
    assert "2099-08-14" not in combined
    assert "Traceback" not in combined
    assert "category=memory_search_failed" in combined
    assert "exception_class=RuntimeError" in combined


def test_goal_logs_omit_goal_fields_and_exception_content(capsys):
    goal_type = "short_term"
    title = "SYNTHETIC-GOAL-TITLE-SENTINEL"
    reason = "SYNTHETIC-GOAL-REASON-SENTINEL"
    raw_error = "SYNTHETIC-GOAL-ERROR-SENTINEL"

    class FailingGoalManager:
        def add_manual_goal(self, _goal_type, _title, _reason):
            raise RuntimeError(raw_error)

    class Signal:
        def __init__(self):
            self.emitted = []

        def emit(self, *args):
            self.emitted.append(args)

    bridge = SimpleNamespace(goal_manager=FailingGoalManager(), goal_notice=Signal())

    GoalBridgeMixin.add_manual_goal(bridge, goal_type, title, reason)

    combined = _combined_output(capsys)
    assert title not in combined
    assert reason not in combined
    assert raw_error not in combined
    assert "category=goal_add_failed" in combined
    assert "exception_class=RuntimeError" in combined
    assert bridge.goal_notice.emitted == [("목표 추가 중 오류가 발생했어요.", "error")]

def test_provider_exception_string_hook_is_never_invoked(capsys):
    _ensure_qt_app()
    secret = "SYNTHETIC-EXCEPTION-STRING-HOOK-SENTINEL"

    class LeakyError(RuntimeError):
        def __str__(self):
            print(secret)
            return secret

    class FailingClient:
        def send_message(self, _message):
            raise LeakyError(secret)

    errors = []
    worker = AIWorker(FailingClient(), "safe input", use_memory=False)
    worker.error_occurred.connect(errors.append)

    worker.run()

    combined = _combined_output(capsys)
    assert secret not in combined
    assert errors == ["provider_error"]


def test_response_metadata_logs_only_allowlisted_fixed_values(capsys):
    _ensure_qt_app()
    mode_secret = "SYNTHETIC-METADATA-MODE-SENTINEL"
    schema_secret = "SYNTHETIC-METADATA-SCHEMA-SENTINEL"
    repair_secret = "SYNTHETIC-METADATA-REPAIR-SENTINEL"

    class LeakyRepairFlag:
        def __str__(self):
            print(repair_secret)
            return repair_secret

    metadata = ResponseDeliveryMetadata(
        response_mode=mode_secret,
        schema_version=schema_secret,
        promises_authoritative=False,
        repair_performed=LeakyRepairFlag(),
    )

    class MetadataClient(_LoggingClient):
        def get_last_response_delivery_metadata(self):
            return metadata

    payload = ("safe reply", "normal", "", [], {}, [], "", {}, [], "")
    worker = AIWorker(MetadataClient(payload), "safe input", use_memory=False)

    worker.run()

    combined = _combined_output(capsys)
    assert mode_secret not in combined
    assert schema_secret not in combined
    assert repair_secret not in combined
    assert "response_mode=unknown" in combined
    assert "schema_version=none" in combined
    assert "repair_performed=false" in combined


def test_response_log_counts_do_not_invoke_custom_string_or_length_hooks(capsys):
    _ensure_qt_app()
    secret = "SYNTHETIC-RESPONSE-LOG-HOOK-SENTINEL"

    class LeakyText(str):
        def __str__(self):
            print(secret)
            return secret

    class LeakyList(list):
        def __len__(self):
            print(secret)
            return super().__len__()

    payload = (
        LeakyText("safe reply"),
        "normal",
        LeakyText("safe tts"),
        LeakyList([{"date": "2099-01-01"}]),
        {},
        LeakyList([{"title": "safe promise"}]),
        LeakyText("safe thought"),
        {"action": "none"},
        LeakyList([{"title": "safe proactive"}]),
        "",
    )
    worker = AIWorker(_LoggingClient(payload), LeakyText("safe input"), use_memory=False)

    worker.run()

    combined = _combined_output(capsys)
    assert secret not in combined
    assert "message_chars=0" in combined
    assert "reply_chars=0" in combined
    assert "tts_chars=0" in combined
    assert "thought_chars=0" in combined
    assert "event_count=0" in combined
    assert "promise_count=0" in combined
    assert "proactive_count=0" in combined


def test_browser_tts_error_does_not_invoke_exception_string_hook(capsys):
    secret = "SYNTHETIC-BROWSER-TTS-EXCEPTION-HOOK-SENTINEL"

    class LeakyError(RuntimeError):
        def __str__(self):
            print(secret)
            return secret

    class FailingClient:
        def build_request(self, _text):
            raise LeakyError(secret)

    errors = []
    bridge = SimpleNamespace(
        tts_client=FailingClient(),
        _on_tts_error=errors.append,
    )

    TTSBridgeMixin._play_browser_tts(bridge, "safe tts input")

    combined = _combined_output(capsys)
    assert secret not in combined
    assert errors == ["tts_error"]


def test_memory_selection_logs_do_not_format_provider_scores(capsys):
    memory_secret = "SYNTHETIC-MEMORY-SCORE-FORMAT-SENTINEL"
    memory = SimpleNamespace(summary="safe memory", timestamp="2099-08-14T12:00:00")
    chunk = SimpleNamespace(start_turn_index=1, end_turn_index=2, text="safe chunk")

    class LeakyScore:
        def __format__(self, _format_spec):
            print(memory_secret)
            return memory_secret

    class MemoryManager:
        def get_important(self):
            return []

        async def find_similar(self, *_args, **_kwargs):
            return [(memory, LeakyScore())]

        async def find_relevant_raw_chunks(self, *_args, **_kwargs):
            return [
                (
                    chunk,
                    LeakyScore(),
                    {
                        "primary_similarity": LeakyScore(),
                        "support_similarity": LeakyScore(),
                        "keyword_score": LeakyScore(),
                    },
                )
            ]

        def get_recent(self, count=2):
            return []

    client = SimpleNamespace(
        settings={
            "ui_language": "ko",
            "memory_activation_enabled": False,
            "max_raw_chunks_in_context": 1,
            "max_topic_memory_context": 0,
        },
        memory_manager=MemoryManager(),
    )

    context = asyncio.run(build_memory_context(client, "safe query"))

    combined = _combined_output(capsys)
    assert "safe memory" in context
    assert "safe chunk" in context
    assert memory_secret not in combined
    assert "[LLM] similar_memory_selected" in combined
    assert "[LLM] raw_chunk_selected index=1" in combined


def test_token_usage_payload_rejects_bool_negative_and_unsafe_integer_counts():
    payload = ("safe reply", "normal", "", [], {}, [], "", {}, [], "")

    class InvalidUsageClient(_LoggingClient):
        def get_last_token_usage(self):
            return {
                "input_tokens": True,
                "output_tokens": -1,
                "total_tokens": 9_007_199_254_740_992,
            }

    emitted = []
    worker = AIWorker(InvalidUsageClient(payload), "safe input", use_memory=False)
    worker.response_ready.connect(lambda *args: emitted.append(args))

    worker.run()

    assert json.loads(emitted[0][5]) == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }

    bridge = SimpleNamespace(llm_client=InvalidUsageClient(payload))
    normalized = TTSBridgeMixin._resolve_token_usage_payload(
        bridge,
        '{"input_tokens": true, "output_tokens": -1, "total_tokens": 9007199254740992}',
    )
    assert json.loads(normalized) == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_checked_files_error_without_signature_does_not_schedule_refresh(capsys):
    raw_error = "SYNTHETIC-CHECKED-FILES-CONSUMER-ERROR-SENTINEL"
    refreshes = []
    bridge = SimpleNamespace(
        _decode_checked_files_signature=lambda _payload: tuple(),
        _get_checked_files_signature=lambda: ("private/safe.md",),
        _schedule_checked_files_context_refresh=lambda **kwargs: refreshes.append(kwargs),
    )

    ObsidianBridgeMixin._on_checked_files_context_error(
        bridge,
        raw_error,
        "",
    )

    combined = _combined_output(capsys)
    assert raw_error not in combined
    assert "private/safe.md" not in combined
    assert refreshes == []


def test_checked_files_error_with_stale_signature_keeps_force_refresh_behavior(capsys):
    refreshes = []
    bridge = SimpleNamespace(
        _decode_checked_files_signature=lambda _payload: ("synthetic/old.md",),
        _get_checked_files_signature=lambda: ("synthetic/current.md",),
        _schedule_checked_files_context_refresh=lambda **kwargs: refreshes.append(kwargs),
    )

    ObsidianBridgeMixin._on_checked_files_context_error(
        bridge,
        "obsidian_checked_files_error",
        '["synthetic/old.md"]',
    )

    combined = _combined_output(capsys)
    assert "synthetic/old.md" not in combined
    assert "synthetic/current.md" not in combined
    assert refreshes == [{"force": True}]


def test_promises_authoritative_logical_check_does_not_invoke_custom_bool(capsys):
    secret = "SYNTHETIC-PROMISE-METADATA-BOOL-SENTINEL"

    class LeakyBool:
        def __bool__(self):
            print(secret)
            return True

    metadata = ResponseDeliveryMetadata(
        response_mode="json_schema",
        schema_version="1",
        promises_authoritative=LeakyBool(),
        repair_performed=False,
    )
    bridge = build_promise_bridge_dummy(response_metadata=metadata)
    fallback_calls = []
    bridge._maybe_store_user_promise_candidates = (
        lambda _items=None: fallback_calls.append("user") or []
    )
    bridge._maybe_store_assistant_promise_candidates = (
        lambda _text: fallback_calls.append("assistant") or []
    )

    ChatFlowBridgeMixin._handle_response_ready(
        bridge,
        text="safe reply",
        emotion="normal",
        tts_text="",
        events=[],
        analysis_payload="",
        token_usage_payload="",
        scheduled_promises=[],
        thought="",
        goal_update_payload="",
        proactive_conversations=[],
        gesture="",
        response_metadata=metadata,
    )

    combined = _combined_output(capsys)
    assert secret not in combined
    assert fallback_calls == ["user", "assistant"]
