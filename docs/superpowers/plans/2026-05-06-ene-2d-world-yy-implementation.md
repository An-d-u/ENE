# ENE 2D World YY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GameMaker `.yy` 원본 데이터를 기반으로 묶음 팔레트, 오토타일, 기본 잔디 프리셋, 월드 에디터, 에네 자동 이동, `/world` 명령 흐름이 얇게 연결된 ENE 2D 마을 월드 V1을 만든다.

**Architecture:** Python 도메인 모듈이 `Sunnyside_World_Gamemaker`의 `.yy` 파일을 읽어 검증된 `world_asset_manifest.json`을 생성하고, PyQt `WorldWindow`가 웹 월드/에디터를 로드한다. 웹 런타임은 manifest와 월드 JSON만 사용하며, `.yy`를 직접 해석하지 않는다. ENE 본체의 Live2D 오버레이와 채팅은 유지하고, 2D 월드는 별도 생활 공간으로 연결한다.

**Tech Stack:** Python 3.11+, PyQt6/QWebEngine/QWebChannel, Vanilla JavaScript Canvas, JSON, pytest, Pillow.

---

## 참조 문서

- 설계 문서: `docs/superpowers/specs/2026-05-06-ene-2d-world-yy-design.md`
- 기존 2D 월드 설계: `docs/superpowers/specs/2026-05-05-ene-2d-world-design.md`
- 기존 앱 진입점: `src/core/app.py`
- 기존 트레이 메뉴: `src/core/tray_icon.py`
- 기존 채팅 브리지: `src/core/bridge.py`
- 런타임 경로 유틸리티: `src/core/app_paths.py`

## 파일 구조

- Create: `src/world/__init__.py`
  - 월드 도메인 패키지 진입점.
- Create: `src/world/yy_loader.py`
  - GameMaker `.yy` 파일을 UTF-8 BOM 포함 파일에서도 읽고, trailing comma를 정규화해 Python dict로 반환한다.
- Create: `src/world/asset_manifest.py`
  - `tileset_sunnysideworld.yy`와 대표 sprite `.yy`를 읽어 manifest를 생성하고 검증한다.
- Create: `src/world/autotile.py`
  - 4방향 연결 마스크와 `autoTileSets[].tiles` 기반 tile id 선택을 담당한다.
- Create: `src/world/schema.py`
  - 월드 JSON 생성, 기본 잔디 프리셋 생성, 검증을 담당한다.
- Create: `src/world/collision.py`
  - 월드 JSON과 manifest에서 충돌 좌표를 계산한다.
- Create: `src/world/behavior.py`
  - 에네의 평소 활동 영역 선택 알고리즘을 담당한다.
- Create: `src/world/world_command_service.py`
  - `/world` 명령 파싱, 계획 프롬프트 생성, JSON 계획 파싱/검증을 담당한다.
- Create: `src/core/world_bridge.py`
  - QWebChannel 브리지. manifest, 프리셋, 월드 JSON 저장/로드, 명령 큐를 담당한다.
- Create: `src/core/world_window.py`
  - 월드 HTML 경로 계산과 QWebEngine 창 생성을 담당한다.
- Modify: `src/core/app.py`
  - 월드 창 지연 생성, 트레이 신호 연결, 종료 처리, WebBridge와 WorldBridge 연결을 추가한다.
- Modify: `src/core/tray_icon.py`
  - `world_requested` 시그널과 “마을 열기” 메뉴를 추가한다.
- Modify: `src/core/bridge.py`
  - `/world` 명령을 일반 채팅보다 먼저 처리하고 WorldBridge에 제한된 계획을 큐잉한다.
- Modify: `src/ai/diary_service.py`
  - 기존 슬래시 명령 파서 패턴에 맞춰 `/world` 파서를 추가한다.
- Modify: `src/locales/ko.json`, `src/locales/en.json`, `src/locales/ja.json`
  - 트레이 메뉴와 월드 창 UI 라벨을 추가한다.
- Create: `assets/world/index.html`
  - 월드/에디터 웹 진입점.
- Create: `assets/world/style.css`
  - 작업형 에디터 UI 스타일.
- Create: `assets/world/world.js`
  - Canvas 렌더러, 에네 프리뷰, 자동 이동 루프.
- Create: `assets/world/editor.js`
  - 팔레트 선택, 배치, 저장/불러오기, 활동 영역 배치.
- Create generated: `assets/world/generated/world_asset_manifest.json`
  - `.yy` 기반 manifest. 생성 산출물이지만 V1 기본 동작을 위해 커밋한다.
- Create generated: `assets/world/presets/grass_grid.json`
  - 밝은/어두운 잔디 기본 프리셋.
