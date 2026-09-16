"""Qt 소유의 단일 발화 출력 조정기. 생성기는 바꾸지 않고 같은 바이트만 분기한다."""

from dataclasses import dataclass, field, fields
import time

from .audio_buffer import PcmStream
from .audio_route import AudioRoute
from .extension_protocol import validate_extension
from .protocol import ProtocolError, WireMessage, decode_message, encode_message


@dataclass(frozen=True)
class AudioRef:
    registration_generation: int
    server_epoch: str
    connection_generation: str
    conversation_id: str
    message_id: str
    operation_id: str
    utterance_id: str

    def to_fields(self):
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True)
class AudioTransfer:
    kind: str
    ref: AudioRef
    message: WireMessage | None = None
    source: object = field(default=None, repr=False)


class CallbackAudioTransport:
    """불변 제어만 릴레이로 넘긴다. PCM 조각마다 Qt 신호를 추가하지 않는다."""

    def __init__(self, publish):
        self.publish = publish

    def _command(self, kind, message, source=None):
        ref = AudioRef(
            **{item.name: message.fields[item.name] for item in fields(AudioRef)}
        )
        return self.publish(AudioTransfer(kind, ref, message, source))

    def offer(self, message, source):
        return self._command("offer", message, source)

    def send(self, message):
        return self._command("control", message)

    def notify(self, ref):
        return self.publish(AudioTransfer("notify", ref))

    def cancel(self, ref):
        return self.publish(AudioTransfer("cancel", ref))


@dataclass
class _Utterance:
    ref: AudioRef
    source: object
    route: AudioRoute
    streaming: bool
    offered: bool = False


