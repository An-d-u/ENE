from datetime import datetime, timedelta, timezone

from src.ai.proactive_conversation_manager import DEFAULT_COOLDOWN_MINUTES, ProactiveConversationManager


KST = timezone(timedelta(hours=9))
BASE = datetime(2026, 5, 26, 21, 0, tzinfo=KST)


def _payload(**overrides):
    payload = {
        "trigger_at": (BASE + timedelta(minutes=5)).isoformat(timespec="seconds"),
        "title": "가벼운 확인",
        "generation_prompt": "합성 대화 흐름을 짧게 다시 이어가세요.",
        "source_excerpt": "합성 맥락 요약",
        "reason": "짧은 후속 대화가 자연스러운 합성 상황",
        "cooldown_key": "short-followup",
    }
    payload.update(overrides)
    return payload


def test_add_proactive_conversation_persists_and_roundtrips(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")

    item = manager.add_proactive_conversation(**_payload(), now=BASE)
    reloaded = ProactiveConversationManager(tmp_path / "proactive.json")

    assert item is not None
    assert item.status == "scheduled"
    assert item.cooldown_key == "short-followup"
    assert [stored.id for stored in reloaded.list_items()] == [item.id]


def test_invalid_cooldown_key_normalizes_to_global(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")

    item = manager.add_proactive_conversation(**_payload(cooldown_key="made-up-key"), now=BASE)

    assert item is not None
    assert item.cooldown_key == "global-proactive"


def test_add_rejects_invalid_trigger_ranges(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")

    assert manager.add_proactive_conversation(
        **_payload(trigger_at=(BASE - timedelta(minutes=1)).isoformat(timespec="seconds")),
        now=BASE,
    ) is None
    assert manager.add_proactive_conversation(
        **_payload(trigger_at=(BASE + timedelta(seconds=30)).isoformat(timespec="seconds")),
        now=BASE,
    ) is None
    assert manager.add_proactive_conversation(
        **_payload(trigger_at=(BASE + timedelta(minutes=61)).isoformat(timespec="seconds")),
        now=BASE,
    ) is None


def test_add_rejects_same_key_and_global_cooldown(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")

    first = manager.add_proactive_conversation(**_payload(), now=BASE)
    same_key = manager.add_proactive_conversation(
        **_payload(trigger_at=(BASE + timedelta(minutes=10)).isoformat(timespec="seconds")),
        now=BASE + timedelta(minutes=5),
    )
    different_key = manager.add_proactive_conversation(
        **_payload(
            trigger_at=(BASE + timedelta(minutes=15)).isoformat(timespec="seconds"),
            cooldown_key="topic-reopen",
        ),
        now=BASE + timedelta(minutes=5),
    )

    assert first is not None
    assert same_key is None
    assert different_key is None


def test_default_cooldown_is_twenty_minutes_at_boundary(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")

    first = manager.add_proactive_conversation(**_payload(), now=BASE)
    before_boundary = manager.add_proactive_conversation(
        **_payload(trigger_at=(BASE + timedelta(minutes=25)).isoformat(timespec="seconds")),
        now=BASE + timedelta(minutes=19, seconds=59),
    )
    at_boundary = manager.add_proactive_conversation(
        **_payload(trigger_at=(BASE + timedelta(minutes=30)).isoformat(timespec="seconds")),
        now=BASE + timedelta(minutes=20),
    )

    assert DEFAULT_COOLDOWN_MINUTES == 20
    assert first is not None
    assert before_boundary is None
    assert at_boundary is not None


def test_refresh_due_statuses_recovers_persisted_queued_items(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")
    item = manager.add_proactive_conversation(**_payload(), now=BASE)
    manager.set_status(item.id, "queued", now=BASE + timedelta(minutes=5))

    reloaded = ProactiveConversationManager(tmp_path / "proactive.json")
    due_items, expired_items = reloaded.refresh_due_statuses(now=BASE + timedelta(minutes=6))

    assert [entry.id for entry in due_items] == [item.id]
    assert expired_items == []


def test_cancel_scheduled_marks_pending_items_cancelled(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")
    item = manager.add_proactive_conversation(**_payload(), now=BASE)

    cancelled = manager.cancel_scheduled(now=BASE + timedelta(minutes=2))

    assert [entry.id for entry in cancelled] == [item.id]
    assert manager.list_items()[0].status == "cancelled"


def test_refresh_due_statuses_returns_due_and_expires_old_items(tmp_path):
    manager = ProactiveConversationManager(tmp_path / "proactive.json")
    due = manager.add_proactive_conversation(**_payload(), now=BASE)
    old = manager.add_proactive_conversation(
        **_payload(
            trigger_at=(BASE + timedelta(minutes=30)).isoformat(timespec="seconds"),
            cooldown_key="topic-reopen",
        ),
        now=BASE + timedelta(minutes=21),
    )

    due_items, expired_items = manager.refresh_due_statuses(now=BASE + timedelta(minutes=39))

    assert [item.id for item in due_items] == [old.id]
    assert [item.id for item in expired_items] == [due.id]
    statuses = {item.id: item.status for item in manager.list_items()}
    assert statuses[due.id] == "expired"
    assert statuses[old.id] == "scheduled"
