"""
ENE AI 시스템 프롬프트 로더
"""

from .prompt_config import (
    load_prompt_config,
    load_runtime_prompt_config,
    normalize_response_style,
)
from .analysis_prompt import build_analysis_system_appendix
from .response_contract import (
    build_legacy_response_contract_appendix,
    build_structured_response_contract_appendix,
)
from .response_protocol import LLMRequestKind, ResponseMode


_LIFE_RECORD_SYSTEM_CONTRACT = """## 생활 기록 전용 계약

이 지시는 앞의 기본 시스템 프롬프트와 충돌할 경우 생활 기록 행동과 JSON 출력에 대해 우선합니다.
주어진 비활성 구간 동안 에네가 생활 환경에서 한 행동을 시간순으로 구성하세요.
출력은 Markdown이나 설명을 섞지 말고 JSON 객체 하나만 반환하세요.
최상위 키는 `entries`, `ending_state`만 허용합니다.
`entries`는 1개 이상 24개 이하이며 각 항목은 문자열 `started_at`, `ended_at`, `place`, `activity`만 포함합니다.
`ending_state`는 문자열 `place`, `summary`만 포함합니다.
각 객체에 추가 필드를 만들지 마세요.
모든 시각은 요청에 지정된 오프셋 포함 ISO 8601 형식을 사용하세요.
항목은 전체 구간을 빈틈이나 겹침 없이 정확히 덮고, 마지막 항목의 장소는 `ending_state.place`와 같아야 합니다."""


def build_life_record_system_instruction(
    settings_source: dict | None = None,
) -> str:
    """현재 기본 프롬프트 뒤에 생활 기록 전용 우선 계약만 붙인다."""
    config = load_runtime_prompt_config(settings_source=settings_source)
    base_system_prompt = str(config.get("base_system_prompt", "") or "").strip("\n")
    if not base_system_prompt:
        return _LIFE_RECORD_SYSTEM_CONTRACT
    return base_system_prompt + "\n\n" + _LIFE_RECORD_SYSTEM_CONTRACT


def get_system_prompt(
    include_sub_prompt: bool = True,
    settings_source: dict | None = None,
    response_style: str = "legacy_tags",
) -> str:
    """시스템 프롬프트 반환"""
    response_style = normalize_response_style(response_style)
    config = load_runtime_prompt_config(settings_source=settings_source)
    base_system_prompt = str(config.get("base_system_prompt", "") or "")

    if include_sub_prompt:
        try:
            from .sub_prompt import get_sub_prompt

            sub_prompt = (
                get_sub_prompt(settings_source=settings_source, response_style=response_style) or ""
            ).strip()
            if sub_prompt:
                return base_system_prompt + "\n\n" + sub_prompt
            print("[Prompt] sub_prompt가 비어 있어 base_system_prompt만 사용합니다.")
        except Exception as e:
            print(f"[Prompt] sub_prompt 로드 실패, base_system_prompt만 사용합니다: {e}")

    return base_system_prompt


def _resolve_response_style(
    request_kind: LLMRequestKind,
    response_mode: ResponseMode,
) -> str:
    if request_kind != LLMRequestKind.FINAL_REPLY:
        return "plain"
    return "legacy_tags" if response_mode == ResponseMode.LEGACY_TAGS else "structured_fields"


def build_runtime_system_prompt(
    include_sub_prompt: bool = True,
    include_analysis_appendix: bool = False,
    settings_source: dict | None = None,
    request_kind: LLMRequestKind = LLMRequestKind.FINAL_REPLY,
    response_mode: ResponseMode = ResponseMode.LEGACY_TAGS,
) -> str:
    """실제 모델 호출에 사용할 시스템 프롬프트를 조립한다."""
    try:
        request_kind = LLMRequestKind(request_kind)
    except (TypeError, ValueError):
        raise ValueError(f"invalid request kind: {request_kind!r}") from None
    try:
        response_mode = ResponseMode(response_mode)
    except (TypeError, ValueError):
        raise ValueError(f"invalid response mode: {response_mode!r}") from None

    response_style = _resolve_response_style(request_kind, response_mode)
    system_prompt = get_system_prompt(
        include_sub_prompt=include_sub_prompt,
        settings_source=settings_source,
        response_style=response_style,
    )
    parts = [system_prompt]
    if (
        include_analysis_appendix
        and include_sub_prompt
        and request_kind == LLMRequestKind.FINAL_REPLY
        and response_style == "legacy_tags"
    ):
        analysis_system_appendix = build_analysis_system_appendix(
            settings_source=settings_source,
            response_style=response_style,
        ).strip()
        parts.append(analysis_system_appendix)
    if request_kind == LLMRequestKind.FINAL_REPLY:
        if response_style == "legacy_tags":
            response_contract_appendix = build_legacy_response_contract_appendix(
                settings_source=settings_source
            ).strip()
        else:
            config = load_runtime_prompt_config(settings_source=settings_source)
            response_contract_appendix = build_structured_response_contract_appendix(
                settings_source=settings_source,
                available_emotions=config.get("emotions", ("normal",)),
            ).strip()
        if response_contract_appendix:
            parts.append(response_contract_appendix)
    return "\n\n".join(part for part in parts if part)


def get_available_emotions() -> list[str]:
    """사용 가능한 감정 목록 반환"""
    config = load_runtime_prompt_config()
    return list(config.get("emotions", []))


def get_parseable_emotions(settings_source: dict | None = None) -> list[str]:
    """응답 파서가 하위 호환으로 인식할 수 있는 감정 목록 반환."""
    saved_config = load_prompt_config()
    runtime_config = load_runtime_prompt_config(settings_source=settings_source)
    emotions: list[str] = []
    seen: set[str] = set()
    for item in list(saved_config.get("emotions", [])) + list(runtime_config.get("emotions", [])):
        emotion = str(item or "").strip().lower()
        if emotion and emotion not in seen:
            seen.add(emotion)
            emotions.append(emotion)
    if not emotions:
        emotions = ["normal"]
    return emotions
