"""한 요청에만 빌려 주고 공유 상태가 바뀌면 폐기하는 화면 이미지."""
from threading import Lock
from datetime import datetime

SCREEN_UNAVAILABLE_HINT = "이번 요청에는 화면 이미지가 없습니다. 화면을 보았다고 가정하지 말고 사용자 메시지에 답하세요."


class ScreenFrame:
    def __init__(self, jpeg, authorized, *, source="PC 화면"):
        self._jpeg = jpeg
        self._authorized = authorized
        self._lock = Lock()
        self.missing_on_read = False
        self.source = source
        self.captured_at = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")
        self.visual_summary = ""

    def summary_note(self):
        """현재 요청에서 실제로 읽을 수 있는 화면의 검증된 설명만 반환한다."""
        if not self.visual_summary or self.read() is None:
            return ""
        return f"{self.source} · {self.captured_at}\n{self.visual_summary}"

    def read(self):
        """전송 직전에도 같은 공유 대상과 모드가 유효할 때만 JPEG를 읽는다."""
        with self._lock:
            self._discard_if_stale()
            if not self._jpeg:
                self.missing_on_read = True
            return self._jpeg

    def _discard_if_stale(self):
        if self._jpeg and not self._authorized():
            self._jpeg = None

    def revalidate(self):
        with self._lock:
            self._discard_if_stale()

    def close(self):
        with self._lock:
            self._jpeg = None
            self._authorized = None
            self.visual_summary = ""


def jpeg_bytes(image):
    if image is None or image.isNull():
        return None
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt

    if image.width() > 1280 or image.height() > 720:
        image = image.scaled(1280, 720, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "JPEG", 82):
        return None
    return bytes(data)
