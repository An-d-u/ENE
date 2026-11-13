"""Gemini와 Anthropic의 기본 모델 및 샘플링 요청 정책."""

import re


ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"


def resolve_anthropic_model(model_name: str) -> str:
    """종료된 기존 기본 별칭만 대체하고 사용자가 고른 다른 모델은 유지한다."""
    model = str(model_name or "").strip()
    if model in {"", "claude-3-5-sonnet-latest"}:
        return ANTHROPIC_DEFAULT_MODEL
    return model


def supports_native_sampling(provider: str, model_name: str) -> bool:
    """최신 네이티브 모델에서 거부하거나 무시하는 샘플링 값을 생략한다."""
    if provider == "anthropic":
        return False
    if provider != "gemini":
        return True
    model = str(model_name or "").strip().lower().removeprefix("models/")
    if model.startswith("gemini-") and model.endswith("-latest"):
        return False
    match = re.match(r"^gemini-(\d+)(?:\.(\d+))?(?:-|$)", model)
    if not match:
        return True
    major, minor = int(match[1]), int(match[2] or 0)
    return not (
        major > 3
        or (major == 3 and minor >= 6)
        or (major == 3 and minor == 5 and "flash-lite" in model)
    )


def native_sampling_params(provider: str, model_name: str, params: dict) -> dict:
    if not supports_native_sampling(provider, model_name):
        return {}
    return {"temperature": params["temperature"], "top_p": params["top_p"]}
