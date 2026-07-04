"""
설정 대화상자 기본 UI 조립 mixin.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .settings_dialog_widgets import ClickableFrame, ToggleSwitch, apply_soft_shadow


class SettingsDialogUiMixin:
    def _create_toggle(self, text: str, *, key: str | None = None) -> ToggleSwitch:
        toggle = ToggleSwitch(self._translated_text(key, text) if key else text)
        self._toggle_checks.append(toggle)
        if key:
            self._register_text_binding(toggle.setText, key, text)
        toggle.set_theme_colors(
            accent=self._theme_values["theme_accent_color"],
            track_off=self._theme_values["settings_input_bg_color"],
            text_color=self._theme_text_color(self._theme_values["settings_card_bg_color"]),
            muted_border=self._theme_rgba(self._theme_text_color(self._theme_values["settings_card_bg_color"]), 0.12),
        )
        return toggle

    def _apply_stylesheet(self):
        accent = self._theme_values["theme_accent_color"]
        settings_window = self._theme_values["settings_window_bg_color"]
        settings_card = self._theme_values["settings_card_bg_color"]
        settings_input = self._theme_values["settings_input_bg_color"]
        primary_text = self._theme_text_color(settings_card)
        muted_text = self._theme_muted_text_color(settings_card)
        title_muted = self._theme_muted_text_color(settings_window)
        input_text = self._theme_text_color(settings_input)
        card_border = self._theme_border_color(settings_card, 0.10)
        window_border = self._theme_border_color(settings_window, 0.10)
        input_border = self._theme_border_color(settings_input, 0.14)
        tab_shell_bg = self._theme_variant(settings_window, lighter=102) if self._theme_text_color(settings_window) == "#111827" else self._theme_variant(settings_window, darker=104)
        accent_hover = self._theme_variant(accent, darker=108)
        accent_title = self._theme_variant(accent, darker=116)
        accent_soft = self._theme_rgba(accent, 0.10)
        accent_soft_strong = self._theme_rgba(accent, 0.18)
        accent_border = self._theme_rgba(accent, 0.22)
        accent_focus = self._theme_rgba(accent, 0.55)
        accent_slider = self._theme_rgba(accent, 0.80)
        accent_slider_hover = self._theme_rgba(accent, 1.0)
        accent_dropdown = self._theme_rgba(accent, 0.12)
        style = """
        QDialog { background: __SETTINGS_WINDOW__; color: __PRIMARY_TEXT__; font-family: 'Malgun Gothic', 'Segoe UI Variable', 'Segoe UI', sans-serif; }
        QWidget { background: transparent; }
        #MainFrame { background: __SETTINGS_CARD__; border: 1px solid __WINDOW_BORDER__; border-radius: 30px; }
        #TitleBar, #FooterCard, #SidebarShell, #ContentShell { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 24px; }
        #TitleLabel { color: __PRIMARY_TEXT__; font-size: 18px; font-weight: 700; }
        #TitleSubLabel { color: __TITLE_MUTED__; font-size: 12px; font-weight: 600; }
        #CloseButton { background: transparent; border: none; color: __MUTED_TEXT__; min-width: 34px; min-height: 34px; border-radius: 17px; font-size: 18px; }
        #CloseButton:hover { background: __PRIMARY_TEXT_SOFT__; color: __PRIMARY_TEXT__; }
        #FooterTitle { color: __PRIMARY_TEXT__; font-size: 15px; font-weight: 700; }
        #FooterBody { color: __MUTED_TEXT__; font-size: 13px; }
        #InlineHint { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        #ValueBadge { color: __PRIMARY_TEXT__; font-size: 13px; font-weight: 700; background: __SETTINGS_INPUT__; border: 1px solid __INPUT_BORDER__; border-radius: 12px; padding: 8px 12px; }
        #SidebarTitle { color: __PRIMARY_TEXT__; font-size: 15px; font-weight: 700; }
        #SidebarMeta { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        #ContentHeaderTitle { color: __PRIMARY_TEXT__; font-size: 18px; font-weight: 700; }
        #ContentHeaderMeta { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        QFrame#NavItemCard { background: __TAB_SHELL_BG__; border: 1px solid __CARD_BORDER__; border-radius: 20px; }
        QFrame#NavItemCard:hover { border: 1px solid __ACCENT_BORDER__; background: __PRIMARY_TEXT_SOFT__; }
        QFrame#NavItemCard[selected='true'] { background: __SETTINGS_CARD__; border: 1px solid __ACCENT_BORDER__; }
        QLabel#NavItemTitle { color: __PRIMARY_TEXT__; font-size: 14px; font-weight: 700; }
        QLabel#NavItemMeta { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        QFrame#NavItemCard[selected='true'] QLabel#NavItemMeta { color: __PRIMARY_TEXT__; }

        QLabel, QCheckBox { color: __PRIMARY_TEXT__; font-size: 13px; }
        QCheckBox { spacing: 0px; background: transparent; }
        QGroupBox { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 22px; margin-top: 12px; padding-top: 20px; padding-left: 18px; padding-right: 18px; padding-bottom: 18px; font-weight: 700; color: __PRIMARY_TEXT__; }
        QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 9px; top: -2px; padding: 0 4px; color: __ACCENT_TITLE__; background: __SETTINGS_CARD__; }
        QPushButton { min-height: 44px; padding: 0 18px; border-radius: 18px; border: 1px solid __CARD_BORDER__; background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; font-size: 13px; font-weight: 600; }
        QPushButton:hover { background: __SETTINGS_INPUT__; }
        QPushButton:disabled { background: __SETTINGS_CARD__; color: __DISABLED_TEXT__; }
        QPushButton[accent='true'] { background: __ACCENT__; color: __ACCENT_TEXT__; border: 1px solid __ACCENT__; }
        QPushButton[accent='true']:hover { background: __ACCENT_HOVER__; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { min-height: 42px; padding: 0 14px; border-radius: 16px; background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; font-size: 13px; selection-background-color: __ACCENT_SOFT_STRONG__; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid __ACCENT_FOCUS__; background: __SETTINGS_INPUT__; }
        QPlainTextEdit { background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; border-radius: 18px; padding: 14px; font-size: 13px; font-family: 'Consolas', 'D2Coding', 'Malgun Gothic', monospace; selection-background-color: __ACCENT_SOFT_STRONG__; }
        QPlainTextEdit:focus { border: 1px solid __ACCENT_FOCUS__; background: __SETTINGS_INPUT__; }
        QListWidget { background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; border-radius: 18px; padding: 8px; outline: none; }
        QListWidget::item { color: __INPUT_TEXT__; background: transparent; border: 1px solid transparent; border-radius: 14px; padding: 10px 12px; margin: 2px 0; }
        QListWidget::item:hover { background: __PRIMARY_TEXT_SOFT__; border: 1px solid __CARD_BORDER__; }
        QListWidget::item:selected { background: __ACCENT_SOFT__; color: __INPUT_TEXT__; border: 1px solid __ACCENT_BORDER__; }
        QComboBox::drop-down { border: none; width: 28px; }
        QComboBox QAbstractItemView { background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; border: 1px solid __CARD_BORDER__; selection-background-color: __ACCENT_DROPDOWN__; outline: none; padding: 4px; }
        QSlider::groove:horizontal { border: 1px solid __INPUT_BORDER__; height: 6px; background: __TAB_SHELL_BG__; border-radius: 3px; }
        QSlider::sub-page:horizontal { background: __ACCENT_SLIDER__; border-radius: 3px; }
        QSlider::handle:horizontal { background: __SETTINGS_CARD__; border: 2px solid __ACCENT_SLIDER__; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
        QSlider::handle:horizontal:hover { border: 2px solid __ACCENT_SLIDER_HOVER__; }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical { width: 10px; background: transparent; margin: 8px 0; }
        QScrollBar::handle:vertical { background: __MUTED_TEXT_SOFT__; min-height: 20px; border-radius: 5px; }
        QScrollBar::handle:vertical:hover { background: __MUTED_TEXT_STRONG__; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
        """
        style = (
            style.replace("__ACCENT__", accent)
            .replace("__ACCENT_HOVER__", accent_hover)
            .replace("__ACCENT_TEXT__", self._theme_text_color(accent))
            .replace("__ACCENT_TITLE__", accent_title)
            .replace("__ACCENT_SOFT__", accent_soft)
            .replace("__ACCENT_SOFT_STRONG__", accent_soft_strong)
            .replace("__ACCENT_BORDER__", accent_border)
            .replace("__ACCENT_FOCUS__", accent_focus)
            .replace("__ACCENT_SLIDER__", accent_slider)
            .replace("__ACCENT_SLIDER_HOVER__", accent_slider_hover)
            .replace("__ACCENT_DROPDOWN__", accent_dropdown)
            .replace("__SETTINGS_WINDOW__", settings_window)
            .replace("__SETTINGS_CARD__", settings_card)
            .replace("__SETTINGS_INPUT__", settings_input)
            .replace("__PRIMARY_TEXT__", primary_text)
            .replace("__MUTED_TEXT__", muted_text)
            .replace("__TITLE_MUTED__", title_muted)
            .replace("__INPUT_TEXT__", input_text)
            .replace("__CARD_BORDER__", card_border)
            .replace("__WINDOW_BORDER__", window_border)
            .replace("__INPUT_BORDER__", input_border)
            .replace("__TAB_SHELL_BG__", tab_shell_bg)
            .replace("__PRIMARY_TEXT_SOFT__", self._theme_rgba(primary_text, 0.08))
            .replace("__DISABLED_TEXT__", self._theme_rgba(primary_text, 0.42))
            .replace("__MUTED_TEXT_SOFT__", self._theme_rgba(muted_text, 0.35))
            .replace("__MUTED_TEXT_STRONG__", self._theme_rgba(muted_text, 0.55))
        )
        self.setStyleSheet(style)

        for toggle in self._toggle_checks:
            toggle.set_theme_colors(
                accent=accent,
                track_off=settings_input,
                text_color=primary_text,
                muted_border=self._theme_rgba(primary_text, 0.12),
            )
        if self._embedded_memory_panel is not None:
            self._embedded_memory_panel.apply_theme(dict(self._theme_values))

    def _setup_ui(self):
        self._apply_stylesheet()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)

        self.main_frame = QFrame()
        self.main_frame.setObjectName("MainFrame")
        apply_soft_shadow(self.main_frame)
        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        main_layout.addWidget(self.main_frame)

        workspace_row = QHBoxLayout()
        workspace_row.setSpacing(14)

        sidebar_shell = QFrame()
        sidebar_shell.setObjectName("SidebarShell")
        sidebar_shell.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar_shell)
        sidebar_layout.setContentsMargins(14, 14, 14, 14)
        sidebar_layout.setSpacing(12)

        sidebar_title = QLabel("ENE 설정")
        self._bind_widget_text(sidebar_title, "settings.sidebar.title", "ENE 설정")
        sidebar_title.setObjectName("SidebarTitle")
        sidebar_layout.addWidget(sidebar_title)

        sidebar_meta = QLabel("섹션을 옆 메뉴에서 고르고 오른쪽에서 세부 설정을 조정합니다.")
        self._bind_widget_text(
            sidebar_meta,
            "settings.sidebar.meta",
            "섹션을 옆 메뉴에서 고르고 오른쪽에서 세부 설정을 조정합니다.",
        )
        sidebar_meta.setObjectName("SidebarMeta")
        sidebar_meta.setWordWrap(True)
        sidebar_layout.addWidget(sidebar_meta)

        self.section_nav_container = QWidget()
        section_nav_layout = QVBoxLayout(self.section_nav_container)
        section_nav_layout.setContentsMargins(0, 4, 0, 0)
        section_nav_layout.setSpacing(10)
        sidebar_layout.addWidget(self.section_nav_container)
        sidebar_layout.addStretch()

        content_shell = QFrame()
        content_shell.setObjectName("ContentShell")
        content_layout = QVBoxLayout(content_shell)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(8)

        content_header = QWidget()
        content_header_layout = QHBoxLayout(content_header)
        content_header_layout.setContentsMargins(4, 0, 0, 0)
        content_header_layout.setSpacing(10)

        content_header_text = QVBoxLayout()
        content_header_text.setContentsMargins(0, 0, 0, 0)
        content_header_text.setSpacing(2)

        self.content_header_title = QLabel("창 설정")
        self.content_header_title.setObjectName("ContentHeaderTitle")
        content_header_text.addWidget(self.content_header_title)

        self.content_header_meta = QLabel("창 위치와 크기를 조정합니다.")
        self.content_header_meta.setObjectName("ContentHeaderMeta")
        self.content_header_meta.setWordWrap(True)
        content_header_text.addWidget(self.content_header_meta)

        content_header_layout.addLayout(content_header_text, 1)
        content_header_layout.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("CloseButton")
        close_btn.clicked.connect(self._cancel_settings)
        content_header_layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        content_layout.addWidget(content_header)

        self.content_stack = QStackedWidget()
        self.content_stack.currentChanged.connect(self._on_tab_changed)
        content_layout.addWidget(self.content_stack)

        self._add_section(
            "창 설정",
            "창 위치와 크기, 언어",
            self._create_window_tab(),
            title_key="settings.section.window.title",
            description_key="settings.section.window.description",
        )
        self._add_section(
            "테마 설정",
            "라이트/다크와 팔레트",
            self._create_theme_tab(),
            title_key="settings.section.theme.title",
            description_key="settings.section.theme.description",
        )
        self._add_section(
            "모델 설정",
            "배치와 Live2D 경로",
            self._create_model_tab(),
            title_key="settings.section.model.title",
            description_key="settings.section.model.description",
        )
        self._add_section(
            "LLM 설정",
            "공급자와 응답 스타일",
            self._create_llm_tab(),
            title_key="settings.section.llm.title",
            description_key="settings.section.llm.description",
        )
        self._add_section(
            "TTS 설정",
            "공급자와 음성 합성 구성",
            self._create_tts_tab(),
            title_key="settings.section.tts.title",
            description_key="settings.section.tts.description",
        )
        self._add_section(
            "동작 설정",
            "버튼, PTT, 감지 옵션",
            self._create_behavior_tab(),
            title_key="settings.section.behavior.title",
            description_key="settings.section.behavior.description",
        )
        self._add_lazy_tab(
            "memory",
            "기억 관리",
            "기억 목록과 검색 설정",
            self._create_memory_tab,
            title_key="settings.section.memory.title",
            description_key="settings.section.memory.description",
        )
        self._add_lazy_tab(
            "topic_memory",
            "주제 기억 관리",
            "키워드 단서 지도",
            self._create_topic_memory_tab,
            title_key="settings.section.topic_memory.title",
            description_key="settings.section.topic_memory.description",
        )
        self._add_lazy_tab(
            "profile",
            "사용자 기억 관리",
            "user_profile.json 구조 편집",
            self._create_user_profile_tab,
            title_key="settings.section.profile.title",
            description_key="settings.section.profile.description",
        )
        self._add_lazy_tab(
            "ene_profile",
            "ENE 기억 관리",
            "에네 자기 정보 구조 편집",
            self._create_ene_profile_tab,
            title_key="settings.section.ene_profile.title",
            description_key="settings.section.ene_profile.description",
        )
        self._add_lazy_tab(
            "prompt",
            "프롬프트 설정",
            "프롬프트와 감정 규칙",
            self._create_prompt_tab,
            title_key="settings.section.prompt.title",
            description_key="settings.section.prompt.description",
        )
        self._set_section_index(0)

        workspace_row.addWidget(sidebar_shell)
        workspace_row.addWidget(content_shell, 1)
        layout.addLayout(workspace_row, 1)

        layout.addWidget(self._build_footer_note())

    def _build_footer_note(self):
        card = QFrame()
        card.setObjectName("FooterCard")
        footer_layout = QHBoxLayout(card)
        footer_layout.setContentsMargins(18, 16, 18, 16)
        footer_layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        title = QLabel("설정 적용 안내")
        self._bind_widget_text(title, "settings.footer.title", "설정 적용 안내")
        title.setObjectName("FooterTitle")
        text_col.addWidget(title)

        body = QLabel("변경사항은 저장 전까지 미리보기로만 반영됩니다. 취소하면 이전 설정으로 돌아가며, 일부 LLM 설정은 저장 후 다시 시작해야 완전히 반영됩니다.")
        self._bind_widget_text(
            body,
            "settings.footer.body",
            "변경사항은 저장 전까지 미리보기로만 반영됩니다. 취소하면 이전 설정으로 돌아가며, 일부 LLM 설정은 저장 후 다시 시작해야 완전히 반영됩니다.",
        )
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        text_col.addWidget(body)
        footer_layout.addLayout(text_col, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.setContentsMargins(0, 0, 0, 0)

        cancel_btn = QPushButton("취소")
        self._bind_widget_text(cancel_btn, "settings.footer.cancel", "취소")
        cancel_btn.clicked.connect(self._cancel_settings)
        action_row.addWidget(cancel_btn)

        save_btn = QPushButton("변경사항 저장")
        self._bind_widget_text(save_btn, "settings.footer.save", "변경사항 저장")
        save_btn.setProperty("accent", True)
        save_btn.style().unpolish(save_btn)
        save_btn.style().polish(save_btn)
        save_btn.clicked.connect(self._save_settings)
        action_row.addWidget(save_btn)

        footer_layout.addLayout(action_row, 0)
        return card

    def _build_hint_label(self, text: str, *, key: str | None = None):
        label = QLabel(text)
        label.setObjectName("InlineHint")
        label.setWordWrap(True)
        if key:
            self._register_text_binding(label.setText, key, text)
        return label

    def _build_section_nav_card(self, title: str, description: str, index: int) -> ClickableFrame:
        card = ClickableFrame()
        card.setObjectName("NavItemCard")
        card.setProperty("selected", "false")
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("NavItemTitle")
        layout.addWidget(title_label)

        meta_label = QLabel(description)
        meta_label.setObjectName("NavItemMeta")
        meta_label.setWordWrap(True)
        layout.addWidget(meta_label)

        card.clicked.connect(lambda idx=index: self._set_section_index(idx))
        self._section_nav_cards[index] = card
        self._section_nav_titles[index] = title_label
        self._section_nav_meta[index] = meta_label
        return card

    def _add_section(
        self,
        title: str,
        description: str,
        widget: QWidget,
        *,
        title_key: str | None = None,
        description_key: str | None = None,
    ) -> int:
        index = self.content_stack.addWidget(widget)
        self._section_header_map[index] = (title, description)
        self._section_text_meta[index] = (
            title_key or "",
            title,
            description_key or "",
            description,
        )
        nav_layout = self.section_nav_container.layout()
        if nav_layout is not None:
            nav_layout.addWidget(self._build_section_nav_card(title, description, index))
        return index

    def _set_section_index(self, index: int) -> None:
        if not hasattr(self, "content_stack"):
            return
        if index < 0 or index >= self.content_stack.count():
            return
        self.content_stack.setCurrentIndex(index)
        self._update_section_nav_selection(index)

    def _update_section_nav_selection(self, current_index: int) -> None:
        for index, card in self._section_nav_cards.items():
            card.setProperty("selected", "true" if index == current_index else "false")
            card.style().unpolish(card)
            card.style().polish(card)

        title, description = self._section_header_map.get(
            current_index,
            (
                self._translated_text("settings.sidebar.title", "ENE 설정"),
                self._translated_text("settings.content.placeholder", "섹션을 선택해 세부 설정을 조정합니다."),
            ),
        )
        if hasattr(self, "content_header_title"):
            self.content_header_title.setText(title)
        if hasattr(self, "content_header_meta"):
            self.content_header_meta.setText(description)

    def focus_section(self, tab_id: str) -> None:
        index = next((idx for idx, current_tab_id in self._lazy_tab_index_to_id.items() if current_tab_id == tab_id), -1)
        if index >= 0:
            self._set_section_index(index)

    def _add_lazy_tab(
        self,
        tab_id: str,
        title: str,
        description: str,
        builder,
        *,
        title_key: str | None = None,
        description_key: str | None = None,
    ) -> None:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(10, 10, 10, 10)
        host_layout.setSpacing(12)

        card = QFrame()
        card.setObjectName("FooterCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("FooterTitle")
        card_layout.addWidget(title_label)

        body_label = QLabel(description)
        body_label.setObjectName("FooterBody")
        body_label.setWordWrap(True)
        card_layout.addWidget(body_label)
        self._lazy_tab_header_labels[tab_id] = (title_label, body_label)

        host_layout.addWidget(card)
        host_layout.addStretch()

        index = self._add_section(
            title,
            description,
            host,
            title_key=title_key,
            description_key=description_key,
        )
        self._lazy_tab_hosts[tab_id] = host
        self._lazy_tab_builders[tab_id] = builder
        self._lazy_tab_index_to_id[index] = tab_id

    def _on_tab_changed(self, index: int) -> None:
        self._update_section_nav_selection(index)
        tab_id = self._lazy_tab_index_to_id.get(index)
        if tab_id:
            self._ensure_lazy_tab_loaded(tab_id)

    def _ensure_lazy_tab_loaded(self, tab_id: str) -> None:
        if tab_id in self._lazy_tab_loaded:
            return

        host = self._lazy_tab_hosts.get(tab_id)
        builder = self._lazy_tab_builders.get(tab_id)
        if host is None or builder is None:
            return

        built_widget = builder()
        layout = host.layout()
        if layout is None:
            return

        self._lazy_tab_header_labels.pop(tab_id, None)
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        layout.addWidget(built_widget)
        self._install_no_wheel_handlers(built_widget)
        self._lazy_tab_loaded.add(tab_id)

    def _build_secret_row(self, line_edit: QLineEdit, toggle_handler, button_attr_name: str):
        line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(line_edit, 1)

        toggle_btn = QPushButton(self._localized_secret_toggle_text(True))
        toggle_btn.setMinimumWidth(72)
        toggle_btn.clicked.connect(toggle_handler)
        setattr(self, button_attr_name, toggle_btn)
        self._secret_toggle_pairs.append((line_edit, toggle_btn))
        layout.addWidget(toggle_btn)
        return row

    def _toggle_secret_field(self, line_edit: QLineEdit, button: QPushButton):
        is_password = line_edit.echoMode() == QLineEdit.EchoMode.Password
        line_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if is_password else QLineEdit.EchoMode.Password
        )
        button.setText(self._localized_secret_toggle_text(not is_password))
