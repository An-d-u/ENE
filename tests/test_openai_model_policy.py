from src.ai.openai_model_policy import (
    OPENAI_REASONING_EFFORTS,
    normalize_reasoning_effort,
    resolve_openai_model_policy,
)


def test_official_openai_gpt_5_6_uses_reasoning_policy():
    policy = resolve_openai_model_policy(" OpenAI ", " GPT-5.6-SOL ")
    assert policy.supports_temperature is False
    assert policy.supports_top_p is False
    assert policy.supports_reasoning_effort is True
    assert policy.default_reasoning_effort == "low"
    assert policy.allowed_reasoning_efforts == OPENAI_REASONING_EFFORTS


def test_official_openai_gpt_5_6_family_boundaries_match():
    for model_name in ("gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        policy = resolve_openai_model_policy("openai", model_name)
        assert policy.supports_reasoning_effort is True


def test_official_openai_o_series_uses_reasoning_policy():
    for model_name in (
        "o1",
        "o1-mini",
        "o1-2024-12-17",
        "o3",
        "o3-mini",
        "o3-2025-01-31",
        "o4",
        "o4-mini",
        "o4-2026-08-08",
    ):
        policy = resolve_openai_model_policy("openai", model_name)
        assert policy.supports_temperature is False
        assert policy.supports_top_p is False
        assert policy.supports_reasoning_effort is True
        assert policy.default_reasoning_effort == "low"
        assert policy.allowed_reasoning_efforts == OPENAI_REASONING_EFFORTS


def test_o_series_policy_requires_official_provider_and_exact_family_boundary():
    for provider, model_name in (
        ("openrouter", "o3-mini"),
        ("custom_api", "o4"),
        ("openai", "vendor/o3-mini"),
        ("openai", "o3preview"),
        ("openai", "o-3"),
    ):
        policy = resolve_openai_model_policy(provider, model_name)
        assert policy.supports_temperature is True
        assert policy.supports_top_p is True
        assert policy.supports_reasoning_effort is False


def test_policy_does_not_match_similar_or_custom_models():
    for provider, model_name in (
        ("openai", "gpt-5.60"),
        ("openai", "vendor/gpt-5.6-sol"),
        ("custom_api", "gpt-5.6-sol"),
        ("gemini", "gpt-5.6"),
    ):
        policy = resolve_openai_model_policy(provider, model_name)
        assert policy.supports_temperature is True
        assert policy.supports_top_p is True
        assert policy.supports_reasoning_effort is False


def test_reasoning_effort_normalization_uses_low_for_invalid_values():
    assert normalize_reasoning_effort(" XHIGH ") == "xhigh"
    assert normalize_reasoning_effort("unsupported") == "low"
    assert normalize_reasoning_effort(None) == "low"
