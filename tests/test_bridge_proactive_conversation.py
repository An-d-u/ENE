import sys
import json
import types
from typing import get_args


google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.ai import http_llm_common, llm_client
from src.core.bridge import WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _RunningWorker:
    def isRunning(self):
        return True


class _StoppedWorker:
    def isRunning(self):
        return False


class _DummySettings:
    def __init__(self, config=None):
        self.config = dict(config or {})

    def get(self, key, default=None):
        return self.config.get(key, default)


class _DummyProactiveManager:
    def __init__(self):
        self.added = []
        self.items = []
        self.cancelled = False
        self.deleted = []
        self.updated = []

    def add_proactive_conversation(self, **payload):
        self.added.append(dict(payload))
        item = dict(payload)
        item["id"] = payload.get("id", f"proactive-{len(self.added)}")
        item["status"] = payload.get("status", "scheduled")
        self.items.append(item)
        return item

    def cancel_scheduled(self, now=None):
        self.cancelled = True
        for item in self.items:
            if item.get("status") == "scheduled":
                item["status"] = "cancelled"
        return list(self.items)

    def set_status(self, item_id, status):
        self.updated.append((item_id, status))
        for item in self.items:
            if item.get("id") == item_id:
                item["status"] = status
                return True
        return False

    def delete_item(self, item_id):
        self.deleted.append(item_id)
        before = len(self.items)
        self.items = [item for item in self.items if item.get("id") != item_id]
        return len(self.items) != before

    def list_dicts(self, include_statuses=None):
        allowed = set(include_statuses or [])
        return [
            dict(item)
            for item in self.items
            if not allowed or item.get("status") in allowed
        ]

    def refresh_due_statuses(self):
        due = [item for item in self.items if item.get("status") == "scheduled"]
        return due, []


def _attach_proactive_helpers(dummy):
    dummy._current_proactive_fire_time = lambda: WebBridge._current_proactive_fire_time(dummy)
    dummy._proactive_fire_signature = lambda payload=None: WebBridge._proactive_fire_signature(dummy, payload)
    dummy._prune_recent_proactive_fire_signatures = (
        lambda now_dt=None: WebBridge._prune_recent_proactive_fire_signatures(dummy, now_dt)
    )
    dummy._should_suppress_duplicate_proactive_fire = (
        lambda payload=None: WebBridge._should_suppress_duplicate_proactive_fire(dummy, payload)
    )
    dummy._mark_proactive_fire_started = lambda payload=None: WebBridge._mark_proactive_fire_started(dummy, payload)
    dummy._is_proactive_conversation_enabled = lambda: WebBridge._is_proactive_conversation_enabled(dummy)
    dummy.refresh_proactive_settings = lambda: WebBridge.refresh_proactive_settings(dummy)
    dummy._store_proactive_conversations = (
        lambda candidates=None, suppress=False: WebBridge._store_proactive_conversations(dummy, candidates, suppress=suppress)
    )
    dummy._remember_tracked_proactive_ids = lambda ids=None: WebBridge._remember_tracked_proactive_ids(dummy, ids)
    dummy._cancel_pending_proactive_conversations_for_user_message = (
        lambda: WebBridge._cancel_pending_proactive_conversations_for_user_message(dummy)
    )
    dummy._enqueue_due_proactive_conversation = lambda payload: WebBridge._enqueue_due_proactive_conversation(dummy, payload)
    dummy._drain_proactive_queue_if_idle = lambda: WebBridge._drain_proactive_queue_if_idle(dummy)
    dummy._start_proactive_ai_worker = lambda payload: WebBridge._start_proactive_ai_worker(dummy, payload)
    dummy._collect_proactive_ids = lambda items=None: WebBridge._collect_proactive_ids(dummy, items)
    dummy._finalize_completed_runtime_items = (
        lambda promise_id="", proactive_id="": WebBridge._finalize_completed_runtime_items(dummy, promise_id, proactive_id)
    )
    dummy._finalize_pending_response_completion_if_any = (
        lambda: WebBridge._finalize_pending_response_completion_if_any(dummy)
    )
    return dummy


