import asyncio
import json
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication

from src.ai import prompt as prompt_module
from src.ai.http_llm_common import _CommonMixin
from src.ai.response_pipeline import ResponseAttempt, execute_final_response
from src.ai.response_protocol import (
    LLMRequestKind,
    ProviderResponse,
    ResponseDeliveryMetadata,
    ResponseMode,
    ResponseStatus,
)
from src.core.bridge import AIWorker, WebBridge
from src.ui.settings_tabs.profile_memory_tab import _request_profile_memory_proposal
from tests.structured_response_fixtures import (
    make_requirements,
    make_valid_envelope,
    valid_envelope_json,
)
from tests.test_bridge_promise_reminders import build_promise_bridge_dummy


def _ensure_qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def _provider_response(
    carrier: str,
    *,
    mode: ResponseMode = ResponseMode.JSON_SCHEMA,
    status: ResponseStatus = ResponseStatus.COMPLETE,
) -> ProviderResponse:
    return ProviderResponse(carrier=carrier, status=status, mode=mode)


class _PipelineClient:
    """공급자 응답부터 공통 파이프라인까지 실행하는 합성 클라이언트다."""

    def __init__(
        self,
        outcomes,
        *,
        requirements,
        initial_mode: ResponseMode = ResponseMode.JSON_SCHEMA,
    ):
        self._outcomes = list(outcomes)
        self._requirements = requirements
        self._initial_mode = initial_mode
        self.attempts: list[ResponseAttempt] = []
        self.metadata = ResponseDeliveryMetadata.empty()

    def _request(self, attempt: ResponseAttempt) -> ProviderResponse:
        self.attempts.append(attempt)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def send_message(self, _message):
        result = execute_final_response(
            self._request,
            requirements=self._requirements,
            initial_mode=self._initial_mode,
        )
        self.metadata = result.metadata
        return result.payload

    def get_last_response_delivery_metadata(self):
        return self.metadata

    def get_last_token_usage(self):
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }


def _run_final_response_flow(
    outcomes,
    *,
    requirements,
    initial_mode: ResponseMode = ResponseMode.JSON_SCHEMA,
    configure_bridge=None,
):
    _ensure_qt_app()
    client = _PipelineClient(
        outcomes,
        requirements=requirements,
        initial_mode=initial_mode,
    )
    worker = AIWorker(client, "중립 합성 요청", use_memory=False)
    bridge = build_promise_bridge_dummy()
    bridge.worker = worker
    if callable(configure_bridge):
        configure_bridge(bridge)

    signal_payloads = []
    errors = []
    worker.response_ready.connect(lambda *args: signal_payloads.append(args))
    worker.error_occurred.connect(errors.append)
    worker.response_ready.connect(
        lambda *args: WebBridge._on_response_ready(
            bridge,
            *args,
            response_worker=worker,
        )
    )

    worker.run()

    assert errors == []
    assert len(signal_payloads) == 1
    assert len(signal_payloads[0]) == 11
    return client, bridge, signal_payloads[0]


def test_native_thought_reaches_existing_message_received_ui_path():
    reply = "구조화 합성 답변"
    thought = "공개 가능한 짧은 합성 반응"

    client, bridge, signal_payload = _run_final_response_flow(
        [
            _provider_response(
                valid_envelope_json(reply=reply, thought=thought),
            )
        ],
        requirements=make_requirements(require_thought=True),
    )

    assert signal_payload[0] == reply
    assert signal_payload[7] == thought
    assert bridge.message_received.emitted == [(reply, "normal", thought)]
    assert client.metadata.response_mode == "json_schema"
    assert client.metadata.repair_performed is False


def test_missing_thought_is_repaired_before_reaching_ui_path():
    reply = "복구 뒤에도 유지할 합성 답변"
    repaired_thought = "복구된 공개용 합성 반응"

    client, bridge, _signal_payload = _run_final_response_flow(
        [
            _provider_response(valid_envelope_json(reply=reply)),
            _provider_response(
                json.dumps({"thought": repaired_thought}, ensure_ascii=False)
            ),
        ],
        requirements=make_requirements(require_thought=True),
    )

    assert [attempt.phase for attempt in client.attempts] == ["primary", "repair"]
    assert bridge.message_received.emitted == [
        (reply, "normal", repaired_thought)
    ]
    assert client.metadata.repair_performed is True


