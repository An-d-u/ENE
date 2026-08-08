import hashlib

import pytest
import requests

import src.ai.http_llm_common as response_capabilities
from src.ai.http_llm_common import (
    ResponseCapabilityRegistry,
    build_capability_key,
    is_explicit_structured_output_unsupported,
    resolve_response_mode,
)
from src.ai.response_protocol import (
    LIFE_RECORD_SCHEMA_ID,
    LIFE_RECORD_SCHEMA_VERSION,
    LLMRequestKind,
    ProviderProfile,
    ProviderRefusalError,
    RESPONSE_ENVELOPE_SCHEMA_ID,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseMode,
)


class SyntheticErrorResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.json_accessed = False

    def json(self):
        self.json_accessed = True
        return {"error": {"message": self.text}}


def profile(
    provider: str,
    wire_format: str,
    *,
    endpoint: str = "",
    model: str = "synthetic-model",
) -> ProviderProfile:
    return ProviderProfile(
        provider=provider,
        wire_format=wire_format,
        endpoint=endpoint,
        model=model,
    )


def http_error(status_code: int, body: str) -> requests.HTTPError:
    response = SyntheticErrorResponse(status_code, body)
    return requests.HTTPError(
        f"synthetic_http_{status_code}",
        response=response,
    )


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (profile("openai", "openai_responses"), ResponseMode.JSON_SCHEMA),
        (profile("openrouter", "openai_chat"), ResponseMode.JSON_SCHEMA),
        (profile("deepseek", "openai_chat"), ResponseMode.JSON_OBJECT),
        (profile("anthropic", "anthropic"), ResponseMode.JSON_SCHEMA),
        (
            profile(
                "ollama",
                "ollama",
                endpoint="http://127.0.0.1:11434/api/chat",
            ),
            ResponseMode.JSON_SCHEMA,
        ),
    ],
)
def test_named_provider_profiles_choose_conservative_native_modes(
    current,
    expected,
):
    assert resolve_response_mode(current) is expected


@pytest.mark.parametrize(
    ("wire_format", "endpoint", "expected"),
    [
        (
            "openai_responses",
            "https://api.openai.com/v1/responses",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            "openai_chat",
            "https://api.openai.com/v1/chat/completions",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            "openai_chat",
            "https://openrouter.ai/api/v1/chat/completions",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            "openai_chat",
            "https://api.deepseek.com/chat/completions",
            ResponseMode.JSON_OBJECT,
        ),
        (
            "openai_chat",
            "https://api.deepseek.com/beta/chat/completions",
            ResponseMode.STRICT_TOOL,
        ),
        (
            "anthropic",
            "https://api.anthropic.com/v1/messages",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            "ollama",
            "http://[::1]:11434/api/chat",
            ResponseMode.JSON_SCHEMA,
        ),
    ],
)
def test_custom_official_endpoint_profile_reuses_matching_native_mode(
    wire_format,
    endpoint,
    expected,
):
    current = profile(
        "custom_api",
        wire_format,
        endpoint=endpoint,
    )

    assert resolve_response_mode(current) is expected


@pytest.mark.parametrize(
    "wire_format",
    [
        "openai_chat",
        "openai_responses",
        "anthropic",
        "mistral",
        "google_cloud",
        "cohere",
        "ollama",
    ],
)
def test_unknown_custom_endpoint_defaults_to_legacy_for_every_wire_format(
    wire_format,
):
    current = profile(
        "custom_api",
        wire_format,
        endpoint="https://synthetic.invalid/v1/generate",
    )

    assert resolve_response_mode(current) is ResponseMode.LEGACY_TAGS


