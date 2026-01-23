import sys
import os
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWidgets import (QApplication, QMainWindow, QSystemTrayIcon, 
                             QMenu, QVBoxLayout, QWidget, QLabel, 
                             QSlider, QFormLayout, QHBoxLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QAction, QIcon, QColor, QPixmap, QCloseEvent

# --- [1] 드래그 이동을 위한 상단 바 위젯 ---
class DraggableBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(30)
        self.setStyleSheet("""
            background-color: rgba(0, 0, 0, 100);
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        self.label = QLabel("ENE :: Drag Here")
        self.label.setStyleSheet("color: rgba(255, 255, 255, 150); font-weight: bold;")
        layout.addWidget(self.label)
        
        self.drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None


# --- [2] 모델 위치/크기 조절 설정 창 ---
class SettingsWindow(QWidget):
    changed = pyqtSignal(float, int, int) # scale, x, y

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Model Settings")
        self.resize(300, 200)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        layout = QFormLayout(self)

        # 슬라이더 설정 (기존과 동일)
        self.slider_scale = QSlider(Qt.Orientation.Horizontal)
        self.slider_scale.setRange(10, 150)
        self.slider_scale.setValue(25)
        self.slider_scale.valueChanged.connect(self.emit_change)
        layout.addRow("Scale (%)", self.slider_scale)

        self.slider_x = QSlider(Qt.Orientation.Horizontal)
        self.slider_x.setRange(-300, 300)
        self.slider_x.setValue(0)
        self.slider_x.valueChanged.connect(self.emit_change)
        layout.addRow("Position X", self.slider_x)

        self.slider_y = QSlider(Qt.Orientation.Horizontal)
        self.slider_y.setRange(-300, 300)
        self.slider_y.setValue(0)
        self.slider_y.valueChanged.connect(self.emit_change)
        layout.addRow("Position Y", self.slider_y)

    def emit_change(self):
        scale = self.slider_scale.value() / 100.0
        x = self.slider_x.value()
        y = self.slider_y.value()
        self.changed.emit(scale, x, y)

    # [수정됨] 창 닫기 이벤트(X버튼) 오버라이드
    # 프로그램을 끄지 않고 창만 숨김 처리
    def closeEvent(self, event: QCloseEvent):
        event.ignore()  # 닫기 이벤트를 무시하고
        self.hide()     # 숨기기만 함


# --- [3] 메인 어플리케이션 ---
class ENEWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(400, 700)
        self.center_window()

        self.initUI()
        self.initTray()
        
        self.settings_window = SettingsWindow()
        self.settings_window.changed.connect(self.update_model_transform)

    def initUI(self):
        central_widget = QWidget()
        central_widget.setStyleSheet("background-color: transparent;")
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 드래그 바
        self.drag_bar = DraggableBar(self)
        layout.addWidget(self.drag_bar)

        # 웹뷰
        self.webview = QWebEngineView()
        self.webview.page().setBackgroundColor(Qt.GlobalColor.transparent)
        
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(current_dir, "assets/web/index.html")
        self.webview.load(QUrl.fromLocalFile(html_path))
        
        layout.addWidget(self.webview)

    def initTray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("red"))
        self.tray_icon.setIcon(QIcon(pixmap))
        
        menu = QMenu()
        
        # 1. 설정창 열기
        settings_action = QAction("Open Settings", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        # 2. [수정됨] 드래그 바 토글 메뉴 추가
        self.toggle_bar_action = QAction("Hide Drag Bar", self)
        self.toggle_bar_action.triggered.connect(self.toggle_drag_bar)
        menu.addAction(self.toggle_bar_action)
        
        menu.addSeparator()
        
        # 3. 전체 종료
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def open_settings(self):
        geom = self.geometry()
        self.settings_window.move(geom.x() + geom.width() + 10, geom.y())
        self.settings_window.show()

    def toggle_drag_bar(self):
        """드래그 바를 보이거나 숨깁니다."""
        if self.drag_bar.isVisible():
            self.drag_bar.hide()
            self.toggle_bar_action.setText("Show Drag Bar")
        else:
            self.drag_bar.show()
            self.toggle_bar_action.setText("Hide Drag Bar")

    def update_model_transform(self, scale, x, y):
        js_code = f"window.updateModelTransform({scale}, {x}, {y});"
        self.webview.page().runJavaScript(js_code)

    def center_window(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 500, screen.height() - 800)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ENEWindow()
    window.show()
    sys.exit(app.exec())