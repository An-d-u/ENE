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


class _DummyLlmClient:
    def __init__(self, rollback_result=True):
        self.rollback_result = rollback_result

    def rollback_last_assistant_turn(self):
        return self.rollback_result


def _attach_bridge_promise_helpers(dummy):
    if not hasattr(dummy, "_last_request_payload"):
        dummy._last_request_payload = {}
    dummy._collect_promise_ids = lambda items=None: WebBridge._collect_promise_ids(dummy, items)
    dummy._remember_tracked_promise_ids = lambda reminder_ids=None: WebBridge._remember_tracked_promise_ids(dummy, reminder_ids)
    dummy._delete_tracked_promises_for_retry = lambda: WebBridge._delete_tracked_promises_for_retry(dummy)
    dummy._current_promise_fire_time = lambda: WebBridge._current_promise_fire_time(dummy)
    dummy._promise_fire_signature = lambda payload=None: WebBridge._promise_fire_signature(dummy, payload)
    dummy._prune_recent_promise_fire_signatures = lambda now_dt=None: WebBridge._prune_recent_promise_fire_signatures(dummy, now_dt)
    dummy._should_suppress_duplicate_promise_fire = lambda payload=None: WebBridge._should_suppress_duplicate_promise_fire(dummy, payload)
    dummy._dismiss_duplicate_promise_payload = lambda payload=None: WebBridge._dismiss_duplicate_promise_payload(dummy, payload)
    dummy._mark_promise_fire_started = lambda payload=None: WebBridge._mark_promise_fire_started(dummy, payload)
    return dummy


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
    _attach_bridge_promise_helpers(dummy)
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


def test_store_local_promise_candidates_ignores_plain_time_reference():
    dummy = type("BridgeDummy", (), {})()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)

    stored = WebBridge._store_local_promise_candidates(
        dummy,
        "8시도 안됐는데 잘 순 없잖아...",
        "2026-04-07 19:40",
        source="user",
    )

    assert stored == []
    assert dummy.promise_manager.added == []


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
    _attach_bridge_promise_helpers(dummy)
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
    _attach_bridge_promise_helpers(dummy)
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


def test_on_response_ready_stores_assistant_promise_after_user_accepts_recent_suggestion():
    dummy = type("BridgeDummy", (), {})()
    _attach_bridge_promise_helpers(dummy)
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = [
        ("assistant", "차라리 5분만 더 멍하니 계시다가, 다시 한번 의자에 앉아보는 건 어때요?", "2026-04-07 21:10"),
        ("user", "응.. 그럴래...", "2026-04-07 21:11"),
    ]
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
        (role, text, timestamp or "2026-04-07 21:11")
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
        "알겠어요. 그럼 딱 5분만이에요. 제가 시간 되면 정확히 알려드릴 테니까요.",
        "smile",
        "",
        [],
        "",
        "",
        [],
    )

    assert len(dummy.promise_manager.added) == 1
    assert dummy.promise_manager.added[0]["source"] == "assistant"
    assert dummy.promise_manager.added[0]["trigger_at"] == "2026-04-07T21:16:00+09:00"


def test_on_response_ready_uses_user_fallback_only_when_llm_returns_no_promises():
    dummy = type("BridgeDummy", (), {})()
    _attach_bridge_promise_helpers(dummy)
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = [("user", "3분 뒤 일기 써야지", "2026-04-06 21:00")]
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
        (role, text, timestamp or "2026-04-06 21:00")
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
    dummy._maybe_store_user_promise_candidates = (
        lambda scheduled_promises=None: WebBridge._maybe_store_user_promise_candidates(
            dummy,
            scheduled_promises,
        )
    )
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []

    WebBridge._on_response_ready(
        dummy,
        "좋아, 이따 다시 이야기하자.",
        "smile",
        "",
        [],
        "",
        "",
        [],
    )

    assert len(dummy.promise_manager.added) == 1
    assert dummy.promise_manager.added[0]["source"] == "user"
    assert dummy.promise_manager.added[0]["trigger_at"] == "2026-04-06T21:03:00+09:00"