@pytest.mark.parametrize(
    ("wire_format", "endpoint"),
    [
        (
            "openai_responses",
            "https://api.openai.com.evil.invalid/v1/responses",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/responses/extra",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/responses?mode=redirect",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/responses?",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/responses#fragment",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/responses#",
        ),
        (
            "openai_responses",
            "https://api.openai.com@evil.invalid/v1/responses",
        ),
        (
            "openai_responses",
            "http://api.openai.com/v1/responses",
        ),
        (
            "openai_chat",
            "https://openrouter.ai/api/v1/chat/completions.extra",
        ),
        (
            "anthropic",
            "https://api.anthropic.com/v1/messages?beta=true",
        ),
        (
            "ollama",
            "http://127.0.0.1.evil.invalid:11434/api/chat",
        ),
        (
            "ollama",
            "http://127.0.0.1:11434/api/chat/extra",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/responses/",
        ),
        (
            "openai_responses",
            "not a valid endpoint",
        ),
        (
            "openai_responses",
            " https://api.openai.com/v1/responses",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/responses ",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/respon\nses",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/respon\rses",
        ),
        (
            "openai_responses",
            "https://api.openai.com/v1/respon\tses",
        ),
        (
            "openai_responses",
            "https://api.openai.com:/v1/responses",
        ),
        (
            "ollama",
            "http://127.0.0.1:/api/chat",
        ),
        (
            "ollama",
            "http://[::1]:/api/chat",
        ),
        (
            "ollama",
            "http://127.0.0.1:11434/api/chat?cloud=true",
        ),
        (
            "ollama",
            "http://127.0.0.1:11434/api/chat?",
        ),
    ],
)
def test_official_endpoint_matching_rejects_suffix_path_and_query_attacks(
    wire_format,
    endpoint,
):
    current = profile("custom_api", wire_format, endpoint=endpoint)

    assert resolve_response_mode(current) is ResponseMode.LEGACY_TAGS


@pytest.mark.parametrize(
    ("provider", "wire_format", "endpoint"),
    [
        (
            "custom_api",
            "openai_chat",
            "https://api.openai.com/v1/responses",
        ),
        (
            "openai",
            "openai_responses",
            "https://openrouter.ai/api/v1/chat/completions",
        ),
        (
            "openrouter",
            "openai_chat",
            "https://api.openai.com/v1/chat/completions",
        ),
        (
            "anthropic",
            "anthropic",
            "https://api.openai.com/v1/responses",
        ),
    ],
)
def test_official_endpoint_requires_matching_provider_and_wire_format(
    provider,
    wire_format,
    endpoint,
):
    current = profile(provider, wire_format, endpoint=endpoint)

    assert resolve_response_mode(current) is ResponseMode.LEGACY_TAGS


def test_named_provider_with_non_official_endpoint_uses_legacy():
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://synthetic.invalid/v1/responses",
    )

    assert resolve_response_mode(current) is ResponseMode.LEGACY_TAGS


def test_ollama_cloud_uses_legacy():
    current = profile(
        "ollama",
        "ollama",
        endpoint="https://ollama.com/api/chat",
    )

    assert resolve_response_mode(current) is ResponseMode.LEGACY_TAGS


def test_legacy_setting_forces_legacy_without_probe():
    current = profile("openai", "openai_responses")

    assert (
        resolve_response_mode(current, configured_mode="legacy")
        is ResponseMode.LEGACY_TAGS
    )


def test_invalid_configured_mode_is_rejected():
    current = profile("openai", "openai_responses")

    with pytest.raises(ValueError, match="structured response mode"):
        resolve_response_mode(current, configured_mode="native")


def test_resolver_never_probes_network(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("capability resolver must not use the network")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_if_called)
    candidates = [
        profile("openai", "openai_responses"),
        profile("openrouter", "openai_chat"),
        profile("deepseek", "openai_chat"),
        profile("anthropic", "anthropic"),
        profile(
            "ollama",
            "ollama",
            endpoint="http://localhost:11434/api/chat",
        ),
    ]

    for current in candidates:
        assert resolve_response_mode(current) is not None

    assert (
        resolve_response_mode(
            candidates[0],
            configured_mode="legacy",
        )
        is ResponseMode.LEGACY_TAGS
    )


