# Provider-Neutral Structured Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ENE의 일반 대화 응답을 제공자 중립 `ResponseEnvelopeV1`로 검증해 생각·TTS·감정·일정·약속·목표·선제 대화·제스처 전달을 안정화하고, 네이티브 구조화를 지원하지 않는 모델은 기존 태그 방식으로 계속 동작하게 한다.

**Architecture:** 고정된 envelope 스키마와 로컬 도메인 검증기를 중심에 두고, 제공자별 어댑터는 요청 형식과 응답 carrier/종료 상태만 변환한다. 공통 파이프라인이 명시적 미지원 하향, 전체 재생성 1회, thought/TTS 제한 복구 1회를 제어하며, 최종 결과는 기존 10개 튜플과 11개 Qt signal 형식을 그대로 유지한다. 일반 대화가 아닌 요약·판정·Markdown·일기·노트 요청은 `request_kind`로 분리한다.

**Tech Stack:** Python 3.12, PyQt6, pytest, requests, Google Gen AI SDK, 표준 라이브러리 `dataclasses`/`enum`/`json`/`hashlib`/`hmac`

**Complexity:** 야심참. 공통 계약은 하나지만 OpenAI Responses, OpenAI-compatible, Anthropic, Ollama, Gemini의 요청·종료 상태·history 동작이 각각 달라 단계별 회귀 검증이 필요하다.

**Design Reference:** `docs/superpowers/specs/2026-07-18-provider-neutral-structured-response-design.md`

---

## 구현 전 공통 원칙

- 모든 테스트 fixture와 문서 예시는 실제 대화와 무관한 새 중립 합성 데이터만 사용한다.
- `memory.json`, `config.json`, `api_keys.json`, `.env*` 등 런타임·개인정보 파일은 열거나 staging하지 않는다.
- 외부 `jsonschema` 의존성을 추가하지 않는다. 송신 스키마는 고정 dict로 만들고 수신은 허용 목록·타입·도메인 규칙으로 직접 검증한다.
- `thought`는 공개 가능한 캐릭터의 짧은 내면 반응이며 모델의 raw chain-of-thought가 아니다.
- 전체 응답 재생성과 제한 복구가 끝나기 전에는 일정·약속·목표·분석·선제 대화 부수효과를 적용하지 않는다.
- 각 Task는 RED → 최소 구현 → GREEN → 관련 회귀 → 작은 커밋 순서를 지킨다.

### 모든 Commit 단계의 필수 개인정보 gate

각 Task의 `git add`와 `git commit` 사이에 아래 검사를 반드시 실행한다. 검색 결과가 0건이어야 한다는 뜻이 아니라, 모든 후보를 직접 확인해 실제 개인정보·대화 원문·비밀값이 아님을 설명할 수 있어야 한다.

```powershell
git diff --cached --check
$stagedFiles = git diff --cached --name-only
$runtimeMatches = $stagedFiles | Select-String -Pattern '(^|[\\/])(memory\.json|user_profile\.json|ene_profile\.json|config\.json|api_keys\.json|obs_config\.json|mood_state\.json|calendar\.json|diary\.json|api_key\.txt|\.env[^\\/]*)$'
if ($runtimeMatches) { throw "런타임 파일이 staging되었습니다: $runtimeMatches" }
git diff --cached -- | rg -n "(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|이름|생일|건강|병원|일정|취업|자소서|프로필|name|birthday|health|hospital|schedule|employment|resume|profile)"
git diff --cached --
```

Expected: runtime/secret pattern 없음. 개인정보 후보 검색 결과는 합성 fixture·필드명·정책 문구만 있으며, staged diff를 눈으로 확인했을 때 실제 사용자 데이터나 실제 대화 문장이 없다.

### Task 1: 공통 요청·응답 프로토콜과 안전한 기본 설정을 고정

**Files:**
- Create: `src/ai/response_protocol.py`
- Modify: `src/core/settings.py`
- Create: `tests/test_response_protocol.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 요청 종류, 응답 모드, 전달 메타데이터의 실패 테스트 작성**

```python
from src.ai.response_protocol import (
    LLMRequestKind,
    ProviderResponse,
    ProviderRefusalError,
    ResponseDeliveryMetadata,
    ResponseMode,
    ResponseStatus,
    StructuredOutputUnsupported,
)


def test_response_protocol_uses_content_free_delivery_metadata_defaults():
    metadata = ResponseDeliveryMetadata.empty()

    assert metadata.response_mode == ""
    assert metadata.schema_version == ""
    assert metadata.promises_authoritative is False
    assert metadata.repair_performed is False
    assert not hasattr(metadata, "reply")
    assert not hasattr(metadata, "prompt")


def test_request_kinds_and_response_modes_are_explicit():
    assert {item.value for item in LLMRequestKind} == {
        "final_reply", "summary", "decision", "markdown", "plain_text"
    }
    assert {item.value for item in ResponseMode} == {
        "json_schema", "strict_tool", "json_object", "legacy_tags"
    }
    assert {item.value for item in ResponseStatus} == {
        "complete", "incomplete", "refusal", "empty"
    }


def test_provider_response_keeps_carrier_while_errors_omit_raw_body():
    response = ProviderResponse(
        carrier="synthetic carrier",
        status=ResponseStatus.COMPLETE,
        mode=ResponseMode.JSON_SCHEMA,
    )
    error = StructuredOutputUnsupported(ResponseMode.JSON_SCHEMA, provider="openai")
    assert response.carrier == "synthetic carrier"
    assert response.finish_reason == ""
    assert str(error) == "structured_output_unsupported"
    assert not hasattr(error, "response_body")
    assert issubclass(ProviderRefusalError, RuntimeError)
```

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_response_protocol.py tests/test_settings.py -k "response_protocol or structured_response_mode" -v`

Expected: `src.ai.response_protocol`이 없어 import 실패하거나 `structured_response_mode` 기본값이 없어 FAIL

- [ ] **Step 3: 최소 프로토콜 타입과 설정 기본값 구현**

```python
RESPONSE_ENVELOPE_SCHEMA_VERSION = "1"


class LLMRequestKind(str, Enum):
    FINAL_REPLY = "final_reply"
    SUMMARY = "summary"
    DECISION = "decision"
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"


class ResponseMode(str, Enum):
    JSON_SCHEMA = "json_schema"
    STRICT_TOOL = "strict_tool"
    JSON_OBJECT = "json_object"
    LEGACY_TAGS = "legacy_tags"


class ResponseStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    REFUSAL = "refusal"
    EMPTY = "empty"


@dataclass(frozen=True)
class ProviderResponse:
    carrier: str
    status: ResponseStatus
    mode: ResponseMode
    finish_reason: str = ""
    usage: dict[str, int | None] | None = None


class StructuredOutputUnsupported(RuntimeError):
    def __init__(self, mode: ResponseMode, *, provider: str):
        super().__init__("structured_output_unsupported")
        self.mode = mode
        self.provider = provider


class ProviderRefusalError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResponseDeliveryMetadata:
    response_mode: str = ""
    schema_version: str = ""
    promises_authoritative: bool = False
    repair_performed: bool = False

    @classmethod
    def empty(cls) -> "ResponseDeliveryMetadata":
        return cls()
```

`src/core/settings.py`에는 UI를 추가하지 않고 `"structured_response_mode": "auto"`만 기본값으로 둔다. 읽을 때는 `auto|legacy` 외 값을 `auto`로 정규화한다.

- [ ] **Step 4: GREEN 및 기본 설정 회귀 확인**

Run: `python -m pytest tests/test_response_protocol.py tests/test_settings.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_protocol.py src/core/settings.py tests/test_response_protocol.py tests/test_settings.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: add structured response protocol types"
```

### Task 2: 고정 `ResponseEnvelopeV1` 스키마와 요청 시점 요구사항을 구현

**Files:**
- Create: `src/ai/response_envelope.py`
- Create: `tests/test_response_envelope.py`
- Create: `tests/structured_response_fixtures.py`
- Modify: `src/ai/response_contract.py`

공통 테스트 데이터는 `tests/structured_response_fixtures.py` 한 곳에서 합성 값으로 만든다.

```python
from copy import deepcopy
import json

from src.ai.response_envelope import ResponseRequirements


_BASE_ENVELOPE = {
    "reply": "중립 합성 답변",
    "emotion": "normal",
    "tts_text": "",
    "events": [],
    "analysis": {
        "user_emotion": "",
        "user_intent": "",
        "interaction_effect": "",
        "bond_delta_hint": "",
        "stress_delta_hint": "",
        "energy_delta_hint": "",
        "valence_delta_hint": "",
        "confidence": "",
        "flags": "",
    },
    "promises": [],
    "thought": "",
    "goal_update": {
        "action": "none",
        "type": "",
        "id": "",
        "title": "",
        "reason": "",
        "completion_reason": "",
    },
    "proactive_conversations": [],
    "gesture": "",
}


def make_valid_envelope(**overrides):
    payload = deepcopy(_BASE_ENVELOPE)
    payload.update(overrides)
    return payload


def valid_envelope_json(**overrides):
    return json.dumps(make_valid_envelope(**overrides), ensure_ascii=False)


def make_requirements(**overrides):
    values = {
        "response_language": "ko",
        "tts_language": "ko",
        "require_thought": False,
        "require_tts_text": False,
        "enable_analysis": False,
        "enable_events": False,
        "enable_promises": False,
        "enable_goal_update": False,
        "enable_proactive_conversations": False,
        "enable_gesture": False,
        "allowed_emotions": ("normal",),
        "allowed_proactive_cooldown_keys": ("synthetic",),
    }
    values.update(overrides)
    return ResponseRequirements(**values)


def no_repair_requirements():
    return make_requirements()


def thought_enabled_requirements():
    return make_requirements(require_thought=True)


def thought_and_tts_requirements():
    return make_requirements(
        tts_language="ja",
        require_thought=True,
        require_tts_text=True,
    )


def all_enabled_requirements():
    return make_requirements(
        require_thought=True,
        enable_analysis=True,
        enable_events=True,
        enable_promises=True,
        enable_goal_update=True,
        enable_proactive_conversations=True,
        enable_gesture=True,
    )


def repair_json(**fields):
    return json.dumps(fields, ensure_ascii=False)
```

