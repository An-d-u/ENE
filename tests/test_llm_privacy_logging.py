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


class _ObsidianPrivacySignal:
    def __init__(self, *, fail=False):
        self.emitted = []
        self.fail = fail

    def emit(self, *args):
        if self.fail:
            raise _ObsidianLeakyError("SYNTHETIC-OBSIDIAN-SIGNAL-SENTINEL")
        self.emitted.append(args)


class _ObsidianLeakyError(RuntimeError):
    string_calls = 0
    repr_calls = 0

    def __str__(self):
        type(self).string_calls += 1
        print(self.args[0])
        return self.args[0]

    def __repr__(self):
        type(self).repr_calls += 1
        print(self.args[0])
        return self.args[0]


@pytest.fixture(autouse=False)
def reset_obsidian_leaky_error_hooks():
    _ObsidianLeakyError.string_calls = 0
    _ObsidianLeakyError.repr_calls = 0


def _assert_obsidian_exception_was_not_rendered(capsys, secret):
    combined = _combined_output(capsys)
    assert secret not in combined
    assert _ObsidianLeakyError.string_calls == 0
    assert _ObsidianLeakyError.repr_calls == 0
    return combined


def test_obsidian_cache_validation_error_does_not_render_exception(
    capsys,
    reset_obsidian_leaky_error_hooks,
):
    secret = "SYNTHETIC-OBSIDIAN-CACHE-ERROR-SENTINEL"

    class FailingManager:
        def build_tree(self, **_kwargs):
            raise _ObsidianLeakyError(secret)

    invalidations = []
    bridge = SimpleNamespace(
        obsidian_manager=FailingManager(),
        _invalidate_checked_files_context_cache=lambda: invalidations.append(True),
    )

    valid = ObsidianBridgeMixin._validate_cached_checked_files_context(
        bridge,
        ("synthetic/note.md",),
    )

    combined = _assert_obsidian_exception_was_not_rendered(capsys, secret)
    assert valid is False
    assert invalidations == [True]
    assert "category=obsidian_cache_validation_error" in combined


@pytest.mark.parametrize("failing_stage", ["settings", "signal"])
def test_obsidian_cache_cleanup_errors_do_not_render_exceptions(
    capsys,
    reset_obsidian_leaky_error_hooks,
    failing_stage,
):
    secret = f"SYNTHETIC-OBSIDIAN-{failing_stage.upper()}-ERROR-SENTINEL"

    class Manager:
        def build_tree(self, **_kwargs):
            return {"ok": True, "checked_files": [], "nodes": []}

    class Settings:
        def set_checked_files(self, _files):
            if failing_stage == "settings":
                raise _ObsidianLeakyError(secret)

    signal = _ObsidianPrivacySignal(fail=failing_stage == "signal")
    if failing_stage == "signal":
        secret = "SYNTHETIC-OBSIDIAN-SIGNAL-SENTINEL"
    invalidations = []
    bridge = SimpleNamespace(
        obsidian_manager=Manager(),
        obs_settings=Settings(),
        obs_tree_updated=signal,
        _cached_obs_tree_json="{}",
        _invalidate_checked_files_context_cache=lambda: invalidations.append(True),
        _schedule_checked_files_context_refresh=lambda **_kwargs: None,
    )

    valid = ObsidianBridgeMixin._validate_cached_checked_files_context(
        bridge,
        ("synthetic/old.md",),
    )

    combined = _assert_obsidian_exception_was_not_rendered(capsys, secret)
    assert valid is False
    assert invalidations == [True]
    expected_category = {
        "settings": "obsidian_checked_files_cleanup_error",
        "signal": "obsidian_tree_signal_error",
    }[failing_stage]
    assert f"category={expected_category}" in combined


