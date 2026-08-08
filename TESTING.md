# CI + 테스트 가이드 (V1)

## 로컬 실행

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m coverage run --source=src --omit="src/core/app.py,src/core/audio_player.py,src/core/global_ptt.py,src/core/overlay_window.py,src/core/bridge_workers.py,src/core/bridge_mixins/attachments.py,src/core/bridge_mixins/away.py,src/core/bridge_mixins/memory_summary.py,src/core/bridge_mixins/mood.py,src/core/bridge_mixins/obsidian.py,src/ui/drag_bar.py,src/ui/settings_dialog_hotkeys.py,src/ui/settings_dialog_profile.py,src/ui/settings_dialog_prompt.py,src/ui/settings_dialog_theme.py,src/ui/settings_dialog_tts.py,src/ui/settings_dialog_widgets.py,src/ai/http_llm_clients.py,src/ai/http_llm_common.py,src/ai/http_llm_openai.py,src/ai/http_llm_custom_providers.py,src/ai/http_llm_anthropic.py,src/ai/http_llm_ollama.py,src/ai/llm_client.py" -m pytest -q
python -m coverage report --show-missing --skip-empty --fail-under=80
```

이 커버리지 게이트는 GUI, 오디오 장치, 외부 HTTP 런타임처럼 CI에서 안정적으로 재현하기 어려운 표면을 제외한 선별 대상 기준이다.

## 정적 검사

```powershell
python -m ruff check . --select E9,F63,F7,F82
```

## 테스트 범위

- `tests/test_embedding.py`
  - 코사인 유사도 계산 검증
- `tests/test_memory_manager.py`
  - 메모리 로드/저장/정렬/필터링/유사도 검색 검증
- `tests/test_memory_types.py`
  - 메모리 데이터 구조 생성/직렬화 검증
- `tests/test_summary_parsing.py`
  - 대화 요약 파싱 로직 검증
- `tests/test_audio_analyzer.py`
  - WAV 기반 립싱크 분석 결과 검증
- `tests/test_viseme_stream_analyzer.py`
  - 실시간 viseme 프레임 인터페이스와 폴백 가능한 분석기 계약 검증
- `tests/test_tts_sync_controller.py`
  - `80~120ms` 적응형 동기화 버퍼 시작 규칙과 RMS 폴백 규칙 검증
- `tests/test_model_lip_sync_profile.py`
  - 모델 입 파라미터 자동 감지, override merge, 잘못된 프로파일 폴백 검증
- `tests/test_bridge_tts_streaming.py`
  - 스트리밍 TTS에서 메시지 표시, 오디오 시작, 립싱크 시작 시점 동기화와 `mouth_pose` 생성 검증
- `tests/test_chat_ui_assets.py`
  - web 자산의 `mouth_pose` 훅과 다중 입 파라미터 적용 경로 존재 검증
- `tests/test_settings.py`
  - 설정 로드/저장/복구 로직 검증

## `viseme 립싱크` 회귀 테스트

이 기능을 검증할 때는 아래 회귀 묶음을 함께 돌린다.

```powershell
python -m pytest tests/test_settings.py tests/test_ui_i18n_smoke.py tests/test_bridge_tts_streaming.py tests/test_chat_ui_assets.py tests/test_viseme_stream_analyzer.py tests/test_tts_sync_controller.py -q
```

이 묶음은 다음을 함께 잠근다.

- `viseme 립싱크` 설정의 기본값, 저장/로드, 레거시 설정 업그레이드
- 설정 창 체크박스와 로케일 바인딩
- 브리지의 런타임 게이트와 `mouth_pose` 생성
- 웹 자산의 expression mouth bias 합성 및 RMS 폴백
- viseme 스트림 분석기 계약
- 적응형 `80~120ms` TTS 동기화 버퍼 규칙

## CI 동작

- 파일: `.github/workflows/ci.yml`
- 트리거: `push`, `pull_request`
- 매트릭스:
  - OS: `ubuntu-latest`, `windows-latest`
  - Python: `3.11`
- 실행 항목:
  1. 의존성 설치
  2. `ruff` 검사
  3. `pytest + coverage` 실행 (`선별 대상 최소 80% 미만이면 실패`)

## 생활 기록 회귀 테스트

생활 기록의 저장·시간·공급자·UI·수명주기 변경을 검증할 때는 아래 집중 묶음을 실행한다. GUI 자산 검증을 위해 headless Qt 플랫폼을 사용한다.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_local_time.py tests/test_life_session_tracker.py tests/test_life_record_types.py tests/test_life_record_manager.py tests/test_life_record_prompt.py tests/test_life_record_llm_contract.py tests/test_life_record_http_native_providers.py tests/test_life_record_http_format_parity.py tests/test_life_record_chat_context.py tests/test_life_record_request_gate.py tests/test_life_record_bridge_flow.py tests/test_life_record_regeneration.py tests/test_life_record_settings_ui.py tests/test_life_record_panel_assets.py tests/test_life_record_ui_states.py tests/test_life_record_app_lifecycle.py tests/test_life_record_end_to_end.py tests/test_build_windows_release.py -q
```

이 묶음은 다음 계약을 함께 잠근다.

