import asyncio
import sys
import types

google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.ai.llm_client import GeminiClient
from src.core.bridge import WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _DummyMemoryManager:
    def __init__(self):
        self.calls = []

    async def add_summary(
        self,
        summary,
        original_messages,
        is_important=False,
        tags=None,
        source="chat",
        memory_type="general",
        importance_reason=None,
        confidence=0.5,
        entity_names=None,
    ):
        self.calls.append(
            {
                "summary": summary,
                "original_messages": list(original_messages),
                "is_important": is_important,
                "tags": list(tags or []),
                "source": source,
                "memory_type": memory_type,
                "importance_reason": importance_reason,
                "confidence": confidence,
                "entity_names": list(entity_names or []),
            }
        )


class _DummyLLMClient:
    def __init__(self):
        self.summarize_calls = []
        self.clear_context_calls = 0
        self.rebuild_calls = []

    async def summarize_conversation(self, messages):
        self.summarize_calls.append(list(messages))
        return "압축된 요약", [], ["[speaking_style] 짧고 단정한 말투를 유지한다."], {
            "memory_type": "task",
            "importance_reason": "repeated_topic",
            "confidence": 0.81,
            "entity_names": ["ENE"],
        }

    def clear_context(self):
        self.clear_context_calls += 1

    def rebuild_context_from_conversation(self, conversation_buffer):
        self.rebuild_calls.append(list(conversation_buffer))
        return True


def test_auto_summarize_clears_llm_chat_context_after_persisting_summary():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "안녕", "2026-03-24 10:00"),
        ("assistant", "안녕하세요", "2026-03-24 10:01"),
        ("user", "오늘 일정 알려줘", "2026-03-24 10:02"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _DummyLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = _DummyEneProfile()

    asyncio.run(WebBridge._auto_summarize(dummy))

    assert dummy.memory_manager.calls == [
        {
            "summary": "압축된 요약",
            "original_messages": ["안녕", "안녕하세요", "오늘 일정 알려줘"],
            "is_important": False,
            "tags": [],
            "source": "chat",
            "memory_type": "task",
            "importance_reason": "repeated_topic",
            "confidence": 0.81,
            "entity_names": ["ENE"],
        }
    ]
    assert dummy.ene_profile.calls == [
        {
            "content": "[speaking_style] 짧고 단정한 말투를 유지한다.",
            "category": "fact",
            "source": "대화 요약 (2026-03-24 10:02)",
            "origin": "auto",
            "auto_update": True,
            "confidence": None,
        }
    ]
    assert dummy.llm_client.clear_context_calls == 1
    assert dummy.conversation_buffer == []


class _Fact:
    def __init__(self, category, content, timestamp):
        self.category = category
        self.content = content
        self.timestamp = timestamp


class _DummyProfile:
    basic_info = {}
    preferences = {}

    def __init__(self, facts):
        self._facts = facts

    def get_all_facts(self):
        return list(self._facts)


class _DummyEneProfile:
    def __init__(self):
        self.calls = []
        self.core_profile = {
            "identity": ["에네는 차분한 동반자다."],
            "speaking_style": [],
            "relationship_tone": [],
        }
        self.facts = []

    def add_fact(self, content, category="fact", source="", origin="auto", auto_update=True, confidence=None):
        self.calls.append(
            {
                "content": content,
                "category": category,
                "source": source,
                "origin": origin,
                "auto_update": auto_update,
                "confidence": confidence,
            }
        )


def test_build_memory_context_includes_ene_profile_blocks():
    dummy = type("ClientDummy", (), {})()
    dummy.memory_manager = _EmptyMemoryManager()
    dummy.user_profile = _DummyProfile([])
    dummy.ene_profile = _DummyEneProfile()
    dummy.ene_profile.facts = [
        type(
            "Fact",
            (),
            {
                "category": "speaking_style",
                "content": "짧고 단정한 말투를 유지한다.",
                "origin": "auto",
                "auto_update": True,
                "timestamp": "2026-03-24T10:00:00",
            },
        )()
    ]
    dummy.mood_manager = None
    dummy.settings = type("SettingsDummy", (), {"config": {"max_profile_facts_in_context": 2}})()
    dummy.calendar_manager = None

    context = asyncio.run(GeminiClient._build_memory_context(dummy, "에네는 어떤 말투야?"))

    assert "[에네 기본 설정]" in context
    assert "에네는 차분한 동반자다." in context
    assert "[에네에 대한 누적 정보]" in context
    assert "[speaking_style] 짧고 단정한 말투를 유지한다." in context


class _EmptyMemoryManager:
    def get_important(self):
        return []

    async def find_similar(self, query, top_k=3, min_similarity=0.5):
        return []

    def get_recent(self, count=5):
        return []


def test_build_memory_context_limits_profile_facts_to_recent_configured_count():
    dummy = type("ClientDummy", (), {})()
    dummy.memory_manager = _EmptyMemoryManager()
    dummy.user_profile = _DummyProfile(
        [
            _Fact("goal", "토익 점수를 올리고 싶다", "2026-03-24T09:00:00"),
            _Fact("habit", "아침마다 산책한다", "2026-03-24T08:00:00"),
            _Fact("preference", "다크 판타지를 좋아한다", "2026-03-24T07:00:00"),
        ]
    )
    dummy.mood_manager = None
    dummy.settings = type("SettingsDummy", (), {"config": {"max_profile_facts_in_context": 2}})()
    dummy.calendar_manager = None

    context = asyncio.run(GeminiClient._build_memory_context(dummy, "오늘 뭐 할까"))

    assert "[goal] : 토익 점수를 올리고 싶다" in context
    assert "[habit] : 아침마다 산책한다" in context
    assert "[preference] : 다크 판타지를 좋아한다" not in context


def test_build_memory_search_text_uses_recent_visible_turns_with_latest_user_message():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "첫 질문", "2026-03-24 10:00"),
        ("assistant", "첫 답변", "2026-03-24 10:01"),
        ("user", "두 번째 질문", "2026-03-24 10:02"),
        ("assistant", "두 번째 답변", "2026-03-24 10:03"),
        ("user", "세 번째 질문", "2026-03-24 10:04"),
        ("assistant", "세 번째 답변", "2026-03-24 10:05"),
    ]
    dummy.settings = type("SettingsDummy", (), {"get": lambda self, key, default=None: 2 if key == "memory_search_recent_turns" else default})()
    dummy._resolve_memory_search_turns = lambda: WebBridge._resolve_memory_search_turns(dummy)

    search_text = WebBridge._build_memory_search_text(dummy, "네 번째 질문")

    assert "첫 질문" not in search_text
    assert "첫 답변" not in search_text
    assert "두 번째 질문" in search_text
    assert "세 번째 답변" in search_text
    assert "네 번째 질문" in search_text
    assert "[Message Time: 2026-03-24 10:02]" in search_text
    assert "[Message Time: 2026-03-24 10:05]" in search_text