def test_capability_key_uses_process_local_fingerprint_without_raw_endpoint():
    endpoint = "https://synthetic.invalid/v1/generate?token=synthetic-secret"
    current = profile(
        "custom_api",
        "openai_responses",
        endpoint=endpoint,
    )

    key = build_capability_key(current)
    registry = ResponseCapabilityRegistry()
    registry.mark_legacy(key)

    assert key.endpoint_fingerprint
    assert key.endpoint_fingerprint == build_capability_key(
        current
    ).endpoint_fingerprint
    assert key.endpoint_fingerprint != hashlib.sha256(
        endpoint.encode("utf-8")
    ).hexdigest()
    assert endpoint not in key.endpoint_fingerprint
    assert endpoint not in repr(key)
    assert endpoint not in repr(current)
    assert endpoint not in repr(registry)


def test_capability_key_defaults_to_final_reply_and_life_override_is_isolated():
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )

    final_key = build_capability_key(current)
    life_key = build_capability_key(
        current,
        request_kind=LLMRequestKind.LIFE_RECORD,
        schema_id=LIFE_RECORD_SCHEMA_ID,
        schema_version=LIFE_RECORD_SCHEMA_VERSION,
    )
    registry = ResponseCapabilityRegistry()
    registry.mark_legacy(final_key)

    assert final_key.request_kind is LLMRequestKind.FINAL_REPLY
    assert final_key.schema_id == RESPONSE_ENVELOPE_SCHEMA_ID
    assert final_key.schema_version == RESPONSE_ENVELOPE_SCHEMA_VERSION
    assert life_key.request_kind is LLMRequestKind.LIFE_RECORD
    assert life_key.schema_id == LIFE_RECORD_SCHEMA_ID
    assert life_key.schema_version == LIFE_RECORD_SCHEMA_VERSION
    assert life_key != final_key
    assert registry.resolve(current) is ResponseMode.LEGACY_TAGS
    assert (
        registry.resolve(current, capability_key=life_key)
        is ResponseMode.JSON_SCHEMA
    )


def test_endpoint_fingerprint_changes_when_process_secret_changes(monkeypatch):
    current = profile(
        "custom_api",
        "openai_responses",
        endpoint="https://synthetic.invalid/v1/generate",
    )
    monkeypatch.setattr(
        response_capabilities,
        "_CAPABILITY_ENDPOINT_FINGERPRINT_KEY",
        b"a" * 32,
    )
    first = build_capability_key(current).endpoint_fingerprint

    monkeypatch.setattr(
        response_capabilities,
        "_CAPABILITY_ENDPOINT_FINGERPRINT_KEY",
        b"b" * 32,
    )
    second = build_capability_key(current).endpoint_fingerprint

    assert first != second


def test_endpoint_fingerprint_covers_untrimmed_endpoint_value():
    exact = profile(
        "custom_api",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )
    trailing_space = profile(
        "custom_api",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses ",
    )

    assert build_capability_key(exact) != build_capability_key(trailing_space)


def test_explicit_unknown_schema_parameter_downgrades_by_full_key_and_clear():
    current = profile(
        "custom_api",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )
    same_endpoint_other_provider = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )
    same_endpoint_other_model = profile(
        "custom_api",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
        model="synthetic-model-2",
    )
    registry = ResponseCapabilityRegistry()
    key = build_capability_key(current)

    assert is_explicit_structured_output_unsupported(
        http_error(400, "unknown parameter: response_format.json_schema")
    )
    registry.mark_legacy(key)

    assert registry.resolve(current) is ResponseMode.LEGACY_TAGS
    assert (
        registry.resolve(same_endpoint_other_provider)
        is ResponseMode.JSON_SCHEMA
    )
    assert (
        registry.resolve(same_endpoint_other_model)
        is ResponseMode.JSON_SCHEMA
    )
    assert (
        registry.resolve(current, schema_version="2")
        is ResponseMode.JSON_SCHEMA
    )

    registry.clear()
    assert registry.resolve(current) is ResponseMode.JSON_SCHEMA


