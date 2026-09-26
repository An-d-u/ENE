# 휴대폰 캐릭터 배치·표시 수명 검증

확인일: 2026-09-26. 실제 단말 시험을 제외한 로컬 구현·검증 기록이다. main 통합, push, 태그, 릴리스, APK 업로드, 설치는 수행하지 않았다.

## 구현 범위

- 휴대폰 공통 크기 50–200%, 가로·세로 0–100%를 PC 배치와 독립 조절한다.
- 앱 수명의 컨트롤러가 최초 저장값을 읽고 250ms 변경 합치기·조작 종료 저장·원자 쓰기·실패 재시도를 관리한다. 연결/등록 정리는 배치 파일을 지우지 않는다.
- 최초 화면 맞춤은 모델 기본 layout 크기로 한 번 계산하며 PC 움직임의 상대 변화만 더한다. PC 창 배치 경로는 유지한다.
- 키보드/화면 접힘과 같은 인증 연결의 동기화에서는 WebView와 SDK 모델을 유지한다. 숨김 중 모델 자동 갱신·앱 ticker·추적 RAF·몸짓 타이머·터치·접근성을 차단한다.
- PC에서 확정한 공통 움직임 20개 키를 기존 경로로 적용하며 로컬 배치를 덮지 않는다. 원격 프로토콜·라이브러리 버전은 변경하지 않았다.
- 복귀 스냅샷 적용과 새 표정이 겹치면 가장 최신 표정 하나만 복원한다. 이전 스냅샷 완료가 새 세대의 대기 상태를 지우지 못한다. 일회성 몸짓은 대기열에 넣지 않는다.

## 작업 위치와 코드 기준

기준 ENE 폴더 아래 `.worktrees/companion-character-layout/ENE`와 `.worktrees/companion-character-layout/ENE_APP`을 사용한다. 두 저장소의 브랜치 이름은 `codex/companion-character-layout`이다. 주 작업 폴더를 이동하거나 교체하지 않았다.

| 저장소 | 착수 기준 | 검증한 제품 코드 |
| --- | --- | --- |
| ENE | main `954f037`, 계획 `779eb0f` | `6f61f2f` |
| ENE_APP | 로컬 main `ad1de52` | `de0dc7b` |

ENE_APP main의 기존 미전송 9개 커밋을 그대로 조상으로 유지했다. 이후 문서 커밋은 제품 코드를 바꾸지 않는다. 기본 실행 폴더는 여전히 기존 main이므로 이번 작업을 main에 이미 적용한 것으로 간주하지 않는다. 내보낸 실행부는 이 ENE/ENE_APP 조합으로 검증했다.

## 자동 검사

ENE 격리 폴더에서 기존 Python 3.12.10 가상환경을 사용했다. Qt는 offscreen, 임시 폴더는 매 실행 고유 경로를 사용했다.

```powershell
python -B -m pytest -q --tb=short -rs -p no:cacheprovider --basetemp <새로운-시험-임시폴더>
python -B -m tools.export_companion_character --check --require-core
```

최종 전체 결과: **4,278 통과 / 1 제외 / 실패 0**. 제외 항목은 기존 `test_companion_private_files.py`의 심볼릭 링크 생성 권한 검사이며 현재 시험 계정에 권한이 없어 자체 조건으로 제외됐다. 이번 변경 때문에 테스트 기준을 낮추거나 검사를 끄지 않았다. Python 3.11 실행 파일은 있지만 pytest·PyQt6 등 의존성 환경이 없어 **3.11 실행은 미검증**이다.

전체 검사 초기에 기존 PC 쓰다듬기 하네스 2개가 새 공통 상태 파일을 적재하지 않아 실패했다. 실제 `runtime_character_state.js`와 PC 활성 상태를 하네스에 추가하고 기존 기대 동작을 유지했다. 해당 UI 검사 160개와 최종 전체 검사가 통과했다.

