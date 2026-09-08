"""연결별 자원 상한·단조 시계·단일 스냅샷 작업을 검증한다."""

import asyncio
import json
import threading

import pytest

from tests.companion_helpers import FakeClock, sample_id
from src.core.companion.transcript import CurrentConversationTranscript


def test_heartbeat_requires_matching_nonce_before_deadline():
    from src.core.companion.session import Heartbeat, SessionError

    clock = FakeClock()
    heartbeat = Heartbeat(clock=clock.monotonic, id_factory=lambda: sample_id(80))
    assert heartbeat.tick() is None
    clock.advance(15)
    ping = heartbeat.tick()
    assert ping["nonce"] == sample_id(80)
    assert not heartbeat.pong(sample_id(81))
    clock.advance(9.9)
    assert heartbeat.tick() is None
    clock.advance(0.1)
    with pytest.raises(SessionError, match="heartbeat_timeout"):
        heartbeat.tick()


def test_heartbeat_matching_pong_schedules_next_ping_and_late_pong_cannot_recover():
    from src.core.companion.session import Heartbeat, SessionError

    clock = FakeClock()
    heartbeat = Heartbeat(clock=clock.monotonic)
    clock.advance(15)
    nonce = heartbeat.tick()["nonce"]
    assert heartbeat.pong(nonce)
    assert not heartbeat.pong(nonce)
    clock.advance(14.9)
    assert heartbeat.tick() is None
    clock.advance(0.1)
    late = heartbeat.tick()["nonce"]
    clock.advance(10)
    assert not heartbeat.pong(late)
    with pytest.raises(SessionError):
        heartbeat.tick()


def test_token_bucket_limits_burst_and_refills_monotonically():
    from src.core.companion.session import TokenBucket

    clock = FakeClock()
    bucket = TokenBucket(10, 20, clock=clock.monotonic)
    assert all(bucket.take() for _ in range(20))
    assert not bucket.take()
    clock.advance(0.1)
    assert bucket.take()
    assert not bucket.take()
    clock.advance(100)
    assert sum(bucket.take() for _ in range(25)) == 20


def test_preauth_limits_concurrent_slots_and_releases_exactly_once():
    from src.core.companion.session import PreauthLimiter, SessionError

    limiter = PreauthLimiter()
    first = limiter.acquire("192.0.2.1")
    second = limiter.acquire("192.0.2.1")
    with pytest.raises(SessionError, match="rate_limited"):
        limiter.acquire("192.0.2.1")
    rest = [limiter.acquire(f"192.0.2.{i}") for i in range(2, 8)]
    with pytest.raises(SessionError):
        limiter.acquire("192.0.2.8")
    limiter.release(first)
    limiter.release(first)
    replacement = limiter.acquire("192.0.2.1")
    assert limiter.active_count == 8
    for slot in [second, replacement, *rest]:
        limiter.release(slot)
    assert limiter.active_count == 0


def test_preauth_sliding_minute_is_bounded_and_failed_attempts_count():
    from src.core.companion.session import PreauthLimiter, SessionError

    clock = FakeClock()
    limiter = PreauthLimiter(clock=clock.monotonic)
    for _ in range(10):
        limiter.release(limiter.acquire("192.0.2.1"))
    with pytest.raises(SessionError):
        limiter.acquire("192.0.2.1")
    for i in range(2, 7):
        for _ in range(10):
            limiter.release(limiter.acquire(f"192.0.2.{i}"))
    with pytest.raises(SessionError):
        limiter.acquire("192.0.2.99")
    clock.advance(60)
    limiter.release(limiter.acquire("192.0.2.1"))
    assert limiter.attempt_count == 1