def test_capability_cache_separates_wire_format_and_endpoint_fingerprint():
    base = profile(
        "custom_api",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )
    changed_wire = profile(
        "custom_api",
        "openai_chat",
        endpoint="https://api.openai.com/v1/responses",
    )
    base_key = build_capability_key(base)
    changed_wire_key = build_capability_key(changed_wire)
    registry = ResponseCapabilityRegistry()
    registry.mark_legacy(base_key)

    assert base_key != changed_wire_key
    assert base_key.wire_format != changed_wire_key.wire_format
    assert (
        base_key.endpoint_fingerprint
        == changed_wire_key.endpoint_fingerprint
    )
    assert registry.resolve(base) is ResponseMode.LEGACY_TAGS
    assert repr(registry) == "ResponseCapabilityRegistry(legacy_overrides=1)"
    registry.clear()
    registry.mark_legacy(changed_wire_key)
    assert registry.resolve(base) is ResponseMode.JSON_SCHEMA
    assert repr(registry) == "ResponseCapabilityRegistry(legacy_overrides=1)"
    registry.clear()
    assert repr(registry) == "ResponseCapabilityRegistry(legacy_overrides=0)"

    first_endpoint = profile(
        "deepseek",
        "openai_chat",
        endpoint="https://api.deepseek.com/chat/completions",
    )
    second_endpoint = profile(
        "deepseek",
        "openai_chat",
        endpoint="https://api.deepseek.com/v1/chat/completions",
    )
    first_key = build_capability_key(first_endpoint)
    second_key = build_capability_key(second_endpoint)

    assert first_key.endpoint_fingerprint != second_key.endpoint_fingerprint
    registry.clear()
    registry.mark_legacy(first_key)
    assert registry.resolve(first_endpoint) is ResponseMode.LEGACY_TAGS
    assert registry.resolve(second_endpoint) is ResponseMode.JSON_OBJECT


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (400, "unknown parameter: response_format.json_schema"),
        (404, "unsupported parameter: text.format"),
        (422, "unknown field 'output_config.format'"),
        (400, "response_format is unsupported"),
        (400, "parameter 'response_format' is not supported"),
        (400, 'field "output_config.format" is unsupported'),
        (400, "unknown field: response_format."),
        (400, "unsupported parameter: text.format."),
        (400, '"response_format" is not supported'),
        (400, "The model does not support response_format"),
        (400, "Model synthetic-v1 does not support response_format"),
        (400, "The model does not support the response_format parameter"),
        (400, "Model 'synthetic-v1' does not support response_format"),
        (400, 'Model "synthetic-v1" does not support response_format'),
        (400, "Model `synthetic-v1` does not support response_format"),
        (400, "unknown field: response_format.type"),
        (400, "unknown field: text.format.type"),
        (400, "unknown field: output_config.format.schema"),
        (400, "unknown parameter: response_json_schema"),
        (400, "invalid schema; unknown parameter: response_format"),
        (400, "unknown field: response_format.json_schema.strict"),
        (400, "unknown field: response_format.json_schema.schema"),
        (400, "unknown field: response_format.json_schema.name"),
        (400, "unknown field: text.format.strict"),
        (400, "unknown field: text.format.schema"),
        (400, "unknown field: text.format.name"),
        (400, "unknown field: output_config.format.type"),
    ],
)
def test_direct_structured_parameter_errors_are_explicitly_unsupported(
    status_code,
    body,
):
    assert is_explicit_structured_output_unsupported(
        http_error(status_code, body)
    )


def test_openai_invalid_response_format_parameter_not_supported_is_explicit():
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(
            400,
            "Invalid parameter: response_format is not supported with this model.",
        ),
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    )


@pytest.mark.parametrize(
    "body",
    [
        "Invalid parameter: response_format of type json_schema is not supported with this model.",
        "Invalid parameter: 'response_format' of type 'json_schema' is not supported with this model.",
        'Invalid parameter: "response_format" of type "json_schema" is not supported with this model.',
        "This model does not support response_format parameter.",
        "Invalid parameter: response_format. This parameter is not supported with this model.",
    ],
)
def test_openai_direct_response_format_not_supported_variants_are_explicit(body):
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(400, body),
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    )