def test_failed_thought_repair_preserves_reply_and_omits_only_thought():
    reply = "복구 실패에도 표시할 합성 답변"

    client, bridge, _signal_payload = _run_final_response_flow(
        [
            _provider_response(valid_envelope_json(reply=reply)),
            RuntimeError("synthetic_repair_failure"),
        ],
        requirements=make_requirements(require_thought=True),
    )

    assert [attempt.phase for attempt in client.attempts] == ["primary", "repair"]
    assert bridge.message_received.emitted == [(reply, "normal", "")]
    assert client.metadata.repair_performed is True


def test_legacy_tag_thought_reaches_the_same_worker_and_ui_path():
    reply = "레거시 합성 답변"
    thought = "레거시 공개용 합성 반응"
    carrier = (
        f"[subconscious]{thought}[/subconscious]\n"
        f"{reply} [normal]"
    )

    client, bridge, signal_payload = _run_final_response_flow(
        [_provider_response(carrier, mode=ResponseMode.LEGACY_TAGS)],
        requirements=make_requirements(require_thought=True),
        initial_mode=ResponseMode.LEGACY_TAGS,
    )

    assert signal_payload[0] == reply
    assert signal_payload[7] == thought
    assert bridge.message_received.emitted == [(reply, "normal", thought)]
    assert client.metadata.response_mode == "legacy_tags"
    assert client.metadata.promises_authoritative is False


def test_structured_empty_promises_are_final_but_legacy_keeps_heuristics():
    structured_fallback_calls = []
    legacy_fallback_calls = []

    def configure_structured(bridge):
        bridge._maybe_store_user_promise_candidates = (
            lambda _items=None: structured_fallback_calls.append("user") or []
        )
        bridge._maybe_store_assistant_promise_candidates = (
            lambda _text: structured_fallback_calls.append("assistant") or []
        )

    def configure_legacy(bridge):
        bridge._maybe_store_user_promise_candidates = (
            lambda _items=None: legacy_fallback_calls.append("user") or []
        )
        bridge._maybe_store_assistant_promise_candidates = (
            lambda _text: legacy_fallback_calls.append("assistant") or []
        )

    structured_client, _structured_bridge, _structured_signal = (
        _run_final_response_flow(
            [_provider_response(valid_envelope_json(promises=[]))],
            requirements=make_requirements(enable_promises=True),
            configure_bridge=configure_structured,
        )
    )
    legacy_client, _legacy_bridge, _legacy_signal = _run_final_response_flow(
        [
            _provider_response(
                "휴리스틱을 유지할 레거시 합성 답변 [normal]",
                mode=ResponseMode.LEGACY_TAGS,
            )
        ],
        requirements=make_requirements(enable_promises=True),
        initial_mode=ResponseMode.LEGACY_TAGS,
        configure_bridge=configure_legacy,
    )

    assert structured_client.metadata.promises_authoritative is True
    assert structured_fallback_calls == []
    assert legacy_client.metadata.promises_authoritative is False
    assert legacy_fallback_calls == ["user", "assistant"]


def test_retry_and_repair_apply_only_final_side_effect_once():
    discarded_event = {
        "date": "2099-07-01",
        "title": "폐기할 합성 일정",
        "description": "실패한 시도",
    }
    final_event = {
        "date": "2099-07-02",
        "title": "적용할 합성 일정",
        "description": "최종 검증 결과",
    }
    invalid_primary = make_valid_envelope(reply="", events=[discarded_event])
    calendar_additions = []

    def configure_bridge(bridge):
        bridge.settings = SimpleNamespace(
            config={"enable_schedule_recognition": True}
        )
        bridge.calendar_manager = SimpleNamespace(
            add_event=lambda **payload: calendar_additions.append(payload)
        )

    client, bridge, _signal_payload = _run_final_response_flow(
        [
            _provider_response(json.dumps(invalid_primary, ensure_ascii=False)),
            _provider_response(
                valid_envelope_json(
                    reply="최종 합성 답변",
                    events=[final_event],
                )
            ),
            _provider_response(
                json.dumps(
                    {
                        "thought": "복구된 합성 반응",
                        "events": [discarded_event],
                    },
                    ensure_ascii=False,
                )
            ),
        ],
        requirements=make_requirements(
            require_thought=True,
            enable_events=True,
        ),
        configure_bridge=configure_bridge,
    )

    assert [attempt.phase for attempt in client.attempts] == [
        "primary",
        "regenerate",
        "repair",
    ]
    assert calendar_additions == [
        {
            "date": final_event["date"],
            "title": final_event["title"],
            "description": final_event["description"],
            "source": "ai_extracted",
        }
    ]
    assert bridge.message_received.emitted == [
        ("최종 합성 답변", "normal", "복구된 합성 반응")
    ]


