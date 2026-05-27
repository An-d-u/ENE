"""
ENE - AI Desktop Partner
Live2D 기반 데스크톱 AI 어시스턴트
"""
import os
import sys
from pathlib import Path


WEBENGINE_SAFE_RENDERING_FLAGS = (
    "--disable-gpu-compositing",
    "--disable-zero-copy",
    "--disable-gpu-rasterization",
    "--disable-accelerated-2d-canvas",
)


def _append_chromium_flags(existing_flags: str, required_flags: tuple[str, ...]) -> str:
    """기존 Chromium 플래그를 유지하면서 필요한 플래그만 추가한다."""
    flags = existing_flags.split()
    known_flags = set(flags)
    for flag in required_flags:
        if flag not in known_flags:
            flags.append(flag)
            known_flags.add(flag)
    return " ".join(flags)


def _configure_webengine_rendering():
    """
    투명 WebEngine 창과 WebGL 캔버스가 Windows GPU 합성에서
    검은 타일/뒤 화면 비침으로 깨지는 현상을 줄인다.
    """
    existing_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _append_chromium_flags(
        existing_flags,
        WEBENGINE_SAFE_RENDERING_FLAGS,
    )


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


# 중요: PyQt import 전에 WebEngine 렌더링 플래그와 STT 런타임을 준비한다.
_configure_webengine_rendering()
_preload_stt_runtime()

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

from src.core.app import ENEApplication


def _get_base_path() -> Path:
    """개발/패키징 환경에 맞는 기준 경로를 반환한다."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def main():
    """메인 진입점"""
    # Qt 애플리케이션 초기화
    app = QApplication(sys.argv)
    app.setApplicationName("ENE")
    app.setOrganizationName("ENE")
    base_path = _get_base_path()
    icon_path = base_path / "assets" / "icons" / "ene_app.ico"
    if not icon_path.exists():
        icon_path = base_path / "assets" / "icons" / "tray_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # 트레이 아이콘만 있어도 앱 유지
    app.setQuitOnLastWindowClosed(False)

    # ENE 애플리케이션 실행
    ene_app = ENEApplication()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
