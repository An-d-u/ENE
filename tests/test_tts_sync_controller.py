from src.ai.viseme_stream_analyzer import VisemeFrame
from src.core.tts_sync_controller import TTSSyncController


def test_sync_controller_starts_when_min_buffer_and_viseme_ready():
    controller = TTSSyncController(min_buffer_ms=80, max_buffer_ms=120)
    controller.push_audio(duration_ms=80, pcm_bytes=b"1234")
    controller.mark_viseme_ready_through(0.08)

    assert controller.should_start(now_ms=80) is True


def test_sync_controller_forces_start_at_max_buffer_even_without_viseme():
    controller = TTSSyncController(min_buffer_ms=80, max_buffer_ms=120)
    controller.push_audio(duration_ms=70, pcm_bytes=b"1234")

    assert controller.should_start(now_ms=121) is True
    assert controller.should_use_rms_fallback(now_ms=121) is True


def test_sync_controller_never_rewrites_past_frames():
    controller = TTSSyncController(min_buffer_ms=80, max_buffer_ms=120)
    controller.mark_started(at_ms=100)
    controller.record_played_until(0.15)
    controller.push_viseme_frames([VisemeFrame(timestamp=0.10, viseme="A", confidence=0.9)])

    assert controller.dequeue_future_visemes() == []
