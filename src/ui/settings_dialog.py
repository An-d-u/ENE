"""
Settings dialog for ENE.
Provides live preview without immediate persistence.
"""
import re
from pathlib import Path

try:
    import tiktoken
    import tiktoken_ext.openai_public  # noqa: F401
except ImportError:
    tiktoken = None
from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QListWidget,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from ..ai import prompt_config
from ..ai.tts_client import get_gpt_sovits_text_split_methods, get_tts_provider_catalog, get_tts_provider_defaults
from ..ai.llm_provider import get_llm_provider_catalog
from ..core.i18n import I18n, SUPPORTED_UI_LANGUAGES, get_i18n
from ..core.system_theme import THEME_PRESETS, get_theme_preset, get_windows_theme_mode
from ..core.hotkey_utils import normalize_hotkey_text
from ..core.app_paths import (
    get_bundle_root,
    get_user_data_dir,
    get_user_file,
    read_text_data,
    write_text_data,
)

from .settings_dialog_prompt import SettingsDialogPromptMixin
from .settings_dialog_theme import SettingsDialogThemeMixin
from .settings_dialog_tts import SettingsDialogTtsMixin
from .settings_dialog_goals import SettingsDialogGoalsMixin
from .settings_dialog_hotkeys import SettingsDialogHotkeyMixin
from .settings_dialog_profile import SettingsDialogProfileMixin
from .settings_dialog_ui import SettingsDialogUiMixin
from .settings_dialog_values import SettingsDialogValuesMixin
from .settings_dialog_widgets import (
    ClickableFrame,
    ThemeColorPickerPopup,
    ToggleSwitch,
)


