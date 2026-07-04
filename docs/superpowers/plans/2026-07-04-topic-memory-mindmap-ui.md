# Topic Memory Mindmap UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장된 `knowledge_map.json`의 주제 기억을 기존 기억 관리 창에서 읽기 전용 마인드맵으로 탐색할 수 있게 만든다.

**Architecture:** 주제 기억 저장/검색/컨텍스트 주입 로직은 그대로 두고, UI 전용 view model과 PyQt 패널을 새로 만든다. `MemoryDialog`는 기존 장기 기억 화면을 첫 번째 탭으로 유지하고, 두 번째 탭에 `KnowledgeMapManager.topics`를 읽는 주제 기억 지도 패널을 붙인다.

**Tech Stack:** Python, PyQt6, pytest, 기존 `src.ai.knowledge_map_types`, 기존 i18n JSON(`src/locales/*.json`)

---

## 범위

V1에서 한다:

- 기존 `MemoryDialog` 안에 `장기 기억` / `주제 기억 지도` 탭을 추가한다.
- `주제 기억 지도` 탭은 저장된 topic/clue를 읽기 전용으로 보여준다.
- 화면 안의 로컬 검색, state 필터, 새로고침, 노드 선택 상세 패널을 제공한다.
- 마인드맵 연결선은 표시 전용이다. 저장, 병합, 검색, 컨텍스트 주입 판단에 쓰지 않는다.
- `settings` 화면에 임베드된 기억 패널에서도 같은 주제 기억 지도 탭이 보이게 한다.

V1에서 하지 않는다:

- topic/clue 수정, 삭제, 병합 수동 제어
- 노드 위치 저장
- 연결선 승인/편집
- 그래프 연결 결과를 실제 회상/검색 로직에 반영
- `knowledge_map.json` 직접 파일 쓰기

개인정보/공개 저장소 안전:

- 테스트 데이터는 `Project Atlas`, `Topic Beta` 같은 가상 예시만 사용한다.
- 실제 대화 문장, 실제 사용자 정보, 실제 프롬프트를 테스트/문서/스크린샷에 넣지 않는다.
- `knowledge_map.json` 같은 런타임 파일은 커밋하지 않는다.

## 파일 구조

- Create: `src/ui/topic_memory_mindmap_model.py`
  - UI 전용 그래프 view model을 만든다.
  - `TopicMemoryTopic` 목록을 입력받아 노드/엣지/상세 조회용 인덱스로 변환한다.
  - PyQt에 의존하지 않는 순수 Python 모듈로 유지한다.

- Create: `src/ui/topic_memory_mindmap.py`
  - PyQt6 위젯 구현.
  - 로컬 검색, state 필터, 새로고침 버튼, `QGraphicsView` 캔버스, 읽기 전용 상세 패널을 가진다.
  - `KnowledgeMapManager`에서는 `load()`와 `topics`만 사용한다.

- Modify: `src/ui/memory_dialog.py`
  - 생성자에 `knowledge_map_manager=None` 인자를 추가한다.
  - 기존 기억 관리 화면을 첫 번째 탭으로 감싼다.
  - `TopicMemoryMindmapPanel`을 두 번째 탭으로 추가한다.
  - `retranslate_ui()`에서 탭 제목과 주제 기억 패널 문구를 갱신한다.

- Modify: `src/core/app.py`
  - `_show_memory_dialog()`에서 `self.knowledge_map_manager`를 `MemoryDialog`에 전달한다.

- Modify: `src/ui/settings_tabs/memory_tab.py`
  - 설정 화면에 임베드된 `MemoryDialog`에도 `bridge.knowledge_map_manager`를 전달한다.

- Modify: `src/locales/ko.json`, `src/locales/en.json`, `src/locales/ja.json`
  - 탭 이름과 주제 기억 지도 UI 문구를 추가한다.

- Test: `tests/test_topic_memory_mindmap_model.py`
  - 순수 view model 변환/필터/표시 전용 엣지 계산을 검증한다.

- Modify/Test: `tests/test_ui_i18n_smoke.py`
  - `MemoryDialog` 탭 추가, 번역 갱신, 앱/설정 경로의 manager 전달을 검증한다.

---

### Task 1: 주제 기억 그래프 View Model

**Files:**
- Create: `src/ui/topic_memory_mindmap_model.py`
- Test: `tests/test_topic_memory_mindmap_model.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_topic_memory_mindmap_model.py`를 만든다.

