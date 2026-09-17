# 캐릭터 실행부의 외부 구성 요소

2026-09-16에 기존 설치 스크립트의 공개 원본과 로컬 바이트 SHA-256을 대조했다. 라이브러리는 수정하거나 새 버전으로 교체하지 않았다. 이 기록은 공개 배포·상용 이용에 대한 허가나 법률 판단을 대신하지 않는다.

- Pixi.js 7.3.0: 고정된 npm 배포 파일과 일치한다. `Pixi-MIT.txt`는 해당 태그의 원문이다.
- pixi-live2d-display 0.4.0의 cubism4 빌드: 고정된 npm 배포 파일과 일치한다. `pixi-live2d-display-MIT.txt`는 해당 태그의 원문이다.
- 표시 라이브러리에 포함된 Cubism Web Framework: 상위 태그의 하위 모듈 커밋 `1f9cdfd140e87ba0ae68a356bb5ec339a0e65f99`를 확인했다. `CubismWebFramework-LICENSE.md`를 원문 그대로 보존한다. 이 파일의 과거 요금·정책 문구를 현재 정책으로 해석하지 않는다.
- Live2D Cubism Core: 공개 소스와 실행부 내보내기에서 제외한다. 사용자가 [공식 SDK 페이지](https://www.live2d.com/en/sdk/download/web/)에서 약관을 확인하고 직접 받아 로컬에 배치한다. 검증된 기존 파일의 공개 API 버전 정수는 `83951616`이며 원본 파일의 저작권·재배포 코드 고지는 변경하지 않는다. [독점 소프트웨어 계약](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html), [SDK 배포 정책](https://www.live2d.com/en/sdk/license/)을 별도로 확인해야 한다.

표시 라이브러리의 패키지 메타데이터는 Pixi 6 계열을 peer dependency로 선언하지만, 기존 PC 프로젝트는 Pixi 7.3.0을 사용한다. 이번 분리는 기존 파일을 유지한다. Node VM의 가상 렌더러 시험은 이 조합의 실제 WebGL·WebView 호환성을 증명하지 않는다. 단말 시험 전에는 호환성 검증 완료로 표시하지 않는다.

개인 모델·음성·대화·설정 파일은 이 실행부 묶음에 포함하지 않는다. 공개 배포물은 소스와 빌드 안내이며 완성 APK·Windows ZIP·SDK는 제공하지 않는다. Core 분리만으로 출시 허가 문제가 해결되지는 않는다. 특히 사용자가 모델을 추가할 수 있는 확장성 앱의 배포 조건은 출시 전에 별도로 확인한다.
