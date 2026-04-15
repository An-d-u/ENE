import json

from PyQt6.QtCore import QCoreApplication

from src.ai.tts_client import create_tts_client
from src.ai.viseme_stream_analyzer import VisemeFrame
from src.core.bridge import WebBridge
from src.core.model_lip_sync_profile import build_model_lip_sync_profile_from_params


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


def test_bridge_builds_mouth_pose_from_rms_and_viseme():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge._model_lip_sync_profile = build_model_lip_sync_profile_from_params(
        {
            "ParamMouthOpenY",
            "ParamMouthForm",
            "ParamMouthFunnel",
            "ParamMouthPuckerWiden",
            "ParamJawOpen",
        }
    )

    pose = bridge._build_mouth_pose(rms_open=0.6, viseme="O", confidence=0.8)

    assert pose["open"] >= 0.6
    assert "funnel" in pose
    assert pose["source"] == "viseme_blend"


def test_bridge_keeps_rms_open_when_viseme_confidence_is_low():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge._model_lip_sync_profile = build_model_lip_sync_profile_from_params(
        {
            "ParamMouthOpenY",
            "ParamMouthForm",
            "ParamMouthFunnel",
            "ParamMouthPuckerWiden",
            "ParamJawOpen",
        }
    )

    pose = bridge._build_mouth_pose(rms_open=0.5, viseme="I", confidence=0.2)

    assert pose["open"] == 0.5
    assert abs(pose["form"]) < 0.2


def test_bridge_invalidates_profile_cache_when_model_path_changes(tmp_path):
    _ensure_qt_app()

    first_model_dir = tmp_path / "first"
    first_model_dir.mkdir()
    first_model_path = first_model_dir / "first.model3.json"
    first_model_path.write_text(json.dumps({"Groups": []}, ensure_ascii=False), encoding="utf-8-sig")
    first_model_path.with_suffix(".cdi3.json").write_text(
        json.dumps({"Parameters": [{"Id": "ParamMouthOpenY"}]}, ensure_ascii=False),
        encoding="utf-8-sig",
    )

    second_model_dir = tmp_path / "second"
    second_model_dir.mkdir()
    second_model_path = second_model_dir / "second.model3.json"
    second_model_path.write_text(json.dumps({"Groups": []}, ensure_ascii=False), encoding="utf-8-sig")
    second_model_path.with_suffix(".cdi3.json").write_text(
        json.dumps(
            {
                "Parameters": [
                    {"Id": "ParamMouthOpenY"},
                    {"Id": "ParamMouthForm"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    bridge = WebBridge(settings={"model_json_path": str(first_model_path)})
    old_profile = bridge._get_model_lip_sync_profile()
    bridge.settings = {"model_json_path": str(second_model_path)}

    assert bridge._get_model_lip_sync_profile() is not old_profile


def test_bridge_emits_mouth_pose_payload_with_stream_viseme_shape():
    _ensure_qt_app()

    bridge = WebBridge(settings={"viseme_lipsync_enabled": True})
    bridge._model_lip_sync_profile = build_model_lip_sync_profile_from_params(
        {
            "ParamMouthOpenY",
            "ParamMouthForm",
            "ParamMouthFunnel",
            "ParamMouthPuckerWiden",
            "ParamJawOpen",
        }
    )
    bridge._sync_controller.push_viseme_frames(
        [VisemeFrame(timestamp=0.05, viseme="U", confidence=0.9)]
    )

    emitted = []
    lip_sync_values = []
    bridge.mouth_pose_update.connect(lambda payload: emitted.append(json.loads(payload)))
    bridge.lip_sync_update.connect(lambda value: lip_sync_values.append(float(value)))

    bridge._emit_mouth_signals(0.3, timestamp_sec=0.05)

    assert emitted
    assert lip_sync_values == [0.3]
    assert emitted[-1]["open"] >= 0.3
    assert emitted[-1]["funnel"] > 0.0
    assert emitted[-1]["source"] == "viseme_blend"


def test_bridge_emits_rms_only_mouth_pose_when_viseme_lipsync_is_disabled():
    _ensure_qt_app()

    bridge = WebBridge(settings={"viseme_lipsync_enabled": False})
    bridge._model_lip_sync_profile = build_model_lip_sync_profile_from_params(
        {
            "ParamMouthOpenY",
            "ParamMouthForm",
            "ParamMouthFunnel",
            "ParamMouthPuckerWiden",
            "ParamJawOpen",
        }
    )
    bridge._sync_controller.push_viseme_frames(
        [VisemeFrame(timestamp=0.05, viseme="U", confidence=0.9)]
    )

    emitted = []
    lip_sync_values = []
    bridge.mouth_pose_update.connect(lambda payload: emitted.append(json.loads(payload)))
    bridge.lip_sync_update.connect(lambda value: lip_sync_values.append(float(value)))

    bridge._emit_mouth_signals(0.3, timestamp_sec=0.05)

    assert lip_sync_values == [0.3]
    assert emitted
    assert emitted[-1]["open"] == 0.3
    assert emitted[-1]["source"] == "rms"
    assert emitted[-1]["jaw"] == 0.0
    assert emitted[-1]["form"] == 0.0
    assert emitted[-1]["funnel"] == 0.0
    assert emitted[-1]["pucker_widen"] == 0.0
