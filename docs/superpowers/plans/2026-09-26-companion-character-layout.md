# 휴대폰 캐릭터 배치 저장과 표시 수명 구현 계획

> **실행 에이전트:** `superpowers:executing-plans`로 같은 세션에서 순차 직접 구현한다. 각 작업은 `superpowers:test-driven-development`, 완료 판단과 커밋 전에는 `superpowers:verification-before-completion`을 적용한다. 작업별 구현 에이전트로 나누지 않는다. 체크박스는 앞으로 수행할 작업이며 완료 기록이 아니다.

**목표:** 휴대폰에서 크기·가로·세로 위치를 조절해 자동 저장·복원하고, PC 움직임 설정을 유지하면서 채팅 입력과 화면 접힘에 따른 불필요한 모델 재생성을 제거한다.

**구조:** 앱 수명의 배치 상태와 로컬 저장소를 연결 세션에서 분리한다. 네이티브 내부 표시 명령으로 검증된 배치·가시성만 공유 실행부에 전달한다. 화면 표시 여부와 렌더러 소유권을 분리하고 실제 종료 시 기존 자원 회수를 유지한다.

**기술:** Kotlin·Compose·Coroutine StateFlow·Android AtomicFile, 기존 WebView 응답 통로, JavaScript·Pixi 7.3.0·pixi-live2d-display 0.4.0-cubism4, Node VM·pytest, Gradle offline/strict 검증. 라이브러리 추가나 버전 변경은 없다.

---

기준 문서는 [승인된 설계](../specs/2026-09-26-companion-character-layout-design.md)다. ENE 작업 브랜치는 `codex/companion-character-layout`, 설계 커밋은 `3f6d0bf`다. 작성 시 기존 ENE main은 `954f037`, ENE_APP main은 `ad1de52`이며 ENE_APP의 기존 미전송 커밋 9개를 보존한다. 실제 구현 시작 시 다시 확인한다.

이번 요청에서는 계획만 작성한다. 아래 코드, 명령과 커밋은 **구현 착수 후** 수행한다. main 통합·push·태그·릴리스·실기기 설치는 이 계획의 자동 실행 대상이 아니다.

## 공통 경로와 실행 규칙

아래 초기화는 기존 최종 ENE 폴더에서 실행한다. 다른 PowerShell 호출에서는 변수를 다시 준비하거나 확인한 절대 작업 경로를 명시한다. 개인 절대 경로·환경변수 전체·`local.properties` 원문을 공개 문서나 로그에 붙이지 않는다.

```powershell
$eneSourceRoot = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0) { throw 'ENE 경로 확인 실패' }
$appSourceRoot = Join-Path (Split-Path -Parent $eneSourceRoot) 'ENE_APP'
$layoutRoot = Join-Path $eneSourceRoot '.worktrees/companion-character-layout'
$eneWorkRoot = Join-Path $layoutRoot 'ENE'
$appWorkRoot = Join-Path $layoutRoot 'ENE_APP'
$py = Join-Path $eneSourceRoot '.venv/Scripts/python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
```

- ENE의 격리 폴더는 이미 존재한다. ENE_APP 격리 폴더는 작업 0에서 현재 로컬 main으로 만든다. 오래된 미디어 작업 폴더를 새 변경의 기준으로 사용하지 않는다.
- 파일 목록에서 `K/`는 ENE_APP `app/src/main/java/dev/ene/companion/`, `U/`는 `app/src/test/java/dev/ene/companion/`, `I/`는 `app/src/androidTest/java/dev/ene/companion/`를 뜻한다. ENE 경로는 ENE 작업 루트 기준이다.
- 모든 새 파일은 UTF-8 BOM 없음. 로컬 편집은 `apply_patch`, 공유 파일의 기계적 복사는 기존 내보내기 도구를 사용한다.
- 기존 코드·백업·Core·모델·APK·등록·설정·대화를 삭제하거나 이동하지 않는다. 설정과 대화를 테스트 fixture로 읽지 않는다. 합성 모델 정보와 합성 대화만 사용한다.
- 아래 pytest 명령 직전에 `Set-Location $eneWorkRoot`와 새 임시 경로를 준비한다. `--basetemp`는 매 실행 새로운 경로를 사용한다.

```powershell
$testRun = Join-Path $env:TEMP ('ene-character-layout-' + [guid]::NewGuid().ToString('N'))
```

- 각 외부 명령 직후 `$LASTEXITCODE`를 확인하고 실패 시 중단한다. 권한 문제는 허용된 실행 권한으로 재시도하며 검사 기준을 바꾸지 않는다.
- Gradle 명령은 `$appWorkRoot`에서 실행한다. 기존 JDK·Android SDK·Gradle 캐시를 사용하며 `--offline --dependency-verification strict --console=plain`을 유지한다. 설치 경로가 필요하면 기존 설정에서 SDK 경로 항목만 읽고 새 작업 폴더의 제외된 `local.properties`에 작성한다.
- 각 작업은 실패 테스트 → 최소 수정 → 집중 통과 → 변경 검토 → 영어 로컬 커밋 순서다. 전체 검사는 최종 통합 시 실행한다. 저장소별로 정확한 경로만 스테이징하고 실제 이름·대화·건강/일정/프로필·API 키 후보, 금지 런타임 파일과 바이너리를 검사한다. 넓은 `git add .`는 사용하지 않는다.
- 문서만 작성한 현재 단계에는 기존 캐릭터 실행부·진입점 검사 20개 통과 기록만 있다. 새 기능의 통과 결과로 인용하지 않는다.

