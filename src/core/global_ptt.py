"""
전역 Push-to-Talk + faster-whisper STT 컨트롤러.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .hotkey_utils import MODIFIER_TOKENS, hotkey_to_spec, normalize_hotkey_text


def _pynput_key_to_token(key) -> str | None:
    """
    pynput 키 객체를 내부 단축키 토큰으로 변환한다.
    """
    if key is None:
        return None

    name = str(getattr(key, "name", "") or "").strip().lower()
    if name:
        table = {
            "ctrl": "ctrl",
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "shift": "shift",
            "shift_l": "shift",
            "shift_r": "shift",
            "alt": "alt",
            "alt_l": "alt",
            "alt_r": "alt",
            "alt_gr": "alt",
            "cmd": "meta",
            "cmd_l": "meta",
            "cmd_r": "meta",
            "super": "meta",
            "windows": "meta",
            "space": "space",
            "enter": "enter",
            "esc": "esc",
            "tab": "tab",
            "backspace": "backspace",
            "delete": "delete",
            "insert": "insert",
            "home": "home",
            "end": "end",
            "page_up": "page_up",
            "page_down": "page_down",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
        }
        mapped = table.get(name)
        if mapped:
            return mapped
        if name.startswith("f") and name[1:].isdigit():
            return name

    char = getattr(key, "char", None)
    if isinstance(char, str) and char:
        if char == " ":
            return "space"
        lowered = char.lower()
        if lowered == "+":
            return "plus"
        if lowered == "-":
            return "minus"
        if lowered == ",":
            return "comma"
        if lowered == ".":
            return "period"
        if lowered == "/":
            return "slash"
        if lowered == "\\":
            return "backslash"
        if lowered == ";":
            return "semicolon"
        if lowered == "'":
            return "quote"
        if lowered == "`":
            return "backquote"
        if lowered == "[":
            return "left_bracket"
        if lowered == "]":
            return "right_bracket"
        if len(lowered) == 1 and lowered.isprintable() and not lowered.isspace():
            return lowered

    vk = getattr(key, "vk", None)
    if isinstance(vk, int):
        if 48 <= vk <= 57 or 65 <= vk <= 90:
            return chr(vk).lower()

    return None


@dataclass
class _RecorderResult:
    pcm_bytes: bytes
    duration_sec: float


class _RawAudioRecorder:
    """
    PTT 구간 오디오를 16kHz mono PCM16으로 수집한다.
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1, dtype: str = "int16"):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.dtype = dtype
        self._stream = None
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()
        self._started_at = 0.0

    def start(self):
        import sounddevice as sd

        self.stop(silent=True)
        with self._lock:
            self._chunks = []
            self._started_at = time.monotonic()

        def callback(indata, frames, _stream_time, status):
            if status:
                # status는 로그성 정보라서 녹음은 계속 유지한다.
                print(f"[PTT] 오디오 입력 status: {status}")
            if frames <= 0:
                return
            with self._lock:
                self._chunks.append(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            callback=callback,
        )
        self._stream.start()

    def stop(self, silent: bool = False) -> _RecorderResult:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

        with self._lock:
            raw = b"".join(self._chunks)
            self._chunks = []
            started_at = self._started_at
            self._started_at = 0.0

        if started_at > 0:
            duration_sec = max(0.0, time.monotonic() - started_at)
        else:
            duration_sec = 0.0

        if not silent:
            print(f"[PTT] 녹음 정지: {duration_sec:.2f}s, bytes={len(raw)}")
        return _RecorderResult(pcm_bytes=raw, duration_sec=duration_sec)


