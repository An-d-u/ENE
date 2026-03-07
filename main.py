"""
ENE - AI Desktop Partner
Live2D 기반 데스크톱 AI 어시스턴트
"""
import os
import sys


def _preload_stt_runtime():
    """
    Windows에서 PyQt6 이후 faster-whisper 모델 로드 시
    프로세스가 비정상 종료되는 케이스를 피하기 위해
    STT 런타임을 먼저 로드한다.
    """
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    try:
        import faster_whisper  # type: ignore  # noqa: F401
        print("OK: STT 런타임 프리로드 완료")
    except Exception as e:
        # STT는 선택 기능이므로 실패해도 앱은 계속 실행한다.
        print(f"WARNING: STT 런타임 프리로드 실패: {e}")


# 중요: PyQt import 전에 STT 런타임을 프리로드한다.
_preload_stt_runtime()

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
