# 동반 앱 음성·캐릭터 후속 검증

검증일: 2026-09-23. 작업 브랜치: 양쪽 저장소의 `codex/companion-media-followup`.
ENE 기준 커밋은 `40aac44`, ENE_APP 기준 커밋은 `81ee793`이다. 기존 main의 변경은 보존했다.

## 변경과 원인 구분

- 스트리밍 WAV의 HTTP 조각이 PCM 프레임 중간에서 나뉘면 정상 음성도 `invalid_pcm`으로 거절되는 경로를 합성 데이터로 재현했다. 해석기가 프레임 크기 미만의 잔여 바이트만 이어 붙이도록 수정했다. 불완전 헤더·마지막 프레임은 전송 종료 시 거절한다.
- 실제 휴대폰에서 발생한 음성 중단도 같은 원인인지는 미확인이다. 스트리밍 설정, GPT-SoVITS 요청 매개변수, 버퍼/시간 제한, 수동 휴대폰의 PC 대체 금지 정책은 변경하지 않았다.
- 캐릭터의 일반 window 메시지 전달을 고정 출처·최상위 문서 검사 후 확보한 Android 응답 통로로 바꿨다. 내부 문서 준비 알림, 네이티브 세대 전달, 엔진 초기화, 준비 응답, 스냅샷 순서로 처리한다. 잘못된 출처·세대, 중복 초기화, 종료 후 콜백을 차단한다.
- 다운로드·초기화 응답 제한·엔진 초기화·자산 읽기·렌더링 실패를 고정 문구로 구분한다. 원시 예외·URL·사용자 경로·모델 식별자는 표시하지 않는다. CSP와 외부 네트워크 차단은 유지했다.

조각 크기는 요청한 크기보다 작을 수 있다. [aiohttp 공식 설명](https://docs.aiohttp.org/en/stable/streams.html#asynchronous-iteration-support)
캐릭터 전용 응답 통로는 출처를 제한한 메시지 리스너와 응답 프록시를 사용한다. [Android 공식 설명](https://developer.android.com/develop/ui/views/layout/webapps/native-api-access-jsbridge)

## 실행 결과

| 검사 | 결과 |
| --- | --- |
| 수정 전 집중 검사 | ENE 85개 통과, Android 캐릭터 집중 검사 통과 |
| 음성 회귀 실패 재현 | 조각 경계·종료 검증에서 16개 실패 확인 후 수정 |
| 음성 집중 검사 | 101개 통과; 실제 worker와 출력 조정기로 전체 바이트·완료·PC 무출력 확인 |
| ENE 전체 검사 | Python 3.12.10, 4,129개 통과·기존 제외 1개, 110.17초 |
| 최종 집중 재검사 | 시험 fixture 정리 뒤 음성 큐·캐릭터 문서·내보내기 24개 통과 |
| 정적 검사 | 변경 Python 파일 Ruff, 양쪽 `git diff --check` 통과 |
| Android 전체 단위 검사 | 266개 통과, 실패·오류·제외 0 |
| Android 빌드 | offline·strict 의존성 검증, Core 검사, 개발/계측 APK 빌드 통과 |
| Android Lint | 오류 0, 기존 경고 4개 |
| APK 내용 검사 | 전체 558항목, 캐릭터 22항목, manifest 자산 21개 해시 및 정확한 경로 집합 일치 |
| 개인정보 후보 검사 | 변경 추가 줄의 키·개인정보 후보 0, APK 모델·개인 설정·시험 CA·개인키 경로 후보 0 |
| 보존 검사 | Core 4개 복사본의 기존 해시 유지, 이전 APK 백업 해시 일치, 기존과 같은 디버그 서명 |

보안 테스트는 새 준비 절차를 반영했고 외부 출처·하위 프레임·종료 이후 입력의 거절 검사는 유지했다.
수정 diff를 별도로 읽기 전용 리뷰했으며 새로 도입된 확정적인 중요 결함은 발견되지 않았다.
격리 검증 동안 원본 저장소의 실행 코드·설정은 바꾸지 않았으며 기존 메모리 기능 변경도 보존했다.

## 산출물과 보존 위치

기존 ENE 폴더 기준:

- PC 수정본: `.worktrees/companion-media-repair/ENE`.
- Android 수정본: `.worktrees/companion-media-repair/ENE_APP`.
- 새 APK: `.worktrees/companion-media-repair/ENE_APP/app/build/outputs/apk/debug/app-debug.apk`.
- 이전 개발 APK: `backups/companion-media-20260923-followup/previous-app-debug.apk`.

새 APK는 37,701,047바이트이며 SHA-256은 `6e4430447f8cf090fb8fc93c564d97fe4cb32fa935845c0872f3ad0546cbbf4a`이다.
이전 개발 APK 백업 해시는 `939cc834a7c6bb17ae93b1bc0e7259af384171936c701f0eb0f2354468c0901c`이다.
Core 해시는 `25ae938cb4fe282ce189b357bcc97e603d1e1f7ec78bf04150d401c23cdc792f`로 유지됐다.
Core·모델·APK·백업은 Git 제외 상태이며 새로 다운로드하지 않았다.

## 적용과 미확인 사항

사용자 승인으로 ENE `7dbf2c7`, ENE_APP `30d8e49`를 기존 최종 폴더의 로컬 main에 fast-forward 적용했다.
원격 pull·push·공개 업로드·릴리스 생성은 하지 않았다. 격리 폴더와 로컬 브랜치는 APK·로컬 자산 보존을 위해 남겼다.
기존 ENE 폴더에서 PC 앱을 재시작하고 위의 새 APK로 업데이트하면 양쪽 수정본을 사용할 수 있다.
기본 ENE_APP 폴더의 이전 APK는 덮어쓰지 않았으므로 반드시 위 격리 폴더의 새 APK를 사용한다.
기존 등록·설정·사용자 데이터는 삭제하지 않는다.

통합 후 main과 같은 커밋의 격리 폴더에서 전체 검사를 재실행했다. ENE는 4,129개 통과·기존 제외 1개(101.45초),
Android는 캐시 재사용 없이 266개 통과·실패/오류/제외 0이다. 기본 ENE 폴더의 캐릭터 실행부·Core 검사도 통과했다.
새 APK·이전 APK 백업·기본 폴더의 원본 APK 해시가 유지됐음을 다시 확인했다. 이 기록의 문서 전용 변경은 APK 실행 코드를 바꾸지 않는다.

실제 WebView 내부 문서의 통신 왕복 계측 시험을 추가했지만, 계측 APK는 빌드만 했으며 단말에서는 실행하지 않았다.
실제 캐릭터 표시, 스트리밍 음성 전체 재생, 기기별 입력·포커스·수명 동작과 Live2D 출시 허가 확인은 미확인 항목이다.
이번 회귀 검사 통과를 해당 단말 증상의 최종 해결이나 공개 배포 허가로 해석하지 않는다.
