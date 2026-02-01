"""
ENE 메인 애플리케이션
오버레이 윈도우와 트레이 아이콘을 관리
"""
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject

from .settings import Settings
from .overlay_window import OverlayWindow
from .tray_icon import TrayIcon
from ..ui.settings_dialog import SettingsDialog
from ..ai.llm_client import GeminiClient


class ENEApplication(QObject):
    """ENE 메인 애플리케이션 클래스"""
    
    def __init__(self):
        super().__init__()
        
        # 설정 관리자
        self.settings = Settings()
        
        # LLM 클라이언트 초기화
        self._init_llm_client()
        
        # 오버레이 윈도우 생성
        self.overlay_window = OverlayWindow(self.settings)
        self.overlay_window.set_llm_client(self.llm_client)  # LLM 클라이언트 연결
        self.overlay_window.show()
        
        # 트레이 아이콘 생성
        self.tray_icon = TrayIcon()
        
        # 시그널 연결
        self._connect_signals()
    
    def _init_llm_client(self):
        """LLM 클라이언트 초기화"""
        from pathlib import Path
        
        # API 키 파일에서 읽기
        api_key_file = Path('api_key.txt')
        
        if not api_key_file.exists():
            print("WARNING: api_key.txt 파일이 없습니다.")
            print("프로젝트 루트에 api_key.txt 파일을 생성하고 Gemini API 키를 입력해주세요.")
            self.llm_client = None
            return
        
        try:
            api_key = api_key_file.read_text(encoding='utf-8').strip()
            
            if not api_key:
                print("WARNING: api_key.txt가 비어있습니다.")
                self.llm_client = None
                return
            
            self.llm_client = GeminiClient(api_key=api_key)
            print("OK: Gemini API 클라이언트 초기화 성공")
            
        except Exception as e:
            print(f"ERROR: Gemini API 클라이언트 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.llm_client = None
    
    def _connect_signals(self):
        """시그널 연결"""
        # 트레이 아이콘 시그널
        self.tray_icon.settings_requested.connect(self._show_settings_dialog)
        self.tray_icon.toggle_drag_bar_requested.connect(self._toggle_drag_bar)
        self.tray_icon.toggle_mouse_tracking_requested.connect(self._toggle_mouse_tracking)
        self.tray_icon.quit_requested.connect(self._quit_application)
    
    def _show_settings_dialog(self):
        """설정 다이얼로그 표시"""
        dialog = SettingsDialog(self.settings.config, self.overlay_window)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.settings_preview.connect(self._on_settings_preview)  # 미리보기 시그널 연결
        dialog.exec()
    
    def _on_settings_changed(self, new_settings: dict):
        """설정 변경 시 (저장)"""
        self.overlay_window.apply_new_settings(new_settings)
    
    def _on_settings_preview(self, new_settings: dict):
        """설정 미리보기 (저장하지 않음)"""
        # 임시로 설정 적용 (저장하지 않음)
        self.overlay_window.settings.update(new_settings)
        self.overlay_window._apply_settings()
        self.overlay_window._apply_model_settings()
    
    def _toggle_drag_bar(self):
        """드래그 바 토글"""
        is_visible = self.overlay_window.toggle_drag_bar()
        self.tray_icon.update_drag_bar_menu_text(is_visible)
    
    def _toggle_mouse_tracking(self):
        """마우스 트래킹 토글"""
        is_enabled = self.overlay_window.toggle_mouse_tracking()
        self.tray_icon.update_mouse_tracking_menu_text(is_enabled)
    
    def _quit_application(self):
        """애플리케이션 종료"""
        self.overlay_window.close()
        QApplication.quit()