class SettingsDialog(
    SettingsDialogPromptMixin,
    SettingsDialogThemeMixin,
    SettingsDialogTtsMixin,
    SettingsDialogUiMixin,
    SettingsDialogProfileMixin,
    SettingsDialogGoalsMixin,
    SettingsDialogHotkeyMixin,
    SettingsDialogValuesMixin,
    QDialog,
):
    settings_changed = pyqtSignal(dict)
    settings_preview = pyqtSignal(dict)
    settings_cancelled = pyqtSignal()

    def __init__(self, current_settings: dict, memory_manager=None, bridge=None, parent=None):
        super().__init__(parent)
        self._original_settings = current_settings.copy()
        self._memory_manager = memory_manager
        self._bridge = bridge
        self._browser_tts_voices: list[dict[str, object]] = []
        self._browser_voice_request_inflight = False
        self._browser_voice_refresh_attempts = 0
        self._browser_voice_refresh_timer = QTimer(self)
        self._browser_voice_refresh_timer.setSingleShot(True)
        self._browser_voice_refresh_timer.timeout.connect(self._request_browser_tts_voices)
        self._bundle_root = get_bundle_root()
        self._user_data_root = get_user_data_dir()
        self._project_root = self._bundle_root
        self._prompt_path = prompt_config.BASE_SYSTEM_PROMPT_PATH
        self._sub_prompt_path = prompt_config.SUB_PROMPT_BODY_PATH
        self._user_profile_path = get_user_file("user_profile.json")
        self._prompt_status_label: QLabel | None = None
        self._profile_status_label: QLabel | None = None
        self._base_prompt_token_label: QLabel | None = None
        self._sub_prompt_token_label: QLabel | None = None
        self._prompt_status_state = ("settings.prompt.status.idle", "로드 대기", {})
        self._profile_status_state = ("settings.profile.status.idle", "로드 대기", {})
        self._fact_timestamp_state = ("settings.profile.facts.timestamp.new", "신규 항목", {})
        self._emotion_items: list[dict[str, str]] = []
        self._emotion_current_index = -1
        self._basic_info_items: list[tuple[str, str]] = []
        self._basic_info_current_index = -1
        self._fact_items: list[dict[str, str]] = []
        self._fact_current_index = -1
        self._loading = False
        self._capturing_ptt_hotkey = False
        self._dialog_i18n = self._build_dialog_i18n(self._original_settings.get("ui_language", "auto"))
        self._theme_defaults = {
            "theme_accent_color": "#0071E3",
            "settings_window_bg_color": "#EEF1F5",
            "settings_card_bg_color": "#FFFFFF",
            "settings_input_bg_color": "#F8FAFC",
            "chat_panel_bg_color": "#111214",
            "chat_input_bg_color": "#1B1D22",
            "chat_assistant_bubble_color": "#FFFFFF",
            "chat_user_bubble_color": "#0071E3",
        }
        self._theme_color_edits: dict[str, QLineEdit] = {}
        self._theme_preset_frames: dict[str, ClickableFrame] = {}
        self._theme_preset_titles: dict[str, QLabel] = {}
        self._theme_preset_meta: dict[str, QLabel] = {}
        self._theme_preset_input: dict[str, QLabel] = {}
        self._theme_preset_assistant: dict[str, QLabel] = {}
        self._theme_preset_user: dict[str, QLabel] = {}
        self._theme_variant_frames: dict[str, ClickableFrame] = {}
        self._theme_variant_titles: dict[str, QLabel] = {}
        self._theme_variant_meta: dict[str, QLabel] = {}
        self._theme_color_swatches: dict[str, ClickableFrame] = {}
        self._theme_color_reset_buttons: dict[str, QPushButton] = {}
        self._theme_color_titles: dict[str, str] = {}
        self._theme_picker_panels: dict[str, QFrame] = {}
        self._theme_picker_previews: dict[str, QFrame] = {}
        self._theme_picker_value_labels: dict[str, QLabel] = {}
        self._theme_picker_hue_sliders: dict[str, QSlider] = {}
        self._theme_picker_saturation_sliders: dict[str, QSlider] = {}
        self._theme_picker_lightness_sliders: dict[str, QSlider] = {}
        self._theme_picker_popup: ThemeColorPickerPopup | None = None
        self._theme_picker_active_key: str | None = None
        self._theme_live_update_timer = QTimer(self)
        self._theme_live_update_timer.setSingleShot(True)
        self._theme_live_update_timer.setInterval(24)
        self._theme_live_update_timer.timeout.connect(self._flush_theme_live_update)
        self._prompt_token_update_timer = QTimer(self)
        self._prompt_token_update_timer.setSingleShot(True)
        self._prompt_token_update_timer.setInterval(40)
        self._prompt_token_update_timer.timeout.connect(self._refresh_prompt_token_counts)
        self._toggle_checks: list[ToggleSwitch] = []
        self._embedded_memory_panel = None
        self._embedded_ene_profile_panel = None
        self.memory_search_recent_turns_spin: QSpinBox | None = None
        self.assistant_display_name_edit: QLineEdit | None = None
        self.user_address_name_edit: QLineEdit | None = None
        self.tts_language_combo: QComboBox | None = None
        self.enable_ene_goals_check: ToggleSwitch | None = None
        self.show_ene_goal_button_check: ToggleSwitch | None = None
        self.enable_response_analysis_check: ToggleSwitch | None = None
        self.enable_schedule_recognition_check: ToggleSwitch | None = None
        self.enable_conversation_promises_check: ToggleSwitch | None = None
        self.include_ene_thoughts_in_context_check: ToggleSwitch | None = None
        self.ene_thought_context_limit_spin: QSpinBox | None = None
        self.obsidian_checked_max_chars_per_file_spin: QSpinBox | None = None
        self.obsidian_checked_total_max_chars_spin: QSpinBox | None = None
        self._goal_items: dict = {}
        self._goal_active_list: QListWidget | None = None
        self._goal_history_list: QListWidget | None = None
        self._goal_type_combo: QComboBox | None = None
        self._goal_title_edit: QLineEdit | None = None
        self._goal_reason_edit: QPlainTextEdit | None = None
        self._goal_add_button: QPushButton | None = None
        self._goal_update_button: QPushButton | None = None
        self._goal_complete_button: QPushButton | None = None
        self._goal_cancel_button: QPushButton | None = None
        self._goal_empty_label: QLabel | None = None
        self._goal_form_labels: list[QLabel] = []
        self._goal_bridge_connected = False
        self._goal_active_snapshot: list[dict] = []
        self._goal_history_snapshot: list[dict] = []
        self._lazy_tab_hosts: dict[str, QWidget] = {}
        self._lazy_tab_builders: dict[str, callable] = {}
        self._lazy_tab_loaded: set[str] = set()
        self._lazy_tab_index_to_id: dict[int, str] = {}
        self._section_header_map: dict[int, tuple[str, str]] = {}
        self._section_text_meta: dict[int, tuple[str, str, str, str]] = {}
        self._section_nav_cards: dict[int, ClickableFrame] = {}
        self._section_nav_titles: dict[int, QLabel] = {}
        self._section_nav_meta: dict[int, QLabel] = {}
        self._lazy_tab_header_labels: dict[str, tuple[QLabel, QLabel]] = {}
        self._ui_text_bindings: list[tuple[object, str, str]] = []
        self._combo_item_bindings: dict[QComboBox, list[tuple[int, str, str]]] = {}
        self._secret_toggle_pairs: list[tuple[QLineEdit, QPushButton]] = []
        self._theme_color_title_labels: dict[str, QLabel] = {}
        self._theme_color_desc_labels: dict[str, QLabel] = {}
        self._theme_color_text_meta: dict[str, tuple[str, str, str, str]] = {}
        self._prompt_tokenizer = tiktoken.get_encoding("cl100k_base") if tiktoken is not None else None
        self._theme_values = {
            key: self._normalize_theme_color(
                str(self._original_settings.get(key, default_value)),
                fallback=default_value,
            )
            for key, default_value in self._theme_defaults.items()
        }
        self._theme_mode = str(self._original_settings.get("theme_mode", "light")).strip().lower()
        if self._theme_mode not in THEME_PRESETS:
            self._theme_mode = "light"
        self._follow_system_theme = bool(self._original_settings.get("follow_system_theme", False))
        if self._follow_system_theme:
            self._theme_mode = get_windows_theme_mode()
            self._theme_values.update(get_theme_preset(self._theme_mode))
        self._ptt_hotkey_value = normalize_hotkey_text(
            str(self._original_settings.get("global_ptt_hotkey", "alt")),
            default="alt",
        )
        self._tts_catalog = get_tts_provider_catalog()
        self._gpt_sovits_text_split_methods = get_gpt_sovits_text_split_methods()
        self._tts_output_devices = []
        raw_tts_configs = self._original_settings.get("tts_provider_configs", {})
        if not isinstance(raw_tts_configs, dict):
            raw_tts_configs = {}
        self._tts_provider_configs = {
            provider: {
                **get_tts_provider_defaults(provider),
                **(provider_config if isinstance(provider_config, dict) else {}),
            }
            for provider, provider_config in raw_tts_configs.items()
        }
        for provider in self._tts_catalog.keys():
            self._tts_provider_configs.setdefault(provider, get_tts_provider_defaults(provider))

        raw_tts_api_keys = self._original_settings.get("tts_api_keys", {})
        self._tts_api_keys = dict(raw_tts_api_keys) if isinstance(raw_tts_api_keys, dict) else {}

        self.setWindowTitle(self._translated_text("settings.window.title", "ENE 설정"))
        icon_path = self._project_root / "assets" / "icons" / "ene_app.ico"
        if not icon_path.exists():
            icon_path = self._project_root / "assets" / "icons" / "tray_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(1280, 740)
        self.resize(1460, 860)
        self.setWindowFlags(
            Qt.WindowType.Dialog 
            | Qt.WindowType.FramelessWindowHint 
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self._drag_active = False
        self._drag_offset = QPoint()
        self._resize_active = False
        self._resize_edge = ""
        self._resize_start_global = QPoint()
        self._resize_start_geometry = self.geometry()
        self._resize_margin = 12
        self.setMouseTracking(True)

        self._setup_ui()
        self._install_no_wheel_handlers()
        self._load_values()
        self._connect_goal_bridge()
        self._request_goal_items()
        if hasattr(self, "ui_language_combo"):
            self._set_dialog_preview_language(self.ui_language_combo.currentData() or "auto")
        self._retranslate_ui()

    def _install_no_wheel_handlers(self, root: QWidget | None = None) -> None:
        target = root or self
        if isinstance(target, (QAbstractSpinBox, QComboBox)):
            target.installEventFilter(self)
        for widget in target.findChildren(QAbstractSpinBox):
            widget.installEventFilter(self)
        for widget in target.findChildren(QComboBox):
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            event.ignore()
            return True
        return super().eventFilter(obj, event)

    def _normalize_ui_language(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "auto"
        if normalized == "auto":
            return normalized
        return normalized if normalized in SUPPORTED_UI_LANGUAGES else "auto"

    def _resolve_dialog_preview_language(self, ui_language: str | None) -> str:
        normalized = self._normalize_ui_language(ui_language)
        if normalized == "auto":
            runtime_language = str(get_i18n().language or "en").strip().lower()
            return runtime_language if runtime_language in SUPPORTED_UI_LANGUAGES else "en"
        return normalized

    def _build_dialog_i18n(self, ui_language: str | None) -> I18n:
        runtime_i18n = get_i18n()
        return I18n(
            language=self._resolve_dialog_preview_language(ui_language),
            locales_dir=runtime_i18n.locales_dir,
        )

    def _set_dialog_preview_language(self, ui_language: str | None) -> None:
        self._dialog_i18n = self._build_dialog_i18n(ui_language)

    def _normalize_theme_color(self, value: str, fallback: str | None = None) -> str:
        match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(value or "").strip())
        if not match:
            return fallback or self._theme_defaults["theme_accent_color"]
        return f"#{match.group(1).upper()}"

    def _translated_text(self, key: str, fallback: str) -> str:
        translated = self._dialog_i18n.t(key)
        return fallback if translated == key else translated

    def _translated_text_format(self, key: str, fallback: str, **kwargs) -> str:
        translated = self._dialog_i18n.t(key, **kwargs)
        if translated == key:
            try:
                return fallback.format(**kwargs) if kwargs else fallback
            except Exception:
                return fallback
        return translated

    def _register_text_binding(self, setter, key: str, fallback: str) -> None:
        self._ui_text_bindings.append((setter, key, fallback))
        setter(self._translated_text(key, fallback))

    def _bind_widget_text(self, widget, key: str, fallback: str):
        self._register_text_binding(widget.setText, key, fallback)
        return widget

    def _bind_group_title(self, group: QGroupBox, key: str, fallback: str) -> QGroupBox:
        self._register_text_binding(group.setTitle, key, fallback)
        return group

    def _bind_placeholder(self, widget, key: str, fallback: str):
        self._register_text_binding(widget.setPlaceholderText, key, fallback)
        return widget

    def _bind_tooltip(self, widget, key: str, fallback: str):
        self._register_text_binding(widget.setToolTip, key, fallback)
        return widget

    def _bind_suffix(self, widget, key: str, fallback: str):
        self._register_text_binding(widget.setSuffix, key, fallback)
        return widget

    def _bind_special_value_text(self, widget, key: str, fallback: str):
        self._register_text_binding(widget.setSpecialValueText, key, fallback)
        return widget

    def _bind_combo_item(self, combo: QComboBox, index: int, key: str, fallback: str) -> None:
        self._combo_item_bindings.setdefault(combo, []).append((index, key, fallback))
        combo.setItemText(index, self._translated_text(key, fallback))

    def _create_form_label(self, key: str, fallback: str) -> QLabel:
        label = QLabel()
        self._register_text_binding(label.setText, key, fallback)
        return label

    def _add_form_row(self, form: QFormLayout, key: str, fallback: str, field) -> QLabel:
        label = self._create_form_label(key, fallback)
        form.addRow(label, field)
        return label

    def _localized_secret_toggle_text(self, is_password: bool) -> str:
        if is_password:
            return self._translated_text("settings.secret.show", "표시")
        return self._translated_text("settings.secret.hide", "숨김")

    def _refresh_secret_toggle_buttons(self) -> None:
        for line_edit, button in self._secret_toggle_pairs:
            button.setText(self._localized_secret_toggle_text(line_edit.echoMode() == QLineEdit.EchoMode.Password))

    def _refresh_combo_item_bindings(self) -> None:
        for combo, items in self._combo_item_bindings.items():
            for index, key, fallback in items:
                combo.setItemText(index, self._translated_text(key, fallback))

    def _refresh_section_labels(self) -> None:
        for index, meta in self._section_text_meta.items():
            title_key, title_fallback, description_key, description_fallback = meta
            title = self._translated_text(title_key, title_fallback)
            description = self._translated_text(description_key, description_fallback)
            self._section_header_map[index] = (title, description)
            if index in self._section_nav_titles:
                self._section_nav_titles[index].setText(title)
            if index in self._section_nav_meta:
                self._section_nav_meta[index].setText(description)
        if hasattr(self, "content_stack"):
            self._update_section_nav_selection(self.content_stack.currentIndex())

    def _refresh_theme_color_texts(self) -> None:
        for key, meta in self._theme_color_text_meta.items():
            title_key, title_fallback, description_key, description_fallback = meta
            title = self._translated_text(title_key, title_fallback)
            description = self._translated_text(description_key, description_fallback)
            self._theme_color_titles[key] = title
            if key in self._theme_color_title_labels:
                self._theme_color_title_labels[key].setText(title)
            if key in self._theme_color_desc_labels:
                self._theme_color_desc_labels[key].setText(description)

    def _refresh_lazy_tab_headers(self) -> None:
        stale_tab_ids = []
        for tab_id, labels in self._lazy_tab_header_labels.items():
            title_label, body_label = labels
            index = next((idx for idx, current_tab_id in self._lazy_tab_index_to_id.items() if current_tab_id == tab_id), -1)
            if index < 0:
                stale_tab_ids.append(tab_id)
                continue
            title, description = self._section_header_map.get(index, ("", ""))
            try:
                title_label.setText(title)
                body_label.setText(description)
            except RuntimeError:
                stale_tab_ids.append(tab_id)
        for tab_id in stale_tab_ids:
            self._lazy_tab_header_labels.pop(tab_id, None)

    def _refresh_ui_language_combo_labels(self) -> None:
        if not hasattr(self, "ui_language_combo"):
            return
        option_specs = [
            ("auto", "settings.window.general.ui_language.auto", "시스템 기본값"),
            ("ko", "settings.window.general.ui_language.ko", "한국어"),
            ("en", "settings.window.general.ui_language.en", "영어"),
            ("ja", "settings.window.general.ui_language.ja", "일본어"),
        ]
        for index, (_value, key, fallback) in enumerate(option_specs):
            self.ui_language_combo.setItemText(index, self._translated_text(key, fallback))

    def _refresh_ptt_language_combo_labels(self) -> None:
        if not hasattr(self, "ptt_language_combo"):
            return
        option_specs = [
            ("ko", "settings.behavior.ptt.language.ko", "한국어"),
            ("en", "settings.behavior.ptt.language.en", "영어"),
            ("ja", "settings.behavior.ptt.language.ja", "일본어"),
        ]
        for index, (_value, key, fallback) in enumerate(option_specs):
            self.ptt_language_combo.setItemText(index, self._translated_text(key, fallback))

    def _fact_category_label(self, category: str) -> str:
        normalized = str(category or "basic").strip() or "basic"
        fallback_map = {
            "basic": "basic",
            "preference": "preference",
            "goal": "goal",
            "habit": "habit",
        }
        fallback = fallback_map.get(normalized, normalized)
        return self._translated_text(f"settings.profile.facts.category.{normalized}", fallback)

    def _refresh_fact_category_combo_labels(self) -> None:
        if not hasattr(self, "fact_category_combo"):
            return
        for index in range(self.fact_category_combo.count()):
            category = str(self.fact_category_combo.itemData(index) or "")
            if not category:
                continue
            self.fact_category_combo.setItemText(index, self._fact_category_label(category))

    def _set_prompt_status(self, key: str, fallback: str, **kwargs) -> None:
        self._prompt_status_state = (key, fallback, dict(kwargs))
        if self._prompt_status_label is not None:
            self._prompt_status_label.setText(self._translated_text_format(key, fallback, **kwargs))

    def _set_profile_status(self, key: str, fallback: str, **kwargs) -> None:
        self._profile_status_state = (key, fallback, dict(kwargs))
        if self._profile_status_label is not None:
            self._profile_status_label.setText(self._translated_text_format(key, fallback, **kwargs))

    def _set_fact_timestamp(self, key: str, fallback: str, **kwargs) -> None:
        self._fact_timestamp_state = (key, fallback, dict(kwargs))
        if hasattr(self, "fact_timestamp_label") and self.fact_timestamp_label is not None:
            self.fact_timestamp_label.setText(self._translated_text_format(key, fallback, **kwargs))

    def _refresh_provider_combo_labels(self) -> None:
        if hasattr(self, "llm_provider_combo"):
            catalog = get_llm_provider_catalog()
            for index in range(self.llm_provider_combo.count()):
                provider_id = str(self.llm_provider_combo.itemData(index) or "")
                self.llm_provider_combo.setItemText(
                    index,
                    self._llm_provider_label(provider_id, catalog.get(provider_id)),
                )
        if hasattr(self, "tts_provider_combo"):
            for index in range(self.tts_provider_combo.count()):
                provider_id = str(self.tts_provider_combo.itemData(index) or "")
                self.tts_provider_combo.setItemText(
                    index,
                    self._tts_provider_label(provider_id, self._tts_catalog.get(provider_id)),
                )

    def _restore_original_ui_language(self) -> None:
        original_ui_language = str(self._original_settings.get("ui_language", "auto")).strip() or "auto"
        self._set_dialog_preview_language(original_ui_language)

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self._translated_text("settings.window.title", "ENE 설정"))
        self._refresh_combo_item_bindings()
        for setter, key, fallback in self._ui_text_bindings:
            setter(self._translated_text(key, fallback))
        self._refresh_ui_language_combo_labels()
        self._refresh_ptt_language_combo_labels()
        self._refresh_provider_combo_labels()
        self._refresh_fact_category_combo_labels()
        self._refresh_section_labels()
        self._refresh_lazy_tab_headers()
        self._refresh_theme_color_texts()
        self._refresh_secret_toggle_buttons()
        self._refresh_theme_editor_state()
        if self._theme_picker_popup is not None:
            self._theme_picker_popup.set_fallback_title(
                self._translated_text("settings.theme.picker.popup.title", "색상 선택")
            )
            active_title = self._theme_color_titles.get(self._theme_picker_active_key or "", "")
            self._theme_picker_popup.set_title(active_title)
        if self._embedded_ene_profile_panel is not None:
            self._embedded_ene_profile_panel.set_translators(self._translated_text, self._translated_text_format)
        if self._embedded_memory_panel is not None and hasattr(self._embedded_memory_panel, "retranslate_ui"):
            self._embedded_memory_panel.retranslate_ui()
        self._refresh_prompt_token_counts()
        self._update_ptt_hotkey_ui()
        self._sync_tts_provider_ui()
        if self._goal_active_list is not None and self._goal_history_list is not None:
            self._render_goal_items(self._goal_active_snapshot, self._goal_history_snapshot)
        if self._browser_tts_voices:
            self._populate_browser_tts_language_filter(self._browser_tts_voices)
            self._populate_browser_tts_voice_combo()
        elif hasattr(self, "tts_browser_voice_lang_filter_combo") and self.tts_browser_voice_lang_filter_combo.count():
            self.tts_browser_voice_lang_filter_combo.setItemText(
                0,
                self._translated_text("settings.tts.browser.filter.all", "전체 언어"),
            )
        if hasattr(self, "tts_output_device_combo"):
            current_device_id = str(self.tts_output_device_combo.currentData() or "").strip()
            self._refresh_tts_output_devices(current_device_id)
        prompt_key, prompt_fallback, prompt_kwargs = self._prompt_status_state
        self._set_prompt_status(prompt_key, prompt_fallback, **prompt_kwargs)
        profile_key, profile_fallback, profile_kwargs = self._profile_status_state
        self._set_profile_status(profile_key, profile_fallback, **profile_kwargs)
        timestamp_key, timestamp_fallback, timestamp_kwargs = self._fact_timestamp_state
        self._set_fact_timestamp(timestamp_key, timestamp_fallback, **timestamp_kwargs)
        self._refresh_browser_voice_status_label()

    def _create_window_tab(self):
        from .settings_tabs import window_tab

        return window_tab.build_window_tab(self)

    def _create_theme_tab(self):
        from .settings_tabs import theme_tab

        return theme_tab.build_theme_tab(self)

    def _create_model_tab(self):
        from .settings_tabs import model_tab

        return model_tab.build_model_tab(self)

    def _create_llm_tab(self):
        from .settings_tabs import llm_tab

        return llm_tab.build_llm_tab(self)

    def _create_tts_tab(self):
        from .settings_tabs import tts_tab

        return tts_tab.build_tts_tab(self)

    def _create_behavior_tab(self):
        from .settings_tabs import behavior_tab

        return behavior_tab.build_behavior_tab(self)

    def _create_memory_tab(self):
        from .settings_tabs import memory_tab

        return memory_tab.build_memory_tab(self)

    def _create_user_profile_tab(self):
        from .settings_tabs import user_profile_tab

        return user_profile_tab.build_user_profile_tab(self)

    def _create_ene_profile_tab(self):
        from .settings_tabs import ene_profile_tab

        return ene_profile_tab.build_ene_profile_tab(self)

    def _create_prompt_tab(self):
        from .settings_tabs import prompt_tab

        return prompt_tab.build_prompt_tab(self)

    def _read_text_file(self, path: Path) -> str:
        return read_text_data(path, encoding="utf-8-sig")

    def _write_text_file(self, path: Path, text: str) -> None:
        normalized = text.replace("\r\n", "\n")
        write_text_data(path, normalized, encoding="utf-8")

    def closeEvent(self, event):
        self._stop_ptt_hotkey_capture()
        if not getattr(self, "_saved", False):
            self._restore_original_ui_language()
        if not hasattr(self, "_saved"):
            self.settings_cancelled.emit()
        event.accept()

    def _hit_test_resize_edge(self, pos: QPoint) -> str:
        margin = self._resize_margin
        left = pos.x() <= margin
        right = pos.x() >= self.width() - margin
        top = pos.y() <= margin
        bottom = pos.y() >= self.height() - margin

        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return ""

    def _update_resize_cursor(self, pos: QPoint) -> None:
        edge = self._hit_test_resize_edge(pos)
        cursor_map = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursor_map.get(edge, Qt.CursorShape.ArrowCursor))

    def _apply_resize(self, global_pos: QPoint) -> None:
        delta = global_pos - self._resize_start_global
        geometry = self._resize_start_geometry
        x = geometry.x()
        y = geometry.y()
        width = geometry.width()
        height = geometry.height()

        minimum_width = self.minimumWidth()
        minimum_height = self.minimumHeight()

        if "right" in self._resize_edge:
            width = max(minimum_width, width + delta.x())
        if "bottom" in self._resize_edge:
            height = max(minimum_height, height + delta.y())
        if "left" in self._resize_edge:
            new_width = max(minimum_width, width - delta.x())
            x += width - new_width
            width = new_width
        if "top" in self._resize_edge:
            new_height = max(minimum_height, height - delta.y())
            y += height - new_height
            height = new_height

        self.setGeometry(x, y, width, height)

    def mousePressEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._hit_test_resize_edge(event.position().toPoint())
            if edge:
                self._resize_active = True
                self._resize_edge = edge
                self._resize_start_global = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                event.accept()
                return

            if event.pos().y() < 80:
                self._drag_active = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        if self._resize_active:
            self._apply_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drag_active:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return

        self._update_resize_cursor(event.position().toPoint())

    def keyPressEvent(self, event):
        if self._capturing_ptt_hotkey:
            if event.key() == Qt.Key.Key_Escape:
                self._stop_ptt_hotkey_capture()
                event.accept()
                return

            hotkey_text = self._build_hotkey_from_event(event)
            if hotkey_text:
                self._ptt_hotkey_value = normalize_hotkey_text(hotkey_text, default="alt")
                self._stop_ptt_hotkey_capture()
                self._on_setting_changed()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._resize_active = False
            self._resize_edge = ""
            self._update_resize_cursor(event.position().toPoint())
            event.accept()

    def keyReleaseEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        super().keyReleaseEvent(event)
