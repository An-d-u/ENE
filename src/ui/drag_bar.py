"""
반투명 드래그 바 위젯
윈도우를 드래그하여 이동할 수 있는 바
"""
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt, QPoint, pyqtSignal


class DragBar(QWidget):
    """반투명 드래그 바"""
    
    # 드래그 완료 시 위치 변경 시그널 (x, y)
    position_changed = pyqtSignal(int, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DragBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        # 드래그 상태
        self._drag_position = QPoint()
        self._is_dragging = False
        
        # UI 설정
        self.setFixedHeight(30)
        self._setup_ui()
    
    def _setup_ui(self):
        """UI 초기화"""
        # 레이아웃
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        
        # 라벨
        self.label = QLabel("ENE")
        self.label.setObjectName("DragBarLabel")
        layout.addWidget(self.label)
        
        layout.addStretch()
        self.apply_theme("rgba(0, 0, 0, 0.30)", "#FFFFFF", "rgba(255, 255, 255, 0.08)")

    def apply_theme(self, background: str, text_color: str, border_color: str) -> None:
        """현재 테마에 맞춰 드래그 바 색을 적용한다."""
        self.setStyleSheet(
            f"""
            QWidget#DragBar {{
                background-color: {background};
                border-bottom: 1px solid {border_color};
            }}
            QLabel#DragBarLabel {{
                background: transparent;
                color: {text_color};
                font-weight: 700;
            }}
            """
        )
    
    def mousePressEvent(self, event):
        """마우스 누름 - 드래그 시작"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 현재 마우스 위치를 전역 좌표로 저장
            self._drag_position = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            self._is_dragging = True
            event.accept()
    
    def mouseMoveEvent(self, event):
        """마우스 이동 - 윈도우 드래그"""
        if event.buttons() == Qt.MouseButton.LeftButton and self._is_dragging:
            # 윈도우를 새 위치로 이동
            new_pos = event.globalPosition().toPoint() - self._drag_position
            self.window().move(new_pos)
            # 실시간으로 위치 시그널 발생
            self.position_changed.emit(new_pos.x(), new_pos.y())
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """마우스 놓기 - 드래그 종료"""
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            # 최종 위치 시그널 발생
            window = self.window()
            self.position_changed.emit(window.x(), window.y())
            event.accept()
