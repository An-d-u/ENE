"""
ENE AI 서브 프롬프트 로더
"""

from .prompt_config import get_sub_prompt_text


def get_sub_prompt() -> str:
    """서브 프롬프트 반환"""
    return get_sub_prompt_text()