def test_store_proactive_conversations_persists_items_and_tracks_ids():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()
    dummy._last_request_payload = {"type": "text"}
    dummy.settings = _DummySettings({"enable_proactive_conversation": True})

    stored = WebBridge._store_proactive_conversations(
        dummy,
        [
            {
                "trigger_at": "2026-05-26T21:20:00+09:00",
                "title": "가벼운 확인",
                "generation_prompt": "합성 대화 흐름을 짧게 다시 이어가세요.",
                "source_excerpt": "합성 맥락",
                "reason": "합성 후속 대화",
                "cooldown_key": "short-followup",
            }
        ],
    )
    WebBridge._remember_tracked_proactive_ids(dummy, [item["id"] for item in stored])

    assert dummy.proactive_manager.added[0]["cooldown_key"] == "short-followup"
    assert dummy._last_request_payload["proactive_ids"] == ["proactive-1"]


def test_store_proactive_conversations_skips_when_feature_is_disabled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.settings = _DummySettings({"enable_proactive_conversation": False})

    stored = WebBridge._store_proactive_conversations(
        dummy,
        [
            {
                "trigger_at": "2026-05-26T21:20:00+09:00",
                "title": "가벼운 확인",
                "generation_prompt": "합성 대화 흐름을 짧게 다시 이어가세요.",
                "cooldown_key": "short-followup",
            }
        ],
    )

    assert stored == []
    assert dummy.proactive_manager.added == []


def test_cancel_pending_proactive_conversations_for_user_message():
    dummy = type("BridgeDummy", (), {})()
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_manager.add_proactive_conversation(
        trigger_at="2026-05-26T21:20:00+09:00",
        title="가벼운 확인",
        generation_prompt="합성 대화 흐름을 짧게 다시 이어가세요.",
        cooldown_key="short-followup",
    )

    WebBridge._cancel_pending_proactive_conversations_for_user_message(dummy)

    assert dummy.proactive_manager.cancelled is True
    assert dummy.proactive_manager.items[0]["status"] == "cancelled"


def test_cancel_pending_proactive_conversations_clears_queued_payloads():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_run_queue = [
        {
            "id": "queued-1",
            "title": "가벼운 확인",
            "cooldown_key": "short-followup",
            "trigger_at": "2026-05-26T21:20:00+09:00",
        }
    ]
    dummy.proactive_manager.items = [{"id": "queued-1", "status": "scheduled"}]

    WebBridge._cancel_pending_proactive_conversations_for_user_message(dummy)

    assert dummy.proactive_run_queue == []
    assert dummy.proactive_manager.items[0]["status"] == "cancelled"


def test_duplicate_due_proactive_is_cancelled_instead_of_repolled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.worker = _StoppedWorker()
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_run_queue = []
    dummy._recent_proactive_fire_signatures = {}
    payload = {
        "id": "p1",
        "title": "가벼운 확인",
        "cooldown_key": "short-followup",
        "trigger_at": "2026-05-26T21:20:00+09:00",
    }
    dummy._active_proactive_signature = WebBridge._proactive_fire_signature(dummy, payload)

    WebBridge._enqueue_due_proactive_conversation(dummy, payload)

    assert dummy.proactive_manager.updated == [("p1", "cancelled")]
    assert dummy.proactive_run_queue == []


def test_repeated_poll_for_same_queued_proactive_does_not_enqueue_duplicate():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.worker = _RunningWorker()
    dummy.proactive_manager = _DummyProactiveManager()
    payload = {
        "id": "p1",
        "title": "가벼운 확인",
        "cooldown_key": "short-followup",
        "trigger_at": "2026-05-26T21:20:00+09:00",
    }
    dummy.proactive_run_queue = [payload]
    dummy._recent_proactive_fire_signatures = {}
    dummy._active_proactive_signature = None

    WebBridge._enqueue_due_proactive_conversation(dummy, dict(payload))

    assert dummy.proactive_run_queue == [payload]
    assert dummy.proactive_manager.updated == []


def test_enqueue_due_proactive_conversation_queues_when_worker_is_running():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.worker = _RunningWorker()
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_run_queue = []
    dummy._recent_proactive_fire_signatures = {}
    dummy._active_proactive_signature = None

    payload = {"id": "p1", "title": "가벼운 확인", "cooldown_key": "short-followup", "trigger_at": "2026-05-26T21:20:00+09:00"}
    WebBridge._enqueue_due_proactive_conversation(dummy, payload)

    assert dummy.proactive_run_queue == [payload]
    assert dummy.proactive_manager.updated == [("p1", "queued")]