def test_build_memory_search_text_prefixes_current_message_with_message_time():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = []
    dummy.settings = type("SettingsDummy", (), {"get": lambda self, key, default=None: 0 if key == "memory_search_recent_turns" else default})()
    dummy._resolve_memory_search_turns = lambda: WebBridge._resolve_memory_search_turns(dummy)

    search_text = WebBridge._build_memory_search_text(dummy, "지금 질문", "2026-03-24 10:06")

    assert search_text == "[Message Time: 2026-03-24 10:06]\n[현재 사용자 메시지] 지금 질문"


def test_on_response_ready_rebuilds_llm_history_from_visible_conversation_only():
    dummy = type("BridgeDummy", (), {})()
    dummy._last_assistant_response = None
    dummy.mood_manager = None
    dummy.llm_client = _DummyLLMClient()
    dummy._emit_mood_changed = lambda snapshot: None
    dummy.conversation_buffer = [("user", "순수 사용자 메시지", "2026-03-24 10:00")]
    dummy._append_conversation = lambda role, text: dummy.conversation_buffer.append((role, text, "2026-03-24 10:01"))
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy._is_rerolling = False
    dummy.reroll_state_changed = _DummySignal()
    dummy._check_auto_summarize = lambda: None
    dummy._resolve_token_usage_payload = lambda payload="": payload or "{}"
    dummy._sanitize_visible_response_text = lambda text: WebBridge._sanitize_visible_response_text(dummy, text)
    dummy._collect_promise_ids = lambda stored: WebBridge._collect_promise_ids(dummy, stored)
    dummy._remember_tracked_promise_ids = lambda promise_ids: None
    dummy._refresh_llm_history_from_visible_conversation = (
        lambda: WebBridge._refresh_llm_history_from_visible_conversation(dummy)
    )

    WebBridge._on_response_ready(
        dummy,
        "analysis=user\n실제 응답 본문",
        "smile",
        "",
        [],
    )

    assert dummy.llm_client.rebuild_calls == [
        [
            ("user", "순수 사용자 메시지", "2026-03-24 10:00"),
            ("assistant", "analysis=user\n실제 응답 본문", "2026-03-24 10:01"),
        ]
    ]


def test_gemini_rebuild_context_from_conversation_prefixes_message_time():
    captured = {}
    dummy = type("ClientDummy", (), {})()
    dummy._create_chat_session = lambda history: captured.setdefault("history", history) or history

    ok = GeminiClient.rebuild_context_from_conversation(
        dummy,
        [
            ("user", "안녕", "2026-03-24 10:00"),
            ("assistant", "반가워", "2026-03-24 10:01"),
        ],
    )

    assert ok is True
    assert captured["history"] == [
        {"role": "user", "parts": [{"text": "[Message Time: 2026-03-24 10:00]\n안녕"}]},
        {"role": "model", "parts": [{"text": "[Message Time: 2026-03-24 10:01]\n반가워"}]},
    ]
