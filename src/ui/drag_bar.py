"""
반투명 드래그 바 위젯
윈도우를 드래그하여 이동할 수 있는 바
"""
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPalette, QColor


class DragBar(QWidget):
    """반투명 드래그 바"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 드래그 상태
        self._drag_position = QPoint()
        
        # UI 설정
        self.setFixedHeight(30)
        self._setup_ui()
    
    def _setup_ui(self):
        """UI 초기화"""
        # 레이아웃
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        
        # 라벨
        label = QLabel("ENE")
        label.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(label)
        
        layout.addStretch()
        
        # 배경 색상 (반투명 검은색)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 77))  # alpha=77 (약 30%)
        self.setPalette(palette)
    
    def mousePressEvent(self, event):
        """마우스 누름 - 드래그 시작"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 현재 마우스 위치를 전역 좌표로 저장
            self._drag_position = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """마우스 이동 - 윈도우 드래그"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            # 윈도우를 새 위치로 이동
            self.window().move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
