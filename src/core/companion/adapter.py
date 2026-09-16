"""불변 명령과 상관 ID로 네트워크 루프에서 Qt 소유자에게 요청한다."""

import asyncio
from dataclasses import dataclass, field
import threading
import time
from uuid import uuid4

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot

from .protocol import ProtocolError, WireMessage, decode_message, encode_message
from .transcript import TranscriptEvent


class AdapterError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AdmissionContext:
    gateway_generation: str
    registration_generation: int
    connection_generation: str | None = None


@dataclass(frozen=True)
class ConversationHead:
    server_epoch: str
    conversation_id: str


@dataclass(frozen=True)
class AdapterCommand:
    correlation_id: str
    operation: str
    context: AdmissionContext
    deadline: float
    message: WireMessage | None = field(default=None, repr=False)
    pending: tuple[str, ...] = ()


@dataclass
class _PendingCall:
    command: AdapterCommand
    future: asyncio.Future = field(repr=False)
    cancelled: threading.Event = field(default_factory=threading.Event, repr=False)


class QtGatewayAdapter(QObject):
    requested = pyqtSignal(object)

    def __init__(self, owner, parent=None, *, timeout=5):
        super().__init__(parent)
        self._owner = owner
        self._timeout = timeout
        self._gateway = None
        self._registration = 0
        self._connection = None
        self._enabled = False
        self._blocked = True
        self._loop = self._event_sink = None
        self._media_sink = self._media_wake = None
        # 잠금은 전송표 조회/취소에만 사용한다. Qt 작업이나 await 동안 잡지 않는다.
        self._lock = threading.Lock()
        self._closing = True
        self._pending = {}
        self.requested.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        bind = getattr(owner, "bind_companion_adapter", None)
        if callable(bind):
            bind(self)

    def is_current_connection(self, connection):
        """구연결의 상태 알림을 새 연결에 전달하지 않도록 Qt에서 확인한다."""
        self._require_qt()
        return self._enabled and not self._blocked and connection is not None and connection == self._connection

    def validate_admission(self, context):
        """소유 브리지에서도 같은 Qt 권한 원본을 검사한다."""
        self._require_qt()
        if not self._enabled or context.gateway_generation != self._gateway:
            raise AdapterError("stale_gateway")
        if context.registration_generation != self._registration:
            raise AdapterError("stale_registration")
        if self._blocked:
            raise AdapterError("admission_blocked")
        if (
            self._connection is None
            or context.connection_generation != self._connection
        ):
            raise AdapterError("stale_connection")

    def _require_qt(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("qt_thread_required")

    def configure(self, gateway_generation, registration_generation):
        self._require_qt()
        self._gateway = gateway_generation
        self._registration = registration_generation
        self._connection = None
        self._enabled, self._blocked = True, False
        with self._lock:
            self._closing = False
        character = getattr(self._owner, "_companion_character", None)
        if character is not None:
            character.activate()

    def disable(self):
        self._require_qt()
        self._enabled, self._blocked = False, True
        self._connection = None
        self._notify_owner_disconnect()
        character = getattr(self._owner, "_companion_character", None)
        if character is not None:
            character.deactivate()
        with self._lock:
            self._closing = True
            for call in self._pending.values():
                call.cancelled.set()
            cancelled = tuple(self._pending)
        # aboutToQuit 이후에는 Qt queued ACK가 오지 않아도 네트워크 await를 해제한다.
        loop = self._loop
        if loop is not None and not loop.is_closed():
            for correlation_id in cancelled:
                try:
                    loop.call_soon_threadsafe(
                        self._complete, correlation_id, None, "stale_gateway"
                    )
                except RuntimeError:
                    break

    def attach(self, loop, event_sink, *, media_sink=None):
        self._require_qt()
        if self._loop is not None:
            raise RuntimeError("adapter_already_attached")
        self._loop, self._event_sink = loop, event_sink
        self._media_sink = media_sink

    def publish_audio(self, command):
        """PCM은 공유 버퍼가 보관한다. 읽기 깨우기는 최대 한 개만 대기한다."""
        self._require_qt()
        loop = self._loop
        if (
            not self._enabled
            or self._closing
            or loop is None
            or self._media_sink is None
        ):
            return False
        with self._lock:
            if command.kind == "notify":
                already_pending = self._media_wake is not None
                self._media_wake = command
                if already_pending:
                    return True
        try:
            if command.kind == "notify":
                loop.call_soon_threadsafe(self._deliver_audio_wake)
            else:
                loop.call_soon_threadsafe(self._deliver_audio, command)
            return True
        except RuntimeError:
            with self._lock:
                self._media_wake = None
            return False

    def _deliver_audio_wake(self):
        with self._lock:
            command, self._media_wake = self._media_wake, None
        if command is not None:
            self._deliver_audio(command)

    def _deliver_audio(self, command):
        if self._enabled and not self._closing and self._media_sink is not None:
            self._media_sink(command)

    def detach(self):
        """소유 루프와 스레드가 끝난 뒤 Qt에서 호출한다."""
        self._require_qt()
        if self._loop is not None and self._loop.is_running():
            raise RuntimeError("adapter_loop_running")
        self._loop = self._event_sink = None
        self._media_sink = None
        with self._lock:
            self._pending.clear()
            self._media_wake = None

    @property
    def pending_count(self):
        with self._lock:
            return len(self._pending)

    async def call(self, operation, context, *, message=None, pending=()):
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            raise AdapterError("adapter_unavailable")
        if operation not in {
            "connect",
            "disconnect",
            "capture",
            "character_capture",
            "send",
            "extension",
            "block",
            "restore",
            "register",
        }:
            raise AdapterError("unsupported_command")
        command = AdapterCommand(
            str(uuid4()),
            operation,
            context,
            time.monotonic() + self._timeout,
            message,
            tuple(pending),
        )
        call = _PendingCall(command, loop.create_future())
        with self._lock:
            if self._closing:
                raise AdapterError("stale_gateway")
            if len(self._pending) >= 32 or (
                operation == "capture"
                and any(
                    item.command.operation == "capture"
                    for item in self._pending.values()
                )
            ):
                raise AdapterError("adapter_busy")
            self._pending[command.correlation_id] = call
        self.requested.emit(command)
        try:
            value, error = await asyncio.wait_for(
                asyncio.shield(call.future), self._timeout
            )
        except TimeoutError:
            call.cancelled.set()
            # Qt가 응답하기 전에는 전송표/캡처 자리를 회수하지 않는다.
            raise AdapterError("adapter_timeout") from None
        except asyncio.CancelledError:
            call.cancelled.set()
            raise
        if error is not None:
            raise AdapterError(error)
        return value

    def cancel_connection(self, context):
        """구연결의 Qt 대기 명령을 표시한다. 이미 수락한 작업은 취소하지 않는다."""
        with self._lock:
            for call in self._pending.values():
                if call.command.context == context:
                    call.cancelled.set()

    def _complete(self, correlation_id, value, error):
        with self._lock:
            call = self._pending.pop(correlation_id, None)
        if call is not None and not call.future.done():
            call.future.set_result((value, error))

    @pyqtSlot(object)
    def _dispatch(self, command):
        self._require_qt()
        with self._lock:
            call = self._pending.get(command.correlation_id)
        if call is None:
            return
        value, error = None, None
        try:
            if not self._enabled or command.context.gateway_generation != self._gateway:
                raise AdapterError("stale_gateway")
            if call.cancelled.is_set():
                raise AdapterError("stale_connection")
            if time.monotonic() >= command.deadline:
                raise AdapterError("adapter_timeout")
            value = self._execute(command)
        except AdapterError as failure:
            error = failure.code
        except Exception:
            error = "adapter_failed"
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(
                    self._complete, command.correlation_id, value, error
                )
            except RuntimeError:
                pass

    def _execute(self, command):
        operation, context = command.operation, command.context
        if operation == "block":
            self._blocked = True
            self._notify_owner_disconnect()
            return None
        if operation == "register":
            if not self._blocked:
                raise AdapterError("admission_barrier_required")
            self._registration = context.registration_generation
            self._connection = None
            self._blocked = False
            return None
        if context.registration_generation != self._registration:
            raise AdapterError("stale_registration")
        if operation == "restore":
            self._blocked = False
            return None
        if operation == "disconnect":
            if context.connection_generation == self._connection:
                self._connection = None
                self._notify_owner_disconnect()
            return None
        if self._blocked:
            raise AdapterError("admission_blocked")
        if operation == "connect":
            if context.connection_generation is None:
                raise AdapterError("stale_connection")
            result = self._owner.head()
            self._connection = context.connection_generation
            return result
        if (
            self._connection is None
            or context.connection_generation != self._connection
        ):
            raise AdapterError("stale_connection")
        if operation == "capture":
            return self._owner.capture(context.registration_generation, command.pending)
        if operation == "character_capture":
            character = getattr(self._owner, "_companion_character", None)
            if character is None:
                raise AdapterError("unsupported_command")
            return character.state.capture()
        if operation == "extension" and isinstance(command.message, WireMessage):
            from .extension_protocol import (
                CAPABILITIES,
                ExtensionContext,
                validate_extension,
            )

            head = self._owner.head()
            current = ExtensionContext(
                context.registration_generation,
                head.server_epoch,
                context.connection_generation,
                head.conversation_id,
            )
            try:
                # 실제 협상은 세션에서 검사한다. Qt 경계에서는 현재 소유권과 수신 방향을 재검사한다.
                validate_extension(
                    command.message, current, CAPABILITIES, direction="from_phone"
                )
            except ProtocolError as error:
                raise AdapterError(error.code) from None
            handler = getattr(self._owner, "submit_extension", None)
            if not callable(handler):
                raise AdapterError("unsupported_command")
            return handler(context, command.message)
        if (
            operation == "send"
            and isinstance(command.message, WireMessage)
            and command.message.type == "send_text"
        ):
            return self._owner.submit(context, command.message)
        raise AdapterError("unsupported_command")

    def _notify_owner_disconnect(self):
        handler = getattr(self._owner, "_companion_connection_closed", None)
        if callable(handler):
            try:
                handler()
            except Exception:
                # PC 재생 복구가 실패해도 연결 차단과 대기 호출 회수는 계속한다.
                print("[Companion] audio_disconnect_cleanup_failed")

    def publish_extension(self, kind, fields):
        """현재 Qt 연결 식별자를 붙인다. 협상 여부는 서버 세션에서 다시 검사한다."""
        self._require_qt()
        if not self._enabled or self._blocked or self._connection is None:
            return
        self.publish({
            **fields, "type": kind, "protocol_version": 1,
            "registration_generation": self._registration,
            "server_epoch": self._owner.head().server_epoch,
            "connection_generation": self._connection,
        })

    def publish(self, event):
        self._require_qt()
        if not self._enabled or self._loop is None:
            return
        value = event.to_wire() if isinstance(event, TranscriptEvent) else event
        try:
            message = decode_message(encode_message(value))
        except ProtocolError as error:
            if error.code != "message_too_large" or not isinstance(
                event, TranscriptEvent
            ):
                raise
            message = decode_message(
                encode_message(
                    {
                        "type": "resync_required",
                        "protocol_version": 1,
                        "server_epoch": event.server_epoch,
                        "conversation_id": event.conversation_id,
                        "reason": "large_event",
                    }
                )
            )
        try:
            self._loop.call_soon_threadsafe(self._event_sink, message)
        except RuntimeError:
            pass
