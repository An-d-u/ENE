"""모바일 녹음의 설정 스냅샷·취소·늦은 결과 폐기를 소유한다. 대화 요청은 만들지 않는다."""
import asyncio
from dataclasses import dataclass
from importlib.util import find_spec
import time

from ..stt_service import SttSettings, SttBusy, recording_limits, shared_stt_service
from .input_uploads import InputError


def capture_stt_settings(owner):
    minimum, maximum = recording_limits(getattr(owner, "settings", {}))
    reason = "ready"
    if find_spec("faster_whisper") is None:
        reason = "stt_unavailable"
    elif shared_stt_service().busy:
        reason = "stt_busy"
    elif owner.life_record_state.phase != "idle" or (owner.worker and owner.worker.isRunning()):
        reason = "busy"
    return SttSettings.from_mapping(getattr(owner, "settings", {})), minimum, maximum, reason


@dataclass(frozen=True)
class _Recording:
    command: str
    context: object
    settings: SttSettings
    minimum: int
    maximum: int
    expires: float


class SttInput:
    def __init__(self, session, service=None):
        self.session = session
        self.service = service or shared_stt_service()
        self.recording = None
        self.task = None
        self.closed = False

    def _emit(self, kind, context, **fields):
        if self.closed or self.session.extension_context != context or not self.session.synced:
            return
        self.session.queue(dict(type=kind, protocol_version=1,
                                registration_generation=context.registration_generation,
                                server_epoch=context.server_epoch, connection_generation=context.connection_generation,
                                conversation_id=context.conversation_id, **fields), control=True)

    async def receive(self, message):
        fields = message.fields
        context = self.session.extension_context
        if message.type == "stt_cancel":
            if self.recording and self.recording.command == fields["command_id"]:
                self.cancel()
            return
        if message.type in {"stt_limits_request", "stt_begin"}:
            settings, minimum, maximum, reason = await self.session.adapter.call("stt_settings", self.session.context)
            if self.closed or self.session.extension_context != context or not self.session.synced:
                return
            if message.type == "stt_limits_request":
                self._emit("stt_limits", context, query_id=fields["query_id"], min_ms=minimum, max_ms=maximum,
                           sample_rate=16000, channels=1, sample_width=2, allowed=reason == "ready", reason=reason)
                return
            if self.recording is not None or self.task is not None or self.service.busy:
                reason = "stt_busy"
            if reason != "ready":
                self._emit("stt_result", context, command_id=fields["command_id"], status="failed", text="", reason=reason)
                return
            self.recording = _Recording(fields["command_id"], context, settings, minimum, maximum, time.monotonic() + 120)
            self._emit("stt_ready", context, command_id=fields["command_id"], min_ms=minimum, max_ms=maximum)
            return
        if message.type != "stt_transcribe":
            return
        item = self.recording
        if (item is None or item.command != fields["command_id"] or item.context != context
                or time.monotonic() >= item.expires or self.task is not None):
            raise InputError("stt_not_ready")
        length = fields["byte_length"]
        if not item.minimum * 32 <= length <= item.maximum * 32:
            self.recording = None
            raise InputError("recording_duration")
        # 시작 이후 PC가 다른 작업에 진입한 경우에도 모델 실행을 허용하지 않는다.
        _, _, _, reason = await self.session.adapter.call("stt_settings", self.session.context)
        if self.closed or self.recording is not item or self.session.extension_context != context:
            return
        if reason != "ready":
            self.recording = None
            self._emit("stt_result", context, command_id=item.command, status="failed", text="", reason=reason)
            return
        pcm, = self.session.uploads.claim(context, ({**fields, "mime": "audio/pcm"},), "pcm")
        self.task = asyncio.create_task(self._transcribe(item, pcm.body), name="companion-stt-result")

    async def _transcribe(self, item, pcm):
        # shield로 결과 대기만 취소한다. 실제 엔진 잠금과 PCM은 worker가 끝날 때 회수된다.
        worker = asyncio.create_task(asyncio.to_thread(self.service.transcribe_pcm16, pcm, item.settings))
        del pcm
        def consume(done):
            if not done.cancelled():
                done.exception()
        worker.add_done_callback(consume)
        try:
            text = await asyncio.wait_for(asyncio.shield(worker), 120)
            if not text.strip():
                raise InputError("no_speech")
            if len(text.encode("utf-8")) > 16384:
                raise InputError("text_too_large")
            if self.recording is item:
                self._emit("stt_result", item.context, command_id=item.command, status="complete", text=text, reason="ready")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = "stt_timeout" if isinstance(error, TimeoutError) else "stt_busy" if isinstance(error, SttBusy) else error.code if isinstance(error, InputError) else "stt_failed"
            if self.recording is item:
                self._emit("stt_result", item.context, command_id=item.command, status="failed", text="", reason=code)
        finally:
            if self.recording is item:
                self.recording = None
            self.task = None

    def tick(self):
        if self.recording and self.task is None and time.monotonic() >= self.recording.expires:
            self.cancel()

    def cancel(self):
        self.recording = None
        if self.task is not None:
            self.task.cancel()

    def close(self):
        self.closed = True
        self.cancel()
