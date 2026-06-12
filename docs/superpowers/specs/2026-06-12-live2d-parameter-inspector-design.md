# Live2D 파라미터 인스펙터 설계

## 배경

ENE의 Live2D 클라이언트는 모델 표시, 표정 전환, 립싱크, 시선 추적, 유휴 모션, 쓰다듬기 반응을 이미 처리한다. 하지만 Live2D 모델에 포함된 장식용 파라미터를 사용자가 직접 조절할 방법은 없다. 일부 모델은 리본, 액세서리, 의상 파츠 같은 장식을 파라미터 값으로 켜거나 조절할 수 있으므로, ENE 안에서 현재 모델의 파라미터를 탐색하고 저장할 수 있는 런타임 UI가 필요하다.

## 목표

- 현재 로드된 Live2D 모델의 파라미터 목록을 ENE 클라이언트 내부에서 확인한다.
- 사용자가 장식용 파라미터 값을 조절하고 저장할 수 있다.
- 저장된 값은 앱 재시작, 모델 재로드 후에도 유지된다.
- 저장값은 모델별로 따로 유지해 다른 모델의 파라미터와 섞이지 않는다.
- 표정, 립싱크, 시선 추적, 유휴 모션, 쓰다듬기 기능과 충돌하지 않도록 적용 순서를 분리한다.
- V1은 단일 저장값 세트를 제공하고, 프리셋/내보내기/공유 기능은 포함하지 않는다.

## 비목표

- Live2D 모델 파일 자체를 수정하지 않는다.
- 표정 편집기, 모션 편집기, 의상 프리셋 관리 시스템을 만들지 않는다.
- 파라미터가 실제로 장식인지 자동으로 완벽히 판정하지 않는다.
- LLM 응답이나 감정 시스템이 이 파라미터를 자동으로 바꾸게 하지 않는다.

## 사용자 경험

빠른 메뉴에 `Live2D` 버튼을 추가한다. 버튼을 누르면 오른쪽 floating panel 형태의 `파라미터 인스펙터`가 열린다. 패널은 기존 예정/선제/목표 패널과 같은 시각 언어를 따른다.

패널 상단에는 다음 주의문을 표시한다.

> 장식 조절용입니다. 표정, 눈, 입, 머리, 몸 움직임 관련 파라미터는 표정/립싱크/쓰다듬기와 충돌할 수 있으므로 건드리지 않는 것을 추천합니다.

패널에는 검색 입력과 `추천`, `전체`, `고정` 탭을 둔다.

- `추천`: 장식 후보로 볼 만한 파라미터만 보여준다.
- `전체`: 현재 모델에서 읽을 수 있는 모든 파라미터를 보여준다.
- `고정`: 사용자가 고정한 파라미터만 보여준다.

각 파라미터 행은 ID, 현재값, min/default/max 범위, 슬라이더, 숫자 입력, 고정 버튼, 초기화 버튼을 가진다. `저장` 버튼을 누르면 현재 모델 전용 저장값으로 기록한다. `저장 취소`가 아니라 `초기화`는 해당 파라미터 저장값을 제거하고 모델 기본값으로 되돌리는 동작이다.

## 모델별 저장 규칙

설정에는 `live2d_parameter_overrides`를 추가한다.

```json
{
  "live2d_parameter_overrides": {
    "assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json": {
      "values": {
        "ParamRibbon": 1.0
      },
      "pinned": [
        "ParamRibbon"
      ]
    }
  }
}
```

저장 key는 사용자가 설정한 `model_json_path`를 `relativize_for_storage(...)`와 같은 기존 저장 규칙에 맞춰 정규화한 문자열로 둔다. 외부 절대 경로 모델은 절대 경로 문자열을 사용한다. 이 방식은 같은 파라미터 ID가 다른 모델에서 다른 의미를 가질 때 값이 섞이는 문제를 막는다.

저장값은 공개 저장소에 커밋되지 않는 런타임 `config.json`에만 들어간다. 테스트와 문서에는 실제 사용자 모델 경로나 개인 데이터가 아닌 합성 예시만 사용한다.

## 파라미터 탐색

웹 런타임은 현재 `window.live2dModel.internalModel.coreModel`에서 파라미터 ID, 현재값, 기본값, 최소값, 최대값을 읽는다. `pixi-live2d-display`/Cubism core에서 직접 배열 이름이 환경별로 다를 수 있으므로, 구현 시에는 지원되는 getter와 배열 구조를 안전하게 감지하는 작은 helper를 둔다.

파라미터 metadata를 읽지 못하는 환경에서는 패널에 오류 메시지를 표시하고 저장 동작을 비활성화한다. 모델이 아직 로드되지 않았으면 로딩 상태를 보여주고, 모델 로드 완료 후 목록을 다시 만든다.

## 추천 필터

V1의 추천 탭은 보수적인 제외 규칙으로 만든다. 다음 prefix나 keyword를 가진 파라미터는 추천 탭에서 제외하고 전체 탭에만 노출한다.

- `ParamEye`
- `ParamMouth`
- `ParamJaw`
- `ParamTongue`
- `ParamBrow`
- `ParamAngle`
- `ParamBody`
- `ParamBreath`
- `ParamArm`
- `ParamHand`
- `ParamShoulder`
- `ParamLeg`

이 필터는 안전한 자동 판정이 아니라 “추천 탭을 덜 위험하게 만드는 장치”다. 사용자는 전체 탭에서 모든 파라미터를 볼 수 있지만, 주의문으로 표정/동작 계열 파라미터 수정을 피하도록 안내한다.