- Create tests:
  - `tests/test_world_yy_loader.py`
  - `tests/test_world_asset_manifest.py`
  - `tests/test_world_autotile.py`
  - `tests/test_world_schema.py`
  - `tests/test_world_collision.py`
  - `tests/test_world_behavior.py`
  - `tests/test_world_command_service.py`
  - `tests/test_world_window.py`
  - `tests/test_world_assets.py`
  - `tests/test_world_command_parsing.py`

---

### Task 1: GameMaker `.yy` 로더

**Files:**
- Create: `src/world/__init__.py`
- Create: `src/world/yy_loader.py`
- Test: `tests/test_world_yy_loader.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from src.world.yy_loader import load_yy_file, strip_gamemaker_trailing_commas


def test_strip_gamemaker_trailing_commas_keeps_values():
    raw = '{"name":"Room1","items":[{"x":1,},],}'

    cleaned = strip_gamemaker_trailing_commas(raw)

    assert cleaned == '{"name":"Room1","items":[{"x":1}]}'


def test_load_yy_file_reads_real_tileset():
    path = Path(
        "assets/sprites/Sunnyside_World_ASSET_PACK_V2.1/"
        "Sunnyside_World_Gamemaker/tilesets/tileset_sunnysideworld/"
        "tileset_sunnysideworld.yy"
    )

    data = load_yy_file(path)

    assert data["resourceType"] == "GMTileSet"
    assert data["name"] == "tileset_sunnysideworld"
    assert data["tileWidth"] == 16
    assert data["tileHeight"] == 16


def test_load_yy_file_reports_path_on_parse_error(tmp_path):
    broken = tmp_path / "broken.yy"
    broken.write_text('{"name":', encoding="utf-8-sig")

    with pytest.raises(ValueError, match="broken.yy"):
        load_yy_file(broken)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_yy_loader.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.world'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/world/__init__.py`:

```python
"""ENE 2D 월드 도메인 모듈."""
```

Create `src/world/yy_loader.py`:

```python
"""GameMaker .yy 파일 로더."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_TRAILING_COMMA_PATTERN = re.compile(r",(\s*[}\]])")


def strip_gamemaker_trailing_commas(raw_text: str) -> str:
    """GameMaker .yy의 trailing comma를 표준 JSON 형태로 정규화한다."""
    previous = str(raw_text or "")
    while True:
        cleaned = _TRAILING_COMMA_PATTERN.sub(r"\1", previous)
        if cleaned == previous:
            return cleaned
        previous = cleaned


def load_yy_file(path: str | Path) -> dict[str, Any]:
    """GameMaker .yy 파일을 dict로 읽는다."""
    yy_path = Path(path)
    try:
        raw_text = yy_path.read_text(encoding="utf-8-sig")
        parsed = json.loads(strip_gamemaker_trailing_commas(raw_text))
    except Exception as exc:
        raise ValueError(f"{yy_path}: .yy 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{yy_path}: .yy 최상위 값은 object여야 합니다.")
    return parsed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_yy_loader.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/world/__init__.py src/world/yy_loader.py tests/test_world_yy_loader.py
git commit -m "feat: add GameMaker yy loader"
```

---

### Task 2: `.yy` 기반 manifest 생성

**Files:**
- Create: `src/world/asset_manifest.py`
- Create generated: `assets/world/generated/world_asset_manifest.json`
- Test: `tests/test_world_asset_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from src.world.asset_manifest import (
    DEFAULT_GAMEMAKER_ROOT,
    REQUIRED_AUTOTILE_SETS,
    build_world_asset_manifest,
    validate_manifest,
    write_world_asset_manifest,
)


def test_manifest_reads_required_autotile_sets_from_yy():
    manifest = build_world_asset_manifest(bundle_root=Path("."))
    names = {item["name"] for item in manifest["tilesets"]["tileset_sunnysideworld"]["autoTileSets"]}

    assert REQUIRED_AUTOTILE_SETS <= names


def test_manifest_preserves_path01_tile_numbers_from_source():
    manifest = build_world_asset_manifest(bundle_root=Path("."))
    auto_tiles = {
        item["name"]: item["tiles"]
        for item in manifest["tilesets"]["tileset_sunnysideworld"]["autoTileSets"]
    }

    assert auto_tiles["Path 01"] == [
        449, 450, 451, 452, 453, 454, 455, 456,
        513, 514, 515, 516, 517, 518, 519, 0,
    ]


def test_manifest_validates_sprite_frames_exist():
    manifest = build_world_asset_manifest(bundle_root=Path("."))

    assert validate_manifest(bundle_root=Path("."), manifest=manifest) == []


def test_write_manifest_uses_utf8_bom(tmp_path):
    output = tmp_path / "world_asset_manifest.json"

    write_world_asset_manifest(bundle_root=Path("."), output_path=output)

    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_asset_manifest.py -v`