통합 읽기 전용 리뷰에서 복귀 스냅샷이 새 표정을 덮는 경쟁 조건 1개를 발견했다. 실제 진입점·공유 실행부로 실패를 재현한 뒤 수정했다. 이전 스냅샷 완료, 스냅샷 번호 이하의 액션, 표정 복원 중 추가 액션도 검사했다. 최종 캐릭터 런타임·진입점·내보내기·CSP 집중 검사 42개가 통과했다.

마지막 네이티브 경계 점검에서 대화 동기화 중 받은 PC 설정 변경 알림이 복귀 후 갱신되지 않는 경로를 추가 재현했다. CharacterSequence의 미적용 스냅샷 상태를 조회해 복귀 시 갱신하도록 최소 수정했고 실패 테스트를 통과시켰다. 변경 없는 단순 숨김/복귀는 추가 다운로드를 요구하지 않는다.

ENE_APP 격리 폴더에서는 기존 JDK 21·SDK·의존성 캐시를 사용했다.

```powershell
.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest --offline --dependency-verification strict --console=plain
```

JUnit XML 합산: **48개 클래스 / 280개 검사 / 실패·오류·제외 0**. Lint: **오류 0 / 경고 4**, 이전 미디어 빌드 보고서와 동일한 WebMessage 기능 확인 안내 1개, 저장 공간 API 안내 2개, 앱 아이콘 안내 1개다. 새 경고는 없다. 마지막 네이티브 보완 후 전체 단위 검사를 다시 실행했고 개발 APK와 계측 APK 빌드를 통과했다.

## APK·자산 보존

새 APK는 새 ENE_APP 작업 폴더의 `app/build/outputs/apk/debug/app-debug.apk`에만 생성했다.

- 크기: **37,745,980 바이트**.
- APK SHA-256: `567b01f599db03c9aaacfee916441419e4c84e546783c2b53c36f2db72013b07`.
- 개발 서명 인증서 SHA-256: `3f81a75e00f622babed3823947f75d329c7e1fe3440347967f883d9b4d246b90`.
- APK 캐릭터 파일 21개 모두 import manifest의 SHA-256과 일치했다. manifest 자체 이외의 추가 캐릭터 파일은 없다.
- APK의 그 외 assets는 기존 공개 도메인 목록과 ML Kit 바코드 모델 3개다. 사용자 Live2D 모델·설정/대화/등록 파일·시험 CA·개인키·환경 파일 후보는 포함되지 않았다.
- Core는 기존 로컬 파일을 복사했고 원본/두 작업 복사본 모두 `25ae938cb4fe282ce189b357bcc97e603d1e1f7ec78bf04150d401c23cdc792f`이며 207,155 바이트다. 새 다운로드는 하지 않았다.
- 기존 주 ENE_APP APK `2d89affbbdc532d30170d3f91e5289dfc35ac4d09a3997d787e6be9c7344ce02`와 이전 미디어 작업 APK `6e4430447f8cf090fb8fc93c564d97fe4cb32fa935845c0872f3ad0546cbbf4a`는 전후 일치한다.
- 주 저장소 두 곳은 착수 시 main 커밋과 깨끗한 상태를 유지했다. 기존 사용자 모델·설정·대화·백업은 읽거나 변경하지 않았다. Core·APK·local.properties·작업 폴더는 계속 Git에서 제외된다.

## 미확인과 후속 인수

계측 소스와 APK는 컴파일/빌드했지만 단말에서 실행하지 않았다. 실제 AtomicFile IO 오류/강제 종료, WebView·GPU·키보드·터치·회전·발열, 모델별 움직임 일치, 음성 체감 동작은 미검증이다. Compose 검사는 surface의 생성/해제 경계 중심이며 전체 ConnectionScreen의 실제 SYNCING 화면 전환을 단말에서 확인해야 한다.

재접속과 앱 재시작 후 배치 복원, 메시지 전송 전후 모델 유지, PC 설정 저장/모델 교체 후 배치 불변, 큰 글자에서 조절/복원/닫기 접근성을 후속 단말 인수 항목으로 남긴다. 앱 삭제/데이터 초기화에는 로컬 배치가 보존되지 않는다. Live2D 출시 허가 확인과 공개 바이너리 배포는 이번 완료 범위에 포함하지 않는다.
