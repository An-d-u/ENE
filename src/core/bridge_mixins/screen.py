"""PC에서 명시적으로 선택한 창의 공유 상태를 관리한다."""
import ipaddress
import json
import sys
from urllib.parse import urlsplit
from weakref import WeakSet

from ..screen_frame import ScreenFrame, jpeg_bytes

from PyQt6.QtCore import pyqtSlot


def _remote_endpoint(client):
    try:
        host = urlsplit(str(getattr(client, "endpoint", ""))).hostname or ""
        if host.lower() == "localhost":
            return False
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


class ScreenBridgeMixin:
    def _screen_available(self):
        return sys.platform == "win32" and self._vision_available()

    def _vision_available(self):
        client = self.llm_client
        return (getattr(client, "supports_image_input", False)
                and getattr(client, "supports_screen_input", True)
                and getattr(client, "screen_model_supported", True)
                and callable(getattr(client, "send_screen_question", None))
                and callable(getattr(client, "observe_screen_once", None)))

    @pyqtSlot(result=str)
    def get_screen_share_state(self):
        session = getattr(self, "_screen_share", None)
        return json.dumps({
            "available": bool(self._screen_available()),
            "question": bool(session and session.question),
            "observe": bool(session and session.observe),
            "title": session.title if session else "",
            "model": str(getattr(self.llm_client, "model_name", "") or ""),
            "remote": _remote_endpoint(self.llm_client),
            "error": getattr(self, "_screen_error", "") or getattr(session, "error", ""),
        }, ensure_ascii=False)

    def _capture_question_frame(self):
        session = getattr(self, "_screen_share", None)
        if not session or not session.question:
            return None
        try:
            return self._screen_frame_for("question", session.snapshot())
        except (OSError, RuntimeError):
            return ScreenFrame(None, lambda: False)

    def _screen_frame_for(self, mode, image):
        session = self._screen_share
        epoch_name = mode + "_epoch"
        epoch = getattr(session, epoch_name)
        generation = session.generation
        input_epoch = getattr(self, "_ambient_input_epoch", 0)

        def authorized():
            return (session.can_send(generation) and getattr(session, epoch_name) == epoch
                    and getattr(session, mode) and (mode != "observe" or (
                        self._observation_device() == "pc" and
                        input_epoch == getattr(self, "_ambient_input_epoch", 0))))

        frame = ScreenFrame(jpeg_bytes(image), authorized)
        if not hasattr(self, "_screen_frames"):
            self._screen_frames = WeakSet()
        self._screen_frames.add(frame)
        return frame

    def _emit_screen_share_state(self):
        for frame in tuple(getattr(self, "_screen_frames", ())):
            frame.revalidate()
        session = getattr(self, "_screen_share", None)
        scene = (session.generation, session.observe_epoch) if session and session.observe else None
        if scene != getattr(self, "_observed_scene", None):
            self._observed_scene = scene
            owner = getattr(self, "_last_question_device", None)
            if owner is None or owner[0] == "pc":
                self._observation_schedule.reset_scene()
                self._invalidate_automatic_reply()
        self.screen_share_state_changed.emit(self.get_screen_share_state())
        self._publish_mobile_camera_state()

    @pyqtSlot(bool, bool)
    def configure_screen_share(self, question, observe):
        if not (question or observe):
            self.stop_screen_share()
            return
        if getattr(self, "_choosing_screen", False) or not self._screen_available():
            self._emit_screen_share_state()
            return
        self._screen_error = ""
        choice_epoch = getattr(self, "_screen_choice_epoch", 0)
        try:
            from ..screen_share import ScreenShare

            session = getattr(self, "_screen_share", None)
            if session is None:
                session = self._screen_share = ScreenShare(self)
                session.changed.connect(self._emit_screen_share_state)
            if not session.title:
                client = self.llm_client
                self._choosing_screen = True
                try:
                    chosen = session.choose(self.parent())
                    if (not chosen or client is not self.llm_client
                            or choice_epoch != getattr(self, "_screen_choice_epoch", 0)):
                        session.stop()
                        return
                finally:
                    self._choosing_screen = False
            self._sync_pc_observation_capture()
            session.set_modes(question, observe)
        except (ImportError, OSError, RuntimeError):
            self.stop_screen_share()
            self._screen_error = "capture_unavailable"
        finally:
            self._emit_screen_share_state()

    def screen_controls_disconnected(self, *_):
        """공유 표시와 종료 버튼을 잃은 페이지의 캡처 권한을 회수한다."""
        self._discard_all_screen_voice()
        self._invalidate_automatic_reply()
        self._browser_speaking = False
        self.stop_screen_share()

    @pyqtSlot()
    def stop_screen_share(self):
        self._screen_choice_epoch = getattr(self, "_screen_choice_epoch", 0) + 1
        session = getattr(self, "_screen_share", None)
        if session:
            session.stop()
        self._screen_error = ""
        self._emit_screen_share_state()