```python
from src.ai.knowledge_map_types import TopicMemoryClue, TopicMemoryTopic
from src.ui.topic_memory_mindmap_model import build_topic_memory_graph


def _topic(topic_id, keyword, clues, aliases=None, retrieval_terms=None):
    return TopicMemoryTopic(
        id=topic_id,
        keyword=keyword,
        aliases=list(aliases or []),
        retrieval_terms=list(retrieval_terms or []),
        clues=clues,
    )


def _clue(clue_id, subject, type="note", state="active", text="Synthetic clue text."):
    return TopicMemoryClue(
        id=clue_id,
        subject=subject,
        type=type,
        state=state,
        text=text,
        confidence=0.75,
    )


def test_build_graph_creates_central_topic_clue_nodes_and_primary_edges():
    graph = build_topic_memory_graph(
        [
            _topic(
                "topic-1",
                "Project Atlas",
                [_clue("clue-1", "planning", type="status")],
                aliases=["Atlas"],
                retrieval_terms=["roadmap"],
            )
        ]
    )

    assert graph.total_topics == 1
    assert graph.total_clues == 1
    assert graph.nodes["root"].label == "주제 기억"
    assert graph.nodes["topic:topic-1"].label == "Project Atlas"
    assert graph.nodes["clue:topic-1:clue-1"].label == "planning"
    assert ("root", "topic:topic-1", "topic") in {
        (edge.source_id, edge.target_id, edge.kind) for edge in graph.edges
    }
    assert ("topic:topic-1", "clue:topic-1:clue-1", "clue") in {
        (edge.source_id, edge.target_id, edge.kind) for edge in graph.edges
    }


def test_build_graph_filters_locally_by_keyword_alias_term_and_clue_text():
    graph = build_topic_memory_graph(
        [
            _topic("topic-1", "Project Atlas", [_clue("clue-1", "planning")], aliases=["Atlas"]),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "archive", text="Reference note")]),
        ],
        query="atlas",
    )

    assert "topic:topic-1" in graph.nodes
    assert "topic:topic-2" not in graph.nodes


def test_build_graph_filters_by_state_without_mutating_topics():
    clue = _clue("clue-1", "planning", state="closed")
    topics = [_topic("topic-1", "Project Atlas", [clue])]

    graph = build_topic_memory_graph(topics, state_filter="active")

    assert graph.total_topics == 0
    assert graph.total_clues == 0
    assert topics[0].clues[0].state == "closed"


def test_build_graph_adds_visual_shared_edges_only():
    graph = build_topic_memory_graph(
        [
            _topic("topic-1", "Project Atlas", [_clue("clue-1", "planning", type="status")]),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "planning", type="status")]),
        ]
    )

    visual_edges = [edge for edge in graph.edges if edge.kind == "shared"]
    assert visual_edges
    assert visual_edges[0].is_visual_hint is True
    assert "planning" in visual_edges[0].reason or "status" in visual_edges[0].reason
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
python -m pytest tests/test_topic_memory_mindmap_model.py -q
```

Expected: `ModuleNotFoundError: No module named 'src.ui.topic_memory_mindmap_model'`

- [ ] **Step 3: 최소 구현 작성**

`src/ui/topic_memory_mindmap_model.py`를 만든다. 주석은 필요한 곳만 한국어로 작성한다.

핵심 구조:

```python
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

from src.ai.knowledge_map_types import TopicMemoryClue, TopicMemoryTopic


@dataclass(frozen=True)
class MindmapNode:
    id: str
    label: str
    kind: str
    topic_id: str | None = None
    clue_id: str | None = None
    subtitle: str = ""
    x: float = 0.0
    y: float = 0.0


@dataclass(frozen=True)
class MindmapEdge:
    source_id: str
    target_id: str
    kind: str
    reason: str = ""
    strength: float = 1.0
    is_visual_hint: bool = False


@dataclass(frozen=True)
class TopicMemoryGraph:
    nodes: dict[str, MindmapNode] = field(default_factory=dict)
    edges: list[MindmapEdge] = field(default_factory=list)
    topic_index: dict[str, TopicMemoryTopic] = field(default_factory=dict)
    clue_index: dict[str, TopicMemoryClue] = field(default_factory=dict)
    total_topics: int = 0
    total_clues: int = 0


def build_topic_memory_graph(
    topics: Iterable[TopicMemoryTopic],
    *,
    query: str = "",
    state_filter: str = "all",
    max_topics: int = 80,
) -> TopicMemoryGraph:
    # 순수 표시용 변환이다. manager.search_* 또는 save 계열은 호출하지 않는다.
    normalized_topics = [topic for topic in topics or [] if topic.keyword][:max_topics]
    return _build_graph_from_topics(
        normalized_topics,
        query=query,
        state_filter=state_filter,
    )
```

구현 규칙:

- root node id는 `"root"`, label은 `"주제 기억"`으로 고정한다.
- topic node id는 `f"topic:{topic.id}"`.
- clue node id는 `f"clue:{topic.id}:{clue.id}"`.
- clue label은 `clue.subject`가 있으면 subject, 없으면 `clue.type`, 둘 다 없으면 `"단서"`를 쓴다.
- query 필터는 keyword, aliases, retrieval_terms, clue subject/type/state/text에 대해 case-insensitive substring으로만 처리한다.
- state 필터는 `"all"`이면 전체, 그 외에는 clue.state casefold 값과 비교한다. 필터에 남는 clue가 하나도 없는 topic은 화면에서 숨긴다.
- primary edge:
  - root -> topic: `kind="topic"`, `is_visual_hint=False`
  - topic -> clue: `kind="clue"`, `is_visual_hint=False`
- visual shared edge:
  - 서로 다른 topic 사이에서 clue subject 또는 type이 겹치면 `kind="shared"`, `is_visual_hint=True`
  - retrieval_terms가 겹쳐도 `kind="shared"`, `is_visual_hint=True`
  - 너무 복잡해지지 않도록 topic pair당 최대 1개만 추가한다.
- 레이아웃:
  - root는 `(0, 0)`
  - topic은 반지름 240 원형 배치
  - clue는 해당 topic 바깥쪽 반지름 120 내외의 작은 원형 배치
  - 좌표는 deterministic 해야 한다.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
python -m pytest tests/test_topic_memory_mindmap_model.py -q
```

Expected: `4 passed`

- [ ] **Step 5: 커밋**

```powershell
git add src/ui/topic_memory_mindmap_model.py tests/test_topic_memory_mindmap_model.py
git commit -m "feat: add topic memory mindmap view model"
```

---

### Task 2: 주제 기억 지도 i18n 키 선행 추가

**Files:**
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`

- [ ] **Step 1: locale 키 추가**

`src/locales/ko.json`, `src/locales/en.json`, `src/locales/ja.json`에 같은 key set을 먼저 추가한다. 이후 Task 3/4의 UI 테스트가 실제 locale 파일을 쓰므로, 이 작업이 먼저 끝나야 한다.

한국어 권장 문구:

```json
"memory.tabs.long_term": "장기 기억",
"memory.tabs.topic_map": "주제 기억 지도",
"memory.topic_map.search.placeholder": "주제, 단서, 검색어 필터",
"memory.topic_map.state.all": "전체 상태",
"memory.topic_map.refresh": "지도 새로고침",
"memory.topic_map.summary": "{topics}개 주제 · {clues}개 단서",
"memory.topic_map.empty.title": "선택된 주제 기억이 없습니다",
"memory.topic_map.empty.body": "지도에서 주제나 단서를 선택하면 상세 정보가 표시됩니다.",
"memory.topic_map.unavailable.title": "주제 기억을 사용할 수 없습니다",
"memory.topic_map.unavailable.body": "주제 기억 매니저가 초기화되지 않았습니다.",
"memory.topic_map.error.title": "주제 기억을 불러오지 못했습니다",
"memory.topic_map.error.body": "저장된 주제 기억을 읽는 중 오류가 발생했습니다: {error}",
"memory.topic_map.detail.aliases": "별칭",
"memory.topic_map.detail.retrieval_terms": "검색 단서",
"memory.topic_map.detail.state": "상태",
"memory.topic_map.detail.type": "유형",
"memory.topic_map.detail.confidence": "신뢰도",
"memory.topic_map.detail.source": "원본 기억",
"memory.topic_map.detail.history": "이력"
```

영어/일본어도 같은 key를 빠짐없이 추가한다. 문구는 자연스러운 UI 표현이면 충분하지만 placeholder로 비워 두지 않는다.

- [ ] **Step 2: JSON 파싱 확인**

Run:

```powershell
python -m json.tool src/locales/ko.json | Out-Null
python -m json.tool src/locales/en.json | Out-Null
python -m json.tool src/locales/ja.json | Out-Null
```

Expected: no output and exit code 0.

- [ ] **Step 3: 커밋**

```powershell
git add src/locales/ko.json src/locales/en.json src/locales/ja.json
git commit -m "feat: add topic memory map translations"
```

---

### Task 3: 읽기 전용 PyQt 마인드맵 패널

**Files:**
- Create: `src/ui/topic_memory_mindmap.py`
- Modify: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_ui_i18n_smoke.py`에 독립 테스트를 추가한다.

```python
from src.ai.knowledge_map_types import TopicMemoryClue, TopicMemoryTopic
from src.ui.topic_memory_mindmap import TopicMemoryMindmapPanel