## 작업 0. 작업 공간과 보존 기준 준비

**대상:** Git 상태, 기존 Core·개발 APK, 가상환경·SDK. 제품 코드 변경 없음.

- [ ] **0.1** 양쪽 최종 폴더와 기존 ENE 작업 폴더에서 `git status --short --branch`, `git rev-parse HEAD`, `git worktree list --porcelain`을 확인한다. 미커밋 변경은 보존한다. 착수 기준이 달라졌으면 변경 범위와 충돌 여부를 확인하고 필요 시 계획 기준을 갱신한다. reset/rebase로 맞추지 않는다.
- [ ] **0.2** ENE에서 `.worktrees/` 제외와 대상 폴더·브랜치 부재를 확인한 뒤 ENE_APP 작업 트리만 만든다. 기존 경로가 있으면 생성 명령을 재실행하거나 덮어쓰지 않는다.

```powershell
git -C $eneSourceRoot check-ignore -v .worktrees/companion-character-layout/ENE_APP
git -C $appSourceRoot worktree add $appWorkRoot -b codex/companion-character-layout main
```

- [ ] **0.3** 양쪽 기존 Core의 크기·SHA-256·Git 제외를 확인한다. 필요한 격리 폴더에 **기존 Core 한 파일만** 복사한다. ENE 대상은 `assets/web/lib/live2dcubismcore.min.js`, ENE_APP 대상은 `app/src/main/assets/character/lib/live2dcubismcore.min.js`다. 대상이 이미 있으면 해시를 비교하고 다르면 중단한다. 원본과 대상 해시가 manifest의 고정 해시와 같아야 한다. 모델·사용자 설정을 복사할 필요는 없다.
- [ ] **0.4** 기존 ENE_APP 및 이전 미디어 격리 폴더의 APK 존재·해시를 기록한다. 새 APK는 새 작업 폴더에서만 빌드한다. 그곳에도 이전 APK가 있다면 ENE의 제외된 `backups/` 아래 새 고유 폴더로 복사하고 해시 대조 후에만 재빌드한다. 원본 APK는 보존한다.
- [ ] **0.5** 출발점의 집중 검사를 실행하고 예상 통과를 확인한다. 기존 실패가 있으면 새 변경의 실패와 구분하고 해결 방향을 확인한다.

```powershell
& $py -B -m pytest tests/test_companion_character_runtime.py tests/test_companion_character_entry.py tests/test_companion_character_state.py tests/test_companion_character_bridge.py -q -p no:cacheprovider --basetemp $testRun
```

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests dev.ene.companion.CharacterSessionTest --tests dev.ene.companion.CharacterSequenceTest --tests dev.ene.companion.CharacterLayoutTest --tests dev.ene.companion.CharacterBridgeTest --offline --dependency-verification strict --console=plain
```

## 작업 1. 로컬 배치 자료와 자동 저장

**파일:**

- 신설: `K/character/CharacterPlacement.kt`, `K/character/CharacterPlacementController.kt`, `K/storage/CharacterPlacementStore.kt`.
- 신설 검사: `U/CharacterPlacementTest.kt`, `U/CharacterPlacementControllerTest.kt`, `I/CharacterPlacementStoreTest.kt`.
- 참고만: `K/storage/ConnectionSettingsStore.kt`의 `readAtomic`, `writeAtomic`, `requireNoBackupDirectory`. 기존 연결 저장 형식은 변경하지 않는다.

- [ ] **1.1** 값과 저장 형식의 단위 검사를 작성한다. 기본값, 양 끝 범위, NaN/무한대/문자열 숫자/누락/여분 키/잘못된 버전/범위 밖 값의 거절, 직렬화 왕복을 검사한다. 아래 자료형과 별도로 `CharacterPlacementCodec`을 같은 파일에 두며 코덱은 Android API를 참조하지 않는다.

```kotlin
data class CharacterPlacement(
    val scale: Double = 1.0,
    val xPercent: Double = 50.0,
    val yPercent: Double = 50.0,
) {
    init {
        require(scale.isFinite() && scale in 0.5..2.0)
        require(xPercent.isFinite() && xPercent in 0.0..100.0)
        require(yPercent.isFinite() && yPercent in 0.0..100.0)
    }
}

