import asyncio
import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.ai.life_record_types import create_life_record, stable_life_record_id
from src.ai.http_llm_clients import (
    AnthropicClient,
    CohereClient,
    GoogleCloudClient,
    MistralClient,
    OllamaClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)
from src.ai.http_llm_common import _CommonMixin
from src.ai.llm_client import GeminiClient
from src.ai.llm_provider import LLMClientProtocol
from src.ai import memory_context_builder
from src.core.bridge_workers import AIWorker
from src.core.bridge_mixins.attachments import AttachmentBridgeMixin


build_memory_context = memory_context_builder.build_memory_context


def _build_life_record_context_block(**kwargs):
    builder = getattr(memory_context_builder, "build_life_record_context_block", None)
    assert callable(builder), "생활 기록 임시 컨텍스트 빌더가 필요합니다."
    return builder(**kwargs)


SEOUL = ZoneInfo("Asia/Seoul")


def _record(*, day: int, activity: str):
    start = datetime(2099, 8, day, 7, 0, tzinfo=SEOUL)
    end = datetime(2099, 8, day, 8, 0, tzinfo=SEOUL)
    return create_life_record(
        id=stable_life_record_id(start, end),
        inactive_started_at=start,
        returned_at=end,
        created_at=end,
        updated_at=end,
        revision=1,
        timezone="Asia/Seoul",
        inactive_start_source="graceful_exit",
        mood_snapshot={
            "label": "차분함",
            "valence": 0.1,
            "energy": 0.2,
            "bond": 0.3,
            "stress": 0.1,
            "short_term_mood": "안정적",
        },
        entries=[
            {
                "started_at": start,
                "ended_at": end,
                "place": "합성 온실",
                "activity": activity,
            }
        ],
        ending_state={"place": "합성 온실", "summary": "정리를 마쳤다."},
    )


class _Manager:
    def __init__(self, records):
        self.records = tuple(records)

    def latest(self):
        return self.records[0] if self.records else None


class _BrokenManager:
    def latest(self):
        raise RuntimeError("SYNTHETIC-PRIVATE-STORE-DETAIL")


class _CountingManager(_Manager):
    def __init__(self, records):
        super().__init__(records)
        self.latest_calls = 0

    def latest(self):
        self.latest_calls += 1
        return super().latest()


class _Client:
    def __init__(self, *, enabled=True, records=(), memory_manager=None):
        self.settings = {"enable_life_records": enabled, "locale": "ko"}
        self.life_record_manager = _Manager(records)
        self.memory_manager = memory_manager


def test_life_record_block_contains_only_latest_public_safe_record():
    latest = _record(day=7, activity="최신 합성 활동")

    block = _build_life_record_context_block(enabled=True, latest_record=latest)

    assert "최신 합성 활동" in block
    assert "정리를 마쳤다." in block
    assert "mood_snapshot" not in block
    assert latest.id not in block
    assert "graceful_exit" not in block
    assert "revision" not in block
    assert "과거 합성 활동" not in block


@pytest.mark.parametrize(
    ("enabled", "records", "expected"),
    [
        (False, (_record(day=7, activity="비활성 기록"),), False),
        (True, (), False),
        (True, (_record(day=7, activity="최신 기록"),), True),
    ],
)
def test_memory_context_requires_explicit_opt_in_and_preserves_early_return(
    enabled,
    records,
    expected,
):
    client = _Client(enabled=enabled, records=records, memory_manager=None)

    default_context = asyncio.run(build_memory_context(client, "합성 질의"))
    opted_in_context = asyncio.run(
        build_memory_context(
            client,
            "합성 질의",
            include_life_record_context=True,
        )
    )

    assert "최신 생활 기록" not in default_context
    assert ("최신 생활 기록" in opted_in_context) is expected


def test_memory_context_reads_latest_at_each_opted_in_request():
    old = _record(day=6, activity="처음 최신 활동")
    new = _record(day=7, activity="교체된 최신 활동")
    manager = _Manager((old,))
    client = _Client(records=())
    client.life_record_manager = manager

    first = asyncio.run(
        build_memory_context(client, "합성 질의", include_life_record_context=True)
    )
    manager.records = (new, old)
    second = asyncio.run(
        build_memory_context(client, "합성 질의", include_life_record_context=True)
    )

    assert "처음 최신 활동" in first
    assert "처음 최신 활동" not in second
    assert "교체된 최신 활동" in second


def test_memory_context_omits_broken_store_without_logging_private_detail(capsys):
    client = _Client(records=())
    client.life_record_manager = _BrokenManager()

    context = asyncio.run(
        build_memory_context(client, "합성 질의", include_life_record_context=True)
    )

    captured = capsys.readouterr()
    assert "최신 생활 기록" not in context
    assert "SYNTHETIC-PRIVATE-STORE-DETAIL" not in captured.out + captured.err