@pytest.mark.parametrize(
    "type_name",
    ["json_schema", "'json_schema'", '"json_schema"', "`json_schema`"],
)
def test_openai_response_format_bounded_type_modifier_is_explicit(type_name):
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(
            400,
            f"Invalid parameter: response_format of type {type_name} is not supported.",
        ),
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    )


def test_deepseek_json_object_type_modifier_is_explicit():
    current = profile("deepseek", "openai_chat")

    assert is_explicit_structured_output_unsupported(
        http_error(
            400,
            "Invalid parameter: 'response_format' of type 'json_object' is not supported.",
        ),
        profile=current,
        response_mode=ResponseMode.JSON_OBJECT,
    )


@pytest.mark.parametrize("type_name", ["xml", "'arbitrary_type'", '"json"'])
def test_response_format_arbitrary_type_modifier_is_not_explicit(type_name):
    assert not is_explicit_structured_output_unsupported(
        http_error(
            400,
            f"Invalid parameter: response_format of type {type_name} is not supported.",
        ),
        profile=profile("openai", "openai_responses"),
        response_mode=ResponseMode.JSON_SCHEMA,
    )


def test_official_openrouter_404_without_structured_route_is_explicit():
    current = profile(
        "openrouter",
        "openai_chat",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(
            404,
            '{"error":{"message":"No endpoints found that support the requested parameters."}}',
        ),
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    )


@pytest.mark.parametrize(
    ("current", "status_code", "body", "response_mode"),
    [
        (
            profile(
                "openai",
                "openai_chat",
                endpoint="https://openrouter.ai/api/v1/chat/completions",
            ),
            404,
            "No endpoints found that support the requested parameters.",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            profile(
                "openrouter",
                "openai_chat",
                endpoint="https://openrouter.ai/api/v1/chat/completions",
            ),
            429,
            "No endpoints found that support the requested parameters.",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            profile(
                "openrouter",
                "openai_chat",
                endpoint="https://openrouter.ai/api/v1/chat/completions",
            ),
            503,
            "No endpoints found that support the requested parameters.",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            profile(
                "openrouter",
                "openai_chat",
                endpoint="https://openrouter.ai/api/v1/chat/completions",
            ),
            404,
            "No endpoints found.",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            profile(
                "openrouter",
                "openai_chat",
                endpoint="https://openrouter.ai/api/v1/chat/completions",
            ),
            404,
            "No endpoints found that support the requested parameters: schema validation failed.",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            profile(
                "openrouter",
                "openai_chat",
                endpoint="https://synthetic.invalid/v1/chat/completions",
            ),
            404,
            "No endpoints found that support the requested parameters.",
            ResponseMode.JSON_SCHEMA,
        ),
        (
            profile(
                "openrouter",
                "openai_chat",
                endpoint="https://openrouter.ai/api/v1/chat/completions",
            ),
            404,
            "No endpoints found that support the requested parameters.",
            ResponseMode.JSON_OBJECT,
        ),
    ],
)
def test_openrouter_route_absence_requires_exact_official_404_boundary(
    current,
    status_code,
    body,
    response_mode,
):
    assert is_explicit_structured_output_unsupported(
        http_error(status_code, body),
        profile=current,
        response_mode=response_mode,
    ) is False


@pytest.mark.parametrize(
    "body",
    [
        r'{"message":"\"response_format\" is not supported"}',
        r'{"error":{"message":"\"response_format\" is not supported"}}',
        r'{"error":"\"response_format\" is not supported"}',
        r'{"message":"Model \"synthetic-v1\" does not support response_format"}',
        r'{"message":"Model \"model@prod\" does not support response_format"}',
        r'{"message":"Model model@prod does not support response_format"}',
        r'{"message":"Model model+prod does not support response_format"}',
    ],
)
def test_json_message_escaped_quotes_are_matched_locally(body):
    assert is_explicit_structured_output_unsupported(http_error(400, body))