def test_outbox_total_count_includes_control_and_events():
    from src.core.companion.session import Outbox, SessionError

    box = Outbox(max_items=2)
    event = CurrentConversationTranscript().append_user("가상의 도형").to_wire()
    box.put(event)
    box.put(
        {"type": "ping", "protocol_version": 1, "nonce": sample_id(90)}, control=True
    )
    with pytest.raises(SessionError, match="slow_consumer"):
        box.put(event)
    assert json.loads(box.pop_control())["type"] == "ping"
    assert json.loads(box.pop_event())["payload"]["text"] == "가상의 도형"
    assert box.byte_count == box.item_count == 0


def test_outbox_byte_limit_is_utf8_and_drop_releases_storage():
    from src.core.companion.session import Outbox, SessionError

    event = CurrentConversationTranscript().append_user("행성" * 30).to_wire()
    box = Outbox(max_bytes=8)
    with pytest.raises(SessionError, match="slow_consumer"):
        box.put(event)
    assert box.byte_count == 0
    box = Outbox()
    box.put(event)
    box.clear()
    assert box.item_count == box.byte_count == 0
    assert box.pop_event() is None


def test_outbox_snapshot_watermark_keeps_only_later_matching_events():
    from src.core.companion.session import Outbox

    transcript = CurrentConversationTranscript()
    box = Outbox()
    box.put(transcript.append_user("첫 도형").to_wire())
    captured = transcript.capture()
    second = transcript.append_user("다음 도형").to_wire()
    box.put(second)
    box.put(CurrentConversationTranscript().append_user("다른 가상 대화").to_wire())
    box.trim_events(captured)
    assert json.loads(box.pop_event()) == second
    assert box.item_count == box.byte_count == 0


def test_snapshot_pump_merges_requests_and_keeps_capture_single_until_old_result():
    from src.core.companion.session import SnapshotPump, SyncCapture

    async def scenario():
        transcript = CurrentConversationTranscript()
        transcript.append_user("이전 도형")
        gate = asyncio.Event()
        started = asyncio.Event()
        calls = []
        sent = []
        completed = []

        async def capture(pending):
            result = SyncCapture(transcript.capture())
            calls.append(pending)
            started.set()
            if len(calls) == 1:
                await gate.wait()
            return result

        async def emit(frame):
            sent.append(frame)

        pump = SnapshotPump(capture, emit, completed.append)
        pump.request_sync(())
        await started.wait()
        for _ in range(100):
            pump.request_sync(())
        assert len(calls) == 1
        transcript.reset()
        transcript.append_user("새 도형")
        for _ in range(100):
            pump.invalidate()
        await asyncio.sleep(0)
        assert len(calls) == 1
        gate.set()
        await asyncio.wait_for(pump.wait_idle(), 3)
        assert len(calls) == 2
        assert len(completed) == 1
        assert {frame["conversation_id"] for frame in sent} == {
            transcript.conversation_id
        }
        assert sent[-1]["type"] == "snapshot_end"
        await pump.close()

    asyncio.run(scenario())


def test_snapshot_pump_invalidates_during_send_before_replacement():
    from src.core.companion.session import SnapshotPump, SyncCapture

    async def scenario():
        transcript = CurrentConversationTranscript()
        transcript.append_user("별" * 50000)
        calls, sent, completed = [], [], []

        async def capture(pending):
            calls.append(1)
            return SyncCapture(transcript.capture())

        async def emit(frame):
            sent.append(frame)
            if len(sent) == 2:
                transcript.reset()
                transcript.append_user("새 행성")
                pump.invalidate()
                for _ in range(50):
                    pump.request_sync(())

        pump = SnapshotPump(capture, emit, completed.append)
        pump.request_sync(())
        await asyncio.wait_for(pump.wait_idle(), 3)
        assert len(calls) == 2
        assert len(completed) == 1
        assert [frame["type"] for frame in sent[:3]] == [
            "snapshot_begin",
            "snapshot_part",
            "snapshot_begin",
        ]
        assert sent[-1]["conversation_id"] == transcript.conversation_id
        await pump.close()

    asyncio.run(scenario())


