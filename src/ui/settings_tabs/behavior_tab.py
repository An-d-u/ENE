"""
동작 설정 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...ai.prompt import get_available_emotions


def build_behavior_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    display_group = QGroupBox("표시 요소")
    self._bind_group_title(display_group, "settings.behavior.display.title", "표시 요소")
    display_layout = QVBoxLayout(display_group)
    display_layout.setSpacing(8)

    self.show_drag_bar_check = self._create_toggle("드래그 바 표시", key="settings.behavior.display.drag_bar")
    self.show_drag_bar_check.toggled.connect(self._on_setting_changed)
    display_layout.addWidget(self.show_drag_bar_check)

    self.show_recent_reroll_button_check = self._create_toggle(
        "최근 메시지 리롤 버튼 표시",
        key="settings.behavior.display.recent_reroll",
    )
    self.show_recent_reroll_button_check.toggled.connect(self._on_setting_changed)
    display_layout.addWidget(self.show_recent_reroll_button_check)

    self.show_recent_edit_button_check = self._create_toggle(
        "최근 메시지 수정 버튼 표시",
        key="settings.behavior.display.recent_edit",
    )
    self.show_recent_edit_button_check.toggled.connect(self._on_setting_changed)
    display_layout.addWidget(self.show_recent_edit_button_check)

    self.show_token_usage_bubble_check = self._create_toggle(
        "대화 토큰 확인",
        key="settings.behavior.display.token_usage",
    )
    self.show_token_usage_bubble_check.toggled.connect(self._on_setting_changed)
    display_layout.addWidget(self.show_token_usage_bubble_check)

    self.typing_effect_check = self._create_toggle(
        "타이핑 효과",
        key="settings.behavior.display.typing_effect",
    )
    self.typing_effect_check.toggled.connect(self._on_typing_effect_toggle)
    display_layout.addWidget(self.typing_effect_check)

    self.message_split_check = self._create_toggle(
        "메시지 분할 표시",
        key="settings.behavior.display.message_split",
    )
    self.message_split_check.toggled.connect(self._on_setting_changed)
    display_layout.addWidget(self.message_split_check)

    self.enable_ene_thoughts_check = self._create_toggle(
        "에네 생각 표시",
        key="settings.behavior.display.ene_thoughts",
    )
    self.enable_ene_thoughts_check.toggled.connect(self._on_ene_thoughts_toggle)
    display_layout.addWidget(self.enable_ene_thoughts_check)

    self.enable_ene_goals_check = self._create_toggle(
        "에네 목표 사용",
        key="settings.behavior.display.ene_goals",
    )
    self.enable_ene_goals_check.toggled.connect(self._on_ene_goals_toggle)
    display_layout.addWidget(self.enable_ene_goals_check)

    self.include_ene_thoughts_in_context_check = self._create_toggle(
        "에네 생각을 다음 대화에 반영",
        key="settings.behavior.display.ene_thought_context",
    )
    self.include_ene_thoughts_in_context_check.toggled.connect(self._on_ene_thought_context_toggle)
    display_layout.addWidget(self.include_ene_thoughts_in_context_check)

    self.enable_proactive_conversation_check = self._create_toggle(
        "선제 대화 사용",
        key="settings.behavior.display.proactive_conversation",
    )
    self.enable_proactive_conversation_check.toggled.connect(self._on_setting_changed)
    display_layout.addWidget(self.enable_proactive_conversation_check)

    thought_context_layout = QFormLayout()
    thought_context_layout.setContentsMargins(0, 0, 0, 0)
    thought_context_layout.setSpacing(8)
    self.ene_thought_context_limit_spin = QSpinBox()
    self.ene_thought_context_limit_spin.setRange(0, 20)
    self.ene_thought_context_limit_spin.setSuffix(
        self._translated_text("settings.behavior.display.ene_thought_context_limit.suffix", " 개")
    )
    self._register_text_binding(
        self.ene_thought_context_limit_spin.setSuffix,
        "settings.behavior.display.ene_thought_context_limit.suffix",
        " 개",
    )
    self.ene_thought_context_limit_spin.setSpecialValueText(
        self._translated_text("settings.behavior.display.ene_thought_context_limit.zero", "포함 안 함")
    )
    self._register_text_binding(
        self.ene_thought_context_limit_spin.setSpecialValueText,
        "settings.behavior.display.ene_thought_context_limit.zero",
        "포함 안 함",
    )
    self.ene_thought_context_limit_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        thought_context_layout,
        "settings.behavior.display.ene_thought_context_limit.label",
        "생각 반영 개수:",
        self.ene_thought_context_limit_spin,
    )
    display_layout.addLayout(thought_context_layout)

    typing_speed_layout = QFormLayout()
    typing_speed_layout.setContentsMargins(0, 0, 0, 0)
    typing_speed_layout.setSpacing(8)
    self.typing_effect_speed_combo = QComboBox()
    self.typing_effect_speed_combo.addItem(
        self._translated_text("settings.behavior.display.typing_speed.fast", "빠름"),
        "fast",
    )
    self._bind_combo_item(
        self.typing_effect_speed_combo,
        0,
        "settings.behavior.display.typing_speed.fast",
        "빠름",
    )
    self.typing_effect_speed_combo.addItem(
        self._translated_text("settings.behavior.display.typing_speed.normal", "보통"),
        "normal",
    )
    self._bind_combo_item(
        self.typing_effect_speed_combo,
        1,
        "settings.behavior.display.typing_speed.normal",
        "보통",
    )
    self.typing_effect_speed_combo.addItem(
        self._translated_text("settings.behavior.display.typing_speed.slow", "느림"),
        "slow",
    )
    self._bind_combo_item(
        self.typing_effect_speed_combo,
        2,
        "settings.behavior.display.typing_speed.slow",
        "느림",
    )
    self.typing_effect_speed_combo.currentIndexChanged.connect(self._on_setting_changed)
    self.typing_effect_speed_label = self._add_form_row(
        typing_speed_layout,
        "settings.behavior.display.typing_speed.label",
        "타이핑 속도:",
        self.typing_effect_speed_combo,
    )
    display_layout.addLayout(typing_speed_layout)

    self.mouse_tracking_check = self._create_toggle(
        "마우스 트래킹 활성화",
        key="settings.behavior.display.mouse_tracking",
    )
    self.mouse_tracking_check.toggled.connect(self._on_setting_changed)
    display_layout.addWidget(self.mouse_tracking_check)
    display_layout.addWidget(
        self._build_hint_label(
            "기본 노출 요소와 마우스 상호작용을 한 묶음으로 관리합니다.",
            key="settings.behavior.display.hint",
        )
    )
    layout.addWidget(display_group)

    action_group = QGroupBox("대화와 보조 버튼")
    self._bind_group_title(action_group, "settings.behavior.actions.title", "대화와 보조 버튼")
    action_layout = QVBoxLayout(action_group)
    action_layout.setSpacing(8)
    self.show_manual_summary_button_check = self._create_toggle(
        "수동 요약 버튼 표시",
        key="settings.behavior.actions.manual_summary",
    )
    self.show_manual_summary_button_check.toggled.connect(self._on_setting_changed)
    action_layout.addWidget(self.show_manual_summary_button_check)

    self.show_obsidian_note_button_check = self._create_toggle(
        "노트 버튼 표시",
        key="settings.behavior.actions.note_button",
    )
    self.show_obsidian_note_button_check.toggled.connect(self._on_setting_changed)
    action_layout.addWidget(self.show_obsidian_note_button_check)

    self.show_mood_toggle_button_check = self._create_toggle(
        "기분 버튼 표시",
        key="settings.behavior.actions.mood_button",
    )
    self.show_mood_toggle_button_check.toggled.connect(self._on_setting_changed)
    action_layout.addWidget(self.show_mood_toggle_button_check)

    self.show_ene_goal_button_check = self._create_toggle(
        "목표 버튼 표시",
        key="settings.behavior.actions.goal_button",
    )
    self.show_ene_goal_button_check.toggled.connect(self._on_setting_changed)
    action_layout.addWidget(self.show_ene_goal_button_check)
    action_layout.addWidget(
        self._build_hint_label(
            "자주 누르는 버튼만 켜두면 화면이 덜 복잡해집니다.",
            key="settings.behavior.actions.hint",
        )
    )
    layout.addWidget(action_group)

    layout.addWidget(self._create_ene_goals_group())

    ptt_group = QGroupBox("음성 입력 (전역 PTT)")
    self._bind_group_title(ptt_group, "settings.behavior.ptt.title", "음성 입력 (전역 PTT)")
    ptt_layout = QFormLayout(ptt_group)
    ptt_layout.setSpacing(8)
    ptt_layout.setContentsMargins(10, 15, 10, 10)

    self.enable_global_ptt_check = self._create_toggle(
        "전역 Push-to-Talk 활성화",
        key="settings.behavior.ptt.enable",
    )
    self.enable_global_ptt_check.toggled.connect(self._on_setting_changed)
    ptt_layout.addRow(self.enable_global_ptt_check)

    self.interrupt_tts_on_ptt_check = self._create_toggle(
        "PTT 시작 시 ENE 음성 출력 끊기",
        key="settings.behavior.ptt.interrupt_tts",
    )
    self.interrupt_tts_on_ptt_check.toggled.connect(self._on_setting_changed)
    ptt_layout.addRow(self.interrupt_tts_on_ptt_check)

    ptt_hotkey_row = QHBoxLayout()
    self.global_ptt_hotkey_value_label = QLabel("")
    self.global_ptt_hotkey_value_label.setMinimumWidth(140)
    self.global_ptt_hotkey_value_label.setObjectName("ValueBadge")
    ptt_hotkey_row.addWidget(self.global_ptt_hotkey_value_label)

    self.global_ptt_hotkey_set_button = QPushButton("단축키 설정")
    self.global_ptt_hotkey_set_button.clicked.connect(self._start_ptt_hotkey_capture)
    ptt_hotkey_row.addWidget(self.global_ptt_hotkey_set_button)

    self.global_ptt_hotkey_reset_button = QPushButton("기본값")
    self._bind_widget_text(self.global_ptt_hotkey_reset_button, "settings.behavior.ptt.hotkey.reset", "기본값")
    self.global_ptt_hotkey_reset_button.clicked.connect(self._reset_ptt_hotkey)
    ptt_hotkey_row.addWidget(self.global_ptt_hotkey_reset_button)
    self._add_form_row(ptt_layout, "settings.behavior.ptt.hotkey.label", "PTT 단축키:", ptt_hotkey_row)

    self.ptt_language_combo = QComboBox()
    for value, key, fallback in (
        ("ko", "settings.behavior.ptt.language.ko", "한국어"),
        ("en", "settings.behavior.ptt.language.en", "영어"),
        ("ja", "settings.behavior.ptt.language.ja", "일본어"),
    ):
        self.ptt_language_combo.addItem(self._translated_text(key, fallback), value)
    self.ptt_language_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(ptt_layout, "settings.behavior.ptt.language.label", "입력 언어:", self.ptt_language_combo)

    self.global_ptt_hotkey_hint_label = QLabel("")
    self.global_ptt_hotkey_hint_label.setWordWrap(True)
    self.global_ptt_hotkey_hint_label.setObjectName("InlineHint")
    ptt_layout.addRow(self.global_ptt_hotkey_hint_label)

    layout.addWidget(ptt_group)

    note_group = QGroupBox("노트 설정")
    self._bind_group_title(note_group, "settings.behavior.note.title", "노트 설정")
    note_layout = QFormLayout(note_group)
    note_layout.setSpacing(8)
    note_layout.setContentsMargins(10, 15, 10, 10)

    self.note_include_recent_context_check = self._create_toggle(
        "/note에 최근 대화 맥락 자동 주입",
        key="settings.behavior.note.include_recent",
    )
    self.note_include_recent_context_check.toggled.connect(self._on_note_context_toggle)
    note_layout.addRow(self.note_include_recent_context_check)

    self.note_recent_context_turns_spin = QSpinBox()
    self.note_recent_context_turns_spin.setRange(0, 200)
    self._bind_special_value_text(self.note_recent_context_turns_spin, "settings.behavior.note.recent_turns.all", "전체 세션")
    self._bind_suffix(self.note_recent_context_turns_spin, "settings.behavior.note.recent_turns.suffix", " 턴")
    self.note_recent_context_turns_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        note_layout,
        "settings.behavior.note.recent_turns.label",
        "주입 턴 수 (0=전체):",
        self.note_recent_context_turns_spin,
    )

    self.obsidian_checked_max_chars_per_file_spin = QSpinBox()
    self.obsidian_checked_max_chars_per_file_spin.setRange(100, 200000)
    self._bind_suffix(
        self.obsidian_checked_max_chars_per_file_spin,
        "settings.behavior.note.checked_max_chars_per_file.suffix",
        " 자",
    )
    self.obsidian_checked_max_chars_per_file_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        note_layout,
        "settings.behavior.note.checked_max_chars_per_file.label",
        "체크 파일당 최대 글자 수:",
        self.obsidian_checked_max_chars_per_file_spin,
    )

    self.obsidian_checked_total_max_chars_spin = QSpinBox()
    self.obsidian_checked_total_max_chars_spin.setRange(100, 1000000)
    self._bind_suffix(
        self.obsidian_checked_total_max_chars_spin,
        "settings.behavior.note.checked_total_max_chars.suffix",
        " 자",
    )
    self.obsidian_checked_total_max_chars_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        note_layout,
        "settings.behavior.note.checked_total_max_chars.label",
        "체크 파일 전체 최대 글자 수:",
        self.obsidian_checked_total_max_chars_spin,
    )
    layout.addWidget(note_group)

    idle_group = QGroupBox("유휴 모션")
    self._bind_group_title(idle_group, "settings.behavior.idle.title", "유휴 모션")
    idle_layout = QFormLayout(idle_group)
    idle_layout.setSpacing(8)
    idle_layout.setContentsMargins(10, 15, 10, 10)
    self.idle_motion_check = self._create_toggle(
        "유휴 모션 활성화 (말하지 않을 때 자동 움직임)",
        key="settings.behavior.idle.enable",
    )
    self.idle_motion_check.toggled.connect(self._on_setting_changed)
    idle_layout.addRow(self.idle_motion_check)

    self.builtin_idle_motion_check = self._create_toggle(
        "Live2D 기본 idle 모션 활성화",
        key="settings.behavior.idle.builtin_enable",
    )
    self.builtin_idle_motion_check.toggled.connect(self._on_setting_changed)
    idle_layout.addRow(self.builtin_idle_motion_check)

    self.auto_eye_blink_check = self._create_toggle(
        "자동 눈 깜빡임 활성화",
        key="settings.behavior.idle.auto_eye_blink_enable",
    )
    self.auto_eye_blink_check.toggled.connect(self._on_setting_changed)
    idle_layout.addRow(self.auto_eye_blink_check)

    self.idle_motion_strength_spin = QDoubleSpinBox()
    self.idle_motion_strength_spin.setRange(0.2, 2.0)
    self.idle_motion_strength_spin.setSingleStep(0.1)
    self.idle_motion_strength_spin.setDecimals(2)
    self.idle_motion_strength_spin.setSuffix("x")
    self.idle_motion_strength_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(idle_layout, "settings.behavior.idle.strength", "유휴 모션 강도:", self.idle_motion_strength_spin)

    self.idle_motion_speed_spin = QDoubleSpinBox()
    self.idle_motion_speed_spin.setRange(0.5, 2.0)
    self.idle_motion_speed_spin.setSingleStep(0.1)
    self.idle_motion_speed_spin.setDecimals(2)
    self.idle_motion_speed_spin.setSuffix("x")
    self.idle_motion_speed_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(idle_layout, "settings.behavior.idle.speed", "유휴 모션 속도:", self.idle_motion_speed_spin)
    layout.addWidget(idle_group)

    pat_group = QGroupBox("머리 쓰다듬기")
    self._bind_group_title(pat_group, "settings.behavior.head_pat.title", "머리 쓰다듬기")
    pat_layout = QFormLayout(pat_group)
    pat_layout.setSpacing(8)
    pat_layout.setContentsMargins(10, 15, 10, 10)
    self.head_pat_check = self._create_toggle(
        "머리 쓰다듬기 활성화",
        key="settings.behavior.head_pat.enable",
    )
    self.head_pat_check.toggled.connect(self._on_setting_changed)
    pat_layout.addRow(self.head_pat_check)

    self.head_pat_strength_spin = QDoubleSpinBox()
    self.head_pat_strength_spin.setRange(0.5, 2.5)
    self.head_pat_strength_spin.setSingleStep(0.1)
    self.head_pat_strength_spin.setDecimals(2)
    self.head_pat_strength_spin.setSuffix("x")
    self.head_pat_strength_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(pat_layout, "settings.behavior.head_pat.strength", "쓰다듬기 강도:", self.head_pat_strength_spin)

    self.head_pat_fade_in_spin = QSpinBox()
    self.head_pat_fade_in_spin.setRange(50, 1000)
    self.head_pat_fade_in_spin.setSuffix(" ms")
    self.head_pat_fade_in_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(pat_layout, "settings.behavior.head_pat.fade_in", "시작 페이드:", self.head_pat_fade_in_spin)

    self.head_pat_fade_out_spin = QSpinBox()
    self.head_pat_fade_out_spin.setRange(50, 1200)
    self.head_pat_fade_out_spin.setSuffix(" ms")
    self.head_pat_fade_out_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(pat_layout, "settings.behavior.head_pat.fade_out", "종료 페이드:", self.head_pat_fade_out_spin)

    self.head_pat_active_emotion_combo = QComboBox()
    self._emotion_options = get_available_emotions()
    if "eyeclose" not in self._emotion_options:
        self._emotion_options.append("eyeclose")
    self.head_pat_active_emotion_combo.addItems(self._emotion_options)
    self.head_pat_active_emotion_combo.currentTextChanged.connect(self._on_setting_changed)
    self._add_form_row(
        pat_layout,
        "settings.behavior.head_pat.active_emotion_default",
        "쓰다듬기 중 감정(기본):",
        self.head_pat_active_emotion_combo,
    )

    self.head_pat_active_emotion_custom_edit = QLineEdit()
    self._bind_placeholder(
        self.head_pat_active_emotion_custom_edit,
        "settings.behavior.head_pat.active_emotion_custom.placeholder",
        "커스텀 감정 (텍스트 우선)",
    )
    self.head_pat_active_emotion_custom_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        pat_layout,
        "settings.behavior.head_pat.active_emotion_custom.label",
        "쓰다듬기 중 감정(커스텀):",
        self.head_pat_active_emotion_custom_edit,
    )

    self.head_pat_end_emotion_combo = QComboBox()
    self.head_pat_end_emotion_combo.addItems(self._emotion_options)
    self.head_pat_end_emotion_combo.currentTextChanged.connect(self._on_setting_changed)
    self._add_form_row(pat_layout, "settings.behavior.head_pat.end_emotion_default", "종료 감정(기본):", self.head_pat_end_emotion_combo)

    self.head_pat_end_emotion_custom_edit = QLineEdit()
    self._bind_placeholder(
        self.head_pat_end_emotion_custom_edit,
        "settings.behavior.head_pat.end_emotion_custom.placeholder",
        "커스텀 감정 (텍스트 우선)",
    )
    self.head_pat_end_emotion_custom_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        pat_layout,
        "settings.behavior.head_pat.end_emotion_custom.label",
        "종료 감정(커스텀):",
        self.head_pat_end_emotion_custom_edit,
    )

    self.head_pat_end_emotion_duration_spin = QSpinBox()
    self.head_pat_end_emotion_duration_spin.setRange(1, 30)
    self.head_pat_end_emotion_duration_spin.setSuffix(" s")
    self.head_pat_end_emotion_duration_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(pat_layout, "settings.behavior.head_pat.end_duration", "감정 유지 시간:", self.head_pat_end_emotion_duration_spin)
    layout.addWidget(pat_group)

    away_group = QGroupBox("자리 비움/유휴 감지")
    self._bind_group_title(away_group, "settings.behavior.away.title", "자리 비움/유휴 감지")
    away_layout = QFormLayout(away_group)
    away_layout.setSpacing(8)
    away_layout.setContentsMargins(10, 15, 10, 10)

    self.enable_away_nudge_check = self._create_toggle(
        "유휴 감지 자동 말걸기 활성화",
        key="settings.behavior.away.enable",
    )
    self.enable_away_nudge_check.toggled.connect(self._on_setting_changed)
    away_layout.addRow(self.enable_away_nudge_check)

    self.away_idle_minutes_spin = QSpinBox()
    self.away_idle_minutes_spin.setRange(5, 240)
    self._bind_suffix(self.away_idle_minutes_spin, "settings.behavior.away.idle_minutes.suffix", " 분")
    self.away_idle_minutes_spin.valueChanged.connect(self._on_away_idle_minutes_changed)
    self._add_form_row(away_layout, "settings.behavior.away.idle_minutes.label", "유휴 시간:", self.away_idle_minutes_spin)

    self.away_input_grace_minutes_spin = QSpinBox()
    self.away_input_grace_minutes_spin.setRange(1, 240)
    self._bind_suffix(self.away_input_grace_minutes_spin, "settings.behavior.away.input_grace_minutes.suffix", " 분")
    self.away_input_grace_minutes_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        away_layout,
        "settings.behavior.away.input_grace_minutes.label",
        "입력 확인 구간:",
        self.away_input_grace_minutes_spin,
    )

    self.away_retry_limit_spin = QSpinBox()
    self.away_retry_limit_spin.setRange(0, 20)
    self._bind_suffix(self.away_retry_limit_spin, "settings.behavior.away.retry_limit.suffix", " 회")
    self.away_retry_limit_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(away_layout, "settings.behavior.away.retry_limit.label", "추가 재실행 횟수:", self.away_retry_limit_spin)

    layout.addWidget(away_group)

    layout.addStretch()
    scroll.setWidget(widget)
    return scroll

