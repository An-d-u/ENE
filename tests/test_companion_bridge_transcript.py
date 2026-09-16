"""실제 브리지의 공개 시점과 내부 문맥 분리를 합성 데이터로 검증한다."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
import pytest

from src.ai.response_protocol import ResponseDeliveryMetadata
from src.core.bridge import WebBridge
from src.core.bridge_mixins import chat_flow
from src.core.companion.requests import RequestRef


class FakeWorker(QObject):
    response_ready = pyqtSignal(str, str, str, list)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.running = False
        self.response_metadata = ResponseDeliveryMetadata.empty()

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def reply(self, text="가상 정원에 둥근 화분을 배치했습니다.", spoken=""):
        self.response_ready.emit(text, "normal", spoken, [])
        self.running = False
        self.finished.emit()


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(chat_flow, "AIWorker", FakeWorker)
    result = WebBridge(settings={"enable_life_records": False})
    result.llm_client = SimpleNamespace(clear_context=lambda: None)
    result._build_general_chat_prompt = lambda text, **kwargs: "가상 도형 배치 지시"
    result._build_memory_search_inputs = lambda *args, **kwargs: {
        "memory_search_text": "",
        "latest_user_message": "",
        "recent_context_text": "",
    }
    yield result
    for timer in (result.promise_timer, result.proactive_timer, result.away_timer):
        timer.stop()
    result.deleteLater()
    app.processEvents()


def capture(bridge):
    transcript = getattr(bridge.chat_state, "public_transcript", None)
    assert transcript is not None, "공개 기록은 모바일 연결 이전부터 브리지가 소유해야 한다"
    return transcript.capture()


def prepare(bridge, text="가상 정원의 화분은 둥근 모양입니다."):
    return bridge._prepare_chat_request(
        received_at=datetime(2030, 2, 3, tzinfo=timezone.utc),
        request_type="text",
        message=text,
    )


def commit(bridge, text="가상 정원의 화분은 둥근 모양입니다."):
    request = prepare(bridge, text)
    bridge._commit_prepared_chat_request(request)
    return request, bridge.worker


def test_public_record_exists_before_mobile_connection(bridge):
    assert capture(bridge).messages == ()


def test_preparation_captures_immutable_request_without_publishing(bridge):
    request = prepare(bridge)
    assert isinstance(getattr(request, "request_ref", None), RequestRef)
    assert request.request_ref.conversation_id == capture(bridge).conversation_id
    with pytest.raises(FrozenInstanceError):
        request.request_ref.request_id = "changed"
    assert capture(bridge).messages == ()


def test_committed_user_and_visible_reply_have_stable_ids(bridge):
    request, worker = commit(bridge)
    first = capture(bridge).messages
    assert len(first) == 1
    assert first[0].role == "user"
    assert first[0].text == request.message
    assert first[0].request_id == request.request_ref.request_id
    worker.reply()
    messages = capture(bridge).messages
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].id == first[0].id
    assert messages[1].request_id == first[0].request_id
    assert messages[1].id != first[0].id


def test_internal_buffer_append_is_not_a_public_display(bridge):
    bridge._append_conversation("user", "합성 내부 검색 문맥")
    bridge._append_conversation("assistant", "합성 미공개 중간 응답")
    assert capture(bridge).messages == ()


def test_tts_waits_for_display_and_failure_publishes_once(bridge):
    bridge.enable_tts = True
    bridge.tts_client = object()
    bridge.audio_player = object()
    bridge._play_tts = lambda text: None
    _, worker = commit(bridge)
    worker.reply(spoken="합성 음성 출력")
    assert [message.role for message in capture(bridge).messages] == ["user"]
    bridge._on_tts_error("합성 생성 오류", operation_id=bridge.life_record_state.operation_id)
    bridge._flush_pending_response_if_any()
    assert [message.role for message in capture(bridge).messages] == ["user", "assistant"]


def test_duplicate_response_signal_cannot_duplicate_public_reply(bridge):
    _, worker = commit(bridge)
    worker.response_ready.emit("가상 구의 반지름은 두 칸입니다.", "normal", "", [])
    worker.response_ready.emit("가상 구의 반지름은 두 칸입니다.", "normal", "", [])
    assert len(capture(bridge).messages) == 2


def test_manual_summary_does_not_erase_visible_messages(bridge):
    _, worker = commit(bridge)
    worker.reply()
    before = capture(bridge)
    bridge._drop_reviewed_messages_from_buffer(list(bridge.conversation_buffer))
    assert bridge.conversation_buffer == []
    after = capture(bridge)
    assert after.messages == before.messages
    assert after.conversation_id == before.conversation_id


def test_reset_rejects_old_worker_before_any_response_side_effects(bridge):
    _, worker = commit(bridge)
    before = capture(bridge)
    bridge.clear_conversation()
    worker.reply("가상 이전 작업의 지연 결과")
    after = capture(bridge)
    assert after.conversation_id != before.conversation_id
    assert after.server_epoch == before.server_epoch
    assert after.messages == ()
    assert bridge.conversation_buffer == []


def test_reset_discards_old_tts_pending_publication(bridge):
    bridge.enable_tts = True
    bridge.tts_client = object()
    bridge.audio_player = object()
    bridge._play_tts = lambda text: None
    _, worker = commit(bridge)
    worker.reply(spoken="합성 음성 출력")
    bridge.clear_conversation()
    bridge._flush_pending_response_if_any()
    assert capture(bridge).messages == ()


def test_automatic_response_does_not_publish_its_prompt_as_user(bridge):
    bridge._start_ai_worker("합성 예약 실행용 내부 지시")
    bridge.worker.reply("가상 정원의 조명을 켰습니다.")
    messages = capture(bridge).messages
    assert [message.role for message in messages] == ["assistant"]
    assert "내부 지시" not in messages[0].text


def test_local_notice_signal_is_not_blindly_forwarded(bridge):
    bridge.message_received.emit("합성 로컬 파일 안내", "normal", "합성 생각")
    assert capture(bridge).messages == ()


def test_public_snapshot_excludes_private_reply_metadata(bridge):
    _, worker = commit(bridge)
    bridge._on_response_ready(
        "가상 큐브는 초록색입니다.", "smile", "", [],
        thought="합성 비공개 추론", analysis_payload=json.dumps({"private": "합성 내부 정보"}),
        response_worker=worker, operation_id=bridge.life_record_state.operation_id,
    )
    payload = json.loads(capture(bridge).to_bytes())
    assert len(payload["messages"]) == 2
    allowed = {"id", "role", "text", "displayed_at", "request_id", "attachment_unsupported"}
    assert all(set(message) <= allowed for message in payload["messages"])
    assert "합성 비공개" not in json.dumps(payload, ensure_ascii=False)


def test_auto_summary_preserves_complete_public_snapshot(bridge):
    _, worker = commit(bridge)
    worker.reply()
    before = capture(bridge)
    bridge.memory_manager = SimpleNamespace(add_summary=AsyncMock())
    bridge._summarize_conversation_with_loaded_topic_memory = AsyncMock(
        return_value=("가상 도형을 정리한 합성 요약", [], [], {})
    )
    asyncio.run(bridge._auto_summarize())
    assert bridge.conversation_buffer == []
    assert capture(bridge).messages == before.messages
    assert capture(bridge).conversation_id == before.conversation_id
    bridge.memory_manager.add_summary.assert_awaited_once()


def test_reset_rejects_prepared_request_before_commit(bridge):
    request = prepare(bridge)
    bridge.clear_conversation()
    bridge._commit_prepared_chat_request(request)
    assert bridge.worker is None
    assert bridge.conversation_buffer == []
    assert capture(bridge).messages == ()


def test_late_error_after_reset_does_not_display_or_keep_gate_busy(bridge):
    _, worker = commit(bridge)
    displayed = []
    bridge.message_received.connect(lambda *args: displayed.append(args))
    bridge.clear_conversation()
    worker.error_occurred.emit("합성 이전 요청 오류")
    assert displayed == []
    assert bridge.life_record_state.phase == "idle"


def test_attachment_commit_publishes_only_user_text_and_unsupported_flag(bridge):
    request = bridge._prepare_chat_request(
        received_at=datetime(2030, 2, 3, tzinfo=timezone.utc),
        request_type="attachments", message="가상 첨부 도형의 색을 분류합니다.",
        attachments=[{
            "id": "synthetic-attachment", "name": "synthetic-shape.txt",
            "path": "C:/synthetic-private/shape.txt", "category": "document",
            "status": "ready", "text": "합성 첨부 원문",
        }],
    )
    bridge._resolve_prepared_attachments = lambda values: values
    bridge._commit_prepared_chat_request(request)
    message = capture(bridge).messages[0]
    assert message.text == request.message
    assert message.attachment_unsupported is True
    bridge.worker.reply()
    assert capture(bridge).messages[1].request_id == request.request_ref.request_id
    wire = capture(bridge).to_bytes().decode()
    assert "synthetic-private" not in wire
    assert "합성 첨부 원문" not in wire


@pytest.mark.parametrize("kind", ["note", "diary", "obs"])
def test_file_ai_result_keeps_pc_text_but_publishes_neutral_marker(bridge, kind):
    displayed = []
    bridge.message_received.connect(lambda *args: displayed.append(args))
    if kind == "note":
        bridge._start_note_worker("합성 내부 노트 지시", "합성 내부 파일 문맥")
    elif kind == "diary":
        bridge._start_diary_worker("합성 내부 일지 지시", "합성 내부 파일 문맥")
    else:
        bridge._activate_obsidian_integration = lambda: None
        bridge._build_obsidian_context_block = lambda **kwargs: "합성 내부 파일 문맥"
        bridge._handle_obs_command("/obs 가상 도형 분류")
    bridge.worker.reply("합성 비공개 파일 결과")
    assert displayed[0][0] == "합성 비공개 파일 결과"
    messages = capture(bridge).messages
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].text == "PC 전용 파일 작업 결과입니다. PC에서 확인해 주세요."


@pytest.mark.parametrize("command", ["read", "append", "replace"])
def test_direct_file_result_excludes_paths_and_preview(bridge, command):
    bridge._activate_obsidian_integration = lambda: None
    bridge._parse_obs_subcommand = lambda _: (command, {
        "path": "synthetic-private/shape.md", "content": "합성 내용",
        "before": "합성 이전", "after": "합성 이후",
    })
    bridge.obsidian_manager = SimpleNamespace(
        read_file=lambda _: "합성 비공개 파일 내용",
        append_file=lambda *args, **kwargs: SimpleNamespace(ok=True, path="synthetic-private/shape.md"),
        replace_in_file=lambda *args: SimpleNamespace(ok=True, path="synthetic-private/shape.md"),
    )
    displayed = []
    bridge.message_received.connect(lambda *args: displayed.append(args))
    assert bridge._handle_obs_command("/obs 합성 파일 명령")
    assert displayed
    messages = capture(bridge).messages
    assert len(messages) == 1
    assert "synthetic-private" not in messages[0].text
    assert "합성 비공개 파일 내용" not in messages[0].text
