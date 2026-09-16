"""미디어 계약의 공통 사례와 협상·세대·방향 경계를 검증한다."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.core.companion.extension_protocol import (
    ExtensionContext,
    negotiate,
    validate_extension,
)
from src.core.companion.protocol import ProtocolError, decode_message, encode_message


CASES = json.loads(
    (
        Path(__file__).resolve().parents[1] / "contracts/companion/v1/media_cases.json"
    ).read_text(encoding="utf-8")
)["cases"]
SAMPLES = {
    item["message"]["type"]: item["message"]
    for item in CASES
    if item["name"].endswith("_정상")
}
CONTEXT = ExtensionContext(
    1,
    SAMPLES["audio_offer"]["server_epoch"],
    SAMPLES["audio_offer"]["connection_generation"],
    SAMPLES["audio_offer"]["conversation_id"],
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_contract(case):
    raw = json.dumps(case["message"], ensure_ascii=False)
    if "error" in case:
        with pytest.raises(ProtocolError) as failure:
            decode_message(raw)
        assert failure.value.code == case["error"]
        assert str(failure.value) == case["error"]
    else:
        assert json.loads(encode_message(decode_message(raw))) == case["expected"]


def test_capability_intersection_dependency_and_default_disabled():
    assert negotiate(["audio_pcm_v1"]) == ()
    assert (
        negotiate(["character_controls_v1"], ["character_controls_v1", "character_v1"])
        == ()
    )
    assert set(
        negotiate(["audio_pcm_v1", "unknown", "character_v1"], ["audio_pcm_v1"])
    ) == {"audio_pcm_v1"}


@pytest.mark.parametrize(
    "changes",
    [
        {"registration_generation": 2},
        {"connection_generation": "00000000-0000-4000-8000-000000000099"},
        {"server_epoch": "00000000-0000-4000-8000-000000000099"},
        {"conversation_id": "00000000-0000-4000-8000-000000000099"},
    ],
)
def test_stale_extensions_do_not_pass_generation_guard(changes):
    message = decode_message(json.dumps(SAMPLES["audio_progress"]))
    with pytest.raises(ProtocolError, match="stale_extension"):
        validate_extension(
            message,
            replace(CONTEXT, **changes),
            {"audio_pcm_v1"},
            direction="from_phone",
            sample_rate=24000,
        )


def test_unnegotiated_wrong_direction_and_rate_specific_frames_are_rejected():
    message = decode_message(json.dumps(SAMPLES["audio_prepared"]))
    with pytest.raises(ProtocolError, match="extension_not_negotiated"):
        validate_extension(message, CONTEXT, set(), direction="from_phone")
    with pytest.raises(ProtocolError, match="unsupported_command"):
        validate_extension(message, CONTEXT, {"audio_pcm_v1"}, direction="from_pc")
    message = decode_message(
        json.dumps({**SAMPLES["audio_prepared"], "buffered_frames": 32001})
    )
    with pytest.raises(ProtocolError):
        validate_extension(
            message, CONTEXT, {"audio_pcm_v1"}, direction="from_phone", sample_rate=8000
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "\ud800"])
def test_invalid_finite_and_unicode_values_are_safe_errors(value):
    with pytest.raises(ProtocolError) as failure:
        decode_message(json.dumps({**SAMPLES["audio_progress"], "mouth_open": value}))
    assert str(failure.value) == failure.value.code


def test_control_patch_and_parameter_limits_before_unknown_field_removal():
    for kind, size in [
        ("audio_progress", 2048),
        ("head_pat", 2048),
        ("character_settings_patch", 49152),
    ]:
        with pytest.raises(ProtocolError, match="message_too_large"):
            decode_message(json.dumps({**SAMPLES[kind], "ignored": "x" * size}))
    with pytest.raises(ProtocolError):
        decode_message(
            json.dumps(
                {
                    **SAMPLES["character_settings_patch"],
                    "parameters": {f"Param{index}": 0 for index in range(257)},
                }
            )
        )


def test_extension_does_not_change_transcript_sequence_or_revision():
    from src.core.companion.transcript import CurrentConversationTranscript

    transcript = CurrentConversationTranscript()
    before = transcript.capture()
    message = decode_message(json.dumps(SAMPLES["audio_progress"]))
    validate_extension(
        message, CONTEXT, {"audio_pcm_v1"}, direction="from_phone", sample_rate=24000
    )
    after = transcript.capture()
    assert (before.event_seq, before.conversation_revision) == (
        after.event_seq,
        after.conversation_revision,
    )
    assert "event_seq" not in message.to_dict()


def test_huge_integer_is_a_safe_error_not_float_conversion_overflow():
    with pytest.raises(ProtocolError):
        decode_message(json.dumps({**SAMPLES["audio_progress"], "mouth_open": 10**400}))
