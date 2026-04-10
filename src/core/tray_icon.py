"""
시스템 트레이 아이콘 및 메뉴
"""
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QObject, pyqtSignal
from pathlib import Path
import sys

from .i18n import tr


class TrayIcon(QObject):
    """시스템 트레이 아이콘 관리 클래스"""
    
    # 시그널 정의
    settings_requested = pyqtSignal()
    ene_profile_requested = pyqtSignal()
    calendar_requested = pyqtSignal()  # 캘린더
    toggle_drag_bar_requested = pyqtSignal()
    toggle_mouse_tracking_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    
    def __init__(
        self,
        parent=None,
        show_on_create: bool = True,
        drag_bar_visible: bool = True,
        mouse_tracking_enabled: bool = True,
    ):
        super().__init__(parent)
        self._drag_bar_visible = bool(drag_bar_visible)
        self._mouse_tracking_enabled = bool(mouse_tracking_enabled)
        
        # 아이콘 경로 설정
        if getattr(sys, 'frozen', False):
            # PyInstaller로 패키징된 경우
            base_path = Path(sys._MEIPASS)
        else:
            # 개발 모드
            base_path = Path(__file__).parent.parent.parent
        
        icon_path = base_path / "assets" / "icons" / "ene_app.ico"
        if not icon_path.exists():
            icon_path = base_path / "assets" / "icons" / "tray_icon.png"
        
        # 트레이 아이콘 생성
        self.tray_icon = QSystemTrayIcon()
        
        if icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))
        else:
            print(f"경고: 트레이 아이콘을 찾을 수 없음: {icon_path}")
        
        # 컨텍스트 메뉴 생성
        self._create_menu()

        self.retranslate_ui()

        # 트레이 아이콘 표시
        if show_on_create:
            self.tray_icon.show()
    
    def _create_menu(self):
        """우클릭 메뉴 생성"""
        menu = QMenu()
        
        # 설정 액션
        self.settings_action = QAction("", self)
        self.settings_action.triggered.connect(self.settings_requested.emit)
        menu.addAction(self.settings_action)

        # 에네 정보 액션
        self.ene_profile_action = QAction("", self)
        self.ene_profile_action.triggered.connect(self.ene_profile_requested.emit)
        menu.addAction(self.ene_profile_action)
        
        # 캘린더 액션
        self.calendar_action = QAction("", self)
        self.calendar_action.triggered.connect(self.calendar_requested.emit)
        menu.addAction(self.calendar_action)
        
        menu.addSeparator()
        
        # 드래그 바 표시/숨김 액션
        self.toggle_bar_action = QAction("", self)
        self.toggle_bar_action.triggered.connect(self.toggle_drag_bar_requested.emit)
        menu.addAction(self.toggle_bar_action)
        
        # 마우스 트래킹 ON/OFF 액션
        self.toggle_mouse_tracking_action = QAction("", self)
        self.toggle_mouse_tracking_action.triggered.connect(self.toggle_mouse_tracking_requested.emit)
        menu.addAction(self.toggle_mouse_tracking_action)
        
        menu.addSeparator()
        
        # 종료 액션
        self.quit_action = QAction("", self)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(self.quit_action)
        
        self.tray_icon.setContextMenu(menu)

    def _drag_bar_label(self) -> str:
        if self._drag_bar_visible:
            return tr("tray.drag_bar.hide")
        return tr("tray.drag_bar.show")

    def _mouse_tracking_label(self) -> str:
        if self._mouse_tracking_enabled:
            return tr("tray.mouse_tracking.disable")
        return tr("tray.mouse_tracking.enable")

    def retranslate_ui(self):
        """현재 언어 카탈로그로 트레이 UI를 다시 번역한다."""
        self.tray_icon.setToolTip(tr("tray.tooltip"))
        self.settings_action.setText(tr("tray.settings"))
        self.ene_profile_action.setText(tr("tray.ene_profile"))
        self.calendar_action.setText(tr("tray.calendar"))
        self.toggle_bar_action.setText(self._drag_bar_label())
        self.toggle_mouse_tracking_action.setText(self._mouse_tracking_label())
        self.quit_action.setText(tr("tray.quit"))
    
    def update_drag_bar_menu_text(self, is_visible: bool):
        """드래그 바 메뉴 텍스트 업데이트"""
        self._drag_bar_visible = bool(is_visible)
        self.toggle_bar_action.setText(self._drag_bar_label())
    
    def update_mouse_tracking_menu_text(self, is_enabled: bool):
        """마우스 트래킹 메뉴 텍스트 업데이트"""
        self._mouse_tracking_enabled = bool(is_enabled)
        self.toggle_mouse_tracking_action.setText(self._mouse_tracking_label())