class _DummyKnowledgeMapManager:
    def __init__(self, topics):
        self.topics = topics
        self.load_calls = 0
        self.search_calls = 0

    def load(self):
        self.load_calls += 1
        return self

    def search_direct(self, *_args, **_kwargs):
        self.search_calls += 1
        raise AssertionError("UI 로컬 필터가 검색 pipeline을 호출하면 안 됩니다.")

    search = search_direct

    def async_search(self, *_args, **_kwargs):
        self.search_calls += 1
        raise AssertionError("UI 로컬 필터가 검색 pipeline을 호출하면 안 됩니다.")

    def save(self):
        raise AssertionError("읽기 전용 UI가 save를 호출하면 안 됩니다.")

    def merge_hints_direct(self, *_args, **_kwargs):
        raise AssertionError("읽기 전용 UI가 merge를 호출하면 안 됩니다.")

    merge_hints = merge_hints_direct

    async def async_merge_hints(self, *_args, **_kwargs):
        raise AssertionError("읽기 전용 UI가 merge를 호출하면 안 됩니다.")


def test_topic_memory_mindmap_panel_renders_topics_and_filters_locally():
    _get_qapp()
    configure_i18n(language="ko", locales_dir=Path("src/locales"), system_locale="ko_KR")
    manager = _DummyKnowledgeMapManager(
        [
            TopicMemoryTopic(
                id="topic-1",
                keyword="Project Atlas",
                aliases=["Atlas"],
                retrieval_terms=["roadmap"],
                clues=[
                    TopicMemoryClue(
                        id="clue-1",
                        subject="planning",
                        type="status",
                        state="active",
                        text="Synthetic project note.",
                    )
                ],
            )
        ]
    )

    panel = TopicMemoryMindmapPanel(manager)

    assert panel.summary_label.text() == "1개 주제 · 1개 단서"
    assert "Project Atlas" in panel.detail_title.text()
    assert manager.search_calls == 0

    panel.search_input.setText("missing")
    assert panel.summary_label.text() == "0개 주제 · 0개 단서"
    assert manager.search_calls == 0

    panel.search_input.setText("atlas")
    assert panel.summary_label.text() == "1개 주제 · 1개 단서"
    panel.close()


def test_topic_memory_mindmap_panel_refresh_reloads_manager_without_saving():
    _get_qapp()
    manager = _DummyKnowledgeMapManager([])

    panel = TopicMemoryMindmapPanel(manager)
    panel.refresh()

    assert manager.load_calls == 1
    panel.close()


def test_topic_memory_mindmap_panel_shows_load_error_without_crashing():
    _get_qapp()

    class FailingKnowledgeMapManager(_DummyKnowledgeMapManager):
        def load(self):
            self.load_calls += 1
            raise ValueError("synthetic load failure")

    panel = TopicMemoryMindmapPanel(FailingKnowledgeMapManager([]))
    panel.refresh()

    assert "주제 기억을 불러오지 못했습니다" in panel.detail_title.text()
    assert "synthetic load failure" in panel.detail_body.toPlainText()
    panel.close()
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
python -m pytest tests/test_ui_i18n_smoke.py::test_topic_memory_mindmap_panel_renders_topics_and_filters_locally tests/test_ui_i18n_smoke.py::test_topic_memory_mindmap_panel_refresh_reloads_manager_without_saving tests/test_ui_i18n_smoke.py::test_topic_memory_mindmap_panel_shows_load_error_without_crashing -q
```

Expected: `ModuleNotFoundError: No module named 'src.ui.topic_memory_mindmap'`

- [ ] **Step 3: 최소 구현 작성**

`src/ui/topic_memory_mindmap.py`를 만든다.

구성:

- `TopicMemoryMindmapPanel(QWidget)`
  - `self.search_input = QLineEdit()`
  - `self.state_filter = QComboBox()`
  - `self.refresh_btn = QPushButton(t("memory.topic_map.refresh"))`
  - `self.summary_label = QLabel()`
  - `self.scene = QGraphicsScene()`
  - `self.view = QGraphicsView(self.scene)`
  - `self.detail_title = QLabel()`
  - `self.detail_body = QTextBrowser()` 또는 읽기 전용 `QTextEdit`
- `refresh()`:
  - manager가 있고 callable `load`가 있으면 `manager.load()` 호출
  - `save`, `merge`, `search` 계열은 호출하지 않는다.
  - `load()`가 예외를 던지면 예외를 밖으로 올리지 않고 `memory.topic_map.error.title/body`를 상세 패널에 표시한다.
  - 로드 실패 시 기존 graph가 있으면 scene은 마지막 성공 상태를 유지하고, graph가 없으면 빈 상태로 둔다.
  - 로드 성공 시에만 `_rebuild_graph()`를 호출한다.
  - 로드 실패 시에는 `_rebuild_graph()`를 호출하지 않고 오류 상세 패널을 유지한다.
- `_rebuild_graph()`:
  - `build_topic_memory_graph(manager.topics, query=self.search_input.text(), state_filter=self._current_state_filter())` 호출
  - scene을 비우고 edge, node 순서로 렌더링
  - 첫 topic이 있으면 자동 선택, 없으면 empty detail
- `_select_node(node_id)`:
  - graph 인덱스에서 topic/clue를 찾아 상세 패널에 표시
- `retranslate_ui()`:
  - placeholder, 버튼, 필터 항목, empty 문구 갱신
  - 이전 상태가 로드 오류였다면 오류 제목/본문도 현재 언어로 다시 표시한다.

시각 구현 규칙:

- `QGraphicsLineItem`으로 edge를 먼저 그린다.
- `kind="shared"` edge는 점선 또는 옅은 색상으로 표시한다.
- topic node는 clue node보다 크게 그린다.
- node label은 `QGraphicsTextItem`으로 표시하되 너무 긴 label은 24자 내외로 줄인다.
- 그래프는 읽기 전용이다. drag로 위치 저장을 구현하지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
python -m pytest tests/test_ui_i18n_smoke.py::test_topic_memory_mindmap_panel_renders_topics_and_filters_locally tests/test_ui_i18n_smoke.py::test_topic_memory_mindmap_panel_refresh_reloads_manager_without_saving tests/test_ui_i18n_smoke.py::test_topic_memory_mindmap_panel_shows_load_error_without_crashing -q
```

