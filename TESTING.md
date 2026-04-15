# CI + 테스트 가이드 (V1)

## 로컬 실행

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pytest -q --cov=src --cov-report=term-missing --cov-fail-under=4
```

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
  3. `pytest + coverage` 실행 (`최소 4% 미만이면 실패`)

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
