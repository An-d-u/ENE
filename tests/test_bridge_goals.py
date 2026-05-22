import json

from src.core.bridge import AIWorker, WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _DummyGoalManager:
    def __init__(self):
        self.calls = []
        self.snapshot = {
            "version": 1,
            "active": {"short_term": [{"id": "goal_1", "title": "물 마시기"}], "long_term": []},
            "history": [],
        }

    def apply_llm_update(self, update):
        self.calls.append(("apply_llm_update", update))
        return self.snapshot

    def get_snapshot(self):
        self.calls.append(("get_snapshot",))
        return self.snapshot

    def add_manual_goal(self, goal_type, title, reason):
        self.calls.append(("add_manual_goal", goal_type, title, reason))
        return self.snapshot

    def update_goal(self, goal_id, fields):
        self.calls.append(("update_goal", goal_id, fields))
        return self.snapshot

    def complete_goal(self, goal_id, reason):
        self.calls.append(("complete_goal", goal_id, reason))
        return self.snapshot

    def cancel_goal(self, goal_id, reason):
        self.calls.append(("cancel_goal", goal_id, reason))
        return self.snapshot


def _response_ready_dummy(goal_manager=None):
    dummy = type("BridgeDummy", (), {})()
    dummy._last_assistant_response = None
    dummy.mood_manager = None
    dummy.goal_manager = goal_manager
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._append_conversation = lambda role, text: setattr(dummy, "appended", (role, text))
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy.goal_items_updated = _DummySignal()
    dummy.goal_notice = _DummySignal()
    dummy._is_rerolling = False
    dummy.reroll_state_changed = _DummySignal()
    dummy._check_auto_summarize = lambda: None
    dummy._resolve_token_usage_payload = lambda payload="": payload or "{}"
    dummy._sanitize_visible_response_text = lambda text: WebBridge._sanitize_visible_response_text(dummy, text)
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._collect_promise_ids = lambda items=None: []
    dummy._emit_goal_items_updated = lambda snapshot=None: WebBridge._emit_goal_items_updated(dummy, snapshot)
    return dummy


def test_on_response_ready_applies_goal_update_and_emits_fresh_snapshot():
    manager = _DummyGoalManager()
    dummy = _response_ready_dummy(goal_manager=manager)

    WebBridge._on_response_ready(
        dummy,
        "오늘은 물부터 챙겨요.",
        "smile",
        "",
        [],
        "",
        "",
        [],
        "",
        json.dumps(
            {"action": "create", "type": "short_term", "title": "물 마시기", "reason": "컨디션 관리"},
            ensure_ascii=False,
        ),
    )

    assert manager.calls == [
        (
            "apply_llm_update",
            {"action": "create", "type": "short_term", "title": "물 마시기", "reason": "컨디션 관리"},
        )
    ]
    assert dummy.goal_items_updated.emitted == [(json.dumps(manager.snapshot, ensure_ascii=False),)]
    assert dummy.message_received.emitted == [("오늘은 물부터 챙겨요.", "smile", "")]


def test_on_response_ready_continues_message_emit_without_goal_manager_or_payload():
    dummy = _response_ready_dummy(goal_manager=None)

    WebBridge._on_response_ready(dummy, "그대로 보여줄 응답", "normal", "", [])

    assert dummy.message_received.emitted == [("그대로 보여줄 응답", "normal", "")]
    assert dummy.goal_items_updated.emitted == []


def test_sanitize_visible_response_text_removes_leaked_goal_update_block():
    dummy = type("BridgeDummy", (), {})()

    sanitized = WebBridge._sanitize_visible_response_text(
        dummy,
        "좋아요.\n[ene_goal_update]\naction=create\ntype=short_term\ntitle=물 마시기\nreason=건강\n[/ene_goal_update]\n계속 갈게요.",
    )

    assert sanitized == "좋아요.\n계속 갈게요."


def test_sanitize_visible_response_text_removes_unclosed_goal_update_block_to_end():
    dummy = type("BridgeDummy", (), {})()

    sanitized = WebBridge._sanitize_visible_response_text(
        dummy,
        "좋아요.\n[ene_goal_update]\naction=create\ntitle=보이면 안 됨\nreason=닫는 태그 없음",
    )

    assert sanitized == "좋아요."
    assert "보이면 안 됨" not in sanitized


def test_manual_goal_slots_call_manager_and_emit_snapshots():
    manager = _DummyGoalManager()
    dummy = type("BridgeDummy", (), {})()
    dummy.goal_manager = manager
    dummy.goal_items_updated = _DummySignal()
    dummy.goal_notice = _DummySignal()

    WebBridge.request_goal_items(dummy)
    WebBridge.add_manual_goal(dummy, "short_term", "스트레칭", "몸 풀기")
    WebBridge.update_goal_item(dummy, "goal_1", "물 마시기", "컨디션 관리")
    WebBridge.complete_goal_item(dummy, "goal_1", "완료")
    WebBridge.cancel_goal_item(dummy, "goal_2", "보류")

    assert manager.calls == [
        ("get_snapshot",),
        ("add_manual_goal", "short_term", "스트레칭", "몸 풀기"),
        ("update_goal", "goal_1", {"title": "물 마시기", "reason": "컨디션 관리"}),
        ("complete_goal", "goal_1", "완료"),
        ("cancel_goal", "goal_2", "보류"),
    ]
    assert dummy.goal_items_updated.emitted == [(json.dumps(manager.snapshot, ensure_ascii=False),)] * 5
    assert dummy.goal_notice.emitted == []


def test_ai_worker_normalize_response_payload_returns_goal_update_for_new_and_legacy_shapes():
    worker = AIWorker.__new__(AIWorker)

    assert AIWorker._normalize_response_payload(
        worker,
        ("본문", "smile", "TTS", [], {"user_intent": "plan"}, [{"title": "쉬기"}], "속마음", {"action": "none"}),
    ) == (
        "본문",
        "smile",
        "TTS",
        [],
        {"user_intent": "plan"},
        [{"title": "쉬기"}],
        "속마음",
        {"action": "none"},
    )
    assert AIWorker._normalize_response_payload(
        worker,
        ("본문", "smile", "TTS", [], {"user_intent": "plan"}, [{"title": "쉬기"}], "속마음"),
    ) == (
        "본문",
        "smile",
        "TTS",
        [],
        {"user_intent": "plan"},
        [{"title": "쉬기"}],
        "속마음",
        {},
    )
    assert AIWorker._normalize_response_payload(
        worker,
        ("본문", "smile", "TTS", [], {"user_intent": "plan"}, [{"title": "쉬기"}]),
    ) == (
        "본문",
        "smile",
        "TTS",
        [],
        {"user_intent": "plan"},
        [{"title": "쉬기"}],
        "",
        {},
    )