Expected: `3 passed`

- [ ] **Step 5: 커밋**

```powershell
git add src/ui/topic_memory_mindmap.py tests/test_ui_i18n_smoke.py
git commit -m "feat: add topic memory mindmap panel"
```

---

### Task 4: MemoryDialog 탭 통합

**Files:**
- Modify: `src/ui/memory_dialog.py`
- Modify: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_ui_i18n_smoke.py`에 테스트를 추가한다.

```python
def test_memory_dialog_adds_topic_memory_tab_and_passes_manager():
    _get_qapp()
    configure_i18n(language="ko", locales_dir=Path("src/locales"), system_locale="ko_KR")
    memory_manager = _DummyMemoryManager([])
    knowledge_manager = _DummyKnowledgeMapManager([])

    dialog = MemoryDialog(memory_manager, knowledge_map_manager=knowledge_manager)

    assert dialog.tabs.count() == 2
    assert dialog.tabs.tabText(0) == "장기 기억"
    assert dialog.tabs.tabText(1) == "주제 기억 지도"
    assert dialog.topic_memory_panel.knowledge_map_manager is knowledge_manager
    dialog.close()
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
python -m pytest tests/test_ui_i18n_smoke.py::test_memory_dialog_adds_topic_memory_tab_and_passes_manager -q
```

Expected: `AttributeError: 'MemoryDialog' object has no attribute 'tabs'`

- [ ] **Step 3: `MemoryDialog` 생성자 확장**

`src/ui/memory_dialog.py`:

- import에 `QTabWidget` 추가
- `TopicMemoryMindmapPanel` import 추가
- 생성자를 다음 형태로 바꾼다.

```python
def __init__(
    self,
    memory_manager,
    bridge=None,
    parent=None,
    embedded: bool = False,
    knowledge_map_manager=None,
):
    super().__init__(parent)
    self.memory_manager = memory_manager
    self.bridge = bridge
    self.knowledge_map_manager = knowledge_map_manager or getattr(bridge, "knowledge_map_manager", None)
    self._embedded = embedded
```

- 기존 호출부 호환을 위해 기존 인자 순서는 유지하고 새 인자는 keyword로 뒤에 둔다.

- [ ] **Step 4: 기존 화면을 첫 번째 탭으로 감싸기**

`_setup_ui()`를 다음 구조로 바꾼다.

```python
def _setup_ui(self) -> None:
    root = QVBoxLayout(self)
    root.setContentsMargins(
        0 if self._embedded else 18,
        0 if self._embedded else 18,
        0 if self._embedded else 18,
        0 if self._embedded else 18,
    )
    surface = CardFrame("Surface")
    root.addWidget(surface)
    layout = QVBoxLayout(surface)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(16)
    if not self._embedded:
        layout.addWidget(self._build_title_bar())

    self.tabs = QTabWidget()
    self.long_term_memory_page = QWidget()
    long_term_layout = QVBoxLayout(self.long_term_memory_page)
    long_term_layout.setContentsMargins(0, 0, 0, 0)
    long_term_layout.setSpacing(16)

    long_term_layout.addLayout(self._build_stats_row())
    long_term_layout.addWidget(self._build_filter_card())
    body_grid = QGridLayout()
    body_grid.setHorizontalSpacing(14)
    body_grid.setVerticalSpacing(14)
    body_grid.addWidget(self._build_memory_list_card(), 0, 0, 2, 2)
    body_grid.addWidget(self._build_inspector_card(), 0, 2)
    body_grid.addWidget(self._build_tuning_card(), 1, 2)
    body_grid.setColumnStretch(0, 1)
    body_grid.setColumnStretch(1, 1)
    body_grid.setColumnStretch(2, 1)
    long_term_layout.addLayout(body_grid, 1)

    self.topic_memory_panel = TopicMemoryMindmapPanel(self.knowledge_map_manager)
    self.tabs.addTab(self.long_term_memory_page, t("memory.tabs.long_term"))
    self.tabs.addTab(self.topic_memory_panel, t("memory.tabs.topic_map"))
    layout.addWidget(self.tabs, 1)