interface CharacterPlacementStorage {
    fun load(): CharacterPlacement?
    fun save(value: CharacterPlacement)
}
```

저장 형식은 `{"version":1,"scale":1.0,"xPercent":50.0,"yPercent":50.0}`의 정확한 네 키다. `ProtocolCodec`의 엄격한 객체/숫자 검사 패턴을 사용하고 오류는 고정 코드로 변환한다. 최대 8 KiB, UTF-8 엄격 해석을 유지한다.

- [ ] **1.2** `CharacterPlacementControllerTest`에 가짜 저장소와 코루틴 가상 시간을 사용한다. 첫 읽기 전 변경 차단, 파일 없음, 읽기 오류 기본값과 경고, 변경 후 250ms 합치기, 조작 종료 즉시 저장 요청, 저장 중 새 변경, 오래된 저장 완료, 실패 후 재시도, 새 컨트롤러의 복원을 각각 검사한다. 첫 실패를 확인한다. 선언 누락을 정리한 뒤에도 새 동작을 제거하면 행동 검사가 실패해야 한다.

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests dev.ene.companion.CharacterPlacementTest --tests dev.ene.companion.CharacterPlacementControllerTest --offline --dependency-verification strict --console=plain
```

- [ ] **1.3** `CharacterPlacementStore`를 구현한다. 기본 경로는 `noBackupFilesDir/character_presentation/placement.json`이며 모델 캐시·`companion` 등록 폴더 밖이다. 기존 AtomicFile 도우미로 원자 저장하고 읽어 같은 값인지 확인한 뒤 성공을 반환한다. 단순 읽기 실패 시 파일을 쓰거나 지우지 않는다. `clear()`를 연결 정리 경로에 추가하지 않는다.
- [ ] **1.4** 컨트롤러에 `StateFlow`를 둔다. 공개 상태는 배치, `loaded`, 저장 상태(`idle`, `dirty`, `saving`, `error`), 읽기 실패 여부다. 앱 수명의 scope와 IO dispatcher를 주입한다. 초기 읽기는 한 번만 실행하며 끝날 때까지 배치 컨트롤과 최초 렌더러 표시를 기다리게 한다. 채팅 연결 자체는 기다리지 않는다.
- [ ] **1.5** 자동 저장을 다음 순서로 구현한다. Main에서만 목표값·수정 번호·상태를 갱신한다. 하나의 writer만 IO 저장을 수행하고 완료는 Main으로 돌려보낸다.

| 입력/결과 | 처리 |
| --- | --- |
| `change(value)` | 검증 후 즉시 상태 반영, 수정 번호 증가, 250ms 저장 요청을 재예약 |
| `finishAdjustment()` | 예약만 취소하고 현재 수정 번호의 즉시 저장을 요청 |
| writer가 저장 중 | 저장 작업은 취소하지 않고 최신 목표값을 보관; 동시에 두 쓰기 금지 |
| 저장 성공 | 저장한 수정 번호만 완료로 기록; 최신 번호와 다르면 완료 UI를 표시하지 않고 다음 최신값 저장 |
| 저장 실패 | 마지막 정상 파일과 미리보기 보존; 최신 목표와 같은 번호면 `error`로 정지, 더 최신 번호가 대기 중이면 그 값의 저장은 계속; 실패한 같은 번호를 무한 재시도하지 않음 |
| 새 수정 또는 `retrySave()` | 최신 값으로 새 저장 요청; 읽기 실패 경고는 정상 쓰기 후 해제 |
| `reset()` | 기본값 전체를 한 번에 반영하고 즉시 저장; 다른 배치 파일/PC 설정은 변경하지 않음 |

변경 예약용 Job과 실제 writer를 분리한다. `collectLatest { store.save(...) }`로 진행 중인 원자 쓰기를 취소하지 않는다. 마지막 저장 완료 후 다시 로드했을 때 같은 값이어야 한다. 화면 회전·재접속에서 컨트롤러를 새로 만들지 않는다.

- [ ] **1.6** Android 계측 검사에는 실제 AtomicFile 왕복, 잘못된 형식에서 원본 보존, 저장 실패 시 마지막 정상 파일 보존, 백업 대상 경로 거절을 추가한다. 시험 디렉터리는 앱 noBackupFilesDir의 고유 시험 폴더 하나로 한정한다. 이번에는 컴파일만 하며 AtomicFile의 실제 단말 IO를 JVM 대역 검사로 대체했다고 보고하지 않는다.
- [ ] **1.7** 위 JVM 검사 통과, 변경 검토·개인정보 검사를 마치고 ENE_APP에 `feat: persist phone character placement`로 로컬 커밋한다. 앱 연결 주입은 작업 3에서 한다.

## 작업 2. 공유 실행부의 배치와 숨김 처리

**ENE 파일:**

- 수정: `assets/web/runtime_character_state.js`, `runtime_character_host.js`, `runtime_live2d_model.js`, `runtime_auto_blink_tracking.js`, `runtime_gesture_engine.js`, `runtime_head_pat.js`, `assets/web/character/entry.js`.
- 수정 검사: `tests/test_companion_character_runtime.py`, `tests/test_companion_character_entry.py`.
- 수정: `contracts/companion/character-runtime.json`에서 실제 바뀐 소스의 SHA-256만 갱신.
- 내보내기 대상: ENE_APP `app/src/main/assets/character/`의 해당 파일과 `import-manifest.json`. 라이브러리·Core·고지·HTML 로드 목록은 그대로다.