## 충돌 방지

저장된 장식 파라미터는 별도의 `사용자 오버라이드 레이어`로 다룬다. 표정, 립싱크, 시선 추적, 유휴 모션, 쓰다듬기 코드가 한 프레임에서 필요한 값을 적용한 뒤, 마지막 단계에서 저장된 오버라이드를 다시 적용한다.

구현 위치는 새 웹 런타임 chunk인 `runtime_live2d_parameters.js`가 담당한다.

- 모델 로드 완료 후 저장된 값을 초기 적용한다.
- Pixi ticker 또는 internalModel update hook 중 기존 업데이트보다 늦게 실행되는 지점에 오버라이드 적용 함수를 연결한다.
- 파라미터가 현재 모델에 없으면 무시하고 사용자에게 조용히 실패하지 않도록 패널 행에 `모델에 없음` 상태를 표시한다.
- 사용자가 슬라이더를 움직이는 동안에는 즉시 미리보기 적용을 한다.
- `저장` 전 미리보기 값은 현재 세션에서만 적용된다. 저장하지 않고 모델을 다시 불러오거나 앱을 닫으면 사라진다.

이 구조는 장식용으로 저장한 값이 표정/립싱크/쓰다듬기 쪽 파라미터를 실수로 덮어쓸 가능성은 남긴다. 그래서 추천 탭 제외 규칙과 주의문을 함께 제공한다. V1은 위험 파라미터를 완전히 막지 않고, 사용자가 전체 탭에서 직접 고르는 권한은 유지한다.

## Python 브리지

`WebBridge`에 다음 QWebChannel 메서드를 추가한다.

- `get_live2d_parameter_overrides(model_key) -> str`: 현재 모델 key의 저장값 JSON을 반환한다.
- `save_live2d_parameter_overrides(model_key, payload_json)`: 현재 모델 key의 `values`와 `pinned`를 저장한다.

`OverlayWindow`는 모델 설정을 JS로 보낼 때 `modelKey`와 저장된 override payload도 함께 보낸다. 모델 경로가 변경되면 JS는 새 모델 key 기준으로 저장값을 다시 요청하거나 전달받은 payload를 적용한다.

저장 함수는 입력 payload를 검증한다.

- `values`는 `{parameter_id: number}` 형태만 허용한다.
- 파라미터 ID는 비어 있지 않은 문자열이어야 한다.
- 값은 유한한 숫자여야 한다.
- `pinned`는 문자열 배열만 허용한다.

## 파일 구성

- `assets/web/index.html`: Live2D 버튼, 패널 DOM, 새 script chunk 추가
- `assets/web/runtime_chat_state.js`: 새 DOM 참조와 패널 상태 변수 추가
- `assets/web/runtime_ui_strings.js`: Live2D 버튼/패널 문구 반영
- `assets/web/runtime_live2d_parameters.js`: 파라미터 목록 수집, UI 렌더링, 미리보기, 저장값 적용
- `assets/web/runtime_live2d_model.js`: 모델 로드 완료 후 파라미터 인스펙터에 모델 변경을 알림
- `assets/web/style.css`: 패널, 행, 슬라이더, 주의문 스타일
- `src/core/settings.py`: `live2d_parameter_overrides` 기본값 추가
- `src/core/bridge.py` 또는 관련 mixin: 저장/조회용 QWebChannel 메서드 추가
- `src/core/overlay_window.py`: model key와 override payload를 JS에 전달
- `src/locales/*.json`: 버튼과 패널 문구 추가
- `tests/test_chat_ui_assets.py`: DOM/script 순서/오버라이드 레이어 계약 검증
- `tests/test_settings.py` 또는 bridge 관련 테스트: 설정 저장 payload 검증

## 테스트 계획

1. Asset 테스트
   - 새 runtime script가 기존 의존성 뒤, 최종 `script.js` 앞에 로드되는지 확인한다.
   - Live2D 버튼과 파라미터 패널 DOM이 존재하는지 확인한다.
   - 주의문 문구가 포함되는지 확인한다.
   - 추천 제외 prefix 목록이 포함되는지 확인한다.
   - 오버라이드 적용 함수가 프레임 후반에 호출되는 계약을 문자열 또는 helper 단위로 검증한다.

2. 설정/브리지 테스트
   - `live2d_parameter_overrides` 기본값이 `{}`인지 확인한다.
   - 모델별 key가 분리되어 저장되는지 확인한다.
   - 잘못된 payload가 저장되지 않는지 확인한다.
   - 저장값이 `settings.save()`를 통해 UTF-8 BOM JSON 설정 파일로 유지되는지 확인한다.

3. 수동 검증
   - 앱 실행 후 Live2D 패널을 열 수 있다.
   - 현재 모델 파라미터 목록이 표시된다.
   - 슬라이더 변경이 즉시 모델에 반영된다.
   - 저장 후 앱 재시작 또는 모델 재로드 시 값이 유지된다.
   - 표정 변경, 립싱크, 쓰다듬기 중에도 저장된 장식 파라미터가 유지된다.

## V2 후보

- 여러 장식 상태를 프리셋으로 저장한다.
- 파라미터 변경 전/후 스냅샷을 비교한다.
- 모델별로 “안전 파라미터”를 사용자가 직접 이름 붙인다.
- 위험 계열 파라미터를 잠금 처리하는 고급 안전 모드를 추가한다.
