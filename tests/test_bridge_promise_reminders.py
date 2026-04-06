import sys
import types
import json


google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.core.bridge import AIWorker, WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _DummyPromiseManager:
    def __init__(self):
        self.added = []
        self.updated = []
        self.deleted = []
        self.items = []

    def add_promise(self, **payload):
        self.added.append(dict(payload))
        item = dict(payload)
        item["id"] = payload.get("id", f"id-{len(self.added)}")
        item["status"] = payload.get("status", "scheduled")
        self.items.append(item)
        return item

    def list_promise_dicts(self, include_statuses=None):
        if not include_statuses:
            return list(self.items)
        allowed = set(include_statuses)
        return [item for item in self.items if item.get("status") in allowed]

    def find_similar_promise(self, **kwargs):
        return None

    def update_promise_title(self, reminder_id, title):
        self.updated.append((reminder_id, title))
        for item in self.items:
            if item.get("id") == reminder_id:
                item["title"] = title
                return True
        return False

    def set_status(self, reminder_id, status):
        self.updated.append((reminder_id, status))
        for item in self.items:
            if item.get("id") == reminder_id:
                item["status"] = status
                return True
        return False

    def delete_promise(self, reminder_id):
        self.deleted.append(reminder_id)
        before = len(self.items)
        self.items = [item for item in self.items if item.get("id") != reminder_id]
        return len(self.items) != before


class _RunningWorker:
    def isRunning(self):
        return True


def test_ai_worker_normalize_response_payload_supports_promises():
    worker = AIWorker.__new__(AIWorker)

    normalized = AIWorker._normalize_response_payload(
        worker,
        ("본문", "smile", None, [], {"user_intent": "plan"}, [{"title": "쉬는 시간"}]),
    )

    assert normalized == (
        "본문",
        "smile",
        None,
        [],
        {"user_intent": "plan"},
        [{"title": "쉬는 시간"}],
    )


def test_store_scheduled_promises_persists_items_and_emits_notice():
    dummy = type("BridgeDummy", (), {})()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy._promise_notice_message = "대화 약속이 저장되었습니다."

    stored = WebBridge._store_scheduled_promises(
        dummy,
        [
            {
                "title": "쉬는 시간",
                "trigger_at": "2026-04-06T21:10:00+09:00",
                "source": "user",
                "source_excerpt": "10분만 쉬고 다시 할게",
            }
        ],
    )

    assert len(stored) == 1
    assert dummy.promise_manager.added == [
        {
            "title": "쉬는 시간",
            "trigger_at": "2026-04-06T21:10:00+09:00",
            "source": "user",
            "source_excerpt": "10분만 쉬고 다시 할게",
        }
    ]
    assert dummy.promise_notice.emitted[-1] == ("대화 약속이 저장되었습니다.", "success")


def test_enqueue_due_promise_queues_when_worker_is_running():
    dummy = type("BridgeDummy", (), {})()
    dummy.worker = _RunningWorker()
    dummy.promise_run_queue = []
    dummy._start_promise_ai_worker = lambda payload: None

    payload = {"title": "일기 쓰기"}
    WebBridge._enqueue_due_promise(dummy, payload)

    assert dummy.promise_run_queue == [payload]


def test_drain_promise_queue_if_idle_starts_next_payload():
    dummy = type("BridgeDummy", (), {})()
    started = []
    dummy.worker = None
    dummy.promise_run_queue = [{"title": "쉬는 시간"}]
    dummy._start_promise_ai_worker = lambda payload: started.append(payload)

    WebBridge._drain_promise_queue_if_idle(dummy)

    assert started == [{"title": "쉬는 시간"}]
    assert dummy.promise_run_queue == []


def test_emit_promise_items_updated_hides_triggered_items():
    dummy = type("BridgeDummy", (), {})()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_items_updated = _DummySignal()
    dummy.promise_manager.add_promise(
        id="scheduled-1",
        title="쉬는 시간",
        trigger_at="2026-04-06T21:10:00+09:00",
        source="user",
        source_excerpt="10분만 쉬고 다시 할게",
        status="scheduled",
    )
    dummy.promise_manager.add_promise(
        id="triggered-1",
        title="이미 발화됨",
        trigger_at="2026-04-06T20:10:00+09:00",
        source="assistant",
        source_excerpt="이미 끝남",
        status="triggered",
    )

    WebBridge._emit_promise_items_updated(dummy)

    payload = json.loads(dummy.promise_items_updated.emitted[-1][0])
    assert [item["id"] for item in payload] == ["scheduled-1"]


