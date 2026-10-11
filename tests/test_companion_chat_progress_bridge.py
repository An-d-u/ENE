"""생성 상태는 현재 요청에만 귀속되며 부가 알림 실패가 대화를 막지 않는다."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.core.companion.protocol import MAX_SAFE_INTEGER, ProtocolError
from src.core.companion.requests import RequestRef
from tests.companion_helpers import sample_id


def setup_progress():
    from src.core.companion.chat_progress_bridge import CompanionChatProgressBridge

    sent = []
    transcript = SimpleNamespace(server_epoch=sample_id(1), conversation_id=sample_id(2))
    owner = SimpleNamespace(chat_state=SimpleNamespace(public_transcript=transcript),
                            life_record_state=SimpleNamespace(operation_id=1, phase="normal_reply"),
                            _companion_adapter=SimpleNamespace(publish_extension=lambda kind, fields: sent.append((kind, fields))))
    ref = RequestRef(0, sample_id(1), sample_id(2), sample_id(3), "pc", "1")
    return CompanionChatProgressBridge(owner), owner, ref, sent


def test_phases_are_idempotent_and_late_stage_does_not_regress():
    progress, _, ref, sent = setup_progress()
    assert progress.snapshot() == {"conversation_id": ref.conversation_id, "progress_revision": 0, "phase": "idle"}
    progress.begin(ref, "preparing")
    progress.begin(ref, "generating")
    progress.begin(ref, "generating")
    progress.text_ready(ref)
    progress.begin(ref, "generating")
    assert [fields["phase"] for _, fields in sent] == ["preparing", "generating", "text_ready"]
    assert progress.snapshot()["progress_revision"] == 3
    progress.finish(ref)
    progress.finish(ref)
    assert progress.snapshot() == {"conversation_id": ref.conversation_id, "progress_revision": 4, "phase": "idle"}
    progress.begin(ref, "generating")
    assert progress.snapshot()["phase"] == "idle"


@pytest.mark.parametrize("change", [
    {"server_epoch": sample_id(10)}, {"conversation_id": sample_id(11)},
    {"request_id": sample_id(12)}, {"operation_id": "9"},
])
def test_stale_completion_cannot_finish_current_request(change):
    progress, _, ref, _ = setup_progress()
    progress.begin(ref, "generating")
    before = progress.snapshot()
    progress.text_ready(replace(ref, **change))
    progress.finish(replace(ref, **change))
    assert progress.snapshot() == before


def test_new_operation_and_reset_reject_old_callbacks():
    progress, owner, ref, _ = setup_progress()
    progress.begin(ref, "generating")
    owner.life_record_state.operation_id = 2
    new = replace(ref, request_id=sample_id(4), operation_id="2")
    progress.begin(new, "generating")
    progress.begin(ref, "preparing")
    progress.finish(ref)
    assert progress.snapshot()["request_id"] == new.request_id
    owner.chat_state.public_transcript.conversation_id = sample_id(5)
    progress.reset(sample_id(5))
    progress.text_ready(new)
    assert progress.snapshot() == {"conversation_id": sample_id(5), "progress_revision": 0, "phase": "idle"}


def test_missing_or_failed_publisher_preserves_state():
    progress, owner, ref, _ = setup_progress()
    del owner._companion_adapter
    progress.begin(ref, "generating")
    def fail(*args):
        raise RuntimeError("synthetic_failure")
    owner._companion_adapter = SimpleNamespace(publish_extension=fail)
    progress.text_ready(ref)
    assert progress.snapshot()["phase"] == "text_ready"
    progress.finish(ref)
    assert progress.snapshot()["phase"] == "idle"


def test_revision_exhaustion_is_nonfatal_and_never_reuses_revision():
    progress, _, ref, sent = setup_progress()
    progress._revision = MAX_SAFE_INTEGER
    progress.begin(ref, "generating")
    with pytest.raises(ProtocolError, match="progress_unavailable"):
        progress.snapshot()
    assert sent == [("extension_error", {"feature": "chat_progress_v1", "code": "progress_unavailable"})]
