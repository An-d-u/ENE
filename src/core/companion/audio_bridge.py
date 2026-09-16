"""기존 TTS 표시 순서와 확장 출력 조정기를 연결하는 Qt 어댑터."""

from dataclasses import dataclass
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer

from .audio_buffer import AudioBufferError, PcmFormat, WavSource
from .audio_coordinator import AudioCoordinator, AudioRef, CallbackAudioTransport
from .extension_protocol import ExtensionContext
from .protocol import decode_message, encode_message
from .requests import RequestRef


@dataclass(frozen=True)
class _Intent:
    request_ref: RequestRef
    normal_operation_id: int
    operation_id: str
    utterance_id: str
    pc_only: bool


@dataclass(frozen=True)
class _WaveCandidate:
    intent: _Intent
    context: ExtensionContext
    source: WavSource


class CompanionAudioBridge(QObject):
    capabilities = ("audio_pcm_v1",)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._held = self._playing = None
        self._release_allowed = True
        self._stream_claim = None
        self._pc_bypass = False
        self._pc_analyzer = None
        self._wave_lips = None
        self.coordinator = AudioCoordinator(
            CallbackAudioTransport(self._publish),
            self,
            self._completed,
            stream_buffer_seconds=2,
        )
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        try:
            self.coordinator.tick()
        except Exception as exc:
            self.owner._recover_tts_callback_exception(
                "companion_audio_tick_failed", exc
            )

    def _publish(self, command):
        adapter = getattr(self.owner, "_companion_adapter", None)
        return adapter is not None and adapter.publish_audio(command)

    def bind_worker(self, worker, completion):
        self._stream_claim = None
        self._pc_analyzer = None
        bounded = getattr(worker, "enable_bounded_delivery", None)
        if callable(bounded):
            bounded()
        if not isinstance(completion, dict) or not isinstance(
            completion.get("request_ref"), RequestRef
        ):
            return
        operation = completion.get("normal_operation_id")
        if type(operation) is not int:
            return
        worker.companion_audio_intent = _Intent(
            completion["request_ref"],
            operation,
            str(uuid4()),
            str(uuid4()),
            bool(completion.get("companion_file_result")),
        )

    def _intent(self):
        active = getattr(self.owner, "_active_tts_operation", None)
        if not isinstance(active, tuple) or len(active) != 2:
            return None
        intent = getattr(active[1], "companion_audio_intent", None)
        state = self.owner.life_record_state
        if not isinstance(intent, _Intent) or not state.matches_operation(
            intent.normal_operation_id, "normal_reply"
        ):
            return None
        return (
            intent
            if self.owner._companion_request_is_current(intent.request_ref)
            else None
        )

    def receive(self, context, message):
        if message.type == "audio_availability":
            head = self.owner.head()
            extension = ExtensionContext(
                context.registration_generation,
                head.server_epoch,
                context.connection_generation,
                head.conversation_id,
            )
            mode, reason = "auto", "ready"
            if not self.owner.enable_tts:
                mode, reason = "disabled", "tts_disabled"
            elif getattr(self.owner.tts_client, "uses_browser_playback", False):
                mode, reason = "pc_only", "browser_tts"
            self.coordinator.availability(
                extension, message.fields["available"] and mode == "auto"
            )
            return decode_message(
                encode_message(
                    {
                        "type": "audio_status",
                        "protocol_version": 1,
                        "registration_generation": extension.registration_generation,
                        "server_epoch": extension.server_epoch,
                        "connection_generation": extension.connection_generation,
                        "mode": mode,
                        "reason": reason,
                    }
                )
            )
        return self.coordinator.receive(message)

    def wave_candidate(self, raw):
        intent = self._intent()
        if (
            intent is None
            or intent.pc_only
            or not self.coordinator.available
            or not self.owner.enable_tts
            or self.owner._tts_interrupted_for_ptt
        ):
            return None
        try:
            source = WavSource(raw)
        except AudioBufferError:
            return None
        self._held = intent
        return _WaveCandidate(intent, self.coordinator.context, source)

    def holds_completion(self, payload):
        return (
            isinstance(payload, dict)
            and self._held is not None
            and (
                payload.get("normal_operation_id") == self._held.normal_operation_id
                and payload.get("request_ref") == self._held.request_ref
            )
        )

    def _reference(self, intent, context):
        message_id = self.owner.chat_state.public_assistant_ids.get(
            intent.request_ref.key
        )
        if message_id is None or context is None:
            return None
        return AudioRef(
            context.registration_generation,
            intent.request_ref.server_epoch,
            context.connection_generation,
            intent.request_ref.conversation_id,
            message_id,
            intent.operation_id,
            intent.utterance_id,
        )

    def play_wave(self, candidate):
        if candidate is None:
            return False
        ref = self._reference(candidate.intent, candidate.context)
        if ref is not None:
            self._playing = (ref, candidate.intent)
            self._wave_lips = self.owner.lip_sync_data
            self.owner.lip_sync_data = None
            if self.coordinator.begin_wave(ref, candidate.source):
                if self.coordinator.active_ref is not None:
                    self.timer.start()
                return True
            self._playing = None
            self.owner.lip_sync_data, self._wave_lips = self._wave_lips, None
        self._release(candidate.intent)
        return False

    def play(self, raw):
        """준비 실패 때만 기존 PC 재생기를 호출한다."""
        self.owner.lip_sync_data = self._wave_lips
        self.owner.audio_player.play(raw)
        if self.owner.lip_sync_data:
            self.owner._start_lip_sync()

    def stream_format(self, sample_rate, channels, sample_width):
        if self._pc_bypass:
            return False
        if self._stream_claim is not None:
            return True
        intent = self._intent()
        if (
            intent is None
            or intent.pc_only
            or not self.owner.enable_tts
            or self.owner._tts_interrupted_for_ptt
        ):
            return False
        ref = self._reference(intent, self.coordinator.context)
        if ref is None or not self.coordinator.eligible(ref):
            return False
        try:
            format = PcmFormat(sample_rate, channels, sample_width)
        except AudioBufferError:
            return False
        if not self.coordinator.begin_stream(ref, format):
            return False
        self._held = intent
        self._playing = self._stream_claim = (ref, intent)
        self.timer.start()
        return True

    def stream_chunk(self, data):
        if self._pc_bypass or self._stream_claim is None:
            return False
        self.coordinator.offer_pcm(self._stream_claim[0], data)
        return True

    def stream_finished(self):
        if self._pc_bypass or self._stream_claim is None:
            return False
        self.coordinator.source_end(self._stream_claim[0])
        return True

    def _pc_call(self, method, *args):
        self._pc_bypass = True
        try:
            method(*args)
        finally:
            self._pc_bypass = False

    def start(self, format):
        from src.ai.audio_analyzer import RealtimeLipSyncAnalyzer

        self._pc_analyzer = RealtimeLipSyncAnalyzer(
            sample_rate=format.sample_rate,
            channels=format.channels,
            sample_width=format.sample_width,
            frame_duration_ms=50,
        )
        self._pc_call(
            self.owner._process_tts_stream_format,
            format.sample_rate,
            format.channels,
            format.sample_width,
        )

    def write(self, data):
        self._pc_call(
            self.owner._process_tts_stream_chunk, data, self._pc_analyzer.push_pcm(data)
        )

    def finish(self):
        tail = self._pc_analyzer.finalize()
        if tail:
            self._pc_call(self.owner._process_tts_stream_chunk, b"", tail)
        self._pc_call(self.owner._complete_tts_stream)

    def _release(self, intent):
        if self._held is intent:
            self._held = None
        payload = getattr(self.owner, "_pending_response_completion", None)
        if (
            self._release_allowed
            and not self.owner.pending_response
            and isinstance(payload, dict)
            and payload.get("normal_operation_id") == intent.normal_operation_id
            and payload.get("request_ref") == intent.request_ref
        ):
            self.owner._finalize_pending_response_completion_if_any()

    def _completed(self, ref, reason):
        playing = self._playing
        if playing is None or playing[0] != ref:
            return
        self._playing = None
        self._wave_lips = None
        self.timer.stop()
        if self._stream_claim == playing:
            if reason == "pc_fallback":
                self._stream_claim = None
            elif reason != "finished":
                active = getattr(self.owner, "_active_tts_operation", None)
                if (
                    isinstance(active, tuple)
                    and getattr(active[1], "companion_audio_intent", None) is playing[1]
                ):
                    try:
                        active[1].request_stop()
                    except Exception:
                        pass
        self._release(playing[1])

    def disconnected(self):
        self.coordinator.disconnected()

    def cancel(self, reason, *, release=True):
        self._release_allowed = release
        try:
            if self.coordinator.active_ref is not None:
                self.coordinator.cancel(self.coordinator.active_ref, reason)
            elif self._held is not None:
                self._release(self._held)
        finally:
            self._release_allowed = True
            self.timer.stop()