def test_poll_proactive_conversations_ignores_due_items_when_feature_is_disabled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.worker = _StoppedWorker()
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_manager.items = [
        {
            "id": "p1",
            "title": "가벼운 확인",
            "generation_prompt": "합성 대화 흐름을 짧게 다시 이어가세요.",
            "cooldown_key": "short-followup",
            "trigger_at": "2026-05-26T21:20:00+09:00",
            "status": "scheduled",
        }
    ]
    dummy.proactive_run_queue = [{"id": "queued-1", "status": "scheduled"}]
    dummy.settings = _DummySettings({"enable_proactive_conversation": False})
    started = []
    dummy._start_proactive_ai_worker = lambda payload: started.append(payload)

    WebBridge._poll_proactive_conversations(dummy)

    assert started == []
    assert dummy.proactive_run_queue == []
    assert dummy.proactive_manager.cancelled is True


def test_drain_proactive_queue_if_idle_starts_next_payload():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.worker = None
    dummy.proactive_run_queue = [{"id": "p1"}]
    started = []
    dummy._start_proactive_ai_worker = lambda payload: started.append(payload)

    WebBridge._drain_proactive_queue_if_idle(dummy)

    assert started == [{"id": "p1"}]
    assert dummy.proactive_run_queue == []


def test_drain_proactive_queue_clears_pending_when_feature_is_disabled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": False})
    dummy.worker = None
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_run_queue = [{"id": "p1", "status": "scheduled"}]
    started = []
    dummy._start_proactive_ai_worker = lambda payload: started.append(payload)

    WebBridge._drain_proactive_queue_if_idle(dummy)

    assert started == []
    assert dummy.proactive_run_queue == []
    assert dummy.proactive_manager.cancelled is True


def test_start_proactive_ai_worker_cancels_payload_when_feature_is_disabled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": False})
    dummy.proactive_manager = _DummyProactiveManager()
    dummy._active_proactive_signature = None
    dummy._recent_proactive_fire_signatures = {}
    started = []
    dummy._start_ai_worker = lambda message_with_time: started.append(message_with_time)

    WebBridge._start_proactive_ai_worker(
        dummy,
        {
            "id": "p1",
            "title": "가벼운 확인",
            "generation_prompt": "합성 대화 흐름을 짧게 다시 이어가세요.",
            "cooldown_key": "short-followup",
        },
    )

    assert started == []
    assert dummy.proactive_manager.updated == [("p1", "cancelled")]


def test_start_proactive_ai_worker_uses_generation_prompt():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()
    dummy._active_proactive_signature = None
    dummy._recent_proactive_fire_signatures = {}
    dummy._prompt_language = lambda: "ko"
    dummy._now_timestamp = lambda: "2026-05-26 21:20"
    dummy._with_prompt_time = lambda timestamp, prompt: f"[현재 시각: {timestamp}]\n{prompt}"
    dummy._last_request_payload = None
    started = []
    dummy._start_ai_worker = lambda message_with_time: started.append(message_with_time)

    WebBridge._start_proactive_ai_worker(
        dummy,
        {
            "id": "p1",
            "title": "가벼운 확인",
            "generation_prompt": "합성 대화 흐름을 짧게 다시 이어가세요.",
            "reason": "합성 후속 대화",
            "cooldown_key": "short-followup",
            "trigger_at": "2026-05-26T21:20:00+09:00",
        },
    )

    assert dummy.proactive_manager.updated == [("p1", "triggered")]
    assert "합성 대화 흐름을 짧게 다시 이어가세요." in started[0]
    assert dummy._last_request_payload["type"] == "proactive"
    assert dummy._last_request_payload["proactive_id"] == "p1"
    assert dummy._last_request_payload["message_with_time"] == started[0]


def test_reroll_ignores_proactive_reply_payload():
    dummy = type("BridgeDummy", (), {})()
    dummy.llm_client = object()
    dummy._last_request_payload = {"type": "proactive", "message_with_time": "synthetic prompt"}
    dummy.worker = None
    messages = []
    dummy._reset_pending_ui_state = lambda message: messages.append(message)
    dummy._rollback_last_turn_pair_for_retry = lambda: (_ for _ in ()).throw(AssertionError("rollback should not run"))

    WebBridge.reroll_last_response(dummy)

    assert messages == ["선제 대화 응답은 리롤할 수 없어요."]


