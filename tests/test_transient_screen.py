from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtGui import QImage, QColor


def test_screen_frame_expires_when_question_mode_is_restarted():
    from src.core.bridge_mixins.screen import ScreenBridgeMixin
    image = QImage(220, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("orange"))
    session = SimpleNamespace(question=True, question_epoch=3, generation=4,
                              snapshot=lambda: image, can_send=lambda generation: generation == 4)
    bridge = type("Bridge", (ScreenBridgeMixin,), {})()
    bridge._screen_share = session
    frame = bridge._capture_question_frame()
    assert frame.read().startswith(bytes.fromhex("ffd8"))
    session.question_epoch += 1
    assert frame.read() is None
    frame.close()
    assert frame.read() is None


def test_worker_uses_one_request_only_and_releases_bytes():
    from src.core.bridge_workers import AIWorker
    from src.core.screen_frame import ScreenFrame

    class Client:
        supports_image_input = True
        async def send_screen_question(self, message, frame, **kwargs):
            assert frame.read() == b"synthetic"
            return ("ok", "normal", "", [], {}, [], "", {}, [], "", None)
    frame = ScreenFrame(b"synthetic", lambda: True)
    worker = AIWorker(Client(), "demo", screen_frame=frame)
    received = Mock()
    worker.response_ready.connect(received)
    worker.run()
    received.assert_called_once()
    assert frame.read() is None


def test_capture_failure_preserves_text_turn():
    from src.core.bridge_mixins.screen import ScreenBridgeMixin

    class Bridge(ScreenBridgeMixin):
        pass

    def failed():
        raise RuntimeError("합성 캡처 오류")

    bridge = Bridge()
    bridge._screen_share = SimpleNamespace(question=True, question_epoch=2, generation=1,
        snapshot=failed, can_send=lambda generation: True)
    frame = bridge._capture_question_frame()
    assert frame is not None and frame.read() is None
