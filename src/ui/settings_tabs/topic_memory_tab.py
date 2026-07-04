"""설정 창의 주제 기억 관리 탭 빌더."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..topic_memory_mindmap import TopicMemoryMindmapPanel


def build_topic_memory_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(12)

    knowledge_map_manager = getattr(self._bridge, "knowledge_map_manager", None) if self._bridge else None
    panel = TopicMemoryMindmapPanel(knowledge_map_manager, widget)
    self._embedded_topic_memory_panel = panel
    layout.addWidget(panel)

    if knowledge_map_manager is None:
        card = QFrame()
        card.setObjectName("FooterCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(8)

        title = QLabel()
        self._bind_widget_text(title, "settings.topic_memory.empty.title", "주제 기억 관리")
        title.setObjectName("FooterTitle")
        card_layout.addWidget(title)

        body = QLabel()
        self._bind_widget_text(
            body,
            "settings.topic_memory.empty.body",
            "주제 기억 매니저가 초기화되지 않아 저장된 주제 기억을 표시할 수 없습니다.",
        )
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        card_layout.addWidget(body)
        layout.addWidget(card)

    scroll.setWidget(widget)
    return scroll
