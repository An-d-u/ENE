"""
Settings dialog for ENE.
Provides live preview without immediate persistence.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..ai.prompt import get_available_emotions
from ..ai.llm_provider import LLMFormat, get_llm_provider_catalog


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal(dict)
    settings_preview = pyqtSignal(dict)
    settings_cancelled = pyqtSignal()

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self._original_settings = current_settings.copy()
        self._loading = False

        self.setWindowTitle("ENE 설정")
        self.setMinimumWidth(520)
        self.setMinimumHeight(640)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(False)

        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._create_window_tab(), "창 설정")
        tabs.addTab(self._create_model_tab(), "모델 설정")
        tabs.addTab(self._create_llm_tab(), "LLM 설정")
        tabs.addTab(self._create_behavior_tab(), "동작 설정")
        layout.addWidget(tabs)

        button_layout = QHBoxLayout()
        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self._cancel_settings)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _create_window_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        position_group = QGroupBox("창 위치")
        position_layout = QFormLayout()

        self.window_x_spin = QSpinBox()
        self.window_x_spin.setRange(-9999, 9999)
        self.window_x_spin.setSuffix(" px")
        self.window_x_spin.valueChanged.connect(self._on_setting_changed)
        position_layout.addRow("X 좌표:", self.window_x_spin)

        self.window_y_spin = QSpinBox()
        self.window_y_spin.setRange(-9999, 9999)
        self.window_y_spin.setSuffix(" px")
        self.window_y_spin.valueChanged.connect(self._on_setting_changed)
        position_layout.addRow("Y 좌표:", self.window_y_spin)
        position_group.setLayout(position_layout)
        layout.addWidget(position_group)

        size_group = QGroupBox("창 크기")
        size_layout = QFormLayout()

        self.window_width_spin = QSpinBox()
        self.window_width_spin.setRange(200, 3840)
        self.window_width_spin.setSuffix(" px")
        self.window_width_spin.valueChanged.connect(self._on_setting_changed)
        size_layout.addRow("너비:", self.window_width_spin)

        self.window_height_spin = QSpinBox()
        self.window_height_spin.setRange(200, 2160)
        self.window_height_spin.setSuffix(" px")
        self.window_height_spin.valueChanged.connect(self._on_setting_changed)
        size_layout.addRow("높이:", self.window_height_spin)
        size_group.setLayout(size_layout)
        layout.addWidget(size_group)

        preset_layout = QHBoxLayout()
        center_btn = QPushButton("화면 중앙")
        center_btn.clicked.connect(self._preset_center)
        preset_layout.addWidget(center_btn)

        br_btn = QPushButton("우측 하단")
        br_btn.clicked.connect(self._preset_bottom_right)
        preset_layout.addWidget(br_btn)

        bl_btn = QPushButton("좌측 하단")
        bl_btn.clicked.connect(self._preset_bottom_left)
        preset_layout.addWidget(bl_btn)
        layout.addLayout(preset_layout)

        layout.addStretch()
        return widget

    def _create_model_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        scale_group = QGroupBox("모델 크기")
        scale_layout = QVBoxLayout()
        scale_form = QFormLayout()
        self.model_scale_spin = QDoubleSpinBox()
        self.model_scale_spin.setRange(0.1, 2.0)
        self.model_scale_spin.setSingleStep(0.05)
        self.model_scale_spin.setDecimals(2)
        self.model_scale_spin.setSuffix("x")
        self.model_scale_spin.valueChanged.connect(self._on_setting_changed)
        scale_form.addRow("스케일:", self.model_scale_spin)
        scale_layout.addLayout(scale_form)

        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 200)
        self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.scale_slider.setTickInterval(10)
        scale_layout.addWidget(self.scale_slider)
        self.model_scale_spin.valueChanged.connect(lambda v: self.scale_slider.setValue(int(v * 100)))
        self.scale_slider.valueChanged.connect(lambda v: self.model_scale_spin.setValue(v / 100.0))
        scale_group.setLayout(scale_layout)
        layout.addWidget(scale_group)

        x_group = QGroupBox("모델 X 위치 (좌우)")
        x_layout = QVBoxLayout()
        x_info = QHBoxLayout()
        x_info.addWidget(QLabel("좌측 ↓ ↓"))
        x_info.addStretch()
        self.model_x_value_label = QLabel("50%")
        self.model_x_value_label.setStyleSheet("font-weight: bold;")
        x_info.addWidget(self.model_x_value_label)
        x_info.addStretch()
        x_info.addWidget(QLabel("우측 ↓ ↓"))
        x_layout.addLayout(x_info)
        self.model_x_slider = QSlider(Qt.Orientation.Horizontal)
        self.model_x_slider.setRange(-100, 200)
        self.model_x_slider.valueChanged.connect(lambda v: self.model_x_value_label.setText(f"{v}%"))
        self.model_x_slider.valueChanged.connect(self._on_setting_changed)
        x_layout.addWidget(self.model_x_slider)
        x_group.setLayout(x_layout)
        layout.addWidget(x_group)

        y_group = QGroupBox("모델 Y 위치 (상하)")
        y_layout = QVBoxLayout()
        y_info = QHBoxLayout()
        y_info.addWidget(QLabel("상단 ↓ ↓"))
        y_info.addStretch()
        self.model_y_value_label = QLabel("50%")
        self.model_y_value_label.setStyleSheet("font-weight: bold;")
        y_info.addWidget(self.model_y_value_label)
        y_info.addStretch()
        y_info.addWidget(QLabel("하단 ↓ ↓"))
        y_layout.addLayout(y_info)
        self.model_y_slider = QSlider(Qt.Orientation.Horizontal)
        self.model_y_slider.setRange(-100, 200)
        self.model_y_slider.valueChanged.connect(lambda v: self.model_y_value_label.setText(f"{v}%"))
        self.model_y_slider.valueChanged.connect(self._on_setting_changed)
        y_layout.addWidget(self.model_y_slider)
        y_group.setLayout(y_layout)
        layout.addWidget(y_group)

        preset_layout = QHBoxLayout()
        center_btn = QPushButton("중앙")
        center_btn.clicked.connect(lambda: self._set_model_position(50, 50))
        preset_layout.addWidget(center_btn)
        left_btn = QPushButton("좌측")
        left_btn.clicked.connect(lambda: self._set_model_position(25, 50))
        preset_layout.addWidget(left_btn)
        right_btn = QPushButton("우측")
        right_btn.clicked.connect(lambda: self._set_model_position(75, 50))
        preset_layout.addWidget(right_btn)
        layout.addLayout(preset_layout)

        layout.addStretch()
        return widget

    def _create_llm_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        llm_group = QGroupBox("LLM 설정")
        llm_form = QFormLayout(llm_group)

        self.llm_provider_combo = QComboBox()
        self._provider_values = []
        catalog = get_llm_provider_catalog()
        for provider in sorted(catalog.keys()):
            meta = catalog[provider]
            self.llm_provider_combo.addItem(f"{meta.display_name} ({provider})", provider)
            self._provider_values.append(provider)
        self._llm_api_keys = {}
        self._llm_models = {}
        self._llm_model_params = {}
        self._active_model_key_by_provider = {}
        self.llm_provider_combo.currentIndexChanged.connect(self._on_llm_provider_changed)
        llm_form.addRow("공급자:", self.llm_provider_combo)

        self.llm_api_key_edit = QLineEdit()
        self.llm_api_key_edit.setPlaceholderText("선택한 공급자의 API 키")
        self.llm_api_key_edit.textChanged.connect(self._on_llm_api_key_changed)
        llm_form.addRow("API 키:", self.llm_api_key_edit)

        self.llm_model_edit = QLineEdit()
        self.llm_model_edit.setPlaceholderText("예: gemini-3-flash-preview, gpt-4o-mini")
        self.llm_model_edit.textChanged.connect(self._on_llm_model_changed)
        llm_form.addRow("모델:", self.llm_model_edit)

        self.llm_temperature_spin = QDoubleSpinBox()
        self.llm_temperature_spin.setRange(0.0, 2.0)
        self.llm_temperature_spin.setSingleStep(0.1)
        self.llm_temperature_spin.setDecimals(2)
        self.llm_temperature_spin.valueChanged.connect(self._on_llm_param_changed)
        llm_form.addRow("Temperature:", self.llm_temperature_spin)

        self.llm_top_p_spin = QDoubleSpinBox()
        self.llm_top_p_spin.setRange(0.0, 1.0)
        self.llm_top_p_spin.setSingleStep(0.05)
        self.llm_top_p_spin.setDecimals(2)
        self.llm_top_p_spin.valueChanged.connect(self._on_llm_param_changed)
        llm_form.addRow("Top P:", self.llm_top_p_spin)

        self.llm_max_tokens_spin = QSpinBox()
        self.llm_max_tokens_spin.setRange(0, 65536)
        self.llm_max_tokens_spin.setSpecialValueText("자동")
        self.llm_max_tokens_spin.valueChanged.connect(self._on_llm_param_changed)
        llm_form.addRow("Max Tokens:", self.llm_max_tokens_spin)

        self.custom_api_group = QGroupBox("Custom API")
        custom_form = QFormLayout(self.custom_api_group)

        self.custom_api_url_edit = QLineEdit()
        self.custom_api_url_edit.setPlaceholderText("예: https://api.example.com/v1/chat/completions")
        self.custom_api_url_edit.textChanged.connect(self._on_setting_changed)
        custom_form.addRow("URL:", self.custom_api_url_edit)

        self.custom_api_key_or_password_edit = QLineEdit()
        self.custom_api_key_or_password_edit.setPlaceholderText("키 또는 패스워드")
        self.custom_api_key_or_password_edit.textChanged.connect(self._on_setting_changed)
        custom_form.addRow("키/패스워드:", self.custom_api_key_or_password_edit)

        self.custom_api_request_model_edit = QLineEdit()
        self.custom_api_request_model_edit.setPlaceholderText("요청 모델명")
        self.custom_api_request_model_edit.textChanged.connect(self._on_setting_changed)
        custom_form.addRow("요청 모델:", self.custom_api_request_model_edit)

        self.custom_api_format_combo = QComboBox()
        custom_format_options = [
            ("OpenAI Compatible", LLMFormat.OPENAI_COMPATIBLE.value),
            ("OpenAI Response API", LLMFormat.OPENAI_RESPONSE_API.value),
            ("Anthropic Claude", LLMFormat.ANTHROPIC.value),
            ("Mistral", LLMFormat.MISTRAL.value),
            ("Google Cloud", LLMFormat.GOOGLE_CLOUD.value),
            ("Cohere", LLMFormat.COHERE.value),
        ]
        for label, value in custom_format_options:
            self.custom_api_format_combo.addItem(label, value)
        self.custom_api_format_combo.currentIndexChanged.connect(self._on_setting_changed)
        custom_form.addRow("포맷:", self.custom_api_format_combo)

        self.custom_api_group.setVisible(False)
        llm_form.addRow(self.custom_api_group)

        self.llm_restart_info = QLabel("주의: LLM 설정 변경은 앱 재시작 후 완전히 반영됩니다.")
        self.llm_restart_info.setWordWrap(True)
        llm_form.addRow(self.llm_restart_info)

        layout.addWidget(llm_group)
        layout.addStretch()
        return widget

    def _create_behavior_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.show_drag_bar_check = QCheckBox("드래그 바 표시")
        self.show_drag_bar_check.toggled.connect(self._on_setting_changed)
        drag_row = QHBoxLayout()
        drag_row.addWidget(self.show_drag_bar_check)

        self.show_recent_reroll_button_check = QCheckBox("최근 메시지 리롤 버튼 표시")
        self.show_recent_reroll_button_check.toggled.connect(self._on_setting_changed)
        drag_row.addWidget(self.show_recent_reroll_button_check)

        self.show_recent_edit_button_check = QCheckBox("최근 메시지 수정 버튼 표시")
        self.show_recent_edit_button_check.toggled.connect(self._on_setting_changed)
        drag_row.addWidget(self.show_recent_edit_button_check)

        self.show_manual_summary_button_check = QCheckBox("수동 요약 버튼 표시")
        self.show_manual_summary_button_check.toggled.connect(self._on_setting_changed)
        drag_row.addWidget(self.show_manual_summary_button_check)
        drag_row.addStretch()
        layout.addLayout(drag_row)

        self.mouse_tracking_check = QCheckBox("마우스 트래킹 활성화")
        self.mouse_tracking_check.toggled.connect(self._on_setting_changed)
        layout.addWidget(self.mouse_tracking_check)

        idle_group = QGroupBox("유휴 모션")
        idle_layout = QFormLayout(idle_group)
        self.idle_motion_check = QCheckBox("유휴 모션 활성화 (말하지 않을 때 자동 움직임)")
        self.idle_motion_check.toggled.connect(self._on_setting_changed)
        idle_layout.addRow(self.idle_motion_check)

        self.idle_motion_dynamic_check = QCheckBox("유휴 모션 다이나믹 모드")
        self.idle_motion_dynamic_check.toggled.connect(self._on_setting_changed)
        idle_layout.addRow(self.idle_motion_dynamic_check)

        self.idle_motion_strength_spin = QDoubleSpinBox()
        self.idle_motion_strength_spin.setRange(0.2, 2.0)
        self.idle_motion_strength_spin.setSingleStep(0.1)
        self.idle_motion_strength_spin.setDecimals(2)
        self.idle_motion_strength_spin.setSuffix("x")
        self.idle_motion_strength_spin.valueChanged.connect(self._on_setting_changed)
        idle_layout.addRow("유휴 모션 강도:", self.idle_motion_strength_spin)

        self.idle_motion_speed_spin = QDoubleSpinBox()
        self.idle_motion_speed_spin.setRange(0.5, 2.0)
        self.idle_motion_speed_spin.setSingleStep(0.1)
        self.idle_motion_speed_spin.setDecimals(2)
        self.idle_motion_speed_spin.setSuffix("x")
        self.idle_motion_speed_spin.valueChanged.connect(self._on_setting_changed)
        idle_layout.addRow("유휴 모션 속도:", self.idle_motion_speed_spin)
        layout.addWidget(idle_group)

        pat_group = QGroupBox("머리 쓰다듬기")
        pat_layout = QFormLayout(pat_group)
        self.head_pat_check = QCheckBox("머리 쓰다듬기 활성화")
        self.head_pat_check.toggled.connect(self._on_setting_changed)
        pat_layout.addRow(self.head_pat_check)

        self.head_pat_strength_spin = QDoubleSpinBox()
        self.head_pat_strength_spin.setRange(0.5, 2.5)
        self.head_pat_strength_spin.setSingleStep(0.1)
        self.head_pat_strength_spin.setDecimals(2)
        self.head_pat_strength_spin.setSuffix("x")
        self.head_pat_strength_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("쓰다듬기 강도:", self.head_pat_strength_spin)

        self.head_pat_fade_in_spin = QSpinBox()
        self.head_pat_fade_in_spin.setRange(50, 1000)
        self.head_pat_fade_in_spin.setSuffix(" ms")
        self.head_pat_fade_in_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("시작 페이드:", self.head_pat_fade_in_spin)

        self.head_pat_fade_out_spin = QSpinBox()
        self.head_pat_fade_out_spin.setRange(50, 1200)
        self.head_pat_fade_out_spin.setSuffix(" ms")
        self.head_pat_fade_out_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("종료 페이드:", self.head_pat_fade_out_spin)

        self.head_pat_active_emotion_combo = QComboBox()
        self._emotion_options = get_available_emotions()
        if "eyeclose" not in self._emotion_options:
            self._emotion_options.append("eyeclose")
        self.head_pat_active_emotion_combo.addItems(self._emotion_options)
        self.head_pat_active_emotion_combo.currentTextChanged.connect(self._on_setting_changed)
        pat_layout.addRow("쓰다듬기 중 감정(기본):", self.head_pat_active_emotion_combo)

        self.head_pat_active_emotion_custom_edit = QLineEdit()
        self.head_pat_active_emotion_custom_edit.setPlaceholderText("커스텀 감정 (텍스트 우선)")
        self.head_pat_active_emotion_custom_edit.textChanged.connect(self._on_setting_changed)
        pat_layout.addRow("쓰다듬기 중 감정(커스텀):", self.head_pat_active_emotion_custom_edit)

        self.head_pat_end_emotion_combo = QComboBox()
        self.head_pat_end_emotion_combo.addItems(self._emotion_options)
        self.head_pat_end_emotion_combo.currentTextChanged.connect(self._on_setting_changed)
        pat_layout.addRow("종료 감정(기본):", self.head_pat_end_emotion_combo)

        self.head_pat_end_emotion_custom_edit = QLineEdit()
        self.head_pat_end_emotion_custom_edit.setPlaceholderText("커스텀 감정 (텍스트 우선)")
        self.head_pat_end_emotion_custom_edit.textChanged.connect(self._on_setting_changed)
        pat_layout.addRow("종료 감정(커스텀):", self.head_pat_end_emotion_custom_edit)

        self.head_pat_end_emotion_duration_spin = QSpinBox()
        self.head_pat_end_emotion_duration_spin.setRange(1, 30)
        self.head_pat_end_emotion_duration_spin.setSuffix(" s")
        self.head_pat_end_emotion_duration_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("감정 유지 시간:", self.head_pat_end_emotion_duration_spin)
        layout.addWidget(pat_group)

        away_group = QGroupBox("자리 비움/유휴 감지")
        away_layout = QFormLayout(away_group)

        self.enable_away_nudge_check = QCheckBox("유휴 감지 자동 말걸기 활성화")
        self.enable_away_nudge_check.toggled.connect(self._on_setting_changed)
        away_layout.addRow(self.enable_away_nudge_check)

        self.away_idle_minutes_spin = QSpinBox()
        self.away_idle_minutes_spin.setRange(5, 240)
        self.away_idle_minutes_spin.setSuffix(" 분")
        self.away_idle_minutes_spin.valueChanged.connect(self._on_setting_changed)
        away_layout.addRow("유휴 시간:", self.away_idle_minutes_spin)

        self.away_diff_threshold_spin = QDoubleSpinBox()
        self.away_diff_threshold_spin.setRange(1.0, 15.0)
        self.away_diff_threshold_spin.setSingleStep(0.5)
        self.away_diff_threshold_spin.setDecimals(1)
        self.away_diff_threshold_spin.setSuffix(" %")
        self.away_diff_threshold_spin.valueChanged.connect(self._on_setting_changed)
        away_layout.addRow("화면 차이 민감도:", self.away_diff_threshold_spin)

        self.away_retry_limit_spin = QSpinBox()
        self.away_retry_limit_spin.setRange(0, 20)
        self.away_retry_limit_spin.setSuffix(" 회")
        self.away_retry_limit_spin.valueChanged.connect(self._on_setting_changed)
        away_layout.addRow("추가 재실행 횟수:", self.away_retry_limit_spin)

        layout.addWidget(away_group)

        layout.addStretch()
        return widget

    def _on_llm_provider_changed(self, *_):
        provider = str(self.llm_provider_combo.currentData() or "gemini")

        self._loading = True
        try:
            self.llm_api_key_edit.setText(str(self._llm_api_keys.get(provider, "")))
            model_text = str(self._llm_models.get(provider, ""))
            self.llm_model_edit.setText(model_text)
            self._active_model_key_by_provider[provider] = self._model_param_key(model_text)
            self._apply_model_params_to_widgets(provider, model_text)
            self.custom_api_group.setVisible(provider == "custom_api")
        finally:
            self._loading = False

        self._on_setting_changed()

    def _on_llm_api_key_changed(self, text: str):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        self._llm_api_keys[provider] = text
        self._on_setting_changed()

    def _on_llm_model_changed(self, text: str):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        old_key = self._active_model_key_by_provider.get(provider, "__default__")
        new_key = self._model_param_key(text)
        provider_params = self._llm_model_params.setdefault(provider, {})
        if new_key not in provider_params:
            provider_params[new_key] = dict(provider_params.get(old_key, self._default_model_params()))
        self._active_model_key_by_provider[provider] = new_key
        self._llm_models[provider] = text.strip()
        self._apply_model_params_to_widgets(provider, text)
        self._on_setting_changed()

    def _on_llm_param_changed(self, *_):
        if self._loading:
            return
        self._set_current_model_params()
        self._on_setting_changed()

    def _default_model_params(self) -> dict:
        return {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048}

    def _model_param_key(self, model_name: str) -> str:
        key = str(model_name or "").strip()
        return key if key else "__default__"

    def _normalize_model_params(self, params) -> dict:
        defaults = self._default_model_params()
        if not isinstance(params, dict):
            return defaults
        normalized = dict(defaults)
        try:
            normalized["temperature"] = max(0.0, min(2.0, float(params.get("temperature", defaults["temperature"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["top_p"] = max(0.0, min(1.0, float(params.get("top_p", defaults["top_p"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["max_tokens"] = max(0, int(params.get("max_tokens", defaults["max_tokens"])))
        except (TypeError, ValueError):
            pass
        return normalized

    def _get_model_params(self, provider: str, model_name: str) -> dict:
        store = self._llm_model_params.setdefault(provider, {})
        model_key = self._model_param_key(model_name)
        params = store.get(model_key)
        if not isinstance(params, dict):
            params = store.get("__default__")
        if not isinstance(params, dict):
            params = self._default_model_params()
        normalized = self._normalize_model_params(params)
        store[model_key] = dict(normalized)
        store.setdefault("__default__", dict(normalized))
        return normalized

    def _set_current_model_params(self):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        model_text = self.llm_model_edit.text().strip()
        model_key = self._model_param_key(model_text)
        self._active_model_key_by_provider[provider] = model_key
        provider_store = self._llm_model_params.setdefault(provider, {})
        provider_store[model_key] = self._normalize_model_params(
            {
                "temperature": self.llm_temperature_spin.value(),
                "top_p": self.llm_top_p_spin.value(),
                "max_tokens": self.llm_max_tokens_spin.value(),
            }
        )
        provider_store.setdefault("__default__", dict(provider_store[model_key]))

    def _apply_model_params_to_widgets(self, provider: str, model_name: str):
        params = self._get_model_params(provider, model_name)
        self.llm_temperature_spin.setValue(float(params["temperature"]))
        self.llm_top_p_spin.setValue(float(params["top_p"]))
        self.llm_max_tokens_spin.setValue(int(params["max_tokens"]))

    def _on_setting_changed(self):
        if self._loading:
            return
        self._preview_settings()

    def _load_values(self):
        self._loading = True
        try:
            self.window_x_spin.setValue(self._original_settings.get("window_x", 100))
            self.window_y_spin.setValue(self._original_settings.get("window_y", 100))
            self.window_width_spin.setValue(self._original_settings.get("window_width", 400))
            self.window_height_spin.setValue(self._original_settings.get("window_height", 600))

            self.show_drag_bar_check.setChecked(self._original_settings.get("show_drag_bar", True))
            self.show_recent_reroll_button_check.setChecked(
                self._original_settings.get("show_recent_reroll_button", True)
            )
            self.show_recent_edit_button_check.setChecked(
                self._original_settings.get("show_recent_edit_button", True)
            )
            self.show_manual_summary_button_check.setChecked(
                self._original_settings.get("show_manual_summary_button", True)
            )
            self.mouse_tracking_check.setChecked(self._original_settings.get("mouse_tracking_enabled", True))

            self.idle_motion_check.setChecked(self._original_settings.get("enable_idle_motion", True))
            self.idle_motion_dynamic_check.setChecked(self._original_settings.get("idle_motion_dynamic_mode", False))
            self.idle_motion_strength_spin.setValue(float(self._original_settings.get("idle_motion_strength", 1.0)))
            self.idle_motion_speed_spin.setValue(float(self._original_settings.get("idle_motion_speed", 1.0)))

            self.head_pat_check.setChecked(self._original_settings.get("enable_head_pat", True))
            self.head_pat_strength_spin.setValue(float(self._original_settings.get("head_pat_strength", 1.0)))
            self.head_pat_fade_in_spin.setValue(int(self._original_settings.get("head_pat_fade_in_ms", 180)))
            self.head_pat_fade_out_spin.setValue(int(self._original_settings.get("head_pat_fade_out_ms", 220)))

            active_default_emotion = str(
                self._original_settings.get("head_pat_active_emotion_default", "eyeclose")
            ).strip() or "eyeclose"
            if active_default_emotion not in self._emotion_options:
                active_default_emotion = "eyeclose"
            self.head_pat_active_emotion_combo.setCurrentText(active_default_emotion)
            self.head_pat_active_emotion_custom_edit.setText(
                str(self._original_settings.get("head_pat_active_emotion_custom", ""))
            )

            default_emotion = str(self._original_settings.get("head_pat_end_emotion_default", "shy")).strip() or "shy"
            if default_emotion not in self._emotion_options:
                default_emotion = "shy"
            self.head_pat_end_emotion_combo.setCurrentText(default_emotion)
            self.head_pat_end_emotion_custom_edit.setText(
                str(self._original_settings.get("head_pat_end_emotion_custom", ""))
            )
            self.head_pat_end_emotion_duration_spin.setValue(
                int(self._original_settings.get("head_pat_end_emotion_duration_sec", 5))
            )
            self.enable_away_nudge_check.setChecked(self._original_settings.get("enable_away_nudge", True))
            self.away_idle_minutes_spin.setValue(int(self._original_settings.get("away_idle_minutes", 60)))
            self.away_diff_threshold_spin.setValue(float(self._original_settings.get("away_diff_threshold_percent", 3.0)))
            self.away_retry_limit_spin.setValue(int(self._original_settings.get("away_additional_retry_limit", 0)))

            self.model_scale_spin.setValue(self._original_settings.get("model_scale", 1.0))
            self.model_x_slider.setValue(int(self._original_settings.get("model_x_percent", 50)))
            self.model_y_slider.setValue(int(self._original_settings.get("model_y_percent", 50)))

            llm_provider = str(self._original_settings.get("llm_provider", "gemini")).strip().lower()
            loaded_keys = self._original_settings.get("llm_api_keys", {})
            self._llm_api_keys = loaded_keys.copy() if isinstance(loaded_keys, dict) else {}
            for provider_name in self._provider_values:
                self._llm_api_keys.setdefault(provider_name, "")

            loaded_models = self._original_settings.get("llm_models", {})
            self._llm_models = loaded_models.copy() if isinstance(loaded_models, dict) else {}
            legacy_model = str(self._original_settings.get("llm_model", "gemini-3-flash-preview")).strip()
            for provider_name in self._provider_values:
                if provider_name not in self._llm_models:
                    self._llm_models[provider_name] = legacy_model if provider_name == "gemini" else ""
                self._active_model_key_by_provider[provider_name] = self._model_param_key(
                    self._llm_models.get(provider_name, "")
                )

            loaded_params = self._original_settings.get("llm_model_params", {})
            self._llm_model_params = {}
            if isinstance(loaded_params, dict):
                for provider_name, provider_params in loaded_params.items():
                    if isinstance(provider_params, dict):
                        mapped = {}
                        for model_name, params in provider_params.items():
                            mapped[str(model_name)] = self._normalize_model_params(params)
                        self._llm_model_params[str(provider_name)] = mapped
            for provider_name in self._provider_values:
                provider_store = self._llm_model_params.setdefault(provider_name, {})
                active_key = self._active_model_key_by_provider.get(provider_name, "__default__")
                if active_key not in provider_store:
                    provider_store[active_key] = self._default_model_params()
                provider_store.setdefault("__default__", dict(provider_store[active_key]))

            if llm_provider in self._provider_values:
                idx = self.llm_provider_combo.findData(llm_provider)
                if idx >= 0:
                    self.llm_provider_combo.setCurrentIndex(idx)
            selected_provider = str(self.llm_provider_combo.currentData() or "gemini")
            self.llm_model_edit.setText(str(self._llm_models.get(selected_provider, "")))
            self._apply_model_params_to_widgets(selected_provider, self.llm_model_edit.text())

            self.custom_api_url_edit.setText(str(self._original_settings.get("custom_api_url", "")))
            self.custom_api_key_or_password_edit.setText(
                str(self._original_settings.get("custom_api_key_or_password", ""))
            )
            self.custom_api_request_model_edit.setText(
                str(self._original_settings.get("custom_api_request_model", ""))
            )
            custom_api_format = str(self._original_settings.get("custom_api_format", LLMFormat.OPENAI_COMPATIBLE.value))
            format_index = self.custom_api_format_combo.findData(custom_api_format)
            if format_index >= 0:
                self.custom_api_format_combo.setCurrentIndex(format_index)

            self.llm_api_key_edit.setText(str(self._llm_api_keys.get(selected_provider, "")))
            self.custom_api_group.setVisible(selected_provider == "custom_api")
        finally:
            self._loading = False

    def update_position(self, x: int, y: int):
        self._loading = True
        try:
            self.window_x_spin.setValue(x)
            self.window_y_spin.setValue(y)
        finally:
            self._loading = False

    def _preset_center(self):
        screen = QApplication.primaryScreen().geometry()
        width = self.window_width_spin.value()
        height = self.window_height_spin.value()
        self.window_x_spin.setValue((screen.width() - width) // 2)
        self.window_y_spin.setValue((screen.height() - height) // 2)

    def _preset_bottom_right(self):
        screen = QApplication.primaryScreen().geometry()
        width = self.window_width_spin.value()
        height = self.window_height_spin.value()
        self.window_x_spin.setValue(screen.width() - width - 50)
        self.window_y_spin.setValue(screen.height() - height - 50)

    def _preset_bottom_left(self):
        screen = QApplication.primaryScreen().geometry()
        height = self.window_height_spin.value()
        self.window_x_spin.setValue(50)
        self.window_y_spin.setValue(screen.height() - height - 50)

    def _set_model_position(self, x_percent, y_percent):
        self.model_x_slider.setValue(int(x_percent))
        self.model_y_slider.setValue(int(y_percent))

    def _get_current_values(self):
        current_provider = str(self.llm_provider_combo.currentData() or "gemini")
        self._llm_api_keys[current_provider] = self.llm_api_key_edit.text()
        self._llm_models[current_provider] = self.llm_model_edit.text().strip()
        self._set_current_model_params()

        active_custom_emotion = self.head_pat_active_emotion_custom_edit.text().strip()
        active_default_emotion = self.head_pat_active_emotion_combo.currentText().strip() or "eyeclose"
        resolved_active_emotion = active_custom_emotion if active_custom_emotion else active_default_emotion

        custom_emotion = self.head_pat_end_emotion_custom_edit.text().strip()
        default_emotion = self.head_pat_end_emotion_combo.currentText().strip() or "shy"
        resolved_emotion = custom_emotion if custom_emotion else default_emotion

        if not resolved_active_emotion:
            resolved_active_emotion = "eyeclose"
        if not resolved_emotion:
            resolved_emotion = "shy"

        return {
            "window_x": self.window_x_spin.value(),
            "window_y": self.window_y_spin.value(),
            "window_width": self.window_width_spin.value(),
            "window_height": self.window_height_spin.value(),
            "show_drag_bar": self.show_drag_bar_check.isChecked(),
            "show_recent_reroll_button": self.show_recent_reroll_button_check.isChecked(),
            "show_recent_edit_button": self.show_recent_edit_button_check.isChecked(),
            "show_manual_summary_button": self.show_manual_summary_button_check.isChecked(),
            "mouse_tracking_enabled": self.mouse_tracking_check.isChecked(),
            "enable_idle_motion": self.idle_motion_check.isChecked(),
            "idle_motion_dynamic_mode": self.idle_motion_dynamic_check.isChecked(),
            "idle_motion_strength": self.idle_motion_strength_spin.value(),
            "idle_motion_speed": self.idle_motion_speed_spin.value(),
            "enable_head_pat": self.head_pat_check.isChecked(),
            "head_pat_strength": self.head_pat_strength_spin.value(),
            "head_pat_fade_in_ms": self.head_pat_fade_in_spin.value(),
            "head_pat_fade_out_ms": self.head_pat_fade_out_spin.value(),
            "head_pat_active_emotion_default": active_default_emotion,
            "head_pat_active_emotion_custom": active_custom_emotion,
            "head_pat_active_emotion": resolved_active_emotion,
            "head_pat_end_emotion_default": default_emotion,
            "head_pat_end_emotion_custom": custom_emotion,
            "head_pat_end_emotion": resolved_emotion,
            "head_pat_end_emotion_duration_sec": self.head_pat_end_emotion_duration_spin.value(),
            "enable_away_nudge": self.enable_away_nudge_check.isChecked(),
            "away_idle_minutes": self.away_idle_minutes_spin.value(),
            "away_diff_threshold_percent": self.away_diff_threshold_spin.value(),
            "away_additional_retry_limit": self.away_retry_limit_spin.value(),
            "model_scale": self.model_scale_spin.value(),
            "model_x_percent": self.model_x_slider.value(),
            "model_y_percent": self.model_y_slider.value(),
            "llm_provider": str(self.llm_provider_combo.currentData() or "gemini"),
            "llm_model": self.llm_model_edit.text().strip() or "gemini-3-flash-preview",
            "llm_models": dict(self._llm_models),
            "llm_model_params": dict(self._llm_model_params),
            "llm_api_keys": dict(self._llm_api_keys),
            "custom_api_url": self.custom_api_url_edit.text().strip(),
            "custom_api_key_or_password": self.custom_api_key_or_password_edit.text().strip(),
            "custom_api_request_model": self.custom_api_request_model_edit.text().strip(),
            "custom_api_format": str(self.custom_api_format_combo.currentData() or LLMFormat.OPENAI_COMPATIBLE.value),
        }

    def _preview_settings(self):
        self.settings_preview.emit(self._get_current_values())

    def _save_settings(self):
        self._saved = True
        self.settings_changed.emit(self._get_current_values())
        self.close()

    def _cancel_settings(self):
        self._saved = False
        self.settings_cancelled.emit()
        self.close()

    def closeEvent(self, event):
        if not hasattr(self, "_saved"):
            self.settings_cancelled.emit()
        event.accept()
