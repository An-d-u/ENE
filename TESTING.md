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
- `tests/test_settings.py`
  - 설정 로드/저장/복구 로직 검증

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
