"""실제 요청·최종 응답·음성 완료 경계의 생성 표시를 합성 입력으로 검증한다."""

import json
from dataclasses import replace

import pytest

from src.core.companion.protocol import decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge, bridge as synthetic_bridge  # noqa: F401
from tests.test_companion_edit_reroll import command, completed_pair
from tests.test_companion_tts_routing import routed_bridge, stream_reply, wire  # noqa: F401


def progress(owner):
    return owner._ensure_companion_chat_progress().snapshot()


@pytest.mark.parametrize("source", ["pc", "phone", "edit", "reroll"])
def test_all_request_paths_publish_generation_then_text_ready(admission, source, monkeypatch):
    owner, adapter, context, _ = admission
    if source in {"edit", "reroll"}:
        completed_pair(admission)
    sent = []
    monkeypatch.setattr(adapter, "publish_extension", lambda kind, fields: sent.append((kind, fields)) or True)
    if source == "phone":
        result = owner.submit_mobile_text(context, mobile_message(owner))
        request_id = result.request_ref.request_id
    elif source == "pc":
        request_id = owner.submit_chat_request("가상 별의 위치를 설명합니다.").request_ref.request_id
    else:
        method = owner.edit_companion_message if source == "edit" else owner.reroll_companion_message
        args = {"text": "가상 별을 오른쪽으로 옮깁니다."} if source == "edit" else {}
        result = json.loads(method(command(owner, "user" if source == "edit" else "assistant", **args)))
        assert result["state"] == "accepted"
        request_id = result["request_id"]
    assert progress(owner)["phase"] == "generating"
    assert progress(owner)["request_id"] == request_id
    owner.worker.reply("가상 별의 배치를 마쳤습니다.")
    phases = [fields["phase"] for kind, fields in sent if kind == "chat_progress_state"]
    assert phases[-3:] == ["generating", "text_ready", "idle"]
    assert owner.life_record_state.phase == "idle"


def test_text_ready_does_not_release_stream_gate(routed_bridge):
    owner, context, jobs, transfers, played = routed_bridge
    result = stream_reply(routed_bridge, published=False)
    assert progress(owner)["phase"] == "text_ready"
    assert result.request_ref.key not in owner.chat_state.public_assistant_ids
    assert owner.submit_chat_request("가상 별을 추가합니다.").code == "busy"
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    offer = next(item for item in transfers if item.kind == "offer")
    owner.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=2400))
    jobs[0].stream_finished.emit()
    assert progress(owner)["phase"] == "text_ready"
    assert owner.life_record_state.phase == "normal_reply"
    owner.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=2400))
    assert progress(owner)["phase"] == "idle"
    assert owner.life_record_state.phase == "idle" and played == []


def test_failure_reset_and_old_worker_do_not_restore_progress(admission):
    owner, _, context, _ = admission
    owner.submit_mobile_text(context, mobile_message(owner))
    old = owner.worker
    old.error_occurred.emit("synthetic_provider_failure")
    old.running = False
    old.finished.emit()
    assert progress(owner)["phase"] == "idle"
    owner.submit_mobile_text(context, mobile_message(owner, number=41))
    current = progress(owner)
    old.reply()
    assert progress(owner) == current
    owner.clear_conversation()
    assert progress(owner)["phase"] == "idle"


def test_query_uses_current_connection_not_pc_request_generation(admission):
    owner, _, context, _ = admission
    result = owner.submit_chat_request("가상의 격자를 설명합니다.")
    assert result.request_ref.registration_generation == 0
    head = owner.head()
    request = decode_message(encode_message({
        "protocol_version": 1, "type": "chat_progress_request", "registration_generation": 1,
        "server_epoch": head.server_epoch, "connection_generation": context.connection_generation,
        "conversation_id": head.conversation_id,
    }))
    before = owner.chat_state.public_transcript.capture()
    answer = owner.submit_extension(context, request)
    assert answer.type == "chat_progress_state"
    assert answer.fields["registration_generation"] == 1
    assert answer.fields["request_id"] == result.request_ref.request_id
    after = owner.chat_state.public_transcript.capture()
    assert replace(after, snapshot_id=before.snapshot_id) == before
    owner.worker.reply()


def test_progress_query_over_tls_without_media(admission, tmp_path):
    from PyQt6.QtWidgets import QApplication
    from tests.test_companion_adapter import run_adapter
    from tests.test_companion_gateway import harness

    owner, adapter, _, counts = admission
    gateways = []

    async def until(ws, kind):
        while True:
            frame = await ws.receive_json(timeout=3)
            if frame["type"] == kind:
                return frame

    async def scenario():
        async with harness(tmp_path, capabilities=("chat_progress_v1",)) as (gateway, client, base, token, _, _):
            gateway.adapter = adapter
            gateways.append(gateway)
            ws = await client.ws_connect(base + "/ws", headers={"Authorization": "Bearer " + token})
            await ws.send_json({"type": "hello", "protocol_version": 1, "capabilities": ["chat_progress_v1"]})
            ready = await until(ws, "ready")
            ext = await until(ws, "extensions_ready")
            await ws.send_json({"type": "chat_progress_request", "protocol_version": 1,
                **{key: ext[key] for key in ("registration_generation", "server_epoch", "connection_generation")},
                "conversation_id": ready["conversation_id"]})
            state = await until(ws, "chat_progress_state")
            assert state["phase"] == "idle" and state["progress_revision"] == 0
            assert "request_id" not in state
            await ws.close()

    run_adapter(QApplication.instance(), adapter, scenario,
                on_event=lambda message: gateways[-1].publish(message) if gateways else None)
    assert not any(counts.values())


def test_progress_exists_before_phone_connects(bridge):
    bridge.submit_chat_request("가상 다각형의 꼭짓점을 설명합니다.")
    assert progress(bridge)["phase"] == "generating"
    bridge.worker.reply("가상 다각형에 꼭짓점을 표시했습니다.")
    assert progress(bridge)["phase"] == "idle"
