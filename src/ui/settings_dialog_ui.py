"""
설정 대화상자 기본 UI 조립 mixin.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QScrollArea,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .settings_dialog_widgets import ToggleSwitch


# 탐색 순서와 지연 로딩 페이지의 식별자는 외부에서 여는 바로가기에도 쓰인다.
_SECTIONS = (
    ("window", "display", "창 설정", "창 위치와 크기, 언어", "\ue737", "#f6e5d8", "#925b35", QStyle.StandardPixmap.SP_DesktopIcon),
    ("theme", "display", "테마 설정", "라이트·다크 모드와 색상 팔레트", "\ue790", "#efe1f6", "#825493", QStyle.StandardPixmap.SP_DialogApplyButton),
    ("model", "display", "모델 설정", "아바타 배치, 표정과 제스처, 터치 반응", "\ue7b8", "#e2eee6", "#496e55", QStyle.StandardPixmap.SP_ComputerIcon),
    ("llm", "conversation", "LLM 설정", "공급자와 인증, 모델, 웹 검색과 임베딩", "\ue8bd", "#e4e9f8", "#576b9f", QStyle.StandardPixmap.SP_MessageBoxInformation),
    ("tts", "conversation", "음성 설정", "음성 합성과 재생 기기, 마이크 입력 단축키", "\ue767", "#f5e1eb", "#92546d", QStyle.StandardPixmap.SP_MediaVolume),
    ("behavior", "conversation", "동작 설정", "대화창 표시, ENE의 반응, 상황 감지와 기록", "\ue9e9", "#eee5da", "#846642", QStyle.StandardPixmap.SP_FileDialogDetailedView),
    ("memory", "memory", "기억 관리", "장기 기억, 주제 기억, 사용자와 ENE의 기억", "\ue82d", "#e4e5f8", "#666296", QStyle.StandardPixmap.SP_DirOpenIcon),
    ("prompt", "memory", "프롬프트 설정", "기본 지침, 생활 환경과 감정 규칙", "\ue70f", "#e3edef", "#4c727b", QStyle.StandardPixmap.SP_FileIcon),
)
_NAV_GROUPS = {"display": "화면", "conversation": "대화", "memory": "기억과 지침"}


def _tinted_surface(base, accent, amount):
    surface, ink = QColor(base), QColor(accent)
    channels = [round(a + (b - a) * amount) for a, b in zip(surface.getRgb()[:3], ink.getRgb()[:3])]
    return QColor(*channels).name()


def _navigation_icon(widget, glyph, background, foreground, fallback):
    family = "Segoe MDL2 Assets"
    if family not in QFontDatabase.families():
        return widget.style().standardIcon(fallback)
    scale = widget.devicePixelRatioF()
    pixmap = QPixmap(round(26 * scale), round(26 * scale))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    box = QRectF(0, 0, 26, 26)
    painter.drawRoundedRect(box, 7, 7)
    font = QFont(family)
    font.setPixelSize(15)
    painter.setFont(font)
    painter.setPen(QColor(foreground))
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


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
        accent_soft = self._theme_rgba(accent, 0.10)
        accent_soft_strong = self._theme_rgba(accent, 0.18)
        accent_border = self._theme_rgba(accent, 0.22)
        accent_focus = self._theme_rgba(accent, 0.55)
        accent_slider = self._theme_rgba(accent, 0.80)
        accent_slider_hover = self._theme_rgba(accent, 1.0)
        accent_dropdown = self._theme_rgba(accent, 0.12)
        style = """
        QDialog { background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; font-family: 'Segoe UI Variable', 'Malgun Gothic', sans-serif; }
        QDialog#SettingsStudio { background: transparent; }
        QWidget { background: transparent; }
        #MainFrame { background: __SETTINGS_WINDOW__; border: 1px solid __WINDOW_BORDER__; border-radius: 17px; }
        #TitleBar { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 __TINT__, stop:0.52 __SETTINGS_CARD__, stop:1 __WASH__); border-bottom: 1px solid __CARD_BORDER__; border-top-left-radius: 16px; border-top-right-radius: 16px; }
        #BrandName { font-size: 22px; font-weight: 800; color: __PRIMARY_TEXT__; }
        #BrandDivider { background: __CARD_BORDER__; }
        #CloseButton { background: transparent; border: none; color: __MUTED_TEXT__; min-width: 0; min-height: 0; padding: 0; border-radius: 8px; font-size: 20px; }
        #CloseButton:hover { background: __PRIMARY_TEXT_SOFT__; color: __PRIMARY_TEXT__; }
        #SidebarShell { border: none; border-right: 1px solid __CARD_BORDER__; }
        #SidebarMenu { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 __TINT__, stop:0.55 __SETTINGS_INPUT__, stop:1 __WASH__); }
        #NavGroup { color: __MUTED_TEXT__; padding: 0 9px 4px; font-size: 12px; font-weight: 600; }
        QPushButton#NavItem { text-align: left; color: __PRIMARY_TEXT__; background: transparent; min-height: 37px; padding: 0 8px; border: 1px solid transparent; border-radius: 9px; }
        QPushButton#NavItem:hover { background: __ACCENT_SOFT__; }
        QPushButton#NavItem:checked { background: __SETTINGS_CARD__; border-color: __ACCENT_BORDER__; font-weight: 700; }
        QPushButton#NavItem:focus { border-color: __ACCENT_FOCUS__; }
        #ContentShell { background: __SETTINGS_WINDOW__; }
        #Breadcrumb { color: __TITLE_MUTED__; font-size: 11px; font-weight: 600; }
        #ContentHeaderTitle { color: __WINDOW_TEXT__; font-size: 29px; font-weight: 750; }
        #ContentHeaderMeta { color: __TITLE_MUTED__; font-size: 13px; }
        #SettingsFooter { background: __SETTINGS_CARD__; border-top: 1px solid __CARD_BORDER__; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; }
        #FooterCard { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 14px; }
        #FooterTitle { color: __PRIMARY_TEXT__; font-size: 15px; font-weight: 700; }
        #FooterBody, #InlineHint { color: __MUTED_TEXT__; font-size: 12px; }
        #ValueBadge { color: __PRIMARY_TEXT__; font-size: 13px; font-weight: 700; background: __SETTINGS_INPUT__; border: 1px solid __INPUT_BORDER__; border-radius: 8px; padding: 5px 9px; }
        QTabWidget::pane { background: transparent; border: none; }
        QTabWidget::tab-bar { alignment: left; }
        QTabBar::tab { background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; border: 1px solid __CARD_BORDER__; border-radius: 9px; margin: 0 4px 6px 0; padding: 7px 12px; }
        QTabBar::tab:hover { border-color: __ACCENT_BORDER__; }
        QTabBar::tab:selected { color: __ACCENT_TEXT__; background: __ACCENT__; border-color: __ACCENT__; font-weight: 700; }

        QLabel, QCheckBox { color: __PRIMARY_TEXT__; font-size: 13px; }
        QCheckBox { spacing: 0px; background: transparent; }
        QGroupBox { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 14px; padding: 30px 12px 8px; margin: 0; font-size: 14px; font-weight: 700; color: __PRIMARY_TEXT__; }
        QGroupBox::title { subcontrol-origin: border; subcontrol-position: top left; left: 16px; top: 9px; padding: 0; color: __PRIMARY_TEXT__; }
        QPushButton { min-height: 32px; padding: 0 13px; border-radius: 9px; border: 1px solid __CARD_BORDER__; background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; font-size: 13px; font-weight: 600; }
        QPushButton:focus { border-color: __ACCENT_FOCUS__; }
        QPushButton:hover { background: __SETTINGS_INPUT__; }
        QPushButton:disabled { background: __SETTINGS_CARD__; color: __DISABLED_TEXT__; }
        QPushButton[accent='true'] { background: __ACCENT__; color: __ACCENT_TEXT__; border: 1px solid __ACCENT__; }
        QPushButton[accent='true']:hover { background: __ACCENT_HOVER__; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { min-height: 32px; padding: 0 9px; border-radius: 8px; background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; font-size: 13px; selection-background-color: __ACCENT_SOFT_STRONG__; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid __ACCENT_FOCUS__; background: __SETTINGS_INPUT__; }
        QPlainTextEdit { background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; border-radius: 10px; padding: 10px; font-size: 13px; font-family: 'Consolas', 'D2Coding', 'Malgun Gothic', monospace; selection-background-color: __ACCENT_SOFT_STRONG__; }
        QPlainTextEdit:focus { border: 1px solid __ACCENT_FOCUS__; background: __SETTINGS_INPUT__; }
        QListWidget { background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; border-radius: 10px; padding: 6px; outline: none; }
        QListWidget::item { color: __INPUT_TEXT__; background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 7px 10px; margin: 2px 0; }
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
            .replace("__WINDOW_TEXT__", self._theme_text_color(settings_window))
            .replace("__TINT__", _tinted_surface(settings_card, accent, 0.055))
            .replace("__WASH__", _tinted_surface(settings_card, accent, 0.12))
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
        if getattr(self, "_together_panel", None) is not None:
            self._together_panel.apply_theme(dict(self._theme_values))
        if self._embedded_memory_panel is not None:
            self._embedded_memory_panel.apply_theme(dict(self._theme_values))
        if self._embedded_topic_memory_panel is not None:
            self._embedded_topic_memory_panel.apply_theme(dict(self._theme_values))

    def _setup_ui(self):
        self.setObjectName("SettingsStudio")
        self._apply_stylesheet()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(7, 7, 7, 7)
        self.main_frame = QFrame()
        self.main_frame.setObjectName("MainFrame")
        outer.addWidget(self.main_frame)
        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("TitleBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(18, 7, 12, 7)
        bar_layout.setSpacing(10)
        avatar = QLabel()
        avatar.setPixmap(self.windowIcon().pixmap(32, 32))
        bar_layout.addWidget(avatar)
        brand = QLabel("ENE")
        brand.setObjectName("BrandName")
        bar_layout.addWidget(brand)
        divider = QFrame()
        divider.setObjectName("BrandDivider")
        divider.setFixedSize(1, 16)
        bar_layout.addWidget(divider)
        title = QLabel()
        self._bind_widget_text(title, "settings.navigation.title", "환경설정")
        bar_layout.addWidget(title)
        bar_layout.addStretch()
        self.section_picker = QComboBox()
        self.section_picker.setObjectName("SectionPicker")
        self._register_text_binding(self.section_picker.setAccessibleName, "settings.navigation.menu", "설정 메뉴")
        bar_layout.addWidget(self.section_picker)
        close = QPushButton("×")
        close.setObjectName("CloseButton")
        close.setFixedSize(32, 32)
        self._register_text_binding(close.setAccessibleName, "settings.navigation.close", "닫기")
        close.clicked.connect(self._cancel_settings)
        bar_layout.addWidget(close)
        layout.addWidget(bar)

        workspace = QHBoxLayout()
        workspace.setSpacing(0)
        layout.addLayout(workspace, 1)
        self.sidebar = QScrollArea()
        self.sidebar.setObjectName("SidebarShell")
        self.sidebar.setWidgetResizable(True)
        self.sidebar.setFixedWidth(180)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav = QWidget()
        nav.setObjectName("SidebarMenu")
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(10, 18, 10, 14)
        nav_layout.setSpacing(3)
        self.sidebar.setWidget(nav)
        workspace.addWidget(self.sidebar)

        panel = QFrame()
        panel.setObjectName("ContentShell")
        content = QVBoxLayout(panel)
        content.setContentsMargins(20, 16, 20, 12)
        content.setSpacing(3)
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("Breadcrumb")
        content.addWidget(self.breadcrumb)
        self.content_header_title = QLabel()
        self.content_header_title.setObjectName("ContentHeaderTitle")
        content.addWidget(self.content_header_title)
        self.content_header_meta = QLabel()
        self.content_header_meta.setObjectName("ContentHeaderMeta")
        self.content_header_meta.setWordWrap(True)
        content.addWidget(self.content_header_meta)
        content.addSpacing(9)
        self.content_stack = QStackedWidget()
        content.addWidget(self.content_stack, 1)
        workspace.addWidget(panel, 1)

        last_group = None
        for index, (key, group, title, description, glyph, bg, fg, fallback) in enumerate(_SECTIONS):
            if group != last_group:
                if last_group is not None:
                    nav_layout.addSpacing(13)
                heading = QLabel()
                heading.setObjectName("NavGroup")
                self._bind_widget_text(heading, f"settings.navigation.{group}", _NAV_GROUPS[group])
                nav_layout.addWidget(heading)
                last_group = group

            self._add_section(nav_layout, index, key, title, description, glyph, bg, fg, fallback)

        nav_layout.addStretch()
        self.section_picker.activated.connect(self._set_section_index)
        self.content_stack.currentChanged.connect(self._on_tab_changed)
        self._refresh_section_labels()
        layout.addWidget(self._build_footer_note())
        self._update_navigation_width()

    def _add_section(self, nav_layout, index, key, title, description, glyph, bg, fg, fallback):
        button = QPushButton()
        button.setObjectName("NavItem")
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setAutoDefault(False)
        button.setIcon(_navigation_icon(self, glyph, bg, fg, fallback))
        button.setIconSize(QSize(26, 26))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked, idx=index: self._set_section_index(idx))
        nav_layout.addWidget(button)
        self._section_nav_cards[index] = button
        self.section_picker.addItem(button.icon(), title)
        self._section_text_meta[index] = (
            f"settings.section.{key}.title", title, f"settings.section.{key}.description", description,
        )
        factory = getattr(self, f"_create_{key}_tab")
        if key in ("memory", "prompt"):
            host = QWidget()
            QVBoxLayout(host).setContentsMargins(0, 0, 0, 0)
            self._lazy_tab_hosts[key] = host
            self._lazy_tab_builders[key] = factory
            self._lazy_tab_index_to_id[index] = key
            self.content_stack.addWidget(host)
        else:
            self.content_stack.addWidget(factory())

    def _update_navigation_width(self):
        compact = self.width() < 860
        self.sidebar.setVisible(not compact)
        self.section_picker.setVisible(compact)

    def _build_footer_note(self):
        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(18, 9, 18, 9)
        row.setSpacing(8)
        status = QLabel()
        status.setObjectName("FooterBody")
        status.setWordWrap(True)
        self._bind_widget_text(status, "settings.navigation.preview", "변경사항은 저장 전까지 미리보기에 반영됩니다.")
        row.addWidget(status, 1)
        cancel = QPushButton()
        self._bind_widget_text(cancel, "settings.footer.cancel", "취소")
        cancel.clicked.connect(self._cancel_settings)
        row.addWidget(cancel)
        save = QPushButton()
        self._bind_widget_text(save, "settings.footer.save", "변경사항 저장")
        save.setProperty("accent", True)
        save.clicked.connect(self._save_settings)
        row.addWidget(save)
        return footer

    def _build_hint_label(self, text: str, *, key: str | None = None):
        label = QLabel(text)
        label.setObjectName("InlineHint")
        label.setWordWrap(True)
        if key:
            self._register_text_binding(label.setText, key, text)
        return label

    def _set_section_index(self, index: int) -> None:
        if 0 <= index < self.content_stack.count():
            self.content_stack.setCurrentIndex(index)

    def _update_section_nav_selection(self, index: int) -> None:
        self._section_nav_cards[index].setChecked(True)
        self.section_picker.setCurrentIndex(index)
        group = _SECTIONS[index][1]
        home = self._translated_text("settings.navigation.title", "환경설정")
        category = self._translated_text(f"settings.navigation.{group}", _NAV_GROUPS[group])
        self.breadcrumb.setText(f"{home}  ›  {category}")
        title, description = self._section_header_map[index]
        self.content_header_title.setText(title)
        self.content_header_meta.setText(description)

    def focus_section(self, tab_id: str) -> None:
        requested_section = tab_id
        memory_tab_id = {
            "together": "together",
            "topic_memory": "topic_memory",
            "profile": "profile_memory",
            "ene_profile": "profile_memory",
        }.get(tab_id)
        tab_id = {
            "together": "memory",
            "topic_memory": "memory",
            "profile": "memory",
            "ene_profile": "memory",
            "life_world": "prompt",
        }.get(tab_id, tab_id)
        index = next((idx for idx, section in enumerate(_SECTIONS) if section[0] == tab_id), -1)
        if index >= 0:
            self._set_section_index(index)
            if memory_tab_id:
                self._focus_memory_management_tab(memory_tab_id)
            elif requested_section == "life_world":
                self._ensure_lazy_tab_loaded("prompt")
                QTimer.singleShot(0, self._focus_life_world_editor)

    def _focus_life_world_editor(self) -> None:
        editor = getattr(self, "life_world_editor", None)
        if editor is None:
            return
        scroll = getattr(self, "_prompt_scroll", None)
        group = getattr(self, "_life_world_group", None)
        if scroll is not None and group is not None:
            scroll.ensureWidgetVisible(group, 12, 12)
        editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def _focus_memory_management_tab(self, tab_id: str) -> None:
        self._ensure_lazy_tab_loaded("memory")
        host = self._lazy_tab_hosts.get("memory")
        if host is None:
            return
        tabs = host.findChild(QTabWidget, "memoryManagementTabs")
        if tabs is None:
            return
        for index in range(tabs.count()):
            if tabs.tabBar().tabData(index) == tab_id:
                tabs.setCurrentIndex(index)
                return

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
