import sys
import os
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel  # 추가
from PyQt6.QtWidgets import (QApplication, QMainWindow, QSystemTrayIcon, 
                             QMenu, QVBoxLayout, QWidget, QLabel, 
                             QSlider, QFormLayout, QHBoxLayout, QPushButton) # QPushButton 추가
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QObject, pyqtSlot # QObject, pyqtSlot 추가
from PyQt6.QtGui import QAction, QIcon, QColor, QPixmap, QCloseEvent

# --- [Step 1-3] Python에서 JS로 메시지를 보내거나 받을 객체 ---
class ENEBridge(QObject):
    def __init__(self):
        super().__init__()

    # JS에서 호출할 수 있는 함수 (슬롯)
    @pyqtSlot(str)
    def modelClicked(self, message):
        print(f"JS에서 온 메시지: {message}")

# --- [설정 창] 감정 테스트 버튼 추가 ---
class SettingsWindow(QWidget):
    changed = pyqtSignal(float, int, int)
    expression_requested = pyqtSignal(str) # 감정 변경 신호 추가

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ENE Settings")
        self.resize(300, 350)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # 기존 슬라이더
        self.slider_scale = QSlider(Qt.Orientation.Horizontal); self.slider_scale.setRange(10, 150); self.slider_scale.setValue(25)
        self.slider_x = QSlider(Qt.Orientation.Horizontal); self.slider_x.setRange(-300, 300); self.slider_x.setValue(0)
        self.slider_y = QSlider(Qt.Orientation.Horizontal); self.slider_y.setRange(-300, 300); self.slider_y.setValue(0)
        
        form_layout.addRow("Scale (%)", self.slider_scale)
        form_layout.addRow("Pos X", self.slider_x)
        form_layout.addRow("Pos Y", self.slider_y)
        layout.addLayout(form_layout)

        for s in [self.slider_scale, self.slider_x, self.slider_y]:
            s.valueChanged.connect(self.emit_change)

        # 감정 테스트 버튼 레이아웃 추가
        layout.addWidget(QLabel("<b>Expression Test</b>"))
        btn_layout = QHBoxLayout()
        
        # Hiyori 모델의 기본 감정 파일명들 (예시)
        expressions = ["f01", "f02", "f03", "f04"] 
        for exp in expressions:
            btn = QPushButton(exp)
            btn.clicked.connect(lambda checked, e=exp: self.expression_requested.emit(e))
            btn_layout.addWidget(btn)
        
        layout.addLayout(btn_layout)

    def emit_change(self):
        self.changed.emit(self.slider_scale.value()/100.0, self.slider_x.value(), self.slider_y.value())

    def closeEvent(self, event):
        event.ignore(); self.hide()

# --- [메인 윈도우] ---
class ENEWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(400, 700)
        self.center_window()

        # 브릿지 및 채널 설정
        self.bridge = ENEBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("pyBridge", self.bridge)

        self.initUI()
        self.initTray()
        
        self.settings_window = SettingsWindow()
        self.settings_window.changed.connect(self.update_model_transform)
        # 감정 버튼 클릭 시 JS 호출 연결
        self.settings_window.expression_requested.connect(self.change_emotion)

    def initUI(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        self.drag_bar = DraggableBar(self)
        layout.addWidget(self.drag_bar)

        self.webview = QWebEngineView()
        self.webview.page().setBackgroundColor(Qt.GlobalColor.transparent)
        
        # 브릿지 채널을 웹페이지에 주입
        self.webview.page().setWebChannel(self.channel)

        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(current_dir, "assets/web/index.html")
        self.webview.load(QUrl.fromLocalFile(html_path))
        
        layout.addWidget(self.webview)
        self.setCentralWidget(central)

    def change_emotion(self, exp_name):
        """Python에서 JS의 감정 변경 함수를 실행"""
        self.webview.page().runJavaScript(f"window.changeExpression('{exp_name}');")

    def update_model_transform(self, scale, x, y):
        self.webview.page().runJavaScript(f"window.updateModelTransform({scale}, {x}, {y});")

    # (이하 Tray 및 이동 로직은 이전과 동일)
    def initTray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(64, 64); pixmap.fill(QColor("red"))
        self.tray_icon.setIcon(QIcon(pixmap))
        menu = QMenu()
        menu.addAction("Open Settings", self.open_settings)
        self.toggle_bar_action = QAction("Hide Drag Bar", self)
        self.toggle_bar_action.triggered.connect(self.toggle_drag_bar)
        menu.addAction(self.toggle_bar_action)
        menu.addSeparator()
        menu.addAction("Exit", QApplication.instance().quit)
        self.tray_icon.setContextMenu(menu); self.tray_icon.show()

    def open_settings(self):
        g = self.geometry(); self.settings_window.move(g.x() + g.width() + 10, g.y()); self.settings_window.show()

    def toggle_drag_bar(self):
        if self.drag_bar.isVisible():
            self.drag_bar.hide(); self.toggle_bar_action.setText("Show Drag Bar")
        else:
            self.drag_bar.show(); self.toggle_bar_action.setText("Hide Drag Bar")

    def center_window(self):
        s = QApplication.primaryScreen().geometry(); self.move(s.width()-500, s.height()-800)

class DraggableBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent); self.parent_window = parent; self.setFixedHeight(30)
        self.setStyleSheet("background-color: rgba(0,0,0,100); border-top-left-radius: 10px; border-top-right-radius: 10px;")
        layout = QHBoxLayout(self); layout.setContentsMargins(10,0,0,0)
        layout.addWidget(QLabel("ENE :: Drag Here", styleSheet="color: white; font-weight: bold;"))
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self.drag_pos = e.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton: self.parent_window.move(e.globalPosition().toPoint() - self.drag_pos)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ENEWindow()
    window.show()
    sys.exit(app.exec())