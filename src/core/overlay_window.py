"""
투명 오버레이 윈도우
Live2D 모델을 표시하는 프레임리스 투명 윈도우
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebChannel import QWebChannel
from pathlib import Path
import sys

from ..ui.drag_bar import DragBar
from .bridge import WebBridge


class OverlayWindow(QWidget):
    """투명 배경의 Live2D 오버레이 윈도우"""
    
    def __init__(self, settings_manager):
        super().__init__()
        
        self.settings = settings_manager
        
        # 윈도우 플래그 설정
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |  # 프레임 제거
            Qt.WindowType.WindowStaysOnTopHint |  # 항상 위
            Qt.WindowType.Tool  # 작업 표시줄에 표시 안 함
        )
        
        # 배경 투명화
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Python-JS 브릿지 생성 (settings 전달)
        self.bridge = WebBridge(settings=self.settings, parent=self)
        
        # UI 설정
        self._setup_ui()
        
        # QWebChannel 설정
        self._setup_webchannel()
        
        # 설정 적용
        self._apply_settings()
        
        # 마우스 트래킹 설정
        self._setup_mouse_tracking()
    
    def _setup_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 웹뷰 (전체 창 사용)
        self.web_view = QWebEngineView(self)
        
        # 웹뷰 배경 투명화
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.web_view.setStyleSheet("background: transparent;")
        
        # 페이지 배경색을 투명하게 설정 (중요!)
        from PyQt6.QtGui import QColor
        page = self.web_view.page()
        page.setBackgroundColor(QColor(0, 0, 0, 0))  # 완전 투명
        
        # 페이지 설정
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        self.web_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        self.web_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        
        # 페이지 로드 완료 후 배경 투명화 스크립트 실행
        self.web_view.loadFinished.connect(self._on_page_loaded)
        
        # HTML 파일 로드
        html_path = self._get_html_path()
        if html_path.exists():
            self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            print(f"경고: HTML 파일을 찾을 수 없음: {html_path}")
        
        layout.addWidget(self.web_view)
        
        # 드래그 바 (absolute positioning - 웹뷰 위에 배치)
        self.drag_bar = DragBar(self)
        self.drag_bar.move(0, 0)
        self.drag_bar.resize(self.width(), 30)
        # 최상위로 올리기
        self.drag_bar.raise_()
        # 마우스 이벤트가 제대로 전달되도록 설정
        self.drag_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
    
    def _on_page_loaded(self, ok):
        """페이지 로드 완료 시 호출"""
        if ok:
            # 페이지 배경을 투명하게 설정
            self.web_view.page().runJavaScript("""
                document.body.style.backgroundColor = 'transparent';
                document.documentElement.style.backgroundColor = 'transparent';
            """)
            
            # 모델 설정 적용
            self._apply_model_settings()
            
            print("웹 페이지 로드 완료")
        else:
            print("경고: 웹 페이지 로드 실패")
    
    def _apply_model_settings(self):
        """모델 위치 및 스케일 적용"""
        scale = self.settings.get('model_scale', 1.0)
        x_percent = self.settings.get('model_x_percent', 50)
        y_percent = self.settings.get('model_y_percent', 50)
        
        # JavaScript로 모델 조정
        js_code = f"""
        (function() {{
            // Live2D 모델이 로드될 때까지 대기
            function applyModelSettings() {{
                const model = window.live2dModel;
                if (model) {{
                    // 모델 스케일 적용
                    model.scale.set({scale});
                    
                    // 모델 위치 적용 (퍼센트 기반)
                    const canvasWidth = window.innerWidth;
                    const canvasHeight = window.innerHeight;
                    model.x = canvasWidth * {x_percent / 100};
                    model.y = canvasHeight * {y_percent / 100};
                    
                    console.log('Model settings applied: scale=' + {scale} + ', x=' + {x_percent}+ '%, y=' + {y_percent} + '%');
                }} else {{
                    // 모델이 아직 없으면 100ms 후 재시도
                    setTimeout(applyModelSettings, 100);
                }}
            }}
            applyModelSettings();
        }})();
        """
        
        self.web_view.page().runJavaScript(js_code)
    
    def _get_html_path(self) -> Path:
        """HTML 파일 경로 가져오기"""
        if getattr(sys, 'frozen', False):
            # PyInstaller로 패키징된 경우
            base_path = Path(sys._MEIPASS)
        else:
            # 개발 모드
            base_path = Path(__file__).parent.parent.parent
        
        return base_path / "assets" / "web" / "index.html"
    
    def _apply_settings(self):
        """설정 적용"""
        # 위치
        x = self.settings.get('window_x', 100)
        y = self.settings.get('window_y', 100)
        self.move(x, y)
        
        # 크기
        width = self.settings.get('window_width', 400)
        height = self.settings.get('window_height', 600)
        self.resize(width, height)
        
        # 줌 레벨
        zoom = self.settings.get('zoom_level', 1.0)
        self.web_view.setZoomFactor(zoom)
        
        # 드래그 바 표시 여부
        show_bar = self.settings.get('show_drag_bar', True)
        self.drag_bar.setVisible(show_bar)
    
    def apply_new_settings(self, new_settings: dict):
        """새 설정 적용"""
        # 마우스 트래킹 설정 변경 확인
        old_tracking = self.settings.get('mouse_tracking_enabled', True)
        new_tracking = new_settings.get('mouse_tracking_enabled', True)
        
        self.settings.update(new_settings)
        self._apply_settings()
        self._apply_model_settings()  # 모델 설정도 적용
        
        # 마우스 트래킹 설정이 변경된 경우
        if old_tracking != new_tracking:
            if new_tracking:
                self.mouse_tracking_timer.start()
                self.web_view.page().runJavaScript("window.setMouseTrackingEnabled(true);")
            else:
                self.mouse_tracking_timer.stop()
                self.web_view.page().runJavaScript("window.setMouseTrackingEnabled(false);")
        
        self.settings.save()
    
    def toggle_drag_bar(self):
        """드래그 바 표시/숨김 토글"""
        current = self.drag_bar.isVisible()
        self.drag_bar.setVisible(not current)
        self.settings.set('show_drag_bar', not current)
        self.settings.save()
        return not current
    
    def resizeEvent(self, event):
        """창 크기 변경 시 드래그 바 너비 조정"""
        super().resizeEvent(event)
        # 드래그 바 너비를 창 너비에 맞춤
        self.drag_bar.resize(self.width(), 30)
    
    def closeEvent(self, event):
        """창 닫기 이벤트 - 현재 위치/크기 저장"""
        self.settings.set('window_x', self.x())
        self.settings.set('window_y', self.y())
        self.settings.set('window_width', self.width())
        self.settings.set('window_height', self.height())
        self.settings.save()
        
        event.accept()
    
    def _setup_mouse_tracking(self):
        """마우스 트래킹 초기화"""
        from PyQt6.QtCore import QTimer
        
        # 마우스 트래킹 타이머 (30 FPS = 약 33ms마다 업데이트)
        self.mouse_tracking_timer = QTimer(self)
        self.mouse_tracking_timer.setInterval(33)  # 33ms
        self.mouse_tracking_timer.timeout.connect(self._update_mouse_position)
        
        # 설정에서 마우스 트래킹 활성화 여부 확인
        if self.settings.get('mouse_tracking_enabled', True):
            self.mouse_tracking_timer.start()
    
    def _update_mouse_position(self):
        """전역 마우스 위치를 JavaScript로 전달"""
        from PyQt6.QtGui import QCursor
        
        # 전역 마우스 위치 가져오기
        global_pos = QCursor.pos()
        
        # 윈도우 기준 상대 좌표로 변환
        local_pos = self.mapFromGlobal(global_pos)
        
        # JavaScript로 마우스 위치 전달
        js_code = f"window.updateMousePosition({local_pos.x()}, {local_pos.y()});"
        self.web_view.page().runJavaScript(js_code)
    
    def _setup_webchannel(self):
        """QWebChannel 설정"""
        # WebChannel 생성
        self.channel = QWebChannel()
        
        # 브릿지 등록
        self.channel.registerObject('bridge', self.bridge)
        
        # WebEngineView의 페이지에 채널 설정
        self.web_view.page().setWebChannel(self.channel)
        
        print("QWebChannel initialized")
    
    def set_llm_client(self, llm_client):
        """LLM 클라이언트 설정"""
        self.bridge.set_llm_client(llm_client)
    
    def toggle_mouse_tracking(self):
        """마우스 트래킹 ON/OFF"""
        if self.mouse_tracking_timer.isActive():
            self.mouse_tracking_timer.stop()
            self.settings.set('mouse_tracking_enabled', False)
            # JavaScript에서도 비활성화
            self.web_view.page().runJavaScript("window.setMouseTrackingEnabled(false);")
            return False
        else:
            self.mouse_tracking_timer.start()
            self.settings.set('mouse_tracking_enabled', True)
            # JavaScript에서도 활성화
            self.web_view.page().runJavaScript("window.setMouseTrackingEnabled(true);")
            return True