Expected: FAIL because `src.world.asset_manifest` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement `src/world/asset_manifest.py` with these public functions:

```python
DEFAULT_GAMEMAKER_ROOT = (
    "assets/sprites/Sunnyside_World_ASSET_PACK_V2.1/Sunnyside_World_Gamemaker"
)
REQUIRED_AUTOTILE_SETS = {"Land", "Path 01", "Path 02", "Path 03", "River"}

def build_world_asset_manifest(*, bundle_root: Path, gamemaker_root: str = DEFAULT_GAMEMAKER_ROOT) -> dict:
    ...

def validate_manifest(*, bundle_root: Path, manifest: dict) -> list[str]:
    ...

def write_world_asset_manifest(*, bundle_root: Path, output_path: Path) -> dict:
    ...
```

Implementation rules:

- Use `load_yy_file()` from `src/world/yy_loader.py`.
- Read `tilesets/tileset_sunnysideworld/tileset_sunnysideworld.yy`.
- Preserve `tileWidth`, `tileHeight`, `out_columns`, `tile_count`, `autoTileSets[].name`, `autoTileSets[].tiles`.
- Read sprite metadata for this first V1 object/character set:
  - `spr_tileset_sunnysideworld`
  - `spr_deco_tree_01`
  - `base_idle_strip9`
  - `base_walk_strip8`
  - `base_waiting_strip9`
  - `base_doing_strip8`
- For each sprite, record `width`, `height`, `bbox`, `frames[].name`, and frame PNG path.
- Derive frame PNG path as `<gamemaker_root>/sprites/<sprite_name>/<frame_name>.png`.
- Add ENE-specific `paletteGroups` after the raw source section. Keep source metadata and ENE behavior metadata separate.
- Write JSON with `encoding="utf-8-sig"`, `indent=2`, `ensure_ascii=False`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_asset_manifest.py -v`

Expected: PASS.

- [ ] **Step 5: Generate real manifest**

Run:

```powershell
@'
from pathlib import Path
from src.world.asset_manifest import write_world_asset_manifest

write_world_asset_manifest(
    bundle_root=Path("."),
    output_path=Path("assets/world/generated/world_asset_manifest.json"),
)
'@ | python -
```

Expected: `assets/world/generated/world_asset_manifest.json` exists and starts with UTF-8 BOM.

- [ ] **Step 6: Commit**

```powershell
git add src/world/asset_manifest.py tests/test_world_asset_manifest.py assets/world/generated/world_asset_manifest.json
git commit -m "feat: generate yy-based world asset manifest"
```

---

### Task 3: 월드 JSON 스키마와 잔디 프리셋

**Files:**
- Create: `src/world/schema.py`
- Create generated: `assets/world/presets/grass_grid.json`
- Test: `tests/test_world_schema.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from src.world.schema import build_grass_grid_world, validate_world, write_grass_grid_preset


def test_grass_grid_world_has_required_layers_and_spawn():
    world = build_grass_grid_world(width=20, height=12)

    assert world["version"] == 1
    assert world["tileSize"] == 16
    assert set(world["layers"]) == {"ground", "object", "collision", "activity"}
    assert world["spawn"] == {"x": 10, "y": 6}
    assert world["activityPoints"]


def test_grass_grid_uses_bright_and_dark_grass_refs():
    world = build_grass_grid_world(width=6, height=4)
    tile_ids = {cell["paletteId"] for cell in world["layers"]["ground"]}

    assert {"ground.grass.light", "ground.grass.dark"} <= tile_ids


def test_validate_world_rejects_out_of_bounds_spawn():
    world = build_grass_grid_world(width=6, height=4)
    world["spawn"] = {"x": 99, "y": 0}

    assert "spawn is outside map bounds" in validate_world(world)


def test_write_grass_grid_preset_uses_utf8_bom(tmp_path):
    output = tmp_path / "grass_grid.json"

    write_grass_grid_preset(output_path=output)

    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert validate_world(json.loads(output.read_text(encoding="utf-8-sig"))) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_schema.py -v`

Expected: FAIL because `src.world.schema` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement:

```python
def build_grass_grid_world(width: int = 24, height: int = 14) -> dict:
    ...

def validate_world(world: dict) -> list[str]:
    ...

def write_grass_grid_preset(*, output_path: Path) -> dict:
    ...
```

Schema rules:

- `layers.ground`: one cell per tile with `x`, `y`, `paletteId`.
- `layers.object`: placed sprite objects.
- `layers.collision`: explicit collision overrides.
- `layers.activity`: visible editor markers.
- `activityPoints`: runtime activity definitions.
- Default activity points:
  - `plaza_idle`
  - `pond_rest`
  - `farm_work`
  - `animal_care`
- Use `ground.grass.light` and `ground.grass.dark` in alternating columns or checker pattern.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_schema.py -v`