def test_edit_ignores_proactive_reply_payload():
    dummy = type("BridgeDummy", (), {})()
    dummy.llm_client = object()
    dummy._last_request_payload = {"type": "proactive", "message_with_time": "synthetic prompt"}
    dummy.worker = None
    messages = []
    dummy._reset_pending_ui_state = lambda message: messages.append(message)
    dummy._rollback_last_turn_pair_for_retry = lambda: (_ for _ in ()).throw(AssertionError("rollback should not run"))

    WebBridge.edit_last_user_message(dummy, "수정 문장")

    assert messages == ["선제 대화 응답은 수정할 사용자 메시지가 없어요."]


def test_request_proactive_conversation_items_emits_visible_items_when_enabled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": True})
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_items_updated = _DummySignal()
    dummy.proactive_manager.items = [
        {"id": "p1", "title": "가벼운 확인", "status": "scheduled"},
        {"id": "p2", "title": "대기 중 확인", "status": "queued"},
        {"id": "p3", "title": "이미 시작", "status": "triggered"},
    ]

    WebBridge.request_proactive_conversation_items(dummy)

    payload = json.loads(dummy.proactive_items_updated.emitted[-1][0])
    assert [item["id"] for item in payload] == ["p1", "p2"]


def test_request_proactive_conversation_items_emits_empty_when_disabled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": False})
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_items_updated = _DummySignal()
    dummy.proactive_manager.items = [
        {"id": "p1", "title": "가벼운 확인", "status": "scheduled"},
    ]

    WebBridge.request_proactive_conversation_items(dummy)

    assert dummy.proactive_items_updated.emitted == [("[]",)]


def test_on_response_ready_stores_proactive_conversation_when_no_promises():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.promise_manager = None
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = []
    dummy.mood_manager = None
    dummy.calendar_manager = None
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy._is_rerolling = False
    dummy._active_promise_id = ""
    dummy._active_proactive_id = ""
    dummy._last_request_payload = {"type": "text"}
    dummy._last_assistant_response = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append((role, text, timestamp or "2026-05-26 21:20"))
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._store_scheduled_promises = lambda items: []
    dummy._maybe_store_user_promise_candidates = lambda scheduled_promises=None: []
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []
    dummy._collect_promise_ids = lambda items=None: []
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._drain_proactive_queue_if_idle = lambda: None

    WebBridge._on_response_ready(
        dummy,
        "좋아요.",
        "smile",
        "",
        [],
        "",
        "",
        [],
        "",
        "",
        [
            {
                "trigger_at": "2026-05-26T21:20:00+09:00",
                "title": "가벼운 확인",
                "generation_prompt": "합성 대화 흐름을 짧게 다시 이어가세요.",
                "cooldown_key": "short-followup",
            }
        ],
    )

    assert len(dummy.proactive_manager.added) == 1
    assert dummy._last_request_payload["proactive_ids"] == ["proactive-1"]


def test_on_response_ready_marks_active_proactive_completed_for_cooldown():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": True})
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_manager.items = [{"id": "p1", "status": "triggered"}]
    dummy.promise_manager = None
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = []
    dummy.mood_manager = None
    dummy.calendar_manager = None
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy._is_rerolling = False
    dummy._active_promise_id = ""
    dummy._active_proactive_id = "p1"
    dummy._active_proactive_signature = "short-followup|가벼운 확인|2026-05-26T21:20"
    dummy._last_request_payload = {"type": "proactive"}
    dummy._last_assistant_response = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append((role, text, timestamp or "2026-05-26 21:20"))
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._store_scheduled_promises = lambda items: []
    dummy._maybe_store_user_promise_candidates = lambda scheduled_promises=None: []
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []
    dummy._collect_promise_ids = lambda items=None: []
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._drain_proactive_queue_if_idle = lambda: None

    WebBridge._on_response_ready(
        dummy,
        "가볍게 먼저 말을 건 합성 답변입니다.",
        "smile",
        "",
        [],
        "",
        "",
        [],
        "",
        "",
        [],
    )

    assert dummy.proactive_manager.updated == [("p1", "completed")]
    assert dummy.proactive_manager.deleted == []
    assert dummy._active_proactive_id is None
    assert dummy._active_proactive_signature is None


