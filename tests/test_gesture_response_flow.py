import json
import subprocess
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

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


def test_gesture_playback_signal_follows_only_current_player():
    class Player(QObject):
        playback_active_changed = pyqtSignal(bool)

    _ensure_qt_app()
    bridge = WebBridge()
    states = []
    bridge.speech_playback_changed.connect(states.append)
    old, current = Player(), Player()
    bridge.set_tts(None, old)
    bridge.set_tts(None, old)
    old.playback_active_changed.emit(True)
    bridge.set_tts(None, current)
    old.playback_active_changed.emit(True)
    current.playback_active_changed.emit(True)
    current.playback_active_changed.emit(False)
    assert states == [True, False, True, False]


def test_response_gesture_pose_samples_and_audio_repeat_lifetime():
    engine = Path(__file__).resolve().parents[1] / "assets/web/runtime_gesture_engine.js"
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const engine = fs.readFileSync(process.argv[1], 'utf8');
function playback(limit) {
    let now = 16, sequence = 1, currentPeak = null;
    const timers = new Map(), peaks = [], eye = [];
    function later(callback, delay) {
        const id = ++sequence;
        timers.set(id, {callback, at: now + delay});
        return id;
    }
    function advance(until) {
        while (true) {
            const timer = [...timers].sort((a,b) => a[1].at - b[1].at)[0];
            if (!timer || timer[1].at > until) break;
            timers.delete(timer[0]);
            now = timer[1].at;
            timer[1].callback(now);
        }
        now = until;
    }
    const c = {performance:{now:()=>now}, Math:Object.assign(Object.create(Math), {random:()=>0}),
        setTimeout:later, clearTimeout:id=>timers.delete(id), requestAnimationFrame:cb=>later(cb, 16),
        cancelAnimationFrame:id=>timers.delete(id), characterCanAnimate:()=>true};
    c.window = c;
    c.eneResponseMotion = {
        echoLimit:()=>limit, echoScale:i=>limit === null ? null : [1, .9, .8][i],
        gestureClip:()=>limit === null ? null : {duration:.5, useClipDuration:true},
        gestureOffsets:()=>({angleX:10}), scaleGesture:()=>{},
    };
    c.setSyntheticGestureOffsets = offsets => {
        currentPeak = Math.max(currentPeak ?? 0, Math.abs(offsets.angleX || 0));
        if (offsets.eyeX) eye.push(offsets.eyeX);
    };
    c.clearSyntheticGestureOffsets = () => {
        if (currentPeak !== null) peaks.push(currentPeak);
        currentPeak = null;
    };
    vm.runInNewContext(engine, c);
    c.scheduleSyntheticGestureDuringSpeech('shake');
    return {c, peaks, eye, advance};
}
for (const limit of [0, 1, 2, 3]) {
    const {c, peaks, eye, advance} = playback(limit);
    c.setSyntheticGestureSpeechPlayback(true);
    advance(25000);
    assert.deepEqual(peaks, [10,10,9,8].slice(0, 1 + limit));
    assert.ok(eye.length);
}
let p = playback(3);
p.c.setSyntheticGestureSpeechPlayback(true);
p.advance(3960);
p.c.setSyntheticGestureSpeechPlayback(false);
p.advance(16000);
assert.deepEqual(p.peaks, [10]);
p = playback(3);
p.advance(18000);
assert.deepEqual(p.peaks, [10]);
p = playback(3);
p.c.setSyntheticGestureSpeechPlayback(true);
p.advance(3960);
p.c.cancelPendingResponseGesture();
p.advance(21000);
assert.deepEqual(p.peaks,[10]);
p = playback(null);
for (let i=100; i<=23000; i+=100) { p.advance(i); p.c.notifySyntheticGestureSpeechActivity(); }
assert.equal(p.peaks.length, 2);
assert.ok(Math.abs(p.peaks[1] / p.peaks[0] - .58) < .005);
"""
    result = subprocess.run(
        ["node", "-e", script, str(engine)], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