Expected: PASS.

- [ ] **Step 5: Generate real preset**

Run:

```powershell
@'
from pathlib import Path
from src.world.schema import write_grass_grid_preset

write_grass_grid_preset(output_path=Path("assets/world/presets/grass_grid.json"))
'@ | python -
```

Expected: `assets/world/presets/grass_grid.json` exists and is UTF-8 with BOM.

- [ ] **Step 6: Commit**

```powershell
git add src/world/schema.py tests/test_world_schema.py assets/world/presets/grass_grid.json
git commit -m "feat: add editable grass grid world preset"
```

---

### Task 4: 오토타일 연결 규칙

**Files:**
- Create: `src/world/autotile.py`
- Test: `tests/test_world_autotile.py`

- [ ] **Step 1: Write the failing test**

```python
from src.world.autotile import autotile_mask, choose_autotile_id, refresh_autotile_cells


PATH_01 = [
    449, 450, 451, 452, 453, 454, 455, 456,
    513, 514, 515, 516, 517, 518, 519, 0,
]


def test_autotile_mask_uses_four_cardinal_neighbors():
    same_type = {(1, 0), (0, 1), (-1, 0)}

    assert autotile_mask(x=0, y=0, same_type_positions=same_type) == 0b0111


def test_choose_autotile_id_uses_source_order():
    assert choose_autotile_id(PATH_01, mask=0) == 449
    assert choose_autotile_id(PATH_01, mask=15) == 0


def test_refresh_autotile_cells_updates_neighbors():
    cells = {
        (1, 1): {"semanticType": "path_01", "tileId": 449},
        (2, 1): {"semanticType": "path_01", "tileId": 449},
    }

    refreshed = refresh_autotile_cells(cells, changed={(1, 1)}, auto_tiles={"path_01": PATH_01})

    assert refreshed[(1, 1)]["tileId"] != 449
    assert refreshed[(2, 1)]["tileId"] != 449
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_autotile.py -v`

Expected: FAIL because `src.world.autotile` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement:

```python
NORTH = 1
EAST = 2
SOUTH = 4
WEST = 8

def autotile_mask(*, x: int, y: int, same_type_positions: set[tuple[int, int]]) -> int:
    ...

def choose_autotile_id(tile_ids: list[int], *, mask: int) -> int:
    ...

def refresh_autotile_cells(cells: dict, *, changed: set[tuple[int, int]], auto_tiles: dict[str, list[int]]) -> dict:
    ...
```

V1 mapping rule:

- Use mask as direct index into the 16 tile list.
- Keep this intentionally simple and covered by tests.
- Later V2 can replace this with exact GameMaker mask mapping if needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_autotile.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/world/autotile.py tests/test_world_autotile.py
git commit -m "feat: add world autotile rules"
```

---

### Task 5: 충돌과 발밑 footprint

**Files:**
- Create: `src/world/collision.py`
- Test: `tests/test_world_collision.py`

- [ ] **Step 1: Write the failing test**

```python
from src.world.collision import build_collision_grid, is_blocked


def test_water_tile_blocks_movement():
    world = {
        "width": 4,
        "height": 4,
        "layers": {
            "ground": [{"x": 1, "y": 1, "paletteId": "autotile.river"}],
            "object": [],
            "collision": [],
            "activity": [],
        },
    }
    manifest = {"palette": {"autotile.river": {"blocking": True}}}

    grid = build_collision_grid(world, manifest)

    assert is_blocked(grid, 1, 1) is True


def test_tree_blocks_only_footprint_tiles():
    world = {
        "width": 6,
        "height": 6,
        "layers": {
            "ground": [],
            "object": [{"x": 2, "y": 2, "paletteId": "object.tree.01"}],
            "collision": [],
            "activity": [],
        },
    }
    manifest = {
        "palette": {
            "object.tree.01": {
                "blocking": True,
                "footprint": {"x": 0, "y": 1, "w": 2, "h": 1},
            }
        }
    }

    grid = build_collision_grid(world, manifest)

    assert is_blocked(grid, 2, 2) is False
    assert is_blocked(grid, 2, 3) is True
    assert is_blocked(grid, 3, 3) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_collision.py -v`

Expected: FAIL because `src.world.collision` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement:

```python
def build_collision_grid(world: dict, manifest: dict) -> list[list[bool]]:
    ...

def is_blocked(grid: list[list[bool]], x: int, y: int) -> bool:
    ...