- [ ] **Step 1: 재귀 strict schema와 request-scoped snapshot 테스트 작성**

```python
from src.ai.response_envelope import (
    RESPONSE_ENVELOPE_SCHEMA_NAME,
    RESPONSE_ENVELOPE_V1_SCHEMA,
    build_response_requirements,
)


def _assert_strict_objects(schema):
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
    for value in schema.values():
        if isinstance(value, dict):
            _assert_strict_objects(value)
        elif isinstance(value, list):
            for item in value:
                _assert_strict_objects(item)


def test_response_schema_requires_every_object_property_recursively():
    assert RESPONSE_ENVELOPE_SCHEMA_NAME == "ene_response_envelope_v1"
    _assert_strict_objects(RESPONSE_ENVELOPE_V1_SCHEMA)


def test_analysis_confidence_and_flags_are_strings():
    properties = RESPONSE_ENVELOPE_V1_SCHEMA["properties"]["analysis"]["properties"]
    assert properties["confidence"]["type"] == "string"
    assert properties["flags"]["type"] == "string"


def test_response_requirements_are_a_request_scoped_snapshot():
    settings = {"enable_ene_thoughts": True, "ui_language": "ko", "tts_language": "ja"}
    requirements = build_response_requirements(settings, available_emotions=["normal", "smile"])
    settings["enable_ene_thoughts"] = False
    assert requirements.require_thought is True
    assert requirements.require_tts_text is True
```

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_response_envelope.py::test_response_schema_requires_every_object_property_recursively -v`

Expected: `ModuleNotFoundError: src.ai.response_envelope`

- [ ] **Step 3: 교집합 스키마와 불변 요구사항 구현**

최상위 10개 필드는 모두 `required`이고 `null`, `oneOf`, `pattern`, `minLength`는 사용하지 않는다.

```python
RESPONSE_ENVELOPE_SCHEMA_NAME = "ene_response_envelope_v1"

TOP_LEVEL_FIELDS = (
    "reply", "emotion", "tts_text", "events", "analysis", "promises",
    "thought", "goal_update", "proactive_conversations", "gesture",
)

ANALYSIS_FIELDS = (
    "user_emotion", "user_intent", "interaction_effect", "bond_delta_hint",
    "stress_delta_hint", "energy_delta_hint", "valence_delta_hint",
    "confidence", "flags",
)


@dataclass(frozen=True)
class ResponseRequirements:
    response_language: str
    tts_language: str
    require_thought: bool
    require_tts_text: bool
    enable_analysis: bool
    enable_events: bool
    enable_promises: bool
    enable_goal_update: bool
    enable_proactive_conversations: bool
    enable_gesture: bool
    allowed_emotions: tuple[str, ...]
    allowed_proactive_cooldown_keys: tuple[str, ...]
```

하위 object 필드는 설계서 5.2 목록과 정확히 맞춘다. `analysis`의 모든 값, 특히 `confidence`와 `flags`도 string이다. `goal_update.action`의 비활성 송신값은 `none`, 나머지는 빈 문자열이다.

- [ ] **Step 4: GREEN 및 기존 계약 테스트 확인**

Run: `python -m pytest tests/test_response_envelope.py tests/test_response_contract.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_envelope.py src/ai/response_contract.py tests/test_response_envelope.py tests/structured_response_fixtures.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: define canonical response envelope schema"
```

### Task 3: envelope 부분 회수·도메인 검증·기존 10개 튜플 변환을 구현

**Files:**
- Modify: `src/ai/response_envelope.py`
- Modify: `tests/test_response_envelope.py`
- Modify: `src/ai/response_parser.py`

- [ ] **Step 1: 정상 변환과 부분 회수 실패 테스트 작성**

```python
from tests.structured_response_fixtures import (
    all_enabled_requirements,
    make_valid_envelope,
    thought_and_tts_requirements,
    thought_enabled_requirements,
)


def test_valid_envelope_maps_to_existing_tuple_order():
    decoded = decode_response_envelope(
        json.dumps(make_valid_envelope(reply="중립적인 합성 답변", thought="짧은 합성 내면 반응")),
        requirements=thought_enabled_requirements(),
    )

    assert decoded.payload[0] == "중립적인 합성 답변"
    assert decoded.payload[1] == "normal"
    assert decoded.payload[6] == "짧은 합성 내면 반응"
    assert len(decoded.payload) == 10


def test_decoder_preserves_reply_and_drops_invalid_side_effect_items():
    envelope = make_valid_envelope(reply="보존할 합성 답변")
    envelope["events"] = [{"date": "", "title": "잘못된 항목", "description": "", "extra": "x"}]
    envelope["promises"] = [{"trigger_at": "", "title": "잘못된 약속", "source": "user", "source_excerpt": ""}]
    envelope["unknown_root"] = "ignored"

    decoded = decode_response_envelope(json.dumps(envelope), requirements=all_enabled_requirements())

    assert decoded.payload[0] == "보존할 합성 답변"
    assert decoded.payload[3] == []
    assert decoded.payload[5] == []
    assert decoded.invalid_paths


def test_decoder_reports_only_enabled_missing_thought_and_translation_tts():
    envelope = make_valid_envelope(reply="합성 답변", thought="", tts_text="")
    decoded = decode_response_envelope(json.dumps(envelope), requirements=thought_and_tts_requirements())
    assert decoded.missing_required_fields == ("thought", "tts_text")
```

추가 테스트:

- `test_decoder_rejects_non_object_root_and_blank_reply`
- `test_decoder_normalizes_disabled_features_and_same_language_tts`
- `test_decoder_validates_goal_actions_and_limits_proactive_items_to_one`
- `test_decoder_normalizes_invalid_emotion_and_gesture`
- `test_legacy_tuple_uses_the_same_domain_normalizer`

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_response_envelope.py -k "maps_to_existing or preserves_reply or reports_only_enabled" -v`

Expected: decode/result API가 없어 FAIL

- [ ] **Step 3: 진단 결과와 allowlist 기반 decoder 구현**

```python
@dataclass(frozen=True)
class ResponseEnvelopeDecodeResult:
    payload: LLM_RESPONSE_TUPLE | None
    present_fields: frozenset[str]
    missing_required_fields: tuple[str, ...]
    invalid_paths: tuple[str, ...]
    root_error: str = ""

    @property
    def has_valid_reply(self) -> bool:
        return self.payload is not None and bool(self.payload[0].strip())
```

규칙:

- JSON 문법 또는 root object가 잘못되면 `payload=None`이다.
- root extra key는 무시하지만 `invalid_paths`에 기록한다.
- 부수효과 배열의 item에 extra/missing/type 오류가 있으면 그 item 전체를 버린다.
- `analysis`는 허용 key의 비어 있지 않은 문자열만 남긴다.
- `goal_update`는 action별 필수값이 충족되지 않으면 기존 튜플에서 `{}`로 정규화한다.
- 비활성 기능은 모델 값과 무관하게 기존 빈 표현으로 강제한다.
- 같은 언어 TTS는 `reply`를 재사용하고 `tts_text` 누락으로 판정하지 않는다.

- [ ] **Step 4: GREEN 및 기존 파서 기능 토글 회귀 확인**

Run: `python -m pytest tests/test_response_envelope.py tests/test_response_parser_feature_toggles.py tests/test_goal_update_parsing.py tests/test_proactive_conversation_parsing.py tests/test_gesture_response_flow.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_envelope.py src/ai/response_parser.py tests/test_response_envelope.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: decode and validate response envelopes"
```

### Task 4: 레거시 태그의 닫히지 않은 제어 블록 노출을 차단

**Files:**
- Modify: `src/ai/response_cleanup.py`
- Modify: `src/ai/response_parser.py`
- Modify: `tests/test_response_parsing.py`
- Modify: `tests/test_response_parser_feature_toggles.py`

- [ ] **Step 1: 제어 블록 누출과 thought-only 회귀 테스트 작성**

```python
@pytest.mark.parametrize(
    "start_tag",
    ["[analysis]", "[subconscious]", "[thought]", "[ene_thought]", "[tts]", "[ene_goal_update]", "[proactive_conversation]"],
)
def test_parse_response_strips_unclosed_reserved_control_blocks(start_tag):
    parsed = parse_llm_response(f"표시 가능한 합성 답변 [normal]\n{start_tag}\n노출되면 안 되는 합성 메타")
    assert parsed[0] == "표시 가능한 합성 답변"
    assert "노출되면 안 되는" not in str(parsed)


def test_parse_response_does_not_promote_thought_only_block_to_reply():
    parsed = parse_llm_response("[thought]\n합성 내면 반응\n[/thought]")
    assert parsed[0] == ""
```

기존 `test_parse_response_keeps_reply_when_model_wraps_everything_as_thought`는 승인 설계와 반대이므로 위 이름과 기대값으로 교체한다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_response_parsing.py -k "unclosed_reserved or thought_only" -v`

Expected: 닫히지 않은 analysis/thought/TTS 내용이 reply에 남거나 thought-only가 reply로 승격되어 FAIL

- [ ] **Step 3: 공통 예약 블록 정리 구현**

파싱 시작 단계에서 대응 종료 태그가 없는 예약 시작 태그부터 응답 끝까지 제거한다. 대상은 thought alias, `tts`, `analysis`, `ene_goal_update`, `proactive_conversation`이다. 닫힌 정상 블록은 기존 추출 순서를 유지하고, `<think>` 제거도 유지한다.

- [ ] **Step 4: GREEN 및 전체 레거시 파서 회귀 확인**

Run: `python -m pytest tests/test_response_parsing.py tests/test_response_parser_feature_toggles.py tests/test_response_contract.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_cleanup.py src/ai/response_parser.py tests/test_response_parsing.py tests/test_response_parser_feature_toggles.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "fix: hide malformed legacy response control blocks"
```

### Task 5: 의미 규칙, 구조화 필드 지침, 레거시 태그 형식을 분리

**Files:**
- Modify: `src/ai/response_contract.py`
- Modify: `src/ai/analysis_prompt.py`
- Modify: `src/ai/goal_prompt.py`
- Modify: `src/ai/thought_prompt.py`
- Modify: `src/ai/prompt_config.py`
- Modify: `src/ai/sub_prompt.py`
- Modify: `src/ai/prompt.py`
- Create: `tests/test_response_prompt_modes.py`
- Modify: `tests/test_response_contract.py`
- Modify: `tests/test_prompt_config.py`

- [ ] **Step 1: prompt mode 실패 테스트 작성**

```python
LEGACY_TOKENS = (
    "[emotion]", "[analysis]", "[subconscious]", "[tts]",
    "[ene_goal_update]", "[proactive_conversation]", "[event:", "[약속:", "[gesture:",
)


