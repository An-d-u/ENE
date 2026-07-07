from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
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


class _GraphView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self._zoom_level = 0
        self._zoom_min = -5
        self._zoom_max = 8
        self._pending_fit = False
        self.setObjectName("topicMemoryGraphView")
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)

    def wheelEvent(self, event) -> None:
        if event.angleDelta().y() > 0 and self._zoom_level < self._zoom_max:
            factor = 1.15
            self._zoom_level += 1
        elif event.angleDelta().y() < 0 and self._zoom_level > self._zoom_min:
            factor = 1 / 1.15
            self._zoom_level -= 1
        else:
            event.accept()
            return
        self.scale(factor, factor)
        self._pending_fit = False
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pending_fit:
            self._fit_scene()

    def request_fit(self) -> None:
        self._pending_fit = True
        self._fit_scene()

    def _fit_scene(self) -> None:
        rect = self.scene().sceneRect()
        viewport_size = self.viewport().size()
        if rect.isEmpty() or viewport_size.width() < 80 or viewport_size.height() < 80:
            return
        self.resetTransform()
        self._zoom_level = 0
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._pending_fit = False

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#11151d"))
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        grid = 32
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)
        right = int(rect.right())
        bottom = int(rect.bottom())
        for x in range(left, right + grid, grid):
            for y in range(top, bottom + grid, grid):
                painter.drawPoint(x, y)


class _GraphItemPropertiesMixin:
    def __init__(self):
        self._graph_properties: dict[str, Any] = {}

    def setProperty(self, name: str, value: Any) -> None:
        self._graph_properties[name] = value

    def property(self, name: str) -> Any:
        return self._graph_properties.get(name)


class _MindmapEdgeItem(_GraphItemPropertiesMixin, QGraphicsPathItem):
    def __init__(
        self,
        source: MindmapNode,
        target: MindmapNode,
        *,
        kind: str,
        reason: str,
    ):
        _GraphItemPropertiesMixin.__init__(self)
        QGraphicsPathItem.__init__(self)
        self._kind = kind
        self._reason = reason
        self._path = _edge_path(source, target, kind)
        self.setPath(self._path)
        self.setToolTip(reason)
        self.apply_state("normal")

    def apply_state(self, state: str) -> None:
        self.setProperty("graphState", state)
        if self._kind == "shared":
            color = QColor("#7dd3fc") if state == "selected" else QColor("#64748b")
            alpha = 185 if state == "selected" else 95
            width = 1.9 if state == "selected" else 1.15
            style = Qt.PenStyle.DashLine
        else:
            color = QColor("#94a3b8") if state == "selected" else QColor("#475569")
            alpha = 170 if state == "selected" else 92
            width = 1.55 if state == "selected" else 1.0
            style = Qt.PenStyle.SolidLine
        if state == "dimmed":
            alpha = 26
        color.setAlpha(alpha)
        pen = QPen(color, width)
        pen.setStyle(style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)