@pytest.mark.parametrize(
    "client_type",
    [
        LLMClientProtocol,
        GeminiClient,
        OpenAICompatibleClient,
        OpenAIResponseAPIClient,
        AnthropicClient,
        MistralClient,
        GoogleCloudClient,
        CohereClient,
        OllamaClient,
    ],
)
@pytest.mark.parametrize("method_name", ["send_message_with_memory", "send_message_with_images"])
def test_final_reply_clients_expose_default_off_request_scope(client_type, method_name):
    parameter = inspect.signature(getattr(client_type, method_name)).parameters[
        "include_life_record_context"
    ]

    assert parameter.default is False


class _CapturingClient:
    def __init__(self):
        self.scopes = []

    async def send_message_with_memory(self, *args, include_life_record_context=False, **kwargs):
        self.scopes.append(include_life_record_context)
        return "합성 응답", "neutral", None, [], {}, [], "", {}, [], ""

    async def send_message_with_images(
        self,
        *args,
        include_life_record_context=False,
        **kwargs,
    ):
        self.scopes.append(include_life_record_context)
        return "합성 응답", "neutral", None, [], {}, [], "", {}, [], ""


@pytest.mark.parametrize("included", [False, True])
@pytest.mark.parametrize("images", [[], [{"dataUrl": "synthetic"}]])
def test_ai_worker_forwards_immutable_life_record_request_scope(included, images):
    client = _CapturingClient()
    worker = AIWorker(
        client,
        "합성 요청",
        images=images,
        include_life_record_context=included,
    )

    worker.run()

    assert client.scopes == [included]


class _AttachmentBridge(AttachmentBridgeMixin):
    def __init__(self):
        self.llm_client = object()
        self.settings = {"locale": "ko"}
        self.calendar_manager = None
        self.mood_manager = None
        self.conversation_buffer = []
        self._message_attachment_records = {}
        self.started = []

    def _resolve_prepared_attachments(self, _attachments):
        return []

    def _normalize_attachment_runtime_state(self, prepared):
        return prepared

    def _build_active_image_payload(self, _attachments):
        return []

    def _now_timestamp(self):
        return "2099-08-07 10:00"

    def _prompt_language(self):
        return "ko"

    def _build_general_chat_prompt(self, message, attachment_context=""):
        return message

    def _with_prompt_time(self, timestamp, prompt):
        return f"[{timestamp}]\n{prompt}"

    def _build_memory_search_inputs(self, message, _timestamp):
        return {
            "memory_search_text": message,
            "latest_user_message": message,
            "recent_context_text": "",
        }

    def _mark_user_activity(self):
        pass

    def _append_conversation(self, role, message, timestamp):
        self.conversation_buffer.append((role, message, timestamp))

    def _extract_attachment_message_id(self, _attachments):
        return "synthetic-message"

    def _compose_attachment_history_message(self, message, _attachments):
        return message

    def _start_ai_worker(self, *args, **kwargs):
        self.started.append((args, kwargs))


def test_attachment_entrypoint_explicitly_opts_in_life_record_context():
    bridge = _AttachmentBridge()

    bridge.send_to_ai_with_attachments("합성 첨부 질문", "[]")

    assert bridge.started[0][1]["include_life_record_context"] is True


def test_http_final_reply_places_life_record_first_but_keeps_history_original():
    record = _record(day=7, activity="요청 전용 합성 활동")
    client = OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://example.invalid/v1/chat/completions",
        provider_name="synthetic-provider",
        settings={"enable_life_records": True, "enable_web_search": False},
    )
    client.life_record_manager = _Manager((record,))
    captured = {}

    def _capture(message, history_user_content=None):
        captured["message"] = message
        captured["history_user_content"] = history_user_content
        return "합성 응답", "neutral", None, [], {}, [], "", {}, [], ""

    client.send_message = _capture

    asyncio.run(
        client.send_message_with_memory(
            "원래 합성 사용자 메시지",
            include_life_record_context=True,
        )
    )

    assert captured["message"].startswith("[최신 생활 기록")
    assert "요청 전용 합성 활동" in captured["message"]
    assert captured["history_user_content"] == "원래 합성 사용자 메시지"
    assert client.get_conversation_history() == []


