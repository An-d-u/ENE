# 소스 공개와 로컬 빌드

공개 저장소는 자체 소스, 재배포 가능한 라이브러리·라이선스 고지와 빌드 안내를 제공한다. 완성 APK·Windows ZIP·Cubism Core·SDK 압축파일·모델 데이터는 제공하지 않는다. 기존 로컬 파일을 삭제할 필요는 없다.

Core 분리는 출시 허가나 라이선스 면제를 뜻하지 않는다. ENE는 사용자가 모델을 추가할 수 있는 확장성 앱에 해당할 가능성을 전제로 하며, [공식 확장성 앱 정책](https://www.live2d.com/en/sdk/license/expandable/)에 따른 별도 확인이 필요하다.

## 1. Core 직접 준비

1. 사용자가 [Live2D 공식 Cubism SDK for Web 페이지](https://www.live2d.com/en/sdk/download/web/)에서 약관을 확인하고 직접 다운로드한다. 자동 다운로드나 비공식 미러는 사용하지 않는다.
2. SDK는 저장소 밖의 비공개 폴더에 보관한다. 저장소 안이라면 Git에서 제외된 `local-sdk/`를 사용한다.
3. SDK의 `Core/live2dcubismcore.min.js`를 필요한 저장소에 각각 복사한다.
   - PC: `assets/web/lib/live2dcubismcore.min.js`
   - Android: `app/src/main/assets/character/lib/live2dcubismcore.min.js`
4. 파일의 저작권·라이선스 고지를 수정하지 않는다. SDK 전체나 Core를 Git에 추가하지 않는다.

현재 검증된 Core의 SHA-256은 `25ae938cb4fe282ce189b357bcc97e603d1e1f7ec78bf04150d401c23cdc792f`, 공개 API 버전 정수는 `83951616`이다.

공식 SDK의 파일이 이 해시와 다르면 빌드가 중단된다. 해시 검사를 끄거나 비공식 파일로 맞추지 말고, 해당 SDK 버전의 호환성을 검증한 뒤 PC 계약과 Android 가져오기 manifest를 함께 갱신해야 한다. 현재 공식 다운로드에서 검증된 파일을 구할 수 있는지까지 자동으로 보장하지는 않는다.

```powershell
python scripts/setup_web_libs.py --check-core
python tools/export_companion_character.py --check --require-core
```

`setup_web_libs.py`의 일반 실행은 공개 배포가 가능한 두 표시 라이브러리만 준비하고 Core는 검사만 한다. 두 라이브러리는 저장소에도 포함되어 있으므로 Core 설치를 위해 이 다운로드 단계를 반복할 필요는 없다.

## 2. 모델 직접 준비

사용 권한이 있는 모델을 비공개 로컬 폴더에 준비하고 설정에서 `.model3.json`을 선택한다. Hiyori 데이터는 제공하지 않는다. 필요한 경우 [공식 Hiyori 페이지](https://www.live2d.com/en/learn/sample/momose-hiyori/)와 [모델 이용 조건](https://www.live2d.com/en/learn/sample/model-terms/)을 직접 확인한다.

기존 설정과의 호환성을 위해 코드에 Hiyori 기본 경로 문자열이 남아 있을 수 있다. 이는 모델을 포함한다는 의미가 아니다. 기존 로컬 모델·설정을 바꿀 필요는 없다. Windows 빌드에도 모델은 자동 포함하지 않는다.

## 3. PC 검사와 로컬 빌드

일반 설치·의존성·테스트 환경은 README와 TESTING.md를 따른다. Core 없이도 소스 내보내기 검사와 단위 테스트를 실행할 수 있다. 실제 Core 파일을 확인하는 통합 시험만 파일이 없으면 건너뛴다.

```powershell
python tools/export_companion_character.py --check
python -m pytest tests/test_local_core_setup.py tests/test_companion_character_export.py tests/test_build_windows_release.py -q
python scripts/build_windows_release.py --version local
```

Windows 빌드는 Core 확인 후에만 패키징한다. `dist/`, `build/`, `release/`의 결과는 로컬 전용이며 공개하지 않는다. 기존 실행 환경에서는 빌드를 반복하지 말고 별도 복제본을 권장한다.

## 4. Android 소스 동기화와 빌드

```powershell
python tools/export_companion_character.py --android-root C:/work/ENE_APP
```

계약은 Core를 포함한 20개 항목을 기록하지만 내보내기는 Core를 제외한 소스·라이브러리·고지 19개와 manifest만 복사한다. Android에 직접 설치한 정상 Core는 보존하며 덮어쓰지 않는다. 잘못된 Core가 이미 있으면 오류로 중단한다. 일반 모델·설정·대화는 내보내지 않는다.

ENE_APP은 독립 checkout으로 빌드할 수 있다. 해당 저장소의 `docs/build-and-install.md`를 따른다. JVM 단위 검사는 Core 없이 가능하지만 APK/AAB 빌드는 Core 해시 검사를 통과해야 한다.

## 공개 이력 관리

정리 전 브랜치·태그·번들은 복구용 비공개 보관물이다. 정리된 저장소에 다시 fetch/merge하지 않는다. 필요한 코드는 diff를 검토해 새 커밋으로 옮긴다. `push --all`, `push --mirror`, 포괄적인 태그 push는 사용하지 않는다.

과거 태그에는 당시 자동 릴리스 설정이 남으므로, 원격 태그 갱신 전에는 별도 승인 단계에서 자동 릴리스를 먼저 중지해야 한다. 현재 main의 설정 변경만으로 과거 태그의 실행을 막을 수 있다고 가정하지 않는다.
