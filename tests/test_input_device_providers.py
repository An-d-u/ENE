"""공급자의 실제 최종 요청 경계와 이력 분리를 검증한다."""

import asyncio
from copy import deepcopy
import pytest

from tests import test_http_llm_clients_provider_parity as parity
from tests.http_structured_fixtures import (
    install_client_request_sequence,
    native_final_reply,
    legacy_final_reply,
)
from tests.gemini_structured_fixtures import (
    GeminiHarness,
    FakeChat,
    valid_envelope_json,
)

CASES = [
    (parity._build_task10_openai_chat_client, "_request_openai", True),
    (parity._build_task10_openai_responses_client, "_request_responses", True),
    (parity._build_task10_mistral_client, "_request_openai", False),
    (parity._build_task10_google_client, "_request_google", False),
    (parity._build_task10_cohere_client, "_request_cohere", False),
    (parity._build_task10_anthropic_client, "_request_anthropic", True),
    (parity._build_task10_ollama_client, "_request_ollama", True),
]
MARKER = "[Input device context]"
TEXT = "가상 격자를 세 칸으로 나눕니다."
# 1x1 PNG 합성 이미지.
IMAGE = {
    "dataUrl": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
}


async def empty_memory(*args, **kwargs):
    assert MARKER not in str((args, kwargs))
    return ""


@pytest.mark.parametrize("factory,method,native", CASES)
@pytest.mark.parametrize("mode", ["plain", "memory", "images"])
@pytest.mark.parametrize("device", ["pc", "mobile"])
def test_http_final_input_only(monkeypatch, factory, method, native, mode, device):
    client = factory()
    monkeypatch.setattr(client, "_build_memory_context", empty_memory)
    carrier = native_final_reply() if native else legacy_final_reply()
    records = install_client_request_sequence(
        monkeypatch, client, method, [carrier, carrier]
    )
    if mode == "plain":
        client.send_message(TEXT, request_device=device)
    elif mode == "memory":
        asyncio.run(
            client.send_message_with_memory(
                TEXT, latest_user_message=TEXT, request_device=device
            )
        )
    else:
        asyncio.run(
            client.send_message_with_images(
                TEXT, [deepcopy(IMAGE)], request_device=device
            )
        )
    content = str(records[0].context.user_content)
    assert content.count(MARKER) == 1
    assert ("모바일 앱" if device == "mobile" else "PC") in content
    assert MARKER not in str(client.get_conversation_history())
    assert TEXT in str(client.get_conversation_history())
    client.send_message("가상 격자의 색을 바꿉니다.")
    assert MARKER not in str(records[1].context.user_content)
    assert MARKER not in str(records[1].context.history)


@pytest.mark.parametrize("mode", ["plain", "memory", "images", "invalid_images"])
@pytest.mark.parametrize("device", ["pc", "mobile"])
def test_gemini_final_input_only(monkeypatch, mode, device):
    harness = GeminiHarness(monkeypatch)
    client = harness.client([valid_envelope_json(), valid_envelope_json()])
    monkeypatch.setattr(client, "_build_memory_context", empty_memory)
    captured = []
    original = FakeChat.send_message

    def send(chat, contents, config=None):
        captured.append(str(contents))
        return original(chat, contents, config)

    monkeypatch.setattr(FakeChat, "send_message", send)
    if mode == "plain":
        client.send_message(TEXT, request_device=device)
    elif mode == "memory":
        asyncio.run(
            client.send_message_with_memory(
                TEXT, latest_user_message=TEXT, request_device=device
            )
        )
    else:
        images = [deepcopy(IMAGE)] if mode == "images" else [{"dataUrl": ""}]
        asyncio.run(
            client.send_message_with_images(TEXT, images, request_device=device)
        )
    assert captured[0].count(MARKER) == 1
    assert ("모바일 앱" if device == "mobile" else "PC") in captured[0]
    assert MARKER not in str(client._get_sdk_history(deep_copy=True))
    client.send_message("가상 격자의 색을 바꿉니다.")
    assert MARKER not in captured[1]
    assert MARKER not in str(client._get_sdk_history(deep_copy=True))


def test_http_repair_is_historyless_without_device(monkeypatch):
    client = parity._build_task10_openai_chat_client()
    client.settings["enable_ene_thoughts"] = True
    records = install_client_request_sequence(
        monkeypatch,
        client,
        "_request_openai",
        [native_final_reply(), '{"thought":"가상 도형의 순서를 확인한다."}'],
    )
    client.send_message(TEXT, request_device="mobile")
    assert [record.attempt.phase for record in records] == ["primary", "repair"]
    assert MARKER in records[0].context.user_content
    assert MARKER not in records[1].context.user_content
    assert records[1].context.history == []
    assert MARKER not in str(client.get_conversation_history())


def test_http_failure_then_off_has_no_device(monkeypatch):
    client = parity._build_task10_openai_chat_client()
    records = install_client_request_sequence(
        monkeypatch,
        client,
        "_request_openai",
        [RuntimeError("synthetic"), native_final_reply()],
    )
    with pytest.raises(RuntimeError):
        client.send_message(TEXT, request_device="pc")
    assert client.get_conversation_history() == []
    client.send_message(TEXT)
    assert MARKER not in records[-1].context.user_content


@pytest.mark.parametrize("unsupported", [False, True])
def test_http_internal_retry_keeps_same_device(monkeypatch, unsupported):
    from tests.http_structured_fixtures import explicit_unsupported_error

    client = parity._build_task10_openai_chat_client()
    outcomes = (
        [explicit_unsupported_error(), legacy_final_reply()]
        if unsupported
        else ["not-json", native_final_reply()]
    )
    records = install_client_request_sequence(
        monkeypatch, client, "_request_openai", outcomes
    )
    client.send_message(TEXT, request_device="mobile")
    assert len(records) == 2
    assert records[0].context.user_content == records[1].context.user_content
    assert records[0].context.user_content.count(MARKER) == 1
    assert MARKER not in str(client.get_conversation_history())


def test_gemini_failure_restores_history_and_repair_excludes_device(monkeypatch):
    harness = GeminiHarness(monkeypatch)
    client = harness.client(
        [RuntimeError("synthetic"), valid_envelope_json()],
        repair_responses=['{"thought":"가상 배열의 순서를 확인한다."}'],
        settings={"enable_ene_thoughts": True},
    )
    with pytest.raises(Exception):
        client.send_message(TEXT, request_device="mobile")
    assert MARKER not in str(client._get_sdk_history(deep_copy=True))
    client.send_message(TEXT, request_device="pc")
    assert len(harness.repair_calls) == 1
    assert MARKER not in str(harness.repair_calls)
    assert MARKER not in str(client._get_sdk_history(deep_copy=True))