```

Rules:

- Out-of-bounds is blocked.
- Ground tiles can block if manifest `blocking` is true.
- Object tiles block by `footprint` if present.
- Object without footprint blocks its placed tile only.
- Explicit `layers.collision` overrides should be supported with `blocking: true/false`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_collision.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/world/collision.py tests/test_world_collision.py
git commit -m "feat: add world collision grid"
```

---

### Task 6: 에네 활동 선택 알고리즘

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

Implement `choose_next_activity()`:

- Accept `activity_points`, `mood_key`, `recent_ids`, `seed`.
- Reject empty activity list with `ValueError`.
- Score by `moodWeights[mood_key]`, default `1.0`.
- Multiply recent ids by `0.25`.
- Penalize entries with no `allowedActions`.
- Return one of the max-score candidates using deterministic seeded random.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_behavior.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/world/behavior.py tests/test_world_behavior.py
git commit -m "feat: add world behavior selection"
```

---

### Task 7: `/world` 명령 서비스와 파서

**Files:**
- Create: `src/world/world_command_service.py`
- Modify: `src/ai/diary_service.py`
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

- [ ] **Step 2: Write the failing service test**

```python
import pytest

from src.world.world_command_service import WorldCommandService


def test_parse_plan_json_accepts_object():
    service = WorldCommandService()

    plan = service.parse_plan_json('{"targetActivityPointId":"pond_rest","action":"waiting"}')

    assert plan["targetActivityPointId"] == "pond_rest"


def test_validate_plan_accepts_known_activity_and_action():
    service = WorldCommandService()
    world = {"activityPoints": [{"id": "pond_rest", "allowedActions": ["waiting"]}]}
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

In `src/ai/diary_service.py`:

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

Create `src/world/world_command_service.py` with:

- `build_plan_prompt(request: str, world: dict, mood_summary: str = "") -> str`
- `parse_plan_json(raw_text: str) -> dict`
- `validate_plan(plan: dict, world: dict) -> dict`

Validation rules:

- `targetActivityPointId` must exist in `world["activityPoints"]`.
- `action` must be in that point's `allowedActions`.
- Return normalized dict with `targetActivityPointId`, `action`, `reason`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_world_command_parsing.py tests/test_world_command_service.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/ai/diary_service.py src/world/world_command_service.py tests/test_world_command_parsing.py tests/test_world_command_service.py
git commit -m "feat: add world command service"
```

---

### Task 8: WorldBridge와 WorldWindow

**Files:**
- Create: `src/core/world_bridge.py`
- Create: `src/core/world_window.py`
- Test: `tests/test_world_window.py`

- [ ] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path

from src.core.world_bridge import WorldBridge
from src.core.world_window import resolve_world_html_path


def test_resolve_world_html_path_uses_bundle_root(tmp_path):
    html = tmp_path / "assets" / "world" / "index.html"
    html.parent.mkdir(parents=True)
    html.write_text("<html></html>", encoding="utf-8-sig")

    assert resolve_world_html_path(bundle_root=tmp_path) == html.resolve()


def test_world_bridge_returns_default_preset_when_file_missing(tmp_path):
    bridge = WorldBridge(world_file=tmp_path / "world.json")

    payload = bridge.get_world_json()

    assert "grass_grid" in payload or "잔디" in payload
    assert json.loads(payload)["version"] == 1


def test_world_bridge_rejects_invalid_save_payload(tmp_path):
    bridge = WorldBridge(world_file=tmp_path / "world.json")

    assert bridge.save_world_json("{bad-json") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_window.py -v`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement bridge and path resolver**

`WorldBridge` responsibilities:

- `get_world_json() -> str`
- `save_world_json(payload: str) -> bool`
- `get_asset_manifest_json() -> str`
- `get_preset_json(name: str) -> str`
- `queue_world_command(command: dict) -> None`
- `consume_pending_command_json() -> str`

Implementation notes:

- Use `get_user_file("world/world.json")` for user map storage.
- Use `load_json_data()` and `save_json_data()` from `src/core/app_paths.py`.
- If load fails or validation fails, fall back to `build_grass_grid_world()`.
- `resolve_world_html_path(bundle_root=None)` should use `get_bundle_root() / "assets" / "world" / "index.html"`.
- `WorldWindow` should create `QWebEngineView`, `QWebChannel`, register `worldBridge`, enable local file access, and load the HTML file.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_world_window.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/core/world_bridge.py src/core/world_window.py tests/test_world_window.py
git commit -m "feat: add world window bridge"
```

---

### Task 9: 트레이 메뉴와 앱 수명주기 연결

**Files:**
- Modify: `src/core/tray_icon.py`
- Modify: `src/core/app.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Test: `tests/test_i18n.py`
- Test: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: Write failing i18n test**

Append to `tests/test_i18n.py`:

