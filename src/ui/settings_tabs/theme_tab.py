"""테마 설정 페이지와 세부 색상 편집 창."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ...core.system_theme import THEME_VARIANT_PRESETS
from ..settings_theme_art import PaletteArtwork


class _PaletteGrid(QWidget):
    def __init__(self):
        super().__init__()
        self.cards = {}
        self.mode = ""
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)

    def show_mode(self, mode):
        columns = 1 if self.width() < 450 else 2
        if (mode, columns) == (self.mode, self.columns):
            return
        self.mode, self.columns = mode, columns
        for group, cards in self.cards.items():
            for i, card in enumerate(cards):
                self.grid.removeWidget(card)
                if group == mode:
                    self.grid.addWidget(card, i // columns, i % columns)
                card.setVisible(group == mode)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, int(columns == 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_mode(self.mode)


def _build_hero(dialog):
    hero = PaletteArtwork()
    row = QHBoxLayout(hero)
    row.setContentsMargins(22, 16, 22, 16)
    row.setSpacing(14)
    copy = QVBoxLayout()
    copy.setSpacing(5)
    copy.addStretch()
    caption = dialog._create_form_label("settings.theme.status.current_palette", "현재 팔레트")
    caption.setStyleSheet("color: #5C495D; background: transparent; font-size: 12px; font-weight: 650;")
    copy.addWidget(caption)
    dialog.theme_palette_name = QLabel()
    dialog.theme_palette_name.setWordWrap(True)
    dialog.theme_palette_name.setStyleSheet("background: transparent; color: #382C3E; font-size: 30px; font-weight: 800;")
    copy.addWidget(dialog.theme_palette_name)
    colors = QHBoxLayout()
    colors.setSpacing(1)
    dialog.theme_pigments = []
    for _ in range(4):
        dot = QFrame()
        dot.setFixedSize(20, 20)
        dialog.theme_pigments.append(dot)
        colors.addWidget(dot)
    colors.addStretch()
    copy.addLayout(colors)
    copy.addStretch()
    row.addLayout(copy, 3)

    chat = QFrame()
    chat.setObjectName("ThemeSampleChat")
    chat.setMaximumWidth(285)
    lines = QVBoxLayout(chat)
    lines.setContentsMargins(11, 8, 11, 9)
    lines.setSpacing(5)
    brand = QHBoxLayout()
    brand.setSpacing(5)
    avatar = QLabel()
    avatar.setPixmap(dialog.windowIcon().pixmap(21, 21))
    brand.addWidget(avatar)
    brand.addWidget(QLabel("ENE"))
    brand.addStretch()
    lines.addLayout(brand)
    dialog.theme_chat_assistant = dialog._create_form_label("settings.theme.studio.sample_in", "어떤 색을 골랐어요?")
    dialog.theme_chat_user = dialog._create_form_label("settings.theme.studio.sample_out", "지금 이 색이 좋아.")
    for bubble, align in ((dialog.theme_chat_assistant, Qt.AlignmentFlag.AlignLeft),
                          (dialog.theme_chat_user, Qt.AlignmentFlag.AlignRight)):
        lines.addWidget(bubble, 0, align)
    dialog.theme_chat_input = QFrame()
    dialog.theme_chat_input.setFixedHeight(11)
    lines.addWidget(dialog.theme_chat_input)
    row.addWidget(chat, 2, Qt.AlignmentFlag.AlignVCenter)
    dialog.theme_chat_preview = chat
    dialog.theme_hero = hero
    return hero


def _build_color_dialog(dialog):
    editor = QDialog(dialog)
    editor.setModal(True)
    editor.setObjectName("ThemeColorDialog")
    editor.resize(min(520, dialog.width()), min(560, dialog.height()))
    dialog._register_text_binding(editor.setWindowTitle, "settings.theme.studio.edit", "세부 색상 조정")
    layout = QVBoxLayout(editor)
    layout.setContentsMargins(18, 16, 18, 16)
    heading = dialog._create_form_label("settings.theme.studio.edit", "세부 색상 조정")
    heading.setStyleSheet("font-size: 18px; font-weight: 750;")
    layout.addWidget(heading)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    rows = QVBoxLayout(body)
    rows.setContentsMargins(0, 4, 4, 4)
    rows.setSpacing(7)
    for key, title, hint in (
        ("settings_window_bg_color", "설정창 바깥 배경", "설정창 전체의 기본 바탕색입니다."),
        ("settings_card_bg_color", "설정 카드 배경", "타이틀 바, 카드, 탭 영역의 기본 표면색입니다."),
        ("settings_input_bg_color", "입력 필드 배경", "입력창, 드롭다운, 리스트의 기본 배경색입니다."),
        ("theme_accent_color", "포인트 색상", "저장 버튼, 포커스 링, 선택 상태와 강조 요소에 사용됩니다."),
        ("chat_panel_bg_color", "채팅 메인 배경", "채팅창 하단 패널과 보조 위젯의 기본 배경색입니다."),
        ("chat_input_bg_color", "채팅 입력 배경", "입력창과 입력 래퍼의 기본 배경색입니다."),
        ("chat_assistant_bubble_color", "응답 버블 배경", "AI 응답 말풍선의 기본 배경색입니다."),
        ("chat_user_bubble_color", "사용자 버블 배경", "사용자 말풍선의 기본 배경색입니다."),
    ):
        rows.addWidget(dialog._build_theme_color_editor(key, title, hint))
    rows.addStretch()
    scroll.setWidget(body)
    layout.addWidget(scroll, 1)
    dialog.theme_status_label = QLabel()
    dialog.theme_status_label.setWordWrap(True)
    layout.addWidget(dialog.theme_status_label)
    buttons = QHBoxLayout()
    buttons.addStretch()
    cancel = dialog._bind_widget_text(QPushButton(), "settings.footer.cancel", "취소")
    cancel.clicked.connect(editor.reject)
    buttons.addWidget(cancel)
    apply = dialog._bind_widget_text(QPushButton(), "ene_profile.button.apply", "적용")
    apply.setObjectName("ThemeApply")
    apply.setDefault(True)
    apply.clicked.connect(editor.accept)
    buttons.addWidget(apply)
    layout.addLayout(buttons)
    dialog.theme_color_apply_button = apply
    editor.finished.connect(dialog._finish_theme_color_editor)
    return editor


def build_theme_tab(dialog):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(1, 2, 8, 16)
    layout.setSpacing(12)
    layout.addWidget(_build_hero(dialog))

    row = QHBoxLayout()
    mode_label = dialog._create_form_label("settings.theme.studio.mode", "화면 모드")
    mode_label.setStyleSheet("font-size: 15px; font-weight: 750;")
    row.addWidget(mode_label)
    row.addStretch()
    segment = QFrame()
    segment.setObjectName("ThemeSegments")
    segment_layout = QHBoxLayout(segment)
    segment_layout.setContentsMargins(3, 3, 3, 3)
    segment_layout.setSpacing(2)
    for mode in ("light", "dark", "system"):
        button = dialog._build_theme_mode_preview(mode)
        segment_layout.addWidget(button)
    dialog.follow_system_theme_check = dialog._theme_preset_frames["system"]
    row.addWidget(segment)
    dialog.theme_segments = segment
    layout.addLayout(row)
    dialog.theme_section_rule = QFrame()
    dialog.theme_section_rule.setFixedHeight(1)
    layout.addWidget(dialog.theme_section_rule)
    actions = QHBoxLayout()
    title = dialog._create_form_label("settings.theme.studio.palettes", "컬러 팔레트")
    title.setStyleSheet("font-size: 15px; font-weight: 750;")
    actions.addWidget(title)
    actions.addStretch()
    dialog.theme_edit_button = dialog._bind_widget_text(QPushButton(), "settings.theme.studio.edit", "세부 색상 조정")
    dialog.theme_edit_button.setObjectName("ThemeEditLink")
    dialog.theme_edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
    dialog.theme_edit_button.clicked.connect(dialog._open_theme_color_editor)
    actions.addWidget(dialog.theme_edit_button)
    layout.addLayout(actions)

    dialog.theme_palette_grid = _PaletteGrid()
    for mode, variants in THEME_VARIANT_PRESETS.items():
        dialog.theme_palette_grid.cards[mode] = [
            dialog._build_theme_variant_preview(mode, key, dialog._resolve_theme_bundle_text(bundle, "title"))
            for key, bundle in variants.items()
        ]
    layout.addWidget(dialog.theme_palette_grid)
    layout.addStretch()
    dialog._theme_editor_active = False
    dialog._theme_base_variant = None
    dialog._theme_mode_choices = {}
    dialog._theme_palette_drafts = {}
    dialog.theme_color_dialog = _build_color_dialog(dialog)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    scroll.setWidget(widget)
    return scroll

