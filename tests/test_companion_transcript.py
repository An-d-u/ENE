"""내부 AI 요약 버퍼와 독립적인 공개 기록의 불변 캡처를 확인한다."""

import base64
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from tests.companion_helpers import FakeClock, id_factory, sample_id


def transcript():
    from src.core.companion.transcript import CurrentConversationTranscript

    clock = FakeClock()
    return CurrentConversationTranscript(
        server_epoch=sample_id(1),
        conversation_id=sample_id(2),
        clock=clock.utcnow,
        id_factory=id_factory(),
    )


def test_capture_is_atomic_and_preserves_earlier_messages():
    state = transcript()
    first = state.append_user("가상 삼각형을 표시합니다.", request_id=sample_id(3))
    snapshot = state.capture()
    state.publish_assistant("가상 삼각형을 표시했습니다.", request_id=sample_id(3))
    assert len(snapshot.messages) == 1
    assert len(state.capture().messages) == 2
    assert snapshot.messages[0] == first.message
    with pytest.raises(FrozenInstanceError):
        snapshot.messages[0].text = "변경 시도"


def test_assistant_is_published_once_per_request_not_per_text():
    state = transcript()
    event = state.publish_assistant("가상 파도가 움직입니다.", request_id=sample_id(3))
    assert (
        state.publish_assistant("가상 파도가 움직입니다.", request_id=sample_id(3))
        is None
    )
    second = state.publish_assistant("가상 파도가 움직입니다.", request_id=sample_id(4))
    assert second.message.id != event.message.id
    assert state.capture().event_seq == 2


def test_processing_increments_sequence_but_not_conversation_revision():
    state = transcript()
    state.append_user("가상 별을 그립니다.", request_id=sample_id(3))
    state.set_processing("preparing", sample_id(3))
    snapshot = state.capture()
    assert (snapshot.event_seq, snapshot.conversation_revision) == (2, 1)
    assert snapshot.processing.phase == "preparing"
    assert state.set_processing("preparing", sample_id(3)) is None


def test_replace_preserves_id_and_rejects_stale_target():
    from src.core.companion.transcript import TranscriptError

    state = transcript()
    event = state.append_user("가상 점은 녹색입니다.")
    state.replace(event.message.id, "가상 점은 파란색입니다.", expected_revision=1)
    assert state.capture().messages[0].id == event.message.id
    with pytest.raises(TranscriptError, match="stale_target"):
        state.replace(event.message.id, "다른 변경", expected_revision=1)
    with pytest.raises(TranscriptError, match="stale_target"):
        state.replace(sample_id(9), "다른 변경", expected_revision=2)
    assert state.capture().messages[0].text == "가상 점은 파란색입니다."


def test_reset_changes_conversation_and_discards_only_current_public_state():
    state = transcript()
    state.publish_assistant("가상 새가 날아갑니다.", request_id=sample_id(3))
    old = state.capture()
    state.reset()
    current = state.capture()
    assert current.server_epoch == old.server_epoch
    assert current.conversation_id != old.conversation_id
    assert (current.event_seq, current.conversation_revision, current.messages) == (
        0,
        0,
        (),
    )
    assert state.publish_assistant("새 가상 응답", request_id=sample_id(3)) is not None


def test_large_snapshot_chunks_are_complete_and_hashed_over_original_bytes():
    from src.core.companion.protocol import decode_message, encode_message

    state = transcript()
    for index in range(5000):
        state.append_user(f"가상 도형 {index} 🪐")
    captured = state.capture()
    frames = list(captured.wire_messages())
    for frame in frames:
        assert decode_message(encode_message(frame)).to_dict() == frame
    parts = frames[1:-1]
    data = b"".join(base64.b64decode(frame["data_base64"]) for frame in parts)
    assert len(json.loads(data)["messages"]) == 5000
    assert len(data) == frames[0]["byte_count"] == frames[-1]["byte_count"]
    assert (
        hashlib.sha256(data).hexdigest() == frames[0]["sha256"] == frames[-1]["sha256"]
    )
    assert all(len(base64.b64decode(frame["data_base64"])) <= 32768 for frame in parts)
    assert frames[0]["part_count"] == len(parts)


def test_single_message_transport_limit_does_not_truncate_pc_history():
    from src.core.companion.transcript import TranscriptError

    state = transcript()
    state.append_user("x" * 1048576)
    assert state.capture().to_bytes()
    state.append_user("x" * 1048577)
    with pytest.raises(TranscriptError, match="snapshot_too_large"):
        state.capture().to_bytes()
    assert len(state.capture().messages[-1].text) == 1048577


def test_snapshot_total_size_limit_is_explicit():
    from src.core.companion.transcript import TranscriptError

    state = transcript()
    for _ in range(33):
        state.append_user("x" * 1048576)
    with pytest.raises(TranscriptError, match="snapshot_too_large"):
        state.capture().to_bytes()
    assert len(state.capture().messages) == 33


def test_snapshot_message_count_limit_is_explicit():
    from src.core.companion.transcript import TranscriptError

    state = transcript()
    for _ in range(50001):
        state.append_user("가상 점")
    with pytest.raises(TranscriptError, match="snapshot_too_large"):
        state.capture().to_bytes()


def test_attachment_marker_is_public_but_internal_data_has_no_field():
    state = transcript()
    state.append_user("가상 첨부 설명", attachment_unsupported=True)
    public = json.loads(state.capture().to_bytes())["messages"][0]
    assert public["attachment_unsupported"] is True
    assert set(public) == {
        "id",
        "role",
        "text",
        "displayed_at",
        "attachment_unsupported",
    }
