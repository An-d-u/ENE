from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VisemeFrame:
    """실시간 viseme 프레임 한 건."""

    timestamp: float
    viseme: str
    confidence: float


class VisemeStreamAnalyzer:
    """PCM 청크에서 간단한 viseme 프레임을 추정한다."""

    def __init__(self, sample_rate: int, channels: int = 1, sample_width: int = 2, frame_duration_ms: int = 50):
        self.sample_rate = max(1, int(sample_rate))
        self.channels = max(1, int(channels))
        self.sample_width = max(1, int(sample_width))
        self.frame_duration_ms = max(1, int(frame_duration_ms))
        self._enabled = True
        self._pending_pcm = bytearray()
        self._next_timestamp = 0.0
        self._bytes_per_audio_frame = self.channels * self.sample_width
        self._pcm_bytes_per_window = max(
            self._bytes_per_audio_frame,
            int(self.sample_rate * self.frame_duration_ms / 1000) * self._bytes_per_audio_frame,
        )

    def push_pcm(self, pcm_data: bytes) -> list[VisemeFrame]:
        if not self._enabled:
            return []
        if pcm_data:
            self._pending_pcm.extend(pcm_data)

        frames: list[VisemeFrame] = []
        while len(self._pending_pcm) >= self._pcm_bytes_per_window:
            pcm_frame = bytes(self._pending_pcm[:self._pcm_bytes_per_window])
            del self._pending_pcm[:self._pcm_bytes_per_window]
            frames.append(self._build_frame(pcm_frame))
        return frames

    def finalize(self) -> list[VisemeFrame]:
        if not self._enabled or not self._pending_pcm:
            return []
        remaining = bytes(self._pending_pcm)
        self._pending_pcm.clear()
        return [self._build_frame(remaining)]

    def _build_frame(self, pcm_frame: bytes) -> VisemeFrame:
        if self.sample_width == 1:
            audio_array = np.frombuffer(pcm_frame, dtype=np.uint8)
            normalized = (audio_array.astype(np.float32) - 128.0) / 128.0
        elif self.sample_width == 2:
            audio_array = np.frombuffer(pcm_frame, dtype=np.int16)
            normalized = audio_array.astype(np.float32) / 32768.0
        else:
            audio_array = np.frombuffer(pcm_frame, dtype=np.int32)
            normalized = audio_array.astype(np.float32) / float(2 ** (self.sample_width * 8 - 1))

        if self.channels > 1 and len(normalized) >= self.channels:
            trimmed = len(normalized) - (len(normalized) % self.channels)
            normalized = normalized[:trimmed].reshape(-1, self.channels).mean(axis=1)

        rms = float(np.sqrt(np.mean(normalized ** 2))) if len(normalized) else 0.0
        viseme = "sil" if rms < 0.02 else "A"
        confidence = max(0.0, min(rms * 3.0, 1.0))
        timestamp = self._next_timestamp
        self._next_timestamp = round(self._next_timestamp + (self.frame_duration_ms / 1000.0), 6)
        return VisemeFrame(timestamp=timestamp, viseme=viseme, confidence=confidence)