def test_runtime_structured_final_prompt_uses_fields_without_legacy_tokens():
    prompt = build_runtime_system_prompt(
        include_sub_prompt=True,
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
        settings_source=all_enabled_settings(),
    )
    assert all(token not in prompt for token in LEGACY_TOKENS)
    for field in RESPONSE_ENVELOPE_V1_SCHEMA["required"]:
        assert f"`{field}`" in prompt


def test_runtime_legacy_final_prompt_preserves_tag_contract():
    prompt = build_runtime_system_prompt(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.LEGACY_TAGS,
        settings_source=all_enabled_settings(),
    )
    assert "[subconscious]" in prompt
    assert "[ene_goal_update]" in prompt


def test_plain_text_with_sub_prompt_has_no_final_response_contract():
    prompt = build_runtime_system_prompt(
        include_sub_prompt=True,
        request_kind=LLMRequestKind.PLAIN_TEXT,
        response_mode=ResponseMode.LEGACY_TAGS,
        settings_source=all_enabled_settings(),
    )
    assert all(token not in prompt for token in LEGACY_TOKENS)
```

추가 테스트:

- `test_final_contract_is_selected_by_request_kind_not_include_sub_prompt`
- `test_structured_sub_prompt_uses_emotion_field_instead_of_emotion_tag`
- `test_structured_thought_rule_excludes_raw_reasoning`
- 기존 `build_response_contract_appendix()` 레거시 호출자는 동일 태그를 계속 받는다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_response_prompt_modes.py tests/test_prompt_config.py -k "structured or plain_text or final_contract" -v`

Expected: 새 인자 `TypeError` 또는 구조화/plain prompt에 legacy token이 남아 FAIL

- [ ] **Step 3: 출력 스타일별 prompt builder 구현**

권장 공개 경계:

```python
def build_structured_response_contract_appendix(settings_source=None) -> str:
    return "\n".join(build_structured_response_rules(settings_source))


def build_legacy_response_contract_appendix(settings_source=None) -> str:
    return "\n".join(build_legacy_response_rules(settings_source))


def build_response_contract_appendix(settings_source=None) -> str:
    return build_legacy_response_contract_appendix(settings_source)
```

`prompt_config.build_sub_prompt_text()`에는 `response_style="plain|structured_fields|legacy_tags"`를 전달한다. `analysis_prompt`, `goal_prompt`, `thought_prompt`는 의미 규칙과 태그 직렬화 문구를 분리한다. 구조화 지침은 field 이름만 가리키고, plain 요청에는 final response 형식 자체를 붙이지 않는다. `include_sub_prompt=False`인 final reply에도 base prompt 뒤의 final contract는 유지한다.

- [ ] **Step 4: GREEN 및 기존 prompt 회귀 확인**

Run: `python -m pytest tests/test_response_prompt_modes.py tests/test_response_contract.py tests/test_prompt_config.py tests/test_diary_feature.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_contract.py src/ai/analysis_prompt.py src/ai/goal_prompt.py src/ai/thought_prompt.py src/ai/prompt_config.py src/ai/sub_prompt.py src/ai/prompt.py tests/test_response_prompt_modes.py tests/test_response_contract.py tests/test_prompt_config.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "refactor: separate response semantics from legacy tags"
```

### Task 6: 제공자 profile, capability 선택, 명시적 미지원 하향 cache를 구현

**Files:**
- Modify: `src/ai/response_protocol.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `src/ai/http_llm_ollama.py`
- Create: `tests/test_response_capabilities.py`
- Modify: `tests/test_llm_provider.py`

- [ ] **Step 1: profile과 하향 판정 실패 테스트 작성**

```python
class SyntheticErrorResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def profile(provider, wire_format, *, endpoint="", model="synthetic-model"):
    return ProviderProfile(
        provider=provider,
        wire_format=wire_format,
        endpoint=endpoint,
        model=model,
    )


def http_error(status_code, body):
    response = SyntheticErrorResponse(status_code, body)
    return requests.HTTPError(
        f"synthetic_http_{status_code}",
        response=response,
    )


def test_named_provider_profiles_choose_conservative_native_modes():
    assert resolve_response_mode(profile("openai", "openai_responses")) is ResponseMode.JSON_SCHEMA
    assert resolve_response_mode(profile("openrouter", "openai_chat")) is ResponseMode.JSON_SCHEMA
    assert resolve_response_mode(profile("deepseek", "openai_chat")) is ResponseMode.JSON_OBJECT
    assert resolve_response_mode(profile("anthropic", "anthropic")) is ResponseMode.JSON_SCHEMA
    assert resolve_response_mode(profile("ollama", "ollama", endpoint="http://127.0.0.1:11434/api/chat")) is ResponseMode.JSON_SCHEMA


def test_unknown_custom_endpoint_defaults_to_legacy_but_known_profile_can_reuse_native():
    unknown = profile("custom_api", "openai_responses", endpoint="https://example.invalid/v1/responses")
    known = profile("custom_api", "openai_responses", endpoint="https://api.openai.com/v1/responses")
    assert resolve_response_mode(unknown) is ResponseMode.LEGACY_TAGS
    assert resolve_response_mode(known) is ResponseMode.JSON_SCHEMA


@pytest.mark.parametrize(
    "failure",
    [
        http_error(429, "synthetic_rate_limit"),
        requests.Timeout("synthetic_timeout"),
        http_error(503, "synthetic_server_error"),
        ProviderRefusalError("provider_refusal"),
        ValueError("malformed_output"),
    ],
)
def test_transient_or_content_failures_never_downgrade_capability(failure):
    assert is_explicit_structured_output_unsupported(failure) is False


def test_explicit_unknown_schema_parameter_downgrades_and_caches_by_full_key():
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )
    failure = http_error(
        400,
        "unknown parameter: response_format.json_schema",
    )
    registry = ResponseCapabilityRegistry()
    key = build_capability_key(current)

    assert is_explicit_structured_output_unsupported(failure) is True
    registry.mark_legacy(key)

    assert registry.resolve(current) is ResponseMode.LEGACY_TAGS
```

추가 테스트:

- `test_explicit_unknown_schema_parameter_downgrades_and_caches_by_full_key`
- `test_capability_key_uses_process_local_endpoint_fingerprint_not_raw_url`
- `test_legacy_setting_forces_legacy_without_probe`
- `test_ollama_cloud_uses_legacy`
- `test_named_anthropic_and_ollama_clients_expose_provider_identity`
- `test_custom_api_clients_expose_custom_identity_for_every_wire_format`

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_response_capabilities.py tests/test_llm_provider.py -k "profile or capability or custom_identity" -v`

Expected: resolver/profile API가 없거나 Anthropic/Ollama identity가 없어 FAIL

- [ ] **Step 3: process-local capability registry 구현**

```python
@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    wire_format: str
    endpoint: str
    model: str


@dataclass(frozen=True)
class ResponseCapabilityKey:
    provider: str
    wire_format: str
    endpoint_fingerprint: str
    model: str
    schema_version: str


class ResponseCapabilityRegistry:
    def __init__(self) -> None:
        self._overrides: dict[ResponseCapabilityKey, ResponseMode] = {}

    def resolve(self, profile, configured_mode: str = "auto") -> ResponseMode:
        key = build_capability_key(profile)
        return self._overrides.get(key, default_response_mode(profile, configured_mode))

    def mark_legacy(self, key: ResponseCapabilityKey) -> None:
        self._overrides[key] = ResponseMode.LEGACY_TAGS

    def clear(self) -> None:
        self._overrides.clear()
```

endpoint fingerprint는 process-local HMAC만 저장한다. HTTP 400/404/422에서 해당 mode parameter를 직접 지칭하는 `unsupported`, `unknown parameter`, `unknown field` 조합만 명시적 미지원으로 분류한다. raw error body는 분류 함수 안에서만 보고 exception/log/cache에는 저장하지 않는다. OpenAI·OpenRouter·DeepSeek·Anthropic 공식 endpoint exact match와 로컬 loopback Ollama만 알려진 profile로 인정한다.

- [ ] **Step 4: GREEN 및 공급자 factory 회귀 확인**

Run: `python -m pytest tests/test_response_capabilities.py tests/test_llm_provider.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_protocol.py src/ai/llm_provider.py src/ai/http_llm_common.py src/ai/http_llm_anthropic.py src/ai/http_llm_ollama.py tests/test_response_capabilities.py tests/test_llm_provider.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: resolve structured response capabilities"
```

### Task 7: `request_kind`를 모든 one-shot과 공통 요청 컨텍스트에 명시적으로 전달

**Files:**
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_openai.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `src/ai/http_llm_ollama.py`
- Modify: `src/ai/http_llm_custom_providers.py`
- Modify: `src/ai/llm_client.py`
- Modify: `src/ui/settings_tabs/profile_memory_tab.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_bridge_context_compaction.py`
- Modify: `tests/test_profile_memory_organizer.py`

- [ ] **Step 1: context fingerprint와 호출부 분류 테스트 작성**

```python
def test_request_context_fingerprint_records_kind_mode_and_schema_version():
    client = _build_openai_compatible_client()
    context = client._build_request_context(
        "합성 요청",
        provider_format="openai_responses",
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
    )
    fingerprint = context.fingerprint()
    assert fingerprint["request_kind"] == "final_reply"
    assert fingerprint["response_mode"] == "json_schema"
    assert fingerprint["schema_version"] == "1"


def test_summary_retry_remains_a_summary_request(monkeypatch):
    client = _build_openai_compatible_client()
    calls = []
    responses = iter(["[SUMMARY]\n부분 합성 요약", SUMMARY_OUTPUT])

    def fake_one_shot(_prompt, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)
    client._request_summary_text("합성 요약 입력")

    assert [call["request_kind"] for call in calls] == [
        LLMRequestKind.SUMMARY,
        LLMRequestKind.SUMMARY,
    ]
```

