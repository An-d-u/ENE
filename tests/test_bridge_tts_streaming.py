import json

from PyQt6.QtCore import QCoreApplication

from src.ai.tts_client import create_tts_client
from src.core.bridge import WebBridge


def _ensure_qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_bridge_tts_error_restores_pending_response():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.pending_response = ("복구할 응답", "normal")
    bridge._is_rerolling = True

    received = []
    reroll_states = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))
    bridge.reroll_state_changed.connect(lambda state: reroll_states.append(bool(state)))

    bridge._on_tts_error("mock error")

    assert received == [("복구할 응답", "normal")]
    assert bridge.pending_response is None
    assert bridge._is_rerolling is False
    assert reroll_states and reroll_states[-1] is False


def test_bridge_should_use_streaming_tts_only_when_enabled_and_supported():
    _ensure_qt_app()

    bridge = WebBridge()

    class DummyClient:
        supports_streaming = True

    bridge.tts_client = DummyClient()
    bridge.tts_streaming_enabled = True

    assert bridge._should_use_streaming_tts() is True

    bridge.tts_streaming_enabled = False
    assert bridge._should_use_streaming_tts() is False


def test_should_use_sync_buffer_returns_false_for_browser_tts():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.tts_client = create_tts_client("browser_speech", {})

    assert bridge._should_use_sync_buffer() is False


def test_streaming_path_flushes_message_only_when_playback_really_starts():
    _ensure_qt_app()

    class DummyAudioPlayer:
        def __init__(self):
            self.started = None
            self.chunks = []
            self.finished = False

        def start_stream(self, sample_rate: int, channels: int, sample_width: int):
            self.started = (sample_rate, channels, sample_width)

        def append_stream_pcm(self, pcm_data: bytes):
            self.chunks.append(pcm_data)

        def finish_stream(self):
            self.finished = True

    bridge = WebBridge()
    bridge.audio_player = DummyAudioPlayer()
    bridge.pending_response = ("실시간 응답", "happy")
    bridge.pending_token_usage_payload = json.dumps(
        {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
        ensure_ascii=False,
    )
    bridge.tts_streaming_enabled = True

    received = []
    token_payloads = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))
    bridge.token_usage_ready.connect(lambda payload: token_payloads.append(json.loads(payload)))

    bridge._on_tts_stream_format(1000, 1, 2)
    bridge._get_stream_sync_elapsed_ms = lambda: 0
    bridge._sync_controller.mark_viseme_ready_through(0.08)
    bridge._on_tts_stream_chunk(b"\x01" * 160, [0.25, 0.6])

    assert bridge.audio_player.started == (1000, 1, 2)
    assert bridge.audio_player.chunks == []
    assert received == []
    assert token_payloads == []

    bridge._get_stream_sync_elapsed_ms = lambda: 80
    bridge._on_tts_stream_chunk(b"", [])

    assert bridge.audio_player.chunks == [b"\x01" * 160]
    assert received == [("실시간 응답", "happy")]
    assert token_payloads == [{"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}]
    assert bridge.pending_response is None


def test_streaming_path_starts_with_rms_fallback_after_max_buffer_timeout():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.tts_streaming_enabled = True
    bridge.pending_response = ("지연 응답", "normal")
    bridge._on_tts_stream_format(1000, 1, 2)
    bridge._get_stream_sync_elapsed_ms = lambda: 121

    class DummyAudioPlayer:
        def __init__(self):
            self.started = None
            self.chunks = []

        def start_stream(self, sample_rate: int, channels: int, sample_width: int):
            self.started = (sample_rate, channels, sample_width)

        def append_stream_pcm(self, pcm_data: bytes):
            self.chunks.append(pcm_data)

        def finish_stream(self):
            pass

    bridge.audio_player = DummyAudioPlayer()
    bridge._on_tts_stream_chunk(b"\x02" * 140, [0.4])

    assert bridge._sync_started is True
    assert bridge._sync_using_rms_fallback is True
    assert bridge.audio_player.chunks == [b"\x02" * 140]


def test_interrupt_tts_for_ptt_resets_sync_buffer_state():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge._sync_started = True
    bridge._sync_controller.mark_started(at_ms=100)
    bridge.lip_sync_data = [(0.0, 0.5)]

    bridge.interrupt_tts_for_ptt()

    assert bridge._sync_started is False
    assert bridge.lip_sync_data is None