def test_on_response_ready_defers_proactive_completion_until_tts_pending_response_is_flushed():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": True})
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_manager.items = [{"id": "p1", "status": "triggered"}]
    dummy.promise_manager = None
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = []
    dummy.mood_manager = None
    dummy.calendar_manager = None
    dummy.enable_tts = True
    dummy.tts_client = object()
    dummy.audio_player = object()
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy._is_rerolling = False
    dummy._active_promise_id = ""
    dummy._active_proactive_id = "p1"
    dummy._active_proactive_signature = "short-followup|가벼운 확인|2026-05-26T21:20"
    dummy._last_request_payload = {"type": "proactive"}
    dummy._last_assistant_response = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append((role, text, timestamp or "2026-05-26 21:20"))
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._store_scheduled_promises = lambda items: []
    dummy._maybe_store_user_promise_candidates = lambda scheduled_promises=None: []
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []
    dummy._collect_promise_ids = lambda items=None: []
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._drain_promise_queue_if_idle = lambda: None
    drained = []
    dummy._drain_proactive_queue_if_idle = lambda: drained.append("drained")
    dummy._finalize_completed_runtime_items = (
        lambda promise_id="", proactive_id="": WebBridge._finalize_completed_runtime_items(dummy, promise_id, proactive_id)
    )
    dummy._finalize_pending_response_completion_if_any = (
        lambda: WebBridge._finalize_pending_response_completion_if_any(dummy)
    )
    played = []
    dummy._play_tts = lambda text: played.append(text)

    WebBridge._on_response_ready(
        dummy,
        "가볍게 먼저 말을 건 합성 답변입니다.",
        "smile",
        "읽어줄 합성 문장",
        [],
        "",
        "",
        [],
        "",
        "",
        [],
    )

    assert played == ["읽어줄 합성 문장"]
    assert dummy.message_received.emitted == []
    assert dummy.proactive_manager.updated == []
    assert drained == []

    WebBridge._flush_pending_response_if_any(dummy)

    assert dummy.message_received.emitted == [("가볍게 먼저 말을 건 합성 답변입니다.", "smile", "")]
    assert dummy.proactive_manager.updated == [("p1", "completed")]
    assert dummy._active_proactive_id is None
    assert dummy._active_proactive_signature is None
    assert drained == ["drained"]


def test_on_response_ready_does_not_chain_proactive_conversations_from_active_proactive_reply():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": True})
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_manager.items = [{"id": "p1", "status": "triggered"}]
    dummy.promise_manager = None
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = []
    dummy.mood_manager = None
    dummy.calendar_manager = None
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy._is_rerolling = False
    dummy._active_promise_id = ""
    dummy._active_proactive_id = "p1"
    dummy._active_proactive_signature = "short-followup|가벼운 확인|2026-05-26T21:20"
    dummy._last_request_payload = {"type": "proactive"}
    dummy._last_assistant_response = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append((role, text, timestamp or "2026-05-26 21:20"))
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._store_scheduled_promises = lambda items: []
    dummy._maybe_store_user_promise_candidates = lambda scheduled_promises=None: []
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []
    dummy._collect_promise_ids = lambda items=None: []
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._drain_proactive_queue_if_idle = lambda: None

    WebBridge._on_response_ready(
        dummy,
        "먼저 말을 건 뒤 짧게 마무리한 합성 답변입니다.",
        "smile",
        "",
        [],
        "",
        "",
        [],
        "",
        "",
        [
            {
                "trigger_at": "2026-05-26T21:30:00+09:00",
                "title": "연쇄 확인",
                "generation_prompt": "다시 먼저 말을 거세요.",
                "cooldown_key": "quiet-checkin",
            }
        ],
    )

    assert dummy.proactive_manager.added == []
    assert dummy.proactive_manager.updated == [("p1", "completed")]
    assert dummy._last_request_payload["proactive_ids"] == []