```

주의:

- 기존 `self.total_metric`, `self.memory_list`, `self.inspector_*` 속성명은 유지한다.
- 기존 `_load_memories()`, `_apply_filters()`, `_refresh_memory_item_size_hints()`가 그대로 동작해야 한다.
- tab 내부에 카드 중첩을 새로 만들지 않는다.

- [ ] **Step 5: 번역 갱신 연결**

`retranslate_ui()` 끝에 다음을 추가한다.

```python
if hasattr(self, "tabs"):
    self.tabs.setTabText(0, t("memory.tabs.long_term"))
    self.tabs.setTabText(1, t("memory.tabs.topic_map"))
if hasattr(self, "topic_memory_panel"):
    self.topic_memory_panel.retranslate_ui()
```

- [ ] **Step 6: 테스트 통과 확인**

Run:

```powershell
python -m pytest tests/test_ui_i18n_smoke.py::test_memory_dialog_adds_topic_memory_tab_and_passes_manager tests/test_ui_i18n_smoke.py::test_memory_dialog_translates_visible_strings_states_and_profile_warnings -q
```

Expected: `2 passed`

- [ ] **Step 7: 커밋**

```powershell
git add src/ui/memory_dialog.py tests/test_ui_i18n_smoke.py
git commit -m "feat: show topic memory map in memory dialog"
```

---

### Task 5: 앱과 설정 화면에 KnowledgeMapManager 전달

**Files:**
- Modify: `src/core/app.py`
- Modify: `src/ui/settings_tabs/memory_tab.py`
- Modify: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_ui_i18n_smoke.py`의 `_show_memory_dialog` 테스트 근처에 새 테스트를 추가한다.

```python
def test_show_memory_dialog_passes_knowledge_map_manager(monkeypatch):
    ENEApplication = _load_app_class()
    app = ENEApplication.__new__(ENEApplication)
    app.memory_manager = object()
    app.knowledge_map_manager = object()
    app.overlay_window = SimpleNamespace(bridge=SimpleNamespace())
    created = []

    class FakeMemoryDialog:
        def __init__(self, memory_manager, bridge=None, parent=None, embedded=False, knowledge_map_manager=None):
            created.append(
                {
                    "memory_manager": memory_manager,
                    "bridge": bridge,
                    "knowledge_map_manager": knowledge_map_manager,
                }
            )

        def exec(self):
            return None

    monkeypatch.setattr("src.ui.memory_dialog.MemoryDialog", FakeMemoryDialog)

    ENEApplication._show_memory_dialog(app)

    assert created == [
        {
            "memory_manager": app.memory_manager,
            "bridge": app.overlay_window.bridge,
            "knowledge_map_manager": app.knowledge_map_manager,
        }
    ]
```

설정 탭 경로는 `MemoryDialog`를 monkeypatch한 최소 호출 테스트로 검증한다.

테스트 파일 상단 import에 `QWidget`이 없으면 기존 `PyQt6.QtWidgets` import 줄에 `QWidget`을 추가한다.

