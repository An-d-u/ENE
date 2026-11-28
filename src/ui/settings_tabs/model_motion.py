"""모델의 응답, 대기 및 마우스 상호작용 설정."""

from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ...ai.prompt import get_available_emotions
from ...core.response_motion import emotion_motion_ids
from .section_navigation import group_page, section_group


def _add_motion_strength(dialog, layout, key, fallback):
    spin = QSpinBox()
    spin.setRange(0, 200)
    spin.setSingleStep(5)
    spin.setSuffix("%")
    spin.valueChanged.connect(dialog._on_setting_changed)
    dialog._add_form_row(layout, "settings.behavior.response_motion." + key, fallback, spin)
    return spin


def _add_response_motion_controls(dialog, form):
    prefix = "settings.behavior.response_motion."

    def choice(layout, label, fallback, items):
        combo = QComboBox()
        for value, name in items:
            combo.addItem(name, value)
            dialog._bind_combo_item(combo, combo.count() - 1, prefix + value, name)
        dialog._add_form_row(layout, prefix + label, fallback, combo)
        combo.currentIndexChanged.connect(dialog._on_setting_changed)
        return combo

    dialog.response_motion_mode_combo = choice(form, "mode", "움직임 방식", [
        ("classic", "기존 ENE"), ("accent", "포즈 중심"),
    ])
    dialog.emotion_motion_preset_combo = choice(form, "preset", "동작 프리셋", [
        ("standard", "기본"), ("restrained", "절제형"), ("lively", "발랄형"), ("gentle", "부드러운형"),
    ])
    dialog.emotion_motion_check = dialog._create_toggle("표정에 감정 동작 더하기", key=prefix + "enable")
    form.addRow(dialog.emotion_motion_check)
    details = dialog.response_motion_details = QWidget()
    inner = QFormLayout(details)
    inner.setContentsMargins(0, 0, 0, 0)
    expressions = QHBoxLayout()
    dialog.motion_expression_combo = QComboBox()
    dialog._bind_placeholder(dialog.motion_expression_combo, prefix + "no_expressions", "표정 파일 없음")
    expressions.addWidget(dialog.motion_expression_combo, 1)
    dialog.refresh_motion_expressions_button = QPushButton()
    dialog._bind_widget_text(dialog.refresh_motion_expressions_button, "settings.common.refresh", "새로고침")
    expressions.addWidget(dialog.refresh_motion_expressions_button)
    dialog._add_form_row(inner, prefix + "expression", "모델 표정", expressions).setBuddy(dialog.motion_expression_combo)
    target = dialog.expression_motion_target_combo = QComboBox()
    target.addItem("", "auto")
    target.addItem("", "none")
    dialog._bind_combo_item(target, 1, prefix + "expression_only", "표정만 사용")
    for motion_id in emotion_motion_ids():
        target.addItem(motion_id, motion_id)
        dialog._bind_combo_item(target, target.count() - 1, prefix + "names." + motion_id, motion_id)
    dialog._add_form_row(inner, prefix + "target", "연결할 감정 동작", target)
    dialog.motion_expression_combo.currentIndexChanged.connect(dialog._show_expression_motion_target)
    target.currentIndexChanged.connect(dialog._on_expression_motion_target_changed)
    dialog.refresh_motion_expressions_button.clicked.connect(dialog._refresh_motion_expressions)
    dialog.refresh_motion_expressions_button.clicked.connect(dialog._on_setting_changed)
    dialog.emotion_motion_head_spin = _add_motion_strength(dialog, inner, "head", "감정 동작 고개 강도")
    dialog.emotion_motion_body_spin = _add_motion_strength(dialog, inner, "body", "감정 동작 몸통 강도")
    overlap = dialog.emotion_overlap_spin = QSpinBox()
    overlap.setRange(0, 100)
    overlap.setSuffix("%")
    dialog._bind_tooltip(overlap, prefix + "overlap_hint",
                         "응답 제스처와 겹치는 동안 남겨 둘 감정 동작의 비율입니다. 기본값은 28%입니다.")
    overlap.valueChanged.connect(dialog._on_emotion_overlap_changed)
    dialog._add_form_row(inner, prefix + "overlap", "이 모델의 제스처 중 감정 동작 유지율", overlap)
    form.addRow(details)

    def refresh():
        styled = dialog.response_motion_mode_combo.currentData() != "classic"
        form.setRowVisible(dialog.emotion_motion_preset_combo, styled)
        dialog.emotion_motion_check.setVisible(styled)
        details.setVisible(styled and dialog.emotion_motion_check.isChecked())

    dialog.response_motion_mode_combo.currentIndexChanged.connect(refresh)
    dialog.emotion_motion_check.toggled.connect(refresh)
    dialog.emotion_motion_check.toggled.connect(dialog._on_setting_changed)
    refresh()