- [ ] **2.1** Node VM 하네스에 `model.autoUpdate`, `app.start/stop`, 실제 모델 배율/좌표, `internalModel.width/height`, 모델 생성·파괴·fetch 횟수 기록을 추가한다. 현재 `scale:1` 고정과 키보드 숨김 미지원 때문에 실패하는 검사를 작성한다.
- [ ] **2.2** 휴대폰 배치 계산의 기준을 고정한다. 로딩 직후 `internalModel.width/height`를 읽어 **모델 객체마다 한 번** 저장한다. 이는 번들 라이브러리에서 모델 기본 layout을 반영한, 화면 확대 이전 크기다. 애니메이션 중 `model.width/height`나 현재 변형된 bounds로 다시 기준을 잡지 않는다. 비정상 크기는 렌더 실패로 처리한다.

```javascript
function calculatePhonePlacement(width, height, modelWidth, modelHeight, placement, root) {
    const finite = [width, height, modelWidth, modelHeight, placement.scale,
        placement.xPercent, placement.yPercent].every(Number.isFinite);
    if (!finite || modelWidth <= 0 || modelHeight <= 0) return null;
    if (width <= 0 || height <= 0) return null;
    if (placement.scale < 0.5 || placement.scale > 2 ||
        placement.xPercent < 0 || placement.xPercent > 100 ||
        placement.yPercent < 0 || placement.yPercent > 100) return null;
    const offsets = normalizeLive2DRootMotionOffsets(root);
    const fit = Math.min(width * 0.9 / modelWidth, height * 0.9 / modelHeight);
    return {
        scale: fit * placement.scale * (1 + offsets.rootScale),
        x: width * (placement.xPercent + offsets.rootXPercent) / 100,
        y: height * (placement.yPercent + offsets.rootYPercent) / 100,
    };
}
```

가로·세로 각각 10% 여유, 중앙 기본 배치에서는 양쪽 약 5%씩이다. 합성 모델 100×200, 표시 영역 400×200이면 기본 배율은 0.9다. 배율 1.5, 위치 25/75이면 실제 배율 1.35, 중심 (100,150)이어야 한다. 같은 모델로 200×400 영역에 바꾸면 실제 배율 2.7, 중심 (50,300)이다. 숨김의 0 크기에서는 기존 계산값과 저장값을 유지한다. PC의 기존 최소 배율 0.05 제한을 휴대폰의 큰 원본 모델에 적용해 화면 맞춤을 깨뜨리지 않는다.

- [ ] **2.3** `applyCurrentModelPlacement`에서 `characterHost.kind === 'phone'`일 때만 새 계산을 사용한다. PC 경로는 그대로 유지한다. 신규 배치는 모델을 로딩하기 전부터 호스트에 저장할 수 있어야 하며 최초 유효한 크기에서 바로 적용한다. `applySnapshot`의 휴대폰 고정 `scale:1/xPercent:50/yPercent:50` 덮어쓰기를 제거하고 로컬 배치와 공통 설정을 분리한다.
- [ ] **2.4** 내부 명령 이름을 `presentation`, 자료를 아래 형태로 고정한다. 원격 확장 프로토콜에는 넣지 않는다. 새 `character.applyPresentation()`은 동일 값 재전달에 안전하며 모델 로딩을 시작하지 않는다. `entry.js`는 현재 문서 세대 확인 후에만 전달한다. 자료의 키·숫자·boolean을 검사하고 잘못된 명령은 배치를 바꾸지 않는다.

```json
{"placement":{"scale":1.5,"xPercent":25,"yPercent":75},"visible":false}
```

- [ ] **2.5** 숨김에서는 모델을 파괴하지 않고, 해당 모델의 `autoUpdate=false`, `app.stop()`, 추적 RAF 취소를 함께 수행한다. 번들 모델의 자동 갱신은 `PIXI.Ticker.shared`에 등록되므로 **app.stop만 호출해서 끝내지 않는다**. 공유 Ticker 자체를 전역 정지하지도 않는다.
- [ ] **2.6** 숨김 직전에 쓰다듬기 취소·입 닫기·합성 제스처 정리·대기 제스처 타이머 및 감정 복원 타이머 취소를 실행한다. 숨김 중 새 스냅샷이 설정 함수를 다시 호출해 타이머를 재시작하지 못하도록 추적/제스처/쓰다듬기 진입부에 휴대폰 표시 가능 조건을 적용한다. 설정값 자체를 false로 덮어쓰지 않는다.
- [ ] **2.7** 다시 표시할 때 유효한 영역으로 배치를 적용하고 최신 설정/표정, 현재 음성 상태를 복원한 뒤 모델 자동 갱신·app ticker·추적 RAF를 각각 한 번만 재개한다. 오래 쉰 시간을 큰 delta로 적용하지 않도록 추적 시간 기준을 현재로 재설정한다. 숨김 도중 새 모델이 로딩되어도 숨김 상태를 유지한다.
- [ ] **2.8** 스냅샷·표정·로컬 배치 변경과 숨김/복귀를 반복하여 모델 객체 정체성 유지, 생성 횟수 1, 숨김 시 활성 RAF/제스처 타이머 0을 확인한다. 기존 모델 경로 재사용을 유지하고 동일 버전에서 전체 자산을 다시 읽지 않는다. 모델 교체와 dispose에서는 기존 정리가 정상 수행되어야 한다.
- [ ] **2.9** 호스트 반환 메서드 집합을 검사하는 기존 테스트는 `applyPresentation`을 포함한 정확한 집합으로 갱신한다. 하네스의 휴대폰 kind는 실제 값 `phone`을 사용한다. PC 호스트의 기존 배율/위치, 모션, 쓰다듬기, 종료 검사도 그대로 통과해야 한다.