class _MindmapNodeItem(_GraphItemPropertiesMixin, QGraphicsPathItem):
    def __init__(
        self,
        *,
        node: MindmapNode,
        node_id: str,
        on_select: Callable[[str], None],
    ):
        _GraphItemPropertiesMixin.__init__(self)
        QGraphicsPathItem.__init__(self)
        self._node = node
        self._node_id = node_id
        self._on_select = on_select
        self._width, self._height = _node_size(node)
        self.setPath(_rounded_rect_path(self._width, self._height, _node_radius(node)))
        self.setPos(node.x, node.y)
        self.label_item = QGraphicsTextItem(_short_label(node.label, max_length=28), self)
        self.label_item.setFont(_node_font(node))
        self.label_item.setTextWidth(self._width - 20)
        self._center_label()
        self.setToolTip(node.subtitle or node.label)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_state("normal")

    def apply_state(self, state: str) -> None:
        self.setProperty("graphState", state)
        palette = _node_palette(self._node.kind, state)
        self.setBrush(QBrush(QColor(palette["fill"])))
        self.setPen(QPen(QColor(palette["stroke"]), palette["width"]))
        self.label_item.setDefaultTextColor(QColor(palette["text"]))
        self.setOpacity(palette["opacity"])
        self.setZValue(palette["z"])

    def mousePressEvent(self, event):
        self._on_select(self._node_id)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event):
        if self.property("graphState") not in {"selected", "related"}:
            self.setOpacity(1.0)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.apply_state(str(self.property("graphState") or "normal"))
        super().hoverLeaveEvent(event)

    def _center_label(self) -> None:
        rect = self.label_item.boundingRect()
        self.label_item.setPos(-self._width / 2 + 10, -rect.height() / 2 - 1)


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
        self.view = _GraphView(self.scene)
        self.detail_title = QLabel()
        self.detail_body = QTextBrowser()
        self._node_items: dict[str, _MindmapNodeItem] = {}
        self._edge_items: list[tuple[str, str, Any]] = []
        self._edge_graphics_items: dict[tuple[str, str], _MindmapEdgeItem] = {}

        self._setup_ui()
        self.retranslate_ui()
        self.search_input.textChanged.connect(self._rebuild_graph)
        self.state_filter.currentIndexChanged.connect(self._rebuild_graph)
        self.refresh_btn.clicked.connect(self.refresh)
        self._rebuild_graph()

    def _setup_ui(self) -> None:
        self.setObjectName("topicMemoryMindmapPanel")
        self.view.setMinimumHeight(320)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setFrameShape(QFrame.Shape.NoFrame)

        self.detail_title.setWordWrap(True)
        self.detail_title.setObjectName("topicMemoryMindmapDetailTitle")
        self.detail_body.setReadOnly(True)
        self.detail_body.setOpenExternalLinks(False)
        self.detail_body.setFrameShape(QFrame.Shape.NoFrame)
        self.summary_label.setObjectName("topicMemoryMindmapSummary")

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        controls_layout.addWidget(self.search_input, 1)
        controls_layout.addWidget(self.state_filter)
        controls_layout.addWidget(self.refresh_btn)

        detail_frame = QFrame()
        detail_frame.setObjectName("topicMemoryDetailPanel")
        detail_frame.setMinimumWidth(300)
        detail_frame.setMaximumWidth(430)
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(10)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_body, 1)

        canvas_frame = QFrame()
        canvas_frame.setObjectName("topicMemoryCanvasFrame")
        canvas_layout = QVBoxLayout(canvas_frame)
        canvas_layout.setContentsMargins(1, 1, 1, 1)
        canvas_layout.addWidget(self.view)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.addWidget(canvas_frame)
        body_splitter.addWidget(detail_frame)
        body_splitter.setStretchFactor(0, 3)
        body_splitter.setStretchFactor(1, 2)
        body_splitter.setSizes([760, 360])
        body_splitter.setChildrenCollapsible(False)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(10)
        root_layout.addLayout(controls_layout)
        root_layout.addWidget(self.summary_label)
        root_layout.addWidget(body_splitter, 1)
        self.setStyleSheet(
            """
            QWidget#topicMemoryMindmapPanel {
                background: transparent;
            }
            QFrame#topicMemoryCanvasFrame {
                background: #11151d;
                border: 1px solid rgba(148, 163, 184, 0.22);
                border-radius: 14px;
            }
            QGraphicsView#topicMemoryGraphView {
                background: #11151d;
                border: none;
                border-radius: 13px;
            }
            QFrame#topicMemoryDetailPanel {
                background: rgba(15, 23, 42, 0.92);
                border: 1px solid rgba(148, 163, 184, 0.20);
                border-radius: 14px;
            }
            QLabel#topicMemoryMindmapDetailTitle {
                color: #f8fafc;
                font-size: 16px;
                font-weight: 800;
            }
            QLabel#topicMemoryMindmapSummary {
                color: #64748b;
                font-size: 12px;
                font-weight: 700;
            }
            QTextBrowser {
                color: #dbeafe;
                background: transparent;
                selection-background-color: rgba(125, 211, 252, 0.30);
                font-size: 13px;
                line-height: 1.5;
            }
            QLineEdit, QComboBox, QPushButton {
                min-height: 32px;
                border-radius: 8px;
                border: 1px solid rgba(148, 163, 184, 0.24);
                background: rgba(15, 23, 42, 0.78);
                color: #e5edf7;
                padding: 0 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid rgba(125, 211, 252, 0.70);
            }
            QPushButton:hover {
                background: rgba(30, 41, 59, 0.95);
                border-color: rgba(125, 211, 252, 0.42);
            }
            """
        )

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
        self._node_items.clear()
        self._edge_items.clear()
        self._edge_graphics_items.clear()
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
        self.view.request_fit()

    def _render_edges(self, graph: TopicMemoryGraph) -> None:
        for edge in graph.edges:
            if edge.kind == "topic":
                continue
            source = graph.nodes.get(edge.source_id)
            target = graph.nodes.get(edge.target_id)
            if source is None or target is None:
                continue
            item = _MindmapEdgeItem(source, target, kind=edge.kind, reason=edge.reason)
            item.setZValue(-3 if edge.kind == "shared" else -2)
            self.scene.addItem(item)
            self._edge_items.append((edge.source_id, edge.target_id, edge))
            self._edge_graphics_items[(edge.source_id, edge.target_id)] = item

    def _render_nodes(self, graph: TopicMemoryGraph) -> None:
        for node in graph.nodes.values():
            if node.kind == "root":
                continue
            item = _MindmapNodeItem(
                node=node,
                node_id=node.id,
                on_select=self._select_node,
            )
            item.setZValue(1)
            self.scene.addItem(item)
            self._node_items[node.id] = item

    def _select_node(self, node_id: str) -> None:
        if self._graph is None:
            return
        node = self._graph.nodes.get(node_id)
        if node is None:
            self._set_empty_detail()
            return

        self._selected_node_id = node_id
        self._update_selection_visuals(node_id)
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

    def _update_selection_visuals(self, selected_node_id: str | None) -> None:
        if not selected_node_id:
            for item in self._node_items.values():
                item.apply_state("normal")
            for item in self._edge_graphics_items.values():
                item.apply_state("normal")
            return

        related_ids = {selected_node_id}
        selected_edges: set[tuple[str, str]] = set()
        for source_id, target_id, _edge in self._edge_items:
            if selected_node_id not in {source_id, target_id}:
                continue
            related_ids.add(source_id)
            related_ids.add(target_id)
            selected_edges.add((source_id, target_id))

        for node_id, item in self._node_items.items():
            if node_id == selected_node_id:
                item.apply_state("selected")
            elif node_id in related_ids:
                item.apply_state("related")
            else:
                item.apply_state("dimmed")

        for edge_key, item in self._edge_graphics_items.items():
            item.apply_state("selected" if edge_key in selected_edges else "dimmed")

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


