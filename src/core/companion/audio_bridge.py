"""기존 TTS 표시 순서와 확장 출력 조정기를 연결하는 Qt 어댑터."""

from dataclasses import dataclass
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer

from .audio_buffer import AudioBufferError, MAX_CHUNK, PcmFormat, WavSource
from .audio_coordinator import AudioCoordinator, AudioRef, CallbackAudioTransport
from .audio_route import normalize_output_target
from .character_playback import CharacterPlayback
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
    output_target: str


@dataclass(frozen=True)
class _WaveCandidate:
    intent: _Intent
    context: ExtensionContext
    source: WavSource


@dataclass(frozen=True)
class _StreamCandidate:
    intent: _Intent
    context: ExtensionContext
    format: PcmFormat


class CompanionAudioBridge(QObject):
    capabilities = ("audio_pcm_v1",)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._held = self._playing = None
        self._release_allowed = True
        self._stream_claim = None
        self._pending_stream = None
        self._stream_terminal = False
        self._cancelled_intent = None
        self._pc_bypass = False
        self._pc_analyzer = None
        self._wave_lips = None
        self._phone_available = False
        self._phone_reason = "phone_not_connected"
        self._diagnostic = None
        self._last_snapshot = None
        self._last_wire = None
        self._settings_key = None
        self._pc_pending = None
        self.playback = CharacterPlayback(owner)
        self.coordinator = AudioCoordinator(
            CallbackAudioTransport(self._publish),
            self,
            self._completed,
            playback=self._phone_playback,
            status=self._route_status,
            stream_buffer_seconds=2,
        )
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        try:
            self.coordinator.tick()
            self.playback.tick()
            if not self.playback.active and self.coordinator.active_ref is None and self._diagnostic and self._diagnostic["state"] == "playing":
                self._set_status("none", "idle", "finished")
            if self.coordinator.active_ref is None and not self.playback.active:
                self.timer.stop()
        except Exception as exc:
            self.owner._recover_tts_callback_exception(
                "companion_audio_tick_failed", exc
            )

    def _publish(self, command):
        adapter = getattr(self.owner, "_companion_adapter", None)
        return adapter is not None and adapter.publish_audio(command)

    def bind_worker(self, worker, completion):
        self.playback.finish()
        self._pc_pending = None
        self._stream_claim = None
        self._pending_stream = None
        self._stream_terminal = False
        self._cancelled_intent = None
        self._pc_analyzer = None
        bounded = getattr(worker, "enable_bounded_delivery", None)
        if callable(bounded):
            bounded(can_deliver=lambda data: self._can_deliver_stream_chunk(worker, data))
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
            normalize_output_target(getattr(self.owner, "tts_output_target", "auto")),
        )
        self._set_status("none", "preparing", "generating")
        self._refresh_status()

    def _can_deliver_stream_chunk(self, worker, data):
        active = getattr(self.owner, "_active_tts_operation", None)
        claim = self._stream_claim
        if (
            not isinstance(active, tuple) or len(active) != 2 or active[1] is not worker
            or self._pc_bypass or self._stream_terminal or claim is None
            or self._intent() is not claim[1]
        ):
            return True
        # Qt만 생산하므로 확인과 전달 사이에 HTTP 소비자는 여유를 늘릴 수만 있다.
        return self.coordinator.can_deliver_pcm(claim[0], data)

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

    def pc_intent(self):
        """텍스트 완료가 operation을 해제하기 전에 발화 소유권을 캡처한다."""
        return self._playing[1] if self._pc_bypass and self._playing else self._intent()

    def allows_pc(self, intent=None):
        if intent is not None and intent is self._cancelled_intent:
            return False
        target = intent.output_target if intent else normalize_output_target(
            getattr(self.owner, "tts_output_target", "auto")
        )
        return target != "phone"

    def _block_stream(self, intent, reason="phone_unavailable"):
        self._stream_terminal = True
        self._set_status("none", "stopped", reason)
        if intent is not None:
            self._stop_worker(intent)
            self._release(intent)
        self.owner._flush_pending_response_if_any()
        self._refresh_status()
        return True

    def prepare_pc_stream(self):
        self._pc_pending = self.pc_intent()

    def pc_started(self, intent=None):
        intent = intent or self._pc_pending
        if intent is not None:
            reason = self._diagnostic["reason"] if self._diagnostic else "manual_pc"
            self._set_status("pc", "playing", reason)
        if intent is None or intent.pc_only or not self.owner._companion_request_is_current(intent.request_ref):
            return
        message = self.owner.chat_state.public_assistant_ids.get(intent.request_ref.key)
        if message is None:
            return
        self.playback.begin({
            "server_epoch": intent.request_ref.server_epoch,
            "conversation_id": intent.request_ref.conversation_id,
            "message_id": message, "utterance_id": intent.utterance_id,
        }, "pc", self.owner.audio_player)
        self.timer.start()

    def _phone_playback(self, ref, frames, mouth):
        rate = self.coordinator.active_sample_rate
        if not rate or self._playing is None or self._playing[0] != ref:
            return
        self.playback.phone({
            key: getattr(ref, key) for key in ("server_epoch", "conversation_id", "message_id", "utterance_id")
        }, frames * 1000 // rate, mouth)

    def receive(self, context, message):
        if message.type == "audio_availability":
            head = self.owner.head()
            extension = ExtensionContext(
                context.registration_generation,
                head.server_epoch,
                context.connection_generation,
                head.conversation_id,
            )
            changed = (self.coordinator.context, self._phone_available, self._phone_reason) != (
                extension, message.fields["available"], message.fields["reason"]
            )
            self._phone_available = message.fields["available"]
            self._phone_reason = message.fields["reason"]
            if changed and self._diagnostic and self._diagnostic["state"] in {"stopped", "idle"}:
                self._diagnostic = None
            self.coordinator.availability(
                extension, self._phone_available and self._mode()[0] == "auto"
            )
            return self._refresh_status()
        return self.coordinator.receive(message)

    def connected(self, context, head, capabilities):
        self._phone_available = False
        supported = "audio_pcm_v1" in capabilities
        self._phone_reason = "phone_unavailable" if supported else "audio_not_negotiated"
        self._diagnostic = None
        self._last_wire = None
        self.coordinator.availability(ExtensionContext(context.registration_generation, head.server_epoch,
            context.connection_generation, head.conversation_id) if supported else None, False)
        self._publish_status()

    def _mode(self):
        if not self.owner.enable_tts:
            return "disabled", "tts_disabled"
        intent = self._playing[1] if self._playing else self._intent()
        target = intent.output_target if intent else normalize_output_target(getattr(self.owner, "tts_output_target", "auto"))
        if getattr(self.owner.tts_client, "uses_browser_playback", False):
            return ("disabled" if target == "phone" else "pc_only"), "browser_tts"
        if target == "pc":
            return "pc_only", "manual_pc"
        return "auto", "ready"

    def _idle_reason(self):
        mode, reason = self._mode()
        if mode != "auto":
            return reason
        return self._phone_reason

    def snapshot(self):
        return {"preference": normalize_output_target(getattr(self.owner, "tts_output_target", "auto")),
                **(self._diagnostic or {"output": "none", "state": "idle", "reason": self._idle_reason()})}

    def _set_status(self, output, state, reason):
        self._diagnostic = {"output": output, "state": state, "reason": reason}
        self._publish_status()

    def _route_status(self, ref, output, state, reason):
        if self._playing is not None and self._playing[0] == ref:
            self._set_status(output, state, reason)

    def browser_output(self):
        allowed = self.allows_pc()
        self._set_status("pc" if allowed else "none", "idle" if allowed else "stopped", "browser_tts")
        return allowed

    def _publish_status(self):
        snapshot = self.snapshot()
        if snapshot != self._last_snapshot:
            self._last_snapshot = dict(snapshot)
            self.owner.companion_audio_status_changed.emit(snapshot)
        extension = self.coordinator.context
        if extension is None:
            return None
        status = decode_message(encode_message({
            "type": "audio_status", "protocol_version": 1,
            "registration_generation": extension.registration_generation,
            "server_epoch": extension.server_epoch, "connection_generation": extension.connection_generation,
            "mode": self._mode()[0], **snapshot,
        }))
        adapter = getattr(self.owner, "_companion_adapter", None)
        payload = status.to_dict()
        if adapter is not None and payload != self._last_wire:
            self._last_wire = payload
            adapter.publish(payload)
        return status

    def _refresh_status(self):
        extension = self.coordinator.context
        mode, reason = self._mode()
        if extension is not None:
            self.coordinator.availability(extension, self._phone_available and mode == "auto")
        if mode == "disabled" or (mode == "pc_only" and reason == "browser_tts"):
            self.cancel("output_disabled")
        return self._publish_status()

    def settings_changed(self):
        key = (normalize_output_target(getattr(self.owner, "tts_output_target", "auto")),
               self.owner.enable_tts, bool(getattr(self.owner.tts_client, "uses_browser_playback", False)))
        if key != self._settings_key and (not self._diagnostic or self._diagnostic["state"] in {"idle", "stopped"}):
            self._diagnostic = None
        self._settings_key = key
        self._refresh_status()

    def wave_candidate(self, raw):
        intent = self._intent()
        if intent is not None and intent is self._cancelled_intent:
            return None
        reason = self._ineligible_reason(intent)
        if reason is not None:
            if intent is not None:
                self._set_status("none", "stopped" if not self.allows_pc(intent) else "preparing", reason)
            return None
        if (
            intent is None
            or intent.pc_only
            or intent.output_target == "pc"
            or not self.coordinator.available
            or not self.owner.enable_tts
            or self.owner._tts_interrupted_for_ptt
        ):
            return None
        try:
            source = WavSource(raw)
        except AudioBufferError:
            self._set_status("none", "stopped" if not self.allows_pc(intent) else "preparing", "unsupported_format")
            return None
        self._held = intent
        return _WaveCandidate(intent, self.coordinator.context, source)

    def _ineligible_reason(self, intent):
        if intent is None:
            return "stale_operation"
        if intent.output_target == "pc":
            return "manual_pc"
        if intent.pc_only:
            return "private_result"
        if not self.owner.enable_tts:
            return "tts_disabled"
        if self.owner._tts_interrupted_for_ptt:
            return "interrupted"
        if self.coordinator.context is None:
            return self._phone_reason
        if not self.coordinator.available:
            return self._phone_reason if self._phone_reason != "ready" else "phone_unavailable"
        return None

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
            if self.coordinator.begin_wave(
                ref, candidate.source, allow_pc_fallback=self.allows_pc(candidate.intent)
            ):
                if self.coordinator.active_ref is not None:
                    self.timer.start()
                return True
            self._playing = None
            self.owner.lip_sync_data, self._wave_lips = self._wave_lips, None
        candidate.source.close()
        self._set_status("none", "stopped" if not self.allows_pc(candidate.intent) else "preparing", "phone_unavailable")
        self._release(candidate.intent)
        return False

    def play(self, raw):
        """준비 실패 때만 기존 PC 재생기를 호출한다."""
        self.owner.lip_sync_data = self._wave_lips
        self.pc_started(self._playing[1] if self._playing else None)
        self.owner.audio_player.play(raw)
        if self.owner.lip_sync_data:
            self.owner._start_lip_sync()

    def stream_format(self, sample_rate, channels, sample_width):
        if self._pc_bypass:
            return False
        if self._stream_claim is not None or self._pending_stream is not None or self._stream_terminal:
            return True
        intent = self._intent()
        reason = self._ineligible_reason(intent)
        if reason is not None:
            if not self.allows_pc(intent):
                return self._block_stream(intent, reason)
            self._set_status("none", "preparing", reason)
            return False
        try:
            format = PcmFormat(sample_rate, channels, sample_width)
        except AudioBufferError:
            if not self.allows_pc(intent):
                return self._block_stream(intent, "unsupported_format")
            self._set_status("none", "preparing", "unsupported_format")
            return False
        self._held = intent
        self._pending_stream = _StreamCandidate(intent, self.coordinator.context, format)
        return True

    def stream_chunk(self, data):
        if self._pc_bypass:
            return False
        if self._stream_terminal:
            return True
        candidate = self._pending_stream
        if candidate is not None:
            if not data:
                return True
            if self._intent() is not candidate.intent or self.owner._tts_interrupted_for_ptt:
                self.cancel("stale_operation")
                return True
            if type(data) is not bytes or len(data) > MAX_CHUNK or len(data) % candidate.format.frame_bytes:
                self.cancel("invalid_pcm")
                self.owner._flush_pending_response_if_any()
                return True
            # 공개 처리 중 완료가 먼저 풀리지 않도록 형식 수신 때 확보한 소유권을 유지한다.
            self.owner._flush_pending_response_if_any()
            self._pending_stream = None
            ref = self._reference(candidate.intent, candidate.context)
            if ref is None or not self.coordinator.begin_stream(
                ref, candidate.format, allow_pc_fallback=self.allows_pc(candidate.intent)
            ):
                if not self.allows_pc(candidate.intent):
                    return self._block_stream(candidate.intent)
                self.start(candidate.format)
                self._release(candidate.intent)
                return False
            self._playing = self._stream_claim = (ref, candidate.intent)
            self.timer.start()
        if self._stream_claim is None:
            return False
        self.coordinator.offer_pcm(self._stream_claim[0], data)
        return True

    def stream_finished(self):
        if self._pc_bypass:
            return False
        if self._stream_terminal:
            return True
        if self._pending_stream is not None:
            candidate, self._pending_stream = self._pending_stream, None
            self._stream_terminal = True
            self._release(candidate.intent)
            self._set_status("none", "stopped", "empty_audio")
            return True
        if self._stream_claim is None:
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
        if reason != "pc_fallback":
            self.playback.finish()
        if not self.playback.active:
            self.timer.stop()
        if self._stream_claim == playing:
            if reason == "pc_fallback":
                self._stream_claim = None
            elif reason != "finished":
                self._stop_worker(playing[1])
        self._release(playing[1])
        self._refresh_status()

    def _stop_worker(self, intent):
        active = getattr(self.owner, "_active_tts_operation", None)
        if isinstance(active, tuple) and getattr(active[1], "companion_audio_intent", None) is intent:
            try:
                active[1].request_stop()
            except Exception:
                pass

    def disconnected(self):
        self._phone_available = False
        self.coordinator.disconnected()
        self.coordinator.context = None
        self._last_wire = None
        self._phone_reason = "phone_not_connected"
        self.playback.finish()
        self.timer.stop()
        self._set_status("none", "stopped", "connection_closed")

    def cancel(self, reason, *, release=True):
        intent = self._intent()
        had_audio = intent is not None or self._held is not None or self._playing is not None or self.playback.active
        if intent is not None:
            self._cancelled_intent = intent
            self._stream_terminal = True
            self._stop_worker(intent)
        self._release_allowed = release
        try:
            if self._pending_stream is not None:
                self._stop_worker(self._pending_stream.intent)
                self._pending_stream = None
                self._stream_terminal = True
            if self.coordinator.active_ref is not None:
                self.coordinator.cancel(self.coordinator.active_ref, reason)
            elif self._held is not None:
                self._release(self._held)
        finally:
            self._release_allowed = True
            self._pc_pending = None
            self.playback.finish()
            self.timer.stop()
            if had_audio:
                self._set_status("none", "stopped", reason)