```python
def test_settings_memory_tab_passes_bridge_knowledge_map_manager(monkeypatch):
    from src.ui.settings_tabs.memory_tab import build_memory_tab

    _get_qapp()
    created = []

    class FakeMemoryDialog(QWidget):
        def __init__(
            self,
            memory_manager,
            bridge=None,
            parent=None,
            embedded=False,
            knowledge_map_manager=None,
        ):
            super().__init__(parent)
            created.append(
                {
                    "memory_manager": memory_manager,
                    "bridge": bridge,
                    "embedded": embedded,
                    "knowledge_map_manager": knowledge_map_manager,
                }
            )

        def apply_theme(self, _theme_values):
            return None

    monkeypatch.setattr("src.ui.settings_tabs.memory_tab.MemoryDialog", FakeMemoryDialog)

    memory_manager = object()
    knowledge_manager = object()
    dialog = SimpleNamespace(
        _memory_manager=memory_manager,
        _bridge=SimpleNamespace(knowledge_map_manager=knowledge_manager),
        _theme_values={},
        _original_settings={},
        _embedded_memory_panel=None,
        _bind_widget_text=lambda *_args, **_kwargs: None,
        _bind_suffix=lambda *_args, **_kwargs: None,
        _bind_special_value_text=lambda *_args, **_kwargs: None,
        _on_setting_changed=lambda *_args, **_kwargs: None,
        _add_form_row=lambda form, _key, fallback, widget: form.addRow(fallback, widget),
        _build_hint_label=lambda text, key=None: QLabel(text),
    )

    widget = build_memory_tab(dialog)

    assert widget is not None
    assert created == [
        {
            "memory_manager": memory_manager,
            "bridge": dialog._bridge,
            "embedded": True,
            "knowledge_map_manager": knowledge_manager,
        }
    ]
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
python -m pytest tests/test_ui_i18n_smoke.py::test_show_memory_dialog_passes_knowledge_map_manager tests/test_ui_i18n_smoke.py::test_settings_memory_tab_passes_bridge_knowledge_map_manager -q
```

Expected: assertion failure because `knowledge_map_manager` is `None` or not passed.

- [ ] **Step 3: 앱 호출부 수정**

`src/core/app.py`:

```python
dialog = MemoryDialog(
    self.memory_manager,
    bridge,
    knowledge_map_manager=self.knowledge_map_manager if hasattr(self, "knowledge_map_manager") else None,
)
```

- [ ] **Step 4: 설정 탭 호출부 수정**

`src/ui/settings_tabs/memory_tab.py`:

```python
knowledge_map_manager = getattr(self._bridge, "knowledge_map_manager", None) if self._bridge else None
panel = MemoryDialog(
    self._memory_manager,
    self._bridge,
    self,
    embedded=True,
    knowledge_map_manager=knowledge_map_manager,
)
```

- [ ] **Step 5: 테스트 통과 확인**

Run:

```powershell
python -m pytest tests/test_ui_i18n_smoke.py::test_show_memory_dialog_passes_knowledge_map_manager tests/test_ui_i18n_smoke.py::test_settings_memory_tab_passes_bridge_knowledge_map_manager -q
```

Expected: `2 passed`

- [ ] **Step 6: 커밋**

```powershell
git add src/core/app.py src/ui/settings_tabs/memory_tab.py tests/test_ui_i18n_smoke.py
git commit -m "feat: pass topic memory manager to memory UI"
```

---

### Task 6: i18n 문구 회귀 테스트

**Files:**
- Modify: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: 번역 회귀 테스트 확장**

기존 `test_memory_dialog_translates_visible_strings_states_and_profile_warnings`의 임시 locale 데이터에 새 키를 넣고 assertion을 추가한다.

필수 키:

```json
{
  "memory.tabs.long_term": "Long-term memory",
  "memory.tabs.topic_map": "Topic memory map",
  "memory.topic_map.search.placeholder": "Filter topic memories",
  "memory.topic_map.state.all": "All states",
  "memory.topic_map.refresh": "Refresh map",
  "memory.topic_map.summary": "{topics} topics · {clues} clues",
  "memory.topic_map.empty.title": "No topic selected",
  "memory.topic_map.empty.body": "Select a topic or clue in the map.",
  "memory.topic_map.unavailable.title": "Topic memory unavailable",
  "memory.topic_map.unavailable.body": "The topic memory manager is not initialized.",
  "memory.topic_map.error.title": "Failed to load topic memory",
  "memory.topic_map.error.body": "Failed to read saved topic memory: {error}",
  "memory.topic_map.detail.aliases": "Aliases",
  "memory.topic_map.detail.retrieval_terms": "Retrieval terms",
  "memory.topic_map.detail.state": "State",
  "memory.topic_map.detail.type": "Type",
  "memory.topic_map.detail.confidence": "Confidence",
  "memory.topic_map.detail.source": "Source memory",
  "memory.topic_map.detail.history": "History"
}
```

Assertion 예시:

```python
assert dialog.tabs.tabText(0) == "長期メモリ"
assert dialog.tabs.tabText(1) == "トピック記憶マップ"
assert dialog.topic_memory_panel.search_input.placeholderText() == "トピック記憶を絞り込み"
```

- [ ] **Step 2: 테스트 통과 확인**

Run:

```powershell
python -m pytest tests/test_ui_i18n_smoke.py::test_memory_dialog_translates_visible_strings_states_and_profile_warnings -q
```

