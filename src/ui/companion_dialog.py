"""PC 로컬에서만 등록·교체를 승인하는 연결 화면."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.core.companion.gateway import GatewayState
from src.core.companion.network import qr_matrix


_ERRORS = {
    "starting": "연결 서버를 시작하는 중입니다.",
    "stopping": "연결 서버를 종료하는 중입니다.",
    "listen_failed": "포트를 열지 못했습니다. 사용 중인 프로그램과 포트 설정을 확인하세요.",
    "no_address": "사용할 IPv4 주소가 없습니다. 개인 LAN 연결을 확인하세요.",
    "pairing_expired": "등록 시간이 만료되었습니다. 새 QR을 만드세요.",
    "storage_write_failed": "등록 정보를 저장하지 못했습니다. 기존 등록은 유지됩니다.",
    "storage_uncertain": "등록 저장 결과를 확인할 수 없어 연결을 차단했습니다. 서버를 다시 시작하세요.",
    "storage_invalid": "등록 파일을 읽을 수 없습니다. 원본을 보존한 채 복구가 필요합니다.",
    "shutdown_timeout": "서버 종료가 지연되고 있습니다. 새 연결은 차단되었습니다.",
    "gateway_busy": "이전 작업을 처리 중입니다. 잠시 후 다시 시도하세요.",
    "gateway_unavailable": "먼저 모바일 연결 서버를 켜세요.",
}


def _plain_label(text=""):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class CompanionDialog(QDialog):
    enabled_requested = pyqtSignal(bool, int)
    qr_requested = pyqtSignal()
    approve_requested = pyqtSignal(str, str)
    reject_requested = pyqtSignal(str)
    revoke_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ENE 모바일 연결 · 개인 LAN")
        self.setMinimumWidth(480)
        self._state = GatewayState(False, None, False, None, None)
        self._qr_id = None
        layout = QVBoxLayout(self)
        self.warning_label = _plain_label(
            "V1은 대화와 등록 토큰을 암호화하지 않고 전송합니다. 신뢰하는 개인 LAN에서만 사용하세요. 공용 네트워크·외부 공개는 지원하지 않습니다."
        )
        layout.addWidget(self.warning_label)
        row = QHBoxLayout()
        self.enable_check = QCheckBox("모바일 연결 켜기")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8765)
        self.port_spin.setAccessibleName("연결 포트")
        row.addWidget(self.enable_check)
        row.addStretch()
        row.addWidget(_plain_label("포트"))
        row.addWidget(self.port_spin)
        layout.addLayout(row)
        self.status_label = _plain_label()
        self.address_label = _plain_label()
        self.pending_label = _plain_label()
        layout.addWidget(self.status_label)
        layout.addWidget(self.address_label)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setAccessibleName("일회용 등록 QR 코드")
        layout.addWidget(self.qr_label)
        self.qr_button = QPushButton("새 등록 QR 만들기")
        layout.addWidget(self.qr_button)
        layout.addWidget(self.pending_label)
        actions = QHBoxLayout()
        self.approve_button = QPushButton("이 기기 승인")
        self.reject_button = QPushButton("거절")
        self.revoke_button = QPushButton("기기 등록 해제")
        for button in (self.approve_button, self.reject_button, self.revoke_button):
            button.setMinimumHeight(36)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.counter_label = _plain_label()
        layout.addWidget(self.counter_label)
        self.enable_check.toggled.connect(
            lambda enabled: self.enabled_requested.emit(enabled, self.port_spin.value())
        )
        self.qr_button.clicked.connect(self.qr_requested)
        self.approve_button.clicked.connect(self._approve)
        self.reject_button.clicked.connect(self._reject)
        self.revoke_button.clicked.connect(self.revoke_requested)
        self.set_state(self._state)

    def _approve(self):
        pending = self._state.pending
        if pending is not None:
            self.approve_requested.emit(pending.pairing_id, pending.connection_id)

    def _reject(self):
        if self._state.pending is not None:
            self.reject_requested.emit(self._state.pending.pairing_id)

    def show_error(self, code):
        self.status_label.setText(
            _ERRORS.get(
                code,
                "연결 작업에 실패했습니다. PC 연결 상태를 확인하고 다시 시도하세요.",
            )
        )

    def set_state(self, state):
        self._state = state
        self.enable_check.blockSignals(True)
        self.enable_check.setChecked(state.running)
        self.enable_check.blockSignals(False)
        transitioning = state.code in {"starting", "stopping", "shutdown_timeout"}
        self.enable_check.setEnabled(not transitioning)
        self.port_spin.setEnabled(not state.running and not transitioning)
        self.qr_button.setEnabled(state.running)
        self.approve_button.setEnabled(state.running and state.pending is not None)
        self.reject_button.setEnabled(state.running and state.pending is not None)
        self.revoke_button.setEnabled(state.running and state.registered)
        if state.code:
            self.show_error(state.code)
        else:
            self.status_label.setText(
                "연결 서버 실행 중 · "
                + ("기기 등록됨" if state.registered else "기기 미등록")
                if state.running
                else "모바일 연결 꺼짐"
            )
        self.pending_label.setText(
            f"승인 대기: {state.pending.device_name}\n직접 요청한 기기인지 확인하세요. 이름만으로 기기 신원을 보장하지 않습니다."
            if state.pending
            else "승인 대기 중인 기기가 없습니다."
        )
        if state.qr is None:
            self.qr_label.clear()
            self.address_label.clear()
            self._qr_id = None
        elif self._qr_id != state.qr.pairing_id:
            matrix = qr_matrix(state.qr.to_json())
            image = QImage(len(matrix), len(matrix), QImage.Format.Format_RGB32)
            for y, row in enumerate(matrix):
                for x, dark in enumerate(row):
                    image.setPixelColor(x, y, QColor("black" if dark else "white"))
            scale = max(1, min(4, 440 // len(matrix)))
            self.qr_label.setPixmap(
                QPixmap.fromImage(image).scaled(
                    len(matrix) * scale, len(matrix) * scale
                )
            )
            self.address_label.setText(
                "주소 후보: "
                + ", ".join(f"{item.host}:{item.port}" for item in state.qr.addresses)
                + "\nQR은 2분 동안 유효하며 승인 후 한 번만 사용됩니다."
            )
            self._qr_id = state.qr.pairing_id