def test_on_response_ready_drops_active_proactive_reply_when_feature_is_disabled():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.settings = _DummySettings({"enable_proactive_conversation": False})
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_manager.items = [{"id": "p1", "status": "triggered"}]
    dummy.promise_manager = None
    dummy.message_received = _DummySignal()
    dummy.request_pending_changed = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = []
    dummy.mood_manager = None
    dummy.calendar_manager = None
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy._is_rerolling = False
    dummy._active_promise_id = ""
    dummy._active_proactive_id = "p1"
    dummy._active_proactive_signature = "short-followup|가벼운 확인|2026-05-26T21:20"
    dummy._last_request_payload = {"type": "proactive"}
    dummy._last_assistant_response = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append((role, text, timestamp or "2026-05-26 21:20"))
    history_refreshes = []
    dummy._refresh_llm_history_from_visible_conversation = lambda: history_refreshes.append("refreshed")
    dummy._check_auto_summarize = lambda: None
    dummy._store_scheduled_promises = lambda items: []
    dummy._maybe_store_user_promise_candidates = lambda scheduled_promises=None: []
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []
    dummy._collect_promise_ids = lambda items=None: []
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._drain_proactive_queue_if_idle = lambda: None

    WebBridge._on_response_ready(
        dummy,
        "설정이 꺼진 뒤 도착한 합성 선제 답변입니다.",
        "smile",
        "",
        [],
        "",
        "",
        [],
        "",
        "",
        [],
    )

    assert dummy.message_received.emitted == []
    assert dummy.conversation_buffer == []
    assert dummy.proactive_manager.deleted == ["p1"]
    assert dummy._active_proactive_id is None
    assert dummy._active_proactive_signature is None
    assert dummy.request_pending_changed.emitted == [(False,)]
    assert history_refreshes == ["refreshed"]


def test_on_response_ready_skips_proactive_conversation_when_promises_exist():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()

    stored = WebBridge._store_proactive_conversations(
        dummy,
        [{"title": "가벼운 확인", "generation_prompt": "합성 대화 흐름", "trigger_at": "2026-05-26T21:20:00+09:00"}],
        suppress=True,
    )

    assert stored == []
    assert dummy.proactive_manager.added == []


def test_on_error_drains_proactive_queue_after_active_failure():
    dummy = type("BridgeDummy", (), {})()
    dummy.proactive_manager = _DummyProactiveManager()
    dummy.proactive_run_queue = [{"id": "p2"}]
    dummy._active_proactive_id = "p1"
    dummy._active_proactive_signature = "short-followup|확인|2026-05-26t21:20"
    dummy._active_promise_id = ""
    dummy.promise_manager = None
    dummy.message_received = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy._is_rerolling = False
    drained = []
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._drain_proactive_queue_if_idle = lambda: drained.append("drained")

    WebBridge._on_error(dummy, "synthetic failure")

    assert dummy.proactive_manager.updated == [("p1", "expired")]
    assert drained == ["drained"]


def test_worker_finished_hook_rechecks_promise_and_proactive_queues():
    dummy = type("BridgeDummy", (), {})()
    calls = []
    dummy._drain_promise_queue_if_idle = lambda: calls.append("promise")
    dummy._drain_proactive_queue_if_idle = lambda: calls.append("proactive")

    WebBridge._drain_queues_after_worker_finished(dummy)

    assert calls == ["promise", "proactive"]


def test_attachment_user_message_cancels_pending_proactive_conversations():
    dummy = type("BridgeDummy", (), {})()
    dummy.llm_client = object()
    dummy.message_received = _DummySignal()
    dummy.settings = {}
    dummy.calendar_manager = None
    dummy.mood_manager = None
    dummy.conversation_buffer = []
    dummy._message_attachment_records = {}
    dummy._is_rerolling = False
    cancelled = []
    dummy._cancel_pending_proactive_conversations_for_user_message = lambda: cancelled.append("cancelled")
    dummy._resolve_prepared_attachments = lambda attachments: []
    dummy._normalize_attachment_runtime_state = lambda prepared: []
    dummy._build_active_image_payload = lambda runtime: []
    dummy._now_timestamp = lambda: "2026-05-26 21:20"
    dummy._extract_attachment_message_id = lambda attachments: "msg-1"
    dummy._prompt_language = lambda: "ko"
    dummy._build_general_chat_prompt = lambda message, attachment_context="": message
    dummy._with_prompt_time = lambda timestamp, prompt: f"{timestamp}\n{prompt}"
    dummy._build_memory_search_inputs = lambda message, timestamp: {
        "memory_search_text": message,
        "latest_user_message": message,
        "recent_context_text": "",
    }
    dummy._mark_user_activity = lambda: None
    dummy._compose_attachment_history_message = lambda message, attachments: message
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append((role, text, timestamp))
    dummy._start_ai_worker = lambda *args, **kwargs: None

    WebBridge.send_to_ai_with_attachments(dummy, "합성 첨부 답변", "[]")

    assert cancelled == ["cancelled"]


def test_llm_response_tuple_aliases_include_proactive_conversations():
    assert len(get_args(llm_client.LLM_RESPONSE_TUPLE)) == 9
    assert len(get_args(http_llm_common.LLM_RESPONSE_TUPLE)) == 9
