import sys
import os # 경로 설정을 위해 추가
# QWebEngineView 추가 (QWebEngineWidgets가 없다면 pip install PyQt6-WebEngine 확인)
from PyQt6.QtWebEngineWidgets import QWebEngineView 
from PyQt6.QtWebEngineCore import QWebEngineSettings # 로컬 파일 접근 허용 설정용

from PyQt6.QtWidgets import (QApplication, QMainWindow, QSystemTrayIcon, 
                             QMenu, QVBoxLayout, QWidget)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction, QIcon, QColor, QPixmap

class ENEWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 1. 윈도우 설정
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool 
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 창 크기 조정 (모델이 보이도록 약간 키움)
        self.resize(350, 600)
        self.center_window()
        self.initUI()
        self.initTray()
        self.drag_pos = None

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        # 여백 제거 (중요: 여백이 있으면 흰 테두리가 보임)
        layout.setContentsMargins(0, 0, 0, 0) 

        # --- [Step 1-2 변경점: WebEngineView 추가] ---
        self.webview = QWebEngineView()
        
        # (1) 웹뷰 배경 투명화
        self.webview.page().setBackgroundColor(Qt.GlobalColor.transparent)
        
        # (2) 로컬 파일 접근 허용 (이게 없으면 로컬 json 로드 시 CORS 에러 남)
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        # (3) HTML 파일 로드
        # 현재 실행 위치 기준으로 경로 계산
        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(current_dir, "assets/web/index.html")
        
        self.webview.load(QUrl.fromLocalFile(html_path))
        
        layout.addWidget(self.webview)

    # ... (나머지 initTray, center_window, 이벤트 핸들러 등은 기존과 동일) ...
    def initTray(self):
        # (기존 코드 유지: 빨간 아이콘 코드 그대로 두세요)
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("red")) 
        icon = QIcon(pixmap)
        self.tray_icon.setIcon(icon)
        
        menu = QMenu()
        show_action = QAction("Show/Hide", self)
        show_action.triggered.connect(self.toggle_visibility)
        menu.addAction(show_action)
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def center_window(self):
        screen = QApplication.primaryScreen().geometry()
        x = screen.width() - 400
        y = screen.height() - 650
        self.move(x, y)

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ENEWindow()
    window.show()
    sys.exit(app.exec())