@pytest.mark.parametrize(
    ("command", "expected_message"),
    [
        ("read", "파일을 읽는 중 오류가 발생했어요."),
        ("summarize", "요약할 파일을 읽는 중 오류가 발생했어요."),
    ],
)
def test_obsidian_read_errors_use_fixed_safe_user_messages(
    capsys,
    reset_obsidian_leaky_error_hooks,
    command,
    expected_message,
):
    secret = f"SYNTHETIC-OBSIDIAN-{command.upper()}-ERROR-SENTINEL"

    class FailingManager:
        def read_file(self, _path):
            raise _ObsidianLeakyError(secret)

    messages = _ObsidianPrivacySignal()
    bridge = SimpleNamespace(
        mood_manager=None,
        obsidian_manager=FailingManager(),
        message_received=messages,
        _cancel_pending_proactive_conversations_for_user_message=lambda: None,
        _mark_user_activity=lambda: None,
        _activate_obsidian_integration=lambda: None,
        _parse_obs_subcommand=lambda _body: (command, {"path": "synthetic/note.md"}),
        _build_obsidian_context_block=lambda **_kwargs: "safe context",
        _now_timestamp=lambda: "2099-01-01 00:00",
        _prompt_language=lambda: "ko",
        _last_request_payload=None,
        _is_rerolling=False,
    )

    handled = ObsidianBridgeMixin._handle_obs_command(
        bridge,
        f"/obs {command} synthetic/note.md",
    )

    _assert_obsidian_exception_was_not_rendered(capsys, secret)
    assert handled is True
    assert messages.emitted == [(expected_message, "confused", "")]


def test_obsidian_checked_files_json_error_is_fixed_and_content_free(
    capsys,
    reset_obsidian_leaky_error_hooks,
):
    secret = "SYNTHETIC-OBSIDIAN-CHECKED-JSON-ERROR-SENTINEL"

    class FailingSettings:
        def get_checked_files(self):
            raise _ObsidianLeakyError(secret)

    bridge = SimpleNamespace(obs_settings=FailingSettings())

    payload = ObsidianBridgeMixin.get_obs_checked_files_json(bridge)

    _assert_obsidian_exception_was_not_rendered(capsys, secret)
    assert json.loads(payload) == {
        "checked_files": [],
        "error": "체크 파일 목록을 불러오지 못했어요.",
    }


def test_obsidian_checked_state_error_log_does_not_render_exception(
    capsys,
    reset_obsidian_leaky_error_hooks,
):
    secret = "SYNTHETIC-OBSIDIAN-CHECKED-STATE-ERROR-SENTINEL"

    class FailingSettings:
        def set_file_checked(self, _path, _checked):
            raise _ObsidianLeakyError(secret)

    bridge = SimpleNamespace(obs_settings=FailingSettings())

    ObsidianBridgeMixin.set_obs_file_checked(bridge, "synthetic/private.md", True)

    combined = _assert_obsidian_exception_was_not_rendered(capsys, secret)
    assert "synthetic/private.md" not in combined
    assert "category=obsidian_checked_state_error" in combined


def test_obsidian_panel_error_log_does_not_render_exception(
    capsys,
    reset_obsidian_leaky_error_hooks,
):
    secret = "SYNTHETIC-OBSIDIAN-PANEL-ERROR-SENTINEL"

    class FailingPanel:
        def isVisible(self):
            raise _ObsidianLeakyError(secret)

    bridge = SimpleNamespace(obs_panel_window=FailingPanel())

    ObsidianBridgeMixin.toggle_obs_panel(bridge)

    combined = _assert_obsidian_exception_was_not_rendered(capsys, secret)
    assert "category=obsidian_panel_error" in combined


def test_obsidian_tree_error_signal_uses_fixed_safe_message(capsys):
    secret = "SYNTHETIC-OBSIDIAN-TREE-CONSUMER-ERROR-SENTINEL"
    signal = _ObsidianPrivacySignal()
    retries = []
    bridge = SimpleNamespace(
        _cached_obs_tree_json="{}",
        obs_tree_updated=signal,
        _schedule_obs_tree_retry_if_needed=lambda: retries.append(True),
    )

    ObsidianBridgeMixin._on_obs_tree_error(bridge, secret)

    combined = _combined_output(capsys)
    assert secret not in combined
    assert secret not in str(signal.emitted)
    assert json.loads(signal.emitted[0][0]) == {
        "ok": False,
        "error": "Obsidian 트리를 불러오지 못했어요.",
        "nodes": [],
    }
    assert retries == [True]