def response_motion_page(self):
    expression, form = section_group(self, "expression", "표정과 감정 동작", QFormLayout)
    _add_response_motion_controls(self, form)

    gestures, gesture_layout = section_group(self, "gestures", "응답 제스처", QFormLayout)
    self.enable_synthetic_gestures_check = self._create_toggle(
        "응답 제스처 사용",
        key="settings.behavior.gesture.enable",
    )
    self.enable_synthetic_gestures_check.toggled.connect(self._on_setting_changed)
    gesture_layout.addRow(self.enable_synthetic_gestures_check)

    self.synthetic_gesture_scale_spin = QDoubleSpinBox()
    self.synthetic_gesture_scale_spin.setRange(0.5, 3.0)
    self.synthetic_gesture_scale_spin.setSingleStep(0.1)
    self.synthetic_gesture_scale_spin.setDecimals(2)
    self.synthetic_gesture_scale_spin.setSuffix("x")
    self.synthetic_gesture_scale_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        gesture_layout,
        "settings.behavior.gesture.scale",
        "동작 배율:",
        self.synthetic_gesture_scale_spin,
    )
    self.response_gesture_head_spin = _add_motion_strength(self, gesture_layout, "gesture_head", "응답 제스처 고개 강도")
    self.response_gesture_body_spin = _add_motion_strength(self, gesture_layout, "gesture_body", "응답 제스처 몸통 강도")

    self.response_gesture_repeat_spin = QSpinBox()
    self.response_gesture_repeat_spin.setRange(0, 3)
    self._bind_tooltip(
        self.response_gesture_repeat_spin, "settings.behavior.response_motion.repeat_hint",
        "0이면 첫 동작만 재생합니다. 음성이 계속되면 첫 동작 강도의 100%, 90%, 80%로 차례로 반복합니다.",
    )
    self.response_gesture_repeat_spin.valueChanged.connect(self._on_gesture_repeat_changed)
    self._add_form_row(gesture_layout, "settings.behavior.response_motion.repeat_limit",
                       "이 모델의 최대 추가 반복 횟수", self.response_gesture_repeat_spin)

    def show_gesture_strengths():
        checked = self.enable_synthetic_gestures_check.isChecked()
        gesture_layout.setRowVisible(self.response_gesture_head_spin, checked)
        gesture_layout.setRowVisible(self.response_gesture_body_spin, checked)
        gesture_layout.setRowVisible(self.response_gesture_repeat_spin,
                                     checked and self.response_motion_mode_combo.currentData() == "accent")

    self.enable_synthetic_gestures_check.toggled.connect(show_gesture_strengths)
    self.response_motion_mode_combo.currentIndexChanged.connect(show_gesture_strengths)
    show_gesture_strengths()
    return group_page(expression, gestures)


