"""검토 대기 상태와 실제 저장 실패의 재시도를 검증한다."""

import asyncio
import json
from types import SimpleNamespace
import pytest

from src.ai.ene_profile import EneProfile
from src.ai.memory import MemoryManager
from src.ai.user_profile import ProfileFact, UserProfile
from src.core.bridge_mixins.memory_summary import MemorySummaryBridgeMixin


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


def bridge_case(tmp_path):
    bridge = MemorySummaryBridgeMixin()
    bridge.memory_manager = MemoryManager(tmp_path / "memory.json")
    bridge.user_profile = UserProfile(tmp_path / "profile.json")
    bridge.user_profile.facts = [ProfileFact("은색 모형은 조립 중이다.", "goal", "2025-01-01", id="model", subject="은색 모형")]
    bridge.ene_profile = EneProfile(tmp_path / "ene.json", bridge.user_profile)
    bridge.knowledge_map_manager = None
    bridge.conversation_buffer = [("user", "은색 모형 조립을 끝냈다.", "2025-02-01")]
    update = dict(category="goal", content="은색 모형 조립을 끝냈다.", subject="은색 모형",
                  replaces="model", state="completed", assertion="current", evidence="은색 모형 조립을 끝냈다.")
    async def summarize(messages):
        return "모형 조립을 마쳤다.", ["[goal] 은색 모형 조립을 끝냈다."], [], {"profile_updates": [update]}, []
    bridge._summarize_conversation_with_loaded_topic_memory = summarize
    bridge.summary_review_ready = Signal()
    bridge.summary_review_finished = Signal()
    bridge.summary_notice = Signal()
    bridge._pending_summary_review = asyncio.run(bridge._build_summary_review_state(bridge.conversation_buffer))
    return bridge


def selected_payload(bridge):
    pending = bridge._pending_summary_review
    proposal = pending["profile_proposals"][0]
    return dict(review_id=pending["review_id"], summary=pending["summary"], user_facts=pending["user_facts"],
                ene_facts=pending["ene_facts"], memory_meta=pending["memory_meta"],
                profile_selections=[dict(proposal_id=proposal.proposal_id, selected=True)])


def persist(bridge, payload=None):
    payload = bridge._resolve_profile_review_payload(payload or selected_payload(bridge))
    return asyncio.run(bridge._persist_reviewed_summary(
        payload["summary"], payload["user_facts"], payload.get("ene_facts", []),
        payload["memory_meta"], payload.get("topic_hints", [])))


def test_ui_cannot_replace_server_target_or_forge_manual_edit(tmp_path):
    bridge = bridge_case(tmp_path)
    payload = selected_payload(bridge)
    payload["memory_meta"] = {"profile_updates": [{"replaces": "other", "manual_edit": True}]}
    payload["profile_selections"][0].update(replaces="other", fingerprint="forged", manual_edit=True)
    persist(bridge, payload)
    assert bridge.user_profile.facts[0].state == "completed"
    assert len(bridge.user_profile.facts) == 1


def test_stale_approval_does_not_save_summary(tmp_path):
    from src.ai.profile_review import StaleProfileReview
    bridge = bridge_case(tmp_path)
    payload = selected_payload(bridge)
    bridge.user_profile.facts[0].content = "별도 수정으로 상태가 달라졌다."
    with pytest.raises(StaleProfileReview):
        persist(bridge, payload)
    assert bridge.memory_manager.memories == []
    assert bridge.conversation_buffer


def test_embedding_wait_rechecks_target_before_append(tmp_path):
    from src.ai.profile_review import StaleProfileReview
    bridge = bridge_case(tmp_path)
    class Embedding:
        async def embed(self, text):
            bridge.user_profile.facts[0].content = "임베딩 중 반영된 별도 수정"
            return [1.0, 0.0]
    bridge.memory_manager.embedding_generator = Embedding()
    with pytest.raises(StaleProfileReview):
        persist(bridge)
    assert bridge.memory_manager.memories == []


def test_profile_disk_failure_retries_without_duplicate_summary_or_history(tmp_path, monkeypatch):
    bridge = bridge_case(tmp_path)
    import src.ai.user_profile as module
    original = module.save_json_data
    monkeypatch.setattr(module, "save_json_data", lambda *a, **kw: (_ for _ in ()).throw(OSError("합성 실패")))
    with pytest.raises(OSError):
        persist(bridge)
    assert len(bridge.memory_manager.memories) == 1
    assert len(bridge.user_profile.facts[0].history) == 1
    assert bridge._pending_summary_review["checkpoints"]["profile"]["status"] == "failed"
    monkeypatch.setattr(module, "save_json_data", original)
    persist(bridge)
    assert len(bridge.memory_manager.memories) == 1
    assert len(UserProfile(bridge.user_profile.profile_file).facts[0].history) == 1


def test_old_review_id_is_rejected_and_partial_cancel_is_honest(tmp_path):
    from src.ai.profile_review import StaleProfileReview
    bridge = bridge_case(tmp_path)
    payload = selected_payload(bridge)
    payload["review_id"] = "expired"
    with pytest.raises(StaleProfileReview):
        persist(bridge, payload)
    persist(bridge)
    bridge.cancel_summary_review()
    assert any("이미 저장" in str(values) for values in bridge.summary_notice.values)
    assert bridge._pending_summary_review is None
    assert bridge.conversation_buffer == []


def test_ene_strict_save_propagates_actual_disk_failure(tmp_path, monkeypatch):
    bridge = bridge_case(tmp_path)
    monkeypatch.setattr("src.ai.ene_profile.save_json_data", lambda *a, **kw: (_ for _ in ()).throw(OSError("합성 실패")))
    with pytest.raises(OSError):
        bridge.ene_profile.save(strict=True)


@pytest.mark.parametrize("stage", ["summary", "ene", "topic"])
def test_actual_storage_failures_leave_pending_and_retry_once(tmp_path, monkeypatch, stage):
    from src.ai.knowledge_map import KnowledgeMapManager
    bridge = bridge_case(tmp_path)
    bridge.knowledge_map_manager = KnowledgeMapManager(tmp_path / "topics.json")
    pending = bridge._pending_summary_review
    pending["ene_facts"] = ["[speaking_style] 합성 장면에서 차분한 어조로 안내한다."]
    pending["topic_hints"] = [dict(keyword="모형", subject="은색 모형", type="status_flow", state="completed",
                                    text="은색 모형 조립을 끝냈다.", assertion="current", evidence="은색 모형 조립을 끝냈다.")]
    modules = {"summary": "src.ai.memory", "ene": "src.ai.ene_profile", "topic": "src.ai.knowledge_map"}
    import importlib
    module = importlib.import_module(modules[stage])
    original = module.save_json_data
    def fail(*args, **kwargs):
        raise OSError("합성 영구 저장 실패")
    monkeypatch.setattr(module, "save_json_data", fail)
    payload = selected_payload(bridge)
    payload["topic_hints"] = pending["topic_hints"]
    with pytest.raises((OSError, RuntimeError)):
        persist(bridge, payload)
    assert bridge._pending_summary_review
    monkeypatch.setattr(module, "save_json_data", original)
    persist(bridge, payload)
    assert len(bridge.memory_manager.memories) == 1
    assert len(bridge.user_profile.facts[0].history) == 1
    assert len(bridge.ene_profile.facts) == 1
    assert json.loads((tmp_path / "topics.json").read_text(encoding="utf-8"))["topics"]
