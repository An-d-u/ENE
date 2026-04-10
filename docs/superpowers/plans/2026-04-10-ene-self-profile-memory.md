# ENE 자기 정보 장기기억 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대화 요약에서 에네 자신의 장기 정보를 추출·저장하고, 응답 컨텍스트와 별도 관리 창에서 활용할 수 있게 만든다.

**Architecture:** 기존 사용자 프로필 흐름을 최대한 재사용하되, `ene_profile.json` 전용 저장 계층을 추가해 자동 추출 정보와 수동 보호 정보를 분리한다. 요약 파서는 `[ENE_INFO]`를 추가로 반환하고, 브리지는 이를 새 프로필 저장소에 연결하며, UI는 별도 CRUD 다이얼로그로 제공한다.

**Tech Stack:** Python, PyQt6, pytest, JSON 저장소

---

### Task 1: 에네 프로필 저장소의 정책을 테스트로 고정

**Files:**
- Create: `tests/test_ene_profile.py`
- Reference: `src/ai/user_profile.py`
- Reference: `src/core/app_paths.py`

- [ ] **Step 1: 새 저장소 테스트 파일에 기본 저장/로드 테스트를 작성**

```python
def test_ene_profile_roundtrip_preserves_core_and_fact_fields(tmp_path):
    profile = EneProfile(profile_file=tmp_path / "ene_profile.json")
    profile.core_profile["identity"] = ["에네는 차분한 동반자다."]
    profile.add_fact(
        content="[speaking_style] 짧고 또렷한 문장을 선호한다.",
        source="manual",
        origin="manual",
        auto_update=False,
    )

    reloaded = EneProfile(profile_file=tmp_path / "ene_profile.json")
    assert reloaded.core_profile["identity"] == ["에네는 차분한 동반자다."]
    assert reloaded.facts[0].category == "speaking_style"
    assert reloaded.facts[0].origin == "manual"
```

- [ ] **Step 2: 교차 프로필 중복 차단 테스트를 추가**

```python
def test_add_fact_skips_content_that_duplicates_user_profile(tmp_path):
    user_profile = UserProfile(profile_file=tmp_path / "user_profile.json")
    user_profile.add_fact("[preference] 다크 판타지를 좋아한다.", source="chat")

    profile = EneProfile(profile_file=tmp_path / "ene_profile.json", user_profile=user_profile)
    profile.add_fact("[preference] 다크 판타지를 좋아한다.", source="chat")

    assert profile.facts == []
```

- [ ] **Step 3: 수동 보호와 자동 갱신 허용 규칙 테스트를 추가**

```python
def test_auto_fact_cannot_override_manual_locked_fact(tmp_path):
    profile = EneProfile(profile_file=tmp_path / "ene_profile.json")
    profile.add_fact("[relationship_tone] 사용자를 다정하게 챙긴다.", origin="manual", auto_update=False)
    profile.add_fact("[relationship_tone] 사용자를 장난스럽게 몰아붙인다.", origin="auto", auto_update=True)

    assert len(profile.facts) == 1
    assert profile.facts[0].content == "사용자를 다정하게 챙긴다."
```

- [ ] **Step 4: 테스트를 실행해 실패를 확인**

Run: `pytest tests/test_ene_profile.py -v`  
Expected: `ModuleNotFoundError` 또는 `NameError`로 `EneProfile` 관련 실패

- [ ] **Step 5: 실패 원인을 기록하고 다음 구현 작업으로 넘어간다**


### Task 2: `ene_profile.json` 저장소와 정책 구현

**Files:**
- Create: `src/ai/ene_profile.py`
- Modify: `src/core/app.py`
- Modify: `src/core/bridge.py`
- Test: `tests/test_ene_profile.py`

- [ ] **Step 1: `ProfileFact`와 유사한 에네 전용 fact dataclass를 정의**

```python
@dataclass
class EneProfileFact:
    content: str
    category: str
    timestamp: str
    source: str = ""
    origin: str = "auto"
    auto_update: bool = True
    confidence: float | None = None
```

- [ ] **Step 2: `EneProfile` 클래스에 BOM 기반 저장/로드를 구현**

