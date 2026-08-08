"""공식 OpenAI 모델별 요청 파라미터 정책."""

from __future__ import annotations

from dataclasses import dataclass
import re


OPENAI_REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
_GPT_5_6_PATTERN = re.compile(r"^gpt-5\.6(?:$|-)")
_O_SERIES_PATTERN = re.compile(r"^o\d+(?:$|-)")


@dataclass(frozen=True)
class OpenAIModelPolicy:
    supports_temperature: bool = True
    supports_top_p: bool = True
    supports_reasoning_effort: bool = False
    default_reasoning_effort: str | None = None
    allowed_reasoning_efforts: tuple[str, ...] = ()


_DEFAULT_POLICY = OpenAIModelPolicy()
_REASONING_MODEL_POLICY = OpenAIModelPolicy(
    supports_temperature=False,
    supports_top_p=False,
    supports_reasoning_effort=True,
    default_reasoning_effort="low",
    allowed_reasoning_efforts=OPENAI_REASONING_EFFORTS,
)


def normalize_reasoning_effort(value: object, default: object = "low") -> str:
    """추론 강도를 허용 값으로 정규화한다."""
    normalized_value = str(value or "").strip().lower()
    if normalized_value in OPENAI_REASONING_EFFORTS:
        return normalized_value

    normalized_default = str(default or "").strip().lower()
    if normalized_default in OPENAI_REASONING_EFFORTS:
        return normalized_default
    return "low"


def resolve_openai_model_policy(provider: object, model_name: object) -> OpenAIModelPolicy:
    """공급자와 모델명에 맞는 요청 파라미터 정책을 반환한다."""
    normalized_provider = str(provider or "").strip().lower()
    normalized_model_name = str(model_name or "").strip().lower()
    if normalized_provider == "openai" and (
        _GPT_5_6_PATTERN.match(normalized_model_name)
        or _O_SERIES_PATTERN.match(normalized_model_name)
    ):
        return _REASONING_MODEL_POLICY
    return _DEFAULT_POLICY
