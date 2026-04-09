from __future__ import annotations

from src.ai.viseme_stream_analyzer import VisemeFrame


class TTSSyncController:
    """TTS 시작 게이트와 viseme 적용 시점을 관리한다."""

    def __init__(self, min_buffer_ms: int = 80, max_buffer_ms: int = 120):
        self.min_buffer_ms = max(0, int(min_buffer_ms))
        self.max_buffer_ms = max(self.min_buffer_ms, int(max_buffer_ms))
        self.buffered_audio_ms = 0
        self.started = False
        self.started_at_ms: int | None = None
        self.viseme_ready_through = 0.0
        self.played_until = 0.0
        self._future_visemes: list[VisemeFrame] = []

    def push_audio(self, duration_ms: int, pcm_bytes: bytes) -> None:
        if pcm_bytes:
            self.buffered_audio_ms += max(0, int(duration_ms))

    def mark_viseme_ready_through(self, timestamp_sec: float) -> None:
        self.viseme_ready_through = max(self.viseme_ready_through, float(timestamp_sec))

    def should_start(self, now_ms: int) -> bool:
        if self.started:
            return False
        if (
            int(now_ms) >= self.min_buffer_ms
            and self.buffered_audio_ms >= self.min_buffer_ms
            and self.viseme_ready_through >= (self.min_buffer_ms / 1000.0)
        ):
            return True
        return int(now_ms) >= self.max_buffer_ms

    def should_use_rms_fallback(self, now_ms: int) -> bool:
        return int(now_ms) >= self.max_buffer_ms and self.viseme_ready_through < (self.min_buffer_ms / 1000.0)

    def mark_started(self, at_ms: int) -> None:
        self.started = True
        self.started_at_ms = int(at_ms)

    def record_played_until(self, timestamp_sec: float) -> None:
        self.played_until = max(self.played_until, float(timestamp_sec))

    def push_viseme_frames(self, frames: list[VisemeFrame]) -> None:
        for frame in frames:
            if float(frame.timestamp) > self.played_until:
                self._future_visemes.append(frame)

    def dequeue_future_visemes(self) -> list[VisemeFrame]:
        frames = list(self._future_visemes)
        self._future_visemes.clear()
        return frames
