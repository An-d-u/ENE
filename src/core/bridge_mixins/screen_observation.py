"""사용자 대화에 양보하는 단발 화면 관찰과 안부의 실행 순서."""
from threading import Thread
from time import monotonic
from math import gcd

from PyQt6.QtCore import pyqtSlot

from ...ai.prompt_language import resolve_tts_language
from ..screen_observation import ObservationSchedule, observation_prompt, parse_observation


class ObservationBridgeMixin:
    def _sync_observation_timer(self):
        # 기존 5초 안부 확인과 사용자가 선택한 초 단위 관찰을 한 타이머로 처리한다.
        self.away_timer.setInterval(gcd(5, self._observation_schedule.sample_seconds) * 1000)

    def observation_intervals_state(self):
        schedule = self._observation_schedule
        return schedule.sample_seconds, schedule.request_seconds

    def set_observation_intervals(self, sample_seconds, request_seconds):
        """PC와 앱의 변경을 같은 저장 경로로 받아 현재 관찰에도 반영한다."""
        try:
            self.settings.commit_observation_intervals(sample_seconds, request_seconds)
        except Exception:
            return False
        if (sample_seconds, request_seconds) != self.observation_intervals_state():
            self._observation_schedule.configure(sample_seconds, request_seconds)
            self._sync_observation_timer()
            self.observation_intervals_changed.emit(sample_seconds, request_seconds)
            adapter = getattr(self, "_companion_adapter", None)
            if adapter is not None:
                adapter.publish_extension("observation_intervals_state", dict(conversation_id=self.head().conversation_id,
                    sample_seconds=sample_seconds, request_seconds=request_seconds, saved=True))
        return True

    def _sync_pc_observation_capture(self):
        session = getattr(self, "_screen_share", None)
        set_allowed = getattr(session, "set_observation_allowed", None)
        if callable(set_allowed):
            owner = getattr(self, "_last_question_device", None)
            camera = getattr(self, "_mobile_camera", None)
            set_allowed(owner == ("pc", 0) or (owner is None and not (camera and camera.observe)))

    def _ambient_busy(self):
        if (not self._life_operation_accepts_input() or getattr(self, "_screen_ptt_busy", False)
                or self.pending_response or getattr(self, "_browser_speaking", False)
                or self.proactive_run_queue or getattr(self, "_active_proactive_id", None)):
            return True
        manager = getattr(self, "proactive_manager", None)
        if manager and self._is_proactive_conversation_enabled() and manager.has_due():
            return True
        if any(worker and worker.isRunning() for worker in (self.worker, self.tts_worker)):
            return True
        audio = getattr(self, "_companion_audio", None)
        if audio and (audio.coordinator.active_ref is not None or audio.playback.active):
            return True
        player = getattr(self, "audio_player", None)
        return bool(player and (player.stream_sink is not None or player.player.isPlaying()))

    def _observation_device(self):
        """마지막으로 수락한 질문의 기기가 공유 중일 때만 그 기기를 선택한다."""
        share = getattr(self, "_screen_share", None)
        camera = getattr(self, "_mobile_camera", None)
        desktop = bool(share and share.observe)
        mobile = bool(camera and camera.observe)
        owner = getattr(self, "_last_question_device", None)
        if owner is None:
            if desktop != mobile:
                return "pc" if desktop else "mobile"
        elif desktop and owner == ("pc", 0):
            return "pc"
        elif mobile and owner == ("mobile", camera.scope.registration_generation):
            return "mobile"
        return None

    def _remember_observation_device(self, ref):
        if ref.source not in {"pc", "mobile"}:
            return
        owner = (ref.source, ref.registration_generation if ref.source == "mobile" else 0)
        if getattr(self, "_last_question_device", None) != owner:
            self._last_question_device = owner
            self._sync_pc_observation_capture()
            self._observation_schedule.reset_scene()
            self._publish_mobile_camera_state()

    def _ambient_context(self):
        device = self._observation_device()
        if device == "pc":
            share = self._screen_share
            return (share.generation, share.observe_epoch, getattr(self, "_ambient_input_epoch", 0))
        if device == "mobile":
            camera = self._mobile_camera
            return ("mobile", camera.scope, camera.generation, getattr(self, "_ambient_input_epoch", 0))
        return None

    def _invalidate_automatic_reply(self):
        self._ambient_input_epoch = getattr(self, "_ambient_input_epoch", 0) + 1
        frame = getattr(self, "_observation_frame", None)
        if frame:
            frame.close()
        self._mobile_observation_current = None
        self._stop_observation_voice()

    def _stop_observation_voice(self):
        if getattr(self, "_observation_voice", None) is not None:
            self.interrupt_tts_for_ptt()

    @pyqtSlot(bool)
    def set_browser_speaking(self, speaking):
        self._browser_speaking = speaking

    def _poll_ambient_conversations(self):
        now = monotonic()
        if self._ambient_busy() or now < getattr(self, "_ambient_quiet_until", 0):
            return
        pending = getattr(self, "_observation_pending", None)
        if pending is not None and pending == self._ambient_context():
            return
        if pending is None and self._start_screen_observation(now):
            return
        previous_count = self.away_trigger_count_since_last_user_msg
        self._check_away_nudge_condition()
        if self.away_trigger_count_since_last_user_msg > previous_count:
            self._ambient_quiet_until = now + ObservationSchedule.quiet_seconds

    def _start_screen_observation(self, now):
        context = self._ambient_context()
        if context is None or self._observation_device() != "pc":
            return False
        schedule = self._observation_schedule
        if now < schedule.next_sample:
            return False
        session = self._screen_share
        try:
            image = session.snapshot()
        except (OSError, RuntimeError):
            image = None
        if self._ambient_context() != context or not schedule.candidate(image, now):
            return False
        frame = self._screen_frame_for("observe", image)
        if not frame.read():
            return False
        return self._launch_screen_observation(context, frame, now=now)

    def _launch_screen_observation(self, context, frame, *, now, mobile=False):
        client = self.llm_client
        language = self._prompt_language()
        prompt = observation_prompt(language, resolve_tts_language(self.settings, language), mobile=mobile)
        self._observation_pending = context
        self._observation_frame = frame
        self._observation_schedule.mark_requested(now)
        signal = self.screen_observation_finished

        def observe():
            raw = ""
            try:
                raw = client.observe_screen_once(prompt, frame)
            except Exception:
                # 실패한 자동 관찰은 채팅과 음성에서 조용히 넘어간다.
                pass
            finally:
                frame.close()
            try:
                signal.emit(context, raw if isinstance(raw, str) else "")
            except RuntimeError:
                pass

        Thread(target=observe, daemon=True, name="ene-screen-observation").start()
        return True

    def _observation_still_current(self, context):
        if context != self._ambient_context():
            return False
        if self._observation_device() == "mobile":
            validator = getattr(self, "_mobile_observation_current", None)
            return bool(validator and validator())
        return self._screen_share.validate() and context == self._ambient_context()

    @pyqtSlot(object, str)
    def _finish_screen_observation(self, context, raw):
        if context != getattr(self, "_observation_pending", None):
            return
        self._observation_pending = None
        self._observation_frame = None
        if not self._observation_still_current(context) or self._ambient_busy():
            return
        reply, speech = parse_observation(raw)
        if not reply:
            return
        ref = self._new_companion_request_ref("automatic")
        if not self._display_companion_response(reply, "normal", "", request_ref=ref):
            return
        self._ambient_quiet_until = monotonic() + ObservationSchedule.quiet_seconds
        if (speech and self.enable_tts and self.tts_client and self.audio_player
                and context == self._ambient_context() and not self._ambient_busy()):
            self._play_tts(speech, observation_context=context, observation_ref=ref)
