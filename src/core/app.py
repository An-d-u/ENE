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
            self.memory_manager = None
            return
        
        try:
            api_key = api_key_file.read_text(encoding='utf-8').strip()
            
            if not api_key:
                print("WARNING: api_key.txt가 비어있습니다.")
                self.llm_client = None
                self.memory_manager = None
                return
            
            # 메모리 매니저를 먼저 초기화
            self._init_memory_manager()
            
            # 사용자 프로필 초기화
            self._init_user_profile()
            
            # LLM 클라이언트 초기화 (메모리 매니저 전달)
            self.llm_client = GeminiClient(
                api_key=api_key,
                memory_manager=self.memory_manager
            )
            print("OK: Gemini API 클라이언트 초기화 성공")
            
        except Exception as e:
            print(f"ERROR: Gemini API 클라이언트 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.llm_client = None
            self.memory_manager = None
            
        except Exception as e:
            print(f"ERROR: Gemini API 클라이언트 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.llm_client = None
            self.memory_manager = None
    
    def _init_user_profile(self):
        """사용자 프로필 초기화"""
        try:
            from src.ai.user_profile import UserProfile
            
            self.user_profile = UserProfile(profile_file="user_profile.json")
            print("OK: 사용자 프로필 초기화 성공")
            
        except Exception as e:
            print(f"ERROR: 사용자 프로필 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.user_profile = None
    
    def _init_memory_manager(self):
        """메모리 매니저 초기화"""
        from pathlib import Path
        from src.ai.memory import MemoryManager
        from src.ai.embedding import EmbeddingGenerator
        
        try:
            # Voyage AI API 키 읽기
            voyage_key_file = Path('voyage_api_key.txt')
            
            if not voyage_key_file.exists():
                print("WARNING: voyage_api_key.txt 파일이 없습니다.")
                print("장기기억 기능이 제한적으로 작동합니다 (임베딩 없음).")
                embedding_gen = None
            else:
                voyage_key = voyage_key_file.read_text(encoding='utf-8').strip()
                
                if voyage_key == "your-voyage-api-key-here" or not voyage_key:
                    print("WARNING: Voyage AI API 키를 설정해주세요.")
                    embedding_gen = None
                else:
                    embedding_gen = EmbeddingGenerator(api_key=voyage_key)
                    print("OK: Voyage AI 임베딩 생성기 초기화 성공")
            
            # 메모리 파일 경로
            memory_file = Path('memory.json')
            
            # 메모리 매니저 생성
            self.memory_manager = MemoryManager(
                memory_file=str(memory_file),
                embedding_generator=embedding_gen
            )
            
            print("OK: 메모리 매니저 초기화 성공")
            
        except Exception as e:
            print(f"ERROR: 메모리 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.memory_manager = None
    
    def _connect_signals(self):
        """시그널 연결"""
        # WebBridge에 LLM 클라이언트 및 메모리 매니저 전달
        self.overlay_window.bridge.set_llm_client(self.llm_client)
        if hasattr(self, 'memory_manager'):
            user_profile = self.user_profile if hasattr(self, 'user_profile') else None
            self.overlay_window.bridge.set_memory_manager(
                self.memory_manager,
                self.llm_client,
                user_profile
            )
        # 트레이 아이콘 시그널
        self.tray_icon.settings_requested.connect(self._show_settings_dialog)
        self.tray_icon.memory_requested.connect(self._show_memory_dialog)
        self.tray_icon.toggle_drag_bar_requested.connect(self._toggle_drag_bar)
        self.tray_icon.toggle_mouse_tracking_requested.connect(self._toggle_mouse_tracking)
        self.tray_icon.quit_requested.connect(self._quit_application)
    
    def _show_settings_dialog(self):
        """설정 다이얼로그 표시"""
        dialog = SettingsDialog(self.settings.config, self.overlay_window)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            # 설정 저장
            self.settings.config = dialog.get_settings()
            self.settings.save()
            
            # 설정 적용
            self.overlay_window.apply_settings(self.settings.config)
    
    def _show_memory_dialog(self):
        """기억 관리 다이얼로그 표시"""
        if not hasattr(self, 'memory_manager') or not self.memory_manager:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                None,
                "메모리 없음",
                "메모리 매니저가 초기화되지 않았습니다."
            )
            return
        
        from src.ui.memory_dialog import MemoryDialog
        
        # WebBridge 참조 전달
        bridge = self.overlay_window.bridge if hasattr(self.overlay_window, 'bridge') else None
        dialog = MemoryDialog(self.memory_manager, bridge)
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
        print("애플리케이션 종료 중...")
        
        # 종료 전 남은 대화 요약
        if hasattr(self, 'overlay_window') and hasattr(self.overlay_window, 'bridge'):
            bridge = self.overlay_window.bridge
            
            # 남은 대화가 있으면 요약
            if bridge.conversation_buffer:
                print(f"남은 대화 {len(bridge.conversation_buffer)}개 요약 중...")
                
                try:
                    # clear_conversation이 자동으로 남은 대화를 요약함
                    bridge.clear_conversation()
                    print("요약 완료")
                except Exception as e:
                    print(f"종료 전 요약 실패: {e}")
        
        self.overlay_window.close()
        QApplication.quit()
