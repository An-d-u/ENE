"""
ENE AI 시스템 프롬프트 로더
"""

from .prompt_config import load_prompt_config, load_runtime_prompt_config
from .analysis_prompt import build_analysis_system_appendix
from .response_contract import build_response_contract_appendix


def get_system_prompt(include_sub_prompt: bool = True, settings_source: dict | None = None) -> str:
    """시스템 프롬프트 반환"""
    config = load_runtime_prompt_config(settings_source=settings_source)
    base_system_prompt = str(config.get("base_system_prompt", "") or "")

    if include_sub_prompt:
        try:
            from .sub_prompt import get_sub_prompt

            sub_prompt = (get_sub_prompt(settings_source=settings_source) or "").strip()
            if sub_prompt:
                return base_system_prompt + "\n\n" + sub_prompt
            print("[Prompt] sub_prompt가 비어 있어 base_system_prompt만 사용합니다.")
        except Exception as e:
            print(f"[Prompt] sub_prompt 로드 실패, base_system_prompt만 사용합니다: {e}")

    return base_system_prompt


def build_runtime_system_prompt(
    include_sub_prompt: bool = True,
    include_analysis_appendix: bool = False,
    settings_source: dict | None = None,
) -> str:
    """실제 모델 호출에 사용할 시스템 프롬프트를 조립한다."""
    system_prompt = get_system_prompt(include_sub_prompt=include_sub_prompt, settings_source=settings_source)
    parts = [system_prompt]
    if include_analysis_appendix and include_sub_prompt:
        analysis_system_appendix = build_analysis_system_appendix(settings_source=settings_source).strip()
        parts.append(analysis_system_appendix)
    if include_sub_prompt:
        response_contract_appendix = build_response_contract_appendix(settings_source=settings_source).strip()
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