@pytest.mark.parametrize(
    "body",
    [
        r'{"detail":"unknown parameter: response_format"}',
        r'{"error":{"detail":"unknown field: response_format"}}',
    ],
)
def test_json_exact_error_detail_fields_are_matched(body):
    assert is_explicit_structured_output_unsupported(http_error(400, body))


@pytest.mark.parametrize(
    "body",
    [
        "(response_format) is unsupported",
        "response_format: unsupported",
        "The response_format parameter is not supported.",
        r'{"message":"(response_format) is unsupported"}',
        r'{"message":"response_format: unsupported"}',
        r'{"message":"The response_format parameter is not supported."}',
        "Error: response_format is unsupported",
        "API error: response_format is unsupported",
        "Request error: response_format is unsupported",
        "Bad request: response_format is unsupported",
        "Bad request: parameter response_format is not supported",
        "\ufeffresponse_format is unsupported",
    ],
)
def test_anchored_parameter_assertion_allows_bounded_punctuation(body):
    assert is_explicit_structured_output_unsupported(http_error(400, body))


def test_json_message_quoted_model_format_error_requires_native_context():
    current = profile(
        "ollama",
        "ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(
            400,
            r'{"message":"Model \"synthetic-v1\" does not support format"}',
        ),
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    )


@pytest.mark.parametrize(
    "body",
    [
        "unknown field: format",
        "unknown field: format.",
        "Model synthetic-v1 does not support format for schema-constrained output",
        r'{"error":{"message":"unknown field: format for schema output"}}',
        r'{"error":{"message":"unknown field: format"}}',
        "invalid schematic: unknown field: format",
        r'{"schema_error":"x","message":"unknown field: format"}',
        "invalid fooschema: unknown field: format",
        "schema_error metadata: unknown field: format",
        "validation_state schema: unknown field: format",
        "schema invalid_state: unknown field: format",
        "schema validated successfully: unknown field: format",
        "unsupported_schema property: unknown field: format",
        "unsupported-schema-property: unknown field: format",
    ],
)
def test_ollama_format_errors_require_matching_native_context(body):
    current = profile(
        "ollama",
        "ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(400, body),
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    )


@pytest.mark.parametrize(
    "body",
    [
        "unknown parameter: tool_choice",
        "unsupported parameter: tools",
        "unknown field: strict",
        "unknown parameter: tool_choice for schema-constrained output",
    ],
)
def test_strict_tool_errors_require_matching_mode_context(body):
    current = profile(
        "deepseek",
        "openai_chat",
        endpoint="https://api.deepseek.com/beta/chat/completions",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(400, body),
        profile=current,
        response_mode=ResponseMode.STRICT_TOOL,
    )


@pytest.mark.parametrize(
    "body",
    [
        "unknown field: format",
        "unsupported parameter: tools",
        "unknown field: strict",
        "unknown parameter: tool_choice",
    ],
)
def test_contextual_parameters_without_attempt_context_never_downgrade(body):
    assert is_explicit_structured_output_unsupported(
        http_error(400, body)
    ) is False


@pytest.mark.parametrize(
    "body",
    [
        "unknown field: format",
        "unsupported parameter: tools",
        "unknown field: strict",
        "unknown parameter: tool_choice",
    ],
)
def test_contextual_parameters_in_other_mode_never_downgrade(body):
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )

    assert is_explicit_structured_output_unsupported(
        http_error(400, body),
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    ) is False


@pytest.mark.parametrize(
    "failure",
    [
        http_error(429, "unknown parameter: response_format"),
        requests.Timeout("synthetic_timeout"),
        http_error(503, "unknown field: output_config.format"),
        ProviderRefusalError(),
        ValueError("malformed_output"),
        ValueError("invalid_schema"),
    ],
)
def test_transient_refusal_and_content_failures_never_downgrade(failure):
    assert is_explicit_structured_output_unsupported(failure) is False


