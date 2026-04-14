import asyncio
import sys
import types

google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.core.bridge import WebBridge  # noqa: E402


class _DummyMemoryManager:
    def __init__(self):
        self.calls = []

    async def add_summary(self, **kwargs):
        self.calls.append(kwargs)


class _DummyLLMClient:
    async def summarize_conversation(self, messages):
        return (
            "summary",
            [],
            [],
            {
                "memory_type": "task",
                "importance_reason": "repeated_topic",
                "confidence": 0.81,
                "entity_names": ["ENE"],
            },
        )

    def clear_context(self):
        return None


def test_auto_summarize_persists_structured_original_messages():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "hello", "2026-04-14 20:00"),
        ("assistant", "hi", "2026-04-14 20:01"),
        ("user", "remember this", "2026-04-14 20:02"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _DummyLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = None
    dummy._create_memory_conversation_id = lambda messages: "conv-test-1"

    asyncio.run(WebBridge._auto_summarize(dummy))

    assert dummy.memory_manager.calls[0]["original_messages"] == [
        {
            "role": "user",
            "text": "hello",
            "timestamp": "2026-04-14 20:00",
            "conversation_id": "conv-test-1",
            "turn_index": 0,
        },
        {
            "role": "assistant",
            "text": "hi",
            "timestamp": "2026-04-14 20:01",
            "conversation_id": "conv-test-1",
            "turn_index": 1,
        },
        {
            "role": "user",
            "text": "remember this",
            "timestamp": "2026-04-14 20:02",
            "conversation_id": "conv-test-1",
            "turn_index": 2,
        },
    ]