```python
from src.core.i18n import I18n


def test_tray_world_label_exists():
    for language in ["ko", "en", "ja"]:
        i18n = I18n(language=language)
        assert i18n.t("tray.world") != "tray.world"
```

- [ ] **Step 2: Extend tray smoke test**

In `test_tray_icon_retranslates_menu_text_without_showing_system_tray`, add `tray.world` to temporary locales and assert:

```python
assert tray.world_action.text() == "村を開く"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_i18n.py::test_tray_world_label_exists tests/test_ui_i18n_smoke.py::test_tray_icon_retranslates_menu_text_without_showing_system_tray -v
```

Expected: FAIL because `tray.world` and `world_action` are missing.

- [ ] **Step 4: Implement tray and app integration**

In `TrayIcon`:

- Add `world_requested = pyqtSignal()`.
- Add `self.world_action = QAction("", self)` after calendar action.
- Connect `self.world_action.triggered.connect(self.world_requested.emit)`.
- Set `self.world_action.setText(tr("tray.world"))` in `retranslate_ui()`.

In `ENEApplication`:

- Import `WorldWindow`.
- Set `self.world_window = None` after Obsidian panel setup.
- Connect `self.tray_icon.world_requested.connect(self._show_world_window)`.
- Add `_show_world_window()` that creates or focuses the window.
- Close `world_window` inside `_quit_application()`.

Locale values:

- ko: `"tray.world": "마을 열기"`
- en: `"tray.world": "Open Village"`
- ja: `"tray.world": "村を開く"`

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
pytest tests/test_i18n.py::test_tray_world_label_exists tests/test_ui_i18n_smoke.py::test_tray_icon_retranslates_menu_text_without_showing_system_tray -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/core/tray_icon.py src/core/app.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_i18n.py tests/test_ui_i18n_smoke.py
git commit -m "feat: add world tray entry"
```

---

### Task 10: `/world` 명령 라우팅

**Files:**
- Modify: `src/core/bridge.py`
- Modify: `src/core/app.py`
- Test: `tests/test_world_command_service.py`

- [ ] **Step 1: Write a focused bridge helper test**

Add to `tests/test_world_command_service.py`:

```python
from src.world.world_command_service import run_world_command_plan


class FakePlanner:
    def send_message(self, prompt):
        return '{"targetActivityPointId":"pond_rest","action":"waiting","reason":"요청과 맞음"}'


class FakeWorldBridge:
    def __init__(self):
        self.queued = None

    def get_world_json(self):
        return '{"activityPoints":[{"id":"pond_rest","allowedActions":["waiting"]}]}'

    def queue_world_command(self, command):
        self.queued = command


def test_run_world_command_plan_queues_valid_plan():
    bridge = FakeWorldBridge()

    plan = run_world_command_plan(
        request="연못에서 쉬어줘",
        world_bridge=bridge,
        llm_client=FakePlanner(),
        mood_summary="calm",
    )

    assert bridge.queued == plan
    assert plan["targetActivityPointId"] == "pond_rest"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_command_service.py::test_run_world_command_plan_queues_valid_plan -v`

Expected: FAIL because helper does not exist.

- [ ] **Step 3: Implement pure helper first**

In `src/world/world_command_service.py`, add:

```python
def run_world_command_plan(*, request: str, world_bridge, llm_client, mood_summary: str = "") -> dict:
    ...
```

Rules:

- Load current world from `world_bridge.get_world_json()`.
- Build prompt.
- Call `llm_client.send_message(prompt)`.
- Parse and validate plan.
- Queue with `world_bridge.queue_world_command(plan)`.
- Return plan.

- [ ] **Step 4: Run helper test**

Run: `pytest tests/test_world_command_service.py -v`

Expected: PASS.

- [ ] **Step 5: Integrate into `WebBridge`**

In `src/core/bridge.py`:

- Import `run_world_command_plan`.
- Add `self.world_bridge = None` in `WebBridge.__init__`.
- Add:

```python
def set_world_bridge(self, world_bridge):
    """월드 창 브리지를 연결한다."""
    self.world_bridge = world_bridge
```

- Add `_handle_world_command()` near `_handle_note_command()`:

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
    try:
        run_world_command_plan(
            request=world_body,
            world_bridge=self.world_bridge,
            llm_client=self.llm_client,
            mood_summary="",
        )
    except Exception as exc:
        print(f"[Bridge] /world 명령 처리 실패: {exc}")
        self.message_received.emit("월드 행동을 정하지 못했어요. 마을 상태를 확인해 주세요.", "confused", "")
        return True
    self.message_received.emit("알겠어요. 에네가 마을에서 움직여볼게요.", "normal", "")
    return True
```

