"""대화 화면, 반응, 목표·노트, 감지·기록 설정."""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QPushButton, QSpinBox, QVBoxLayout

from ...core.observation_intervals import MAX_INTERVAL_SECONDS
from ..diagnostic_share_dialog import open_diagnostic_share
from .section_navigation import group_page, section_group, section_tabs


def build_behavior_tab(dialog):
    return section_tabs(dialog, "behavior", (
        ("settings.sections.chat_screen", "대화 화면", _chat_screen(dialog)),
        ("settings.sections.chat_response", "대화 반응", _chat_response(dialog)),
        ("settings.sections.goals_notes", "목표·노트", _goals_notes(dialog)),
        ("settings.sections.detection_records", "감지·기록", _detection_records(dialog)),
    ))


def _chat_screen(self):
    messages, messages_layout = section_group(self, "messages", "메시지 표시", QVBoxLayout)
    self.typing_effect_check = self._create_toggle(
        "타이핑 효과",
        key="settings.behavior.display.typing_effect",
    )
    self.typing_effect_check.toggled.connect(self._on_typing_effect_toggle)
    messages_layout.addWidget(self.typing_effect_check)

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
    messages_layout.addLayout(typing_speed_layout)

    self.message_split_check = self._create_toggle(
        "메시지 분할 표시",
        key="settings.behavior.display.message_split",
    )
    self.message_split_check.toggled.connect(self._on_setting_changed)
    messages_layout.addWidget(self.message_split_check)

    self.show_token_usage_bubble_check = self._create_toggle(
        "대화 토큰 확인",
        key="settings.behavior.display.token_usage",
    )
    self.show_token_usage_bubble_check.toggled.connect(self._on_setting_changed)
    messages_layout.addWidget(self.show_token_usage_bubble_check)

    buttons, buttons_layout = section_group(self, "buttons", "대화창 버튼", QVBoxLayout)
    self.show_drag_bar_check = self._create_toggle("드래그 바 표시", key="settings.behavior.display.drag_bar")
    self.show_drag_bar_check.toggled.connect(self._on_setting_changed)
    buttons_layout.addWidget(self.show_drag_bar_check)

    self.show_recent_reroll_button_check = self._create_toggle(
        "최근 메시지 리롤 버튼 표시",
        key="settings.behavior.display.recent_reroll",
    )
    self.show_recent_reroll_button_check.toggled.connect(self._on_setting_changed)
    buttons_layout.addWidget(self.show_recent_reroll_button_check)

    self.show_recent_edit_button_check = self._create_toggle(
        "최근 메시지 수정 버튼 표시",
        key="settings.behavior.display.recent_edit",
    )
    self.show_recent_edit_button_check.toggled.connect(self._on_setting_changed)
    buttons_layout.addWidget(self.show_recent_edit_button_check)

    self.show_manual_summary_button_check = self._create_toggle(
        "수동 요약 버튼 표시",
        key="settings.behavior.actions.manual_summary",
    )
    self.show_manual_summary_button_check.toggled.connect(self._on_setting_changed)
    buttons_layout.addWidget(self.show_manual_summary_button_check)

    self.show_obsidian_note_button_check = self._create_toggle(
        "노트 버튼 표시",
        key="settings.behavior.actions.note_button",
    )
    self.show_obsidian_note_button_check.toggled.connect(self._on_setting_changed)
    buttons_layout.addWidget(self.show_obsidian_note_button_check)

    self.show_mood_toggle_button_check = self._create_toggle(
        "기분 버튼 표시",
        key="settings.behavior.actions.mood_button",
    )
    self.show_mood_toggle_button_check.toggled.connect(self._on_setting_changed)
    buttons_layout.addWidget(self.show_mood_toggle_button_check)

    self.show_ene_goal_button_check = self._create_toggle(
        "목표 버튼 표시",
        key="settings.behavior.actions.goal_button",
    )
    self.show_ene_goal_button_check.toggled.connect(self._on_setting_changed)
    buttons_layout.addWidget(self.show_ene_goal_button_check)
    return group_page(messages, buttons)


