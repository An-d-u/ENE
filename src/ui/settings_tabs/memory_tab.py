"""
메모리 설정 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..memory_dialog import MemoryDialog


def build_memory_tab(dialog):
    self = dialog
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(12)

    tabs = QTabWidget()
    tabs.setObjectName("memoryManagementTabs")
    _add_translated_tab(
        self,
        tabs,
        _build_long_term_memory_tab(self),
        "settings.memory.tabs.long_term",
        "장기 기억",
    )

    from . import ene_profile_tab, topic_memory_tab, user_profile_tab

    _add_translated_tab(
        self,
        tabs,
        topic_memory_tab.build_topic_memory_tab(self),
        "settings.memory.tabs.topic",
        "주제 기억",
    )
    _add_translated_tab(
        self,
        tabs,
        user_profile_tab.build_user_profile_tab(self),
        "settings.memory.tabs.user_profile",
        "사용자 기억",
    )
    _add_translated_tab(
        self,
        tabs,
        ene_profile_tab.build_ene_profile_tab(self),
        "settings.memory.tabs.ene_profile",
        "ENE 기억",
    )
    layout.addWidget(tabs)
    return widget


def _add_translated_tab(dialog, tabs: QTabWidget, widget: QWidget, key: str, fallback: str) -> None:
    index = tabs.addTab(widget, _tab_text(dialog, key, fallback))
    register = getattr(dialog, "_register_text_binding", None)
    if callable(register):
        register(lambda text, tab_index=index: tabs.setTabText(tab_index, text), key, fallback)


def _tab_text(dialog, key: str, fallback: str) -> str:
    translator = getattr(dialog, "_translated_text", None)
    return translator(key, fallback) if callable(translator) else fallback


def _build_long_term_memory_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(12)

    search_card = QFrame()
    search_card.setObjectName("FooterCard")
    search_layout = QVBoxLayout(search_card)
    search_layout.setContentsMargins(20, 18, 20, 18)
    search_layout.setSpacing(10)

    title = QLabel()
    self._bind_widget_text(title, "settings.memory.search_scope.title", "기억 검색 범위")
    title.setObjectName("FooterTitle")
    search_layout.addWidget(title)

    body = QLabel()
    self._bind_widget_text(
        body,
        "settings.memory.search_scope.body",
        "장기기억 검색 시 최신 사용자 메시지와 함께 참고할 최근 보이는 대화 턴 수를 조절합니다. 현재 턴에만 임시 주입되고, 히스토리에는 순수 대화만 남도록 동작합니다.",
    )
    body.setObjectName("FooterBody")
    body.setWordWrap(True)
    search_layout.addWidget(body)

    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(10)

    self.memory_search_recent_turns_spin = QSpinBox()
    self.memory_search_recent_turns_spin.setRange(0, 50)
    self._bind_suffix(self.memory_search_recent_turns_spin, "settings.memory.search_scope.turns.suffix", " 턴")
    self._bind_special_value_text(
        self.memory_search_recent_turns_spin,
        "settings.memory.search_scope.turns.special",
        "현재 메시지만",
    )
    self.memory_search_recent_turns_spin.valueChanged.connect(self._on_setting_changed)
    try:
        memory_turns = int(self._original_settings.get("memory_search_recent_turns", 2) or 0)
    except Exception:
        memory_turns = 2
    self.memory_search_recent_turns_spin.setValue(max(0, min(memory_turns, 50)))
    self._add_form_row(
        form,
        "settings.memory.search_scope.turns.label",
        "검색에 포함할 최근 대화:",
        self.memory_search_recent_turns_spin,
    )
    form.addRow(
        self._build_hint_label(
            "예: 2턴이면 직전 사용자/에네 2쌍을 보고 현재 메시지와 함께 장기기억을 검색합니다.",
            key="settings.memory.search_scope.turns.hint",
        )
    )

    search_layout.addLayout(form)
    layout.addWidget(search_card)

    if self._memory_manager:
        knowledge_map_manager = getattr(self._bridge, "knowledge_map_manager", None) if self._bridge else None
        panel = MemoryDialog(
            self._memory_manager,
            self._bridge,
            self,
            embedded=True,
            knowledge_map_manager=knowledge_map_manager,
        )
        panel.apply_theme(dict(self._theme_values))
        self._embedded_memory_panel = panel
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        panel.setMinimumSize(0, 0)
        layout.addWidget(panel)
    else:
        card = QFrame()
        card.setObjectName("FooterCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(8)

        title = QLabel()
        self._bind_widget_text(title, "settings.memory.empty.title", "기억 관리")
        title.setObjectName("FooterTitle")
        card_layout.addWidget(title)

        body = QLabel()
        self._bind_widget_text(
            body,
            "settings.memory.empty.body",
            "메모리 매니저가 초기화되지 않아 기억 목록 패널을 표시할 수 없습니다.",
        )
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        card_layout.addWidget(body)
        layout.addWidget(card)

    layout.addStretch()
    scroll.setWidget(widget)
    return scroll