```powershell
& $py -B -m pytest tests/test_companion_character_runtime.py tests/test_companion_character_entry.py -q -p no:cacheprovider --basetemp $testRun
```

- [ ] **2.10** 변경 소스 해시를 구해 계약에 반영하고 기존 도구로 새 ENE_APP 작업 폴더에 내보낸다. 사용자 변경 감지 오류는 강제 덮어쓰기로 우회하지 않는다. Core 해시는 전후가 같아야 한다.

```powershell
& $py -B -m tools.export_companion_character --check --require-core
& $py -B -m tools.export_companion_character --android-root $appWorkRoot --require-core
& $py -B -m pytest tests/test_companion_character_export.py tests/test_companion_character_csp.py -q -p no:cacheprovider --basetemp $testRun
```

- [ ] **2.11** 집중 통과와 안전 검사 후 ENE에 `feat: support phone character placement and suspension`, ENE_APP의 내보낸 파일에는 `chore: sync phone character presentation runtime`로 각각 커밋한다. 내보내기에는 정상 공개 소스·기존 라이브러리 고지만 포함되며 Core는 추가하지 않는다.

## 작업 3. 네이티브 배치 주입과 캐릭터 수명 분리

**ENE_APP 파일:**

- 수정: `K/EneApplication.kt`, `K/connection/ConnectionRepository.kt`.
- 수정: `K/character/CharacterPlatform.kt`, `CharacterSession.kt`, `CharacterSequence.kt`, `CharacterBridge.kt`, `CharacterWebView.kt`.
- 수정 검사: `U/CharacterSessionTest.kt`, `CharacterSequenceTest.kt`, `CharacterBridgeTest.kt`, `ConnectionRepositoryTest.kt`, `I/CharacterWebViewTest.kt`.