def test_on_response_ready_prefers_llm_promises_over_user_fallback():
    dummy = type("BridgeDummy", (), {})()
    _attach_bridge_promise_helpers(dummy)
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = [("user", "3분 뒤 일기 써야지", "2026-04-06 21:00")]
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
        (role, text, timestamp or "2026-04-06 21:00")
    )
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._store_scheduled_promises = lambda items: WebBridge._store_scheduled_promises(dummy, items)
    dummy._maybe_store_user_promise_candidates = (
        lambda scheduled_promises=None: (_ for _ in ()).throw(
            AssertionError("LLM 약속이 있으면 user fallback이 돌면 안 됩니다.")
        )
    )
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []

    WebBridge._on_response_ready(
        dummy,
        "좋아, 이따 다시 이야기하자.",
        "smile",
        "",
        [],
        "",
        "",
        [
            {
                "title": "일기 쓰기",
                "trigger_at": "2026-04-06T21:03:00+09:00",
                "source": "user",
                "source_excerpt": "3분 뒤 일기 써야지",
            }
        ],
    )

    assert len(dummy.promise_manager.added) == 1
    assert dummy.promise_manager.added[0]["title"] == "일기 쓰기"


def test_on_response_ready_tracks_new_promise_ids_on_last_request_payload():
    dummy = type("BridgeDummy", (), {})()
    _attach_bridge_promise_helpers(dummy)
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_notice = _DummySignal()
    dummy.promise_items_updated = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.conversation_buffer = [("user", "3분 뒤 일기 써야지", "2026-04-06 21:00")]
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
    dummy._last_request_payload = {"type": "text", "message": "3분 뒤 일기 써야지"}
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._sanitize_visible_response_text = lambda text: text
    dummy._resolve_token_usage_payload = lambda payload="": payload
    dummy._append_conversation = lambda role, text, timestamp=None: dummy.conversation_buffer.append(
        (role, text, timestamp or "2026-04-06 21:00")
    )
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._check_auto_summarize = lambda: None
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)
    dummy._drain_promise_queue_if_idle = lambda: None
    dummy._store_scheduled_promises = lambda items: WebBridge._store_scheduled_promises(dummy, items)
    dummy._maybe_store_user_promise_candidates = lambda scheduled_promises=None: []
    dummy._maybe_store_assistant_promise_candidates = lambda source_text: []

    WebBridge._on_response_ready(
        dummy,
        "좋아, 이따 다시 이야기하자.",
        "smile",
        "",
        [],
        "",
        "",
        [
            {
                "title": "일기 쓰기",
                "trigger_at": "2026-04-06T21:03:00+09:00",
                "source": "user",
                "source_excerpt": "3분 뒤 일기 써야지",
            }
        ],
    )

    assert dummy._last_request_payload["promise_ids"] == ["id-1"]


def test_reroll_last_response_deletes_only_tracked_promises():
    dummy = type("BridgeDummy", (), {})()
    _attach_bridge_promise_helpers(dummy)
    dummy.llm_client = _DummyLlmClient()
    dummy.worker = None
    dummy.promise_manager = _DummyPromiseManager()
    dummy.reroll_state_changed = _DummySignal()
    dummy.summary_notice = _DummySignal()
    dummy.conversation_buffer = [
        ("user", "3분 뒤 일기 써야지", "2026-04-06 21:00"),
        ("assistant", "좋아, 이따 다시 이야기하자.", "2026-04-06 21:00"),
    ]
    dummy._last_request_payload = {
        "type": "text",
        "message": "3분 뒤 일기 써야지",
        "message_with_time": "[현재 시각: 2026-04-06 21:00]\n3분 뒤 일기 써야지",
        "images": [],
        "memory_search_text": "",
        "promise_ids": ["tracked-1"],
    }
    dummy._is_rerolling = False
    dummy._reset_pending_ui_state = lambda notice="": None
    dummy._emit_promise_items_updated_calls = []
    dummy._emit_promise_items_updated = lambda: dummy._emit_promise_items_updated_calls.append(True)
    dummy._rollback_last_turn_pair_for_retry = lambda: WebBridge._rollback_last_turn_pair_for_retry(dummy)
    started = []
    dummy._start_ai_worker = lambda message_with_time, images=None, memory_search_text="": started.append(
        {
            "message_with_time": message_with_time,
            "images": images or [],
            "memory_search_text": memory_search_text,
        }
    )

    dummy.promise_manager.add_promise(
        id="tracked-1",
        title="일기 쓰기",
        trigger_at="2026-04-06T21:03:00+09:00",
        source="user",
        source_excerpt="3분 뒤 일기 써야지",
        status="scheduled",
    )
    dummy.promise_manager.add_promise(
        id="keep-1",
        title="다른 예약",
        trigger_at="2026-04-06T22:00:00+09:00",
        source="user",
        source_excerpt="다른 예약",
        status="scheduled",
    )

    WebBridge.reroll_last_response(dummy)

    assert dummy.promise_manager.deleted == ["tracked-1"]
    assert [item["id"] for item in dummy.promise_manager.items] == ["keep-1"]
    assert dummy._last_request_payload["promise_ids"] == []
    assert dummy.reroll_state_changed.emitted[-1] == (True,)
    assert started == [
        {
            "message_with_time": "[현재 시각: 2026-04-06 21:00]\n3분 뒤 일기 써야지",
            "images": [],
            "memory_search_text": "",
        }
    ]


