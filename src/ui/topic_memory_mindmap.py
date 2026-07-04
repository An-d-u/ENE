from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.ai.knowledge_map_types import TopicMemoryClue, TopicMemoryTopic
from src.core.i18n import tr as t
from src.ui.topic_memory_mindmap_model import (
    MindmapNode,
    TopicMemoryGraph,
    build_topic_memory_graph,
)


class _MindmapNodeItem(QGraphicsEllipseItem):
    def __init__(
        self,
        rect: QRectF,
        *,
        node_id: str,
        on_select: Callable[[str], None],
        brush: QBrush,
        pen: QPen,
    ):
        super().__init__(rect)
        self._node_id = node_id
        self._on_select = on_select
        self.setBrush(brush)
        self.setPen(pen)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, True)

    def mousePressEvent(self, event):
        self._on_select(self._node_id)
        super().mousePressEvent(event)


class TopicMemoryMindmapPanel(QWidget):
    def __init__(self, manager: Any | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self._graph: TopicMemoryGraph | None = None
        self._selected_node_id: str | None = None
        self._last_load_error: str | None = None

        self.search_input = QLineEdit()
        self.state_filter = QComboBox()
        self.refresh_btn = QPushButton()
        self.summary_label = QLabel()
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.detail_title = QLabel()
        self.detail_body = QTextBrowser()

        self._setup_ui()
        self.retranslate_ui()
        self.search_input.textChanged.connect(self._rebuild_graph)
        self.state_filter.currentIndexChanged.connect(self._rebuild_graph)
        self.refresh_btn.clicked.connect(self.refresh)
        self._rebuild_graph()

    def _setup_ui(self) -> None:
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setMinimumHeight(320)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.detail_title.setWordWrap(True)
        self.detail_title.setObjectName("topicMemoryMindmapDetailTitle")
        self.detail_body.setReadOnly(True)
        self.detail_body.setOpenExternalLinks(False)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.search_input, 1)
        controls_layout.addWidget(self.state_filter)
        controls_layout.addWidget(self.refresh_btn)

        detail_frame = QFrame()
        detail_frame.setFrameShape(QFrame.Shape.StyledPanel)
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_body, 1)

        body_layout = QHBoxLayout()
        body_layout.addWidget(self.view, 3)
        body_layout.addWidget(detail_frame, 2)

        root_layout = QVBoxLayout(self)
        root_layout.addLayout(controls_layout)
        root_layout.addWidget(self.summary_label)
        root_layout.addLayout(body_layout, 1)

    def refresh(self) -> None:
        load = getattr(self.manager, "load", None)
        if self.manager is None or not callable(load):
            self._last_load_error = None
            self._set_unavailable_detail()
            return

        try:
            loaded_manager = load()
        except Exception as exc:
            self._last_load_error = str(exc)
            self._set_error_detail()
            return

        if loaded_manager is not None:
            self.manager = loaded_manager
        self._last_load_error = None
        self._refresh_state_filter_items()
        self._rebuild_graph()

    def retranslate_ui(self) -> None:
        self.search_input.setPlaceholderText(t("memory.topic_map.search.placeholder"))
        self.refresh_btn.setText(t("memory.topic_map.refresh"))
        self._refresh_state_filter_items()
        if self._graph is None:
            self._set_empty_summary()
        elif self._last_load_error is None:
            selected_node_id = self._selected_node_id
            self._rebuild_graph()
            if (
                selected_node_id
                and self._graph is not None
                and selected_node_id in self._graph.nodes
            ):
                self._select_node(selected_node_id)
        else:
            self._set_summary(self._graph.total_topics, self._graph.total_clues)

        if self._last_load_error is not None:
            self._set_error_detail()
        elif self._selected_node_id:
            self._select_node(self._selected_node_id)
        elif self._graph is None or self._graph.total_topics == 0:
            self._set_empty_detail()

    def _refresh_state_filter_items(self) -> None:
        previous = self._current_state_filter()
        states = sorted(
            {
                clue.state
                for topic in self._topics()
                for clue in getattr(topic, "clues", [])
                if getattr(clue, "state", "")
            },
            key=str.casefold,
        )

        self.state_filter.blockSignals(True)
        self.state_filter.clear()
        self.state_filter.addItem(t("memory.topic_map.state.all"), "all")
        for state in states:
            self.state_filter.addItem(state, state)
        index = self.state_filter.findData(previous)
        self.state_filter.setCurrentIndex(index if index >= 0 else 0)
        self.state_filter.blockSignals(False)

    def _rebuild_graph(self) -> None:
        self._graph = build_topic_memory_graph(
            self._topics(),
            query=self.search_input.text(),
            state_filter=self._current_state_filter(),
            root_label=t("memory.topic_map.root.label"),
            fallback_clue_label=t("memory.topic_map.clue.fallback"),
        )

        self.scene.clear()
        self._render_edges(self._graph)
        self._render_nodes(self._graph)
        self._set_summary(self._graph.total_topics, self._graph.total_clues)

        first_topic_id = next(
            (node.id for node in self._graph.nodes.values() if node.kind == "topic"),
            None,
        )
        if first_topic_id is None:
            self._selected_node_id = None
            self._set_empty_detail()
        else:
            self._select_node(first_topic_id)
        if self._last_load_error is not None:
            self._set_error_detail()

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-48, -48, 48, 48))

    def _render_edges(self, graph: TopicMemoryGraph) -> None:
        for edge in graph.edges:
            source = graph.nodes.get(edge.source_id)
            target = graph.nodes.get(edge.target_id)
            if source is None or target is None:
                continue
            pen = QPen(QColor("#9ca3af"))
            pen.setWidthF(1.4)
            if edge.kind == "shared":
                pen.setColor(QColor("#cbd5e1"))
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidthF(1.0)
            item = QGraphicsLineItem(source.x, source.y, target.x, target.y)
            item.setPen(pen)
            item.setZValue(-1)
            self.scene.addItem(item)

    def _render_nodes(self, graph: TopicMemoryGraph) -> None:
        for node in graph.nodes.values():
            radius = self._node_radius(node)
            rect = QRectF(node.x - radius, node.y - radius, radius * 2, radius * 2)
            item = _MindmapNodeItem(
                rect,
                node_id=node.id,
                on_select=self._select_node,
                brush=QBrush(self._node_color(node)),
                pen=QPen(QColor("#334155"), 1.5),
            )
            item.setZValue(1)
            self.scene.addItem(item)

            label = QGraphicsTextItem(_short_label(node.label))
            label.setDefaultTextColor(QColor("#111827"))
            label.setTextWidth(radius * 2.4)
            label.setPos(node.x - radius * 1.2, node.y + radius + 4)
            label.setZValue(2)
            self.scene.addItem(label)

    def _select_node(self, node_id: str) -> None:
        if self._graph is None:
            return
        node = self._graph.nodes.get(node_id)
        if node is None:
            self._set_empty_detail()
            return

        self._selected_node_id = node_id
        if node.kind == "topic" and node.topic_id:
            topic = self._graph.topic_index.get(node.topic_id)
            if topic is not None:
                self._set_topic_detail(topic, self._visible_clues_for_topic(topic.id))
                return
        if node.kind == "clue":
            clue = self._graph.clue_index.get(node_id)
            topic = self._graph.topic_index.get(node.topic_id or "")
            if clue is not None:
                self._set_clue_detail(clue, topic)
                return
        self._set_empty_detail()

    def _visible_clues_for_topic(self, topic_id: str) -> list[TopicMemoryClue]:
        if self._graph is None:
            return []
        return [
            self._graph.clue_index[node.id]
            for node in self._graph.nodes.values()
            if node.kind == "clue"
            and node.topic_id == topic_id
            and node.id in self._graph.clue_index
        ]

    def _set_topic_detail(self, topic: TopicMemoryTopic, clues: list[TopicMemoryClue]) -> None:
        lines = []
        if topic.aliases:
            lines.append(f"{t('memory.topic_map.detail.aliases')}: {', '.join(topic.aliases)}")
        if topic.retrieval_terms:
            lines.append(
                f"{t('memory.topic_map.detail.retrieval_terms')}: {', '.join(topic.retrieval_terms)}"
            )
        if clues:
            lines.append("")
            lines.extend(f"- {clue.subject}: {clue.text}" for clue in clues)
        self.detail_title.setText(topic.keyword)
        self.detail_body.setPlainText("\n".join(lines).strip())

    def _set_clue_detail(
        self,
        clue: TopicMemoryClue,
        topic: TopicMemoryTopic | None,
    ) -> None:
        title_prefix = topic.keyword if topic is not None else clue.subject
        lines = [
            f"{t('memory.topic_map.detail.state')}: {clue.state}",
            f"{t('memory.topic_map.detail.type')}: {clue.type}",
            f"{t('memory.topic_map.detail.confidence')}: {clue.confidence:.2f}",
        ]
        if clue.source_memory_id:
            lines.append(f"{t('memory.topic_map.detail.source')}: {clue.source_memory_id}")
        if clue.text:
            lines.extend(["", clue.text])
        if clue.history:
            lines.append("")
            lines.append(t("memory.topic_map.detail.history"))
            lines.extend(f"- {item.state}: {item.text}" for item in clue.history)
        self.detail_title.setText(f"{title_prefix} - {clue.subject}")
        self.detail_body.setPlainText("\n".join(lines).strip())

    def _set_summary(self, topics: int, clues: int) -> None:
        self.summary_label.setText(t("memory.topic_map.summary", topics=topics, clues=clues))

    def _set_empty_summary(self) -> None:
        self._set_summary(0, 0)

    def _set_empty_detail(self) -> None:
        self.detail_title.setText(t("memory.topic_map.empty.title"))
        self.detail_body.setPlainText(t("memory.topic_map.empty.body"))

    def _set_unavailable_detail(self) -> None:
        self.detail_title.setText(t("memory.topic_map.unavailable.title"))
        self.detail_body.setPlainText(t("memory.topic_map.unavailable.body"))

    def _set_error_detail(self) -> None:
        error = self._last_load_error or ""
        self.detail_title.setText(t("memory.topic_map.error.title"))
        self.detail_body.setPlainText(t("memory.topic_map.error.body", error=error))

    def _topics(self) -> list[TopicMemoryTopic]:
        topics = getattr(self.manager, "topics", []) if self.manager is not None else []
        return list(topics or [])

    def _current_state_filter(self) -> str:
        value = self.state_filter.currentData()
        return str(value or "all")

    def _node_radius(self, node: MindmapNode) -> float:
        if node.kind == "root":
            return 28.0
        if node.kind == "topic":
            return 36.0
        return 22.0

    def _node_color(self, node: MindmapNode) -> QColor:
        if node.kind == "root":
            return QColor("#f8fafc")
        if node.kind == "topic":
            return QColor("#bfdbfe")
        return QColor("#dcfce7")


def _short_label(label: str, *, max_length: int = 24) -> str:
    text = str(label or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."
