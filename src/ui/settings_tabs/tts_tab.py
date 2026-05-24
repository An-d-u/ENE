"""
TTS 설정 탭 빌더.
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
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


def build_tts_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    overview_group = QGroupBox("공급자 선택")
    self._bind_group_title(overview_group, "settings.tts.overview.title", "공급자 선택")
    overview_form = QFormLayout(overview_group)
    overview_form.setSpacing(8)
    overview_form.setContentsMargins(10, 15, 10, 10)

    self.enable_tts_check = self._create_toggle(
        "TTS 활성화",
        key="settings.tts.overview.enable",
    )
    self.enable_tts_check.toggled.connect(self._on_setting_changed)
    overview_form.addRow(self.enable_tts_check)

    self.tts_language_combo = QComboBox()
    for value, key, fallback in (
        ("ja", "settings.tts.overview.language.ja", "일본어"),
        ("ko", "settings.tts.overview.language.ko", "한국어"),
        ("en", "settings.tts.overview.language.en", "영어"),
        ("same_as_response", "settings.tts.overview.language.same_as_response", "응답 언어와 같게"),
    ):
        self.tts_language_combo.addItem(self._translated_text(key, fallback), value)
        self._bind_combo_item(self.tts_language_combo, self.tts_language_combo.count() - 1, key, fallback)
    self.tts_language_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(overview_form, "settings.tts.overview.language.label", "읽기 언어:", self.tts_language_combo)

    self.tts_streaming_enabled_check = self._create_toggle(
        "GPT-SoVITS 스트리밍 TTS 사용",
        key="settings.tts.overview.streaming_enabled",
    )
    self.tts_streaming_enabled_check.toggled.connect(self._on_setting_changed)
    overview_form.addRow(self.tts_streaming_enabled_check)

    self.viseme_lipsync_enabled_check = self._create_toggle(
        "viseme 립싱크",
        key="settings.tts.overview.viseme_lipsync",
    )
    self.viseme_lipsync_enabled_check.toggled.connect(self._on_setting_changed)
    overview_form.addRow(self.viseme_lipsync_enabled_check)

    self.tts_provider_combo = QComboBox()
    for provider_id, meta in self._tts_catalog.items():
        self.tts_provider_combo.addItem(self._tts_provider_label(provider_id, meta), provider_id)
    self.tts_provider_combo.currentIndexChanged.connect(self._on_tts_provider_changed)
    self._add_form_row(overview_form, "settings.tts.overview.provider", "공급자:", self.tts_provider_combo)

    self.tts_provider_hint_label = QLabel("")
    self.tts_provider_hint_label.setWordWrap(True)
    self.tts_provider_hint_label.setObjectName("InlineHint")
    overview_form.addRow(self.tts_provider_hint_label)
    layout.addWidget(overview_group)

    playback_group = QGroupBox("재생")
    self._bind_group_title(playback_group, "settings.tts.playback.title", "재생")
    playback_form = QFormLayout(playback_group)
    playback_form.setSpacing(8)
    playback_form.setContentsMargins(10, 15, 10, 10)

    output_device_row = QHBoxLayout()
    output_device_row.setSpacing(8)
    self.tts_output_device_combo = QComboBox()
    self.tts_output_device_combo.currentIndexChanged.connect(self._on_setting_changed)
    output_device_row.addWidget(self.tts_output_device_combo, 1)
    self.tts_output_device_refresh_button = QPushButton("새로고침")
    self._bind_widget_text(self.tts_output_device_refresh_button, "settings.common.refresh", "새로고침")
    self.tts_output_device_refresh_button.clicked.connect(self._on_tts_output_device_refresh_clicked)
    output_device_row.addWidget(self.tts_output_device_refresh_button)
    self._add_form_row(playback_form, "settings.tts.playback.output_device.label", "출력 장치:", output_device_row)

    self.tts_output_volume_spin = QSpinBox()
    self.tts_output_volume_spin.setRange(0, 100)
    self.tts_output_volume_spin.setSuffix(" %")
    self.tts_output_volume_spin.setValue(80)
    self.tts_output_volume_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(playback_form, "settings.tts.playback.volume", "볼륨:", self.tts_output_volume_spin)
    playback_form.addRow(
        self._build_hint_label(
            "GPT-SoVITS, OpenAI Speech, 호환 API, ElevenLabs처럼 앱 내부 오디오 플레이어를 쓰는 TTS에 공통 적용됩니다. 브라우저 기본 TTS에는 적용되지 않습니다.",
            key="settings.tts.playback.hint",
        )
    )
    layout.addWidget(playback_group)

    self._tts_provider_pages = {}
    self.tts_provider_stack = QStackedWidget()

    gpt_page = QWidget()
    gpt_layout = QVBoxLayout(gpt_page)
    gpt_layout.setSpacing(12)
    gpt_layout.setContentsMargins(0, 0, 0, 0)

    gpt_connection_group = QGroupBox("연결")
    self._bind_group_title(gpt_connection_group, "settings.tts.gpt.connection.title", "연결")
    gpt_connection_form = QFormLayout(gpt_connection_group)
    gpt_connection_form.setSpacing(8)
    gpt_connection_form.setContentsMargins(10, 15, 10, 10)
    self.tts_api_url_edit = QLineEdit()
    self._bind_placeholder(self.tts_api_url_edit, "settings.tts.gpt.connection.api_url.placeholder", "예: http://127.0.0.1:9880")
    self.tts_api_url_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_connection_form, "settings.tts.gpt.connection.api_url.label", "TTS API URL:", self.tts_api_url_edit)
    gpt_layout.addWidget(gpt_connection_group)

    gpt_reference_group = QGroupBox("참조 음성")
    self._bind_group_title(gpt_reference_group, "settings.tts.gpt.reference.title", "참조 음성")
    gpt_reference_form = QFormLayout(gpt_reference_group)
    gpt_reference_form.setSpacing(8)
    gpt_reference_form.setContentsMargins(10, 15, 10, 10)

    audio_row = QHBoxLayout()
    audio_row.setSpacing(8)
    self.tts_ref_audio_path_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_ref_audio_path_edit,
        "settings.tts.gpt.reference.audio.placeholder",
        "예: assets/ref_audio/refvoice.wav",
    )
    self.tts_ref_audio_path_edit.textChanged.connect(self._on_setting_changed)
    audio_row.addWidget(self.tts_ref_audio_path_edit, 1)

    browse_audio_btn = QPushButton("찾아보기")
    self._bind_widget_text(browse_audio_btn, "settings.common.browse", "찾아보기")
    browse_audio_btn.clicked.connect(self._browse_tts_ref_audio_path)
    audio_row.addWidget(browse_audio_btn)
    self._add_form_row(gpt_reference_form, "settings.tts.gpt.reference.audio.label", "참조 오디오:", audio_row)

    self.tts_ref_text_edit = QPlainTextEdit()
    self._bind_placeholder(
        self.tts_ref_text_edit,
        "settings.tts.gpt.reference.text.placeholder",
        "참조 오디오의 원문 텍스트",
    )
    self.tts_ref_text_edit.setFixedHeight(96)
    self.tts_ref_text_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_reference_form, "settings.tts.gpt.reference.text.label", "참조 텍스트:", self.tts_ref_text_edit)

    self.tts_ref_language_edit = QLineEdit()
    self._bind_placeholder(self.tts_ref_language_edit, "settings.tts.gpt.reference.ref_language.placeholder", "예: ja")
    self.tts_ref_language_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_reference_form, "settings.tts.gpt.reference.ref_language.label", "참조 언어:", self.tts_ref_language_edit)

    self.tts_target_language_edit = QLineEdit()
    self._bind_placeholder(self.tts_target_language_edit, "settings.tts.gpt.reference.target_language.placeholder", "예: ja")
    self.tts_target_language_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_reference_form, "settings.tts.gpt.reference.target_language.label", "출력 언어:", self.tts_target_language_edit)
    gpt_layout.addWidget(gpt_reference_group)

    gpt_sampling_group = QGroupBox("합성 파라미터")
    self._bind_group_title(gpt_sampling_group, "settings.tts.gpt.sampling.title", "합성 파라미터")
    gpt_sampling_form = QFormLayout(gpt_sampling_group)
    gpt_sampling_form.setSpacing(8)
    gpt_sampling_form.setContentsMargins(10, 15, 10, 10)

    self.tts_gpt_speed_factor_spin = QDoubleSpinBox()
    self.tts_gpt_speed_factor_spin.setRange(0.6, 1.65)
    self.tts_gpt_speed_factor_spin.setSingleStep(0.05)
    self.tts_gpt_speed_factor_spin.setDecimals(2)
    self.tts_gpt_speed_factor_spin.setValue(1.0)
    self.tts_gpt_speed_factor_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_sampling_form, "settings.tts.gpt.sampling.speed_factor", "속도:", self.tts_gpt_speed_factor_spin)

    self.tts_gpt_top_k_spin = QSpinBox()
    self.tts_gpt_top_k_spin.setRange(1, 100)
    self.tts_gpt_top_k_spin.setValue(15)
    self.tts_gpt_top_k_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_sampling_form, "settings.tts.gpt.sampling.top_k", "Top K:", self.tts_gpt_top_k_spin)

    self.tts_gpt_top_p_spin = QDoubleSpinBox()
    self.tts_gpt_top_p_spin.setRange(0.0, 1.0)
    self.tts_gpt_top_p_spin.setSingleStep(0.05)
    self.tts_gpt_top_p_spin.setDecimals(2)
    self.tts_gpt_top_p_spin.setValue(1.0)
    self.tts_gpt_top_p_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_sampling_form, "settings.tts.gpt.sampling.top_p", "Top P:", self.tts_gpt_top_p_spin)

    self.tts_gpt_temperature_spin = QDoubleSpinBox()
    self.tts_gpt_temperature_spin.setRange(0.0, 1.0)
    self.tts_gpt_temperature_spin.setSingleStep(0.05)
    self.tts_gpt_temperature_spin.setDecimals(2)
    self.tts_gpt_temperature_spin.setValue(1.0)
    self.tts_gpt_temperature_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_sampling_form, "settings.tts.gpt.sampling.temperature", "Temperature:", self.tts_gpt_temperature_spin)

    self.tts_gpt_text_split_combo = QComboBox()
    for method_name, key, fallback in (
        ("cut0", "settings.tts.gpt.sampling.text_split.cut0", "cut0 - 자르지 않음"),
        ("cut1", "settings.tts.gpt.sampling.text_split.cut1", "cut1 - 네 문장씩"),
        ("cut2", "settings.tts.gpt.sampling.text_split.cut2", "cut2 - 50자씩"),
        ("cut3", "settings.tts.gpt.sampling.text_split.cut3", "cut3 - 중국어 마침표"),
        ("cut4", "settings.tts.gpt.sampling.text_split.cut4", "cut4 - 영어 마침표"),
        ("cut5", "settings.tts.gpt.sampling.text_split.cut5", "cut5 - 문장부호 기준"),
    ):
        if method_name in self._gpt_sovits_text_split_methods:
            self.tts_gpt_text_split_combo.addItem(self._translated_text(key, fallback), method_name)
            self._bind_combo_item(self.tts_gpt_text_split_combo, self.tts_gpt_text_split_combo.count() - 1, key, fallback)
    self.tts_gpt_text_split_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(gpt_sampling_form, "settings.tts.gpt.sampling.text_split_method", "자르기:", self.tts_gpt_text_split_combo)
    gpt_reference_form.addRow(
        self._build_hint_label(
            "참조 음성 기반 합성입니다. 로컬 서버나 별도 머신의 GPT-SoVITS 엔드포인트를 그대로 지정할 수 있습니다.",
            key="settings.tts.gpt.reference.hint",
        )
    )
    gpt_sampling_form.addRow(
        self._build_hint_label(
            "WebUI에서 자주 쓰는 속도, 샘플링, 문장 자르기 옵션을 ENE에서도 직접 조절합니다.",
            key="settings.tts.gpt.sampling.hint",
        )
    )
    gpt_layout.addWidget(gpt_sampling_group)
    gpt_layout.addStretch()
    self.tts_provider_stack.addWidget(gpt_page)
    self._tts_provider_pages["gpt_sovits_http"] = gpt_page

    genie_page = QWidget()
    genie_layout = QVBoxLayout(genie_page)
    genie_layout.setSpacing(12)
    genie_layout.setContentsMargins(0, 0, 0, 0)

    genie_connection_group = QGroupBox("Genie 연결")
    self._bind_group_title(genie_connection_group, "settings.tts.genie.connection.title", "Genie 연결")
    genie_connection_form = QFormLayout(genie_connection_group)
    genie_connection_form.setSpacing(8)
    genie_connection_form.setContentsMargins(10, 15, 10, 10)
    self.tts_genie_api_url_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_genie_api_url_edit,
        "settings.tts.genie.connection.api_url.placeholder",
        "예: http://127.0.0.1:7860",
    )
    self.tts_genie_api_url_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        genie_connection_form,
        "settings.tts.genie.connection.api_url.label",
        "API URL:",
        self.tts_genie_api_url_edit,
    )
    genie_layout.addWidget(genie_connection_group)

    genie_character_group = QGroupBox("캐릭터")
    self._bind_group_title(genie_character_group, "settings.tts.genie.character.title", "캐릭터")
    genie_character_form = QFormLayout(genie_character_group)
    genie_character_form.setSpacing(8)
    genie_character_form.setContentsMargins(10, 15, 10, 10)
    self.tts_genie_character_name_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_genie_character_name_edit,
        "settings.tts.genie.character.name.placeholder",
        "예: ene",
    )
    self.tts_genie_character_name_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        genie_character_form,
        "settings.tts.genie.character.name.label",
        "캐릭터 이름:",
        self.tts_genie_character_name_edit,
    )
    self.tts_genie_model_dir_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_genie_model_dir_edit,
        "settings.tts.genie.character.model_dir.placeholder",
        "예: models/ene",
    )
    self.tts_genie_model_dir_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        genie_character_form,
        "settings.tts.genie.character.model_dir.label",
        "ONNX 모델 폴더:",
        self.tts_genie_model_dir_edit,
    )
    self.tts_genie_model_language_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_genie_model_language_edit,
        "settings.tts.genie.character.model_language.placeholder",
        "예: ja",
    )
    self.tts_genie_model_language_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        genie_character_form,
        "settings.tts.genie.character.model_language.label",
        "모델 언어:",
        self.tts_genie_model_language_edit,
    )
    genie_character_form.addRow(
        self._build_hint_label(
            "Genie 서버가 캐릭터를 미리 적재할 수 있도록 캐릭터 이름, ONNX 모델 폴더, 모델 언어를 함께 저장합니다.",
            key="settings.tts.genie.character.hint",
        )
    )
    genie_layout.addWidget(genie_character_group)

    genie_reference_group = QGroupBox("참조 음성")
    self._bind_group_title(genie_reference_group, "settings.tts.genie.reference.title", "참조 음성")
    genie_reference_form = QFormLayout(genie_reference_group)
    genie_reference_form.setSpacing(8)
    genie_reference_form.setContentsMargins(10, 15, 10, 10)
    genie_audio_row = QHBoxLayout()
    genie_audio_row.setSpacing(8)
    self.tts_genie_ref_audio_path_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_genie_ref_audio_path_edit,
        "settings.tts.genie.reference.audio.placeholder",
        "예: assets/ref_audio/refvoice.wav",
    )
    self.tts_genie_ref_audio_path_edit.textChanged.connect(self._on_setting_changed)
    genie_audio_row.addWidget(self.tts_genie_ref_audio_path_edit, 1)
    genie_browse_audio_btn = QPushButton("찾아보기")
    self._bind_widget_text(genie_browse_audio_btn, "settings.common.browse", "찾아보기")
    genie_browse_audio_btn.clicked.connect(
        lambda: self._browse_tts_audio_path_into(
            self.tts_genie_ref_audio_path_edit,
            "settings.tts.genie.reference.audio.dialog.title",
            "Genie 참조 오디오 선택",
        )
    )
    genie_audio_row.addWidget(genie_browse_audio_btn)
    self._add_form_row(
        genie_reference_form,
        "settings.tts.genie.reference.audio.label",
        "참조 오디오:",
        genie_audio_row,
    )
    self.tts_genie_ref_text_edit = QPlainTextEdit()
    self._bind_placeholder(
        self.tts_genie_ref_text_edit,
        "settings.tts.genie.reference.text.placeholder",
        "참조 오디오의 원문 텍스트",
    )
    self.tts_genie_ref_text_edit.setFixedHeight(96)
    self.tts_genie_ref_text_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        genie_reference_form,
        "settings.tts.genie.reference.text.label",
        "참조 텍스트:",
        self.tts_genie_ref_text_edit,
    )
    self.tts_genie_ref_language_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_genie_ref_language_edit,
        "settings.tts.genie.reference.ref_language.placeholder",
        "예: ja",
    )
    self.tts_genie_ref_language_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        genie_reference_form,
        "settings.tts.genie.reference.ref_language.label",
        "참조 언어:",
        self.tts_genie_ref_language_edit,
    )
    genie_reference_form.addRow(
        self._build_hint_label(
            "Genie는 참조 음성을 서버에 먼저 등록하므로 오디오 경로, 원문 텍스트, 참조 언어가 모두 필요합니다.",
            key="settings.tts.genie.reference.hint",
        )
    )
    genie_layout.addWidget(genie_reference_group)

    genie_synthesis_group = QGroupBox("합성")
    self._bind_group_title(genie_synthesis_group, "settings.tts.genie.synthesis.title", "합성")
    genie_synthesis_form = QFormLayout(genie_synthesis_group)
    genie_synthesis_form.setSpacing(8)
    genie_synthesis_form.setContentsMargins(10, 15, 10, 10)
    self.tts_genie_split_sentence_check = self._create_toggle(
        "문장 단위로 나눠 합성",
        key="settings.tts.genie.synthesis.split_sentence",
    )
    self.tts_genie_split_sentence_check.toggled.connect(self._on_setting_changed)
    genie_synthesis_form.addRow(self.tts_genie_split_sentence_check)
    genie_synthesis_form.addRow(
        self._build_hint_label(
            "긴 문장을 서버에서 먼저 분리하도록 맡기고 싶을 때 켭니다.",
            key="settings.tts.genie.synthesis.hint",
        )
    )
    genie_layout.addWidget(genie_synthesis_group)

    genie_layout.addStretch()
    self.tts_provider_stack.addWidget(genie_page)
    self._tts_provider_pages["genie_tts_http"] = genie_page

    openai_page = QWidget()
    openai_layout = QVBoxLayout(openai_page)
    openai_layout.setSpacing(12)
    openai_layout.setContentsMargins(0, 0, 0, 0)

    openai_connection_group = QGroupBox("OpenAI 연결")
    self._bind_group_title(openai_connection_group, "settings.tts.openai.connection.title", "OpenAI 연결")
    openai_connection_form = QFormLayout(openai_connection_group)
    openai_connection_form.setSpacing(8)
    openai_connection_form.setContentsMargins(10, 15, 10, 10)
    self.tts_openai_api_key_edit = QLineEdit()
    self._bind_placeholder(self.tts_openai_api_key_edit, "settings.tts.openai.connection.api_key.placeholder", "OpenAI API 키")
    self.tts_openai_api_key_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        openai_connection_form,
        "settings.tts.openai.connection.api_key.label",
        "API 키:",
        self._build_secret_row(
            self.tts_openai_api_key_edit,
            lambda: self._toggle_secret_field(self.tts_openai_api_key_edit, self.tts_openai_api_key_toggle_button),
            "tts_openai_api_key_toggle_button",
        ),
    )
    self.tts_openai_api_url_edit = QLineEdit()
    self._bind_placeholder(self.tts_openai_api_url_edit, "settings.tts.openai.connection.api_url.placeholder", "예: https://api.openai.com/v1")
    self.tts_openai_api_url_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(openai_connection_form, "settings.tts.openai.connection.api_url.label", "API URL:", self.tts_openai_api_url_edit)
    openai_layout.addWidget(openai_connection_group)

    openai_voice_group = QGroupBox("모델과 음성")
    self._bind_group_title(openai_voice_group, "settings.tts.openai.voice.title", "모델과 음성")
    openai_voice_form = QFormLayout(openai_voice_group)
    openai_voice_form.setSpacing(8)
    openai_voice_form.setContentsMargins(10, 15, 10, 10)
    self.tts_openai_model_combo = QComboBox()
    for model_name in ("gpt-4o-mini-tts", "tts-1", "tts-1-hd"):
        self.tts_openai_model_combo.addItem(model_name, model_name)
    self.tts_openai_model_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(openai_voice_form, "settings.tts.openai.voice.model", "모델:", self.tts_openai_model_combo)
    self.tts_openai_voice_combo = QComboBox()
    for voice_name in ("alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar"):
        self.tts_openai_voice_combo.addItem(voice_name, voice_name)
    self.tts_openai_voice_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(openai_voice_form, "settings.tts.openai.voice.voice", "음성:", self.tts_openai_voice_combo)
    self.tts_openai_speed_spin = QDoubleSpinBox()
    self.tts_openai_speed_spin.setRange(0.25, 4.0)
    self.tts_openai_speed_spin.setSingleStep(0.05)
    self.tts_openai_speed_spin.setDecimals(2)
    self.tts_openai_speed_spin.setValue(1.0)
    self.tts_openai_speed_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(openai_voice_form, "settings.tts.openai.voice.speed", "속도:", self.tts_openai_speed_spin)
    openai_voice_form.addRow(
        self._build_hint_label(
            "AIRI의 OpenAI Speech 설정처럼 API URL, 모델, 음성, 속도를 분리했습니다. 응답 포맷은 립싱크 분석을 위해 WAV로 고정합니다.",
            key="settings.tts.openai.voice.hint",
        )
    )
    openai_layout.addWidget(openai_voice_group)
    openai_layout.addStretch()
    self.tts_provider_stack.addWidget(openai_page)
    self._tts_provider_pages["openai_audio_speech"] = openai_page

    compatible_page = QWidget()
    compatible_layout = QVBoxLayout(compatible_page)
    compatible_layout.setSpacing(12)
    compatible_layout.setContentsMargins(0, 0, 0, 0)

    compatible_connection_group = QGroupBox("호환 API 연결")
    self._bind_group_title(compatible_connection_group, "settings.tts.compatible.connection.title", "호환 API 연결")
    compatible_connection_form = QFormLayout(compatible_connection_group)
    compatible_connection_form.setSpacing(8)
    compatible_connection_form.setContentsMargins(10, 15, 10, 10)
    self.tts_compatible_api_key_edit = QLineEdit()
    self._bind_placeholder(
        self.tts_compatible_api_key_edit,
        "settings.tts.compatible.connection.api_key.placeholder",
        "필요한 경우에만 API 키 입력",
    )
    self.tts_compatible_api_key_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        compatible_connection_form,
        "settings.tts.compatible.connection.api_key.label",
        "API 키:",
        self._build_secret_row(
            self.tts_compatible_api_key_edit,
            lambda: self._toggle_secret_field(self.tts_compatible_api_key_edit, self.tts_compatible_api_key_toggle_button),
            "tts_compatible_api_key_toggle_button",
        ),
    )
    self.tts_compatible_api_url_edit = QLineEdit()
    self._bind_placeholder(self.tts_compatible_api_url_edit, "settings.tts.compatible.connection.api_url.placeholder", "예: http://127.0.0.1:8000/v1")
    self.tts_compatible_api_url_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(compatible_connection_form, "settings.tts.compatible.connection.api_url.label", "API URL:", self.tts_compatible_api_url_edit)
    compatible_layout.addWidget(compatible_connection_group)

    compatible_voice_group = QGroupBox("모델과 음성")
    self._bind_group_title(compatible_voice_group, "settings.tts.compatible.voice.title", "모델과 음성")
    compatible_voice_form = QFormLayout(compatible_voice_group)
    compatible_voice_form.setSpacing(8)
    compatible_voice_form.setContentsMargins(10, 15, 10, 10)
    self.tts_compatible_model_edit = QLineEdit()
    self._bind_placeholder(self.tts_compatible_model_edit, "settings.tts.compatible.voice.model.placeholder", "예: tts-1")
    self.tts_compatible_model_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(compatible_voice_form, "settings.tts.compatible.voice.model.label", "모델:", self.tts_compatible_model_edit)
    self.tts_compatible_voice_edit = QLineEdit()
    self._bind_placeholder(self.tts_compatible_voice_edit, "settings.tts.compatible.voice.voice.placeholder", "예: alloy")
    self.tts_compatible_voice_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(compatible_voice_form, "settings.tts.compatible.voice.voice.label", "음성:", self.tts_compatible_voice_edit)
    self.tts_compatible_speed_spin = QDoubleSpinBox()
    self.tts_compatible_speed_spin.setRange(0.25, 4.0)
    self.tts_compatible_speed_spin.setSingleStep(0.05)
    self.tts_compatible_speed_spin.setDecimals(2)
    self.tts_compatible_speed_spin.setValue(1.0)
    self.tts_compatible_speed_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(compatible_voice_form, "settings.tts.compatible.voice.speed", "속도:", self.tts_compatible_speed_spin)
    compatible_voice_form.addRow(
        self._build_hint_label(
            "로컬 TTS 서버나 프록시 API처럼 OpenAI 음성 합성 스펙을 흉내내는 엔드포인트에 맞춘 범용 설정입니다.",
            key="settings.tts.compatible.voice.hint",
        )
    )
    compatible_layout.addWidget(compatible_voice_group)
    compatible_layout.addStretch()
    self.tts_provider_stack.addWidget(compatible_page)
    self._tts_provider_pages["openai_compatible_audio_speech"] = compatible_page

    elevenlabs_page = QWidget()
    elevenlabs_layout = QVBoxLayout(elevenlabs_page)
    elevenlabs_layout.setSpacing(12)
    elevenlabs_layout.setContentsMargins(0, 0, 0, 0)

    elevenlabs_connection_group = QGroupBox("ElevenLabs 연결")
    self._bind_group_title(elevenlabs_connection_group, "settings.tts.elevenlabs.connection.title", "ElevenLabs 연결")
    elevenlabs_connection_form = QFormLayout(elevenlabs_connection_group)
    elevenlabs_connection_form.setSpacing(8)
    elevenlabs_connection_form.setContentsMargins(10, 15, 10, 10)
    self.tts_elevenlabs_api_key_edit = QLineEdit()
    self._bind_placeholder(self.tts_elevenlabs_api_key_edit, "settings.tts.elevenlabs.connection.api_key.placeholder", "ElevenLabs API 키")
    self.tts_elevenlabs_api_key_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(
        elevenlabs_connection_form,
        "settings.tts.elevenlabs.connection.api_key.label",
        "API 키:",
        self._build_secret_row(
            self.tts_elevenlabs_api_key_edit,
            lambda: self._toggle_secret_field(self.tts_elevenlabs_api_key_edit, self.tts_elevenlabs_api_key_toggle_button),
            "tts_elevenlabs_api_key_toggle_button",
        ),
    )
    self.tts_elevenlabs_api_url_edit = QLineEdit()
    self._bind_placeholder(self.tts_elevenlabs_api_url_edit, "settings.tts.elevenlabs.connection.api_url.placeholder", "예: https://api.elevenlabs.io/v1")
    self.tts_elevenlabs_api_url_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(elevenlabs_connection_form, "settings.tts.elevenlabs.connection.api_url.label", "API URL:", self.tts_elevenlabs_api_url_edit)
    elevenlabs_layout.addWidget(elevenlabs_connection_group)

    elevenlabs_voice_group = QGroupBox("모델과 음성 스타일")
    self._bind_group_title(elevenlabs_voice_group, "settings.tts.elevenlabs.voice.title", "모델과 음성 스타일")
    elevenlabs_voice_form = QFormLayout(elevenlabs_voice_group)
    elevenlabs_voice_form.setSpacing(8)
    elevenlabs_voice_form.setContentsMargins(10, 15, 10, 10)
    self.tts_elevenlabs_model_combo = QComboBox()
    for model_name in ("eleven_multilingual_v2", "eleven_multilingual_v1", "eleven_monolingual_v1"):
        self.tts_elevenlabs_model_combo.addItem(model_name, model_name)
    self.tts_elevenlabs_model_combo.currentIndexChanged.connect(self._on_setting_changed)
    self._add_form_row(elevenlabs_voice_form, "settings.tts.elevenlabs.voice.model", "모델:", self.tts_elevenlabs_model_combo)
    self.tts_elevenlabs_voice_edit = QLineEdit()
    self._bind_placeholder(self.tts_elevenlabs_voice_edit, "settings.tts.elevenlabs.voice.voice_id.placeholder", "예: EXAVITQu4vr4xnSDxMaL")
    self.tts_elevenlabs_voice_edit.textChanged.connect(self._on_setting_changed)
    self._add_form_row(elevenlabs_voice_form, "settings.tts.elevenlabs.voice.voice_id.label", "Voice ID:", self.tts_elevenlabs_voice_edit)
    self.tts_elevenlabs_speed_spin = QDoubleSpinBox()
    self.tts_elevenlabs_speed_spin.setRange(0.5, 2.0)
    self.tts_elevenlabs_speed_spin.setSingleStep(0.05)
    self.tts_elevenlabs_speed_spin.setDecimals(2)
    self.tts_elevenlabs_speed_spin.setValue(1.0)
    self.tts_elevenlabs_speed_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(elevenlabs_voice_form, "settings.tts.elevenlabs.voice.speed", "속도:", self.tts_elevenlabs_speed_spin)
    self.tts_elevenlabs_stability_spin = QDoubleSpinBox()
    self.tts_elevenlabs_stability_spin.setRange(0.0, 1.0)
    self.tts_elevenlabs_stability_spin.setSingleStep(0.05)
    self.tts_elevenlabs_stability_spin.setDecimals(2)
    self.tts_elevenlabs_stability_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(elevenlabs_voice_form, "settings.tts.elevenlabs.voice.stability", "Stability:", self.tts_elevenlabs_stability_spin)
    self.tts_elevenlabs_similarity_spin = QDoubleSpinBox()
    self.tts_elevenlabs_similarity_spin.setRange(0.0, 1.0)
    self.tts_elevenlabs_similarity_spin.setSingleStep(0.05)
    self.tts_elevenlabs_similarity_spin.setDecimals(2)
    self.tts_elevenlabs_similarity_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(elevenlabs_voice_form, "settings.tts.elevenlabs.voice.similarity", "Similarity Boost:", self.tts_elevenlabs_similarity_spin)
    self.tts_elevenlabs_style_spin = QDoubleSpinBox()
    self.tts_elevenlabs_style_spin.setRange(0.0, 1.0)
    self.tts_elevenlabs_style_spin.setSingleStep(0.05)
    self.tts_elevenlabs_style_spin.setDecimals(2)
    self.tts_elevenlabs_style_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(elevenlabs_voice_form, "settings.tts.elevenlabs.voice.style", "Style:", self.tts_elevenlabs_style_spin)
    self.tts_elevenlabs_speaker_boost_check = self._create_toggle(
        "Speaker Boost 사용",
        key="settings.tts.elevenlabs.voice.speaker_boost",
    )
    self.tts_elevenlabs_speaker_boost_check.toggled.connect(self._on_setting_changed)
    elevenlabs_voice_form.addRow(self.tts_elevenlabs_speaker_boost_check)
    elevenlabs_voice_form.addRow(
        self._build_hint_label(
            "AIRI 코드의 ElevenLabs 설정에서 핵심인 모델, Voice ID, stability, similarity boost, style, speaker boost를 그대로 가져왔습니다.",
            key="settings.tts.elevenlabs.voice.hint",
        )
    )
    elevenlabs_layout.addWidget(elevenlabs_voice_group)
    elevenlabs_layout.addStretch()
    self.tts_provider_stack.addWidget(elevenlabs_page)
    self._tts_provider_pages["elevenlabs"] = elevenlabs_page

    browser_page = QWidget()
    browser_layout = QVBoxLayout(browser_page)
    browser_layout.setSpacing(12)
    browser_layout.setContentsMargins(0, 0, 0, 0)

    browser_group = QGroupBox("브라우저 기본 TTS")
    self._bind_group_title(browser_group, "settings.tts.browser.title", "브라우저 기본 TTS")
    browser_form = QFormLayout(browser_group)
    browser_form.setSpacing(8)
    browser_form.setContentsMargins(10, 15, 10, 10)
    self.tts_browser_lang_edit = QLineEdit()
    self._bind_placeholder(self.tts_browser_lang_edit, "settings.tts.browser.lang.placeholder", "예: ja-JP")
    self.tts_browser_lang_edit.textChanged.connect(self._on_browser_tts_lang_changed)
    self._add_form_row(browser_form, "settings.tts.browser.lang.label", "언어:", self.tts_browser_lang_edit)

    self.tts_browser_voice_lang_filter_combo = QComboBox()
    self.tts_browser_voice_lang_filter_combo.addItem(
        self._translated_text("settings.tts.browser.filter.all", "전체 언어"),
        "",
    )
    self.tts_browser_voice_lang_filter_combo.currentIndexChanged.connect(self._on_browser_tts_language_filter_changed)
    self._add_form_row(browser_form, "settings.tts.browser.filter.label", "목록 필터:", self.tts_browser_voice_lang_filter_combo)

    browser_voice_row = QHBoxLayout()
    browser_voice_row.setSpacing(8)
    self.tts_browser_voice_combo = QComboBox()
    self.tts_browser_voice_combo.setEditable(True)
    self.tts_browser_voice_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    self._bind_placeholder(
        self.tts_browser_voice_combo,
        "settings.tts.browser.voice.placeholder",
        "사용 가능한 음성을 자동으로 불러옵니다",
    )
    self.tts_browser_voice_combo.currentIndexChanged.connect(self._on_setting_changed)
    self.tts_browser_voice_combo.currentTextChanged.connect(self._on_setting_changed)
    browser_voice_row.addWidget(self.tts_browser_voice_combo, 1)
    self.tts_browser_voice_refresh_button = QPushButton("새로고침")
    self._bind_widget_text(self.tts_browser_voice_refresh_button, "settings.common.refresh", "새로고침")
    self.tts_browser_voice_refresh_button.clicked.connect(self._request_browser_tts_voices)
    browser_voice_row.addWidget(self.tts_browser_voice_refresh_button)
    self._add_form_row(browser_form, "settings.tts.browser.voice.label", "음성:", browser_voice_row)

    self.tts_browser_voice_status_label = self._build_hint_label(
        "설정창이 열려 있는 현재 ENE 웹뷰 환경에서 음성 목록을 읽습니다. 다른 PC에서는 그 환경 기준 목록이 다시 표시됩니다.",
        key="settings.tts.browser.status.idle",
    )
    browser_form.addRow(self.tts_browser_voice_status_label)

    self.tts_browser_rate_spin = QDoubleSpinBox()
    self.tts_browser_rate_spin.setRange(0.1, 3.0)
    self.tts_browser_rate_spin.setSingleStep(0.05)
    self.tts_browser_rate_spin.setDecimals(2)
    self.tts_browser_rate_spin.setValue(1.0)
    self.tts_browser_rate_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(browser_form, "settings.tts.browser.rate", "속도:", self.tts_browser_rate_spin)
    self.tts_browser_pitch_spin = QDoubleSpinBox()
    self.tts_browser_pitch_spin.setRange(0.0, 2.0)
    self.tts_browser_pitch_spin.setSingleStep(0.05)
    self.tts_browser_pitch_spin.setDecimals(2)
    self.tts_browser_pitch_spin.setValue(1.0)
    self.tts_browser_pitch_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(browser_form, "settings.tts.browser.pitch", "Pitch:", self.tts_browser_pitch_spin)
    self.tts_browser_volume_spin = QDoubleSpinBox()
    self.tts_browser_volume_spin.setRange(0.0, 1.0)
    self.tts_browser_volume_spin.setSingleStep(0.05)
    self.tts_browser_volume_spin.setDecimals(2)
    self.tts_browser_volume_spin.setValue(1.0)
    self.tts_browser_volume_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(browser_form, "settings.tts.browser.volume", "볼륨:", self.tts_browser_volume_spin)
    browser_form.addRow(
        self._build_hint_label(
            "테스트용/폴백용 공급자입니다. API 키 없이 바로 말하게 할 수 있지만, 음질과 사용 가능한 음성은 배포 환경의 브라우저/OS에 따라 달라집니다. 저장된 음성이 현재 환경에 없으면 같은 언어 음성이나 시스템 기본 음성으로 자연스럽게 대체됩니다. 립싱크는 적용되지 않습니다.",
            key="settings.tts.browser.hint",
        )
    )
    browser_layout.addWidget(browser_group)
    browser_layout.addStretch()
    self.tts_provider_stack.addWidget(browser_page)
    self._tts_provider_pages["browser_speech"] = browser_page

    layout.addWidget(self.tts_provider_stack)

    layout.addStretch()
    scroll.setWidget(widget)
    return scroll