class _FasterWhisperService:
    """
    faster-whisper 모델 로딩/추론을 관리한다.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._model_size = "small"
        self._device = "auto"
        self._compute_type = "int8"
        self._language = "ko"

    def configure(self, model_size: str, device: str, compute_type: str, language: str):
        model_size = str(model_size or "small").strip()
        device = str(device or "auto").strip()
        compute_type = str(compute_type or "int8").strip()
        language = str(language or "ko").strip()
        with self._lock:
            changed = (
                self._model_size != model_size
                or self._device != device
                or self._compute_type != compute_type
            )
            self._model_size = model_size
            self._device = device
            self._compute_type = compute_type
            self._language = language
            if changed:
                # 설정이 바뀌면 다음 추론 시점에 모델을 다시 로딩한다.
                self._model = None

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model
            from faster_whisper import WhisperModel

            print(
                f"[PTT] faster-whisper 모델 로딩: "
                f"size={self._model_size}, device={self._device}, compute={self._compute_type}"
            )
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            return self._model

    def transcribe_pcm16(self, pcm_bytes: bytes) -> str:
        if not pcm_bytes:
            return ""
        model = self._ensure_model()
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return ""

        language = self._language or None
        segments, _info = model.transcribe(
            audio=audio,
            language=language,
            vad_filter=True,
            condition_on_previous_text=False,
            beam_size=5,
        )

        parts: list[str] = []
        for seg in segments:
            text = str(getattr(seg, "text", "") or "").strip()
            if text:
                parts.append(text)
        return " ".join(parts).strip()


class _STTWorker(QThread):
    """
    녹음된 PCM 데이터를 백그라운드에서 STT 처리한다.
    """

    finished_text = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, stt_service: _FasterWhisperService, pcm_bytes: bytes):
        super().__init__()
        self.stt_service = stt_service
        self.pcm_bytes = pcm_bytes

    def run(self):
        try:
            text = self.stt_service.transcribe_pcm16(self.pcm_bytes)
            self.finished_text.emit(text)
        except Exception as e:
            self.failed.emit(str(e))


class GlobalPTTController(QObject):
    """
    전역 단축키 기반 PTT 제어기.
    """

    transcription_ready = pyqtSignal(str)
    recording_started = pyqtSignal()
    notice = pyqtSignal(str, str)  # (message, level)

    _request_start_record = pyqtSignal()
    _request_stop_record = pyqtSignal()
    _MAX_RECORD_SEC = 30.0

    def __init__(self, settings_dict: dict | None = None, parent=None):
        super().__init__(parent)
        self._settings = dict(settings_dict or {})
        self._listener = None
        self._keyboard_module = None
        self._recorder = _RawAudioRecorder()
        self._stt_service = _FasterWhisperService()
        self._stt_worker: _STTWorker | None = None
        self._is_recording = False
        self._is_transcribing = False
        self._pressed_tokens: set[str] = set()
        self._pressed_lock = threading.Lock()
        self._required_modifiers: set[str] = set()
        self._trigger_key = "alt"
        self._min_record_sec = 0.25
        self._max_record_sec = self._MAX_RECORD_SEC
        self._enabled = False
        self._deps_error_notified = False
        self._effective_config = None
        self._record_timeout_timer = QTimer(self)
        self._record_timeout_timer.setSingleShot(True)
        self._record_timeout_timer.timeout.connect(self._on_record_timeout)

        self._request_start_record.connect(self._start_recording)
        self._request_stop_record.connect(self._stop_recording_and_transcribe)
        self.apply_settings(self._settings)

    def start(self):
        """
        현재 설정 기준으로 리스너를 시작한다.
        """
        self._restart_listener()

    def shutdown(self):
        """
        리소스를 정리한다.
        """
        self._record_timeout_timer.stop()
        self._stop_listener()
        self._safe_stop_recording()
        self._is_transcribing = False
        self._cleanup_stt_worker(wait_ms=5000)

    def apply_settings(self, settings_dict: dict):
        """
        설정 변경을 즉시 반영한다.
        """
        self._settings = dict(settings_dict or {})
        enabled = bool(self._settings.get("enable_global_ptt", True))
        hotkey_text = normalize_hotkey_text(
            str(self._settings.get("global_ptt_hotkey", "alt")),
            default="alt",
        )
        required_modifiers, trigger_key = hotkey_to_spec(hotkey_text, default="alt")

        model_size = str(self._settings.get("stt_model_size", "small"))
        device = str(self._settings.get("stt_device", "auto"))
        compute_type = str(self._settings.get("stt_compute_type", "int8"))
        language = str(self._settings.get("stt_language", "ko"))

        try:
            min_sec = float(self._settings.get("stt_min_record_sec", 0.25))
        except Exception:
            min_sec = 0.25
        min_record_sec = min(3.0, max(0.1, min_sec))
        try:
            max_sec_raw = float(self._settings.get("stt_max_record_sec", self._MAX_RECORD_SEC))
        except Exception:
            max_sec_raw = self._MAX_RECORD_SEC
        max_record_sec = min(self._MAX_RECORD_SEC, max(1.0, max_sec_raw))

        effective = (
            enabled,
            hotkey_text,
            tuple(sorted(required_modifiers)),
            trigger_key,
            model_size,
            device,
            compute_type,
            language,
            min_record_sec,
            max_record_sec,
        )
        if self._effective_config == effective:
            return
        self._effective_config = effective

        self._enabled = enabled
        self._required_modifiers = required_modifiers
        self._trigger_key = trigger_key
        self._min_record_sec = min_record_sec
        self._max_record_sec = max_record_sec
        self._stt_service.configure(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            language=language,
        )

        self._restart_listener()

    def _ensure_dependencies(self) -> bool:
        try:
            import pynput.keyboard as keyboard  # type: ignore
            import sounddevice as _sounddevice  # type: ignore
            import faster_whisper as _faster_whisper  # type: ignore
        except Exception as e:
            if not self._deps_error_notified:
                self._deps_error_notified = True
                self.notice.emit(
                    f"PTT 비활성화: 의존성 로드 실패 ({e})",
                    "error",
                )
            return False

        self._deps_error_notified = False
        self._keyboard_module = keyboard
        return True

    def _restart_listener(self):
        self._safe_stop_recording()
        self._stop_listener()
        if not self._enabled:
            self.notice.emit("전역 PTT가 비활성화되었습니다.", "info")
            return
        if not self._ensure_dependencies():
            return

        keyboard = self._keyboard_module
        if keyboard is None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._listener.daemon = True
        self._listener.start()
        self.notice.emit("전역 PTT 대기 중입니다.", "info")
        print(
            f"[PTT] listener started: trigger={self._trigger_key}, "
            f"required_modifiers={sorted(self._required_modifiers)}"
        )

    def _stop_listener(self):
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

        with self._pressed_lock:
            self._pressed_tokens.clear()

    def _safe_stop_recording(self):
        self._record_timeout_timer.stop()
        if not self._is_recording:
            return
        self._is_recording = False
        try:
            self._recorder.stop(silent=True)
        except Exception:
            pass

    def _cleanup_stt_worker(self, wait_ms: int = 0):
        worker = self._stt_worker
        if worker is None:
            return
        if wait_ms > 0 and worker.isRunning():
            worker.wait(wait_ms)
        if not worker.isRunning():
            worker.deleteLater()
            if self._stt_worker is worker:
                self._stt_worker = None

    def _on_key_press(self, key):
        token = _pynput_key_to_token(key)
        if not token:
            return

        with self._pressed_lock:
            already_pressed = token in self._pressed_tokens
            self._pressed_tokens.add(token)
            current_pressed = set(self._pressed_tokens)

        if already_pressed:
            return
        if self._is_recording or self._is_transcribing:
            return
        if token != self._trigger_key:
            return
        if not self._required_modifiers.issubset(current_pressed):
            return

        self._request_start_record.emit()

    def _on_key_release(self, key):
        token = _pynput_key_to_token(key)
        if not token:
            return

        with self._pressed_lock:
            self._pressed_tokens.discard(token)

        if token != self._trigger_key:
            return
        if not self._is_recording:
            return
        self._request_stop_record.emit()

    def _start_recording(self):
        if not self._enabled:
            return
        if self._is_recording or self._is_transcribing:
            return
        try:
            self._recorder.start()
            self._is_recording = True
            self._record_timeout_timer.start(int(self._max_record_sec * 1000))
            self.notice.emit("PTT 녹음을 시작했습니다.", "info")
            self.recording_started.emit()
            print("[PTT] recording started")
        except Exception as e:
            self._is_recording = False
            self._record_timeout_timer.stop()
            self.notice.emit(f"마이크 시작 실패: {e}", "error")

    def _stop_recording_and_transcribe(self):
        if not self._is_recording:
            return

        self._is_recording = False
        self._record_timeout_timer.stop()
        try:
            result = self._recorder.stop()
        except Exception as e:
            self.notice.emit(f"마이크 종료 실패: {e}", "error")
            return

        if result.duration_sec < self._min_record_sec or len(result.pcm_bytes) < 1600:
            self.notice.emit("녹음 길이가 짧아 인식을 건너뜁니다.", "info")
            return

        if self._is_transcribing:
            self.notice.emit("이전 음성 인식 처리 중입니다.", "info")
            return

        self._is_transcribing = True
        self.notice.emit("음성 인식 중...", "info")
        worker = _STTWorker(self._stt_service, result.pcm_bytes)
        self._stt_worker = worker
        worker.finished_text.connect(self._on_transcription_ready)
        worker.failed.connect(self._on_transcription_failed)
        worker.start()

    def _on_record_timeout(self):
        if not self._is_recording:
            return
        self.notice.emit("최대 녹음 시간(30초)에 도달해 자동 종료합니다.", "info")
        self._request_stop_record.emit()

    def _on_transcription_ready(self, text: str):
        self._is_transcribing = False
        self._cleanup_stt_worker()
        cleaned = str(text or "").strip()
        if not cleaned:
            self.notice.emit("음성 인식 결과가 없습니다.", "info")
            return
        print(f"[PTT] transcription: {cleaned}")
        self.transcription_ready.emit(cleaned)

    def _on_transcription_failed(self, error: str):
        self._is_transcribing = False
        self._cleanup_stt_worker()
        self.notice.emit(f"음성 인식 실패: {error}", "error")
        print(f"[PTT] transcription failed: {error}")
