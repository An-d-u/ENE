"""
윈도우 시스템 테마(라이트/다크) 조회와 ENE 테마 프리셋 정의.
"""
from __future__ import annotations

try:
    import winreg
except ImportError:  # pragma: no cover - 비윈도우 환경 안전 처리
    winreg = None


LIGHT_THEME_PRESET = {
    "theme_accent_color": "#0071E3",
    "settings_window_bg_color": "#EEF1F5",
    "settings_card_bg_color": "#FFFFFF",
    "settings_input_bg_color": "#F8FAFC",
    "chat_panel_bg_color": "#EEF1F5",
    "chat_input_bg_color": "#FFFFFF",
    "chat_assistant_bubble_color": "#FFFFFF",
    "chat_user_bubble_color": "#0071E3",
}

DARK_THEME_PRESET = {
    "theme_accent_color": "#60A5FA",
    "settings_window_bg_color": "#17181C",
    "settings_card_bg_color": "#202228",
    "settings_input_bg_color": "#2A2D35",
    "chat_panel_bg_color": "#17181C",
    "chat_input_bg_color": "#202228",
    "chat_assistant_bubble_color": "#262A31",
    "chat_user_bubble_color": "#2563EB",
}

THEME_PRESETS = {
    "light": LIGHT_THEME_PRESET,
    "dark": DARK_THEME_PRESET,
}

THEME_VARIANT_PRESETS = {
    "light": {
        "light_classic": {
            "title": "클린 블루",
            "description": "가장 기본이 되는 밝은 뉴트럴 테마입니다.",
            "colors": dict(LIGHT_THEME_PRESET),
        },
        "light_sand": {
            "title": "웜 샌드",
            "description": "따뜻한 회백색과 샌드 포인트로 부드럽게 정리합니다.",
            "colors": {
                "theme_accent_color": "#B86A24",
                "settings_window_bg_color": "#F2E7D8",
                "settings_card_bg_color": "#FFF8EE",
                "settings_input_bg_color": "#F8ECDD",
                "chat_panel_bg_color": "#EADCC9",
                "chat_input_bg_color": "#FFF7EC",
                "chat_assistant_bubble_color": "#FFFDF9",
                "chat_user_bubble_color": "#B86A24",
            },
        },
        "light_mint": {
            "title": "민트 스튜디오",
            "description": "조금 더 선명하고 산뜻한 민트 계열 포인트를 씁니다.",
            "colors": {
                "theme_accent_color": "#0D9A73",
                "settings_window_bg_color": "#DFF2EB",
                "settings_card_bg_color": "#F7FFFC",
                "settings_input_bg_color": "#E6F8F1",
                "chat_panel_bg_color": "#D4ECE4",
                "chat_input_bg_color": "#F6FFFB",
                "chat_assistant_bubble_color": "#F7FFFC",
                "chat_user_bubble_color": "#0D9A73",
            },
        },
    },
    "dark": {
        "dark_midnight": {
            "title": "미드나잇",
            "description": "현재 ENE 다크 분위기에 가장 가까운 기본 다크입니다.",
            "colors": {
                "theme_accent_color": "#78A6FF",
                "settings_window_bg_color": "#111724",
                "settings_card_bg_color": "#1A2232",
                "settings_input_bg_color": "#243049",
                "chat_panel_bg_color": "#111724",
                "chat_input_bg_color": "#1A2232",
                "chat_assistant_bubble_color": "#263148",
                "chat_user_bubble_color": "#3F76FF",
            },
        },
        "dark_graphite": {
            "title": "그래파이트",
            "description": "푸른 기운을 줄이고 더 무채색에 가깝게 정리합니다.",
            "colors": {
                "theme_accent_color": "#8FA0C7",
                "settings_window_bg_color": "#1A1A1C",
                "settings_card_bg_color": "#25262A",
                "settings_input_bg_color": "#303239",
                "chat_panel_bg_color": "#1A1A1C",
                "chat_input_bg_color": "#25262A",
                "chat_assistant_bubble_color": "#303239",
                "chat_user_bubble_color": "#55637D",
            },
        },
        "dark_forest": {
            "title": "딥 포레스트",
            "description": "짙은 숲색 포인트를 얹어 차분한 다크 톤으로 바꿉니다.",
            "colors": {
                "theme_accent_color": "#46C182",
                "settings_window_bg_color": "#121915",
                "settings_card_bg_color": "#1A2620",
                "settings_input_bg_color": "#24342C",
                "chat_panel_bg_color": "#121915",
                "chat_input_bg_color": "#1A2620",
                "chat_assistant_bubble_color": "#2A3B32",
                "chat_user_bubble_color": "#2FA76F",
            },
        },
    },
}


def get_windows_theme_mode() -> str:
    """
    윈도우의 앱 테마 설정을 읽어 라이트/다크 모드를 반환한다.
    읽기에 실패하면 라이트를 기본값으로 사용한다.
    """
    if winreg is None:
        return "light"

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) == 1 else "dark"
    except Exception:
        return "light"


def get_theme_preset(mode: str) -> dict:
    """
    지정한 모드의 테마 프리셋을 복사해서 반환한다.
    """
    normalized = str(mode or "").strip().lower()
    if normalized not in THEME_PRESETS:
        normalized = "light"
    return dict(THEME_PRESETS[normalized])
