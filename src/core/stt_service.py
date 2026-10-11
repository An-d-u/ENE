"""PC PTT와 모바일 입력이 공유하는 로컬 STT 엔진."""

import os
import site
import threading
import math
from dataclasses import dataclass
import numpy as np

_CUDA_DLL_DIR_HANDLES = []
_CUDA_DLL_REGISTERED: set[str] = set()


def _prepare_windows_cuda_runtime_path():
    """
    venv/site-packages에 설치된 NVIDIA 런타임 DLL 경로를 PATH/DLL search path에 등록한다.
    """
    if os.name != "nt":
        return

    candidates: list[str] = []
    try:
        for base in site.getsitepackages():
            candidates.append(os.path.join(base, "nvidia", "cublas", "bin"))
            candidates.append(os.path.join(base, "nvidia", "cudnn", "bin"))
    except Exception as e:
        print(f"[PTT] site-packages 조회 실패: {e}")

    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidates.append(os.path.join(user_site, "nvidia", "cublas", "bin"))
            candidates.append(os.path.join(user_site, "nvidia", "cudnn", "bin"))
    except Exception as e:
        print(f"[PTT] user site-packages 조회 실패: {e}")

    for raw_path in candidates:
        path = os.path.normpath(str(raw_path or "").strip())
        if not path or path in _CUDA_DLL_REGISTERED or not os.path.isdir(path):
            continue
        _CUDA_DLL_REGISTERED.add(path)

        # 기본 PATH에도 추가해 하위 DLL 의존성 검색이 되도록 한다.
        current_path = os.environ.get("PATH", "")
        lowered_items = {p.lower() for p in current_path.split(";") if p}
        if path.lower() not in lowered_items:
            os.environ["PATH"] = f"{path};{current_path}" if current_path else path

        # Python DLL 검색 경로에도 등록한다. handle을 유지해야 유효하다.
        try:
            handle = os.add_dll_directory(path)  # type: ignore[attr-defined]
            _CUDA_DLL_DIR_HANDLES.append(handle)
        except Exception as e:
            print(f"[PTT] DLL 검색 경로 등록 실패: {path} ({e})")


_prepare_windows_cuda_runtime_path()


