import json

from PyQt6.QtCore import QCoreApplication

from src.ai.response_parser import parse_llm_response
from src.core.bridge import WebBridge
from src.core.bridge_workers import AIWorker


def _ensure_qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_parse_response_extracts_optional_gesture_tag_without_visible_leak():
    parsed = parse_llm_response(
        "좋아, 천천히 같이 해보자. [smile] [gesture:nod]\n[tts]\n좋아, 천천히 같이 해보자.\n[/tts]",
        available_emotions={"smile"},
    )

    text, emotion, tts_text, _events, _analysis, _promises, _thought, _goal, _proactive, gesture, _mood = parsed

    assert text == "좋아, 천천히 같이 해보자."
    assert emotion == "smile"
    assert tts_text == "좋아, 천천히 같이 해보자."
    assert gesture == "nod"
    assert "gesture:" not in text
    assert "gesture:" not in tts_text


def test_parse_response_strips_unknown_gesture_tag_without_requesting_gesture():
    parsed = parse_llm_response("괜찮아요. [normal] [gesture:moonwalk]", available_emotions={"normal"})

    text, _emotion, _tts, *_rest, gesture, _mood = parsed

    assert text == "괜찮아요."
    assert gesture == ""


def test_ai_worker_normalize_response_payload_adds_empty_gesture_for_legacy_payload():
    worker = AIWorker.__new__(AIWorker)

    normalized = AIWorker._normalize_response_payload(
        worker,
        (
            "본문",
            "smile",
            "",
            [],
            {"user_intent": "synthetic"},
            [{"title": "대화 약속"}],
            "속마음",
            {"action": "none"},
            [{"title": "가벼운 확인"}],
        ),
    )

    assert normalized == (
        "본문",
        "smile",
        "",
        [],
        {"user_intent": "synthetic"},
        [{"title": "대화 약속"}],
        "속마음",
        {"action": "none"},
        [{"title": "가벼운 확인"}],
        "",
        None,
    )


def test_bridge_emits_gesture_with_immediate_response():
    _ensure_qt_app()

    bridge = WebBridge(settings={"enable_tts": False})
    received = []
    gestures = []
    bridge.message_received.connect(lambda text, emotion, thought: received.append((text, emotion, thought)))
    bridge.gesture_requested.connect(lambda gesture: gestures.append(gesture))

    bridge._on_response_ready("좋아.", "smile", "", [], "", "", [], "", "", [], "nod")

    assert received == [("좋아.", "smile", "")]
    assert gestures == ["nod"]


def test_bridge_suppresses_gesture_when_setting_is_disabled():
    _ensure_qt_app()

    bridge = WebBridge(settings={"enable_tts": False, "enable_synthetic_gestures": False})
    gestures = []
    bridge.gesture_requested.connect(lambda gesture: gestures.append(gesture))

    bridge._on_response_ready("좋아.", "smile", "", [], "", "", [], "", "", [], "nod")

    assert gestures == []


def test_bridge_flushes_pending_gesture_when_tts_response_becomes_visible():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.pending_response = ("실시간 응답", "happy", "곧 보여줄 생각", "tilt")
    bridge.pending_token_usage_payload = json.dumps(
        {"input_tokens": 2, "output_tokens": 4, "total_tokens": 6},
        ensure_ascii=False,
    )

    received = []
    gestures = []
    token_payloads = []
    bridge.message_received.connect(lambda text, emotion, thought: received.append((text, emotion, thought)))
    bridge.gesture_requested.connect(lambda gesture: gestures.append(gesture))
    bridge.token_usage_ready.connect(lambda payload: token_payloads.append(json.loads(payload)))

    bridge._flush_pending_response_if_any()

    assert received == [("실시간 응답", "happy", "곧 보여줄 생각")]
    assert gestures == ["tilt"]
    assert token_payloads == [{"input_tokens": 2, "output_tokens": 4, "total_tokens": 6}]
    assert bridge.pending_response is None
