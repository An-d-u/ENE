"""
테마 설정 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.system_theme import THEME_PRESETS, THEME_VARIANT_PRESETS


def build_theme_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    overview_group = QGroupBox("테마 개요")
    self._bind_group_title(overview_group, "settings.theme.overview.title", "테마 개요")
    overview_layout = QVBoxLayout(overview_group)
    overview_layout.setSpacing(12)
    overview_layout.addWidget(
        self._build_hint_label(
            "설정창과 채팅창은 같은 테마 모드로 움직입니다. 위에서 라이트 또는 다크를 고르고, 필요하면 아래에서 세부 색만 조정할 수 있습니다.",
            key="settings.theme.overview.hint",
        )
    )

    preview_row = QHBoxLayout()
    preview_row.setSpacing(12)
    preview_row.addWidget(
        self._build_theme_mode_preview(
            "light",
            self._resolve_theme_bundle_text(THEME_PRESETS["light"], "title"),
            self._resolve_theme_bundle_text(THEME_PRESETS["light"], "description"),
        ),
        1,
    )
    preview_row.addWidget(
        self._build_theme_mode_preview(
            "dark",
            self._resolve_theme_bundle_text(THEME_PRESETS["dark"], "title"),
            self._resolve_theme_bundle_text(THEME_PRESETS["dark"], "description"),
        ),
        1,
    )

    overview_layout.addLayout(preview_row)

    variant_row = QHBoxLayout()
    variant_row.setSpacing(12)

    light_variant_group = QGroupBox("라이트 프리셋")
    self._bind_group_title(light_variant_group, "settings.theme.variant_group.light", "라이트 프리셋")
    light_variant_layout = QVBoxLayout(light_variant_group)
    light_variant_layout.setSpacing(10)
    for variant_id, bundle in THEME_VARIANT_PRESETS["light"].items():
        light_variant_layout.addWidget(
            self._build_theme_variant_preview(
                "light",
                variant_id,
                self._resolve_theme_bundle_text(bundle, "title"),
                self._resolve_theme_bundle_text(bundle, "description"),
            )
        )
    variant_row.addWidget(light_variant_group, 1)

    dark_variant_group = QGroupBox("다크 프리셋")
    self._bind_group_title(dark_variant_group, "settings.theme.variant_group.dark", "다크 프리셋")
    dark_variant_layout = QVBoxLayout(dark_variant_group)
    dark_variant_layout.setSpacing(10)
    for variant_id, bundle in THEME_VARIANT_PRESETS["dark"].items():
        dark_variant_layout.addWidget(
            self._build_theme_variant_preview(
                "dark",
                variant_id,
                self._resolve_theme_bundle_text(bundle, "title"),
                self._resolve_theme_bundle_text(bundle, "description"),
            )
        )
    variant_row.addWidget(dark_variant_group, 1)

    overview_layout.addLayout(variant_row)

    self.follow_system_theme_check = self._create_toggle(
        "현재 윈도우 앱 테마(라이트/다크)를 따라가기",
        key="settings.theme.follow_system",
    )
    self.follow_system_theme_check.toggled.connect(self._on_follow_system_theme_toggled)
    overview_layout.addWidget(self.follow_system_theme_check)
    layout.addWidget(overview_group)

    settings_group = QGroupBox("설정창 팔레트")
    self._bind_group_title(settings_group, "settings.theme.settings_palette.title", "설정창 팔레트")
    settings_group_layout = QVBoxLayout(settings_group)
    settings_group_layout.setSpacing(12)
    settings_group_layout.addWidget(self._build_theme_color_editor("settings_window_bg_color", "설정창 바깥 배경", "설정창 전체의 기본 바탕색입니다."))
    settings_group_layout.addWidget(self._build_theme_color_editor("settings_card_bg_color", "설정 카드 배경", "타이틀 바, 카드, 탭 영역의 기본 표면색입니다."))
    settings_group_layout.addWidget(self._build_theme_color_editor("settings_input_bg_color", "입력 필드 배경", "입력창, 드롭다운, 리스트의 기본 배경색입니다."))
    layout.addWidget(settings_group)

    chat_group = QGroupBox("채팅창 팔레트")
    self._bind_group_title(chat_group, "settings.theme.chat_palette.title", "채팅창 팔레트")
    chat_group_layout = QVBoxLayout(chat_group)
    chat_group_layout.setSpacing(12)
    chat_group_layout.addWidget(self._build_theme_color_editor("chat_panel_bg_color", "채팅 메인 배경", "채팅창 하단 패널과 보조 위젯의 기본 배경색입니다."))
    chat_group_layout.addWidget(self._build_theme_color_editor("chat_input_bg_color", "채팅 입력 배경", "입력창과 입력 래퍼의 기본 배경색입니다."))
    chat_group_layout.addWidget(self._build_theme_color_editor("chat_assistant_bubble_color", "응답 버블 배경", "AI 응답 말풍선의 기본 배경색입니다."))
    chat_group_layout.addWidget(self._build_theme_color_editor("chat_user_bubble_color", "사용자 버블 배경", "사용자 말풍선의 기본 배경색입니다."))
    layout.addWidget(chat_group)

    accent_group = QGroupBox("포인트 색상")
    self._bind_group_title(accent_group, "settings.theme.accent_palette.title", "포인트 색상")
    accent_group_layout = QVBoxLayout(accent_group)
    accent_group_layout.setSpacing(12)
    accent_group_layout.addWidget(self._build_theme_color_editor("theme_accent_color", "포인트 색상", "저장 버튼, 포커스 링, 선택 상태와 강조 요소에 사용됩니다."))
    layout.addWidget(accent_group)

    self.theme_status_label = QLabel()
    self.theme_status_label.setWordWrap(True)
    layout.addWidget(self.theme_status_label)
    layout.addStretch()

    scroll.setWidget(widget)
    return scroll

