# 에네 2D 마을 월드 V1 .yy 기반 설계

## 목표

에네가 별도 2D 마을 월드에서 돌아다니고 활동하는 모습을 만든다. 사용자는 에디터에서 직접 타일과 오브젝트를 배치하고, 기본 프리셋 맵을 불러와 수정할 수 있어야 한다.

V1의 성공 기준은 에디터와 에네 이동을 모두 얇게 연결한 전체 흐름이다. 완성형 농장 RPG가 아니라, `.yy` 원본 데이터 기반 팔레트, 기본 프리셋, 저장 가능한 에디터, 충돌이 있는 월드, 에네의 자동 이동과 제한된 `/world` 행동까지 한 번에 검증한다.

## 핵심 결정

- V1은 에디터 우선 또는 생활 월드 우선이 아니라, 둘 다 얇게 연결하는 전체 흐름으로 만든다.
- 팔레트는 4096개 타일 전체 노출이 아니라 묶음 중심으로 시작한다.
- 팔레트 원천은 `Sunnyside_World_Gamemaker`의 `.yy` 파일이다.
- 사람이 타일 좌표를 임의로 찍어 팔레트를 만들지 않는다.
- Python이 `.yy`를 파싱해 검증된 `world_asset_manifest.json`을 생성한다.
- 웹 에디터와 월드 런타임은 `.yy`를 직접 해석하지 않고 manifest를 읽는다.
- 기본 프리셋은 사진 예시처럼 밝은 색과 어두운 색 잔디가 반복되는 격자 또는 줄무늬 맵이다.
- 에네의 평소 이동은 LLM 없이 알고리즘으로 처리한다.
- `/world` 같은 특별 명령에서만 제한된 행동 계획을 만든다.

## 아키텍처

V1 데이터 흐름은 다음과 같다.

1. `Sunnyside_World_Gamemaker` 원본 `.yy` 파일을 읽는다.
2. Python 변환기가 필요한 타일셋과 sprite 메타데이터를 파싱한다.
3. 변환기는 원본 값과 파일 존재 여부를 검증한다.
4. 검증된 결과를 `assets/world/generated/world_asset_manifest.json`으로 저장한다.
5. 웹 에디터는 manifest의 묶음 팔레트로 타일과 오브젝트를 보여준다.
6. 사용자가 편집한 결과는 월드 JSON으로 저장된다.
7. 월드 런타임은 같은 월드 JSON과 manifest를 사용해 맵, 충돌, 에네 이동을 렌더링한다.

PyQt 쪽은 `WorldWindow`와 `WorldBridge`를 둔다. `WorldWindow`는 별도 일반 창으로 웹 월드 런타임을 로드한다. `WorldBridge`는 월드 JSON 저장/불러오기, manifest 경로 전달, `/world` 명령 전달, 현재 월드 상태 조회를 담당한다.

기존 Live2D 오버레이와 채팅 UI는 유지한다. 2D 마을 월드는 에네의 생활 공간이며, 기존 오버레이를 대체하지 않는다.

## GameMaker 자산 파싱

V1은 아래 원본 파일을 우선 사용한다.

- `assets/sprites/Sunnyside_World_ASSET_PACK_V2.1/Sunnyside_World_Gamemaker/tilesets/tileset_sunnysideworld/tileset_sunnysideworld.yy`
- `assets/sprites/Sunnyside_World_ASSET_PACK_V2.1/Sunnyside_World_Gamemaker/sprites/spr_tileset_sunnysideworld/spr_tileset_sunnysideworld.yy`
- 대표 오브젝트 sprite `.yy`
  - `spr_deco_tree_01`
  - 울타리, 작물, 밭, 구조물 등 V1 팔레트에 포함되는 sprite
- 에네 아바타용 Human 기본 애니메이션 sprite `.yy`
  - `base_idle_strip9`
  - `base_walk_strip8`
  - `base_waiting_strip9`
  - `base_doing_strip8`