@pytest.mark.parametrize(
    "body",
    [
        "invalid schema for response_format.json_schema",
        "unsupported schema keyword in response_format.json_schema",
        "response_format contains unsupported schema property",
        "malformed JSON returned for response_format",
        "provider refusal while using response_format",
        "unknown parameter: temperature",
        "unsupported model field",
        "unsupported image format",
        "unsupported strict safety policy",
        "unknown parameter: response_formatting",
        "unknown parameter: response_format_extra",
        "unsupported parameter: response_schema_extra",
        "unknown parameter: response_format.other",
        "unsupported field: output_config.temperature",
        "unknown field: text.format.other",
        "unknown parameter: response_format[other]",
        "unknown field: response_format/other",
        "unsupported parameter: response_format-other",
        "unknown field: response_json_schema.other",
        "unknown field: response_format.json_schema.type",
        "unknown field: reply",
        "Model probably does not support response_format",
        "API documentation does not support response_format examples",
        'If "response_format" is unsupported, use legacy tags',
        "Check whether response_format is unsupported",
        "It is possible that the model does not support response_format",
        r'{"message":"If \"response_format\" is unsupported, use legacy tags"}',
        "If (response_format) is unsupported, use legacy tags",
        "Check whether response_format: unsupported",
        "response_format may be unsupported",
        "response_format probably is unsupported",
        r'\"response_format\" is not supported',
        r'{"message":"validation failed","diagnostic":"{\"message\":\"response_format is unsupported\"}"}',
        "If unknown parameter: response_format, use legacy tags",
        "Check whether unknown field: response_format is returned",
        "It may report unsupported parameter: response_format",
        "This may be an unknown parameter: response_format",
        "This might report unknown field: response_format",
        "There could be unsupported parameter: response_format",
        "This is not an unknown parameter: response_format",
        "No unknown parameter: response_format was returned",
        "Not an unsupported field: response_format",
        "Possibly unknown parameter: response_format",
        "Probably unsupported field: response_format",
        "Perhaps unknown parameter: response_format",
        "Maybe unsupported parameter: response_format",
        "For example, unknown field: response_format",
        "Example: unknown parameter: response_format",
        "The API documentation says unknown parameter: response_format",
        "Documentation example: unknown parameter: response_format",
        "docs example: unsupported field: response_format",
        r'{"message":"If unknown parameter: response_format, use tags"}',
        r'{"diagnostic":"unknown parameter: response_format"}',
        "\ufeff" r'{"diagnostic":"unknown parameter: response_format"}',
        r'{"diagnostic":"unknown parameter: response_format"',
        r'[{"message":"unknown parameter: response_format"}]',
        "Error: If unknown parameter: response_format, use tags",
        r'{"detail":"If unknown parameter: response_format, use tags"}',
        r'{"error":{"detail":"Documentation example: unknown field: response_format"}}',
        r'{"detail":{"message":"unknown parameter: response_format"}}',
        r'{"error":{"detail":{"message":"unknown parameter: response_format"}}}',
        r'{"message":"unknown parameter: response_format"',
    ],
)
def test_non_capability_400_errors_never_downgrade(body):
    assert is_explicit_structured_output_unsupported(
        http_error(400, body)
    ) is False