추가 테스트:

- `test_web_search_decision_uses_decision_request_kind`
- `test_markdown_generation_uses_markdown_request_kind`
- `test_diary_and_note_completion_use_plain_text_request_kind`
- `test_note_plan_and_profile_memory_proposal_use_decision_request_kind`
- `test_include_sub_prompt_true_does_not_make_one_shot_a_final_reply`

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_http_llm_clients_provider_parity.py tests/test_profile_memory_organizer.py -k "request_kind or one_shot or summary" -v`

Expected: fake helper가 새 keyword를 받지 못하거나 fingerprint에 kind/mode가 없어 FAIL

- [ ] **Step 3: `LLMRequestContext`와 모든 호출부 갱신**

명시적 분류:

| 호출 | `request_kind` |
|---|---|
| 일반 text/memory/image reply | `FINAL_REPLY` |
| summary 및 summary retry | `SUMMARY` |
| 웹 검색 판단 | `DECISION` |
| Markdown 문서 생성 | `MARKDOWN` |
| diary 완료 안내 | `PLAIN_TEXT` |
| note 명령 계획 | `DECISION` |
| note 실행 보고 | `PLAIN_TEXT` |
| profile-memory JSON 제안 | `DECISION` |

`_request_one_shot_raw()`와 Gemini `_generate_one_shot_text()`는 `request_kind` keyword를 받으며 기본값에 의존하지 않도록 내부 호출부를 전부 명시한다.

- [ ] **Step 4: GREEN 및 one-shot 회귀 확인**

Run: `python -m pytest tests/test_http_llm_clients_provider_parity.py tests/test_bridge_context_compaction.py tests/test_profile_memory_organizer.py tests/test_diary_feature.py tests/test_note_service.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/http_llm_common.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py src/ai/http_llm_ollama.py src/ai/http_llm_custom_providers.py src/ai/llm_client.py src/ui/settings_tabs/profile_memory_tab.py tests/test_http_llm_clients_provider_parity.py tests/test_bridge_context_compaction.py tests/test_profile_memory_organizer.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "refactor: classify llm request kinds explicitly"
```

### Task 8: 공통 최종 응답 파이프라인의 전체 재생성과 하향 정책 구현

**Files:**
- Create: `src/ai/response_pipeline.py`
- Create: `tests/test_structured_response_pipeline.py`
- Modify: `src/ai/response_protocol.py`
- Modify: `src/ai/response_envelope.py`

- [ ] **Step 1: primary/재생성/명시적 하향 실패 테스트 작성**

```python
class RecordingRequester:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.attempts = []
        self.cache_marked_legacy = 0

    def __call__(self, attempt):
        self.attempts.append(attempt)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def mark_unsupported(self, _mode):
        self.cache_marked_legacy += 1


def provider_response(carrier, *, mode=ResponseMode.JSON_SCHEMA, status=ResponseStatus.COMPLETE, finish_reason=""):
    return ProviderResponse(
        carrier=carrier,
        status=status,
        mode=mode,
        finish_reason=finish_reason,
    )


from tests.structured_response_fixtures import (
    no_repair_requirements,
    valid_envelope_json,
)


def test_invalid_root_retries_once_in_the_same_native_mode():
    requester = RecordingRequester([
        provider_response("not-json"),
        provider_response(valid_envelope_json(reply="재생성된 합성 답변")),
    ])
    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
        initial_mode=ResponseMode.JSON_SCHEMA,
        mark_unsupported=requester.mark_unsupported,
    )
    assert [attempt.mode for attempt in requester.attempts] == [ResponseMode.JSON_SCHEMA, ResponseMode.JSON_SCHEMA]
    assert result.payload[0] == "재생성된 합성 답변"


def test_explicit_unsupported_mode_downgrades_once_then_uses_legacy():
    requester = RecordingRequester([
        StructuredOutputUnsupported(ResponseMode.JSON_SCHEMA, provider="openai"),
        provider_response("레거시 합성 답변 [normal]", mode=ResponseMode.LEGACY_TAGS),
    ])
    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
        initial_mode=ResponseMode.JSON_SCHEMA,
        mark_unsupported=requester.mark_unsupported,
    )
    assert result.metadata.response_mode == "legacy_tags"
    assert requester.cache_marked_legacy == 1


@pytest.mark.parametrize(
    "outcome",
    [
        provider_response("안전 거절", status=ResponseStatus.REFUSAL),
        requests.Timeout("synthetic_timeout"),
    ],
)
def test_refusal_and_transient_errors_do_not_downgrade_or_repair(outcome):
    requester = RecordingRequester([outcome])
    with pytest.raises((ProviderRefusalError, requests.Timeout)):
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            initial_mode=ResponseMode.JSON_SCHEMA,
            mark_unsupported=requester.mark_unsupported,
        )
    assert len(requester.attempts) == 1
    assert requester.cache_marked_legacy == 0
```

추가 테스트:

- `test_missing_reply_regenerates_at_most_once`
- `test_incomplete_length_status_regenerates_same_mode`
- `test_second_invalid_response_returns_existing_safe_empty_response_path`
- `test_side_effects_are_not_exposed_from_failed_attempt`
- `test_malformed_output_never_marks_capability_legacy`
- `test_structured_modes_mark_empty_or_invalid_promises_authoritative`
- `test_legacy_mode_marks_empty_promises_non_authoritative`

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_structured_response_pipeline.py -k "retries_once or downgrades_once or refusal" -v`

Expected: pipeline API가 없어 FAIL

- [ ] **Step 3: callback 기반 공통 오케스트레이터 구현**

```python
@dataclass(frozen=True)
class ResponseAttempt:
    phase: str  # primary | regenerate | repair
    mode: ResponseMode
    repair_fields: tuple[str, ...] = ()
    preserved_reply: str = ""
    expand_output_budget: bool = False


@dataclass(frozen=True)
class FinalResponseResult:
    payload: LLM_RESPONSE_TUPLE
    metadata: ResponseDeliveryMetadata
    attempts: tuple[ResponseAttempt, ...]
```

provider callback은 `ProviderResponse(carrier, status, mode, usage)`만 반환한다. 파이프라인은 `ResponseStatus.REFUSAL`을 envelope로 파싱하지 않고, invalid root/missing reply는 같은 mode로 전체 재생성 1회 한다. `INCOMPLETE`이고 길이 초과 계열 `finish_reason`이면 재생성 `ResponseAttempt.expand_output_budget=True`를 설정한다. 각 adapter는 `min(provider_or_model_cap, max(current + 512, current * 2))`로 출력 예산을 늘리며, 알려진 cap이 없으면 보수적 공통 cap 8192를 쓴다. 명시적 구조화 파라미터 미지원 exception만 capability를 legacy로 갱신하고 같은 턴을 legacy로 1회 다시 보낸다.

최종 성공 mode가 `JSON_SCHEMA|STRICT_TOOL|JSON_OBJECT`이면 잘못된 promise 항목이 모두 폐기됐더라도 `promises_authoritative=True`로 둔다. `LEGACY_TAGS`만 `False`이며, 이 값과 실제 성공 mode/schema version을 같은 `FinalResponseResult.metadata`에 기록한다.

`tests/test_structured_response_pipeline.py::test_length_incomplete_sets_expanded_budget_on_only_the_regeneration_attempt`는 첫 attempt는 `False`, 두 번째 attempt만 `True`인지 검증한다. 제공자 payload 테스트는 두 번째 token budget이 첫 번째보다 크고 `client._response_output_token_cap()` 이하인지 검증한다.

- [ ] **Step 4: GREEN**

Run: `python -m pytest tests/test_structured_response_pipeline.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_pipeline.py src/ai/response_protocol.py src/ai/response_envelope.py tests/test_structured_response_pipeline.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: orchestrate validated final responses"
```

### Task 9: thought/TTS historyless 제한 복구와 reply 불변성을 구현

**Files:**
- Modify: `src/ai/response_pipeline.py`
- Modify: `src/ai/response_envelope.py`
- Modify: `tests/test_structured_response_pipeline.py`

- [ ] **Step 1: 제한 복구 실패 테스트 작성**

```python
from tests.structured_response_fixtures import (
    repair_json,
    thought_and_tts_requirements,
    valid_envelope_json,
)


def test_missing_thought_and_tts_use_one_historyless_repair_and_preserve_reply():
    original = "바이트 단위로 보존할 합성 답변"
    requester = RecordingRequester([
        provider_response(valid_envelope_json(reply=original, thought="", tts_text="")),
        provider_response(repair_json(thought="짧은 합성 내면 반응", tts_text="Synthetic speech")),
    ])
    result = execute_final_response(requester, requirements=thought_and_tts_requirements())

    assert result.payload[0] == original
    assert result.payload[6] == "짧은 합성 내면 반응"
    assert result.payload[2] == "Synthetic speech"
    assert requester.attempts[1].phase == "repair"
    assert requester.attempts[1].repair_fields == ("thought", "tts_text")
    assert result.metadata.repair_performed is True


def test_repair_ignores_reply_and_state_changing_fields():
    original = "그대로 남을 합성 답변"
    repair = repair_json(
        thought="채택할 합성 내면 반응",
        tts_text="Adopted synthetic speech",
        reply="무시할 대체 답변",
        events=[{"date": "2099-01-01", "title": "무시할 이벤트", "description": ""}],
        promises=[{
            "trigger_at": "2099-01-01T00:00:00+09:00",
            "title": "무시할 약속",
            "source": "assistant",
            "source_excerpt": "",
        }],
    )
    requester = RecordingRequester([
        provider_response(valid_envelope_json(reply=original, thought="", tts_text="")),
        provider_response(repair),
    ])
    result = execute_final_response(
        requester,
        requirements=thought_and_tts_requirements(),
        initial_mode=ResponseMode.JSON_SCHEMA,
        mark_unsupported=requester.mark_unsupported,
    )
    assert result.payload[0] == original
    assert result.payload[3] == []
    assert result.payload[5] == []
    assert result.payload[6] == "채택할 합성 내면 반응"
```

