# ENE 2D Village World Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 별도 창에서 Sunnyside World 기반 마을을 편집하고, 에네 픽셀 아바타가 평소 알고리즘과 `/world` 명령으로 움직이는 V1을 만든다.

**Architecture:** PyQt 쪽은 `WorldWindow`와 `WorldBridge`로 창 수명주기, 저장, 명령 전달을 맡고, 웹 쪽은 `assets/world`의 Canvas 기반 런타임과 에디터가 월드 JSON을 렌더링한다. 순수 데이터 검증, 팔레트, 행동 선택, `/world` 계획 검증은 Python 모듈로 분리해 테스트 가능하게 만든다.

**Tech Stack:** Python 3.11+, PyQt6/QWebEngine/QWebChannel, Vanilla JavaScript Canvas, JSON, pytest.

---

## 파일 구조

- Create: `src/world/__init__.py`
  - 월드 도메인 패키지 진입점.
- Create: `src/world/palette.py`
  - Sunnyside 선별 팔레트와 source rectangle 검증.
- Create: `src/world/schema.py`
  - 월드 JSON 기본 구조, 프리셋 생성, 검증.
- Create: `src/world/behavior.py`
  - 평소 활동 지점 선택 알고리즘.
- Create: `src/world/world_command_service.py`
  - `/world` 명령 파싱, LLM 계획 프롬프트 생성, 계획 검증.
- Create: `src/core/world_bridge.py`
  - QWebChannel 브리지. 월드 JSON 로드/저장, mood 요약, 명령 전달.
- Create: `src/core/world_window.py`
  - 별도 QWebEngine 월드 창.
- Modify: `src/core/app.py`
  - `WorldWindow` 생성, 트레이 신호 연결, `/world` 브리지 연결.
- Modify: `src/core/tray_icon.py`
  - `마을 열기` 액션과 신호 추가.
- Modify: `src/ai/diary_service.py`
  - `/world` 파서 추가. 기존 `/note`, `/obs`, `/diary` 패턴을 따른다.
- Modify: `src/core/bridge.py`
  - 일반 채팅 전에 `/world` 명령을 감지하고 월드 명령 서비스로 라우팅.
- Create: `assets/world/index.html`
  - 월드/편집기 웹 진입점.
- Create: `assets/world/style.css`
  - 월드 창 UI 스타일.
- Create: `assets/world/palette.js`
  - Python 팔레트와 같은 id/source rectangle을 가진 JS 팔레트.
- Create: `assets/world/world.js`
  - Canvas 렌더러, 에네 아바타 애니메이션, 평소 이동 루프.
- Create: `assets/world/editor.js`
  - 선별 팔레트 기반 타일/오브젝트/활동 지점 배치.
- Create: `assets/world/presets/living_village.json`
  - 기본 프리셋.
- Create: `tests/test_world_palette.py`
- Create: `tests/test_world_schema.py`
- Create: `tests/test_world_behavior.py`
- Create: `tests/test_world_command_service.py`
- Create: `tests/test_world_window.py`
- Create: `tests/test_world_assets.py`
- Modify: `tests/test_diary_feature.py` 또는 create `tests/test_world_command_parsing.py`
  - `/world` 파서 회귀 테스트.
- Modify: `src/locales/ko.json`, `src/locales/en.json`, `src/locales/ja.json`
  - 트레이 메뉴 라벨.
- Modify: `README.md`
  - Sunnyside World 자산 크레딧/라이선스 주의 문구 추가. 실제 라이선스 파일이 없으면 “사용자가 제공한 자산이며 배포 전 라이선스 확인 필요”로 적는다.

---

### Task 1: 월드 팔레트 도메인 만들기

**Files:**
- Create: `src/world/__init__.py`
- Create: `src/world/palette.py`
- Test: `tests/test_world_palette.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from src.world.palette import SUNNYSIDE_TILESET, SELECTED_PALETTE, validate_palette


def test_selected_palette_has_required_groups():
    groups = {item["group"] for item in SELECTED_PALETTE}

    assert {"ground", "village", "decor", "activity"} <= groups


def test_palette_source_rectangles_stay_inside_tileset():
    errors = validate_palette(
        bundle_root=Path("C:/Users/umpad/Desktop/coding/ENE"),
        palette=SELECTED_PALETTE,
    )

    assert errors == []


def test_palette_uses_sunnyside_tileset():
    assert SUNNYSIDE_TILESET.endswith(
        "assets/sprites/Sunnyside_World_ASSET_PACK_V2.1/"
        "Sunnyside_World_Assets/Tileset/spr_tileset_sunnysideworld_16px.png"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_palette.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.world'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/world/__init__.py`:

```python
"""ENE 2D 월드 도메인 모듈."""
```

Create `src/world/palette.py`:

```python
"""Sunnyside World 선별 팔레트."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image


SUNNYSIDE_ROOT = "assets/sprites/Sunnyside_World_ASSET_PACK_V2.1/Sunnyside_World_Assets"
SUNNYSIDE_TILESET = f"{SUNNYSIDE_ROOT}/Tileset/spr_tileset_sunnysideworld_16px.png"

SELECTED_PALETTE: list[dict] = [
    {
        "id": "ground.grass.default",
        "label": "잔디",
        "group": "ground",
        "source": SUNNYSIDE_TILESET,
        "src": {"x": 0, "y": 0, "w": 16, "h": 16},
        "draw": {"w": 16, "h": 16},
        "layer": "ground",
        "blocking": False,
    },
    {
        "id": "ground.path.default",
        "label": "길",
        "group": "ground",
        "source": SUNNYSIDE_TILESET,
        "src": {"x": 16, "y": 0, "w": 16, "h": 16},
        "draw": {"w": 16, "h": 16},
        "layer": "ground",
        "blocking": False,
    },
    {
        "id": "ground.water.default",
        "label": "물",
        "group": "ground",
        "source": SUNNYSIDE_TILESET,
        "src": {"x": 32, "y": 0, "w": 16, "h": 16},
        "draw": {"w": 16, "h": 16},
        "layer": "ground",
        "blocking": True,
    },
    {
        "id": "village.fence.default",
        "label": "울타리",
        "group": "village",
        "source": SUNNYSIDE_TILESET,
        "src": {"x": 48, "y": 0, "w": 16, "h": 16},
        "draw": {"w": 16, "h": 16},
        "layer": "object",
        "blocking": True,
    },
    {
        "id": "decor.tree.default",
        "label": "나무",
        "group": "decor",
        "source": f"{SUNNYSIDE_ROOT}/Elements/Plants/spr_deco_tree_01_strip4.png",
        "src": {"x": 0, "y": 0, "w": 32, "h": 48},
        "draw": {"w": 32, "h": 48},
        "layer": "object",
        "blocking": True,
    },
    {
        "id": "activity.marker.default",
        "label": "활동 지점",
        "group": "activity",
        "source": "",
        "src": {"x": 0, "y": 0, "w": 0, "h": 0},
        "draw": {"w": 16, "h": 16},
        "layer": "marker",
        "blocking": False,
    },
]


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def validate_palette(*, bundle_root: Path, palette: Iterable[dict]) -> list[str]:
    errors: list[str] = []
    for item in palette:
        source = str(item.get("source", "")).strip()
        if not source:
            continue
        source_path = bundle_root / source
        if not source_path.exists():
            errors.append(f"{item.get('id')}: source not found: {source}")
            continue
        width, height = _image_size(source_path)
        src = item.get("src", {})
        x = int(src.get("x", 0))
        y = int(src.get("y", 0))
        w = int(src.get("w", 0))
        h = int(src.get("h", 0))
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            errors.append(f"{item.get('id')}: source rectangle out of bounds")
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_palette.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/world/__init__.py src/world/palette.py tests/test_world_palette.py
git commit -m "feat: add selected world palette"
```

---

### Task 2: 월드 JSON 스키마와 기본 프리셋 만들기

**Files:**
- Create: `src/world/schema.py`
- Create: `assets/world/presets/living_village.json`
- Test: `tests/test_world_schema.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from src.world.schema import build_default_world, validate_world


def test_default_world_contains_spawn_and_activity_points():
    world = build_default_world()

    assert world["version"] == 1
    assert world["tileSize"] == 16
    assert world["spawn"]["x"] >= 0
    assert world["activityPoints"]


def test_living_village_preset_is_valid():
    preset_path = Path("assets/world/presets/living_village.json")
    world = json.loads(preset_path.read_text(encoding="utf-8-sig"))

    assert validate_world(world) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_schema.py -v`

Expected: FAIL because `src.world.schema` and preset file do not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/world/schema.py`:

```python
"""월드 JSON 생성과 검증."""
from __future__ import annotations