def test_store_local_promise_candidates_parses_user_message_and_emits_notice():
    dummy = type("BridgeDummy", (), {})()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)

    stored = WebBridge._store_local_promise_candidates(
        dummy,
        "3분 뒤 일기 써야지",
        "2026-04-06 21:00",
        source="user",
    )

    assert len(stored) == 1
    assert dummy.promise_manager.added[0]["title"] == "대화 약속"
    assert dummy.promise_manager.added[0]["trigger_at"] == "2026-04-06T21:03:00+09:00"
    assert dummy.promise_notice.emitted[-1] == ("대화 약속이 저장되었습니다.", "success")


def test_store_scheduled_promises_upgrades_generic_title_when_llm_title_arrives():
    dummy = type("BridgeDummy", (), {})()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)
    dummy.promise_manager.add_promise(
        id="scheduled-1",
        title="대화 약속",
        trigger_at="2026-04-06T21:10:00+09:00",
        source="assistant",
        source_excerpt="10분 뒤에 다시 한 번 쓰다듬어 주는 건 어때요",
        status="scheduled",
    )
    dummy.promise_manager.find_similar_promise = lambda **kwargs: dummy.promise_manager.items[0]

    stored = WebBridge._store_scheduled_promises(
        dummy,
        [
            {
                "title": "쓰다듬기",
                "trigger_at": "2026-04-06T21:10:00+09:00",
                "source": "assistant",
                "source_excerpt": "10분 뒤에 다시 한 번 쓰다듬어 주는 건 어때요",
            }
        ],
    )

    assert stored == []
    assert dummy.promise_manager.items[0]["title"] == "쓰다듬기"


def test_on_response_ready_stores_assistant_promise_when_user_requested_schedule():
    dummy = type("BridgeDummy", (), {})()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = [("user", "에네한테 n분 뒤에 뭐뭐하기 예정을 하나 잡아줘", "2026-04-07 10:00")]
    dummy.mood_manager = None
    dummy.calendar_manager = None
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy._is_rerolling = False
    dummy._active_promise_id = ""
    dummy._last_assistant_response = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append(
        (role, text, timestamp or "2026-04-07 10:00")
    )
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._store_scheduled_promises = lambda items: WebBridge._store_scheduled_promises(dummy, items)
    dummy._store_local_promise_candidates = (
        lambda source_text, timestamp, source="user": WebBridge._store_local_promise_candidates(
            dummy,
            source_text,
            timestamp,
            source=source,
        )
    )
    dummy._maybe_store_assistant_promise_candidates = (
        lambda source_text: WebBridge._maybe_store_assistant_promise_candidates(dummy, source_text)
    )

    WebBridge._on_response_ready(
        dummy,
        "음, 그럼 10분 뒤에 다시 한 번 쓰다듬어 주는 건 어때요?",
        "smile",
        "",
        [],
        "",
        "",
        [],
    )

    assert len(dummy.promise_manager.added) == 1
    assert dummy.promise_manager.added[0]["title"] == "대화 약속"
    assert dummy.promise_manager.added[0]["source"] == "assistant"
    assert dummy.promise_manager.added[0]["trigger_at"] == "2026-04-07T10:10:00+09:00"


def test_on_response_ready_stores_assistant_promise_when_user_requested_schedule_with_iljeong_wording():
    dummy = type("BridgeDummy", (), {})()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = [("user", "이제 에네가 N분 후에 뭐뭐하기 식으로 일정을 하나 만들어줘.", "2026-04-07 10:00")]
    dummy.mood_manager = None
    dummy.calendar_manager = None
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy._is_rerolling = False
    dummy._active_promise_id = ""
    dummy._last_assistant_response = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append(
        (role, text, timestamp or "2026-04-07 10:00")
    )
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._store_scheduled_promises = lambda items: WebBridge._store_scheduled_promises(dummy, items)
    dummy._store_local_promise_candidates = (
        lambda source_text, timestamp, source="user": WebBridge._store_local_promise_candidates(
            dummy,
            source_text,
            timestamp,
            source=source,
        )
    )
    dummy._maybe_store_assistant_promise_candidates = (
        lambda source_text: WebBridge._maybe_store_assistant_promise_candidates(dummy, source_text)
    )

    WebBridge._on_response_ready(
        dummy,
        "그럼 제가 정할 테니까, 10분 뒤에 침대에 눕는 거예요.",
        "smile",
        "",
        [],
        "",
        "",
        [],
    )

    assert len(dummy.promise_manager.added) == 1
    assert dummy.promise_manager.added[0]["source"] == "assistant"
    assert dummy.promise_manager.added[0]["trigger_at"] == "2026-04-07T10:10:00+09:00"
