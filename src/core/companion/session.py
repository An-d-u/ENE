"""서버 루프 소유의 연결 자원·생존 확인·단일 스냅샷 전송 작업."""

import asyncio
from collections import deque
from dataclasses import dataclass
import itertools
import time
from uuid import uuid4

from aiohttp import WSMsgType

from .protocol import ProtocolError, WireMessage, decode_message, encode_message
from .transcript import CapturedTranscript, TranscriptError
from .connection_resources import ConnectionResources
from .extension_protocol import (
    EXTENSION_TYPES,
    ExtensionContext,
    validate_extension,
    feature_for,
)


class SessionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Heartbeat:
    def __init__(
        self, *, clock=time.monotonic, id_factory=None, interval=15, timeout=10
    ):
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._interval, self._timeout = interval, timeout
        self._next_ping = clock() + interval
        self._nonce = None
        self._deadline = None

    def tick(self):
        now = self._clock()
        if self._nonce is not None:
            if now >= self._deadline:
                raise SessionError("heartbeat_timeout")
            return None
        if now < self._next_ping:
            return None
        self._nonce = self._id_factory()
        self._deadline = now + self._timeout
        return {"type": "ping", "protocol_version": 1, "nonce": self._nonce}

    def pong(self, nonce):
        if (
            self._nonce is None
            or nonce != self._nonce
            or self._clock() >= self._deadline
        ):
            return False
        self._nonce = self._deadline = None
        self._next_ping = self._clock() + self._interval
        return True


class TokenBucket:
    def __init__(self, rate, burst, *, clock=time.monotonic):
        self._rate, self._burst = rate, burst
        self._clock = clock
        self._tokens = float(burst)
        self._updated = clock()

    def take(self):
        now = self._clock()
        self._tokens = min(
            self._burst, self._tokens + max(0, now - self._updated) * self._rate
        )
        self._updated = now
        if self._tokens < 1 - 1e-9:
            return False
        self._tokens = max(0, self._tokens - 1)
        return True