```python
data = {
    "core_profile": self.core_profile,
    "facts": [fact.to_dict() for fact in self.facts],
    "last_updated": datetime.now().isoformat(),
}
save_json_data(self.profile_file, data, encoding="utf-8-sig", indent=2, ensure_ascii=False, trailing_newline=True)
```

- [ ] **Step 3: `add_fact()`에 카테고리 검증, 임시 정보 제거, 중복/유사도 병합을 구현**
- [ ] **Step 4: `user_profile` 교차 중복 검사와 수동 보호 우선순위 검사를 구현**
- [ ] **Step 5: `core_profile` 접근 helper와 컨텍스트용 정렬 helper를 구현**
- [ ] **Step 6: `src/core/app.py`에 `_init_ene_profile()`을 추가하고 앱 시작 시 초기화**
- [ ] **Step 7: `src/core/bridge.py`가 `ene_profile` 참조를 보관할 수 있게 setter 경로를 확장**
- [ ] **Step 8: 테스트를 다시 실행해 통과를 확인**

Run: `pytest tests/test_ene_profile.py -v`  
Expected: 모든 새 테스트 PASS

- [ ] **Step 9: 변경 파일을 커밋**

```bash
git add src/ai/ene_profile.py src/core/app.py src/core/bridge.py tests/test_ene_profile.py
git commit -m "feat: add ene profile storage"
```


### Task 3: 요약 파서와 LLM 인터페이스를 `[ENE_INFO]`까지 확장

**Files:**
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_clients.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `tests/test_summary_parsing.py`

- [ ] **Step 1: 요약 파싱 테스트에 `[ENE_INFO]` 기대값을 먼저 추가**

```python
summary, user_facts, ene_facts, memory_meta = client._parse_summary_response(response_text)
assert "[speaking_style] 짧고 단정한 말투를 유지한다." in ene_facts
```

- [ ] **Step 2: `none` 케이스에서도 `ene_facts == []`를 검증하는 테스트를 추가**
- [ ] **Step 3: 테스트를 실행해 반환 시그니처 불일치로 실패하는지 확인**

Run: `pytest tests/test_summary_parsing.py -v`  
Expected: unpack 에러 또는 assertion 실패

- [ ] **Step 4: Gemini 요약 프롬프트에 `[ENE_INFO]` 허용/금지 규칙을 추가**
- [ ] **Step 5: `_parse_summary_response()`가 `summary, user_facts, ene_facts, memory_meta`를 반환하도록 수정**
- [ ] **Step 6: HTTP 공통 프롬프트/파서를 같은 형식으로 동기화**
- [ ] **Step 7: `LLMClientProtocol`과 각 `summarize_conversation()` 시그니처를 4항 반환으로 갱신**
- [ ] **Step 8: 테스트를 다시 실행해 통과를 확인**

Run: `pytest tests/test_summary_parsing.py -v`  
Expected: 모든 테스트 PASS

- [ ] **Step 9: 변경 파일을 커밋**

```bash
git add src/ai/llm_client.py src/ai/http_llm_clients.py src/ai/llm_provider.py tests/test_summary_parsing.py
git commit -m "feat: parse ene self profile from summaries"
```


### Task 4: 자동 요약 저장과 응답 컨텍스트에 에네 프로필을 연결

**Files:**
- Modify: `src/core/bridge.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/core/app.py`
- Modify: `tests/test_bridge_context_compaction.py`

- [ ] **Step 1: 브리지 테스트에 `ene_facts` 저장 기대값과 더미 프로필을 추가**

```python
class _DummyEneProfile:
    def __init__(self):
        self.calls = []

    def add_fact(self, **kwargs):
        self.calls.append(kwargs)
```

- [ ] **Step 2: `_DummyLLMClient.summarize_conversation()`이 4항 반환을 하도록 바꾸고 실패를 확인**

Run: `pytest tests/test_bridge_context_compaction.py -v`  
Expected: 브리지 unpack 또는 저장 assertion 실패

