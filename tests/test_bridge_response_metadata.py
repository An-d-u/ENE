import json
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication

from src.ai.response_protocol import ResponseDeliveryMetadata
from src.core.bridge import AIWorker, WebBridge
from src.core.bridge_mixins import chat_flow as chat_flow_module
from tests.test_bridge_promise_reminders import build_promise_bridge_dummy


FINAL_PAYLOAD = ("합성 답변", "normal", None, [], {}, [], "", {}, [], "")
STRUCTURED_METADATA = ResponseDeliveryMetadata(
    response_mode="json_schema",
    schema_version="1",
    promises_authoritative=True,
    repair_performed=False,
)


def _ensure_qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class MetadataClient:
    def __init__(self, *, fail=False, metadata=STRUCTURED_METADATA):
        self.fail = fail
        self.metadata = metadata

    def send_message(self, _message):
        if self.fail:
            raise RuntimeError("synthetic_worker_failure")
        return FINAL_PAYLOAD

    def get_last_response_delivery_metadata(self):
        return self.metadata

    def get_last_token_usage(self):
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }


def test_ai_worker_captures_metadata_without_changing_response_signal_shape():
    _ensure_qt_app()
    emitted = []
    worker = AIWorker(MetadataClient(), "합성 입력", use_memory=False)
    worker.response_ready.connect(lambda *args: emitted.append(args))

    worker.run()

    assert len(emitted[0]) == 11
    assert json.loads(emitted[0][5]) == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    assert len(worker._normalize_response_payload(FINAL_PAYLOAD)) == 10
    assert worker.response_metadata == STRUCTURED_METADATA


def test_ai_worker_clears_stale_metadata_before_request_and_on_error():
    _ensure_qt_app()
    worker = AIWorker(MetadataClient(fail=True), "합성 입력", use_memory=False)
    worker.response_metadata = STRUCTURED_METADATA

    worker.run()

    assert worker.response_metadata == ResponseDeliveryMetadata.empty()


def test_ai_worker_clears_captured_metadata_when_postprocessing_fails():
    _ensure_qt_app()

    class InvalidPayloadClient(MetadataClient):
        def send_message(self, _message):
            return ("합성 답변", "normal", None, [], {"invalid": object()}, [], "", {}, [], "")

    errors = []
    worker = AIWorker(InvalidPayloadClient(), "합성 입력", use_memory=False)
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert errors
    assert worker.response_metadata == ResponseDeliveryMetadata.empty()


@pytest.mark.parametrize("flow", ["diary", "note"])
def test_ai_worker_non_final_success_does_not_copy_stale_client_metadata(flow):
    _ensure_qt_app()
    kwargs = {
        "diary_request": "합성 일기 요청" if flow == "diary" else "",
        "diary_service": object() if flow == "diary" else None,
        "note_request": "합성 노트 요청" if flow == "note" else "",
        "note_service": object() if flow == "note" else None,
        "obsidian_manager": object() if flow == "note" else None,
    }
    worker = AIWorker(MetadataClient(), "합성 입력", **kwargs)

    async def fake_flow():
        return FINAL_PAYLOAD

    if flow == "diary":
        worker._run_diary_flow = fake_flow
    else:
        worker._run_note_flow = fake_flow

    worker.run()

    assert worker.response_metadata == ResponseDeliveryMetadata.empty()


def test_ai_worker_memory_final_success_copies_client_metadata():
    _ensure_qt_app()

    class MemoryClient(MetadataClient):
        async def send_message_with_memory(self, *_args, **_kwargs):
            return FINAL_PAYLOAD

    worker = AIWorker(MemoryClient(), "합성 메모리 입력")

    worker.run()

    assert worker.response_metadata == STRUCTURED_METADATA


def test_ai_worker_image_final_success_copies_client_metadata():
    _ensure_qt_app()

    class ImageClient(MetadataClient):
        supports_image_input = True

        async def send_message_with_images(self, *_args, **_kwargs):
            return FINAL_PAYLOAD

    worker = AIWorker(
        ImageClient(),
        "합성 이미지 입력",
        images=[{"dataUrl": "data:image/png;base64,QUJD"}],
    )

    worker.run()

    assert worker.response_metadata == STRUCTURED_METADATA


def test_ai_worker_final_success_with_missing_getter_keeps_empty_metadata():
    _ensure_qt_app()

    class LegacyClient:
        def send_message(self, _message):
            return FINAL_PAYLOAD

    worker = AIWorker(LegacyClient(), "합성 입력", use_memory=False)
    worker.response_metadata = STRUCTURED_METADATA

    worker.run()

    assert worker.response_metadata == ResponseDeliveryMetadata.empty()