추가 테스트:

- `test_missing_only_thought_requests_only_thought_schema`
- `test_same_language_tts_never_triggers_repair`
- `test_repair_timeout_returns_original_reply_with_missing_optional_fields_empty`
- `test_failed_repair_still_sets_repair_performed_true`
- `test_repair_is_attempted_at_most_once`
- `test_legacy_mode_uses_minimal_thought_tts_tag_contract`

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_structured_response_pipeline.py -k "repair or preserve_reply or same_language" -v`

Expected: repair phase가 없어 FAIL

- [ ] **Step 3: 작은 repair schema/legacy contract와 allowlist 병합 구현**

복구 입력은 검증된 원 reply, 응답 언어, 누락 field 이름만 포함한다. history, memory, image, profile은 callback에 전달하지 않는다. structured mode는 누락 field만 가진 작은 schema를 쓰고 legacy는 thought/TTS 최소 태그만 요구한다. 병합 allowlist는 `thought`, `tts_text`뿐이다.

- [ ] **Step 4: GREEN**

Run: `python -m pytest tests/test_structured_response_pipeline.py tests/test_response_envelope.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/response_pipeline.py src/ai/response_envelope.py tests/test_structured_response_pipeline.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: repair missing thought and tts fields"
```

### Task 10: HTTP 공통 실행 경계와 visible reply history 저장을 연결

**Files:**
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_openai.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `src/ai/http_llm_ollama.py`
- Modify: `src/ai/http_llm_custom_providers.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_http_llm_clients_provider_parity.py`
- Modify: `tests/test_http_llm_clients_openai.py`
- Modify: `tests/test_http_llm_clients_multimodal_history.py`
- Create: `tests/http_structured_fixtures.py`

- [ ] **Step 1: HTTP 공통 파이프라인과 history 기대값 반전 테스트 작성**

기존 두 테스트는 확정 설계와 반대이므로 이름과 기대를 바꾼다.

- `test_provider_send_message_stores_visible_reply_only_in_history`
- `test_openai_send_message_stores_visible_reply_only_in_history`

공통 HTTP fixture는 다음처럼 실제 `requests.post` 경계를 기록한다.

```python
import json

import requests

from tests.structured_response_fixtures import valid_envelope_json


class DummyHTTPResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.text = json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def install_http_sequence(monkeypatch, responses):
    captured = []
    queue = list(responses)

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append(json)
        return queue.pop(0)

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)
    return captured


def openai_chat_body(carrier):
    return {"choices": [{"message": {"content": carrier}, "finish_reason": "stop"}]}


def openai_responses_body(carrier, *, status="completed"):
    return {
        "status": status,
        "output": [{
            "type": "message", "role": "assistant", "status": status,
            "content": [{"type": "output_text", "text": carrier}],
        }],
    }


class NoRepairSettings:
    def get(self, key, default=None):
        values = {
            "enable_ene_thoughts": False,
            "prompt_language": "ko",
            "tts_language": "ko",
            "structured_response_mode": "auto",
        }
        return values.get(key, default)


def no_repair_settings():
    return NoRepairSettings()
```

기존 parameterized history 테스트 본문은 각 기존 factory와 response body를 그대로 사용하되 다음 assertion으로 기대를 반전한다.

```python
payload = client.send_message("중립 합성 입력")
assistant = client.get_conversation_history()[-1]
assert assistant["content"] == payload[0]
assert "[analysis]" not in assistant["content"]
assert "{\"reply\"" not in assistant["content"]

metadata = client.get_last_response_delivery_metadata()
assert metadata.schema_version == "1"
```

`tests/conftest.py::_HTTP_LLM_TEST_MODULES`에는 새 `test_http_llm_structured_outputs.py`와 `test_response_capabilities.py`를 추가해 테스트 중 Store prompt 동기화/file I/O가 개입하지 않게 한다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_openai.py tests/test_http_llm_clients_multimodal_history.py -k "visible_reply_only or delivery_metadata" -v`

Expected: 현재 raw tag/JSON을 history에 저장하거나 metadata getter가 없어 FAIL

- [ ] **Step 3: `_CommonMixin._execute_final_response()`와 history commit 구현**

일반 text/memory/image send 경로만 공통 파이프라인을 사용한다. 성공 후 한 번만 user turn과 `parsed_payload[0]`을 history에 commit한다. primary/retry/repair carrier는 history에 넣지 않는다. HTTP client의 token usage는 V1에서 기존처럼 세 값 모두 `None`을 유지한다.

- [ ] **Step 4: GREEN 및 multimodal history 회귀 확인**

Run: `python -m pytest tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_openai.py tests/test_http_llm_clients_multimodal_history.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/http_llm_common.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py src/ai/http_llm_ollama.py src/ai/http_llm_custom_providers.py tests/conftest.py tests/http_structured_fixtures.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_openai.py tests/test_http_llm_clients_multimodal_history.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "refactor: validate http replies before history commit"
```

### Task 11: OpenAI Responses의 strict schema, carrier, status를 구현

**Files:**
- Modify: `src/ai/http_llm_openai.py`
- Create: `tests/test_http_llm_structured_outputs.py`
- Modify: `tests/test_http_llm_clients_openai.py`
- Modify: `tests/test_http_llm_clients_multimodal_history.py`

- [ ] **Step 1: 실제 wire 형태의 payload와 종료 상태 테스트 작성**

```python
def test_openai_responses_final_reply_uses_strict_json_schema(monkeypatch):
    captured = install_http_sequence(
        monkeypatch,
        [DummyHTTPResponse(openai_responses_body(valid_envelope_json(reply="합성 구조화 답변")))],
    )
    client = OpenAIResponseAPIClient(
        api_key="synthetic-key",
        model_name="gpt-4o-mini",
        endpoint="https://api.openai.com/v1/responses",
        provider_name="openai",
        settings=no_repair_settings(),
    )
    client.send_message("중립 합성 입력")
    fmt = captured[0]["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["name"] == RESPONSE_ENVELOPE_SCHEMA_NAME
    assert fmt["strict"] is True
    assert fmt["schema"] == RESPONSE_ENVELOPE_V1_SCHEMA


def test_openai_responses_assistant_history_status_is_completed():
    client = OpenAIResponseAPIClient(
        api_key="synthetic-key",
        model_name="gpt-4o-mini",
        endpoint="https://api.openai.com/v1/responses",
        provider_name="openai",
        settings=no_repair_settings(),
    )
    client._history = [{"role": "assistant", "content": "이전 합성 답변"}]

    items = client._input_items("다음 합성 질문")
    assistant = next(item for item in items if item.get("role") == "assistant")
    assert assistant["status"] == "completed"
```

추가 테스트:

- `test_openai_responses_extracts_output_text_from_output_items`
- `test_openai_responses_refusal_is_not_parsed_or_downgraded`
- `test_openai_responses_incomplete_length_retries_same_mode_and_increases_max_output_tokens_within_cap`
- `test_openai_responses_explicit_format_unsupported_retries_legacy_once_and_caches`
- `test_openai_responses_429_timeout_and_5xx_keep_native_capability`
- 기존 `_DummyResponse(output_text=...)` SDK 축약 fixture만 쓰지 말고 실제 `output[]/content[]/status` fixture를 포함한다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_http_llm_structured_outputs.py tests/test_http_llm_clients_openai.py tests/test_http_llm_clients_multimodal_history.py -k "openai_responses or assistant_history_status" -v`

Expected: `text.format`이 없거나 status가 `complete`, refusal/incomplete가 일반 text로 취급되어 FAIL

- [ ] **Step 3: OpenAI Responses adapter 구현**

`FINAL_REPLY`의 native mode에만 `text.format`을 추가하고 `name=RESPONSE_ENVELOPE_SCHEMA_NAME`을 항상 보낸다. `_extract_text`는 `output_text` 호환 fallback 전에 실제 `output[].content[]`의 `output_text`와 `refusal`을 읽고 response/item status 및 `incomplete_details.reason`을 `ProviderResponse`로 변환한다. assistant input item status는 `completed`로 수정한다. 길이 초과 재생성 payload는 첫 요청보다 큰 `max_output_tokens`를 쓰되 `_response_output_token_cap()` 이하로 제한한다.

- [ ] **Step 4: GREEN**

Run: `python -m pytest tests/test_http_llm_structured_outputs.py tests/test_http_llm_clients_openai.py tests/test_http_llm_clients_multimodal_history.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/http_llm_openai.py tests/test_http_llm_structured_outputs.py tests/test_http_llm_clients_openai.py tests/test_http_llm_clients_multimodal_history.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: use openai responses structured outputs"
```

### Task 12: OpenRouter와 DeepSeek의 서로 다른 OpenAI-compatible 정책을 구현

**Files:**
- Modify: `src/ai/http_llm_openai.py`
- Modify: `tests/test_http_llm_structured_outputs.py`
- Modify: `tests/test_response_capabilities.py`

- [ ] **Step 1: provider별 payload 차이 실패 테스트 작성**

```python
def _capture_openai_compatible(monkeypatch, *, provider_name, endpoint):
    captured = install_http_sequence(
        monkeypatch,
        [DummyHTTPResponse(openai_chat_body(valid_envelope_json(reply="합성 답변")))],
    )
    client = OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint=endpoint,
        provider_name=provider_name,
        settings=no_repair_settings(),
    )
    client.send_message("중립 합성 입력")
    return captured[0]


def test_openrouter_final_reply_requires_json_schema_supporting_route(monkeypatch):
    payload = _capture_openai_compatible(
        monkeypatch,
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )
    schema_config = payload["response_format"]["json_schema"]
    assert payload["response_format"]["type"] == "json_schema"
    assert schema_config["name"] == RESPONSE_ENVELOPE_SCHEMA_NAME
    assert schema_config["strict"] is True
    assert payload["provider"]["require_parameters"] is True