@pytest.mark.parametrize(
    ("command", "ok", "expected_message"),
    [
        ("append", True, "추가 완료"),
        ("append", False, "추가 실패"),
        ("replace", True, "교체 완료"),
        ("replace", False, "교체 실패"),
    ],
)
def test_obsidian_operation_results_do_not_emit_raw_message_or_path(
    capsys,
    command,
    ok,
    expected_message,
):
    secret = f"SYNTHETIC-OBSIDIAN-{command.upper()}-MESSAGE-SENTINEL"
    unsafe_path = f"C:/private/{command}-path-sentinel.md"
    result = SimpleNamespace(ok=ok, message=secret, path=unsafe_path)

    class Manager:
        def append_file(self, *_args, **_kwargs):
            return result

        def replace_in_file(self, *_args, **_kwargs):
            return result

    payload = {
        "path": "synthetic/note.md",
        "content": "synthetic content",
        "before": "synthetic before",
        "after": "synthetic after",
    }
    messages = _ObsidianPrivacySignal()
    invalidations = []
    bridge = SimpleNamespace(
        mood_manager=None,
        obsidian_manager=Manager(),
        message_received=messages,
        _cancel_pending_proactive_conversations_for_user_message=lambda: None,
        _mark_user_activity=lambda: None,
        _activate_obsidian_integration=lambda: None,
        _parse_obs_subcommand=lambda _body: (command, payload),
        _invalidate_checked_files_context_cache=lambda: invalidations.append(True),
        _last_request_payload=None,
        _is_rerolling=False,
    )

    handled = ObsidianBridgeMixin._handle_obs_command(
        bridge,
        f"/obs {command} synthetic/note.md",
    )

    combined = _combined_output(capsys)
    assert handled is True
    assert secret not in combined
    assert unsafe_path not in combined
    assert secret not in str(messages.emitted)
    assert unsafe_path not in str(messages.emitted)
    assert messages.emitted == [(expected_message, "smile" if ok else "confused", "")]
    assert invalidations == ([True] if ok else [])


@pytest.mark.parametrize(
    ("command", "label"),
    [
        ("append", "추가 완료"),
        ("replace", "교체 완료"),
    ],
)
def test_obsidian_success_result_keeps_safe_relative_path(command, label):
    safe_path = "synthetic/folder/note.md"
    result = SimpleNamespace(
        ok=True,
        message="SYNTHETIC-OBSIDIAN-SUCCESS-MESSAGE-SENTINEL",
        path=safe_path,
    )

    class Manager:
        def append_file(self, *_args, **_kwargs):
            return result

        def replace_in_file(self, *_args, **_kwargs):
            return result

    payload = {
        "path": safe_path,
        "content": "synthetic content",
        "before": "synthetic before",
        "after": "synthetic after",
    }
    messages = _ObsidianPrivacySignal()
    bridge = SimpleNamespace(
        mood_manager=None,
        obsidian_manager=Manager(),
        message_received=messages,
        _cancel_pending_proactive_conversations_for_user_message=lambda: None,
        _mark_user_activity=lambda: None,
        _activate_obsidian_integration=lambda: None,
        _parse_obs_subcommand=lambda _body: (command, payload),
        _invalidate_checked_files_context_cache=lambda: None,
        _last_request_payload=None,
        _is_rerolling=False,
    )

    handled = ObsidianBridgeMixin._handle_obs_command(
        bridge,
        f"/obs {command} {safe_path}",
    )

    assert handled is True
    assert messages.emitted == [(f"{label}: {safe_path}", "smile", "")]


def test_obsidian_failed_tree_payload_is_sanitized_before_signal(capsys):
    secret = "SYNTHETIC-OBSIDIAN-TREE-PAYLOAD-SENTINEL"
    signal = _ObsidianPrivacySignal()
    retries = []
    bridge = SimpleNamespace(
        _cached_obs_tree_json="{}",
        obs_tree_updated=signal,
        _schedule_obs_tree_retry_if_needed=lambda: retries.append(True),
    )

    ObsidianBridgeMixin._on_obs_tree_ready(
        bridge,
        json.dumps({"ok": False, "error": secret, "nodes": []}),
    )

    combined = _combined_output(capsys)
    assert secret not in combined
    assert secret not in bridge._cached_obs_tree_json
    assert secret not in str(signal.emitted)
    assert json.loads(signal.emitted[0][0])["error"] == "Obsidian 트리를 불러오지 못했어요."
    assert retries == [True]


def test_obsidian_cached_tree_error_is_sanitized_before_checked_files_signal():
    secret = "SYNTHETIC-OBSIDIAN-CACHED-TREE-ERROR-SENTINEL"
    signal = _ObsidianPrivacySignal()
    bridge = SimpleNamespace(
        _cached_obs_tree_json=json.dumps({"ok": False, "error": secret, "nodes": []}),
        obs_settings=SimpleNamespace(get_checked_files=lambda: ["synthetic/note.md"]),
        obs_tree_updated=signal,
    )

    ObsidianBridgeMixin._emit_obs_tree_with_updated_checked_files(bridge)

    assert secret not in bridge._cached_obs_tree_json
    assert secret not in str(signal.emitted)
    assert json.loads(signal.emitted[0][0])["error"] == "Obsidian 트리를 불러오지 못했어요."
