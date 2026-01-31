"""
ENE - AI Desktop Partner
Live2D 기반 데스크톱 AI 어시스턴트
"""
import sys
from PyQt6.QtWidgets import QApplication
from src.core.app import ENEApplication


def main():
    """메인 진입점"""
    # Qt 애플리케이션 초기화
    app = QApplication(sys.argv)
    app.setApplicationName("ENE")
    app.setOrganizationName("ENE")
    
    # 트레이 아이콘만 있어도 앱 유지
    app.setQuitOnLastWindowClosed(False)
    
    # ENE 애플리케이션 실행
    ene_app = ENEApplication()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