- [ ] **Step 3: `WebBridge._auto_summarize()`가 `ene_facts`를 새 프로필에 저장하도록 구현**
- [ ] **Step 4: `set_memory_manager()` 또는 별도 setter가 `ene_profile`까지 연결하도록 확장**
- [ ] **Step 5: `_build_memory_context()`에 `[에네 기본 설정]`, `[에네에 대한 누적 정보]` 블록을 추가**
- [ ] **Step 6: 자동 fact 정렬을 `보호 수준 -> 최신성` 기준으로 맞춘다**
- [ ] **Step 7: 대상 테스트를 다시 실행해 통과를 확인**

Run: `pytest tests/test_bridge_context_compaction.py -v`  
Expected: 모든 테스트 PASS

- [ ] **Step 8: 변경 파일을 커밋**

```bash
git add src/core/bridge.py src/ai/llm_client.py src/core/app.py tests/test_bridge_context_compaction.py
git commit -m "feat: wire ene profile into summary and context"
```


### Task 5: 별도 ENE 프로필 관리 창 CRUD와 진입점 추가

**Files:**
- Create: `src/ui/ene_profile_dialog.py`
- Modify: `src/ui/memory_dialog.py`
- Modify: `src/locales/ko.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ja.json`
- Modify: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: UI smoke 테스트에 새 다이얼로그 문자열과 기본 CRUD 상태를 추가**
- [ ] **Step 2: 메모리 다이얼로그에서 에네 프로필 진입점 문자열과 경고 문자열 기대값을 추가**
- [ ] **Step 3: 테스트를 실행해 번역 키/다이얼로그 부재로 실패하는지 확인**

Run: `pytest tests/test_ui_i18n_smoke.py -k "profile or memory_dialog" -v`  
Expected: locale key 누락 또는 import 실패

- [ ] **Step 4: `src/ui/profile_dialog.py` 패턴을 참고해 `src/ui/ene_profile_dialog.py` CRUD 다이얼로그를 구현**
- [ ] **Step 5: core profile 편집, fact 목록 편집, `auto_update` 토글, origin 표시를 추가**
- [ ] **Step 6: `memory_dialog.py`에 별도 ENE 프로필 열기 액션을 추가**
- [ ] **Step 7: 각 locale 파일에 새 버튼/헤더/경고/라벨 문자열을 추가**
- [ ] **Step 8: UI smoke 테스트를 다시 실행해 통과를 확인**

Run: `pytest tests/test_ui_i18n_smoke.py -k "profile or memory_dialog" -v`  
Expected: 관련 smoke 테스트 PASS

- [ ] **Step 9: 변경 파일을 커밋**

```bash
git add src/ui/ene_profile_dialog.py src/ui/memory_dialog.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_ui_i18n_smoke.py
git commit -m "feat: add ene profile management dialog"
```


### Task 6: 전체 검증과 정리

**Files:**
- Verify: `tests/test_ene_profile.py`
- Verify: `tests/test_summary_parsing.py`
- Verify: `tests/test_bridge_context_compaction.py`
- Verify: `tests/test_ui_i18n_smoke.py`

- [ ] **Step 1: 새 저장소/요약/브리지 테스트 묶음을 실행**

Run: `pytest tests/test_ene_profile.py tests/test_summary_parsing.py tests/test_bridge_context_compaction.py -v`
Expected: PASS

- [ ] **Step 2: UI smoke 관련 테스트를 실행**

Run: `pytest tests/test_ui_i18n_smoke.py -k "profile or memory_dialog" -v`
Expected: PASS

- [ ] **Step 3: 필요하면 전체 회귀에 가까운 관련 테스트를 추가로 실행**

Run: `pytest tests/test_memory_manager.py tests/test_ui_i18n_smoke.py -k "profile or memory_dialog" -v`
Expected: PASS

- [ ] **Step 4: 문서/로그 메시지/주석을 한국어 기준으로 점검**
- [ ] **Step 5: 최종 변경 파일을 커밋**

```bash
git add src/ai/ene_profile.py src/ai/llm_client.py src/ai/http_llm_clients.py src/ai/llm_provider.py src/core/app.py src/core/bridge.py src/ui/ene_profile_dialog.py src/ui/memory_dialog.py src/locales/ko.json src/locales/en.json src/locales/ja.json tests/test_ene_profile.py tests/test_summary_parsing.py tests/test_bridge_context_compaction.py tests/test_ui_i18n_smoke.py
git commit -m "feat: add ene self profile memory flow"
```

