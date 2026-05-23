"""
WebBridge? TTS, ???, ?? ??? ?? ??.
"""
import json
import time

from ...ai.prompt_language import resolve_prompt_language, resolve_tts_language
from ...ai.viseme_stream_analyzer import VisemeStreamAnalyzer
from ..bridge_workers import StreamingTTSWorker, TTSWorker
from ..model_lip_sync_profile import load_model_lip_sync_profile_for_model_json
from ..tts_sync_controller import TTSSyncController
from .thoughts import ThoughtBridgeMixin


class TTSBridgeMixin:
    def _tts_output_language_names(self, language: str) -> dict[str, str]:
        """프롬프트 언어별 TTS/응답 언어 이름을 반환한다."""
        if language == "en":
            return {"ko": "Korean", "en": "English", "ja": "Japanese"}
        if language == "ja":
            return {"ko": "韓国語", "en": "英語", "ja": "日本語"}
        return {"ko": "한국어", "en": "영어", "ja": "일본어"}

    def _build_tts_output_reminder(self) -> str:
        """현재 턴에만 붙이는 TTS 출력 형식 리마인더를 만든다."""
        read_bool = getattr(self, "_read_bool_setting", None)
        if not callable(read_bool):
            read_bool = lambda key, default=False: ThoughtBridgeMixin._read_bool_setting(self, key, default)
        if not read_bool("enable_tts", bool(getattr(self, "enable_tts", False))):
            return ""

        settings_source = getattr(self, "settings", None)
        response_language = resolve_prompt_language(settings_source=settings_source)
        tts_language = resolve_tts_language(
            settings_source=settings_source,
            response_language=response_language,
        )
        if tts_language == response_language:
            return ""

        names = self._tts_output_language_names(response_language)
        response_name = names.get(response_language, response_language)
        tts_name = names.get(tts_language, tts_language)
        if response_language == "en":
            return (
                "[TTS Output Reminder]\n"
                f"TTS is enabled. In this response, keep the visible reply in {response_name}, "
                f"then always add a [tts]...[/tts] block containing only the {tts_name} text to read aloud.\n"
                "[/TTS Output Reminder]"
            )
        if response_language == "ja":
            return (
                "[TTS出力リマインダー]\n"
                f"TTSが有効です。今回の返答では、表示される返答本文は{response_name}のままにし、"
                f"本文の後に必ず [tts]...[/tts] ブロックを追加して、その中には読み上げ用の{tts_name}文だけを書いてください。\n"
                "[/TTS出力リマインダー]"
            )
        return (
            "[TTS 출력 리마인더]\n"
            f"TTS가 켜져 있습니다. 이번 응답에서는 화면에 보이는 답변 본문은 {response_name}로 유지하고, "
            f"본문 뒤에 반드시 [tts]...[/tts] 블록을 추가해 그 안에는 읽기용 {tts_name} 문장만 작성하세요.\n"
            "[/TTS 출력 리마인더]"
        )

    def _with_tts_output_reminder(self, message: str) -> str:
        """TTS 언어가 응답 언어와 다를 때 현재 요청에만 형식 리마인더를 붙인다."""
        reminder_builder = getattr(self, "_build_tts_output_reminder", None)
        if not callable(reminder_builder):
            reminder_builder = lambda: TTSBridgeMixin._build_tts_output_reminder(self)
        reminder = reminder_builder()
        if not reminder:
            return message
        return f"{reminder}\n\n{message}"

    def _refresh_llm_history_from_visible_conversation(self):
        """현재 보이는 대화 버퍼만 남도록 LLM 히스토리를 재구성한다."""
        if not self.llm_client:
            return
        rebuild = getattr(self.llm_client, "rebuild_context_from_conversation", None)
        if not callable(rebuild):
            return
        try:
            ok = bool(rebuild(self.conversation_buffer))
            if not ok:
                print("[Bridge] LLM 히스토리 재구성 실패")
        except Exception as e:
            print(f"[Bridge] LLM 히스토리 재구성 중 오류: {e}")

    def _should_use_streaming_tts(self) -> bool:
        """현재 응답에서 스트리밍 TTS 경로를 사용할지 판단한다."""
        if not self.tts_streaming_enabled:
            return False
        if not self.tts_client:
            return False
        if getattr(self.tts_client, "uses_browser_playback", False):
            return False
        return bool(getattr(self.tts_client, "supports_streaming", False))

    def _should_use_sync_buffer(self) -> bool:
        """앱이 오디오 출력을 직접 제어할 수 있는 TTS인지 판단한다."""
        if not self.tts_client:
            return True
        return not bool(getattr(self.tts_client, "uses_browser_playback", False))

    def _reset_stream_sync_state(self) -> None:
        """스트리밍 재생 시작 게이트 상태를 초기화한다."""
        self._stream_audio_output_started = False
        self._stream_sync_started_at = None
        self._stream_pending_pcm_chunks = []
        self._stream_pending_lip_sync_data = []
        self._stream_viseme_analyzer = None
        self._sync_controller = TTSSyncController()
        self._sync_started = False
        self._sync_using_rms_fallback = False
        self._stream_future_viseme_frames = []

    def _get_stream_sync_elapsed_ms(self) -> int:
        """스트리밍 동기화 게이트가 열린 뒤 경과한 시간을 반환한다."""
        if self._stream_sync_started_at is None:
            return 0
        return int(max(0.0, (time.monotonic() - self._stream_sync_started_at) * 1000.0))

    def _estimate_stream_chunk_duration_ms(self, pcm_bytes: bytes) -> int:
        """PCM 청크 길이를 밀리초로 환산한다."""
        if not pcm_bytes or not self._stream_audio_format:
            return 0
        sample_rate, channels, sample_width = self._stream_audio_format
        bytes_per_frame = max(1, int(channels) * int(sample_width))
        frame_count = len(pcm_bytes) / bytes_per_frame
        return int(round((frame_count / max(1, int(sample_rate))) * 1000.0))

    def _append_stream_lip_sync_values(self, mouth_values: list, *, target_pending: bool) -> None:
        """스트리밍 립싱크 프레임을 버퍼 또는 활성 타임라인에 적재한다."""
        if not mouth_values:
            return

        target = self._stream_pending_lip_sync_data if target_pending else self.lip_sync_data
        if target is None:
            target = []
            if target_pending:
                self._stream_pending_lip_sync_data = target
            else:
                self.lip_sync_data = target

        for value in mouth_values:
            target.append((self._stream_lip_sync_next_timestamp, float(value)))
            self._stream_lip_sync_next_timestamp = round(self._stream_lip_sync_next_timestamp + 0.05, 6)

    def _ensure_stream_audio_output_started(self) -> None:
        """필요할 때만 실제 스트리밍 오디오 출력을 시작한다."""
        if self._stream_audio_output_started:
            return
        if not self.audio_player or not self._stream_audio_format:
            return
        sample_rate, channels, sample_width = self._stream_audio_format
        self.audio_player.start_stream(sample_rate, channels, sample_width)
        self._stream_audio_output_started = True

    def _start_stream_sync_playback(self) -> None:
        """버퍼링된 메시지, 오디오, 립싱크를 같은 시점에 시작한다."""
        if self._sync_started:
            return

        self._sync_started = True
        self._streaming_tts_started = True
        self._sync_controller.mark_started(self._get_stream_sync_elapsed_ms())
        self._ensure_stream_audio_output_started()
        self._flush_pending_response_if_any()

        if self._stream_pending_pcm_chunks and self.audio_player:
            for chunk in self._stream_pending_pcm_chunks:
                self.audio_player.append_stream_pcm(chunk)
        self._stream_pending_pcm_chunks = []

        if self._stream_pending_lip_sync_data:
            self.lip_sync_data = list(self._stream_pending_lip_sync_data)
            self._stream_pending_lip_sync_data = []
            if not self.lip_sync_timer and self.lip_sync_data:
                self._start_lip_sync()

    def _maybe_start_stream_sync(self) -> None:
        """현재 버퍼 상태로 재생을 시작할지 판단한다."""
        if self._sync_started or not self._should_use_sync_buffer():
            return
        now_ms = self._get_stream_sync_elapsed_ms()
        if self._is_viseme_lipsync_enabled():
            if not self._sync_controller.should_start(now_ms):
                return
            self._sync_using_rms_fallback = self._sync_controller.should_use_rms_fallback(now_ms)
        else:
            min_buffer_ms = self._sync_controller.min_buffer_ms
            max_buffer_ms = self._sync_controller.max_buffer_ms
            if not (
                (int(now_ms) >= min_buffer_ms and self._sync_controller.buffered_audio_ms >= min_buffer_ms)
                or int(now_ms) >= max_buffer_ms
            ):
                return
            self._sync_using_rms_fallback = int(now_ms) >= max_buffer_ms
        self._start_stream_sync_playback()

    def _stop_streaming_lip_sync(self, reset_mouth: bool = True):
        """스트리밍 립싱크 큐와 타이머를 정리한다."""
        if self._stream_lip_sync_timer:
            try:
                self._stream_lip_sync_timer.stop()
            except Exception:
                pass
            self._stream_lip_sync_timer = None
        self._stream_lip_sync_values = []
        if self.lip_sync_timer:
            try:
                self.lip_sync_timer.stop()
            except Exception:
                pass
            self.lip_sync_timer = None
        self.lip_sync_data = None
        self.lip_sync_start_time = None
        self._stream_lip_sync_next_timestamp = 0.0
        self._stream_lip_sync_finished = False
        self._reset_stream_sync_state()
        if reset_mouth:
            self._emit_mouth_signals(0.0)
    
    def _play_tts(self, text: str):
        """립싱크를 포함한 TTS 재생 (비동기 스레드)"""
        self._tts_interrupted_for_ptt = False
        if getattr(self.tts_client, "uses_browser_playback", False):
            self._flush_pending_response_if_any()
            self._play_browser_tts(text)
            return

        # 기존 TTS 워커 종료
        if self.tts_worker and self.tts_worker.isRunning():
            stop_worker = getattr(self.tts_worker, "request_stop", None)
            if callable(stop_worker):
                stop_worker()
            self.tts_worker.quit()
            self.tts_worker.wait()

        self._stop_streaming_lip_sync(reset_mouth=False)
        self._streaming_tts_started = False
        self._stream_lip_sync_next_timestamp = 0.0
        self._stream_lip_sync_finished = False
        self._stream_audio_format = None
        self._reset_stream_sync_state()

        if self._should_use_streaming_tts():
            self.tts_worker = StreamingTTSWorker(self.tts_client, text)
            self.tts_worker.stream_format_ready.connect(self._on_tts_stream_format)
            self.tts_worker.stream_chunk_ready.connect(self._on_tts_stream_chunk)
            self.tts_worker.stream_finished.connect(self._on_tts_stream_finished)
            self.tts_worker.error_occurred.connect(self._on_tts_error)
            self.tts_worker.start()
            print("[Bridge] 스트리밍 TTS 워커 시작 (백그라운드)")
            return

        # 새 TTS 워커 생성
        self.tts_worker = TTSWorker(self.tts_client, text)
        self.tts_worker.tts_ready.connect(self._on_tts_ready)
        self.tts_worker.error_occurred.connect(self._on_tts_error)
        self.tts_worker.start()
        
        print(f"[Bridge] TTS 워커 시작 (백그라운드)")

    def _run_parent_javascript(self, script: str):
        """부모 오버레이의 웹뷰에 자바스크립트를 실행한다."""
        parent = self.parent()
        if not parent or not hasattr(parent, "web_view"):
            return
        try:
            parent.web_view.page().runJavaScript(script)
        except Exception as e:
            print(f"[Bridge] JS 실행 실패: {e}")

    def _play_browser_tts(self, text: str):
        """브라우저 기본 speechSynthesis로 음성을 재생한다."""
        if not self.tts_client:
            return
        try:
            payload = self.tts_client.build_request(text)
        except Exception as e:
            self._on_tts_error(str(e))
            return

        self.lip_sync_data = None
        self.lip_sync_start_time = None
        self._emit_mouth_signals(0.0)
        self._run_parent_javascript(
            "(function(){"
            "if (typeof window.playBrowserTTS === 'function') {"
            f"window.playBrowserTTS({json.dumps(payload, ensure_ascii=False)});"
            "}"
            "})();"
        )
        print("[Bridge] 브라우저 TTS 재생 요청 완료")

    def _flush_pending_response_if_any(self):
        """TTS 대기 중 응답이 있으면 즉시 채팅으로 복구 전송한다."""
        if not self.pending_response:
            return
        if len(self.pending_response) >= 3:
            text, emotion, thought = self.pending_response[:3]
        else:
            text, emotion = self.pending_response
            thought = ""
        print(f"[Bridge] 보류된 응답 즉시 전송: {text[:50]}... [{emotion}]")
        self.message_received.emit(text, emotion, thought)
        self.token_usage_ready.emit(self._resolve_token_usage_payload(self.pending_token_usage_payload))
        if self._is_rerolling:
            self._is_rerolling = False
            self.reroll_state_changed.emit(False)
        self.pending_response = None
        self.pending_token_usage_payload = ""

    def _resolve_token_usage_payload(self, token_usage_payload: str = "") -> str:
        """브리지에서 사용할 토큰 사용량 JSON을 정규화한다."""
        usage = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

        if token_usage_payload:
            try:
                parsed = json.loads(token_usage_payload)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                usage = {
                    "input_tokens": parsed.get("input_tokens") if isinstance(parsed.get("input_tokens"), int) else None,
                    "output_tokens": parsed.get("output_tokens") if isinstance(parsed.get("output_tokens"), int) else None,
                    "total_tokens": parsed.get("total_tokens") if isinstance(parsed.get("total_tokens"), int) else None,
                }
                return json.dumps(usage, ensure_ascii=False)

        getter = getattr(self.llm_client, "get_last_token_usage", None)
        if callable(getter):
            try:
                latest_usage = getter()
            except Exception:
                latest_usage = None
            if isinstance(latest_usage, dict):
                usage = {
                    "input_tokens": latest_usage.get("input_tokens") if isinstance(latest_usage.get("input_tokens"), int) else None,
                    "output_tokens": latest_usage.get("output_tokens") if isinstance(latest_usage.get("output_tokens"), int) else None,
                    "total_tokens": latest_usage.get("total_tokens") if isinstance(latest_usage.get("total_tokens"), int) else None,
                }

        return json.dumps(usage, ensure_ascii=False)

    def _get_settings_value(self, key: str, default=None):
        """Settings 객체나 dict 어디서든 값을 읽는다."""
        if isinstance(self.settings, dict):
            return self.settings.get(key, default)
        getter = getattr(self.settings, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except TypeError:
                return getter(key)
        return default

    def _is_viseme_lipsync_enabled(self) -> bool:
        """설정값을 읽어 viseme 립싱크 적용 여부를 반환한다."""
        raw_value = self._get_settings_value("viseme_lipsync_enabled", True)
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"0", "false", "no", "off"}:
                return False
            if normalized in {"1", "true", "yes", "on"}:
                return True
        return bool(raw_value)

    def _get_model_lip_sync_profile(self):
        """현재 모델 경로 기준 립싱크 프로파일을 캐시해 반환한다."""
        model_json_path = str(self._get_settings_value("model_json_path", "") or "").strip()
        cache_key = model_json_path or "__default__"
        if self._model_lip_sync_profile is not None and self._model_lip_sync_profile_key is None:
            return self._model_lip_sync_profile
        if self._model_lip_sync_profile is not None and self._model_lip_sync_profile_key == cache_key:
            return self._model_lip_sync_profile

        settings_source = self.settings if isinstance(self.settings, dict) else None
        self._model_lip_sync_profile = load_model_lip_sync_profile_for_model_json(
            model_json_path=model_json_path or None,
            settings_source=settings_source,
        )
        self._model_lip_sync_profile_key = cache_key
        return self._model_lip_sync_profile

    def _build_mouth_pose(self, rms_open: float, viseme: str | None = None, confidence: float = 0.0) -> dict:
        """RMS와 viseme를 합쳐 모델 적응형 입모양 payload를 만든다."""
        profile = self._get_model_lip_sync_profile()
        threshold = float(profile.fallback.get("confidence_threshold", 0.55) or 0.55)
        shape_weight = float(profile.fallback.get("viseme_shape_weight", 0.75) or 0.75)
        open_value = max(0.0, min(float(rms_open), 1.0))
        normalized_confidence = max(0.0, min(float(confidence), 1.0))
        viseme_key = str(viseme or "sil").strip() or "sil"
        viseme_payload = profile.viseme_map.get(viseme_key, profile.viseme_map.get("sil", {}))

        pose = {
            "open": open_value,
            "jaw": 0.0,
            "form": 0.0,
            "funnel": 0.0,
            "pucker_widen": 0.0,
            "tongue": 0.0,
            "confidence": normalized_confidence,
            "source": "rms_expression" if self._is_viseme_lipsync_enabled() else "rms",
        }

        if viseme_payload and normalized_confidence > 0.0:
            viseme_open = float(viseme_payload.get("mouth_open", open_value))
            pose["open"] = max(open_value, viseme_open * normalized_confidence)
            pose["source"] = "viseme_blend" if normalized_confidence >= threshold else "rms_blend"

            confidence_scale = 1.0
            if normalized_confidence < threshold and threshold > 0:
                confidence_scale = normalized_confidence / threshold
            scaled_weight = shape_weight * confidence_scale

            pose["jaw"] = max(float(viseme_payload.get("jaw_open", 0.0)) * scaled_weight, pose["open"] * 0.45 if "jaw_open" in profile.param_bindings else 0.0)
            pose["form"] = float(viseme_payload.get("mouth_form", 0.0)) * scaled_weight
            pose["funnel"] = float(viseme_payload.get("mouth_funnel", 0.0)) * scaled_weight
            pose["pucker_widen"] = float(viseme_payload.get("mouth_pucker_widen", 0.0)) * scaled_weight
            pose["tongue"] = float(viseme_payload.get("tongue", 0.0)) * scaled_weight

        return pose

    def _dequeue_stream_viseme_frame(self, timestamp_sec: float):
        """현재 재생 시점까지 도달한 viseme 프레임 하나를 꺼낸다."""
        future_frames = self._sync_controller.dequeue_future_visemes()
        if future_frames:
            self._stream_future_viseme_frames.extend(future_frames)

        matched_frame = None
        remaining_frames = []
        for frame in self._stream_future_viseme_frames:
            if float(frame.timestamp) <= float(timestamp_sec) + 0.001:
                matched_frame = frame
            else:
                remaining_frames.append(frame)
        self._stream_future_viseme_frames = remaining_frames
        return matched_frame

    def _emit_mouth_signals(self, mouth_value: float, *, timestamp_sec: float | None = None) -> None:
        """기존 mouth open 시그널과 새 mouth pose 시그널을 함께 보낸다."""
        self.lip_sync_update.emit(float(mouth_value))

        viseme = None
        confidence = 0.0
        if self._is_viseme_lipsync_enabled() and timestamp_sec is not None and not self._sync_using_rms_fallback:
            frame = self._dequeue_stream_viseme_frame(timestamp_sec)
            if frame is not None:
                viseme = frame.viseme
                confidence = frame.confidence

        pose = self._build_mouth_pose(
            rms_open=float(mouth_value),
            viseme=viseme,
            confidence=confidence,
        )
        self.mouth_pose_update.emit(json.dumps(pose, ensure_ascii=False))

    def _on_tts_stream_format(self, sample_rate: int, channels: int, sample_width: int):
        """스트리밍 TTS의 PCM 포맷이 준비되면 재생기를 시작한다."""
        self._stream_audio_format = (int(sample_rate), int(channels), int(sample_width))
        self._stream_viseme_analyzer = VisemeStreamAnalyzer(
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )
        print(
            f"[Bridge] 스트리밍 TTS 포맷 준비: "
            f"{sample_rate}Hz / {channels}ch / {sample_width}byte"
        )
        if self.audio_player:
            self.audio_player.start_stream(sample_rate, channels, sample_width)
            self._stream_audio_output_started = True

    def _on_tts_stream_chunk(self, pcm_bytes: bytes, mouth_values: list):
        """스트리밍 PCM 청크를 재생 버퍼와 실시간 립싱크 큐에 전달한다."""
        if self._tts_interrupted_for_ptt:
            print("[Bridge] PTT 중단 플래그로 스트리밍 청크 무시")
            return

        if self._stream_sync_started_at is None and (pcm_bytes or mouth_values):
            self._stream_sync_started_at = time.monotonic()

        if pcm_bytes and self._stream_audio_format:
            duration_ms = self._estimate_stream_chunk_duration_ms(pcm_bytes)
            self._sync_controller.push_audio(duration_ms=duration_ms, pcm_bytes=pcm_bytes)
            if self._stream_viseme_analyzer is not None:
                viseme_frames = self._stream_viseme_analyzer.push_pcm(pcm_bytes)
                if viseme_frames:
                    self._sync_controller.mark_viseme_ready_through(viseme_frames[-1].timestamp + 0.05)
                    self._sync_controller.push_viseme_frames(viseme_frames)

        self._maybe_start_stream_sync()

        if pcm_bytes:
            if self._sync_started and self.audio_player:
                self._ensure_stream_audio_output_started()
                self.audio_player.append_stream_pcm(pcm_bytes)
            else:
                self._stream_pending_pcm_chunks.append(bytes(pcm_bytes))

        if mouth_values:
            self._append_stream_lip_sync_values(mouth_values, target_pending=not self._sync_started)
            if self._sync_started and not self.lip_sync_timer and self.lip_sync_data:
                self._start_lip_sync()

    def _on_tts_stream_finished(self):
        """스트리밍 TTS 종료 신호를 받아 잔여 버퍼를 마무리한다."""
        print("[Bridge] 스트리밍 TTS 종료")
        self._stream_lip_sync_finished = True
        if self._stream_viseme_analyzer is not None:
            tail_frames = self._stream_viseme_analyzer.finalize()
            if tail_frames:
                self._sync_controller.mark_viseme_ready_through(tail_frames[-1].timestamp + 0.05)
                self._sync_controller.push_viseme_frames(tail_frames)
        if not self._sync_started and self._stream_pending_pcm_chunks:
            self._sync_using_rms_fallback = self._sync_controller.should_use_rms_fallback(self._get_stream_sync_elapsed_ms())
            self._start_stream_sync_playback()
        elif not self._streaming_tts_started:
            self._flush_pending_response_if_any()
        if self.audio_player:
            self._ensure_stream_audio_output_started()
            self.audio_player.finish_stream()

    def _drain_stream_lip_sync_queue(self):
        """50ms 간격으로 스트리밍 립싱크 값을 UI에 보낸다."""
        if self._stream_lip_sync_values:
            next_value = float(self._stream_lip_sync_values.pop(0))
            self._emit_mouth_signals(next_value)

        if self._stream_lip_sync_values:
            if self._stream_lip_sync_timer and not self._stream_lip_sync_timer.isActive():
                self._stream_lip_sync_timer.start(50)
            return

        if self._stream_lip_sync_finished:
            self._stop_streaming_lip_sync(reset_mouth=True)
            return

        if self._stream_lip_sync_timer:
            self._stream_lip_sync_timer.stop()

    def interrupt_tts_for_ptt(self):
        """PTT 시작 시 현재 음성 출력/립싱크를 즉시 중단한다."""
        # 생성 중인 TTS 결과가 곧 도착할 수 있으면 다음 오디오 재생을 1회 스킵한다.
        self._tts_interrupted_for_ptt = bool(self.pending_response) or bool(
            self.tts_worker and self.tts_worker.isRunning()
        )
        if self.tts_worker and self.tts_worker.isRunning():
            stop_worker = getattr(self.tts_worker, "request_stop", None)
            if callable(stop_worker):
                stop_worker()

        # 재생 중 오디오 중단
        if self.audio_player:
            try:
                self.audio_player.stop()
            except Exception as e:
                print(f"[Bridge] PTT TTS 중단 실패(audio): {e}")

        # 립싱크 중단 및 입 닫기
        if self.lip_sync_timer:
            try:
                self.lip_sync_timer.stop()
            except Exception:
                pass
            self.lip_sync_timer = None
        self.lip_sync_data = None
        self.lip_sync_start_time = None
        self._stop_streaming_lip_sync(reset_mouth=False)
        self._emit_mouth_signals(0.0)
        self._run_parent_javascript(
            "(function(){"
            "if (typeof window.stopBrowserTTS === 'function') {"
            "window.stopBrowserTTS();"
            "}"
            "})();"
        )

        # 보류 중 텍스트가 있으면 즉시 표시
        self._flush_pending_response_if_any()
        print(f"[Bridge] PTT로 TTS 중단 처리 완료 (skip_next={self._tts_interrupted_for_ptt})")

    def _on_tts_ready(self, audio_data: bytes, lip_sync_data: list):
        """비동기 TTS 완료 후 오디오 재생"""
        print(f"[Bridge] TTS 준비 완료: {len(audio_data)} bytes, {len(lip_sync_data)} 프레임")
        self._stop_streaming_lip_sync(reset_mouth=False)
        
        # 립싱크 데이터 저장
        self.lip_sync_data = lip_sync_data if lip_sync_data else None
        
        # 보류된 텍스트가 있으면 이제 전송 (텍스트 + 음성 동시 제공)
        self._flush_pending_response_if_any()
        
        # PTT로 끊긴 경우, 이번 오디오는 재생하지 않는다.
        if self._tts_interrupted_for_ptt:
            self._tts_interrupted_for_ptt = False
            self.lip_sync_data = None
            self._emit_mouth_signals(0.0)
            print("[Bridge] PTT 중단 플래그로 오디오 재생 생략")
            return
        
        # 오디오 재생
        self.audio_player.play(audio_data)
        
        # 립싱크 시작
        if self.lip_sync_data:
            self._start_lip_sync()
    
    def _on_tts_error(self, error_msg: str):
        """TTS 오류 처리"""
        print(f"[Bridge] TTS 오류: {error_msg}")
        self._stop_streaming_lip_sync(reset_mouth=True)
        # TTS 실패 시 보류 중이던 텍스트를 즉시 복구 전송한다.
        self._flush_pending_response_if_any()
        if self._is_rerolling:
            self._is_rerolling = False
            self.reroll_state_changed.emit(False)
    
    def _start_lip_sync(self):
        """립싱크 타이머 시작"""
        from PyQt6.QtCore import QTimer, QTime
        
        if not self.lip_sync_data:
            return
        
        # 기존 타이머 정리
        if self.lip_sync_timer:
            self.lip_sync_timer.stop()
            self.lip_sync_timer = None
        
        # 시작 시간 기록
        self.lip_sync_start_time = QTime.currentTime()
        self.lip_sync_index = 0
        
        # 타이머 생성 (10ms 간격으로 체크)
        self.lip_sync_timer = QTimer(self)
        self.lip_sync_timer.timeout.connect(self._update_lip_sync)
        self.lip_sync_timer.start(10)
        
        print(f"[Bridge] 립싱크 타이머 시작")
    
    def _update_lip_sync(self):
        """립싱크 업데이트 (타이머 콜백)"""
        if not self.lip_sync_data or not self.lip_sync_start_time:
            return
        
        from PyQt6.QtCore import QTime
        
        # 경과 시간 계산 (초)
        elapsed_ms = self.lip_sync_start_time.msecsTo(QTime.currentTime())
        elapsed_sec = elapsed_ms / 1000.0
        
        # 현재 시간에 해당하는 립싱크 값 찾기
        mouth_value = 0.0
        found = False
        
        for i in range(self.lip_sync_index, len(self.lip_sync_data)):
            timestamp, value = self.lip_sync_data[i]
            
            if timestamp <= elapsed_sec:
                mouth_value = value
                self.lip_sync_index = i
                found = True
            else:
                break
        
        # 값 전송
        if found:
            self._emit_mouth_signals(mouth_value, timestamp_sec=elapsed_sec)
        
        # 모든 데이터 처리 완료 시 타이머 종료
        if self.lip_sync_index >= len(self.lip_sync_data) - 1:
            if self._stream_audio_format is not None and not self._stream_lip_sync_finished:
                return
            self.lip_sync_timer.stop()
            self.lip_sync_timer = None
            self._emit_mouth_signals(0.0)  # 입 닫기
            print(f"[Bridge] 립싱크 완료")
