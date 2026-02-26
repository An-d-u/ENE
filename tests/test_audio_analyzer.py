import math
import wave

import numpy as np
import pytest

from src.ai.audio_analyzer import AudioAnalyzer


def _write_wav_mono_16bit(path, samples: np.ndarray, sample_rate: int = 16000):
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def test_analyze_raises_for_missing_file(tmp_path):
    analyzer = AudioAnalyzer(frame_duration_ms=50)
    with pytest.raises(FileNotFoundError):
        analyzer.analyze(str(tmp_path / "missing.wav"))


def test_analyze_generates_lipsync_data_in_valid_range(tmp_path):
    sample_rate = 16000
    duration_sec = 1.0
    t = np.arange(int(sample_rate * duration_sec)) / sample_rate
    samples = 0.3 * np.sin(2 * math.pi * 440 * t)

    wav_path = tmp_path / "tone.wav"
    _write_wav_mono_16bit(wav_path, samples, sample_rate=sample_rate)

    analyzer = AudioAnalyzer(frame_duration_ms=50)
    data = analyzer.analyze(str(wav_path))

    assert len(data) > 0
    timestamps = [ts for ts, _ in data]
    values = [v for _, v in data]
    assert timestamps == sorted(timestamps)
    assert all(0.0 <= v <= 1.0 for v in values)


def test_smooth_data_returns_original_when_shorter_than_window():
    analyzer = AudioAnalyzer(frame_duration_ms=50)
    data = [(0.0, 0.1), (0.05, 0.2)]
    assert analyzer._smooth_data(data, window_size=3) == data