class PreauthLimiter:
    """추적 주소 수도 분당 전체 시도 상한으로 제한한다."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._attempts = deque()
        self._slots = {}

    @property
    def active_count(self):
        return len(self._slots)

    @property
    def attempt_count(self):
        return len(self._attempts)

    def acquire(self, address):
        now = self._clock()
        while self._attempts and self._attempts[0][0] <= now - 60:
            self._attempts.popleft()
        if (
            len(self._attempts) >= 60
            or sum(item[1] == address for item in self._attempts) >= 10
        ):
            raise SessionError("rate_limited")
        self._attempts.append((now, address))
        if (
            len(self._slots) >= 8
            or sum(value == address for value in self._slots.values()) >= 2
        ):
            raise SessionError("rate_limited")
        slot = str(uuid4())
        self._slots[slot] = address
        return slot

    def release(self, slot):
        self._slots.pop(slot, None)


class Outbox:
    """제어/이벤트를 분리하되 두 큐의 합계에 같은 상한을 적용한다."""

    def __init__(self, *, max_items=256, max_bytes=4194304):
        self._control, self._events = deque(), deque()
        self._max_items, self._max_bytes = max_items, max_bytes
        self.byte_count = 0

    @property
    def item_count(self):
        return len(self._control) + len(self._events)

    def put(self, message, *, control=False):
        raw = encode_message(message)
        size = len(raw.encode("utf-8"))
        if (
            self.item_count >= self._max_items
            or self.byte_count + size > self._max_bytes
        ):
            raise SessionError("slow_consumer")
        value = message.to_dict() if isinstance(message, WireMessage) else message
        # 직렬화 후에는 호출자의 변경 가능한 사전을 참조하지 않는다.
        identity = (
            value.get("server_epoch"),
            value.get("conversation_id"),
            value.get("event_seq"),
        )
        (self._control if control else self._events).append((raw, size, identity))
        self.byte_count += size

    def _pop(self, queue):
        if not queue:
            return None
        raw, size, _ = queue.popleft()
        self.byte_count -= size
        return raw

    def pop_control(self):
        return self._pop(self._control)

    def pop_event(self):
        return self._pop(self._events)

    def trim_events(self, captured):
        kept = deque()
        for item in self._events:
            epoch, conversation, seq = item[2]
            if (epoch, conversation) == (
                captured.server_epoch,
                captured.conversation_id,
            ) and seq > captured.event_seq:
                kept.append(item)
            else:
                self.byte_count -= item[1]
        self._events = kept

    def clear_events(self):
        while self._events:
            self._pop(self._events)

    def clear(self):
        self._events.clear()
        self._control.clear()
        self.byte_count = 0


@dataclass(frozen=True)
class SyncCapture:
    transcript: CapturedTranscript
    statuses: tuple[WireMessage, ...] = ()


def _prepare_frames(captured):
    frames = captured.wire_messages()
    # 최초 next에서 전체 직렬화가 일어나므로 작업 스레드에서 수행한다.
    first = next(frames)
    return first, frames


class SnapshotPump:
    """무효화해도 이전 캡처/직렬화가 돌아올 때까지 후속 작업을 만들지 않는다."""

    def __init__(self, capture, emit, on_complete):
        self._capture, self._emit, self._on_complete = capture, emit, on_complete
        self._task = None
        self._generation = 0
        self._pending = ()
        self._rerun = False
        self._closed = False
        self._error = None

    @property
    def busy(self):
        return self._task is not None and not self._task.done()

    @property
    def failure(self):
        return self._error

    def request_sync(self, pending):
        if self._closed:
            return
        if self._error is not None:
            raise SessionError(self._error)
        pending = tuple(pending)
        if self.busy:
            if pending != self._pending:
                self._pending = pending
                self._rerun = True
            return
        self._pending = pending
        self._task = asyncio.create_task(self._run(), name="companion-snapshot")

    def invalidate(self):
        self._generation += 1
        if self.busy:
            self._rerun = True

    async def _run(self):
        try:
            while not self._closed:
                generation = self._generation
                self._rerun = False
                async with asyncio.timeout(120):
                    result = await self._capture(self._pending)
                    if self._closed:
                        return
                    if generation != self._generation:
                        continue
                    worker = asyncio.create_task(
                        asyncio.to_thread(_prepare_frames, result.transcript)
                    )
                    try:
                        first, frames = await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        # to_thread는 취소로 실제 실행이 멈추지 않는다. 해제 전에 회수한다.
                        await worker
                        raise
                    try:
                        for frame in itertools.chain((first,), frames):
                            if self._closed or generation != self._generation:
                                break
                            await asyncio.wait_for(self._emit(frame), 10)
                        else:
                            if not self._closed and generation == self._generation:
                                self._on_complete(result)
                    finally:
                        frames.close()
                if not self._rerun:
                    return
        except TranscriptError as error:
            self._error = error.code
        except TimeoutError:
            self._error = "snapshot_timeout"
        except SessionError as error:
            self._error = error.code
        except Exception:
            self._error = "snapshot_failed"

    async def wait_idle(self):
        if self._task is not None:
            await asyncio.shield(self._task)
        if self._error is not None:
            raise SessionError(self._error)

    async def close(self):
        self._closed = True
        self._generation += 1
        if self._task is not None:
            await asyncio.shield(self._task)


class CompanionSession:
    """수신·명령 접수·단일 writer·timer를 각각 한 작업으로 유지한다."""

    def __init__(
        self,
        ws,
        adapter,
        context,
        ready,
        *,
        validate_connection=None,
        heartbeat_interval=15,
        heartbeat_timeout=10,
    ):
        self.ws, self.adapter, self.context = ws, adapter, context
        self._validate_connection = validate_connection or (lambda: None)
        self.server_epoch = ready["server_epoch"]
        self.conversation_id = ready["conversation_id"]
        self.capabilities = tuple(ready.get("capabilities", ()))
        self.resources = ConnectionResources()
        # 재동기화·pong·대기 음성 제안/EOF의 전용 자리도 총 상한에 포함한다.
        self.outbox = Outbox(max_items=252, max_bytes=4194304 - 3 * 65536 - 125)
        self._audio_offer = self._audio_source_end = None
        self._audio_offer_sent_id = None
        self.outbox.put(ready, control=True)
        if self.capabilities:
            self.outbox.put(
                {
                    "type": "extensions_ready",
                    "protocol_version": 1,
                    "registration_generation": context.registration_generation,
                    "server_epoch": self.server_epoch,
                    "connection_generation": context.connection_generation,
                    "capabilities": list(self.capabilities),
                },
                control=True,
            )
        self._heartbeat = Heartbeat(
            interval=heartbeat_interval, timeout=heartbeat_timeout
        )
        self._rate = TokenBucket(10, 20)
        self._control_rate = TokenBucket(20, 40)
        self._commands = asyncio.Queue(maxsize=20)
        self._extension_rate = TokenBucket(30, 60)
        self._extensions = asyncio.Queue(maxsize=60)
        self._wake = asyncio.Event()
        self._stopped = asyncio.Event()
        self.finished = asyncio.Event()
        self._frame = None
        self._inflight_ack = None
        self._resync = None
        self._native_pong = None
        self._sync_version = self._capture_version = 0
        self._snapshot_active = False
        self._ever_synced = False
        self.synced = False
        self.code = "connection_closed"
        self._pump = SnapshotPump(
            self._capture, self._emit_frame, self._snapshot_complete
        )

    def stop(self, code="connection_closed"):
        if self._stopped.is_set():
            return
        self.code = code
        self.synced = False
        self.adapter.cancel_connection(self.context)
        self.resources.cancel()
        self._audio_offer = self._audio_source_end = None
        self._stopped.set()
        self._wake.set()

    def queue(self, message, *, control=False):
        if self._stopped.is_set():
            return
        try:
            self.outbox.put(message, control=control)
        except SessionError as error:
            self.stop(error.code)
        self._wake.set()

    def publish(self, message):
        if self._stopped.is_set():
            return
        value = message.to_dict()
        if message.type in EXTENSION_TYPES:
            try:
                validate_extension(
                    message,
                    self.extension_context,
                    self.capabilities,
                    direction="from_pc",
                )
            except ProtocolError:
                return
            if message.type == "character_changed":
                self.resources.observe_character(value["state_revision"], value["model_version"])
            self.queue(message, control=True)
            return
        if message.type == "resync_required":
            if value["conversation_id"] != self.conversation_id:
                self.resources.cancel_audio()
            self.server_epoch, self.conversation_id = (
                value["server_epoch"],
                value["conversation_id"],
            )
            self._sync_version += 1
            self.synced = False
            self._resync = encode_message(value)
            self.outbox.clear_events()
            self._pump.invalidate()
            if self._ever_synced and not self._pump.busy:
                self._snapshot_active = True
                self._pump.request_sync(())
            self._wake.set()
        elif message.type == "event":
            if (value["server_epoch"], value["conversation_id"]) == (
                self.server_epoch,
                self.conversation_id,
            ):
                self.queue(message)
        elif message.type == "request_status":
            self.queue(message, control=True)

    def publish_audio(self, command):
        if self._stopped.is_set():
            return
        ref = command.ref
        context = self.extension_context
        if (
            ref.registration_generation,
            ref.server_epoch,
            ref.connection_generation,
            ref.conversation_id,
        ) != (
            context.registration_generation,
            context.server_epoch,
            context.connection_generation,
            context.conversation_id,
        ) or "audio_pcm_v1" not in self.capabilities:
            return
        if command.kind == "offer":
            if (
                not self.synced
                or self._audio_offer is not None
                or command.message.type != "audio_offer"
            ):
                return
            validate_extension(
                command.message, context, self.capabilities, direction="from_pc"
            )
            if any(
                command.message.fields.get(key) != value
                for key, value in ref.to_fields().items()
            ):
                return
            source = command.source
            if (
                source is None
                or source.closed
                or (
                    command.message.fields["sample_rate"],
                    command.message.fields["channels"],
                )
                != (source.format.sample_rate, source.format.channels)
            ):
                return
            self.resources.add_audio(ref.utterance_id, source)
            self._audio_offer = command.message
            self._audio_source_end = self._audio_offer_sent_id = None
        elif ref.utterance_id == self.resources.audio_id:
            if command.kind == "notify":
                self.resources.audio_ready.set()
            elif command.kind == "cancel":
                self.resources.cancel_audio()
                self._audio_offer = self._audio_source_end = None
            elif command.kind == "control":
                validate_extension(
                    command.message, context, self.capabilities, direction="from_pc"
                )
                if any(
                    command.message.fields.get(key) != value
                    for key, value in ref.to_fields().items()
                ):
                    return
                if (
                    command.message.type == "audio_source_end"
                    and self._audio_offer_sent_id != ref.utterance_id
                ):
                    self._audio_source_end = command.message
                else:
                    self.publish(command.message)
        self._wake.set()

    async def _capture(self, pending):
        self._validate_connection()
        self._capture_version = self._sync_version
        return await self.adapter.call("capture", self.context, pending=pending)

    @property
    def extension_context(self):
        return ExtensionContext(
            self.context.registration_generation,
            self.server_epoch,
            self.context.connection_generation,
            self.conversation_id,
        )

    async def _emit_frame(self, frame):
        if self._stopped.is_set():
            raise SessionError(self.code)
        ack = asyncio.get_running_loop().create_future()
        self._frame = (frame, ack, self._capture_version)
        self._wake.set()
        await ack

    def _snapshot_complete(self, result):
        if self._stopped.is_set():
            return
        captured = result.transcript
        if (captured.server_epoch, captured.conversation_id) != (
            self.server_epoch,
            self.conversation_id,
        ):
            self.stop("stale_session")
            return
        self.outbox.trim_events(captured)
        self.synced = True
        self._snapshot_active = False
        for status in result.statuses:
            self.queue(status, control=True)
        self._wake.set()

    async def _send_raw(self, raw):
        self._validate_connection()
        await asyncio.wait_for(self.ws.send_str(raw), 10)

    async def _writer(self):
        while not self._stopped.is_set():
            self._wake.clear()
            raw = self.outbox.pop_control()
            if raw is not None:
                message = decode_message(raw)
                if message.type in EXTENSION_TYPES:
                    try:
                        validate_extension(
                            message,
                            self.extension_context,
                            self.capabilities,
                            direction="from_pc",
                        )
                    except ProtocolError:
                        continue
                    if message.type in {"audio_start", "audio_source_end"} and (
                        self.resources.audio_cancelled
                        or message.fields["utterance_id"] != self.resources.audio_id
                    ):
                        continue
                await self._send_raw(raw)
                continue
            if self._native_pong is not None:
                data, self._native_pong = self._native_pong, None
                await asyncio.wait_for(self.ws.pong(data), 10)
                continue
            if self._resync is not None:
                raw, self._resync = self._resync, None
                await self._send_raw(raw)
                continue
            if self._frame is not None:
                frame, ack, version = self._frame
                self._frame = None
                self._inflight_ack = ack
                if version == self._sync_version:
                    await self._send_raw(encode_message(frame))
                    if frame["type"] == "snapshot_end":
                        self.synced = True
                if not ack.done():
                    ack.set_result(None)
                self._inflight_ack = None
                continue
            if self.synced and not self._snapshot_active:
                raw = self.outbox.pop_event()
                if raw is not None:
                    await self._send_raw(raw)
                    continue
                if self._audio_offer is not None:
                    message, self._audio_offer = self._audio_offer, None
                    if self.resources.audio_cancelled:
                        self._audio_source_end = None
                        continue
                    try:
                        validate_extension(
                            message,
                            self.extension_context,
                            self.capabilities,
                            direction="from_pc",
                        )
                    except ProtocolError:
                        self._audio_source_end = None
                        continue
                    self._audio_offer_sent_id = message.fields["utterance_id"]
                    await self._send_raw(encode_message(message))
                    if self._audio_source_end is not None:
                        end, self._audio_source_end = self._audio_source_end, None
                        self.publish(end)
                    continue
            await self._wake.wait()

    async def _reader(self):
        async for item in self.ws:
            self._validate_connection()
            if item.type in {WSMsgType.PING, WSMsgType.PONG}:
                if not self._control_rate.take():
                    raise SessionError("rate_limited")
                if item.type == WSMsgType.PING:
                    self._native_pong = item.data
                    self._wake.set()
                continue
            if item.type != WSMsgType.TEXT:
                raise SessionError("invalid_message")
            message = decode_message(
                item.data,
                allowed_types={"sync_request", "send_text", "ping", "pong"}
                | EXTENSION_TYPES,
            )
            if message.type in EXTENSION_TYPES:
                if not self._extension_rate.take():
                    raise SessionError("rate_limited")
                try:
                    validate_extension(
                        message,
                        self.extension_context,
                        self.capabilities,
                        direction="from_phone",
                    )
                except ProtocolError:
                    continue
                try:
                    self._extensions.put_nowait(message)
                except asyncio.QueueFull:
                    raise SessionError("rate_limited") from None
                continue
            if message.type in {"ping", "pong"}:
                if not self._control_rate.take():
                    raise SessionError("rate_limited")
                if message.type == "pong":
                    self._heartbeat.pong(message.fields["nonce"])
                else:
                    self.queue(
                        {
                            "type": "pong",
                            "protocol_version": 1,
                            "nonce": message.fields["nonce"],
                        },
                        control=True,
                    )
                continue
            if not self._rate.take():
                raise SessionError("rate_limited")
            if message.type == "sync_request":
                self.synced = False
                self._ever_synced = self._snapshot_active = True
                self._pump.request_sync(message.fields["pending_request_ids"])
            elif not self.synced:
                self.queue(
                    {
                        "type": "error",
                        "protocol_version": 1,
                        "code": "sync_required",
                        "request_id": message.fields["request_id"],
                    },
                    control=True,
                )
            else:
                try:
                    self._commands.put_nowait(message)
                except asyncio.QueueFull:
                    raise SessionError("rate_limited") from None

    async def _command_worker(self):
        while True:
            message = await self._commands.get()
            self._validate_connection()
            try:
                result = await self.adapter.call("send", self.context, message=message)
                if result is not None:
                    self.queue(result, control=True)
            except Exception as error:
                # 내부 어댑터의 고정 코드만 내보낸다. 일반 예외 내용은 버린다.
                from .adapter import AdapterError

                code = (
                    error.code
                    if isinstance(error, AdapterError)
                    else "admission_failed"
                )
                self.queue(
                    {
                        "type": "error",
                        "protocol_version": 1,
                        "code": code,
                        "request_id": message.fields["request_id"],
                    },
                    control=True,
                )

    async def _extension_worker(self):
        while True:
            message = await self._extensions.get()
            self._validate_connection()
            try:
                validate_extension(
                    message,
                    self.extension_context,
                    self.capabilities,
                    direction="from_phone",
                )
                result = await self.adapter.call(
                    "extension", self.context, message=message
                )
                if result is not None:
                    self.publish(result)
            except ProtocolError:
                continue
            except Exception:
                self.queue(
                    {
                        "type": "extension_error",
                        "protocol_version": 1,
                        "registration_generation": self.context.registration_generation,
                        "server_epoch": self.server_epoch,
                        "connection_generation": self.context.connection_generation,
                        "feature": feature_for(message.type, message.fields),
                        "code": "extension_failed",
                    },
                    control=True,
                )

    async def _timer(self):
        while True:
            await asyncio.sleep(0.02)
            if self._pump.failure is not None:
                raise SessionError(self._pump.failure)
            ping = self._heartbeat.tick()
            if ping is not None:
                self.queue(ping, control=True)

    async def run(self):
        tasks = [
            asyncio.create_task(operation(), name="companion-" + name)
            for name, operation in (
                ("receiver", self._reader),
                ("writer", self._writer),
                ("commands", self._command_worker),
                ("extensions", self._extension_worker),
                ("heartbeat", self._timer),
                ("stop", self._stopped.wait),
            )
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                error = task.exception() if not task.cancelled() else None
                if isinstance(error, (SessionError, ProtocolError)):
                    self.stop(error.code)
                elif error is not None:
                    self.stop("connection_failed")
        finally:
            self.stop()
            await self.resources.wait_closed()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._frame is not None:
                _, ack, _ = self._frame
                if not ack.done():
                    ack.set_exception(SessionError(self.code))
                self._frame = None
            if self._inflight_ack is not None and not self._inflight_ack.done():
                self._inflight_ack.set_exception(SessionError(self.code))
            self._inflight_ack = None
            await self._pump.close()
            self.outbox.clear()
            while not self._commands.empty():
                self._commands.get_nowait()
            while not self._extensions.empty():
                self._extensions.get_nowait()
            try:
                await asyncio.wait_for(
                    self.ws.close(
                        code=1000 if self.code == "connection_closed" else 1008,
                        message=self.code.encode("ascii"),
                    ),
                    2,
                )
            except (TimeoutError, ConnectionError):
                pass
            self.finished.set()
