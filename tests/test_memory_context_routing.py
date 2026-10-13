"""모든 내장 제공자가 구조화 화자 문맥을 공통 빌더까지 전달한다."""

import asyncio
from types import SimpleNamespace
import pytest

from src.ai.http_llm_clients import (AnthropicClient, CohereClient, GoogleCloudClient, MistralClient,
                                     OllamaClient, OpenAICompatibleClient, OpenAIResponseAPIClient)
from src.ai.llm_client import GeminiClient


class ReachedBuilder(BaseException):
    pass


@pytest.mark.parametrize("client_type", [GeminiClient, AnthropicClient, CohereClient, GoogleCloudClient,
                                        MistralClient, OllamaClient, OpenAICompatibleClient, OpenAIResponseAPIClient])
@pytest.mark.parametrize("images", [False, True])
def test_public_entrypoints_forward_roles_and_request_identity(monkeypatch, client_type, images):
    client = client_type.__new__(client_type)
    client._begin_response_turn_usage = lambda: None
    client._finish_response_turn_usage = lambda: None
    received = []
    async def builder(_client, query, **kwargs):
        received.append((query, kwargs))
        raise ReachedBuilder()
    module = "src.ai.llm_client" if client_type is GeminiClient else "src.ai.http_llm_common"
    monkeypatch.setattr(module + ".build_common_memory_context", builder)
    messages = [dict(turn_id="turn-synthetic", role="user", text="종이 돛을 접는다.", timestamp="2025-01-01")]
    method = client.send_message_with_images if images else client.send_message_with_memory
    args = ["그건 어떤 모양이었지?", []] if images else ["그건 어떤 모양이었지?"]
    with pytest.raises(ReachedBuilder):
        asyncio.run(method(*args, recent_memory_messages=messages, memory_request_id="request-synthetic"))
    assert received[0][1]["recent_memory_messages"] == messages
    assert received[0][1]["memory_request_id"] == "request-synthetic"


def test_search_snapshot_preserves_user_role_and_respects_disabled_context():
    from src.core.bridge_mixins.chat_flow import ChatFlowBridgeMixin
    bridge = SimpleNamespace(conversation_buffer=[("assistant", "조수만 말한 대상", "2025-01-02")],
                             _summarized_recent_context=[("user", "이전 사용자 대상", "2025-01-01")],
                             _resolve_memory_search_turns=lambda: 3)
    values = ChatFlowBridgeMixin._build_memory_search_inputs(bridge, "그건 어디에?")
    assert [message["role"] for message in values["recent_memory_messages"]] == ["user", "assistant"]
    assert len({message["turn_id"] for message in values["recent_memory_messages"]}) == 2
    assert values["memory_request_id"]
    bridge._resolve_memory_search_turns = lambda: 0
    assert ChatFlowBridgeMixin._build_memory_search_inputs(bridge, "그건 어디에?")["recent_memory_messages"] == []
