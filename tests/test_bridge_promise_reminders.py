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
