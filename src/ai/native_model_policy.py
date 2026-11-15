"""선택 모델의 화면 입력 지원과 네이티브 공급자의 요청 정책."""

import re


ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"

# 일반 대화 API에서 이미지 입력과 텍스트 출력을 함께 지원하는 모델 ID만 허용한다.
# 공급자 공식 모델 목록과 OpenRouter의 모델별 입력 형식을 기준으로 갱신한다.
_SCREEN_MODELS = {
    "gemini": {
        "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
        "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite",
        "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash",
        "gemini-4-carbon", "gemini-4-argon", "gemini-4-hydrogen",
    },
    "openai": {
        "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
        "o1", "o1-pro", "o3", "o4-mini",
        "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.1", "gpt-5.2", "gpt-5.2-pro",
        "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.4-pro", "gpt-5.5", "gpt-5.5-pro",
        "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra", "gpt-6-sol",
        "gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-terra",
    },
    "anthropic": {
        ANTHROPIC_DEFAULT_MODEL, "claude-sonnet-4-5", "claude-haiku-4-5", "claude-haiku-4-5-20251001",
        "claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8",
        "claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-fable-5-1", "claude-fable-5-2",
        "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
    },
    "openrouter": {
        "openai/gpt-4o-mini", "openai/gpt-4o", "openai/gpt-4.1", "openai/gpt-4.1-mini",
        "google/gemini-2.5-flash", "google/gemini-2.5-pro", "google/gemini-3.8-flash",
        "anthropic/claude-sonnet-4.6", "anthropic/claude-opus-4.6",
    },
}


def supports_screen_model(provider: str, model_name: str) -> bool:
    """자유 입력 별칭, 자동 라우팅 및 미확인 모델은 화면 전송 전에 제외한다."""
    model = str(model_name or "").strip()
    if provider == "gemini":
        model = model.removeprefix("models/")
    return model in _SCREEN_MODELS.get(provider, ())


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