- [ ] **3.1** `CharacterRenderer`에 검증된 표시 상태를 받는 `present(placement: CharacterPlacement, visible: Boolean)`을 추가하고 구현과 시험 대역을 갱신한다. Kotlin 자료형뿐 아니라 내부 명령의 정확한 키 집합과 바이트 상한도 검사한다. 공개 `CharacterViewState`에는 `retainRenderer`와 `presentationAllowed`를 추가해 뷰 소유권과 실제 표시를 분리한다.
- [ ] **3.2** 먼저 가짜 renderer로 다음 실패를 재현한다. 정상 대화 이벤트 반복 시 같은 renderer와 로딩 수 유지, 같은 인증 연결의 sync false→true에서 보존, 숨김 중 제스처 미재생, 표정 현재값 복원, 최신 입 모양만 복원, 실제 shutdown에서 clear 한 번. 기존 종료 테스트를 지우거나 느슨하게 하지 않는다.
- [ ] **3.3** 배치 컨트롤러를 `EneApplication`에서 한 번 생성하고 Repository에 주입한다. Repository는 배치 StateFlow를 읽어 현재 세션에 전달한다. 연결 종료는 배치 컨트롤러를 닫거나 초기화하지 않는다. UI의 배치 변경은 컨트롤러를 직접 거치며 `CharacterSettingsPatch`나 임의 WSS 메시지를 보내지 않는 검사도 추가한다.
- [ ] **3.4** CharacterSession에 `panelVisible`과 최신 배치의 준비 상태를 둔다. 설정/다운로드 가능 여부의 기존 `available()`과 표시·입력 조건을 분리한다. 최종 가시성은 `available && panelVisible && placementLoaded && 현재 모델 표시 가능`이다. 숨김은 `resumed(false)`나 `detach()`로 표현하지 않는다.
- [ ] **3.5** `retainRenderer`는 현재 인증 세션에서 확인된 모델을 얻은 후 유지하되 오류·실제 shutdown에서는 false로 한다. 같은 세션의 대화 sync false와 새 모델 다운로드 동안에도 소유권을 유지할 수 있지만 표시/입력은 검증 상태에 맞게 차단한다. 모든 baseState·resumed·load·fail·shutdown 전환에서 새 플래그를 publish한다. 설정 화면 상태가 같다고 이 갱신을 생략하지 않는다.
- [ ] **3.6** sync false 또는 숨김 처리 시 네이티브가 즉시 `present(..., false)`와 쓰다듬기 취소를 전달한다. Compose의 다음 재구성까지 권한 차단을 미루지 않는다. 네이티브 head_pat_input 수락과 HeadPatState 시각 효과에도 실제 표시 조건을 사용한다.
- [ ] **3.7** 숨김 중 action_seq는 계속 관찰한다. 정상 순서의 표정은 `CharacterSequence.snapshot`의 현재값을 갱신하되 숨김 중 렌더 명령은 보내지 않는다. 제스처는 버린다. 숨김만으로 `sequence.detached()`를 호출해 모든 표정을 누락 처리하지 않는다. 실제 누락/버전 불일치만 기존 snapshot 복구 경로를 사용한다. 복귀 시 최신 snapshot과 현재 playback을 보내되 TTS 재시작 요청은 없다.
- [ ] **3.8** WebView는 문서 준비 전 최신 presentation 한 개만 보관한다. document_ready 때 **presentation → 최신 pending snapshot** 순서로 보내므로 저장된 배치와 숨김 상태가 첫 프레임보다 앞선다. close에서 pending presentation을 정리하고, 이미 종료된 뷰·이전 문서 세대의 입력을 거절한다. 현재 세대의 presentation은 반복 전달해도 부작용이 없어야 한다.
- [ ] **3.9** `CharacterBridge.command`에 `presentation` 하나만 추가하고 2 KiB 상한과 정확한 자료 검증을 적용한다. entry.js의 고정 출처·문서 세대·CSP·네트워크 차단을 그대로 유지한다. raw JavaScript 평가 통로는 만들지 않는다.
- [ ] **3.10** 같은 renderer의 동일 모델 snapshot 적용 때문에 기존 유효한 읽기 스트림을 불필요하게 닫는지 확인한다. `CharacterWebView.show`가 설정만 바뀐 동일 immutable 모델 mount를 재사용할 수 있도록 버전·자산 목록을 비교한다. 다른 모델 교체/clear/close의 스트림·핀 정리는 유지한다. 모델 JSON 재조회와 전체 모델 자산 재생성을 구분해 검사한다.

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests dev.ene.companion.CharacterSessionTest --tests dev.ene.companion.CharacterSequenceTest --tests dev.ene.companion.CharacterBridgeTest --tests dev.ene.companion.ConnectionRepositoryTest --tests dev.ene.companion.CharacterRuntimeTest --offline --dependency-verification strict --console=plain
```

- [ ] **3.11** 내부 문서 왕복 계측 검사에 준비 전 여러 배치 중 최종값만 전달, close 후 전달 차단을 추가한다. 검사는 실제 WebMessage 통로를 사용하고 보안 설정을 풀지 않는다. 이번 실행은 계측 APK 컴파일까지다.
- [ ] **3.12** 집중 통과와 diff 검토 후 `fix: separate character visibility from session lifetime`으로 커밋한다.

## 작업 4. 표시 설정 UI와 안정된 AndroidView 소유권

**ENE_APP 파일:**

- 수정: `K/ui/CharacterPanel.kt`, `K/ui/ConnectionScreen.kt`.
- 신설: `K/ui/CharacterPlacementSheet.kt`.
- 수정 검사: `U/CharacterLayoutTest.kt`, `I/CharacterScreenTest.kt`.
- 신설 검사: `I/CharacterPlacementScreenTest.kt`.

- [ ] **4.1** CharacterPanel에서 renderer가 없는 설정/상태 UI와 renderer surface를 작은 composable 경계로 나눈다. 기존 factory를 기본값으로 두고 계측 테스트에서는 단순 View와 생성/해제 카운터를 주입할 수 있게 한다. 제품 경로에서 시험 전용 분기를 켜지 않는다.
- [ ] **4.2** Compose 계측 검사를 먼저 작성한다. 표시 높이 >0→0→>0, 채팅 상태 재구성, 같은 연결의 CONNECTED→SYNCING→CONNECTED에서 생성 1/해제 0을 기대한다. retry generation 변화와 실제 종료에서는 기존 뷰가 정확히 해제되는지도 검사한다. 이 행동은 JVM의 순수 높이 계산 검사만으로 증명했다고 보고하지 않는다.
- [ ] **4.3** `ConnectionScreen`의 `CONNECTED` 조건문 밖에서 CharacterPanel을 안정적으로 호출한다. 실제 AndroidView 존재 여부는 `retainRenderer && placementLoaded`로 결정하고 key는 기존 renderer 세대를 사용한다. 키보드·height·메시지 개수를 key에 넣지 않는다. 명시적 retry와 새 연결의 세대 변화는 유지한다.
- [ ] **4.4** 접힘에서는 뷰를 구성에서 제거하지 않는다. 높이 0의 잘린 컨테이너와 native invisible/touch 차단/접근성 descendants 차단을 적용하고 세션에 panelVisible=false를 알린다. 보이는 컨테이너의 높이는 기존 계산을 유지한다. 0 크기에서 WebView resize가 와도 작업 2의 배치 계산은 유효한 이전 값을 보존한다. 복귀 때 native 표시와 세션 표시 허용을 함께 확인한다.
- [ ] **4.5** 별도 `휴대폰 표시 설정` 버튼과 스크롤 가능한 설정 시트를 추가한다. 기존 `캐릭터 공통 설정`은 그대로 두고 PC 저장 안내를 유지한다. 로컬 설정을 열 때 키보드를 닫고 입력 포커스를 정리한다. 화면이 작아 시트 뒤의 모델이 보이지 않더라도 설정을 닫으면 조절 결과를 확인할 수 있고 복원 버튼은 항상 접근 가능하다.
- [ ] **4.6** 시트에 크기 50–200%, 가로·세로 0–100% 슬라이더, 현재 수치, 기본 배치 복원, 저장 상태를 표시한다. `onValueChange`는 전체 배치 복사본을 controller.change로 전달하고 `onValueChangeFinished`는 finishAdjustment를 호출한다. 닫기 때도 마지막 저장을 요청한다. 로컬 조절에 PC 설정 sheet의 preview/submit API를 사용하지 않는다.
- [ ] **4.7** 읽기 완료 전에는 슬라이더를 비활성화한다. dirty/saving에는 저장 중, 최신 revision 저장 완료에만 저장됨, 오류에는 고정 안내와 저장 재시도를 표시한다. 초기 읽기 오류 안내는 저장 오류와 구분한다. 슬라이더에는 역할·현재값·레이블 semantics를 제공하고 48dp 터치 영역, 큰 글자·작은 화면에서 조절/닫기/복원을 검사한다.
- [ ] **4.8** 단위 검사와 계측 소스 컴파일을 확인한다. 계측 테스트의 실제 실행은 별도 승인 전까지 보류한다.

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests dev.ene.companion.CharacterLayoutTest --tests dev.ene.companion.CharacterPlacementControllerTest :app:compileDebugAndroidTestKotlin --offline --dependency-verification strict --console=plain
```