- In `send_to_ai()`, call `_handle_world_command(message)` before `/note`, `/obs`, `/diary`.
- In `reroll/edit` command reroute section, also route `/world` before `/note`.

In `src/core/app.py`:

- When `_show_world_window()` creates `WorldWindow`, call `self.overlay_window.bridge.set_world_bridge(self.world_window.bridge)` if the bridge exposes that method.
- If the world window already exists, keep the existing connection and only focus the window.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
pytest tests/test_world_command_service.py tests/test_world_command_parsing.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/core/bridge.py src/core/app.py src/world/world_command_service.py tests/test_world_command_service.py
git commit -m "feat: route world commands"
```

---

### Task 11: 웹 월드/에디터 기본 자산

**Files:**
- Create: `assets/world/index.html`
- Create: `assets/world/style.css`
- Create: `assets/world/world.js`
- Create: `assets/world/editor.js`
- Test: `tests/test_world_assets.py`

- [ ] **Step 1: Write failing asset test**

```python
from pathlib import Path


def test_world_assets_exist():
    root = Path("assets/world")
    for name in ["index.html", "style.css", "world.js", "editor.js"]:
        assert (root / name).exists()


def test_world_index_loads_required_scripts():
    html = Path("assets/world/index.html").read_text(encoding="utf-8-sig")

    assert "qwebchannel.js" in html
    assert "world.js" in html
    assert "editor.js" in html


def test_world_runtime_exposes_required_functions():
    world_js = Path("assets/world/world.js").read_text(encoding="utf-8-sig")
    editor_js = Path("assets/world/editor.js").read_text(encoding="utf-8-sig")

    assert "loadManifest" in world_js
    assert "loadWorld" in world_js
    assert "drawImage" in world_js
    assert "saveWorld" in editor_js
    assert "selectedPaletteId" in editor_js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_assets.py -v`

Expected: FAIL because web files do not exist.

- [ ] **Step 3: Implement minimal HTML/CSS**

`index.html`:

- Include UTF-8 meta.
- Include `qrc:///qtwebchannel/qwebchannel.js`.
- Include palette panel, canvas, inspector panel.
- Load `world.js` then `editor.js`.

`style.css`:

- Use a restrained tool UI.
- No landing page.
- Stable dimensions for palette buttons, canvas, inspector.
- Use `image-rendering: pixelated`.
- Ensure no horizontal overflow at 1100px and at 768px.

- [ ] **Step 4: Implement minimal JS runtime**

`world.js` should expose:

- `window.ENEWorld.loadManifest(manifest)`
- `window.ENEWorld.loadWorld(world)`
- `window.ENEWorld.render()`
- `window.ENEWorld.applyCommand(command)`
- `window.ENEWorld.tick()`

Rendering rules:

- Draw ground tiles first.
- Draw objects by y order after ground.
- Draw activity markers in editor mode.
- Draw ENE avatar after objects using current animation frame.
- Use manifest frame PNG paths for sprite images.
- For tileset tile ids, compute source rectangle with:
  - `sx = (tileId % out_columns) * tileWidth`
  - `sy = Math.floor(tileId / out_columns) * tileHeight`

`editor.js` should expose:

- `window.ENEWorldEditor.selectedPaletteId`
- `window.ENEWorldEditor.saveWorld()`
- `window.ENEWorldEditor.loadPreset(name)`
- palette click handlers
- canvas click placement

- [ ] **Step 5: Run asset test**

Run: `pytest tests/test_world_assets.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add assets/world/index.html assets/world/style.css assets/world/world.js assets/world/editor.js tests/test_world_assets.py
git commit -m "feat: add world editor web shell"
```

---

### Task 12: 웹 렌더링과 저장 흐름 통합

**Files:**
- Modify: `assets/world/world.js`
- Modify: `assets/world/editor.js`
- Modify: `src/core/world_bridge.py`
- Test: `tests/test_world_assets.py`
- Test: `tests/test_world_window.py`

- [ ] **Step 1: Add asset smoke tests**

Append to `tests/test_world_assets.py`:

```python
def test_editor_uses_qwebchannel_bridge_methods():
    editor_js = Path("assets/world/editor.js").read_text(encoding="utf-8-sig")

    assert "get_asset_manifest_json" in editor_js
    assert "get_world_json" in editor_js
    assert "save_world_json" in editor_js
    assert "consume_pending_command_json" in editor_js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_world_assets.py::test_editor_uses_qwebchannel_bridge_methods -v`

Expected: FAIL until bridge calls exist in JS.

- [ ] **Step 3: Implement bridge bootstrap in JS**

In `editor.js`:

- On load, create `new QWebChannel(qt.webChannelTransport, callback)`.
- Store `window.worldBridge`.
- Load manifest with `worldBridge.get_asset_manifest_json()`.
- Load world with `worldBridge.get_world_json()`.
- Save with `worldBridge.save_world_json(JSON.stringify(currentWorld))`.
- Poll `consume_pending_command_json()` every 1000ms and pass non-empty command to `ENEWorld.applyCommand()`.

- [ ] **Step 4: Add Python bridge method tests**

Append to `tests/test_world_window.py`:

```python
def test_world_bridge_returns_manifest_json():
    bridge = WorldBridge()

    payload = bridge.get_asset_manifest_json()

    assert "tileset_sunnysideworld" in payload
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
pytest tests/test_world_assets.py tests/test_world_window.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add assets/world/world.js assets/world/editor.js src/core/world_bridge.py tests/test_world_assets.py tests/test_world_window.py
git commit -m "feat: connect world editor to bridge"
```

---

### Task 13: 전체 검증과 문서 보강

**Files:**
- Modify: `README.md`
- Modify or Create: `tests/test_readme_licenses.py`

- [ ] **Step 1: Add README license test**

Ensure `tests/test_readme_licenses.py` includes:

```python
from pathlib import Path


def test_readme_mentions_sunnyside_world_assets():
    readme = Path("README.md").read_text(encoding="utf-8-sig")

    assert "Sunnyside_World" in readme
    assert "license" in readme.lower() or "라이선스" in readme
```

- [ ] **Step 2: Run test to verify it fails if needed**

Run: `pytest tests/test_readme_licenses.py -v`

Expected: FAIL if README does not mention Sunnyside World license handling.

- [ ] **Step 3: Add README note**

Add to the third-party/assets section:

```markdown
### Sunnyside World assets

ENE can use user-provided `Sunnyside_World_ASSET_PACK_V2.1` sprites under `assets/sprites/`.
The 2D world editor reads GameMaker `.yy` metadata from that asset pack to build its tile palette.
Before redistributing builds that include these assets, verify the asset pack license and include any required credit or terms.
```

- [ ] **Step 4: Run focused world tests**

Run:

```powershell
pytest tests/test_world_yy_loader.py tests/test_world_asset_manifest.py tests/test_world_schema.py tests/test_world_autotile.py tests/test_world_collision.py tests/test_world_behavior.py tests/test_world_command_service.py tests/test_world_command_parsing.py tests/test_world_window.py tests/test_world_assets.py tests/test_readme_licenses.py -v
```

Expected: PASS.

- [ ] **Step 5: Run broader regression**

Run:

```powershell
pytest tests/test_i18n.py tests/test_ui_i18n_smoke.py tests/test_app_paths.py tests/test_diary_feature.py tests/test_bridge_mood_flow.py -v
```

Expected: PASS.

- [ ] **Step 6: Manual smoke test**

Run:

```powershell
python main.py
```

Expected:

- 기존 Live2D 오버레이가 표시된다.
- 트레이 메뉴에서 “마을 열기”를 선택할 수 있다.
- 별도 월드 창이 열린다.
- 기본 잔디 프리셋이 표시된다.
- 묶음 팔레트가 보인다.
- 타일을 배치하고 저장할 수 있다.
- 나무는 크게 보이고 발밑에서만 막힌다.
- 물과 울타리는 통과할 수 없다.
- 활동 영역을 배치할 수 있다.
- 에네가 활동 영역 사이를 자동 이동한다.
- `/world 연못 쪽에서 쉬어줘` 입력 시 월드 명령이 큐에 들어가고 월드 런타임이 적용한다.

- [ ] **Step 7: Commit**

```powershell
git add README.md tests/test_readme_licenses.py
git commit -m "docs: document Sunnyside world assets"
```

---

## 최종 완료 기준

- 모든 world 도메인 테스트가 통과한다.
- i18n과 트레이 smoke 테스트가 통과한다.
- 앱 수동 실행에서 기존 오버레이가 깨지지 않는다.
- 월드 창을 열고 기본 프리셋을 볼 수 있다.
- 에디터에서 저장한 월드 JSON을 다시 불러올 수 있다.
- `.yy` 데이터 기반 manifest가 생성되어 커밋되어 있다.
- `assets/sprites/` 원본 에셋은 사용자가 제공한 읽기 전용 자산으로 남기고, 별도 요청 없이는 커밋하지 않는다.

## 리뷰 메모

가장 큰 리스크는 GameMaker 오토타일 16개 순서와 ENE의 4방향 마스크가 픽셀 단위로 완전히 같은지 여부다. V1에서는 원본 묶음을 그대로 보존하고 안정적으로 연결되는 편집 경험을 먼저 만든다. GameMaker 편집기와 완전 동일한 매핑은 `Room1.yy` 프리셋 변환과 함께 V2에서 별도 검증한다.