- `life_records.json`과 `life_session_state.json`의 스키마, 원자 저장, 잠금, 손상 파일 fail-closed 처리
- 일반 환경의 전달된 데이터 파일과 Microsoft Store Python의 visible Roaming 파일을 권위 저장소로 사용하는 규칙
- Microsoft Store Python 런타임 캐시가 권위 파일을 덮지 않고, 권위 파일로부터만 복구되는 규칙
- IANA 시간대, UTC instant 비교, DST 23시간·25시간 날짜 경계, 자정 양쪽 날짜 조회
- 기본 비활성화, 60분 임계값, 빈 생활 환경과 생성·저장 실패에서도 일반 채팅을 계속하는 동작
- 첫 일반 채팅 gate, 명령 선행, 첨부 대화, 리롤 비재생성, 최신 기록만 재생성하는 동작
- 네이티브 구조화 출력과 엄격 JSON 형식의 동일 계약, 명시적 capability 미지원일 때만 수행하는 최대 한 번의 폴백
- `COMPLETE` 내용 검증 실패에만 수행하는 최대 한 번의 내용 재시도와 refusal·incomplete·max-tokens·전송 오류 비재시도
- capability 폴백, 내용 재시도, 일반 답변의 제공된 토큰 사용량 합산과 미제공 값의 `None` 유지
- 날짜 전환 stale 응답 차단, 읽기 전용 capability, 생성·재생성·일반 답변·종료의 상호 배제

### 저장소와 손상 테스트 원칙

- 테스트마다 임시 사용자 데이터 루트를 사용하고 실제 `%AppData%/ENE`를 읽거나 쓰지 않는다.
- 권위 파일을 손상시키는 테스트는 원본 bytes가 보존되고 추가·교체 쓰기가 거부되는지 확인한다.
- Store cache 테스트는 stale cache가 유효해도 missing 또는 손상된 visible 권위 파일 대신 반환되지 않는지 확인한다.
- 예시는 2099년의 가상 장소·활동만 사용하고 실제 사용자 원문을 fixture나 assertion에 복사하지 않는다.

### 로그와 개인정보 검사

생활 기록 테스트는 생활 환경, 프로필, 상태 설명, 활동 문장, 첫 채팅, 모델 응답과 공급자 오류 상세가 로그·예외 표현에 노출되지 않는지 확인해야 한다. 로그 assertion은 안전한 오류 코드, 길이, 항목 수, 상태와 토큰 메타데이터만 허용한다.

commit 전에는 변경된 파일의 UTF-8(BOM 없음), diff whitespace, 비밀값 패턴과 개인정보 후보를 검사한다. 다음 런타임 파일은 tracked tree와 staged diff에 없어야 한다.

```text
life_records.json
life_session_state.json
life_session_state.lock
prompts/life_world.md
```

다른 기존 사용자 런타임 파일과 `.env*`, 사용자 데이터 루트의 `prompts/**`에도 같은 비커밋 정책을 적용한다.

### 릴리스 smoke

릴리스 전에는 빌드 mapping에 `prompts/defaults`, `assets/web`, `tzdata`가 포함되고 사용자 런타임 파일은 포함되지 않는지 확인한다. Microsoft Store Python에서는 실제 Roaming 루트 아래 검증된 `store_smoke/<GUID>` 경로만 사용해 다음을 수동 점검한다.

1. manager 저장 결과가 visible Roaming 권위 파일의 유효한 UTF-8 JSON 완성본인지 확인한다.
2. 런타임 캐시를 stale한 유효 JSON으로 바꾼 뒤 새 프로세스에서 권위 최신값이 반환되고 캐시가 복구되는지 확인한다.
3. visible 권위 파일을 손상시켰을 때 캐시로 폴백하지 않고 읽기 오류가 되는지 확인한다.
4. 원문과 응답을 출력하지 않고, 마지막에 경계 검증을 통과한 `store_smoke/<GUID>` 두 디렉터리만 정리한다.

태그나 공개 archive를 만들기 전에는 변경분만이 아니라 전체 tracked tree, 전체 Git history, 태그 대상 commit, archive 파일 목록과 압축 내부를 검사한다. 민감 데이터가 발견되면 공개 작업을 중단하고 history rewrite 필요 여부를 먼저 판단한다. 세부 운영 기준은 [docs/life_records.md](docs/life_records.md)를 참고한다.

## 기존 실행 파일 호환

- `python test_memory.py`
- `python test_summarization.py`

위 파일들은 기존 실행 습관 유지를 위한 래퍼이며, 내부적으로 pytest를 호출한다.

## 수동 확인 권장 항목

- `gpt_sovits_http` 스트리밍 ON에서 메시지와 오디오가 동시에 시작되는지 확인
- 스트리밍 ON에서 viseme 준비가 늦을 때 `120ms` 안에서 RMS 폴백으로 자연스럽게 시작되는지 확인
- `gpt_sovits_http` 스트리밍 OFF에서도 메시지 표시 직후 오디오가 바로 시작되는지 확인
- `openai_audio_speech`, `openai_compatible_audio_speech`, `elevenlabs`, `genie_tts_http` 전환 후에도 회귀가 없는지 확인
- `browser_speech`는 기존 브라우저 재생 경로가 유지되는지만 확인
- `vbridger`형 모델에서는 `A/I/U/E/O`에 따라 `Form/Funnel/Pucker`가 자연스럽게 섞이는지 확인
- 단순 모델에서는 별도 shape 파라미터 없이도 `open_only`로 깨지지 않는지 확인
- 모델 폴더에 `lip_sync_profile.json`이 없을 때 자동 감지가 정상 동작하는지 확인