Expected: `1 passed`. Task 2에서 locale 파일 키를 이미 추가했고 Task 4에서 탭/패널 연결을 구현했기 때문에, 이 단계는 실패 유도보다 번역 회귀 고정에 목적이 있다.

- [ ] **Step 3: 커밋**

```powershell
git add tests/test_ui_i18n_smoke.py
git commit -m "test: cover topic memory map translations"
```

---

### Task 7: 통합 검증과 문서 업데이트

**Files:**
- Modify: `docs/topic_memory_mindmap_ui_design.md`
- Force add if needed: `docs/superpowers/plans/2026-07-04-topic-memory-mindmap-ui.md`

- [ ] **Step 1: 문서 업데이트**

`docs/topic_memory_mindmap_ui_design.md`에 실제 구현 위치를 반영한다.

추가할 내용:

- V1 구현 파일:
  - `src/ui/topic_memory_mindmap_model.py`
  - `src/ui/topic_memory_mindmap.py`
  - `src/ui/memory_dialog.py`
- 읽기 전용 보장:
  - UI는 `KnowledgeMapManager.load()`와 `topics`만 사용한다.
  - `save`, `merge_hints*`, `search_*`는 호출하지 않는다.
- 설정 화면 임베드 경로:
  - `src/ui/settings_tabs/memory_tab.py`

- [ ] **Step 2: targeted test 전체 실행**

Run:

```powershell
python -m pytest tests/test_topic_memory_mindmap_model.py tests/test_ui_i18n_smoke.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: 기존 주제 기억 회귀 테스트 실행**

Run:

```powershell
python -m pytest tests/test_knowledge_map_types.py tests/test_knowledge_map_manager.py tests/test_bridge_context_compaction.py tests/test_bridge_memory_metadata.py -q
```

Expected: all selected tests pass. 특히 UI 표시용 edge가 저장/검색/컨텍스트 주입 결과를 바꾸지 않아야 한다.

- [ ] **Step 4: 개인정보/런타임 파일 후보 확인**

Run:

```powershell
git status --short
rg -n "knowledge_map\\.json|memory\\.json|user_profile\\.json|ene_profile\\.json|api_keys\\.json|config\\.json|\\.env|실제|생일|건강|일정|자소서|프롬프트 원문" docs src tests
```

Expected:

- `knowledge_map.json` 같은 런타임 파일이 staged/untracked 변경에 없어야 한다.
- 테스트/문서에 실제 사용자 대화나 실제 개인정보 예시가 없어야 한다.
- `docs/superpowers/plans/2026-07-04-topic-memory-mindmap-ui.md`는 `.gitignore`에 걸릴 수 있으므로 커밋할 경우 `git add -f`를 쓴다.

- [ ] **Step 5: 최종 커밋**

```powershell
git add docs/topic_memory_mindmap_ui_design.md
git add -f docs/superpowers/plans/2026-07-04-topic-memory-mindmap-ui.md
git commit -m "docs: document topic memory map UI implementation"
```

- [ ] **Step 6: 최종 상태 확인**

Run:

```powershell
git status --short
git log --oneline -5
```

Expected:

- 작업 트리가 깨끗하거나 의도한 미커밋 변경만 남아 있다.
- 최근 커밋에 Task 1-7 커밋이 보인다.

---

## 최종 검증 명령

구현 완료 후 최소한 아래를 실행한다.

```powershell
python -m pytest tests/test_topic_memory_mindmap_model.py tests/test_ui_i18n_smoke.py tests/test_knowledge_map_types.py tests/test_knowledge_map_manager.py tests/test_bridge_context_compaction.py tests/test_bridge_memory_metadata.py -q
```

예상 결과:

- 모든 테스트 통과
- 주제 기억 지도 UI 테스트에서 `KnowledgeMapManager.search_*`, `save`, `merge_hints*`가 호출되지 않음
- 기존 주제 기억 저장/검색/컨텍스트 주입 테스트 결과 변화 없음

## 수동 확인 체크리스트

- ENE 앱에서 기억 관리 창을 열면 `장기 기억`, `주제 기억 지도` 탭이 보인다.
- `주제 기억 지도` 탭에서 topic/clue 노드가 보이고, 노드 선택 시 오른쪽 상세 패널이 바뀐다.
- 검색어 입력은 화면에 이미 로드된 topic/clue만 줄이며, 실제 기억 검색 결과를 바꾸지 않는다.
- state 필터는 해당 state의 clue만 남기고, 남는 clue가 없는 topic은 숨긴다.
- 새로고침은 저장소를 다시 읽지만 저장 파일을 수정하지 않는다.
- 설정 화면의 기억 관리 패널에도 같은 탭이 보인다.
