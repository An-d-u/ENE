"""
창 설정 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def build_window_tab(dialog):
    self = dialog
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)

    general_group = QGroupBox("일반")
    self._bind_group_title(general_group, "settings.window.general.title", "일반")
    general_layout = QFormLayout(general_group)
    general_layout.setSpacing(8)
    general_layout.setContentsMargins(10, 15, 10, 10)

    self.ui_language_combo = QComboBox()
    for value, key, fallback in (
        ("auto", "settings.window.general.ui_language.auto", "시스템 기본값"),
        ("ko", "settings.window.general.ui_language.ko", "한국어"),
        ("en", "settings.window.general.ui_language.en", "영어"),
        ("ja", "settings.window.general.ui_language.ja", "일본어"),
    ):
        self.ui_language_combo.addItem(self._translated_text(key, fallback), value)
    self.ui_language_combo.currentIndexChanged.connect(self._on_ui_language_changed)
    self._add_form_row(general_layout, "settings.window.general.ui_language.label", "UI 언어:", self.ui_language_combo)
    general_layout.addRow(
        self._build_hint_label(
            "현재 설정창 문구를 미리보기로 바꾸고, 저장 후에는 다음 실행부터 같은 언어를 기본값으로 사용합니다.",
            key="settings.window.general.ui_language.hint",
        )
    )
    self.assistant_display_name_edit = QLineEdit()
    self.assistant_display_name_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        general_layout,
        "settings.window.general.assistant_display_name.label",
        "캐릭터 호칭:",
        self.assistant_display_name_edit,
    )
    self.user_address_name_edit = QLineEdit()
    self.user_address_name_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        general_layout,
        "settings.window.general.user_address_name.label",
        "사용자 호칭:",
        self.user_address_name_edit,
    )
    general_layout.addRow(
        self._build_hint_label(
            "프롬프트 안에서만 쓰는 이름입니다. 채팅 UI와 내부 role 값은 그대로 유지됩니다.",
            key="settings.window.general.prompt_names.hint",
        )
    )
    layout.addWidget(general_group)

    quick_group = QGroupBox("빠른 배치")
    self._bind_group_title(quick_group, "settings.window.quick.title", "빠른 배치")
    quick_layout = QVBoxLayout(quick_group)
    quick_layout.setSpacing(10)
    quick_layout.addWidget(
        self._build_hint_label(
            "자주 쓰는 위치를 먼저 고른 뒤, 아래에서 좌표와 크기를 미세 조정할 수 있습니다.",
            key="settings.window.quick.hint",
        )
    )

    preset_layout = QHBoxLayout()
    preset_layout.setSpacing(10)
    center_btn = QPushButton("화면 중앙")
    self._bind_widget_text(center_btn, "settings.window.quick.center", "화면 중앙")
    center_btn.clicked.connect(self._preset_center)
    preset_layout.addWidget(center_btn)

    br_btn = QPushButton("우측 하단")
    self._bind_widget_text(br_btn, "settings.window.quick.bottom_right", "우측 하단")
    br_btn.clicked.connect(self._preset_bottom_right)
    preset_layout.addWidget(br_btn)

    bl_btn = QPushButton("좌측 하단")
    self._bind_widget_text(bl_btn, "settings.window.quick.bottom_left", "좌측 하단")
    bl_btn.clicked.connect(self._preset_bottom_left)
    preset_layout.addWidget(bl_btn)
    quick_layout.addLayout(preset_layout)
    layout.addWidget(quick_group)

    position_group = QGroupBox("정밀 위치")
    self._bind_group_title(position_group, "settings.window.position.title", "정밀 위치")
    position_layout = QFormLayout()
    position_layout.setSpacing(8)

    self.window_x_spin = QSpinBox()
    self.window_x_spin.setRange(-9999, 9999)
    self.window_x_spin.setSuffix(" px")
    self.window_x_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(position_layout, "settings.window.position.x", "X 좌표:", self.window_x_spin)

    self.window_y_spin = QSpinBox()
    self.window_y_spin.setRange(-9999, 9999)
    self.window_y_spin.setSuffix(" px")
    self.window_y_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(position_layout, "settings.window.position.y", "Y 좌표:", self.window_y_spin)
    position_group.setLayout(position_layout)
    layout.addWidget(position_group)

    size_group = QGroupBox("창 크기")
    self._bind_group_title(size_group, "settings.window.size.title", "창 크기")
    size_layout = QFormLayout()
    size_layout.setSpacing(8)

    self.window_width_spin = QSpinBox()
    self.window_width_spin.setRange(200, 3840)
    self.window_width_spin.setSuffix(" px")
    self.window_width_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(size_layout, "settings.window.size.width", "너비:", self.window_width_spin)

    self.window_height_spin = QSpinBox()
    self.window_height_spin.setRange(200, 2160)
    self.window_height_spin.setSuffix(" px")
    self.window_height_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(size_layout, "settings.window.size.height", "높이:", self.window_height_spin)
    size_group.setLayout(size_layout)
    layout.addWidget(size_group)

    layout.addStretch()
    return widget