from copy import deepcopy


def build_default_world() -> dict:
    return {
        "version": 1,
        "name": "생활형 마을 허브",
        "tileSize": 16,
        "width": 20,
        "height": 12,
        "spawn": {"x": 9, "y": 6},
        "layers": {
            "ground": [],
            "object": [],
            "marker": [],
        },
        "activityPoints": [
            {
                "id": "plaza_idle",
                "label": "광장 대기",
                "x": 9,
                "y": 6,
                "tags": ["social", "idle"],
                "allowedActions": ["idle", "waiting"],
                "moodWeights": {"calm": 1.0, "energetic": 1.1},
            },
            {
                "id": "pond_rest",
                "label": "연못 휴식",
                "x": 15,
                "y": 8,
                "tags": ["quiet", "rest", "water"],
                "allowedActions": ["idle", "waiting"],
                "moodWeights": {"calm": 1.4, "tired": 1.2},
            },
        ],
    }


def validate_world(world: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(world, dict):
        return ["world must be an object"]
    if int(world.get("version", 0) or 0) != 1:
        errors.append("version must be 1")
    width = int(world.get("width", 0) or 0)
    height = int(world.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        errors.append("width and height must be positive")
    spawn = world.get("spawn", {})
    if not isinstance(spawn, dict):
        errors.append("spawn must be an object")
    else:
        x = int(spawn.get("x", -1) or -1)
        y = int(spawn.get("y", -1) or -1)
        if x < 0 or y < 0 or x >= width or y >= height:
            errors.append("spawn is outside map bounds")
    activity_points = world.get("activityPoints", [])
    if not isinstance(activity_points, list) or not activity_points:
        errors.append("activityPoints must not be empty")
    return errors


def clone_default_world() -> dict:
    return deepcopy(build_default_world())
```

Create `assets/world/presets/living_village.json` with UTF-8 BOM:

```json
{
  "version": 1,
  "name": "생활형 마을 허브",
  "tileSize": 16,
  "width": 20,
  "height": 12,
  "spawn": {"x": 9, "y": 6},
  "layers": {
    "ground": [],
    "object": [],
    "marker": []
  },
  "activityPoints": [
    {
      "id": "plaza_idle",
      "label": "광장 대기",
      "x": 9,
      "y": 6,
      "tags": ["social", "idle"],
      "allowedActions": ["idle", "waiting"],
      "moodWeights": {"calm": 1.0, "energetic": 1.1}
    },
    {
      "id": "pond_rest",
      "label": "연못 휴식",
      "x": 15,
      "y": 8,
      "tags": ["quiet", "rest", "water"],
      "allowedActions": ["idle", "waiting"],
      "moodWeights": {"calm": 1.4, "tired": 1.2}
    }
  ]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_schema.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/world/schema.py assets/world/presets/living_village.json tests/test_world_schema.py
git commit -m "feat: add world schema and village preset"
```

---

### Task 3: 평소 이동 알고리즘 만들기

**Files:**
- Create: `src/world/behavior.py`
- Test: `tests/test_world_behavior.py`

- [ ] **Step 1: Write the failing test**

```python
from src.world.behavior import choose_next_activity


def test_choose_next_activity_prefers_matching_mood_weight():
    points = [
        {"id": "plaza", "moodWeights": {"calm": 0.5}, "allowedActions": ["idle"]},
        {"id": "pond", "moodWeights": {"calm": 2.0}, "allowedActions": ["waiting"]},
    ]

    chosen = choose_next_activity(points, mood_key="calm", recent_ids=[], seed=7)

    assert chosen["id"] == "pond"


def test_choose_next_activity_penalizes_recent_point():
    points = [
        {"id": "plaza", "moodWeights": {"calm": 1.0}, "allowedActions": ["idle"]},
        {"id": "pond", "moodWeights": {"calm": 1.0}, "allowedActions": ["waiting"]},
    ]

    chosen = choose_next_activity(points, mood_key="calm", recent_ids=["plaza"], seed=1)

    assert chosen["id"] == "pond"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_behavior.py -v`

Expected: FAIL because `src.world.behavior` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
"""에네 월드 평소 행동 선택 알고리즘."""
from __future__ import annotations

import random
from typing import Iterable


def _score(point: dict, *, mood_key: str, recent_ids: set[str]) -> float:
    mood_weights = point.get("moodWeights", {})
    weight = 1.0
    if isinstance(mood_weights, dict):
        weight = float(mood_weights.get(mood_key, 1.0) or 1.0)
    if str(point.get("id", "")) in recent_ids:
        weight *= 0.25
    if not point.get("allowedActions"):
        weight *= 0.1
    return max(0.01, weight)


def choose_next_activity(
    activity_points: Iterable[dict],
    *,
    mood_key: str = "calm",
    recent_ids: Iterable[str] = (),
    seed: int | None = None,
) -> dict:
    points = [point for point in activity_points if isinstance(point, dict)]
    if not points:
        raise ValueError("activity_points must not be empty")

    recent = {str(item) for item in recent_ids}
    scored = [(point, _score(point, mood_key=mood_key, recent_ids=recent)) for point in points]
    max_score = max(score for _, score in scored)
    best = [point for point, score in scored if score == max_score]
    rng = random.Random(seed)
    return rng.choice(best)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_behavior.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/world/behavior.py tests/test_world_behavior.py
git commit -m "feat: add world behavior selection"
```

---

### Task 4: `/world` 명령 파서와 계획 검증 만들기

**Files:**
- Modify: `src/ai/diary_service.py`
- Create: `src/world/world_command_service.py`
- Test: `tests/test_world_command_service.py`
- Test: `tests/test_world_command_parsing.py`

- [ ] **Step 1: Write the failing parser test**

```python
from src.ai.diary_service import DiaryService


def test_parse_world_command_returns_body():
    is_world, body = DiaryService.parse_world_command("/world 연못 쪽에서 쉬어줘")

    assert is_world is True
    assert body == "연못 쪽에서 쉬어줘"


def test_parse_world_command_ignores_normal_chat():
    assert DiaryService.parse_world_command("그냥 대화") == (False, "")
```

- [ ] **Step 2: Write the failing validation test**

```python
import pytest

from src.world.world_command_service import WorldCommandService


def test_validate_plan_accepts_known_activity_and_action():
    service = WorldCommandService()
    world = {
        "activityPoints": [
            {"id": "pond_rest", "allowedActions": ["waiting"]},
        ]
    }
    plan = {"targetActivityPointId": "pond_rest", "action": "waiting", "reason": "요청과 맞음"}

    assert service.validate_plan(plan, world) == plan


def test_validate_plan_rejects_unknown_activity():
    service = WorldCommandService()
    world = {"activityPoints": [{"id": "pond_rest", "allowedActions": ["waiting"]}]}

    with pytest.raises(ValueError, match="unknown activity point"):
        service.validate_plan({"targetActivityPointId": "missing", "action": "waiting"}, world)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_world_command_parsing.py tests/test_world_command_service.py -v`

Expected: FAIL because parser and service do not exist.

- [ ] **Step 4: Implement parser and service**

In `src/ai/diary_service.py`, add:

```python
_WORLD_COMMAND_PATTERN = re.compile(r"^/world(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
```

Inside `DiaryService`:

```python
@staticmethod
def parse_world_command(message: str) -> tuple[bool, str]:
    """/world 명령 여부와 본문을 반환한다."""
    text = (message or "").strip()
    match = _WORLD_COMMAND_PATTERN.match(text)
    if not match:
        return False, ""
    body = (match.group(1) or "").strip()
    return True, body
```

Create `src/world/world_command_service.py`:

```python
"""'/world' 명령 계획 생성과 검증 보조."""
from __future__ import annotations

import json


class WorldCommandService:
    """월드 행동 명령을 제한된 행동 계획으로 다룬다."""

    def build_plan_prompt(self, *, request: str, world: dict, mood_summary: str = "") -> str:
        activity_points = world.get("activityPoints", [])
        allowed = [
            {
                "id": point.get("id"),
                "label": point.get("label", ""),
                "allowedActions": point.get("allowedActions", []),
                "tags": point.get("tags", []),
            }
            for point in activity_points
        ]
        return (
            "너는 ENE 월드 행동 계획기다. 반드시 JSON만 반환한다.\n"
            "스키마: {\"targetActivityPointId\": string, \"action\": string, \"reason\": string}\n"
            f"사용자 요청: {request}\n"
            f"현재 기분 요약: {mood_summary}\n"
            f"가능한 활동 지점: {json.dumps(allowed, ensure_ascii=False)}"
        )

    def validate_plan(self, plan: dict, world: dict) -> dict:
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        target_id = str(plan.get("targetActivityPointId", "")).strip()
        action = str(plan.get("action", "")).strip()
        points = world.get("activityPoints", [])
        by_id = {str(point.get("id", "")): point for point in points if isinstance(point, dict)}
        if target_id not in by_id:
            raise ValueError("unknown activity point")
        allowed_actions = [str(item) for item in by_id[target_id].get("allowedActions", [])]
        if action not in allowed_actions:
            raise ValueError("action is not allowed for activity point")
        return {
            "targetActivityPointId": target_id,
            "action": action,
            "reason": str(plan.get("reason", "")).strip(),
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_world_command_parsing.py tests/test_world_command_service.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai/diary_service.py src/world/world_command_service.py tests/test_world_command_parsing.py tests/test_world_command_service.py
git commit -m "feat: add world command planning helpers"
```

---

### Task 5: 월드 웹 자산 스켈레톤 만들기

**Files:**
- Create: `assets/world/index.html`
- Create: `assets/world/style.css`
- Create: `assets/world/palette.js`
- Create: `assets/world/world.js`
- Create: `assets/world/editor.js`
- Test: `tests/test_world_assets.py`

- [ ] **Step 1: Write the failing asset smoke test**

```python
from pathlib import Path


def test_world_assets_exist():
    root = Path("assets/world")
    for name in ["index.html", "style.css", "palette.js", "world.js", "editor.js"]:
        assert (root / name).exists()


def test_world_index_loads_required_scripts():
    html = Path("assets/world/index.html").read_text(encoding="utf-8-sig")

    assert "qwebchannel.js" in html
    assert "palette.js" in html
    assert "world.js" in html
    assert "editor.js" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_assets.py -v`

Expected: FAIL because `assets/world` does not exist.

- [ ] **Step 3: Create minimal web assets**

Create `assets/world/index.html`:

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ENE World</title>
  <link rel="stylesheet" href="style.css">
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
</head>
<body>
  <main id="app">
    <aside id="palette" aria-label="선별 팔레트"></aside>
    <section id="stage-wrap">
      <canvas id="world-canvas" width="640" height="384" aria-label="에네 마을"></canvas>
    </section>
    <aside id="inspector" aria-label="속성 패널"></aside>
  </main>
  <script src="palette.js"></script>
  <script src="world.js"></script>
  <script src="editor.js"></script>
</body>
</html>
```

Create `assets/world/style.css` with stable dimensions:

```css
html, body {
  margin: 0;
  min-height: 100%;
  background: #101820;
  color: #edf7ff;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

#app {
  display: grid;
  grid-template-columns: 240px minmax(480px, 1fr) 240px;
  min-height: 100vh;
}

#palette, #inspector {
  padding: 14px;
  background: #172331;
  border-color: rgba(255, 255, 255, 0.12);
}

#palette {
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}

#inspector {
  border-left: 1px solid rgba(255, 255, 255, 0.12);
}