GameMaker `.yy`는 trailing comma가 있어 표준 JSON으로 바로 읽히지 않을 수 있다. V1에는 전용 `.yy` 로더를 둔다. 로더는 주석 없는 JSON 비슷한 구조를 안전하게 정규화하고, 파싱 실패 시 파일 경로와 원인을 명확히 반환한다.

## Manifest 설계

manifest는 원본 `.yy`의 사실과 ENE 월드에서 필요한 동작 속성을 분리한다.

원본에서 가져오는 값:

- tileset 이름
- sprite 참조 경로
- tile width, tile height
- out columns
- tile count
- auto tile set 이름
- auto tile set tile 번호 목록
- sprite width, height
- sprite bbox
- sprite frame id
- frame PNG 경로
- origin

ENE가 붙이는 값:

- 팔레트 그룹 이름
- 사용자 표시 라벨
- 기본 충돌 여부
- 발밑 충돌 영역
- 활동 영역 태그
- 렌더링 레이어
- 오토타일 타입 이름

이 구분을 유지해야 원본 데이터와 제품용 설정이 섞이지 않는다.

## 팔레트 범위

V1 팔레트는 묶음 중심이다.

기본 그룹:

- 바닥
  - 잔디 기본 타일
  - 밝은 잔디
  - 어두운 잔디
- 오토타일
  - `Land`
  - `Path 01`
  - `Path 02`
  - `Path 03`
  - `River`
  - 밭흙에 해당하는 원본 묶음 또는 검증된 sprite 묶음
- 오브젝트
  - 나무
  - 울타리
  - 건물 또는 구조물
  - 작물과 밭 장식
- 활동 영역
  - 농사
  - 낚시
  - 동물 돌봄
  - 휴식

4096개 전체 타일 브라우저는 V1에 넣지 않는다. 전체 브라우저는 사용자가 필요한 타일을 직접 찾을 수 있다는 장점이 있지만, 초기 제품에서는 작업 속도를 크게 떨어뜨린다.

## 기본 프리셋

기본 프리셋은 작은 마을 제작을 시작하기 위한 잔디 맵이다. 사진 예시처럼 밝은 색 잔디와 어두운 색 잔디를 반복 배치한다.

프리셋 조건:

- 밝은/어두운 잔디 타일은 manifest에 있는 팔레트 항목만 참조한다.
- 프리셋은 월드 JSON으로 저장한다.
- 사용자는 프리셋을 불러온 뒤 바로 수정할 수 있다.
- 프리셋 자체는 충돌이 없는 열린 맵으로 시작한다.
- 에네 spawn과 기본 활동 영역을 포함한다.

## 오토타일

흙길, 모래길, 물, 밭흙은 자동으로 자연스럽게 연결되어야 한다. V1은 GameMaker `.yy`의 `autoTileSets` 묶음을 원본으로 삼고, ENE 쪽에서 4방향 연결 규칙을 적용한다.

처리 방식:

1. 사용자가 오토타일 타입을 선택한다.
2. 캔버스에 칠하면 해당 칸의 semantic tile type을 저장한다.
3. 주변 상하좌우 칸 중 같은 타입을 확인한다.
4. 연결 마스크를 계산한다.
5. 해당 타입의 `autoTileSets[].tiles` 순서에서 알맞은 tile id를 선택한다.
6. 주변 같은 타입 칸도 다시 계산한다.

V1의 목표는 “원본 묶음 보존 + 안정적 연결”이다. GameMaker 편집기와 픽셀 단위로 완전히 같은 마스크 매핑을 재현하는 것은 V2 검증 항목으로 둔다.

## 충돌

캐릭터가 통과하지 못하는 요소:

- 물
- 절벽
- 건물
- 울타리
- 발밑 충돌이 설정된 큰 오브젝트

나무처럼 큰 오브젝트는 전체 이미지가 아니라 발밑 영역만 충돌로 처리한다. 기본값은 sprite bbox를 참고하되, ENE manifest에서 `footprint`를 별도로 지정한다.

예시:

```json
{
  "id": "object.tree.01",
  "sourceType": "sprite",
  "spriteName": "spr_deco_tree_01",
  "draw": {"w": 32, "h": 34},
  "footprint": {"x": 8, "y": 24, "w": 16, "h": 8},
  "blocking": true
}
```

활동 영역은 충돌이 아니다. 활동 영역은 에네가 갈 수 있는 목적지 후보와 행동 의미를 제공한다.

## 활동 영역

사용자는 에디터에서 활동 영역을 직접 지정할 수 있다.

V1 활동 타입:

- 농사
- 낚시
- 동물 돌봄
- 휴식

활동 영역 데이터:

```json
{
  "id": "pond_rest",
  "label": "연못 휴식",
  "x": 12,
  "y": 7,
  "tags": ["quiet", "rest", "water"],
  "allowedActions": ["idle", "waiting"],
  "moodWeights": {
    "calm": 1.4,
    "tired": 1.2,
    "energetic": 0.6
  }
}
```

## 에네 행동

평소 행동은 알고리즘으로 처리한다.

입력:

- 현재 위치
- 최근 방문한 활동 영역
- 현재 mood 요약
- 활동 영역 태그
- 충돌 맵
- 쿨다운

기본 흐름:

1. 갈 수 있는 활동 영역을 찾는다.
2. 최근 방문한 지점은 가중치를 낮춘다.
3. mood와 맞는 태그는 가중치를 높인다.
4. 목적지를 하나 고른다.
5. 충돌 맵을 피해 이동한다.
6. 도착하면 허용 행동 중 하나를 실행한다.

`/world` 명령은 특별 상황에서만 사용한다. LLM은 자유 행동을 직접 실행하지 않는다. 반드시 아래와 같은 제한된 계획만 반환해야 한다.

```json
{
  "targetActivityPointId": "pond_rest",
  "action": "waiting",
  "reason": "사용자가 쉬어달라고 했고, 연못 휴식 지점이 조용한 행동에 적합함"
}
```

검증에 실패하면 실행하지 않고 안전한 메시지를 반환한다.

## 웹 에디터 UI

에디터는 작업형 도구처럼 구성한다.

- 왼쪽: 묶음 팔레트
- 중앙: 픽셀 캔버스
- 오른쪽: 속성 패널
- 상단 또는 하단: 저장, 불러오기, 프리셋, 보기 모드 전환

기본 모드:

- 타일 배치
- 오브젝트 배치
- 충돌 보기
- 활동 영역 배치
- 에네 이동 미리보기

UI는 설명문 위주의 랜딩 페이지가 아니라 바로 편집할 수 있는 작업 화면이어야 한다.

## 파일 구조

생성 또는 수정 대상:

- `src/world/__init__.py`
- `src/world/yy_loader.py`
- `src/world/asset_manifest.py`
- `src/world/autotile.py`
- `src/world/schema.py`
- `src/world/behavior.py`
- `src/world/world_command_service.py`
- `src/core/world_bridge.py`
- `src/core/world_window.py`
- `src/core/app.py`
- `src/core/tray_icon.py`
- `src/core/bridge.py`
- `src/locales/ko.json`
- `src/locales/en.json`
- `src/locales/ja.json`
- `assets/world/index.html`
- `assets/world/style.css`
- `assets/world/world.js`
- `assets/world/editor.js`
- `assets/world/generated/world_asset_manifest.json`
- `assets/world/presets/grass_grid.json`
- `tests/test_world_yy_loader.py`
- `tests/test_world_asset_manifest.py`
- `tests/test_world_autotile.py`
- `tests/test_world_schema.py`
- `tests/test_world_behavior.py`
- `tests/test_world_command_service.py`
- `tests/test_world_window.py`
- `tests/test_world_assets.py`

## 검증 기준

자동 테스트:

- `.yy` 로더가 trailing comma가 있는 파일을 읽는다.
- `tileset_sunnysideworld.yy`에서 `tileWidth`, `tileHeight`, `out_columns`, `tile_count`를 읽는다.
- `Land`, `Path 01`, `Path 02`, `Path 03`, `River`의 타일 번호 목록이 원본과 일치한다.
- sprite `.yy`에서 width, height, bbox, frames를 읽고 실제 PNG 경로를 검증한다.
- manifest가 필수 팔레트 그룹을 포함한다.
- 기본 프리셋 월드 JSON이 스키마를 만족한다.
- 오토타일 연결 마스크가 안정적으로 tile id를 선택한다.
- 충돌 맵이 물, 울타리, 건물, 발밑 충돌 오브젝트를 막는다.
- 활동 영역이 목적지 후보로 선택된다.
- `/world` 계획 검증이 존재하지 않는 활동 영역과 허용되지 않은 행동을 거부한다.
- `WorldWindow`가 올바른 HTML 경로를 연다.
- 웹 자산이 manifest, 프리셋, renderer, editor 진입점을 포함한다.

수동 검증:

- ENE 실행 후 기존 Live2D 오버레이가 정상 표시된다.
- 트레이 또는 UI에서 마을 창을 열 수 있다.
- 기본 잔디 프리셋이 보인다.
- 묶음 팔레트가 `.yy` 기반 manifest에서 로드된다.
- 흙길, 모래길, 물, 밭흙이 주변 타일에 맞춰 다시 연결된다.
- 나무를 배치하면 크게 보이지만 발밑에서만 막힌다.
- 물, 울타리, 건물은 에네가 통과하지 못한다.
- 활동 영역을 배치하고 저장할 수 있다.
- 저장 후 다시 열었을 때 같은 맵이 복원된다.
- 에네가 평소 활동 영역 사이를 자동 이동한다.
- `/world 연못 쪽에서 쉬어줘` 같은 명령이 제한된 행동으로 실행된다.

## 리스크와 대응

### `.yy` 파싱

GameMaker `.yy`는 표준 JSON이 아닐 수 있다. 전용 로더로 정규화하고, 원본 파일 경로와 오류 위치를 알 수 있게 한다.

### 오토타일 매핑

`autoTileSets`의 16개 타일 순서가 ENE의 연결 마스크와 완전히 일치하는지 확인이 필요하다. V1은 원본 묶음을 그대로 보존하고 안정적인 연결 규칙을 제공한다. GameMaker와 완전 동일한 시각 재현은 별도 검증 후 V2에서 다듬는다.

### 에셋 라이선스

`assets/sprites/`는 현재 추적되지 않은 사용자 제공 에셋이다. 구현은 이 경로를 읽기 전용 원천으로 사용한다. 배포 전에 Sunnyside World 에셋 라이선스와 포함 가능 여부를 별도로 확인해야 한다.

### 제품 범위

농사, 낚시, 동물 돌봄, 휴식은 V1에서 활동 영역과 애니메이션 의미까지만 제공한다. 실제 작물 성장, 낚시 미니게임, 동물 상태 관리는 V2 이후로 둔다.

## V2 후보

- 전체 타일셋 고급 브라우저
- GameMaker 오토타일 매핑 완전 재현
- `Room1.yy`를 프리셋 맵으로 변환
- 실내맵
- 계절과 시간대 변화
- 에네 전용 픽셀 스프라이트
- 작물 성장과 수확
- 낚시 미니게임
- 동물 상태와 돌봄 루틴
- 기억, 일정, 약속에 따른 활동 영역 선택
- Live2D 오버레이와 월드 행동 감정 동기화

## 확정 기록

- V1 성공 기준: 에디터와 에네 이동을 모두 얇게 연결한 전체 흐름
- 팔레트 범위: 묶음 중심
- 팔레트 원천: GameMaker `.yy` 데이터
- 접근 방식: Python이 `.yy`를 읽어 manifest 생성
- 기본 프리셋: 밝은/어두운 잔디 반복 맵
- 평소 행동: 알고리즘 기반
- 특별 행동: `/world` 명령에서 제한된 계획 사용
