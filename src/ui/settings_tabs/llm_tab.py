"""
LLM 설정 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...ai.llm_provider import LLMFormat, get_llm_provider_catalog


def build_llm_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    provider_group = QGroupBox("공급자와 인증")
    self._bind_group_title(provider_group, "settings.llm.provider_group.title", "공급자와 인증")
    provider_form = QFormLayout(provider_group)
    provider_form.setSpacing(8)
    provider_form.setContentsMargins(10, 15, 10, 10)

    self.llm_provider_combo = QComboBox()
    self._provider_values = []
    catalog = get_llm_provider_catalog()
    for provider in sorted(catalog.keys()):
        meta = catalog[provider]
        self.llm_provider_combo.addItem(self._llm_provider_label(provider, meta), provider)
        self._provider_values.append(provider)
    self._llm_api_keys = {}
    self._llm_models = {}
    self._llm_model_params = {}
    self._active_model_key_by_provider = {}
    self.llm_provider_combo.currentIndexChanged.connect(self._on_llm_provider_changed)
    self._add_form_row(provider_form, "settings.llm.provider_group.provider", "공급자:", self.llm_provider_combo)

    self.llm_api_key_edit = QLineEdit()
    self._bind_placeholder(
        self.llm_api_key_edit,
        "settings.llm.provider_group.api_key.placeholder",
        "선택한 공급자의 API 키",
    )
    self.llm_api_key_edit.textChanged.connect(self._on_llm_api_key_changed)
    self._add_form_row(
        provider_form,
        "settings.llm.provider_group.api_key.label",
        "API 키:",
        self._build_secret_row(
            self.llm_api_key_edit,
            lambda: self._toggle_secret_field(self.llm_api_key_edit, self.llm_api_key_toggle_button),
            "llm_api_key_toggle_button",
        ),
    )
    provider_form.addRow(
        self._build_hint_label(
            "민감한 값은 기본적으로 숨겨집니다. 현재 선택한 공급자 기준으로 저장됩니다.",
            key="settings.llm.provider_group.api_key.hint",
        )
    )
    layout.addWidget(provider_group)

    model_group = QGroupBox("모델과 응답 스타일")
    self._bind_group_title(model_group, "settings.llm.model_group.title", "모델과 응답 스타일")
    model_form = QFormLayout(model_group)
    model_form.setSpacing(8)
    model_form.setContentsMargins(10, 15, 10, 10)

    self.llm_model_edit = QLineEdit()
    self._bind_placeholder(
        self.llm_model_edit,
        "settings.llm.model_group.model.placeholder",
        "예: gemini-3-flash-preview, gpt-4o-mini",
    )
    self.llm_model_edit.textChanged.connect(self._on_llm_model_changed)
    self._add_form_row(model_form, "settings.llm.model_group.model.label", "모델:", self.llm_model_edit)

    self.llm_temperature_spin = QDoubleSpinBox()
    self.llm_temperature_spin.setRange(0.0, 2.0)
    self.llm_temperature_spin.setSingleStep(0.1)
    self.llm_temperature_spin.setDecimals(2)
    self.llm_temperature_spin.valueChanged.connect(self._on_llm_param_changed)
    self._add_form_row(model_form, "settings.llm.model_group.temperature", "Temperature:", self.llm_temperature_spin)

    self.llm_top_p_spin = QDoubleSpinBox()
    self.llm_top_p_spin.setRange(0.0, 1.0)
    self.llm_top_p_spin.setSingleStep(0.05)
    self.llm_top_p_spin.setDecimals(2)
    self.llm_top_p_spin.valueChanged.connect(self._on_llm_param_changed)
    self._add_form_row(model_form, "settings.llm.model_group.top_p", "Top P:", self.llm_top_p_spin)

    self.llm_max_tokens_spin = QSpinBox()
    self.llm_max_tokens_spin.setRange(0, 65536)
    self._bind_special_value_text(self.llm_max_tokens_spin, "settings.common.auto", "자동")
    self.llm_max_tokens_spin.valueChanged.connect(self._on_llm_param_changed)
    self._add_form_row(model_form, "settings.llm.model_group.max_tokens", "Max Tokens:", self.llm_max_tokens_spin)
    model_form.addRow(
        self._build_hint_label(
            "Temperature와 Top P는 창의성 조절용이고, Max Tokens는 응답 길이 제한입니다.",
            key="settings.llm.model_group.hint",
        )
    )
    layout.addWidget(model_group)

    self.custom_api_group = QGroupBox("Custom API")
    self._bind_group_title(self.custom_api_group, "settings.llm.custom_api_group.title", "Custom API")
    custom_form = QFormLayout(self.custom_api_group)
    custom_form.setSpacing(8)
    custom_form.setContentsMargins(10, 15, 10, 10)

    self.custom_api_url_edit = QLineEdit()
    self._bind_placeholder(
        self.custom_api_url_edit,
        "settings.llm.custom_api_group.url.placeholder",
        "예: https://api.example.com/v1/chat/completions",
    )
    self.custom_api_url_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(custom_form, "settings.llm.custom_api_group.url.label", "URL:", self.custom_api_url_edit)

    self.custom_api_key_or_password_edit = QLineEdit()
    self._bind_placeholder(
        self.custom_api_key_or_password_edit,
        "settings.llm.custom_api_group.secret.placeholder",
        "키 또는 패스워드",
    )
    self.custom_api_key_or_password_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        custom_form,
        "settings.llm.custom_api_group.secret.label",
        "키/패스워드:",
        self._build_secret_row(
            self.custom_api_key_or_password_edit,
            lambda: self._toggle_secret_field(self.custom_api_key_or_password_edit, self.custom_api_secret_toggle_button),
            "custom_api_secret_toggle_button",
        ),
    )

    self.custom_api_request_model_edit = QLineEdit()
    self._bind_placeholder(
        self.custom_api_request_model_edit,
        "settings.llm.custom_api_group.request_model.placeholder",
        "요청 모델명",
    )
    self.custom_api_request_model_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        custom_form,
        "settings.llm.custom_api_group.request_model.label",
        "요청 모델:",
        self.custom_api_request_model_edit,
    )

    self.custom_api_format_combo = QComboBox()
    custom_format_options = [
        ("OpenAI Compatible", LLMFormat.OPENAI_COMPATIBLE.value),
        ("OpenAI Response API", LLMFormat.OPENAI_RESPONSE_API.value),
        ("Anthropic Claude", LLMFormat.ANTHROPIC.value),
        ("Mistral", LLMFormat.MISTRAL.value),
        ("Google Cloud", LLMFormat.GOOGLE_CLOUD.value),
        ("Cohere", LLMFormat.COHERE.value),
    ]
    for index, (label, value) in enumerate(custom_format_options):
        self.custom_api_format_combo.addItem(label, value)
        self._bind_combo_item(
            self.custom_api_format_combo,
            index,
            f"settings.llm.custom_api_group.format.{value}",
            label,
        )
    self.custom_api_format_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(custom_form, "settings.llm.custom_api_group.format.label", "포맷:", self.custom_api_format_combo)
    custom_form.addRow(
        self._build_hint_label(
            "Custom API 공급자를 선택한 경우에만 이 섹션이 사용됩니다.",
            key="settings.llm.custom_api_group.hint",
        )
    )

    self.custom_api_group.setVisible(False)
    layout.addWidget(self.custom_api_group)

    embedding_group = QGroupBox("임베딩 설정")
    self._bind_group_title(embedding_group, "settings.llm.embedding_group.title", "임베딩 설정")
    embedding_form = QFormLayout(embedding_group)
    embedding_form.setSpacing(8)
    embedding_form.setContentsMargins(10, 15, 10, 10)

    self.embedding_provider_combo = QComboBox()
    self.embedding_provider_combo.addItem("Voyage AI", "voyage")
    self.embedding_provider_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(
        embedding_form,
        "settings.llm.embedding_group.provider",
        "임베딩 공급자:",
        self.embedding_provider_combo,
    )

    self.embedding_api_key_edit = QLineEdit()
    self._bind_placeholder(
        self.embedding_api_key_edit,
        "settings.llm.embedding_group.api_key.placeholder",
        "Voyage AI API 키",
    )
    self.embedding_api_key_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        embedding_form,
        "settings.llm.embedding_group.api_key.label",
        "임베딩 API 키:",
        self._build_secret_row(
            self.embedding_api_key_edit,
            lambda: self._toggle_secret_field(self.embedding_api_key_edit, self.embedding_api_key_toggle_button),
            "embedding_api_key_toggle_button",
        ),
    )

    self.embedding_model_combo = QComboBox()
    self.embedding_model_combo.addItem("voyage-3", "voyage-3")
    self.embedding_model_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(
        embedding_form,
        "settings.llm.embedding_group.model",
        "임베딩 모델:",
        self.embedding_model_combo,
    )
    embedding_form.addRow(
        self._build_hint_label(
            "현재는 Voyage AI만 지원합니다. 저장 후 새 기억 생성과 유사 기억 검색에 같은 모델이 사용됩니다. API 키는 api_keys.json의 embedding_api_keys에 저장됩니다.",
            key="settings.llm.embedding_group.hint",
        )
    )
    layout.addWidget(embedding_group)

    restart_group = QGroupBox("적용 안내")
    self._bind_group_title(restart_group, "settings.llm.restart_group.title", "적용 안내")
    restart_layout = QVBoxLayout(restart_group)
    restart_layout.setSpacing(8)
    restart_layout.setContentsMargins(10, 15, 10, 10)

    self.llm_restart_info = QLabel("공급자, 키, 모델 변경은 일부 세션에 즉시 보이지 않을 수 있습니다. 저장 후 앱을 다시 시작하면 가장 확실하게 반영됩니다.")
    self._bind_widget_text(
        self.llm_restart_info,
        "settings.llm.restart_group.body",
        "공급자, 키, 모델 변경은 일부 세션에 즉시 보이지 않을 수 있습니다. 저장 후 앱을 다시 시작하면 가장 확실하게 반영됩니다.",
    )
    self.llm_restart_info.setWordWrap(True)
    self.llm_restart_info.setObjectName("FooterBody")
    restart_layout.addWidget(self.llm_restart_info)
    layout.addWidget(restart_group)
    layout.addStretch()
    scroll.setWidget(widget)
    return scroll