def test_snapshot_pump_close_does_not_leave_capture_or_late_send():
    from src.core.companion.session import SnapshotPump, SyncCapture

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        sent = []

        async def capture(pending):
            started.set()
            await release.wait()
            return SyncCapture(CurrentConversationTranscript().capture())

        async def emit(frame):
            sent.append(frame)

        pump = SnapshotPump(capture, emit, lambda result: None)
        pump.request_sync(())
        await started.wait()
        closing = asyncio.create_task(pump.close())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, 1)
        assert not sent
        assert not pump.busy

    asyncio.run(scenario())


def test_snapshot_pump_serialization_error_is_stable_and_does_not_complete():
    from src.core.companion.session import SnapshotPump, SessionError, SyncCapture

    async def scenario():
        transcript = CurrentConversationTranscript()
        transcript.append_user("x" * (1048576 + 1))

        async def capture(pending):
            return SyncCapture(transcript.capture())

        async def emit(frame):
            pytest.fail("너무 큰 스냅샷을 전송하면 안 된다")

        pump = SnapshotPump(capture, emit, lambda result: pytest.fail("완료 불가"))
        pump.request_sync(())
        with pytest.raises(SessionError, match="snapshot_too_large"):
            await pump.wait_idle()
        await pump.close()

    asyncio.run(scenario())


def test_invalidations_during_real_serialization_do_not_start_parallel_workers(
    monkeypatch,
):
    from src.core.companion.session import SnapshotPump, SyncCapture
    from src.core.companion.transcript import CapturedTranscript

    started, release = threading.Event(), threading.Event()
    original = CapturedTranscript.to_bytes
    calls = []

    def delayed_serialization(captured):
        calls.append(captured.conversation_id)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        return original(captured)

    monkeypatch.setattr(CapturedTranscript, "to_bytes", delayed_serialization)

    async def scenario():
        transcript = CurrentConversationTranscript()
        transcript.append_user("초기 가상 도형")
        sent, completed = [], []

        async def capture(pending):
            return SyncCapture(transcript.capture())

        async def emit(frame):
            sent.append(frame)

        pump = SnapshotPump(capture, emit, completed.append)
        try:
            pump.request_sync(())
            while not started.is_set():
                await asyncio.sleep(0.001)
            for _ in range(100):
                transcript.reset()
                pump.invalidate()
                pump.request_sync(())
            assert len(calls) == 1
            release.set()
            await asyncio.wait_for(pump.wait_idle(), 3)
            assert len(calls) == 2 and len(completed) == 1
            assert all(
                item["conversation_id"] == transcript.conversation_id for item in sent
            )
        finally:
            release.set()
            await pump.close()

    asyncio.run(scenario())


def test_session_slow_consumer_is_bounded_and_cancels_only_its_connection():
    from src.core.companion.adapter import AdmissionContext
    from src.core.companion.session import CompanionSession
    from tests.test_companion_gateway import SyntheticPort

    class SocketBoundary:
        async def close(self, **kwargs):
            self.closed = True

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Future()

    async def scenario():
        port = SyntheticPort()
        context = AdmissionContext(sample_id(1), 1, sample_id(2))
        session = CompanionSession(
            SocketBoundary(),
            port,
            context,
            {
                "type": "ready",
                "protocol_version": 1,
                "server_id": sample_id(3),
                "server_epoch": port.transcript.server_epoch,
                "conversation_id": port.transcript.conversation_id,
                "registration_generation": 1,
            },
        )
        event = port.transcript.append_user("큐 경계의 가상 도형").to_wire()
        for _ in range(300):
            session.queue(event)
        assert session.code == "slow_consumer"
        assert session.outbox.item_count <= 256
        assert session.outbox.byte_count <= 4194304
        assert port.cancelled == [context]
        await asyncio.wait_for(session.run(), 1)
        assert session.finished.is_set()
        assert session.outbox.item_count == 0

    asyncio.run(scenario())