def test_deepseek_stable_final_reply_uses_json_object_not_json_schema(monkeypatch):
    payload = _capture_openai_compatible(
        monkeypatch,
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
    )
    assert payload["response_format"] == {"type": "json_object"}
    assert "json_schema" not in str(payload["response_format"])


def test_explicit_deepseek_beta_profile_uses_forced_strict_tool(monkeypatch):
    payload = _capture_openai_compatible(
        monkeypatch,
        provider_name="custom_api",
        endpoint="https://api.deepseek.com/beta/chat/completions",
    )
    function = payload["tools"][0]["function"]
    assert function["name"] == "emit_ene_response_envelope_v1"
    assert function["strict"] is True
    assert function["parameters"] == RESPONSE_ENVELOPE_V1_SCHEMA
    assert payload["tool_choice"]["function"]["name"] == function["name"]
```

추가 테스트:

- `test_openai_compatible_extracts_tool_arguments_carrier`
- `test_openrouter_route_unsupported_downgrades_only_its_capability_key`
- `test_deepseek_malformed_json_retries_json_object_once_without_legacy_downgrade`
- `test_deepseek_never_switches_to_beta_endpoint_automatically`
- `test_deepseek_strict_tool_extracts_function_arguments_carrier`
- `test_unknown_openai_compatible_custom_endpoint_keeps_legacy_tags`

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_http_llm_structured_outputs.py tests/test_response_capabilities.py -k "openrouter or deepseek or tool_arguments" -v`

Expected: response format/provider routing이 없어 FAIL

- [ ] **Step 3: named profile 분기 구현**

OpenRouter는 strict `response_format.json_schema`에 안정적인 schema `name`을 넣고 `provider.require_parameters=true`를 함께 쓴다. DeepSeek stable endpoint는 `json_object`만 사용하고 system 의미 지침에 JSON object 반환을 명시한다. 사용자가 이미 `https://api.deepseek.com/beta/chat/completions`를 명시한 exact profile은 `STRICT_TOOL`을 선택해 `strict=true` named function과 forced `tool_choice`를 사용하고 `function.arguments`를 carrier로 읽는다. stable endpoint를 beta로 자동 변경하지 않는다. 그 밖의 unknown OpenAI-compatible Custom API에는 native payload를 붙이지 않는다.

- [ ] **Step 4: GREEN**

Run: `python -m pytest tests/test_http_llm_structured_outputs.py tests/test_response_capabilities.py tests/test_http_llm_clients_provider_parity.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/http_llm_openai.py tests/test_http_llm_structured_outputs.py tests/test_response_capabilities.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: adapt openrouter and deepseek response modes"
```

### Task 13: Anthropic, 로컬 Ollama, Custom API fallback adapter를 구현

**Files:**
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `src/ai/http_llm_ollama.py`
- Modify: `src/ai/http_llm_custom_providers.py`
- Modify: `src/ai/llm_provider.py`
- Modify: `tests/test_http_llm_structured_outputs.py`
- Modify: `tests/test_response_capabilities.py`
- Modify: `tests/test_llm_provider.py`

- [ ] **Step 1: Anthropic/Ollama/Custom payload 실패 테스트 작성**

```python
def test_anthropic_final_reply_uses_output_config_json_schema(monkeypatch):
    captured = install_http_sequence(
        monkeypatch,
        [DummyHTTPResponse({"content": [{"type": "text", "text": valid_envelope_json()}], "stop_reason": "end_turn"})],
    )
    client = AnthropicClient(
        api_key="synthetic-key", model_name="synthetic-model",
        endpoint="https://api.anthropic.com/v1/messages",
        provider_name="anthropic", settings=no_repair_settings(),
    )
    client.send_message("중립 합성 입력")
    assert captured[0]["output_config"]["format"] == {
        "type": "json_schema",
        "schema": RESPONSE_ENVELOPE_V1_SCHEMA,
    }


def test_local_ollama_final_reply_uses_schema_object_format(monkeypatch):
    captured = install_http_sequence(
        monkeypatch,
        [DummyHTTPResponse({"message": {"content": valid_envelope_json()}, "done": True, "done_reason": "stop"})],
    )
    client = OllamaClient(
        api_key="", model_name="synthetic-model",
        endpoint="http://127.0.0.1:11434/api/chat",
        provider_name="ollama", settings=no_repair_settings(),
    )
    client.send_message("중립 합성 입력")
    assert captured[0]["format"] == RESPONSE_ENVELOPE_V1_SCHEMA
```

unknown Custom API는 기존 7개 wire-format parameterized factory를 사용해 `response_format`, `output_config`, schema object `format`이 없고 legacy contract가 남는지 검증한다. exact 공식 endpoint profile은 별도 positive case로 분리한다.

추가 테스트:

- `test_anthropic_refusal_and_max_tokens_become_terminal_statuses`
- `test_ollama_length_stop_retries_same_structured_mode_without_downgrade`
- `test_ollama_cloud_keeps_legacy_tags_without_schema_format`
- `test_custom_official_endpoint_profile_can_reuse_matching_native_adapter`
- `test_google_cloud_cohere_and_mistral_custom_adapters_default_to_legacy`

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_http_llm_structured_outputs.py tests/test_response_capabilities.py tests/test_llm_provider.py -k "anthropic or ollama or custom" -v`

Expected: native payload/identity/status 처리가 없어 FAIL

- [ ] **Step 3: 제공자별 최소 adapter 구현**

Anthropic은 `output_config.format`과 `stop_reason`을, Ollama는 로컬 profile에서만 schema object `format`과 `done/done_reason`을 사용한다. Custom API constructor에는 항상 `provider_name="custom_api"`와 wire format을 전달한다. 알려진 공식 endpoint profile로 정확히 식별될 때만 matching native adapter를 재사용한다. `max_tokens`/`done_reason=length` 재생성에서는 adapter cap 이내로 출력 예산을 늘리고 payload 테스트로 증가량을 검증한다.

- [ ] **Step 4: GREEN**

Run: `python -m pytest tests/test_http_llm_structured_outputs.py tests/test_response_capabilities.py tests/test_llm_provider.py tests/test_http_llm_clients_provider_parity.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/http_llm_anthropic.py src/ai/http_llm_ollama.py src/ai/http_llm_custom_providers.py src/ai/llm_provider.py tests/test_http_llm_structured_outputs.py tests/test_response_capabilities.py tests/test_llm_provider.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: add anthropic and ollama structured adapters"
```

### Task 14: Gemini native schema, 세션 signature, transactional history를 구현

**Files:**
- Modify: `src/ai/llm_client.py`
- Create: `tests/test_gemini_structured_outputs.py`
- Modify: `tests/test_prompt_config.py`
- Modify: `tests/test_bridge_context_compaction.py`
- Modify: `tests/test_gemini_empty_response.py`
- Create: `tests/gemini_structured_fixtures.py`

- [ ] **Step 1: Gemini config/session/history 실패 테스트 작성**

`tests/gemini_structured_fixtures.py`에는 다음 동작을 가진 `GeminiHarness`를 구현한다.

- `genai.Client`를 fake SDK로 교체한다.
- `fake_sdk.chats.create(model, config, history)` 호출마다 전달된 history deep copy를 `created_histories`에 기록한다.
- `FakeChat.send_message()`는 SDK처럼 user/model turn을 history에 자동 추가하고 준비된 response를 순서대로 반환한다.
- `fake_sdk.models.generate_content()`는 `repair_calls`에만 기록하고 main chat history를 바꾸지 않는다.
- response 객체는 `text`, `candidates`, `prompt_feedback`, `usage_metadata`를 모두 가진다.
- 같은 파일에서 `@pytest.fixture def gemini_harness(monkeypatch): return GeminiHarness(monkeypatch)`를 제공하고 `valid_envelope_json`은 공통 합성 fixture에서 import한다.

```python
def test_gemini_final_reply_config_uses_json_schema_and_json_mime_type(gemini_harness):
    client = gemini_harness.client([valid_envelope_json()])
    config = client._build_chat_config(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
    )
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] == RESPONSE_ENVELOPE_V1_SCHEMA


def test_gemini_session_signature_changes_with_mode_and_schema_version(gemini_harness):
    client = gemini_harness.client([valid_envelope_json()])
    first = client._runtime_prompt_signature(response_mode=ResponseMode.JSON_SCHEMA)
    second = client._runtime_prompt_signature(response_mode=ResponseMode.LEGACY_TAGS)
    assert first != second


def test_gemini_invalid_primary_restores_pre_turn_history_before_regeneration(gemini_harness):
    initial_history = [{"role": "user", "parts": [{"text": "이전 합성 질문"}]}]
    client = gemini_harness.client(
        ["not-json", valid_envelope_json(reply="재생성된 합성 답변")],
        history=initial_history,
    )
    result = client.send_message("현재 합성 질문")
    assert result[0] == "재생성된 합성 답변"
    assert gemini_harness.created_histories[-1] == initial_history
    assert "not-json" not in str(client.get_conversation_history())


def test_gemini_success_history_stores_visible_reply_not_raw_envelope(gemini_harness):
    raw = valid_envelope_json(reply="표시할 합성 답변")
    client = gemini_harness.client([raw])
    client.send_message("중립 합성 입력")
    history = client.get_conversation_history()
    assert history[-1]["content"] == "표시할 합성 답변"
    assert raw not in str(history)
```

추가 테스트:

- `test_gemini_plain_text_config_omits_envelope_schema_even_with_sub_prompt`
- `test_gemini_repair_uses_models_generate_content_without_main_chat_history` — 호출 전후 main history가 같고 `repair_calls == 1`인지 검증
- `test_gemini_retry_preserves_multimodal_user_parts_and_commits_only_visible_assistant_reply`
- `test_gemini_candidate_absence_returns_safe_fallback_without_capability_change`
- 기존 빈 응답 뒤 실패 user turn이 남는 기대는 pre-turn snapshot 복원 기대로 변경한다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_gemini_structured_outputs.py tests/test_prompt_config.py tests/test_bridge_context_compaction.py tests/test_gemini_empty_response.py -k "gemini and (schema or signature or history or repair or candidate)" -v`