class AudioCoordinator:
    def __init__(
        self,
        transport,
        pc_sink,
        completed,
        *,
        now_ms=None,
        playback=None,
        stream_buffer_seconds=4,
    ):
        self.transport, self.pc = transport, pc_sink
        self.completed = completed
        self._now_ms = now_ms or (lambda: int(time.monotonic() * 1000))
        self._playback = playback or (lambda ref, frames, mouth: None)
        self.context = None
        self.available = False
        self._active = None
        self._stream_buffer_seconds = stream_buffer_seconds

    @property
    def active_ref(self):
        return self._active.ref if self._active else None

    @property
    def target(self):
        return self._active.route.target if self._active else "none"

    @property
    def active_sample_rate(self):
        return self._active.source.format.sample_rate if self._active else None

    def availability(self, context, available):
        if self.context != context and self._active is not None:
            self.disconnected()
        self.context, self.available = context, bool(available)

    def eligible(self, ref, *, visible=True):
        context = self.context
        return bool(
            visible
            and self.available
            and context is not None
            and (
                ref.registration_generation,
                ref.server_epoch,
                ref.connection_generation,
                ref.conversation_id,
            )
            == (
                context.registration_generation,
                context.server_epoch,
                context.connection_generation,
                context.conversation_id,
            )
        )

    def _begin(self, ref, source, streaming, visible):
        if not self.eligible(ref, visible=visible):
            return None
        if self._active is not None:
            self.cancel(self._active.ref, "replaced")
        entry = _Utterance(ref, source, AudioRoute(), streaming)
        self._active = entry
        return entry

    def begin_wave(self, ref, source, *, visible=True):
        entry = self._begin(ref, source, False, visible)
        if entry is None:
            return False
        self._offer(entry)
        if self._active is entry:
            self.source_end(ref)
        return True

    def begin_stream(self, ref, format, *, visible=True):
        source = PcmStream(
            format,
            buffer_limit=format.sample_rate
            * format.frame_bytes
            * self._stream_buffer_seconds,
        )
        return self._begin(ref, source, True, visible) is not None

    def _message(self, entry, kind, **extra):
        return decode_message(
            encode_message(
                {
                    "type": kind,
                    "protocol_version": 1,
                    **entry.ref.to_fields(),
                    **extra,
                }
            )
        )

    @staticmethod
    def _attempt(action):
        try:
            return bool(action())
        except Exception:
            return False

    def _offer(self, entry):
        if not self.eligible(entry.ref):
            self._fallback(entry)
            return
        format = entry.source.format
        entry.route.offer(now_ms=self._now_ms(), phone_eligible=True)
        entry.offered = True
        message = self._message(
            entry,
            "audio_offer",
            sample_rate=format.sample_rate,
            channels=format.channels,
            sample_width=2,
            prepare_timeout_ms=2000,
        )
        if not self._attempt(lambda: self.transport.offer(message, entry.source)):
            self._fallback(entry)

    def offer_pcm(self, ref, data):
        entry = self._active
        if entry is None or entry.ref != ref or not entry.streaming or not data:
            return
        result = entry.source.offer(data)
        if result != "accepted":
            if entry.route.target != "phone":
                self._fallback(entry, extra=data)
            else:
                self.cancel(ref, "buffer_full" if result == "full" else "invalid_pcm")
            return
        if not entry.offered:
            self._offer(entry)
        elif not self._attempt(lambda: self.transport.notify(ref) is not False):
            self.disconnected()

    def source_end(self, ref):
        entry = self._active
        if entry is None or entry.ref != ref:
            return
        if entry.streaming:
            entry.source.finish()
        if not entry.offered:
            self._fallback(entry)
            return
        action = entry.route.source_end(total_frames=entry.source.total_frames)
        if action == "cancel":
            self.cancel(ref, "frame_mismatch")
            return
        if action == "complete_once":
            self._end(entry, "finished")
            return
        message = self._message(
            entry, "audio_source_end", total_frames=entry.source.total_frames
        )
        if not self._attempt(lambda: self.transport.send(message)):
            self._delivery_failed(entry)
        self._attempt(lambda: self.transport.notify(ref) is not False)

    def receive(self, message):
        entry = self._active
        if entry is None or any(
            message.fields.get(key) != value
            for key, value in entry.ref.to_fields().items()
        ):
            return None
        try:
            validate_extension(
                message,
                self.context,
                ("audio_pcm_v1",),
                direction="from_phone",
                sample_rate=entry.source.format.sample_rate,
            )
        except ProtocolError:
            return None
        kind, values = message.type, message.fields
        if kind == "audio_prepared":
            action = entry.route.prepared(now_ms=self._now_ms())
            if action == "play_pc":
                self._fallback(entry)
            elif action == "send_start":
                if entry.streaming:
                    entry.source.commit()
                if not self._attempt(
                    lambda: self.transport.send(self._message(entry, "audio_start"))
                ):
                    self._delivery_failed(entry)
        elif kind == "audio_rejected":
            if entry.route.rejected() == "play_pc":
                self._fallback(entry)
        elif kind == "audio_cancel":
            self.cancel(entry.ref, values["reason"])
        elif kind == "audio_started":
            action = entry.route.started(now_ms=self._now_ms())
            if action == "cancel":
                self.cancel(entry.ref, "playback_timeout")
            elif action == "playing":
                self._playback(entry.ref, 0, 0.0)
        elif kind == "audio_progress":
            action = entry.route.progress(
                now_ms=self._now_ms(), played_frames=values["played_frames"]
            )
            if action == "cancel":
                self.cancel(entry.ref, "playback_timeout")
            elif action == "ack_progress":
                self._playback(entry.ref, values["played_frames"], values["mouth_open"])
                return self._message(
                    entry, "audio_progress_ack", played_frames=values["played_frames"]
                )
        elif kind == "audio_finished":
            action = entry.route.phone_finished(played_frames=values["played_frames"])
            if action == "complete_once":
                self._end(entry, "finished")
            elif action == "cancel":
                self.cancel(entry.ref, "frame_mismatch")
        return None

    def tick(self):
        entry = self._active
        if entry is None or not entry.offered:
            return
        action = entry.route.tick(now_ms=self._now_ms())
        if action == "play_pc":
            self._fallback(entry)
        elif action == "cancel":
            self.cancel(entry.ref, "playback_timeout")

    def _delivery_failed(self, entry):
        action = entry.route.delivery_failed()
        if action == "play_pc":
            self._fallback(entry)
        elif action == "cancel":
            self.cancel(entry.ref, "delivery_failed")

    def disconnected(self):
        self.available = False
        entry = self._active
        if entry is None:
            return
        if entry.route.target != "phone":
            self._fallback(entry)
        else:
            self.cancel(entry.ref, "connection_closed")

    def _fallback(self, entry, extra=None):
        if self._active is not entry:
            return
        self._active = None
        if entry.offered:
            self._attempt(
                lambda: self.transport.send(
                    self._message(entry, "audio_cancel", reason="pc_fallback")
                )
            )
        self._attempt(lambda: self.transport.cancel(entry.ref))
        try:
            if entry.streaming:
                chunks = entry.source.take_for_pc()
                self.pc.start(entry.source.format)
                for data in chunks:
                    self.pc.write(data)
                if extra:
                    self.pc.write(extra)
                if entry.source.source_ended:
                    self.pc.finish()
            else:
                self.pc.play(entry.source.raw)
        finally:
            entry.source.close()
            entry.route.finish()
            self.completed(entry.ref, "pc_fallback")

    def cancel(self, ref, reason):
        entry = self._active
        if entry is None or entry.ref != ref:
            return
        entry.route.cancel()
        self._attempt(
            lambda: self.transport.send(
                self._message(entry, "audio_cancel", reason=reason)
            )
        )
        self._end(entry, reason)

    def _end(self, entry, reason):
        if self._active is not entry:
            return
        self._active = None
        self._attempt(lambda: self.transport.cancel(entry.ref))
        entry.source.close()
        entry.route.finish()
        self.completed(entry.ref, reason)