def test_ai_worker_invalid_client_metadata_is_treated_as_empty():
    _ensure_qt_app()
    worker = AIWorker(MetadataClient(metadata={"promises_authoritative": True}), "합성 입력", use_memory=False)

    worker.run()

    assert worker.response_metadata == ResponseDeliveryMetadata.empty()


def test_on_response_ready_skips_promise_heuristics_for_authoritative_empty_promises():
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("authoritative empty promises must not use heuristics")

    dummy = build_promise_bridge_dummy(response_metadata=STRUCTURED_METADATA)
    dummy._maybe_store_user_promise_candidates = fail_if_called
    dummy._maybe_store_assistant_promise_candidates = fail_if_called

    WebBridge._on_response_ready(dummy, "합성 답변", "normal", "", [], "", "", [])

    assert dummy.worker.response_metadata == ResponseDeliveryMetadata.empty()


@pytest.mark.parametrize("flow", ["chat", "diary", "note"])
def test_queued_response_consumes_only_its_source_worker_metadata(monkeypatch, flow):
    class CapturedSignal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

    class FakeWorker:
        def __init__(self, *_args, **_kwargs):
            self.response_ready = CapturedSignal()
            self.error_occurred = CapturedSignal()
            self.response_metadata = STRUCTURED_METADATA

        def start(self):
            return None

    monkeypatch.setattr(chat_flow_module, "AIWorker", FakeWorker)
    dummy = build_promise_bridge_dummy()
    dummy.worker = None
    dummy.llm_client = object()
    dummy.diary_service = object()
    dummy.note_service = object()
    dummy.obsidian_manager = object()
    dummy._on_response_ready = (
        lambda *args, **kwargs: WebBridge._on_response_ready(dummy, *args, **kwargs)
    )
    dummy._on_error = lambda _message: None
    dummy._connect_worker_finished_drain = lambda: None
    dummy._emit_request_pending_stage_changed = lambda _stage: None
    dummy._emit_request_pending_changed = lambda _active: None
    dummy._with_ene_thought_context = lambda message: message
    dummy._with_tts_output_reminder = lambda message: message

    if flow == "chat":
        WebBridge._start_ai_worker(dummy, "합성 입력")
    elif flow == "diary":
        WebBridge._start_diary_worker(dummy, "합성 일기", "합성 입력")
    else:
        WebBridge._start_note_worker(dummy, "합성 노트", "합성 입력")

    source_worker = dummy.worker
    replacement_metadata = ResponseDeliveryMetadata(
        response_mode="legacy_tags",
        schema_version="1",
        promises_authoritative=False,
        repair_performed=False,
    )
    replacement_worker = SimpleNamespace(response_metadata=replacement_metadata)
    dummy.worker = replacement_worker
    fallback_calls = []
    dummy._maybe_store_user_promise_candidates = (
        lambda _items=None: fallback_calls.append("user") or []
    )
    dummy._maybe_store_assistant_promise_candidates = (
        lambda _text: fallback_calls.append("assistant") or []
    )

    source_worker.response_ready.callbacks[0](
        "합성 답변",
        "normal",
        "",
        [],
        "",
        "",
        [],
        "",
        "",
        [],
        "",
    )

    assert fallback_calls == []
    assert source_worker.response_metadata == ResponseDeliveryMetadata.empty()
    assert replacement_worker.response_metadata == replacement_metadata


def test_on_response_ready_consumes_current_worker_metadata_once():
    dummy = build_promise_bridge_dummy(response_metadata=STRUCTURED_METADATA)
    calls = []
    dummy._maybe_store_user_promise_candidates = lambda _items=None: calls.append("user") or []
    dummy._maybe_store_assistant_promise_candidates = lambda _text: calls.append("assistant") or []

    WebBridge._on_response_ready(dummy, "첫 합성 답변", "normal", "", [], "", "", [])
    WebBridge._on_response_ready(dummy, "둘째 합성 답변", "normal", "", [], "", "", [])

    assert calls == ["user", "assistant"]
    assert dummy.worker.response_metadata == ResponseDeliveryMetadata.empty()


@pytest.mark.parametrize("metadata", [None, {"promises_authoritative": True}, "invalid"])
def test_missing_or_invalid_metadata_keeps_legacy_promise_heuristics(metadata):
    dummy = build_promise_bridge_dummy()
    if metadata is None:
        dummy.worker = SimpleNamespace()
    else:
        dummy.worker.response_metadata = metadata
    calls = []
    dummy._maybe_store_user_promise_candidates = lambda _items=None: calls.append("user") or []
    dummy._maybe_store_assistant_promise_candidates = lambda _text: calls.append("assistant") or []

    WebBridge._on_response_ready(dummy, "합성 답변", "normal", "", [], "", "", [])

    assert calls == ["user", "assistant"]