Expected: schema config, assistant history rewrite, retry snapshot이 없어 FAIL

- [ ] **Step 3: Gemini adapter와 history transaction 구현**

- `FINAL_REPLY + JSON_SCHEMA`에만 `response_mime_type`과 `response_json_schema`를 설정한다.
- mode/schema version을 chat session signature에 포함한다.
- final turn 시작 전 SDK history를 deep-copy snapshot으로 보관한다.
- invalid primary/전체 재생성 전 snapshot으로 새 chat session을 만들고 실패 turn을 제거한다.
- 성공 후 최신 model part를 visible `reply`로 교체한다.
- 제한 복구는 기존 `_generate_one_shot_text()` 의미를 바꾸지 말고 response metadata를 보존하는 전용 historyless helper를 사용한다.
- 이미지 user part는 유지하고 assistant text만 수술적으로 교체한다.
- 길이 초과 재생성에서는 `max_output_tokens`를 첫 요청보다 늘리되 Gemini adapter cap 이하로 제한한다.

- [ ] **Step 4: GREEN 및 Gemini context 회귀 확인**

Run: `python -m pytest tests/test_gemini_structured_outputs.py tests/test_prompt_config.py tests/test_bridge_context_compaction.py tests/test_gemini_empty_response.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/llm_client.py tests/gemini_structured_fixtures.py tests/test_gemini_structured_outputs.py tests/test_prompt_config.py tests/test_bridge_context_compaction.py tests/test_gemini_empty_response.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: add gemini structured response transactions"
```

### Task 15: Gemini 한 턴의 primary/retry/repair token usage를 정확히 누산