class _OneShotHarness(_CommonMixin):
    """실제 one-shot 호출부와 공통 프롬프트 조립을 함께 기록한다."""

    def __init__(self):
        self.generation_params = {"max_tokens": 1024}
        self.calls = []

    async def _build_memory_context(self, _message):
        return ""

    def _prompt_language(self):
        return "ko"

    def _request_one_shot_raw(
        self,
        _prompt,
        *,
        request_kind,
        include_sub_prompt=True,
    ):
        system_prompt = prompt_module.build_runtime_system_prompt(
            include_sub_prompt=include_sub_prompt,
            request_kind=request_kind,
            response_mode=ResponseMode.JSON_SCHEMA,
        )
        self.calls.append((request_kind, include_sub_prompt, system_prompt))
        if request_kind is LLMRequestKind.SUMMARY:
            return (
                "[SUMMARY]\n- 중립 합성 요약\n\n"
                "[MASTER_INFO]\n- none\n\n"
                "[ENE_INFO]\n- none\n\n"
                "[MEMORY_META]\n- none"
            )
        return "중립 합성 one-shot 출력"

    def _parse_response(self, response_text):
        return (response_text, "normal", None, [], {}, [], "", {}, [], "")


def test_one_shot_flows_never_attach_final_reply_envelope(monkeypatch):
    monkeypatch.setattr(
        prompt_module,
        "get_system_prompt",
        lambda **_kwargs: "중립 합성 시스템 프롬프트",
    )
    harness = _OneShotHarness()

    harness._request_summary_text("중립 합성 요약 요청")

    async def run_async_flows():
        await harness.generate_markdown_document("중립 합성 문서 요청")
        await harness.generate_diary_completion_reply("중립 합성 일기 완료 안내")
        await harness.generate_note_command_plan("중립 합성 노트 계획")
        await harness.generate_note_execution_report("중립 합성 노트 결과")

    asyncio.run(run_async_flows())
    _request_profile_memory_proposal(harness, "중립 합성 기억 정리 요청")

    assert [(kind, include) for kind, include, _prompt in harness.calls] == [
        (LLMRequestKind.SUMMARY, False),
        (LLMRequestKind.MARKDOWN, False),
        (LLMRequestKind.PLAIN_TEXT, True),
        (LLMRequestKind.DECISION, False),
        (LLMRequestKind.PLAIN_TEXT, True),
        (LLMRequestKind.DECISION, False),
    ]
    forbidden_contract_markers = (
        "`reply`",
        "[subconscious]",
        "Final Response Format",
        "정규 응답 구조",
    )
    for _kind, _include, system_prompt in harness.calls:
        assert all(
            marker not in system_prompt
            for marker in forbidden_contract_markers
        )


def test_hidden_native_thought_is_repaired_before_the_ui_consumes_it():
    reply = "Visible synthetic reply"
    repaired_thought = "Recovered public synthetic reaction"

    client, bridge, signal_payload = _run_final_response_flow(
        [
            _provider_response(
                valid_envelope_json(
                    reply=reply,
                    thought="<think>Hidden synthetic reasoning</think>",
                )
            ),
            _provider_response(
                json.dumps(
                    {
                        "thought": (
                            f"[subconscious]{repaired_thought}[/subconscious]"
                        )
                    }
                )
            ),
        ],
        requirements=make_requirements(require_thought=True),
    )

    assert [attempt.phase for attempt in client.attempts] == ["primary", "repair"]
    assert signal_payload[0] == reply
    assert signal_payload[7] == repaired_thought
    assert bridge.message_received.emitted == [(reply, "normal", repaired_thought)]
    assert client.metadata.repair_performed is True
