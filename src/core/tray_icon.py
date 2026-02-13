"""
시스템 트레이 아이콘 및 메뉴
"""
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QObject, pyqtSignal
from pathlib import Path
import sys


class TrayIcon(QObject):
    """시스템 트레이 아이콘 관리 클래스"""
    
    # 시그널 정의
    settings_requested = pyqtSignal()
    memory_requested = pyqtSignal()  # 기억 관리
    calendar_requested = pyqtSignal()  # 캘린더
    toggle_drag_bar_requested = pyqtSignal()
    toggle_mouse_tracking_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 아이콘 경로 설정
        if getattr(sys, 'frozen', False):
            # PyInstaller로 패키징된 경우
            base_path = Path(sys._MEIPASS)
        else:
            # 개발 모드
            base_path = Path(__file__).parent.parent.parent
        
        icon_path = base_path / "assets" / "icons" / "tray_icon.png"
        
        # 트레이 아이콘 생성
        self.tray_icon = QSystemTrayIcon()
        
        if icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))
        else:
            print(f"경고: 트레이 아이콘을 찾을 수 없음: {icon_path}")
        
        self.tray_icon.setToolTip("ENE - AI Desktop Partner")
        
        # 컨텍스트 메뉴 생성
        self._create_menu()
        
        # 트레이 아이콘 표시
        self.tray_icon.show()
    
    def _create_menu(self):
        """우클릭 메뉴 생성"""
        menu = QMenu()
        
        # 설정 액션
        settings_action = QAction("설정", self)
        settings_action.triggered.connect(self.settings_requested.emit)
        menu.addAction(settings_action)
        
        # 기억 관리 액션
        memory_action = QAction("기억 관리", self)
        memory_action.triggered.connect(self.memory_requested.emit)
        menu.addAction(memory_action)
        
        # 캘린더 액션
        calendar_action = QAction("📅 캘린더", self)
        calendar_action.triggered.connect(self.calendar_requested.emit)
        menu.addAction(calendar_action)
        
        menu.addSeparator()
        
        # 드래그 바 표시/숨김 액션
        self.toggle_bar_action = QAction("드래그 바 숨김", self)
        self.toggle_bar_action.triggered.connect(self.toggle_drag_bar_requested.emit)
        menu.addAction(self.toggle_bar_action)
        
        # 마우스 트래킹 ON/OFF 액션
        self.toggle_mouse_tracking_action = QAction("마우스 트래킹 비활성화", self)
        self.toggle_mouse_tracking_action.triggered.connect(self.toggle_mouse_tracking_requested.emit)
        menu.addAction(self.toggle_mouse_tracking_action)
        
        menu.addSeparator()
        
        # 종료 액션
        quit_action = QAction("종료", self)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(menu)
    
    def update_drag_bar_menu_text(self, is_visible: bool):
        """드래그 바 메뉴 텍스트 업데이트"""
        if is_visible:
            self.toggle_bar_action.setText("드래그 바 숨김")
        else:
            self.toggle_bar_action.setText("드래그 바 표시")
    
    def update_mouse_tracking_menu_text(self, is_enabled: bool):
        """마우스 트래킹 메뉴 텍스트 업데이트"""
        if is_enabled:
            self.toggle_mouse_tracking_action.setText("마우스 트래킹 비활성화")
        else:
            self.toggle_mouse_tracking_action.setText("마우스 트래킹 활성화")