def _short_label(label: str, *, max_length: int = 24) -> str:
    text = str(label or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _edge_path(source: MindmapNode, target: MindmapNode, kind: str) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(source.x, source.y)
    if kind == "shared":
        dx = target.x - source.x
        dy = target.y - source.y
        curve = min(72.0, max(24.0, (abs(dx) + abs(dy)) * 0.08))
        path.cubicTo(
            source.x + dx * 0.35 - dy * 0.08,
            source.y + dy * 0.35 + curve,
            source.x + dx * 0.65 + dy * 0.08,
            source.y + dy * 0.65 - curve,
            target.x,
            target.y,
        )
    else:
        path.lineTo(target.x, target.y)
    return path


def _rounded_rect_path(width: float, height: float, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(-width / 2, -height / 2, width, height), radius, radius)
    return path


def _node_size(node: MindmapNode) -> tuple[float, float]:
    label_length = len(str(node.label or ""))
    if node.kind == "topic":
        return min(190.0, max(124.0, 94.0 + label_length * 5.2)), 54.0
    return min(150.0, max(96.0, 72.0 + label_length * 4.6)), 38.0


def _node_radius(node: MindmapNode) -> float:
    return 10.0 if node.kind == "topic" else 8.0


def _node_font(node: MindmapNode) -> QFont:
    font = QFont("Malgun Gothic")
    font.setPointSize(10 if node.kind == "topic" else 9)
    font.setWeight(QFont.Weight.DemiBold if node.kind == "topic" else QFont.Weight.Medium)
    return font


def _node_palette(kind: str, state: str) -> dict[str, Any]:
    if kind == "topic":
        base = {
            "fill": "#1e293b",
            "stroke": "#64748b",
            "text": "#f8fafc",
            "width": 1.2,
            "opacity": 0.96,
            "z": 3,
        }
    else:
        base = {
            "fill": "#172033",
            "stroke": "#475569",
            "text": "#cbd5e1",
            "width": 1.0,
            "opacity": 0.88,
            "z": 2,
        }
    if state == "selected":
        base.update(
            {
                "fill": "#0f2f43",
                "stroke": "#7dd3fc",
                "text": "#ffffff",
                "width": 2.2,
                "opacity": 1.0,
                "z": 8,
            }
        )
    elif state == "related":
        base.update(
            {
                "stroke": "#38bdf8",
                "text": "#e0f2fe",
                "width": 1.6,
                "opacity": 1.0,
                "z": 5,
            }
        )
    elif state == "dimmed":
        base.update({"opacity": 0.28, "width": 0.9, "z": 1})
    return base