- [ ] **4.9** 생성/해제 규칙·UI 경계를 직접 diff 리뷰하고 `feat: add persistent phone character layout controls`로 커밋한다. 계측 미실행을 기록한다.

## 작업 5. PC 움직임 동기화와 배치 불변 회귀 검사

**파일:**

- ENE 검사 수정: `tests/test_companion_character_state.py`, `test_companion_character_bridge.py`, `test_companion_character_runtime.py`.
- ENE_APP 검사 수정: `U/CharacterSessionTest.kt`, `CharacterSettingsStateTest.kt`, `CharacterPlacementControllerTest.kt`, `ConnectionRepositoryTest.kt`.
- 실제 결함이 재현된 경우에만 관련 `src/core/companion/character_state.py`, `character_bridge.py` 또는 공유 실행부의 해당 적용 함수 수정. 공개 설정 키·프로토콜 확장은 하지 않는다.

- [ ] **5.1** 기존 허용 설정 20개에 대해 유효한 비기본 합성 값을 선택한다. PC 확정 저장 → revision 증가 → character_changed → snapshot → native 상태 → JS 설정 함수까지 키별 기대값을 검사한다. bool false, 수치 0이 허용되는 speech_boost, head_pat 기본 표정 우선순위도 포함한다.
- [ ] **5.2** 서로 다른 로컬 배치(예: 1.5/25/75)를 유지한 채 초기 연결, PC 설정 저장, 같은 모델 snapshot, 새 모델 snapshot, 공통 설정 preview/취소를 실행한다. 어느 경우에도 로컬 저장소에 쓰기가 발생하거나 배치가 1/50/50으로 바뀌면 실패한다.
- [ ] **5.3** 휴대폰 배치 조절이 PC 설정 요청을 생성하지 않고, 기존 휴대폰 공통 설정 편집은 기존대로 요청/확정을 수행하는지 확인한다. PC의 미저장 미리보기·마우스 좌표·창 배치를 새로 전송하지 않는다.
- [ ] **5.4** 재접속과 등록 해제에 연결 저장소/모델 캐시 정리가 있어도 배치 저장소는 유지됨을 Repository 가짜 의존성으로 검사한다. 새 서버의 인증/manifest 준비 전 캐릭터를 노출하지 않는 기존 검사도 유지한다.
- [ ] **5.5** 결함을 찾으면 그 실패에 필요한 최소 수정만 한다. 동기화 경로가 이미 정상인 항목은 테스트만 추가하고 중복 구현하지 않는다. JS 변경이 있으면 해당 manifest 해시 갱신과 내보내기를 다시 수행한다.

