import asyncio
import json
import sys
import types

google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.core.bridge import WebBridge  # noqa: E402
from src.ai.knowledge_map_types import TopicMemoryHint  # noqa: E402


class _DummyMemoryManager:
    def __init__(self, summary_id=None):
        self.calls = []
        self.topic_calls = []
        self.summary_id = summary_id

    async def add_summary(self, **kwargs):
        self.calls.append(kwargs)
        if self.summary_id:
            return types.SimpleNamespace(id=self.summary_id)
        return None

    def __getattr__(self, name):
        if "topic" in name or "knowledge" in name:
            async def _record_topic_call(*args, **kwargs):
                self.topic_calls.append((name, args, kwargs))

            return _record_topic_call
        raise AttributeError(name)


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
                "aliases": ["릴리즈 후보"],
                "trigger_terms": ["릴리스", "후보"],
            },
        )

    def clear_context(self):
        return None


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _ReviewLLMClient:
    def __init__(self):
        self.calls = []
        self.clear_context_calls = 0

    async def summarize_conversation(self, messages):
        self.calls.append(list(messages))
        call_number = len(self.calls)
        return (
            f"요약 후보 {call_number}",
            [f"[goal] 사용자 정보 {call_number}"],
            [f"[speaking_style] 에네 정보 {call_number}"],
            {
                "memory_type": "task",
                "importance_reason": "repeated_topic",
                "confidence": 0.81,
                "entity_names": ["ENE"],
                "aliases": ["요약 후보"],
                "trigger_terms": ["요약", "후보"],
            },
        )

    def clear_context(self):
        self.clear_context_calls += 1


class _TopicReviewLLMClient:
    def __init__(self):
        self.calls = []

    async def summarize_conversation(self, messages):
        self.calls.append(list(messages))
        call_number = len(self.calls)
        return (
            f"topic summary {call_number}",
            [f"[goal] neutral user fact {call_number}"],
            [f"[speaking_style] neutral assistant fact {call_number}"],
            {"memory_type": "task", "confidence": 0.8},
            [
                TopicMemoryHint(
                    keyword=f"Project Topic {call_number}",
                    subject="review payload",
                    type="status_flow",
                    state="active",
                    text=f"Project Topic {call_number} review payload is ready.",
                    aliases=[f"Topic {call_number}"],
                    retrieval_terms=["review", "payload"],
                    confidence=0.77,
                ),
                {
                    "keyword": f"Project Dict {call_number}",
                    "subject": "dict payload",
                    "type": "status_flow",
                    "state": "active",
                    "text": f"Project Dict {call_number} dict payload is ready.",
                    "retrieval_terms": ["dict", "payload"],
                    "confidence": 0.66,
                    "ignored": "not exported",
                },
            ],
        )


class _TopicAutoLLMClient:
    async def summarize_conversation(self, messages):
        return (
            "auto topic summary",
            [],
            [],
            {"memory_type": "task", "confidence": 0.7},
            [
                TopicMemoryHint(
                    keyword="Project Auto",
                    subject="auto summary",
                    type="status_flow",
                    state="active",
                    text="Project Auto summary is ready.",
                    retrieval_terms=["auto", "summary"],
                    confidence=0.76,
                )
            ],
        )

    def clear_context(self):
        return None


class _DummyProfile:
    def __init__(self):
        self.calls = []

    def add_fact(self, **kwargs):
        self.calls.append(kwargs)


class _DummyKnowledgeMapManager:
    def __init__(self, *, fail_on_merge=False, fail_on_save=False):
        self.merge_calls = []
        self.save_calls = 0
        self.fail_on_merge = fail_on_merge
        self.fail_on_save = fail_on_save

    async def async_merge_hints(self, topic_hints, source_memory_id=""):
        self.merge_calls.append((list(topic_hints or []), source_memory_id))
        if self.fail_on_merge:
            raise RuntimeError("synthetic merge failure")

    def save(self):
        self.save_calls += 1
        if self.fail_on_save:
            raise RuntimeError("synthetic save failure")