#stage-wrap {
  display: grid;
  place-items: center;
  padding: 18px;
  overflow: auto;
}

#world-canvas {
  width: min(100%, 960px);
  height: auto;
  image-rendering: pixelated;
  background: #0b1119;
}
```

Create minimal JS globals:

```js
// palette.js
window.ENE_WORLD_PALETTE = [];
```

```js
// world.js
window.ENEWorld = {
  loadWorld(world) {
    window.ENEWorld.currentWorld = world;
  },
  applyCommand(command) {
    window.ENEWorld.lastCommand = command;
  }
};
```

```js
// editor.js
window.ENEWorldEditor = {
  selectedPaletteId: null
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_assets.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assets/world/index.html assets/world/style.css assets/world/palette.js assets/world/world.js assets/world/editor.js tests/test_world_assets.py
git commit -m "feat: add world web shell"
```

---

### Task 6: WorldBridge와 WorldWindow 추가

**Files:**
- Create: `src/core/world_bridge.py`
- Create: `src/core/world_window.py`
- Test: `tests/test_world_window.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from src.core.world_bridge import WorldBridge
from src.core.world_window import resolve_world_html_path


def test_resolve_world_html_path_uses_bundle_root(tmp_path):
    html = tmp_path / "assets" / "world" / "index.html"
    html.parent.mkdir(parents=True)
    html.write_text("<html></html>", encoding="utf-8-sig")

    assert resolve_world_html_path(bundle_root=tmp_path) == html.resolve()


def test_world_bridge_returns_default_world_when_file_missing(tmp_path):
    bridge = WorldBridge(world_file=tmp_path / "world.json")

    payload = bridge.get_world_json()

    assert "생활형 마을 허브" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_window.py -v`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement bridge and path resolver**

Create `src/core/world_bridge.py`:

```python
"""QWebChannel bridge for ENE world window."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSlot

from .app_paths import get_user_file, load_json_data, save_json_data
from ..world.schema import build_default_world, validate_world


class WorldBridge(QObject):
    """월드 웹 런타임과 Python 저장소를 연결한다."""

    def __init__(self, world_file: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.world_file = Path(world_file) if world_file is not None else get_user_file("world/world.json")
        self._pending_command: dict | None = None

    @pyqtSlot(result=str)
    def get_world_json(self) -> str:
        try:
            world = load_json_data(self.world_file, encoding="utf-8-sig")
            if validate_world(world):
                world = build_default_world()
        except Exception:
            world = build_default_world()
        return json.dumps(world, ensure_ascii=False)

    @pyqtSlot(str, result=bool)
    def save_world_json(self, payload: str) -> bool:
        try:
            world = json.loads(payload)
            errors = validate_world(world)
            if errors:
                return False
            save_json_data(self.world_file, world, encoding="utf-8-sig", indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def queue_world_command(self, command: dict) -> None:
        self._pending_command = dict(command)

    @pyqtSlot(result=str)
    def consume_pending_command_json(self) -> str:
        command = self._pending_command or {}
        self._pending_command = None
        return json.dumps(command, ensure_ascii=False)
```

Create `src/core/world_window.py`:

```python
"""별도 ENE 월드 창."""
from __future__ import annotations

from pathlib import Path
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .app_paths import get_bundle_root
from .world_bridge import WorldBridge


def resolve_world_html_path(*, bundle_root: Path | None = None) -> Path:
    root = Path(bundle_root) if bundle_root is not None else get_bundle_root()
    return (root / "assets" / "world" / "index.html").resolve()


class WorldWindow(QWidget):
    """마을 월드를 표시하는 일반 창."""

    def __init__(self, bridge: WorldBridge | None = None, parent=None):
        super().__init__(parent)
        self.bridge = bridge or WorldBridge(parent=self)
        self.setWindowTitle("ENE World")
        self.resize(1100, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView(self)
        self.web_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        self.web_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True,
        )
        layout.addWidget(self.web_view)

        self.channel = QWebChannel(self.web_view.page())
        self.channel.registerObject("worldBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        html_path = resolve_world_html_path()
        self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_window.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/world_bridge.py src/core/world_window.py tests/test_world_window.py
git commit -m "feat: add world window bridge"
```

---

### Task 7: 앱과 트레이에서 월드 창 열기

**Files:**
- Modify: `src/core/tray_icon.py`
- Modify: `src/core/app.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Test: `tests/test_i18n.py` 또는 create `tests/test_tray_world_action.py`

- [ ] **Step 1: Write the failing i18n test**

```python
from src.core.i18n import I18n


def test_tray_world_label_exists():
    for language in ["ko", "en", "ja"]:
        i18n = I18n(language=language)
        assert i18n.t("tray.world") != "tray.world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_i18n.py::test_tray_world_label_exists -v`

Expected: FAIL because `tray.world` is missing.

- [ ] **Step 3: Add tray signal and app handler**

In `src/core/tray_icon.py`, add signal:

```python
world_requested = pyqtSignal()
```

In `_create_menu()`, add after calendar:

```python
self.world_action = QAction("", self)
self.world_action.triggered.connect(self.world_requested.emit)
menu.addAction(self.world_action)
```

In `retranslate_ui()`:

```python
self.world_action.setText(tr("tray.world"))
```

In `src/core/app.py`, import:

```python
from .world_window import WorldWindow
```

In `__init__`, after Obsidian panel setup:

```python
self.world_window = None
```

In `_connect_signals()`:

```python
self.tray_icon.world_requested.connect(self._show_world_window)
```

Add method:

```python
def _show_world_window(self):
    """에네 마을 월드 창을 표시한다."""
    if self.world_window and self.world_window.isVisible():
        self.world_window.raise_()
        self.world_window.activateWindow()
        return
    self.world_window = WorldWindow(parent=None)
    self.world_window.show()
```

Add locale values:

```json
"tray": {
  "world": "마을 열기"
}
```

English: `"Open Village"`  
Japanese: `"村を開く"`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_i18n.py::test_tray_world_label_exists -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/tray_icon.py src/core/app.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_i18n.py
git commit -m "feat: add world tray entry"
```

---

### Task 8: `/world` 명령을 Bridge에 연결

**Files:**
- Modify: `src/core/bridge.py`
- Modify: `src/core/app.py`
- Modify: `src/core/world_bridge.py`
- Test: `tests/test_world_command_service.py`

- [ ] **Step 1: Write the failing bridge-level test**

Prefer a focused pure helper test rather than constructing full `WebBridge`.

```python
from src.world.world_command_service import WorldCommandService


class FakeLLM:
    def send_message(self, prompt):
        return '{"targetActivityPointId":"pond_rest","action":"waiting","reason":"요청과 맞음"}'


def test_parse_llm_plan_json():
    service = WorldCommandService()

    plan = service.parse_plan_json('{"targetActivityPointId":"pond_rest","action":"waiting"}')

    assert plan["targetActivityPointId"] == "pond_rest"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_command_service.py::test_parse_llm_plan_json -v`

Expected: FAIL because `parse_plan_json` is missing.

- [ ] **Step 3: Add planning helpers**

In `WorldCommandService`:

```python
def parse_plan_json(self, raw_text: str) -> dict:
    try:
        parsed = json.loads(str(raw_text or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("world plan must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("world plan must be an object")
    return parsed
```

In `src/core/bridge.py`, add import near the other domain/service imports:

```python
from ..world.world_command_service import WorldCommandService
```

Add fields in `WebBridge.__init__`:

```python
self.world_bridge = None
self.world_command_service = WorldCommandService()
```

Add setter:

```python
def set_world_bridge(self, world_bridge):
    self.world_bridge = world_bridge
```

Add `_handle_world_command()` before `_handle_note_command()` in `send_to_ai()`:

```python
def _handle_world_command(self, message: str) -> bool:
    is_world, world_body = self.diary_service.parse_world_command(message)
    if not is_world:
        return False
    self._mark_user_activity()
    if not world_body:
        self.message_received.emit("`/world` 뒤에 에네가 할 행동을 함께 입력해 주세요.", "confused", "")
        return True
    if not self.world_bridge:
        self.message_received.emit("월드 창이 아직 준비되지 않았어요. 먼저 마을을 열어 주세요.", "confused", "")
        return True
    world = json.loads(self.world_bridge.get_world_json())
    prompt = self.world_command_service.build_plan_prompt(
        request=world_body,
        world=world,
        mood_summary="",
    )
    raw_plan = self.llm_client.send_message(prompt)
    plan = self.world_command_service.validate_plan(
        self.world_command_service.parse_plan_json(raw_plan),
        world,
    )
    self.world_bridge.queue_world_command(plan)
    self.message_received.emit("알겠어요. 에네가 마을에서 움직여볼게요.", "normal", "")
    return True
```

In `send_to_ai()` order:

```python
if self._handle_world_command(message):
    return
```

In `src/core/app.py`, when world window is created, connect:

```python
self.overlay_window.bridge.set_world_bridge(self.world_window.bridge)
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_world_command_service.py tests/test_world_command_parsing.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/bridge.py src/core/app.py src/core/world_bridge.py src/world/world_command_service.py tests/test_world_command_service.py
git commit -m "feat: route world commands"
```

---

### Task 9: Canvas 렌더링과 에디터 최소 기능 구현

**Files:**
- Modify: `assets/world/palette.js`
- Modify: `assets/world/world.js`
- Modify: `assets/world/editor.js`
- Test: `tests/test_world_assets.py`

- [ ] **Step 1: Extend asset test**

```python
def test_world_runtime_exposes_required_functions():
    world_js = Path("assets/world/world.js").read_text(encoding="utf-8-sig")
    editor_js = Path("assets/world/editor.js").read_text(encoding="utf-8-sig")

    assert "drawImage" in world_js
    assert "loadWorld" in world_js
    assert "saveWorld" in editor_js
    assert "selectedPaletteId" in editor_js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_assets.py::test_world_runtime_exposes_required_functions -v`

Expected: FAIL until real JS functions exist.

- [ ] **Step 3: Implement minimal renderer**

In `palette.js`, define selected palette entries matching `src/world/palette.py`.

In `world.js`, implement:

```js
const canvas = document.getElementById("world-canvas");
const ctx = canvas.getContext("2d");
ctx.imageSmoothingEnabled = false;

const imageCache = new Map();

function loadImage(src) {
  if (!imageCache.has(src)) {
    const image = new Image();
    image.src = "../" + src.replace(/^assets\//, "");
    imageCache.set(src, image);
  }
  return imageCache.get(src);
}

function drawPaletteItem(item, x, y, scale) {
  if (!item.source) {
    ctx.fillStyle = "#ffef86";
    ctx.fillRect(x, y, item.draw.w * scale, item.draw.h * scale);
    return;
  }
  const image = loadImage(item.source);
  ctx.drawImage(
    image,
    item.src.x,
    item.src.y,
    item.src.w,
    item.src.h,
    x,
    y,
    item.draw.w * scale,
    item.draw.h * scale
  );
}
```

Then expose `window.ENEWorld.loadWorld`, `window.ENEWorld.render`, and `window.ENEWorld.applyCommand`.

In `editor.js`, implement palette click selection, canvas click placement, and `saveWorld()` that calls `worldBridge.save_world_json(JSON.stringify(world))` when available.

- [ ] **Step 4: Run asset test**

Run: `pytest tests/test_world_assets.py -v`

Expected: PASS.

- [ ] **Step 5: Manual browser check**

Run app: `python main.py`

Expected:
- Tray has `마을 열기`.
- World window opens.
- Preset map appears.
- Clicking a selected palette item and then the canvas places a tile.
- Save returns success in console.

- [ ] **Step 6: Commit**

```bash
git add assets/world/palette.js assets/world/world.js assets/world/editor.js tests/test_world_assets.py
git commit -m "feat: render editable world canvas"
```

---

### Task 10: 라이선스와 문서 보강

**Files:**
- Modify: `README.md`
- Test: `tests/test_readme_licenses.py`

- [ ] **Step 1: Write or extend failing license test**

```python
from pathlib import Path


def test_readme_mentions_sunnyside_world_assets():
    readme = Path("README.md").read_text(encoding="utf-8-sig")

    assert "Sunnyside_World" in readme
    assert "license" in readme.lower() or "라이선스" in readme
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_readme_licenses.py -v`

Expected: FAIL until README mentions the asset.

- [ ] **Step 3: Add README note**

Add to third-party or asset section:

```markdown
### Sunnyside World assets

ENE can use user-provided `Sunnyside_World_ASSET_PACK_V2.1` sprites under `assets/sprites/`.
Before redistributing builds that include these assets, verify the asset pack license and include the required credit/terms.
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_readme_licenses.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_readme_licenses.py
git commit -m "docs: document world asset licensing"
```

---

## 최종 검증

- [ ] Run focused tests:

```bash
pytest tests/test_world_palette.py tests/test_world_schema.py tests/test_world_behavior.py tests/test_world_command_service.py tests/test_world_command_parsing.py tests/test_world_window.py tests/test_world_assets.py tests/test_i18n.py tests/test_readme_licenses.py -v
```

Expected: PASS.

- [ ] Run broader regression:

```bash
pytest tests/test_settings.py tests/test_app_paths.py tests/test_diary_feature.py tests/test_bridge_mood_flow.py -v
```

Expected: PASS.

- [ ] Manual smoke:

```bash
python main.py
```

Expected:
- 기존 Live2D 오버레이가 정상 표시된다.
- 트레이 메뉴에서 마을 창을 열 수 있다.
- 마을 편집기에서 프리셋, 팔레트, 저장이 동작한다.
- 에네 픽셀 아바타가 표시된다.
- `/world 연못 쪽에서 쉬어줘` 입력 시 월드 명령이 큐에 들어가고 월드 런타임이 적용한다.

## 계획 리뷰 메모

이 계획은 브레인스토밍 결과 전체를 한 번에 완성하려 하지만, 작업 순서는 각 커밋이 독립적으로 검증 가능하도록 구성했다. 가장 큰 리스크는 실제 Sunnyside 타일 좌표 선별이다. Task 1에서는 우선 안전한 source rectangle 검증 구조를 만들고, 실제 보기 좋은 좌표는 Task 9 수동 확인에서 보정한다.
