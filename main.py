import sys
import os
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWidgets import (QApplication, QMainWindow, QSystemTrayIcon, QMenu, 
                             QVBoxLayout, QWidget, QSlider, QLabel, QHBoxLayout)
from PyQt6.QtCore import Qt, QUrl, QObject, pyqtSignal, pyqtSlot, QEvent
from PyQt6.QtGui import QAction, QIcon, QColor, QPixmap

# 1. 통신 브릿지 (Python -> JS)
class Bridge(QObject):
    # JS로 보낼 신호 정의 (float 3개: x, y, scale)
    update_transform_signal = pyqtSignal(float, float, float)

    @pyqtSlot(str)
    def log(self, msg):
        print(f"[JS] {msg}")

# 2. 컨트롤 패널 (슬라이더 창)
class ControlPanel(QWidget):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setWindowTitle("ENE Settings")
        self.resize(300, 200)
        self.initUI()
        
    def initUI(self):
        layout = QVBoxLayout()
        
        # X축 슬라이더
        layout.addWidget(QLabel("Position X"))
        self.slider_x = QSlider(Qt.Orientation.Horizontal)
        self.slider_x.setRange(-500, 500)
        self.slider_x.setValue(0)
        self.slider_x.valueChanged.connect(self.update_model)
        layout.addWidget(self.slider_x)
        
        # Y축 슬라이더
        layout.addWidget(QLabel("Position Y"))
        self.slider_y = QSlider(Qt.Orientation.Horizontal)
        self.slider_y.setRange(-500, 500)
        self.slider_y.setValue(50)
        self.slider_y.valueChanged.connect(self.update_model)
        layout.addWidget(self.slider_y)
        
        # 크기(Scale) 슬라이더
        layout.addWidget(QLabel("Scale (Size)"))
        self.slider_scale = QSlider(Qt.Orientation.Horizontal)
        self.slider_scale.setRange(1, 200) # 0.01 ~ 2.0
        self.slider_scale.setValue(25)     # 기본값 0.25
        self.slider_scale.valueChanged.connect(self.update_model)
        layout.addWidget(self.slider_scale)
        
        self.setLayout(layout)

    def update_model(self):
        # 슬라이더 값을 읽어서 JS로 전송
        x = float(self.slider_x.value())
        y = float(self.slider_y.value())
        scale = float(self.slider_scale.value()) / 100.0
        
        # Signal 발생 -> JS가 수신
        self.bridge.update_transform_signal.emit(x, y, scale)

# 3. 메인 아바타 윈도우
class ENEWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 통신 객체 생성
        self.bridge = Bridge()
        
        # 컨트롤 패널 생성
        self.control_panel = ControlPanel(self.bridge)
        self.control_panel.show() # 시작할 때 설정창 같이 띄우기

        # 윈도우 설정
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(400, 600)
        self.center_window()
        
        self.initUI()
        self.initTray()
        
        # 드래그 이동 변수
        self.drag_pos = None

    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.webview = QWebEngineView()
        self.webview.page().setBackgroundColor(Qt.GlobalColor.transparent)
        
        # [드래그 문제 해결] WebEngine의 이벤트 필터 설치
        # WebEngine 내부의 자식 위젯들이 마우스 이벤트를 가져가므로, 그 자식들에게 필터를 걸어야 함
        for child in self.webview.findChildren(QWidget): # 내부 렌더링 위젯 찾기
            child.installEventFilter(self)

        # WebChannel 설정 (JS <-> Python 연결)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.webview.page().setWebChannel(self.channel)

        # 설정 및 로드
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(current_dir, "assets/web/index.html")
        self.webview.load(QUrl.fromLocalFile(html_path))
        
        layout.addWidget(self.webview)

    # [드래그 문제 해결] 이벤트 필터 로직
    def eventFilter(self, source, event):
        # WebEngine 내부 위젯에서 마우스 클릭이 발생했을 때 가로챔
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return False # WebEngine도 클릭을 알아야 하므로 True로 막지 않음 (캐릭터 클릭 위해)
                
        elif event.type() == QEvent.Type.MouseMove:
            if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
                self.move(event.globalPosition().toPoint() - self.drag_pos)
                return True # 이동 중에는 웹페이지 드래그(텍스트 선택 등) 방지
                
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self.drag_pos = None
            
        return super().eventFilter(source, event)

    def initTray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("red"))
        self.tray_icon.setIcon(QIcon(pixmap))
        
        menu = QMenu()
        
        # 설정창 열기 메뉴 추가
        setting_action = QAction("Open Settings", self)
        setting_action.triggered.connect(self.control_panel.show)
        menu.addAction(setting_action)
        
        menu.addAction(QAction("Exit", self, triggered=QApplication.instance().quit))
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def center_window(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 450, screen.height() - 650)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ENEWindow()
    window.show()
    sys.exit(app.exec())