def _chat_response(self):
    reactions, reactions_layout = section_group(self, "reactions", "대화 시작과 해석", QVBoxLayout)
    self.enable_proactive_conversation_check = self._create_toggle(
        "선제 대화 사용",
        key="settings.behavior.display.proactive_conversation",
    )
    self.enable_proactive_conversation_check.toggled.connect(self._on_setting_changed)
    reactions_layout.addWidget(self.enable_proactive_conversation_check)

    self.enable_response_analysis_check = self._create_toggle(
        "응답 분석 블록 사용",
        key="settings.behavior.display.response_analysis",
    )
    self.enable_response_analysis_check.toggled.connect(self._on_response_analysis_toggle)
    reactions_layout.addWidget(self.enable_response_analysis_check)

    self.enable_schedule_recognition_check = self._create_toggle(
        "일정 인식 사용",
        key="settings.behavior.display.schedule_recognition",
    )
    self.enable_schedule_recognition_check.toggled.connect(self._on_setting_changed)
    reactions_layout.addWidget(self.enable_schedule_recognition_check)

    self.enable_conversation_promises_check = self._create_toggle(
        "대화 약속 인식 사용",
        key="settings.behavior.display.conversation_promises",
    )
    self.enable_conversation_promises_check.toggled.connect(self._on_setting_changed)
    reactions_layout.addWidget(self.enable_conversation_promises_check)

    thoughts, thoughts_layout = section_group(self, "thoughts", "생각과 기분", QVBoxLayout)
    self.enable_ene_thoughts_check = self._create_toggle(
        "에네 생각 표시",
        key="settings.behavior.display.ene_thoughts",
    )
    self.enable_ene_thoughts_check.toggled.connect(self._on_ene_thoughts_toggle)
    thoughts_layout.addWidget(self.enable_ene_thoughts_check)

    self.include_ene_thoughts_in_context_check = self._create_toggle(
        "에네 생각을 다음 대화에 반영",
        key="settings.behavior.display.ene_thought_context",
    )
    self.include_ene_thoughts_in_context_check.toggled.connect(self._on_ene_thought_context_toggle)
    thoughts_layout.addWidget(self.include_ene_thoughts_in_context_check)

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
    thoughts_layout.addLayout(thought_context_layout)

    self.enable_mood_system_check = self._create_toggle(
        "기분 기능 사용",
        key="settings.behavior.display.mood_system",
    )
    self.enable_mood_system_check.toggled.connect(self._on_mood_system_toggle)
    thoughts_layout.addWidget(self.enable_mood_system_check)

    mood_profile_layout = QFormLayout()
    mood_profile_layout.setContentsMargins(0, 0, 0, 0)
    mood_profile_layout.setSpacing(8)
    self.mood_personality_profile_combo = QComboBox()
    for index, (value, label_key, fallback) in enumerate(
        (
            ("calm", "settings.behavior.display.mood_profile.calm", "차분함"),
            ("balanced", "settings.behavior.display.mood_profile.balanced", "균형형"),
            ("expressive", "settings.behavior.display.mood_profile.expressive", "감정 풍부형"),
        )
    ):
        self.mood_personality_profile_combo.addItem(
            self._translated_text(label_key, fallback), value
        )
        self._bind_combo_item(
            self.mood_personality_profile_combo, index, label_key, fallback
        )
    self.mood_personality_profile_combo.currentIndexChanged.connect(
        self._on_setting_changed
    )
    self._add_form_row(
        mood_profile_layout,
        "settings.behavior.display.mood_profile.label",
        "기분 성향:",
        self.mood_personality_profile_combo,
    )
    thoughts_layout.addLayout(mood_profile_layout)

    context_group = QGroupBox("대화 컨텍스트")
    self._bind_group_title(context_group, "settings.behavior.context.title", "대화 컨텍스트")
    context_layout = QVBoxLayout(context_group)
    context_layout.setSpacing(8)
    self.include_input_device_context_check = self._create_toggle(
        "대화 기기 정보 전달", key="settings.behavior.context.input_device",
    )
    self.include_input_device_context_check.toggled.connect(self._on_setting_changed)
    context_layout.addWidget(self.include_input_device_context_check)
    context_layout.addWidget(self._build_hint_label(
        "메시지를 보낸 기기가 PC인지 모바일 앱인지 AI에 알립니다. PC·모바일 대화에 공통 적용됩니다.",
        key="settings.behavior.context.input_device_hint",
    ))
    context_layout.addWidget(self._build_hint_label(
        "저장 후 새로 시작하는 응답부터 적용됩니다.",
        key="settings.behavior.context.saved_hint",
    ))
    return group_page(reactions, thoughts, context_group)


def _goals_notes(self):
    self.enable_ene_goals_check = self._create_toggle(
        "에네 목표 사용",
        key="settings.behavior.display.ene_goals",
    )
    self.enable_ene_goals_check.toggled.connect(self._on_ene_goals_toggle)
    goals_group = self._create_ene_goals_group()
    goals_group.layout().insertWidget(0, self.enable_ene_goals_check)

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
    return group_page(goals_group, note_group)


