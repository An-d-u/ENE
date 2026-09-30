"""합성 AI와 실제 Qt/WSS 경계를 연결하고 미디어의 독립 수명을 검증한다."""

import base64
import json

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
import pytest

from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission  # noqa: F401
from tests.test_companion_bridge_transcript import bridge, FakeWorker  # noqa: F401
from tests.test_companion_adapter import run_adapter
from tests.test_companion_chat_actions import action
from tests.test_companion_edit_reroll import completed_pair, state
from tests.test_companion_error_recovery import fail_worker
from tests.test_companion_gateway import harness
from tests.test_companion_tts_routing import routed_bridge, synthetic_bridge, start_reply, wav  # noqa: F401


@pytest.mark.parametrize("origin", ["pc", "mobile"])
def test_actual_qt_tls_retry_edit_failure_and_reconnected_ledger(admission, monkeypatch, tmp_path, origin):
    owner, adapter, context, counts = admission
    owner.companion_event.connect(adapter.publish)
    owner.llm_client.rollback_last_assistant_turn = lambda: True
    owner.llm_client.rebuild_context_from_conversation = lambda *_: True
    if origin == "mobile":
        completed_pair(admission)
    else:
        head = state(owner)
        result = json.loads(owner.submit_pc_chat(json.dumps({
            "server_epoch": head.server_epoch, "conversation_id": head.conversation_id,
            "request_id": sample_id(80), "text": "가상 은색 블록을 정렬해 줘.", "attachments": [],
        })))
        assert result["state"] == "accepted"
        owner.worker.reply()
    originals = state(owner).messages
    before_workers = counts["worker"]
    step = [0]
    original_start = FakeWorker.start
    def start(worker):
        original_start(worker)
        step[0] += 1
        if step[0] == 3:
            QTimer.singleShot(0, lambda: fail_worker(owner))
        else:
            QTimer.singleShot(0, lambda: worker.reply("가상 교체 답변"))
    monkeypatch.setattr(FakeWorker, "start", start)
    gateways = []

    async def until(ws, predicate):
        while True:
            frame = await ws.receive_json(timeout=3)
            if predicate(frame):
                return frame

    async def scenario():
        async with harness(tmp_path, capabilities=("chat_actions_v1",)) as (gateway, client, base, token, _, _):
            gateway.adapter = adapter
            gateways.append(gateway)
            async def connect():
                ws = await client.ws_connect(base + "/ws", headers={"Authorization": "Bearer " + token})
                await ws.send_json({"type": "hello", "protocol_version": 1, "capabilities": ["chat_actions_v1"]})
                ready = await until(ws, lambda f: f["type"] == "ready")
                ext = await until(ws, lambda f: f["type"] == "extensions_ready")
                return ws, {key: ready[key] for key in ("registration_generation", "server_epoch", "conversation_id")} | {"connection_generation": ext["connection_generation"]}
            ws, envelope = await connect()
            await ws.send_json({"type": "sync_request", "protocol_version": 1})
            await until(ws, lambda f: f["type"] == "snapshot_end")
            revision = 2
            last_body = None
            for index, kind in enumerate(("reroll", "edit", "reroll")):
                request_id = sample_id(970 + index)
                await ws.send_json({"type": "chat_action", "protocol_version": 1, **envelope,
                    "request_id": request_id, "kind": kind,
                    "target_message_id": originals[0 if kind == "edit" else 1].id,
                    "expected_revision": revision, **({"text": "가상 편집 요청"} if kind == "edit" else {})})
                result = await until(ws, lambda f: f["type"] == "request_status" and f["request_id"] == request_id and f["state"] in {"completed", "failed", "rejected"})
                assert result["state"] == ("failed" if index == 2 else "completed")
                query = sample_id(980 + index)
                await ws.send_json({"type": "chat_actions_request", "protocol_version": 1, **envelope, "query_id": query, "refresh": True})
                parts, snapshot_id = {}, None
                while True:
                    frame = await ws.receive_json(timeout=3)
                    if frame["type"] == "snapshot_begin":
                        parts, snapshot_id = {}, frame["snapshot_id"]
                    if frame["type"] == "snapshot_part":
                        parts[frame["index"]] = base64.b64decode(frame["data_base64"])
                    if frame["type"] == "chat_actions_state" and frame.get("query_id") == query:
                        assert frame["snapshot_id"] == snapshot_id
                        revision = frame["conversation_revision"]
                        break
                body = json.loads(b"".join(parts[i] for i in sorted(parts)))
                assert [m["id"] for m in body["messages"]] == [m.id for m in originals]
                if index == 2:
                    assert body["messages"] == last_body["messages"]
                last_body = body
            await ws.close()
            ws, _ = await connect()
            await ws.send_json({"type": "sync_request", "protocol_version": 1, "pending_request_ids": [sample_id(972)]})
            restored = await until(ws, lambda f: f["type"] == "request_status" and f["request_id"] == sample_id(972))
            assert restored["state"] == "failed"
            await ws.close()
    run_adapter(QApplication.instance(), adapter, scenario, on_event=lambda message: gateways[-1].publish(message) if gateways else None)
    assert counts["worker"] == before_workers + 3
    assert len(state(owner).messages) == 2


def test_rejected_retry_keeps_playback_and_accepted_failure_never_replays(routed_bridge):
    owner, context, jobs, transfers, played = routed_bridge
    owner.llm_client.rollback_last_assistant_turn = lambda: True
    owner.llm_client.rebuild_context_from_conversation = lambda *_: True
    owner.tts_output_target = "pc"
    start_reply(owner)
    jobs[0].ready(wav())
    assert owner.life_record_state.phase == "idle"
    old = owner._companion_audio.playback.ref
    assert old is not None
    invalid = action(owner, context, expected_revision=0)
    assert owner.submit_extension(context, invalid).fields["state"] == "rejected"
    assert owner._companion_audio.playback.ref == old
    owner.tts_output_target = "phone"
    accepted = action(owner, context, number=995)
    assert owner.submit_extension(context, accepted).fields["state"] == "accepted"
    assert not owner._companion_audio.playback.active
    count = len(played)
    fail_worker(owner)
    assert len(played) == count
    assert not owner._companion_audio.playback.active
