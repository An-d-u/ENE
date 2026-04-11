# Live2D 기본 Idle 토글 설계

## 목표

ENE에서 Live2D 모델이 기본 제공하는 `Idle` 모션을 사용자가 설정에서 직접 켜고 끌 수 있게 한다.

이번 변경은 기존 ENE 커스텀 유휴 모션과 Live2D 기본 `Idle` 모션을 분리해서 제어하는 데 집중한다.

## 승인된 결정

- `유휴 모션`과 `Live2D 기본 Idle`은 별도 설정으로 분리한다.
- 새 설정은 설정 창에서 즉시 미리보기 반영이 가능해야 한다.
- 새 설정은 현재 로드된 모델에도 즉시 적용되어야 한다.
- 기존 `enable_idle_motion`은 ENE 커스텀 idle만 계속 담당한다.

## 배경

현재 `assets/web/script.js`는 모델 로드가 끝나면 `model.motion('Idle')`를 바로 실행한다.

하지만 설정 창의 기존 `유휴 모션` 토글은 JS에서 직접 계산하는 ENE 커스텀 idle 오프셋만 제어한다.
즉, 사용자는 설정상 유휴 모션을 꺼도 Live2D 모델 자체의 기본 `Idle` 모션은 계속 볼 수 있다.

이 상태는 설정 의미가 불분명하고, Live2D 기본 모션과 ENE 커스텀 모션을 각각 시험하거나 비교하려는 사용 흐름에도 맞지 않는다.

## 사용자 경험

1. 설정의 `유휴 모션` 그룹 안에 `Live2D 기본 idle 모션 활성화` 토글이 새로 보인다.
2. 이 토글을 끄면 현재 모델의 기본 `Idle` 모션이 멈춘다.
3. 이 토글을 켜면 현재 모델에서 기본 `Idle` 모션이 다시 시작된다.
4. 앱을 다시 열어도 사용자가 마지막으로 저장한 상태가 유지된다.
5. 기존 `유휴 모션 활성화` 토글은 ENE 커스텀 idle만 그대로 제어한다.

## 핵심 설계

### 1. 설정 키 분리

- 새 설정 키 이름은 `enable_builtin_idle_motion`으로 둔다.
- 기본값은 `True`로 둔다.
- 기존 `enable_idle_motion`과 의미가 겹치지 않도록 분리한다.

### 2. 설정 UI

- `src/ui/settings_dialog.py`의 `유휴 모션` 그룹에 새 토글을 추가한다.
- 텍스트는 기존 토글과 헷갈리지 않게 `Live2D 기본 idle 모션 활성화`로 표기한다.
- 로드 시 현재 설정값을 반영하고, 저장 시 `_get_current_values()`에 포함한다.

### 3. Python -> JS 동기화

- `src/core/overlay_window.py`의 idle 관련 설정 동기화 경로에 새 설정을 포함한다.
- 기존 커스텀 idle용 `window.setIdleMotionEnabled()`와 별도로, 새 `window.setBuiltinIdleMotionEnabled()`를 호출한다.
- 페이지 최초 로드, 미리보기, 실제 저장 모두 같은 경로를 재사용한다.

### 4. 웹 런타임 제어

- `assets/web/script.js`에서 기본 `Idle` 모션 활성 상태를 별도 전역 상태값으로 관리한다.
- 모델 로드 직후 `model.motion('Idle')`를 무조건 실행하지 않고, 새 상태값이 켜져 있을 때만 실행한다.
- 현재 모델에 대해 즉시 토글이 동작하도록 helper를 둔다.
  - 켤 때: 현재 모델이 있으면 `model.motion('Idle')`를 다시 시도한다.
  - 끌 때: 현재 motion manager에 대해 안전한 중지 경로를 순서대로 시도한다.

### 5. 안전성

- 모델이나 motion manager가 없으면 조용히 무시한다.
- 중지 함수가 런타임 버전에 따라 달라도, 가능한 후보를 순서대로 시도하고 실패는 경고 로그만 남긴다.
- 이 토글은 표정, 립싱크, ENE 커스텀 idle 오프셋에는 영향을 주지 않는다.

## 테스트 방향

### 설정

- 기본 설정에 `enable_builtin_idle_motion`이 존재하는지 확인한다.
- 저장/재로드 후 값이 유지되는지 확인한다.

### 웹 스크립트

- 새 토글용 런타임 훅 `window.setBuiltinIdleMotionEnabled`가 존재하는지 확인한다.
- 모델 로드 시 `model.motion('Idle')`가 새 상태값 조건 아래에서만 실행되는지 확인한다.
- 현재 모델 기본 idle을 시작/중지하는 helper가 존재하는지 확인한다.

## 비목표

- Live2D 기본 Idle 모션의 세부 강도나 속도 제어
- 모델별 기본 모션 이름 자동 탐지
- ENE 커스텀 idle과 기본 idle의 자동 상호 배타 처리