def idle_motion_page(self):
    idle, idle_layout = section_group(self, "idle", "대기 모션", QFormLayout)
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

    gestures, gesture_layout = section_group(self, "idle_gestures", "유휴 제스처", QFormLayout)
    self.enable_idle_synthetic_gestures_check = self._create_toggle(
        "유휴 제스처 사용",
        key="settings.behavior.gesture.idle_enable",
    )
    self.enable_idle_synthetic_gestures_check.toggled.connect(self._on_setting_changed)
    gesture_layout.addRow(self.enable_idle_synthetic_gestures_check)

    self.idle_synthetic_gesture_frequency_combo = QComboBox()
    for key, fallback, value in [
        ("settings.behavior.gesture.idle_frequency.low", "낮음", "low"),
        ("settings.behavior.gesture.idle_frequency.normal", "보통", "normal"),
        ("settings.behavior.gesture.idle_frequency.high", "높음", "high"),
    ]:
        self.idle_synthetic_gesture_frequency_combo.addItem(self._translated_text(key, fallback), value)
        self._bind_combo_item(
            self.idle_synthetic_gesture_frequency_combo,
            self.idle_synthetic_gesture_frequency_combo.count() - 1,
            key,
            fallback,
        )
    self.idle_synthetic_gesture_frequency_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(
        gesture_layout,
        "settings.behavior.gesture.idle_frequency.label",
        "유휴 제스처 빈도:",
        self.idle_synthetic_gesture_frequency_combo,
    )
    gesture_layout.addRow(
        self._build_hint_label(
            "아직 시험 기능입니다. 모델에 따라 어색하거나 제대로 작동하지 않을 수 있습니다.",
            key="settings.behavior.gesture.hint",
        )
    )

    expressive, expressive_layout = section_group(self, "expressive", "생동감 모션", QFormLayout)
    self.expressive_motion_check = self._create_toggle(
        "생동감 모션 사용",
        key="settings.behavior.idle.expressive_enable",
    )
    self.expressive_motion_check.toggled.connect(self._on_setting_changed)
    expressive_layout.addRow(self.expressive_motion_check)

    self.expressive_pose_transitions_check = self._create_toggle(
        "포즈/대기 전환 사용",
        key="settings.behavior.idle.expressive_pose_transitions_enable",
    )
    self.expressive_pose_transitions_check.toggled.connect(self._on_setting_changed)
    expressive_layout.addRow(self.expressive_pose_transitions_check)

    self.expressive_motion_strength_spin = QDoubleSpinBox()
    self.expressive_motion_strength_spin.setRange(0.2, 2.5)
    self.expressive_motion_strength_spin.setSingleStep(0.1)
    self.expressive_motion_strength_spin.setDecimals(2)
    self.expressive_motion_strength_spin.setSuffix("x")
    self.expressive_motion_strength_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        expressive_layout,
        "settings.behavior.idle.expressive_strength",
        "생동감 모션 강도:",
        self.expressive_motion_strength_spin,
    )

    self.expressive_motion_speed_spin = QDoubleSpinBox()
    self.expressive_motion_speed_spin.setRange(0.4, 2.0)
    self.expressive_motion_speed_spin.setSingleStep(0.1)
    self.expressive_motion_speed_spin.setDecimals(2)
    self.expressive_motion_speed_spin.setSuffix("x")
    self.expressive_motion_speed_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        expressive_layout,
        "settings.behavior.idle.expressive_speed",
        "생동감 모션 속도:",
        self.expressive_motion_speed_spin,
    )

    self.expressive_motion_speech_boost_spin = QDoubleSpinBox()
    self.expressive_motion_speech_boost_spin.setRange(0.0, 2.5)
    self.expressive_motion_speech_boost_spin.setSingleStep(0.1)
    self.expressive_motion_speech_boost_spin.setDecimals(2)
    self.expressive_motion_speech_boost_spin.setSuffix("x")
    self.expressive_motion_speech_boost_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(
        expressive_layout,
        "settings.behavior.idle.expressive_speech_boost",
        "말할 때 반응:",
        self.expressive_motion_speech_boost_spin,
    )
    expressive_layout.addRow(
        self._build_hint_label(
            "캐릭터에 계속 작은 생동감을 더하는 시험 기능입니다. 모델에 따라 강하거나 약하게 보일 수 있습니다.",
            key="settings.behavior.idle.expressive_hint",
        )
    )
    return group_page(idle, gestures, expressive)


def touch_gaze_page(self):
    tracking, tracking_layout = section_group(self, "tracking", "마우스 추적", QVBoxLayout)
    self.mouse_tracking_check = self._create_toggle(
        "마우스 트래킹 활성화",
        key="settings.behavior.display.mouse_tracking",
    )
    self.mouse_tracking_check.toggled.connect(self._on_setting_changed)
    tracking_layout.addWidget(self.mouse_tracking_check)

    pat, pat_layout = section_group(self, "head_pat", "머리 쓰다듬기", QFormLayout)
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
    return group_page(tracking, pat)