**Files:**
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/response_protocol.py`
- Modify: `tests/test_token_usage.py`
- Modify: `tests/test_bridge_token_usage.py`

- [ ] **Step 1: 누산과 불완전 usage 실패 테스트 작성**

```python
def test_turn_token_usage_accumulates_primary_retry_and_repair():
    accumulator = TurnTokenUsageAccumulator()
    accumulator.record({"input_tokens": 10, "output_tokens": 4, "total_tokens": 14})
    accumulator.record({"input_tokens": 8, "output_tokens": 3, "total_tokens": 11})
    accumulator.record({"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
    assert accumulator.snapshot() == {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28}


def test_turn_token_usage_keeps_each_sum_null_when_any_attempt_omits_it():
    accumulator = TurnTokenUsageAccumulator()
    accumulator.record({"input_tokens": 10, "output_tokens": None, "total_tokens": None})
    accumulator.record({"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
    assert accumulator.snapshot() == {"input_tokens": 12, "output_tokens": None, "total_tokens": None}


def test_next_final_reply_resets_previous_turn_usage():
    client = GeminiClient.__new__(GeminiClient)
    client._begin_response_turn_usage()
    client._record_response_turn_usage({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    client._finish_response_turn_usage()
    client._begin_response_turn_usage()
    client._record_response_turn_usage({"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
    client._finish_response_turn_usage()
    assert client.get_last_token_usage() == {
        "input_tokens": 2, "output_tokens": 1, "total_tokens": 3
    }
```

응답 객체 없이 끝난 timeout/미지원 시도도 해당 시도 usage가 없는 것으로 기록해 각 합계에 `None`을 전파한다. HTTP client는 계속 전부 `None`이다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_token_usage.py tests/test_bridge_token_usage.py -v`

Expected: 현재 `_last_token_usage`가 마지막 응답으로 덮어써져 FAIL

- [ ] **Step 3: turn-scoped accumulator 구현**

public final reply 시작에서 accumulator를 초기화하고, primary/legacy fallback/regeneration/repair의 각 실제 호출을 기록한다. summary·decision·markdown one-shot은 final turn 누산기에 포함하지 않는다. `get_last_token_usage()`는 완료된 최신 final turn snapshot만 반환한다.

- [ ] **Step 4: GREEN**

Run: `python -m pytest tests/test_token_usage.py tests/test_bridge_token_usage.py tests/test_gemini_structured_outputs.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/llm_client.py src/ai/response_protocol.py tests/test_token_usage.py tests/test_bridge_token_usage.py tests/test_gemini_structured_outputs.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: aggregate gemini response turn usage"
```

### Task 16: `AIWorker` 전달 메타데이터와 authoritative promise 분기를 연결

**Files:**
- Modify: `src/core/bridge_workers.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Create: `tests/test_bridge_response_metadata.py`
- Modify: `tests/test_bridge_promise_reminders.py`
- Modify: `tests/test_bridge_worker_multimodal_capability.py`

- [ ] **Step 1: signal 불변·stale 방지·promise authority 실패 테스트 작성**

```python
FINAL_PAYLOAD = ("합성 답변", "normal", None, [], {}, [], "", {}, [], "")
STRUCTURED_METADATA = ResponseDeliveryMetadata(
    response_mode="json_schema", schema_version="1",
    promises_authoritative=True, repair_performed=False,
)


class MetadataClient:
    def __init__(self, *, fail=False):
        self.fail = fail

    def send_message(self, _message):
        if self.fail:
            raise RuntimeError("synthetic_worker_failure")
        return FINAL_PAYLOAD

    def get_last_response_delivery_metadata(self):
        return STRUCTURED_METADATA

    def get_last_token_usage(self):
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}


def test_ai_worker_captures_metadata_without_changing_response_signal_shape():
    emitted = []
    worker = AIWorker(MetadataClient(), "합성 입력", use_memory=False)
    worker.response_ready.connect(lambda *args: emitted.append(args))
    worker.run()
    assert len(emitted[0]) == 11
    assert json.loads(emitted[0][5]) == {
        "input_tokens": None, "output_tokens": None, "total_tokens": None,
    }
    assert worker.response_metadata == STRUCTURED_METADATA


def test_ai_worker_clears_stale_metadata_before_request_and_on_error():
    worker = AIWorker(MetadataClient(fail=True), "합성 입력", use_memory=False)
    worker.response_metadata = STRUCTURED_METADATA
    worker.run()
    assert worker.response_metadata == ResponseDeliveryMetadata.empty()


def test_ai_worker_non_final_success_does_not_copy_stale_client_metadata():
    worker = AIWorker(
        MetadataClient(), "합성 입력",
        diary_request="합성 일기 요청", diary_service=object(),
    )

    async def fake_diary_flow():
        return FINAL_PAYLOAD

    worker._run_diary_flow = fake_diary_flow
    worker.run()
    assert worker.response_metadata == ResponseDeliveryMetadata.empty()


def test_on_response_ready_skips_promise_heuristics_for_authoritative_empty_promises():
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("authoritative empty promises must not use heuristics")

    dummy = build_promise_bridge_dummy()
    dummy.worker.response_metadata = STRUCTURED_METADATA
    dummy._maybe_store_user_promise_candidates = fail_if_called
    dummy._maybe_store_assistant_promise_candidates = fail_if_called
    WebBridge._on_response_ready(dummy, "합성 답변", "normal", "", [], "", "", [])
```

`build_promise_bridge_dummy()`는 `tests/test_bridge_promise_reminders.py`의 기존 반복 설정을 추출한 로컬 helper다. `WebBridge._on_response_ready`가 읽는 `worker`, promise 저장 함수, 후속 응답 처리 함수만 `SimpleNamespace`/bound method로 제공하고 실제 thread·파일·네트워크는 만들지 않는다. `tests/test_bridge_response_metadata.py`에서는 이 helper를 명시적으로 import한다.

추가 테스트:

- `test_on_response_ready_consumes_current_worker_metadata_once`
- `test_ai_worker_non_final_success_does_not_copy_stale_client_metadata`
- `test_missing_or_invalid_metadata_keeps_legacy_promise_heuristics`
- `test_legacy_empty_promises_run_existing_heuristics_once`
- 기존 11개 signal 인자 순서와 10개 tuple normalization 회귀를 유지한다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_bridge_response_metadata.py tests/test_bridge_promise_reminders.py -k "metadata or authoritative or legacy_empty" -v`

Expected: worker metadata가 없거나 structured empty promises에서도 heuristic이 호출되어 FAIL

- [ ] **Step 3: request-scoped worker metadata와 bridge 소비 구현**

`AIWorker.run()` 시작 시 worker metadata를 `ResponseDeliveryMetadata.empty()`로 초기화한다. client도 각 public final reply 시작 시 자체 metadata를 비우고 성공한 final reply에서만 새 값을 설정한다. worker는 text/memory/image 일반 final 분기에서만 client getter를 복사하며 diary/note 같은 비-final 성공 분기는 빈 metadata를 유지한다. 오류·실제 중단에서도 지운다. 성공 emit 직후 `finally`에서 지우지 않는다. Qt queued signal보다 먼저 사라질 수 있기 때문이다.

`_on_response_ready()`가 현재 worker metadata를 snapshot한 뒤 `_handle_response_ready(..., *, response_metadata=None)`에 keyword-only로 전달하고 소비 후 worker 값을 비운다. promise fallback 조건은 다음 하나로 고정한다.

```python
use_fallback = not llm_promises and not promises_authoritative
```

`PromiseBridgeMixin` 저장/추출 함수 자체는 바꾸지 않는다.

- [ ] **Step 4: GREEN 및 브리지 회귀 확인**

Run: `python -m pytest tests/test_bridge_response_metadata.py tests/test_bridge_promise_reminders.py tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_token_usage.py tests/test_gesture_response_flow.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/bridge_workers.py src/core/bridge_mixins/chat_flow.py tests/test_bridge_response_metadata.py tests/test_bridge_promise_reminders.py tests/test_bridge_worker_multimodal_capability.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "feat: deliver structured response metadata to bridge"
```

### Task 17: final reply·TTS·오류 로그에서 원문을 제거

**Files:**
- Modify: `src/ai/llm_client.py`
- Modify: `src/ai/http_llm_common.py`
- Modify: `src/ai/http_llm_openai.py`
- Modify: `src/ai/http_llm_anthropic.py`
- Modify: `src/ai/http_llm_ollama.py`
- Modify: `src/ai/http_llm_custom_providers.py`
- Modify: `src/core/bridge_workers.py`
- Modify: `src/core/bridge_mixins/chat_flow.py`
- Modify: `src/core/bridge_mixins/tts.py`
- Create: `tests/test_llm_privacy_logging.py`
- Modify: `tests/test_bridge_context_compaction.py`
- Modify: `tests/test_bridge_worker_multimodal_capability.py`
- Modify: `tests/test_bridge_request_pending.py`
- Modify: `tests/test_bridge_tts_streaming.py`
- Modify: `tests/test_http_llm_clients_openai.py`

- [ ] **Step 1: 원문 sentinel 비노출 실패 테스트 작성**

```python
from src.ai.response_protocol import ResponseDeliveryMetadata
from src.core.bridge_workers import AIWorker


SAFE_METADATA = ResponseDeliveryMetadata(
    response_mode="json_schema",
    schema_version="1",
    promises_authoritative=True,
    repair_performed=False,
)


class LoggingClient:
    def __init__(self, reply, tts_text):
        self.reply = reply
        self.tts_text = tts_text

    def send_message(self, _message):
        return (self.reply, "normal", self.tts_text, [], {}, [], "", {}, [], "")

    def get_last_response_delivery_metadata(self):
        return SAFE_METADATA

    def get_last_token_usage(self):
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}


def test_final_reply_logs_are_content_free(capsys):
    user_secret = "SYNTHETIC-USER-CONTENT-SENTINEL"
    reply_secret = "SYNTHETIC-REPLY-CONTENT-SENTINEL"
    tts_secret = "SYNTHETIC-TTS-CONTENT-SENTINEL"
    worker = AIWorker(LoggingClient(reply_secret, tts_secret), user_secret, use_memory=False)
    worker.run()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert user_secret not in combined
    assert reply_secret not in combined
    assert tts_secret not in combined
    assert "response_mode=" in combined


def test_provider_error_log_omits_raw_body_and_exception_content(capsys):
    raw_error = "SYNTHETIC-PROVIDER-ERROR-BODY-SENTINEL"

    class FailingClient:
        def send_message(self, _message):
            raise RuntimeError(raw_error)

        def get_last_response_delivery_metadata(self):
            return ResponseDeliveryMetadata.empty()

        def get_last_token_usage(self):
            return {"input_tokens": None, "output_tokens": None, "total_tokens": None}

    AIWorker(FailingClient(), "합성 입력", use_memory=False).run()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert raw_error not in combined
    assert "provider_error" in combined
```

기존 원문 로그를 기대하는 테스트는 privacy-safe 역검증으로 교체한다. schedule 성공/실패, pending TTS flush, TTSWorker/StreamingTTSWorker도 원문이 없어야 한다.

- [ ] **Step 2: RED 확인**

Run: `python -m pytest tests/test_llm_privacy_logging.py tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_request_pending.py tests/test_bridge_tts_streaming.py tests/test_bridge_context_compaction.py -k "log or content_free or omits" -v`

Expected: user/reply/TTS/error body sentinel이 stdout/stderr에 나타나 FAIL

- [ ] **Step 3: 내용 없는 진단 로그와 정규화 오류 구현**

허용: provider/model family, response mode, schema version, 종료/오류 분류 code, 문자 수, item 수, token usage, process-local fingerprint.

금지: user message, assistant reply, thought, TTS, 분석/일정/약속/목표/선제 대화 본문, 전체 request/response JSON, raw HTTP body, traceback에 포함된 prompt.

worker가 사용자에게 보내는 오류는 기존 일반 안내 흐름을 유지하고, 로그에는 exception class/category만 남긴다. raw body는 in-memory classifier에서만 사용한다.

- [ ] **Step 4: GREEN 및 로그 관련 회귀 확인**

Run: `python -m pytest tests/test_llm_privacy_logging.py tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_request_pending.py tests/test_bridge_tts_streaming.py tests/test_bridge_context_compaction.py tests/test_http_llm_clients_openai.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai/llm_client.py src/ai/http_llm_common.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py src/ai/http_llm_ollama.py src/ai/http_llm_custom_providers.py src/core/bridge_workers.py src/core/bridge_mixins/chat_flow.py src/core/bridge_mixins/tts.py tests/test_llm_privacy_logging.py tests/test_bridge_context_compaction.py tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_request_pending.py tests/test_bridge_tts_streaming.py tests/test_http_llm_clients_openai.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "fix: remove llm content from diagnostic logs"
```

### Task 18: 통합 회귀, 운영 문서, 개인정보·staging 검사를 완료

**Files:**
- Create: `docs/provider-neutral-structured-responses.md`
- Create: `tests/test_structured_response_integration.py`

- [ ] **Step 1: 제공자 중립 end-to-end 회귀 테스트 보강**

최소 통합 시나리오:

- native structured thought가 기존 `message_received` 생각 인자로 도달한다.
- thought 누락 → 제한 복구 성공 → 버튼 경로에 nonempty thought가 도달한다.
- thought 복구 실패 → reply는 표시되고 thought만 빈 값이다.
- legacy-only 모델의 정상 tag 응답이 동일 10개 tuple/UI 경로로 도달한다.
- structured `promises=[]`는 heuristic을 재실행하지 않고 legacy empty promises는 재실행한다.
- retry/repair 중 side-effect는 최종 검증 결과에서 한 번만 적용된다.
- summary/decision/markdown/diary/note/profile-memory one-shot에는 ENE envelope가 붙지 않는다.

- [ ] **Step 2: 핵심 묶음 테스트 실행**

Run:

```powershell
python -m pytest tests/test_response_protocol.py tests/test_response_envelope.py tests/test_response_prompt_modes.py tests/test_structured_response_pipeline.py tests/test_response_capabilities.py tests/test_http_llm_structured_outputs.py tests/test_gemini_structured_outputs.py tests/test_bridge_response_metadata.py tests/test_llm_privacy_logging.py tests/test_structured_response_integration.py -v
```

Expected: PASS

- [ ] **Step 3: 관련 전체 회귀 실행**

Run:

```powershell
python -m pytest tests/test_response_contract.py tests/test_response_parsing.py tests/test_response_parser_feature_toggles.py tests/test_goal_update_parsing.py tests/test_proactive_conversation_parsing.py tests/test_gesture_response_flow.py tests/test_http_llm_clients_provider_parity.py tests/test_http_llm_clients_openai.py tests/test_http_llm_clients_multimodal_history.py tests/test_llm_provider.py tests/test_gemini_empty_response.py tests/test_token_usage.py tests/test_bridge_token_usage.py tests/test_bridge_promise_reminders.py tests/test_bridge_worker_multimodal_capability.py tests/test_bridge_request_pending.py tests/test_bridge_tts_streaming.py tests/test_bridge_context_compaction.py tests/test_profile_memory_organizer.py -v
```

Expected: PASS

- [ ] **Step 4: 전체 테스트와 정적 점검 실행**

Run:

```powershell
python -m pytest -q
python -m ruff check src/ai/response_protocol.py src/ai/response_envelope.py src/ai/response_pipeline.py src/ai/response_contract.py src/ai/prompt.py src/ai/http_llm_common.py src/ai/http_llm_openai.py src/ai/http_llm_anthropic.py src/ai/http_llm_ollama.py src/ai/llm_client.py src/core/bridge_workers.py src/core/bridge_mixins/chat_flow.py
git diff --check
```

Expected: 모두 exit 0

- [ ] **Step 5: 운영 문서 작성**

`docs/provider-neutral-structured-responses.md`에 다음만 기록한다.

- `auto`와 긴급 `legacy` 설정 의미
- 제공자별 V1 mode 표
- 명시적 미지원과 일시 오류의 차이
- thought/TTS 제한 복구와 안전한 실패 동작
- `thought`가 raw reasoning이 아니라 공개 가능한 캐릭터 반응이라는 점
- 내용 없는 진단 항목과 troubleshooting 순서
- V2 후보: UI mode 선택, Ollama Cloud capability, DeepSeek beta profile 직접 선택 UI/검증(runtime strict-tool 지원 자체는 V1)

- [ ] **Step 6: 개인정보·runtime·API key staging 검사**

Run:

```powershell
git status --short
rg -n "(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|SYNTHETIC-(USER|REPLY|TTS)-CONTENT-SENTINEL|이름|생일|건강|병원|일정|취업|자소서|프로필|name|birthday|health|hospital|schedule|employment|resume|profile)" src tests docs
git diff --cached --name-only
```

Expected:

- 실제 이름·대화·건강·일정·취업·프로필 원문 및 API key pattern 없음
- synthetic sentinel은 해당 privacy 테스트 안에서만 발견됨
- runtime 파일, binary/generated artifact, screenshot 없음

- [ ] **Step 7: 최종 문서와 통합 변경 commit**

```bash
git add docs/provider-neutral-structured-responses.md tests/test_structured_response_integration.py
# 위 공통 개인정보 gate를 통과한 뒤 실행
git commit -m "docs: document structured response operations"
```

---

## 완료 기준 체크리스트

- [ ] 생각 기능 활성 상태에서 primary 누락 시 thought/TTS 제한 복구가 정확히 한 번 실행된다.
- [ ] 복구 성공 시 nonempty thought가 기존 UI 생각 버튼 경로에 도달한다.
- [ ] 복구 실패 시 원 reply는 그대로 표시되고 누락 기능만 비어 있다.
- [ ] native 지원 제공자는 각 공식 구조화 payload를 사용한다.
- [ ] native 미지원 모델과 unknown Custom API는 기존 태그 방식으로 동작한다.
- [ ] 명시적 미지원만 process-local legacy cache를 갱신한다.
- [ ] 429, timeout, 5xx, refusal, malformed output은 capability를 바꾸지 않는다.
- [ ] history에는 visible reply만 저장되고 raw JSON/tool/tag carrier는 남지 않는다.
- [ ] structured `promises=[]`와 legacy empty promises의 heuristic 동작이 구분된다.
- [ ] 기존 10개 `LLM_RESPONSE_TUPLE`과 11개 `response_ready` signal 인자가 유지된다.
- [ ] final reply 관련 로그와 테스트 fixture에 실제 원문·개인정보가 없다.
- [ ] 전체 pytest와 선택 ruff 검사가 통과한다.