def _build_pending_review(messages=None, *, topic_hints=None):
    messages = messages or [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    return {
        "messages": list(messages),
        "original_messages": [
            {
                "role": role,
                "text": text,
                "timestamp": timestamp,
                "conversation_id": "conv-review-topic",
                "turn_index": index,
            }
            for index, (role, text, timestamp) in enumerate(messages)
        ],
        "source_timestamp": "2026-04-14 20:01",
        "summary": "review summary",
        "user_facts": [],
        "ene_facts": [],
        "memory_meta": {"memory_type": "task", "confidence": 0.8},
        "topic_hints": list(topic_hints or []),
    }


def test_normalize_summary_result_accepts_topic_hints_and_legacy_tuples():
    dummy = type("BridgeDummy", (), {})()
    hint = TopicMemoryHint(
        keyword="Project Normalize",
        subject="tuple support",
        type="status_flow",
        state="active",
        text="Project Normalize tuple support is ready.",
    )

    assert WebBridge._normalize_summary_result(
        dummy,
        ("summary", ["user fact"], ["assistant fact"], {"memory_type": "task"}, [hint]),
    ) == ("summary", ["user fact"], ["assistant fact"], {"memory_type": "task"}, [hint.to_dict()])
    assert WebBridge._normalize_summary_result(
        dummy,
        ("summary", ["user fact"], ["assistant fact"], {"memory_type": "task"}),
    ) == ("summary", ["user fact"], ["assistant fact"], {"memory_type": "task"}, [])
    assert WebBridge._normalize_summary_result(
        dummy,
        ("summary", ["user fact"], {"memory_type": "task"}),
    ) == ("summary", ["user fact"], [], {"memory_type": "task"}, [])
    assert WebBridge._normalize_summary_result(dummy, ("summary", ["user fact"])) == (
        "summary",
        ["user fact"],
        [],
        {},
        [],
    )


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

    assert dummy.memory_manager.calls[0]["aliases"] == ["릴리즈 후보"]
    assert dummy.memory_manager.calls[0]["trigger_terms"] == ["릴리스", "후보"]
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


def test_manual_summarize_emits_review_payload_without_saving():
    dummy = type("BridgeDummy", (), {})()
    dummy.worker = None
    dummy.conversation_buffer = [
        ("user", "hello", "2026-04-14 20:00"),
        ("assistant", "hi", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = None
    dummy.summary_notice = _DummySignal()
    dummy.summary_review_ready = _DummySignal()
    dummy._create_memory_conversation_id = lambda messages: "conv-review-1"
    dummy._prepare_summary_review = lambda: WebBridge._prepare_summary_review(dummy)
    dummy._normalize_summary_result = lambda result: WebBridge._normalize_summary_result(dummy, result)
    dummy._build_summary_storage_payload = lambda messages: WebBridge._build_summary_storage_payload(dummy, messages)
    dummy._emit_summary_review = lambda: WebBridge._emit_summary_review(dummy)

    WebBridge.summarize_now(dummy)

    assert dummy.memory_manager.calls == []
    assert len(dummy.summary_review_ready.emitted) == 1
    payload = json.loads(dummy.summary_review_ready.emitted[0][0])
    assert payload["summary"] == "요약 후보 1"
    assert payload["user_facts"] == ["[goal] 사용자 정보 1"]
    assert payload["ene_facts"] == ["[speaking_style] 에네 정보 1"]
    assert payload["memory_meta"]["memory_type"] == "task"
    assert dummy.conversation_buffer


def test_manual_summarize_review_payload_includes_topic_hints_without_saving():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _TopicReviewLLMClient()
    dummy.summary_review_ready = _DummySignal()
    dummy._create_memory_conversation_id = lambda messages: "conv-topic-review"
    dummy._normalize_summary_result = lambda result: WebBridge._normalize_summary_result(dummy, result)
    dummy._build_summary_storage_payload = lambda messages: WebBridge._build_summary_storage_payload(dummy, messages)
    dummy._emit_summary_review = lambda: WebBridge._emit_summary_review(dummy)

    asyncio.run(WebBridge._prepare_summary_review(dummy))

    assert dummy.memory_manager.calls == []
    assert dummy.memory_manager.topic_calls == []
    assert len(dummy.summary_review_ready.emitted) == 1
    payload = json.loads(dummy.summary_review_ready.emitted[0][0])
    assert [hint["keyword"] for hint in payload["topic_hints"]] == ["Project Topic 1", "Project Dict 1"]
    assert "ignored" not in payload["topic_hints"][1]
    assert dummy._pending_summary_review["topic_hints"] == payload["topic_hints"]


def test_auto_summarize_ignores_topic_hints_for_storage():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _TopicAutoLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = None
    dummy._create_memory_conversation_id = lambda messages: "conv-auto-topic"

    asyncio.run(WebBridge._auto_summarize(dummy))

    assert len(dummy.memory_manager.calls) == 1
    assert dummy.memory_manager.calls[0]["summary"] == "auto topic summary"
    assert dummy.memory_manager.topic_calls == []


def test_approve_summary_review_persists_edited_summary_and_selected_facts():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "hello", "2026-04-14 20:00"),
        ("assistant", "hi", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = _DummyProfile()
    dummy.ene_profile = _DummyProfile()
    dummy.summary_notice = _DummySignal()
    dummy.summary_review_ready = _DummySignal()
    dummy.summary_review_saved = _DummySignal()
    dummy._ene_thought_context_buffer = ["생각"]
    dummy._pending_summary_review = {
        "messages": list(dummy.conversation_buffer),
        "original_messages": [
            {
                "role": "user",
                "text": "hello",
                "timestamp": "2026-04-14 20:00",
                "conversation_id": "conv-review-1",
                "turn_index": 0,
            },
            {
                "role": "assistant",
                "text": "hi",
                "timestamp": "2026-04-14 20:01",
                "conversation_id": "conv-review-1",
                "turn_index": 1,
            },
        ],
        "source_timestamp": "2026-04-14 20:01",
        "summary": "요약 후보",
        "user_facts": ["[goal] 저장할 사용자 정보", "[habit] 제외할 사용자 정보"],
        "ene_facts": ["[speaking_style] 저장할 에네 정보"],
        "memory_meta": {
            "memory_type": "task",
            "importance_reason": "repeated_topic",
            "confidence": 0.81,
            "entity_names": ["ENE"],
        },
    }
    dummy._persist_reviewed_summary = (
        lambda summary, user_facts, ene_facts, memory_meta, topic_hints=None: WebBridge._persist_reviewed_summary(
            dummy,
            summary,
            user_facts,
            ene_facts,
            memory_meta,
            topic_hints,
        )
    )
    dummy._drop_reviewed_messages_from_buffer = (
        lambda messages: WebBridge._drop_reviewed_messages_from_buffer(dummy, messages)
    )

    WebBridge.approve_summary_review(
        dummy,
        json.dumps(
            {
                "summary": "사용자가 고친 요약",
                "user_facts": ["[goal] 저장할 사용자 정보"],
                "ene_facts": ["[speaking_style] 저장할 에네 정보"],
                "memory_meta": {
                    "memory_type": "preference",
                    "importance_reason": "user_marked",
                    "confidence": 0.92,
                    "entity_names": ["ENE", "Project"],
                    "aliases": ["프로젝트 릴리즈"],
                    "trigger_terms": ["프로젝트", "릴리스"],
                },
            },
            ensure_ascii=False,
        ),
    )

    assert dummy.memory_manager.calls[0]["summary"] == "사용자가 고친 요약"
    assert dummy.memory_manager.calls[0]["memory_type"] == "preference"
    assert dummy.memory_manager.calls[0]["importance_reason"] == "user_marked"
    assert dummy.memory_manager.calls[0]["confidence"] == 0.92
    assert dummy.memory_manager.calls[0]["entity_names"] == ["ENE", "Project"]
    assert dummy.memory_manager.calls[0]["aliases"] == ["프로젝트 릴리즈"]
    assert dummy.memory_manager.calls[0]["trigger_terms"] == ["프로젝트", "릴리스"]
    assert dummy.user_profile.calls == [
        {
            "content": "[goal] 저장할 사용자 정보",
            "category": "fact",
            "source": "대화 요약 (2026-04-14 20:01)",
        }
    ]
    assert dummy.ene_profile.calls == [
        {
            "content": "[speaking_style] 저장할 에네 정보",
            "category": "fact",
            "source": "대화 요약 (2026-04-14 20:01)",
            "origin": "auto",
            "auto_update": True,
        }
    ]
    assert dummy.llm_client.clear_context_calls == 1
    assert dummy.conversation_buffer == []
    assert dummy._ene_thought_context_buffer == []
    assert dummy.summary_review_saved.emitted == [()]


def test_approve_summary_review_persists_payload_topic_hints_to_knowledge_map():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager(summary_id="memory-review-1")
    dummy.knowledge_map_manager = _DummyKnowledgeMapManager()
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = None
    dummy.summary_notice = _DummySignal()
    dummy.summary_review_saved = _DummySignal()
    dummy._ene_thought_context_buffer = []
    dummy._pending_summary_review = _build_pending_review(
        dummy.conversation_buffer,
        topic_hints=[
            {
                "keyword": "Original Topic",
                "subject": "pending",
                "type": "status_flow",
                "state": "active",
                "text": "Original pending topic should not be stored.",
            }
        ],
    )
    dummy._persist_reviewed_summary = (
        lambda summary, user_facts, ene_facts, memory_meta, topic_hints=None: WebBridge._persist_reviewed_summary(
            dummy,
            summary,
            user_facts,
            ene_facts,
            memory_meta,
            topic_hints,
        )
    )
    dummy._drop_reviewed_messages_from_buffer = (
        lambda messages: WebBridge._drop_reviewed_messages_from_buffer(dummy, messages)
    )

    WebBridge.approve_summary_review(
        dummy,
        json.dumps(
            {
                "summary": "approved summary",
                "user_facts": [],
                "ene_facts": [],
                "memory_meta": {"memory_type": "task", "confidence": 0.9},
                "topic_hints": [
                    {
                        "keyword": "Approved Topic",
                        "subject": "payload",
                        "type": "status_flow",
                        "state": "active",
                        "text": "Approved payload topic should be stored.",
                        "aliases": ["Approved"],
                        "retrieval_terms": ["payload", "topic"],
                        "confidence": 0.88,
                    },
                    {
                        "keyword": "Malformed Topic",
                        "subject": "payload",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    assert len(dummy.memory_manager.calls) == 1
    assert len(dummy.knowledge_map_manager.merge_calls) == 1
    saved_hints, source_memory_id = dummy.knowledge_map_manager.merge_calls[0]
    assert [hint["keyword"] for hint in saved_hints] == ["Approved Topic"]
    assert source_memory_id == "memory-review-1"
    assert dummy.knowledge_map_manager.save_calls == 1
    assert dummy.conversation_buffer == []
    assert dummy.summary_review_saved.emitted == [()]


def test_approve_summary_review_uses_deleted_payload_topic_hints_over_pending_original():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager(summary_id="memory-review-2")
    dummy.knowledge_map_manager = _DummyKnowledgeMapManager()
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = None
    dummy.summary_notice = _DummySignal()
    dummy.summary_review_saved = _DummySignal()
    dummy._ene_thought_context_buffer = []
    dummy._pending_summary_review = _build_pending_review(
        dummy.conversation_buffer,
        topic_hints=[
            {
                "keyword": "Pending Topic",
                "subject": "pending",
                "type": "status_flow",
                "state": "active",
                "text": "Pending-only topic should not be stored.",
            }
        ],
    )
    dummy._persist_reviewed_summary = (
        lambda summary, user_facts, ene_facts, memory_meta, topic_hints=None: WebBridge._persist_reviewed_summary(
            dummy,
            summary,
            user_facts,
            ene_facts,
            memory_meta,
            topic_hints,
        )
    )
    dummy._drop_reviewed_messages_from_buffer = (
        lambda messages: WebBridge._drop_reviewed_messages_from_buffer(dummy, messages)
    )

    WebBridge.approve_summary_review(
        dummy,
        json.dumps(
            {
                "summary": "approved summary",
                "user_facts": [],
                "ene_facts": [],
                "memory_meta": {"memory_type": "task"},
                "topic_hints": [],
            },
            ensure_ascii=False,
        ),
    )

    assert len(dummy.memory_manager.calls) == 1
    assert dummy.knowledge_map_manager.merge_calls == []
    assert dummy.knowledge_map_manager.save_calls == 0
    assert dummy.conversation_buffer == []
    assert dummy.summary_review_saved.emitted == [()]


def test_persist_reviewed_summary_accepts_mixed_topic_hint_objects_and_skips_malformed():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.knowledge_map_manager = _DummyKnowledgeMapManager()
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = None
    dummy._ene_thought_context_buffer = []
    dummy._pending_summary_review = _build_pending_review(dummy.conversation_buffer)
    dummy._drop_reviewed_messages_from_buffer = (
        lambda messages: WebBridge._drop_reviewed_messages_from_buffer(dummy, messages)
    )

    asyncio.run(
        WebBridge._persist_reviewed_summary(
            dummy,
            "approved summary",
            [],
            [],
            {"memory_type": "task"},
            [
                TopicMemoryHint(
                    keyword="Object Topic",
                    subject="object payload",
                    type="status_flow",
                    state="active",
                    text="Object topic should be stored.",
                ),
                {
                    "keyword": "Dict Topic",
                    "subject": "dict payload",
                    "type": "status_flow",
                    "state": "active",
                    "text": "Dict topic should be stored.",
                },
                {"keyword": "Incomplete Topic", "subject": "missing text"},
                "not a topic hint",
            ],
        )
    )

    saved_hints, source_memory_id = dummy.knowledge_map_manager.merge_calls[0]
    assert [hint["keyword"] for hint in saved_hints] == ["Object Topic", "Dict Topic"]
    assert source_memory_id == "conv-review-topic"
    assert dummy.knowledge_map_manager.save_calls == 1


def test_persist_reviewed_summary_skips_topic_storage_when_knowledge_map_manager_is_none():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager()
    dummy.knowledge_map_manager = None
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = _DummyProfile()
    dummy.ene_profile = None
    dummy._ene_thought_context_buffer = []
    dummy._pending_summary_review = _build_pending_review(dummy.conversation_buffer)
    dummy._drop_reviewed_messages_from_buffer = (
        lambda messages: WebBridge._drop_reviewed_messages_from_buffer(dummy, messages)
    )

    asyncio.run(
        WebBridge._persist_reviewed_summary(
            dummy,
            "approved summary",
            ["[goal] synthetic neutral fact"],
            [],
            {"memory_type": "task"},
            [
                {
                    "keyword": "No Manager Topic",
                    "subject": "missing manager",
                    "type": "status_flow",
                    "state": "active",
                    "text": "This topic should be skipped without a manager.",
                }
            ],
        )
    )

    assert len(dummy.memory_manager.calls) == 1
    assert len(dummy.user_profile.calls) == 1
    assert dummy.conversation_buffer == []
    assert dummy._pending_summary_review is None


def test_persist_reviewed_summary_keeps_summary_profile_and_buffer_cleanup_when_topic_save_fails():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        ("user", "neutral input", "2026-04-14 20:00"),
        ("assistant", "neutral reply", "2026-04-14 20:01"),
    ]
    dummy.memory_manager = _DummyMemoryManager(summary_id="memory-review-3")
    dummy.knowledge_map_manager = _DummyKnowledgeMapManager(fail_on_save=True)
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = _DummyProfile()
    dummy.ene_profile = _DummyProfile()
    dummy._ene_thought_context_buffer = []
    dummy._pending_summary_review = _build_pending_review(dummy.conversation_buffer)
    dummy._drop_reviewed_messages_from_buffer = (
        lambda messages: WebBridge._drop_reviewed_messages_from_buffer(dummy, messages)
    )

    asyncio.run(
        WebBridge._persist_reviewed_summary(
            dummy,
            "approved summary",
            ["[goal] synthetic neutral fact"],
            ["[speaking_style] synthetic neutral fact"],
            {"memory_type": "task"},
            [
                {
                    "keyword": "Failing Save Topic",
                    "subject": "save failure",
                    "type": "status_flow",
                    "state": "active",
                    "text": "Topic save failure should not rollback summary.",
                }
            ],
        )
    )

    assert len(dummy.memory_manager.calls) == 1
    assert len(dummy.user_profile.calls) == 1
    assert len(dummy.ene_profile.calls) == 1
    assert len(dummy.knowledge_map_manager.merge_calls) == 1
    assert dummy.knowledge_map_manager.save_calls == 1
    assert dummy.conversation_buffer == []
    assert dummy._pending_summary_review is None


def test_approve_summary_review_preserves_messages_added_after_review_started():
    dummy = type("BridgeDummy", (), {})()
    reviewed_messages = [
        ("user", "hello", "2026-04-14 20:00"),
        ("assistant", "hi", "2026-04-14 20:01"),
    ]
    new_messages = [
        ("user", "new question", "2026-04-14 20:02"),
        ("assistant", "new answer", "2026-04-14 20:03"),
    ]
    dummy.conversation_buffer = reviewed_messages + new_messages
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _ReviewLLMClient()
    dummy.user_profile = None
    dummy.ene_profile = None
    dummy.summary_notice = _DummySignal()
    dummy.summary_review_saved = _DummySignal()
    dummy._ene_thought_context_buffer = [
        {"conversation_index": 1, "thought": "old"},
        {"conversation_index": 3, "thought": "new"},
    ]
    dummy._pending_summary_review = {
        "messages": list(reviewed_messages),
        "original_messages": [],
        "source_timestamp": "2026-04-14 20:01",
        "summary": "요약 후보",
        "user_facts": [],
        "ene_facts": [],
        "memory_meta": {},
    }
    dummy._persist_reviewed_summary = (
        lambda summary, user_facts, ene_facts, memory_meta, topic_hints=None: WebBridge._persist_reviewed_summary(
            dummy,
            summary,
            user_facts,
            ene_facts,
            memory_meta,
            topic_hints,
        )
    )
    dummy._drop_reviewed_messages_from_buffer = (
        lambda messages: WebBridge._drop_reviewed_messages_from_buffer(dummy, messages)
    )

    WebBridge.approve_summary_review(
        dummy,
        json.dumps({"summary": "검토한 요약"}, ensure_ascii=False),
    )

    assert dummy.conversation_buffer == new_messages
    assert dummy._ene_thought_context_buffer == [{"conversation_index": 1, "thought": "new"}]
    assert dummy.summary_review_saved.emitted == [()]


def test_auto_summarize_is_deferred_while_summary_review_is_pending():
    dummy = type("BridgeDummy", (), {})()
    dummy.memory_manager = _DummyMemoryManager()
    dummy.summarize_threshold = 1
    dummy.conversation_buffer = [("user", "hello", "2026-04-14 20:00")]
    dummy._pending_summary_review = {"summary": "검토 중"}
    dummy.scheduled = False
    dummy._auto_summarize = lambda: setattr(dummy, "scheduled", True)

    WebBridge._check_auto_summarize(dummy)

    assert dummy.scheduled is False


def test_regenerate_summary_review_updates_payload_without_saving():
    dummy = type("BridgeDummy", (), {})()
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _ReviewLLMClient()
    dummy.summary_notice = _DummySignal()
    dummy.summary_review_ready = _DummySignal()
    dummy._pending_summary_review = {
        "messages": [("user", "hello", "2026-04-14 20:00")],
        "original_messages": [],
        "source_timestamp": "2026-04-14 20:00",
        "summary": "이전 요약",
        "user_facts": [],
        "ene_facts": [],
        "memory_meta": {},
    }
    dummy._normalize_summary_result = lambda result: WebBridge._normalize_summary_result(dummy, result)
    dummy._emit_summary_review = lambda: WebBridge._emit_summary_review(dummy)

    WebBridge.regenerate_summary_review(dummy)

    assert dummy.memory_manager.calls == []
    assert len(dummy.llm_client.calls) == 1
    assert dummy._pending_summary_review["summary"] == "요약 후보 1"
    assert dummy._pending_summary_review["user_facts"] == ["[goal] 사용자 정보 1"]
    assert dummy._pending_summary_review["ene_facts"] == ["[speaking_style] 에네 정보 1"]
    assert dummy._pending_summary_review["memory_meta"]["memory_type"] == "task"
    assert len(dummy.summary_review_ready.emitted) == 1
    payload = json.loads(dummy.summary_review_ready.emitted[0][0])
    assert payload["summary"] == "요약 후보 1"


def test_regenerate_summary_review_updates_topic_hints_payload_without_saving():
    dummy = type("BridgeDummy", (), {})()
    dummy.memory_manager = _DummyMemoryManager()
    dummy.llm_client = _TopicReviewLLMClient()
    dummy.summary_notice = _DummySignal()
    dummy.summary_review_ready = _DummySignal()
    dummy._pending_summary_review = {
        "messages": [("user", "neutral input", "2026-04-14 20:00")],
        "original_messages": [],
        "source_timestamp": "2026-04-14 20:00",
        "summary": "old summary",
        "user_facts": [],
        "ene_facts": [],
        "memory_meta": {},
        "topic_hints": [],
    }
    dummy._normalize_summary_result = lambda result: WebBridge._normalize_summary_result(dummy, result)
    dummy._emit_summary_review = lambda: WebBridge._emit_summary_review(dummy)

    WebBridge.regenerate_summary_review(dummy)

    assert dummy.memory_manager.calls == []
    assert dummy.memory_manager.topic_calls == []
    assert dummy._pending_summary_review["summary"] == "topic summary 1"
    assert [hint["keyword"] for hint in dummy._pending_summary_review["topic_hints"]] == [
        "Project Topic 1",
        "Project Dict 1",
    ]
    payload = json.loads(dummy.summary_review_ready.emitted[0][0])
    assert [hint["keyword"] for hint in payload["topic_hints"]] == ["Project Topic 1", "Project Dict 1"]