def test_enqueue_due_promise_skips_duplicate_signature_already_in_queue():
    dummy = type("BridgeDummy", (), {})()
    _attach_bridge_promise_helpers(dummy)
    dummy.worker = _RunningWorker()
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_items_updated = _DummySignal()
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)
    dummy.promise_run_queue = [
        {
            "id": "queued-1",
            "title": "기업 조사",
            "trigger_at": "2026-04-08T20:00:00+09:00",
            "source_excerpt": "8시에 기업 조사 시작",
        }
    ]
    dummy._active_promise_signature = None
    dummy._recent_promise_fire_signatures = {}
    dummy._current_promise_fire_time = lambda: __import__("datetime").datetime(2026, 4, 8, 20, 0, 0)
    dummy._start_promise_ai_worker = lambda payload: (_ for _ in ()).throw(AssertionError("중복이면 시작되면 안 됩니다."))

    dummy.promise_manager.add_promise(
        id="dup-1",
        title="기업 조사",
        trigger_at="2026-04-08T20:00:00+09:00",
        source="assistant",
        source_excerpt="정각 8시예요",
        status="scheduled",
    )

    WebBridge._enqueue_due_promise(
        dummy,
        {
            "id": "dup-1",
            "title": "기업 조사",
            "trigger_at": "2026-04-08T20:00:00+09:00",
            "source_excerpt": "정각 8시예요",
        },
    )

    assert [item["id"] for item in dummy.promise_run_queue] == ["queued-1"]
    assert dummy.promise_manager.deleted == ["dup-1"]


def test_enqueue_due_promise_skips_recently_fired_duplicate_signature():
    dummy = type("BridgeDummy", (), {})()
    _attach_bridge_promise_helpers(dummy)
    dummy.worker = None
    dummy.promise_manager = _DummyPromiseManager()
    dummy.promise_items_updated = _DummySignal()
    dummy._emit_promise_items_updated = lambda: WebBridge._emit_promise_items_updated(dummy)
    dummy.promise_run_queue = []
    dummy._active_promise_signature = None
    dummy._recent_promise_fire_signatures = {
        "기업 조사|2026-04-08T20:00": __import__("datetime").datetime(2026, 4, 8, 20, 0, 0)
    }
    dummy._current_promise_fire_time = lambda: __import__("datetime").datetime(2026, 4, 8, 20, 4, 0)
    started = []
    dummy._start_promise_ai_worker = lambda payload: started.append(payload)

    dummy.promise_manager.add_promise(
        id="dup-2",
        title="기업 조사",
        trigger_at="2026-04-08T20:00:00+09:00",
        source="assistant",
        source_excerpt="8시 정각이에요",
        status="scheduled",
    )

    WebBridge._enqueue_due_promise(
        dummy,
        {
            "id": "dup-2",
            "title": "기업 조사",
            "trigger_at": "2026-04-08T20:00:00+09:00",
            "source_excerpt": "8시 정각이에요",
        },
    )

    assert started == []
    assert dummy.promise_manager.deleted == ["dup-2"]
