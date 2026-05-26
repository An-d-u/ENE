import sys
import types


google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.core.bridge import WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _RunningWorker:
    def isRunning(self):
        return True


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
    return dummy


def test_store_proactive_conversations_persists_items_and_tracks_ids():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()
    dummy._last_request_payload = {"type": "text"}

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


def test_drain_proactive_queue_if_idle_starts_next_payload():
    dummy = type("BridgeDummy", (), {})()
    dummy.worker = None
    dummy.proactive_run_queue = [{"id": "p1"}]
    started = []
    dummy._start_proactive_ai_worker = lambda payload: started.append(payload)

    WebBridge._drain_proactive_queue_if_idle(dummy)

    assert started == [{"id": "p1"}]
    assert dummy.proactive_run_queue == []


def test_start_proactive_ai_worker_uses_generation_prompt():
    dummy = type("BridgeDummy", (), {})()
    _attach_proactive_helpers(dummy)
    dummy.proactive_manager = _DummyProactiveManager()
    dummy._active_proactive_signature = None
    dummy._recent_proactive_fire_signatures = {}
    dummy._prompt_language = lambda: "ko"
    dummy._now_timestamp = lambda: "2026-05-26 21:20"
    dummy._with_prompt_time = lambda timestamp, prompt: f"[현재 시각: {timestamp}]\n{prompt}"
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