def test_concurrent_http_requests_keep_life_record_scope_request_local():
    record = _record(day=7, activity="동시 요청 합성 활동")
    client = OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://example.invalid/v1/chat/completions",
        provider_name="synthetic-provider",
        settings={"enable_life_records": True, "enable_web_search": False},
    )
    client.life_record_manager = _Manager((record,))

    async def _build_both():
        return await asyncio.gather(
            client._build_contextual_message(
                "포함 합성 요청",
                include_life_record_context=True,
            ),
            client._build_contextual_message("제외 합성 요청"),
        )

    included, excluded = asyncio.run(_build_both())

    assert "동시 요청 합성 활동" in included
    assert "동시 요청 합성 활동" not in excluded


@pytest.mark.parametrize(
    "build_context",
    [GeminiClient._build_memory_context, _CommonMixin._build_memory_context],
)
def test_gemini_and_http_build_the_same_bound_manager_block(build_context):
    record = _record(day=7, activity="공통 합성 활동")
    client = _Client(records=(record,), memory_manager=None)

    context = asyncio.run(
        build_context(
            client,
            "합성 질의",
            include_life_record_context=True,
        )
    )

    assert context.startswith("[최신 생활 기록")
    assert "공통 합성 활동" in context


def test_summary_decision_markdown_and_plain_text_paths_never_read_life_record():
    record = _record(day=7, activity="내부 경로 제외 합성 활동")
    manager = _CountingManager((record,))
    client = OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://example.invalid/v1/chat/completions",
        provider_name="synthetic-provider",
        settings={"enable_life_records": True, "enable_web_search": False},
    )
    client.life_record_manager = manager
    captured = []
    summary_output = """[SUMMARY]
합성 요약

[MASTER_INFO]
- none

[ENE_INFO]
- none

[MEMORY_META]
memory_type: general
importance_reason: synthetic
confidence: 0.9
entity_names: none

[TOPIC_MEMORY]
- none"""

    def _capture(prompt, *, request_kind, include_sub_prompt):
        captured.append((prompt, request_kind, include_sub_prompt))
        return summary_output

    client._request_one_shot_raw = _capture
    client._parse_response = lambda raw: raw

    asyncio.run(client.generate_markdown_document("합성 문서 요청"))
    asyncio.run(client.generate_note_command_plan("합성 판단 요청"))
    asyncio.run(client.generate_diary_completion_reply("합성 완료 요청"))
    asyncio.run(client.generate_note_execution_report("합성 보고 요청"))
    client._request_summary_text("합성 요약 요청")

    assert manager.latest_calls == 0
    assert all("내부 경로 제외 합성 활동" not in prompt for prompt, _, _ in captured)


def test_edit_resend_explicitly_opts_in_life_record_context():
    bridge = type("EditBridge", (), {})()
    bridge.llm_client = object()
    bridge.worker = None
    bridge.conversation_buffer = [
        ("user", "이전 합성 질문", "2099-08-07 09:00"),
        ("assistant", "이전 합성 답변", "2099-08-07 09:01"),
    ]
    bridge._last_request_payload = {
        "type": "text",
        "message": "이전 합성 질문",
        "message_with_time": "[2099-08-07 09:00]\n이전 합성 질문",
        "images": [],
        "head_pat_count_before_message": 0,
    }
    bridge._message_attachment_records = {}
    bridge._rollback_last_turn_pair_for_retry = lambda: True
    bridge._delete_tracked_promises_for_retry = lambda: None
    bridge._delete_tracked_proactive_for_retry = lambda: None
    bridge._discard_loaded_topic_memory_context_from_index = lambda _index: None
    bridge._discard_ene_thought_context_from_index = lambda _index: None
    bridge._handle_note_command = lambda _message: False
    bridge._handle_obs_command = lambda _message: False
    bridge._handle_diary_command = lambda _message: False
    bridge._now_timestamp = lambda: "2099-08-07 10:00"
    bridge._append_conversation = lambda role, message, timestamp: bridge.conversation_buffer.append(
        (role, message, timestamp)
    )
    bridge._build_general_chat_prompt = lambda message, attachment_context="": message
    bridge._with_prompt_time = lambda timestamp, prompt: f"[{timestamp}]\n{prompt}"
    bridge._build_memory_search_inputs = lambda message, _timestamp: {
        "memory_search_text": message,
        "latest_user_message": message,
        "recent_context_text": "",
    }
    bridge.reroll_state_changed = type(
        "Signal", (), {"emit": lambda self, *_args: None}
    )()
    started = []
    bridge._start_ai_worker = lambda *args, **kwargs: started.append((args, kwargs))

    from src.core.bridge_mixins.chat_flow import ChatFlowBridgeMixin

    ChatFlowBridgeMixin.edit_last_user_message(bridge, "수정된 합성 질문")

    assert started[0][1]["include_life_record_context"] is True