def _detection_records(self):
    away_group = QGroupBox("자리 비움/유휴 감지")
    self._bind_group_title(away_group, "settings.behavior.away.title", "자리 비움/유휴 감지")
    away_layout = QFormLayout(away_group)
    away_layout.setSpacing(8)
    away_layout.setContentsMargins(10, 15, 10, 10)

    self.enable_away_nudge_check = self._create_toggle(
        "자리 비움 때 채팅에 안부 남기기",
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


    observation_group = QGroupBox()
    self._bind_group_title(observation_group, "settings.behavior.observation.title", "화면을 보고 먼저 말 걸기")
    observation_layout = QFormLayout(observation_group)
    self.observation_sample_seconds_spin = QSpinBox()
    self.observation_request_seconds_spin = QSpinBox()
    for spin, key, label in (
        (self.observation_sample_seconds_spin, "sample", "화면 변화 확인 간격"),
        (self.observation_request_seconds_spin, "request", "모델 호출 최소 간격"),
    ):
        spin.setRange(1, MAX_INTERVAL_SECONDS)
        self._bind_suffix(spin, "settings.behavior.observation.seconds", " 초")
        self._add_form_row(observation_layout, f"settings.behavior.observation.{key}", label, spin)
    observation_layout.addRow(self._build_hint_label(
        "PC 창과 휴대폰 카메라에 함께 적용합니다. 기본값은 화면 확인 30초, 모델 호출 5분입니다.",
        key="settings.behavior.observation.hint",
    ))

    visual_group = QGroupBox()
    self._bind_group_title(visual_group, "settings.behavior.observation.context_title", "질문할 때 본 장면")
    visual_layout = QFormLayout(visual_group)
    self.visual_context_turns_spin = QSpinBox()
    self.visual_context_turns_spin.setRange(0, 20)
    self._bind_suffix(self.visual_context_turns_spin, "settings.behavior.observation.turns", " 턴")
    self._register_text_binding(self.visual_context_turns_spin.setSpecialValueText,
                                "settings.behavior.observation.context_off", "다음 대화에 포함 안 함")
    self._add_form_row(visual_layout, "settings.behavior.observation.context_turns",
                       "화면 정보 유지 턴 수", self.visual_context_turns_spin)
    visual_layout.addRow(self._build_hint_label(
        "기본 5턴. 화면 없이 질문해도 한 턴으로 셉니다. 본 장면 버튼에서는 해당 답변의 요약을 볼 수 있습니다.",
        key="settings.behavior.observation.context_hint"))

    life_record_group = QGroupBox("생활 기록")
    self._bind_group_title(
        life_record_group,
        "settings.behavior.life_records.title",
        "생활 기록",
    )
    life_record_layout = QFormLayout(life_record_group)
    life_record_layout.setSpacing(8)
    life_record_layout.setContentsMargins(10, 15, 10, 10)

    self.enable_life_records_check = self._create_toggle(
        "생활 기록 사용",
        key="settings.behavior.life_records.enable",
    )
    self.enable_life_records_check.setMinimumHeight(44)
    self._register_text_binding(
        self.enable_life_records_check.setAccessibleName,
        "settings.behavior.life_records.enable",
        "생활 기록 사용",
    )
    self.enable_life_records_check.toggled.connect(self._on_life_records_toggle)
    life_record_layout.addRow(self.enable_life_records_check)

    self.life_record_min_inactive_minutes_spin = QSpinBox()
    self.life_record_min_inactive_minutes_spin.setRange(1, 525600)
    self.life_record_min_inactive_minutes_spin.setMinimumHeight(44)
    self._bind_suffix(
        self.life_record_min_inactive_minutes_spin,
        "settings.behavior.life_records.min_inactive.suffix",
        " 분",
    )
    self._register_text_binding(
        self.life_record_min_inactive_minutes_spin.setAccessibleName,
        "settings.behavior.life_records.min_inactive.label",
        "최소 비활성 시간",
    )
    self.life_record_min_inactive_minutes_spin.valueChanged.connect(self._on_setting_changed)
    self._life_record_min_inactive_label = self._add_form_row(
        life_record_layout,
        "settings.behavior.life_records.min_inactive.label",
        "최소 비활성 시간:",
        self.life_record_min_inactive_minutes_spin,
    )
    life_record_layout.addRow(
        self._build_hint_label(
            "이 시간 이상 비활성 상태였을 때만 다음 첫 대화에서 생활 기록을 만듭니다.",
            key="settings.behavior.life_records.hint",
        )
    )

    debug_group = QGroupBox("디버그")
    self._bind_group_title(debug_group, "settings.behavior.debug.title", "디버그")
    debug_layout = QVBoxLayout(debug_group)
    self.debug_mode_check = self._create_toggle(
        "디버그 로그 저장", key="settings.behavior.debug.enable",
    )
    self.debug_mode_check.toggled.connect(self._on_setting_changed)
    debug_layout.addWidget(self.debug_mode_check)
    debug_layout.addWidget(self._build_hint_label(
        "저장 후 적용됩니다. ENE 실행 폴더의 log에 프롬프트 전문, 모델, 생성 시간, 오류 원문을 기록합니다. "
        "대화와 개인정보가 포함될 수 있으므로 공유 전에 내용을 확인하세요.",
        key="settings.behavior.debug.hint",
    ))
    self.diagnostic_share_button = QPushButton()
    self._bind_widget_text(self.diagnostic_share_button, "settings.behavior.debug.share", "진단 공유본 만들기")
    self.diagnostic_share_button.clicked.connect(lambda: open_diagnostic_share(self))
    debug_layout.addWidget(self.diagnostic_share_button)
    return group_page(away_group, observation_group, visual_group, life_record_group, debug_group)