```powershell
& $py -B -m pytest tests/test_companion_character_state.py tests/test_companion_character_bridge.py tests/test_companion_character_runtime.py tests/test_companion_character_entry.py tests/test_companion_character_export.py -q -p no:cacheprovider --basetemp $testRun
```

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests dev.ene.companion.CharacterSessionTest --tests dev.ene.companion.CharacterSettingsStateTest --tests dev.ene.companion.CharacterPlacementControllerTest --tests dev.ene.companion.ConnectionRepositoryTest --offline --dependency-verification strict --console=plain
```

- [ ] **5.6** 검토 후 저장소별 관련 테스트/최소 수정만 커밋한다. 테스트만 추가했으면 `test: verify PC motion sync preserves phone placement`, 실제 수정이 있으면 원인을 설명하는 영어 fix 메시지를 사용한다.

## 작업 6. 통합 검증, 로컬 APK와 인계

**문서:** ENE `docs/companion-character-layout-validation.md` 신설, ENE_APP `docs/character-runtime.md`, `docs/build-and-install.md`의 조작·검증 안내 갱신. 실제 기기 정보·사용자 모델명·대화 예시는 넣지 않는다.

- [ ] **6.1** 두 저장소의 누적 diff를 함께 검토한다. 저장 순서/초기 복원, 표시와 실제 종료, 새 연결 인증, PC 호스트 불변, 오래된 콜백, 쓰다듬기 취소, 코드/자산 원본 일치를 검토한다. 중요 결함을 수정하고 해당 집중 검사를 다시 실행한다. 작업별로 별도 리뷰 에이전트를 반복 생성하지 않는다.
- [ ] **6.2** ENE 전체 검사와 소스 실행부 검사를 수행한다. 기존 가상환경 Python 3.12 결과와 지원 Python 3.11의 실제 실행 여부를 구분한다. 3.11 검증 환경이 없으면 테스트 미실행으로 명시하고 통과했다고 주장하지 않는다. GitHub CI 실행 확인이 필요해도 별도 push 승인 전에는 보내지 않는다.

```powershell
& $py -B -m pytest -q --tb=short -p no:cacheprovider --basetemp $testRun
& $py -B -m tools.export_companion_character --check --require-core
git diff --check
```

- [ ] **6.3** Android 전체 단위 검사, Lint, 개발 APK·계측 APK 빌드를 실행한다. 실패/오류/제외 수와 Lint 기존·신규 경고를 구분한다.

```powershell
.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest --offline --dependency-verification strict --console=plain
```

- [ ] **6.4** `app/build/test-results/testDebugUnitTest/TEST-*.xml`에서 실제 검사 수·실패·오류·제외를 합산한다. 빌드 출력의 성공 문구만으로 테스트 통과를 판단하지 않는다. APK는 `app/build/outputs/apk/debug/app-debug.apk`이며 크기·SHA-256·기존과 같은 개발 서명을 확인한다.
- [ ] **6.5** APK를 읽기 전용으로 열어 허용 캐릭터 파일 목록과 SHA-256을 import-manifest와 대조한다. 개인 모델, 설정, 인증/토큰, 시험 CA/개인키, 대화, 새 로그가 개발 APK에 없는지 확인한다. Core는 승인된 기존 로컬 파일과 같아야 하며 Git에는 추적되지 않아야 한다.
- [ ] **6.6** 이전 APK·기본 폴더·Core 해시와 Git 상태를 작업 0 기록에 대조한다. 본래 미커밋 변경과 ENE_APP 기존 9개 커밋이 보존되었는지 확인한다. 새 worktree/백업/산출물이 공개 추적 대상으로 들어오지 않았는지 검사한다.
- [ ] **6.7** 검증 문서에 실제 실행 명령·결과, 코드 커밋, 새 APK 위치·해시, 보존 확인, 미실행 계측을 기록한다. Android 안내에 휴대폰 배치와 PC 공통 설정 차이, 자동 저장/실패 재시도, 기본 복원을 설명한다. 영어 메시지 `docs: record phone character layout validation`으로 관련 문서만 커밋한다.
- [ ] **6.8** 최종 보고에는 작업 폴더·로컬 커밋·검사 결과·APK 경로, 적용을 위해 필요한 PC 실행부와 APK 쌍을 안내한다. main 통합과 push는 사용자 확인 전 하지 않는다. 기존 실행 폴더에서 새 기능을 이미 사용할 수 있다고 안내하지 않는다.

### 완료 기준과 남겨야 할 제한사항

| 영역 | 이번에 실행할 검증 | 별도 미확인 |
| --- | --- | --- |
| 배치 계산·자료·저장 순서 | Node VM·Kotlin 단위 검사 | 실제 Android 파일시스템의 강제 종료/IO 실패 |
| 설정/연결 수명 | 가짜 전송·renderer의 순서와 횟수 검사 | 실제 WebView·키보드·GPU의 화면 전환 |
| PC 공통 설정 | 합성 설정의 PC→Android 적용과 배치 불변 | 사용자 모델별 움직임의 육안 일치 |
| APK | strict/offline 빌드·목록·해시·서명 검사 | 실제 기기 설치와 체감 동작 |
| 배포 | 업로드 없음, 기존 로컬 자산 보존 | Live2D 출시 허가 확인 |

계측 테스트는 코드와 APK를 준비해도 단말에서 실행하기 전에는 미검증이다. 사용자에게 실제 단말의 재로딩 증상까지 해결되었다고 단정하지 않는다. 자동 검사 결과와 수동 인수 항목을 분리해 인계한다.

## 계획 검토 상태

- [x] 승인된 설계와 현재 파일 경계 대조.
- [x] 계획 문서의 누락·순서·실행 가능성 검토.
- [ ] 사용자에게 계획 인계.
- [ ] 구현 착수 승인 후 작업 0부터 순차 진행.

계획과 설계를 별도로 읽기 전용 검토했으며 실행을 막는 누락이나 모순은 발견되지 않았다. 문서의 PowerShell 코드 블록 14개는 구문 해석을 통과했고, 배치 계산 예시는 실제 기존 루트 모션 정규화 함수와 함께 Node에서 기대 배율·좌표 및 0 크기/잘못된 값 거절을 확인했다. 이는 문서 예시 검증이며 제품 구현이나 단말 시험 결과가 아니다.
