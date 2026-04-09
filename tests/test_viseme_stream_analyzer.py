import math

import numpy as np

from src.ai.viseme_stream_analyzer import VisemeStreamAnalyzer


def make_pcm_bytes(sample_rate: int = 24000, duration_ms: int = 100, amplitude: float = 0.4) -> bytes:
    frame_count = int(sample_rate * duration_ms / 1000)
    t = np.arange(frame_count) / sample_rate
    samples = amplitude * np.sin(2 * math.pi * 220 * t)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    return pcm.tobytes()


def test_viseme_stream_analyzer_returns_timestamped_frames():
    analyzer = VisemeStreamAnalyzer(sample_rate=24000, channels=1, sample_width=2)
    frames = analyzer.push_pcm(make_pcm_bytes())

    assert frames
    assert hasattr(frames[0], "timestamp")
    assert hasattr(frames[0], "viseme")
    assert hasattr(frames[0], "confidence")


def test_viseme_stream_analyzer_can_signal_fallback_without_raising():
    analyzer = VisemeStreamAnalyzer(sample_rate=24000, channels=1, sample_width=2)
    analyzer._enabled = False

    assert analyzer.push_pcm(b"\x00\x00") == []
