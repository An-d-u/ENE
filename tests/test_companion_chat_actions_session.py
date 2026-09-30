"""새 캡처의 실제 전송 완료와 조작 응답의 인과관계를 검증한다."""

import asyncio
from src.core.companion.protocol import decode_message, encode_message
from src.core.companion.session import SnapshotPump, SyncCapture
from src.core.companion.transcript import CurrentConversationTranscript
from tests.companion_helpers import sample_id
from tests.test_companion_gateway import harness, connect, synchronize
from tests.test_companion_admission import admission  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_edit_reroll import completed_pair
from tests.test_companion_chat_actions import action


def test_fresh_snapshot_with_same_pending_never_reuses_preterminal_capture():
    async def scenario():
        transcript = CurrentConversationTranscript()
        entered, release = asyncio.Event(), asyncio.Event()
        captures, sent, done = [], [], []

        async def capture(pending):
            value = SyncCapture(transcript.capture())
            captures.append(pending)
            if len(captures) == 1:
                entered.set()
                await release.wait()
            return value

        async def emit(frame):
            sent.append(frame)

        pump = SnapshotPump(capture, emit, done.append)
        try:
            pump.request_sync((sample_id(90),))
            await entered.wait()
            transcript.append_user("가상의 회색 큐브를 이동합니다.")
            pump.request_sync((sample_id(90),), fresh=True)
            release.set()
            await asyncio.wait_for(pump.wait_idle(), 2)
            assert len(captures) == 2
            assert len(done) == 1
            assert done[0].transcript.conversation_revision == 1
            assert done[0].snapshot_id == sent[-1]["snapshot_id"]
        finally:
            release.set()
            await pump.close()
    asyncio.run(scenario())


def test_state_is_published_for_pc_and_mobile_boundaries(admission, monkeypatch):
    bridge, context, _ = completed_pair(admission)
    emitted = []
    monkeypatch.setattr(bridge._companion_adapter, "publish_extension", lambda kind, fields: emitted.append((kind, fields)))
    bridge.submit_extension(context, action(bridge, context))
    assert any(kind == "chat_actions_state" and fields["reroll_reason"] == "busy" for kind, fields in emitted)
    bridge.worker.reply()
    assert emitted[-1][1]["reroll_allowed"]
    sequences = [fields["state_seq"] for kind, fields in emitted if kind == "chat_actions_state"]
    assert sequences == sorted(set(sequences))
    bridge.clear_conversation()
    assert emitted[-1][1]["user_message_id"] is None


def test_controller_advertises_chat_without_character_or_audio(admission, monkeypatch):
    from src.core.companion.controller import CompanionController

    bridge = admission[0]
    monkeypatch.setattr(bridge, "_companion_audio", None)
    monkeypatch.setattr(bridge, "_companion_character", None)
    controller = CompanionController(bridge)
    assert controller._capabilities == ("chat_actions_v1",)


def test_state_publish_failure_does_not_escape_owner_callback(admission, monkeypatch):
    bridge, _, _ = completed_pair(admission)
    def fail(*args):
        raise RuntimeError("synthetic_publish_failure")
    monkeypatch.setattr(bridge._companion_adapter, "publish_extension", fail)
    bridge._companion_chat_actions.changed()


def test_refresh_query_waits_for_new_snapshot_and_returns_its_id(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_actions_v1",)) as (_, client, base, token, port, _):
            original = port.call
            captures = 0
            async def call(operation, context, *, message=None, pending=()):
                nonlocal captures
                if operation == "capture":
                    captures += 1
                if operation != "extension":
                    return await original(operation, context, message=message, pending=pending)
                current = port.transcript.capture()
                return decode_message(encode_message({
                    **{key: message.fields[key] for key in ("registration_generation", "server_epoch", "connection_generation", "conversation_id", "query_id")},
                    "type": "chat_actions_state", "protocol_version": 1,
                    "snapshot_id": None, "state_seq": 1,
                    "conversation_revision": current.conversation_revision, "event_seq": current.event_seq,
                    "user_message_id": None, "assistant_message_id": None,
                    "edit_allowed": False, "edit_reason": "no_target",
                    "reroll_allowed": False, "reroll_reason": "no_target",
                }))
            port.call = call
            ws = await client.ws_connect(base + "/ws", headers={"Authorization": "Bearer " + token})
            await ws.send_json({"type": "hello", "protocol_version": 1, "capabilities": ["chat_actions_v1"]})
            ready = await ws.receive_json(timeout=2)
            extension = await ws.receive_json(timeout=2)
            initial = await synchronize(ws)
            old_id = initial[-1]["snapshot_id"]
            await ws.send_json({
                "type": "chat_actions_request", "protocol_version": 1,
                "registration_generation": ready["registration_generation"],
                "server_epoch": ready["server_epoch"], "conversation_id": ready["conversation_id"],
                "connection_generation": extension["connection_generation"],
                "query_id": sample_id(940), "refresh": True,
            })
            frames = []
            while not frames or frames[-1]["type"] != "chat_actions_state":
                frames.append(await ws.receive_json(timeout=2))
            ends = [frame for frame in frames if frame["type"] == "snapshot_end"]
            assert len(ends) == 1 and captures == 2
            assert ends[0]["snapshot_id"] != old_id
            assert frames[-1]["snapshot_id"] == ends[0]["snapshot_id"]
            assert frames[-1]["query_id"] == sample_id(940)
            await ws.close()
    asyncio.run(scenario())


def test_old_client_gets_no_chat_extension(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_actions_v1",)) as (_, client, base, token, _, _):
            ws, ready = await connect(client, base, token)
            assert ready["capabilities"] == []
            assert (await synchronize(ws))[0]["type"] == "snapshot_begin"
            await ws.close()
    asyncio.run(scenario())


def test_action_before_initial_sync_is_rejected_without_owner_call(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_actions_v1",)) as (_, client, base, token, port, _):
            ws = await client.ws_connect(base + "/ws", headers={"Authorization": "Bearer " + token})
            await ws.send_json({"type": "hello", "protocol_version": 1, "capabilities": ["chat_actions_v1"]})
            ready = await ws.receive_json(timeout=2)
            extension = await ws.receive_json(timeout=2)
            await ws.send_json({
                "type": "chat_action", "protocol_version": 1,
                "registration_generation": ready["registration_generation"],
                "server_epoch": ready["server_epoch"], "conversation_id": ready["conversation_id"],
                "connection_generation": extension["connection_generation"],
                "request_id": sample_id(945), "kind": "reroll",
                "target_message_id": sample_id(946), "expected_revision": 0,
            })
            result = await ws.receive_json(timeout=2)
            assert result["type"] == "request_status" and result["code"] == "sync_required"
            assert result["request_id"] == sample_id(945)
            assert not any(operation == "extension" for operation, _ in port.calls)
            await ws.close()
    asyncio.run(scenario())