class _FasterWhisperService:
    """
    faster-whisper 모델 로딩/추론을 관리한다.
    """

    def __init__(self):
        # Windows에서 symlink 미지원 시 발생하는 HF 캐시 경고를 기본적으로 숨긴다.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        _prepare_windows_cuda_runtime_path()
        self._lock = threading.Lock()
        self._model = None
        self._model_size = "small"
        self._device = "auto"
        self._compute_type = "int8"
        self._language = "ko"
        self._force_cpu_runtime = False

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
                self._force_cpu_runtime = False

    @staticmethod
    def _is_cuda_runtime_error(error_text: str) -> bool:
        lowered = str(error_text or "").lower()
        markers = (
            "cublas64_12.dll",
            "cublaslt64_12.dll",
            "cudnn",
            "cublas",
            "nvcuda.dll",
            "libcudart",
            "libcublas",
            "libcudnn",
            "cudnn64",
        )
        return any(token in lowered for token in markers)

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model
            from faster_whisper import WhisperModel

            requested_device = "cpu" if self._force_cpu_runtime else self._device
            requested_compute = self._compute_type
            if requested_device == "cpu" and requested_compute in {
                "float16",
                "bfloat16",
                "int8_float16",
                "int8_bfloat16",
            }:
                requested_compute = "int8"
            print(
                f"[PTT] faster-whisper 모델 로딩: "
                f"size={self._model_size}, device={requested_device}, compute={requested_compute}"
            )
            try:
                self._model = WhisperModel(
                    self._model_size,
                    device=requested_device,
                    compute_type=requested_compute,
                )
                return self._model
            except Exception as first_error:
                # GPU(auto 포함) 경로에서 CUDA 런타임이 없으면 CPU로 1회 자동 폴백한다.
                if requested_device != "cpu" and self._is_cuda_runtime_error(str(first_error)):
                    self._force_cpu_runtime = True
                    fallback_device = "cpu"
                    fallback_compute = "int8"
                    print(
                        "[PTT] CUDA 런타임 로딩 실패로 CPU 폴백: "
                        f"device={fallback_device}, compute={fallback_compute}, error={first_error}"
                    )
                    try:
                        self._model = WhisperModel(
                            self._model_size,
                            device=fallback_device,
                            compute_type=fallback_compute,
                        )
                        return self._model
                    except Exception as fallback_error:
                        raise RuntimeError(
                            "STT 초기화 실패: GPU(CUDA)와 CPU 폴백 모두 실패했습니다. "
                            f"(원인: {fallback_error})"
                        ) from fallback_error
                raise RuntimeError(
                    "STT 초기화 실패: 모델 로딩 중 오류가 발생했습니다. "
                    f"(원인: {first_error})"
                ) from first_error

    def _run_transcribe(self, model, audio, language):
        segments, info = model.transcribe(
            audio=audio,
            language=language,
            vad_filter=True,
            condition_on_previous_text=False,
            beam_size=5,
        )
        # 실제 추론 오류는 지연 iterator 순회 중에도 발생한다. CPU 복구 경계 안에서 소비한다.
        return list(segments), info

    def _switch_to_cpu_runtime(self, reason: str):
        with self._lock:
            self._force_cpu_runtime = True
            self._model = None
        print(f"[PTT] CUDA 경로 비활성화 후 CPU 폴백 전환: {reason}")

    def transcribe_pcm16(self, pcm_bytes: bytes) -> str:
        if not pcm_bytes:
            return ""
        model = self._ensure_model()
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return ""

        language = self._language or None
        try:
            segments, _info = self._run_transcribe(model, audio, language)
        except Exception as first_error:
            # 일부 환경은 모델 생성은 성공하지만 첫 추론 시 CUDA DLL 로딩이 실패할 수 있다.
            if self._is_cuda_runtime_error(str(first_error)):
                self._switch_to_cpu_runtime(str(first_error))
                retry_model = self._ensure_model()
                try:
                    segments, _info = self._run_transcribe(retry_model, audio, language)
                except Exception as retry_error:
                    raise RuntimeError(
                        "STT 전사 실패: GPU 경로 오류 후 CPU 재시도도 실패했습니다. "
                        f"(원인: {retry_error})"
                    ) from retry_error
            else:
                raise

        parts: list[str] = []
        for seg in segments:
            text = str(getattr(seg, "text", "") or "").strip()
            if text:
                parts.append(text)
        return " ".join(parts).strip()


@dataclass(frozen=True)
class SttSettings:
    model_size: str = "small"
    device: str = "auto"
    compute_type: str = "int8"
    language: str = "ko"

    @classmethod
    def from_mapping(cls, values):
        return cls(*(str(values.get("stt_" + key, default) or default) for key, default in (
            ("model_size", "small"), ("device", "auto"), ("compute_type", "int8"), ("language", "ko"))))


def recording_limits(values):
    def bounded(key, default, low, high):
        try:
            number = float(values.get(key, default))
            if not math.isfinite(number):
                number = default
        except (TypeError, ValueError):
            number = default
        return round(min(high, max(low, number)) * 1000)
    maximum = bounded("stt_max_record_sec", 30, 1, 30)
    return min(maximum, bounded("stt_min_record_sec", .25, .1, 3)), maximum


class SttBusy(RuntimeError):
    pass


class SharedSttService:
    """설정 저장은 짧게 잠그고, 모델 변경·지연 segment 순회는 추론 잠금 안에서 끝낸다."""

    def __init__(self, engine=None):
        self._engine = engine
        self._configuration_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._settings = SttSettings()

    @property
    def busy(self):
        return self._inference_lock.locked()

    def configure(self, model_size, device, compute_type, language):
        with self._configuration_lock:
            self._settings = SttSettings(model_size, device, compute_type, language)

    def transcribe_pcm16(self, pcm_bytes, settings=None):
        if not self._inference_lock.acquire(blocking=False):
            raise SttBusy("stt_busy")
        try:
            with self._configuration_lock:
                selected = settings or self._settings
            if self._engine is None:
                self._engine = _FasterWhisperService()
            self._engine.configure(**selected.__dict__)
            # faster-whisper의 segments는 지연 iterator다. 엔진이 순회를 끝내야 잠금을 해제한다.
            return self._engine.transcribe_pcm16(pcm_bytes)
        finally:
            self._inference_lock.release()


_SHARED_STT = SharedSttService()


def shared_stt_service():
    return _SHARED_STT