@pytest.mark.parametrize(
    "body",
    [
        "invalid schema: unknown field: format",
        "malformed schema: unknown field: format",
        "schema validation failed: unknown field: format",
        "schema is invalid: unknown field: format",
        "schema failed validation: unknown field: format",
        "invalid response schema: unknown field: format",
        "invalid_schema: unknown field: format",
        "response_schema is invalid: unknown field: format",
        "validation failed for schema: unknown field: format",
        "failed to validate schema: unknown field: format",
        "failed to validate response_schema: unknown field: format",
        "schema failed to validate: unknown field: format",
        "schema mismatch: unknown field: format",
        "schema error: unknown field: format",
        "error in schema: unknown field: format",
        "schema rejected: unknown field: format",
        "Could not parse schema: unknown field: format",
        "Cannot parse schema: unknown field: format",
        "Failed to parse schema: unknown field: format",
        "error validating schema: unknown field: format",
        "unsupported schema keyword: unknown field: format",
        "unsupported schema feature: unknown field: format",
        "Unable to parse schema: unknown field: format",
        "Failed parsing the schema: unknown field: format",
        "The schema could not be parsed: unknown field: format",
        "schema is not valid: unknown field: format",
        "the schema has an error: unknown field: format",
        "unsupported schema property: unknown field: format",
        "unsupported keyword in schema: unknown field: format",
        "schema feature is unsupported: unknown field: format",
        "schema violates a constraint: unknown field: format",
        "constraint was violated by schema: unknown field: format",
    ],
)
def test_schema_validation_context_never_marks_capability_legacy(body):
    current = profile(
        "ollama",
        "ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
    )
    registry = ResponseCapabilityRegistry()
    failure = http_error(400, body)

    unsupported = is_explicit_structured_output_unsupported(
        failure,
        profile=current,
        response_mode=ResponseMode.JSON_SCHEMA,
    )
    if unsupported:
        registry.mark_legacy(build_capability_key(current))

    assert unsupported is False
    assert registry.resolve(current) is ResponseMode.JSON_SCHEMA


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("unknown parameter: response_format"),
        requests.HTTPError("unknown parameter: response_format"),
        requests.HTTPError(
            "unknown parameter: response_format",
            response=SyntheticErrorResponse(400, "synthetic unrelated body"),
        ),
        http_error(401, "unknown parameter: response_format"),
        http_error(403, "unsupported parameter: output_config.format"),
    ],
)
def test_only_http_response_status_and_body_can_prove_explicit_unsupported(
    failure,
):
    assert is_explicit_structured_output_unsupported(failure) is False


def test_classifier_reads_response_text_without_parsing_json():
    response = SyntheticErrorResponse(
        400,
        "unknown parameter: response_format.json_schema",
    )
    failure = requests.HTTPError(
        "synthetic_http_400",
        response=response,
    )

    assert is_explicit_structured_output_unsupported(failure) is True
    assert response.json_accessed is False


def test_explicit_unsupported_body_is_not_persisted_or_logged(caplog):
    raw_body = (
        "unknown parameter: response_format.json_schema; "
        "synthetic private diagnostic"
    )
    failure = http_error(400, raw_body)
    current = profile(
        "openai",
        "openai_responses",
        endpoint="https://api.openai.com/v1/responses",
    )
    registry = ResponseCapabilityRegistry()
    key = build_capability_key(current)

    assert is_explicit_structured_output_unsupported(failure) is True
    registry.mark_legacy(key)

    assert raw_body not in caplog.text


def test_openrouter_legacy_override_isolated_by_full_capability_key():
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    current = profile(
        "openrouter",
        "openai_chat",
        endpoint=endpoint,
        model="synthetic-model-a",
    )
    other_provider = profile(
        "custom_api",
        "openai_chat",
        endpoint=endpoint,
        model="synthetic-model-a",
    )
    other_endpoint_identity = profile(
        "openrouter",
        "openai_chat",
        endpoint="https://OPENROUTER.ai/api/v1/chat/completions",
        model="synthetic-model-a",
    )
    other_model = profile(
        "openrouter",
        "openai_chat",
        endpoint=endpoint,
        model="synthetic-model-b",
    )
    registry = ResponseCapabilityRegistry()
    current_key = build_capability_key(current)

    registry.mark_legacy(current_key)

    assert registry.resolve(current) is ResponseMode.LEGACY_TAGS
    assert registry.resolve(other_provider) is ResponseMode.JSON_SCHEMA
    assert registry.resolve(other_endpoint_identity) is ResponseMode.JSON_SCHEMA
    assert registry.resolve(other_model) is ResponseMode.JSON_SCHEMA
    assert (
        registry.resolve(current, schema_version="2")
        is ResponseMode.JSON_SCHEMA
    )
    assert build_capability_key(other_provider) != current_key
    assert build_capability_key(other_endpoint_identity) != current_key
    assert build_capability_key(other_model) != current_key
    assert build_capability_key(current, schema_version="2") != current_key
