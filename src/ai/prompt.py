"""
ENE AI 시스템 프롬프트 로더
"""

from .prompt_config import load_runtime_prompt_config


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
    config = load_runtime_prompt_config(settings_source=settings_source)
    system_prompt = get_system_prompt(include_sub_prompt=include_sub_prompt, settings_source=settings_source)
    analysis_system_appendix = str(config.get("analysis_system_appendix", "") or "").strip()
    if include_analysis_appendix and include_sub_prompt and analysis_system_appendix:
        return f"{system_prompt}\n\n{analysis_system_appendix}"
    return system_prompt


def get_available_emotions() -> list[str]:
    """사용 가능한 감정 목록 반환"""
    config = load_runtime_prompt_config()
    return list(config.get("emotions", []))
