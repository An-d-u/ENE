import json

from src.ai.ene_goal_manager import EneGoalManager


class _Settings:
    def __init__(self, **config):
        self.config = config


def test_apply_create_adds_active_short_term_goal(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))

    snapshot = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "릴리즈 체크리스트 정리",
            "reason": "사용자가 이번 작업을 마무리하려고 함",
        }
    )

    goals = snapshot["active"]["short_term"]
    assert len(goals) == 1
    assert goals[0]["id"].startswith("goal_")
    assert goals[0]["type"] == "short_term"
    assert goals[0]["title"] == "릴리즈 체크리스트 정리"
    assert goals[0]["reason"] == "사용자가 이번 작업을 마무리하려고 함"
    assert goals[0]["source"] == "llm"
    assert snapshot["active"]["long_term"] == []
    assert snapshot["history"] == []


def test_create_truncates_long_title_and_reason(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    long_title = "제목" * 80
    long_reason = "이유" * 180

    snapshot = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": long_title,
            "reason": long_reason,
        }
    )

    goal = snapshot["active"]["short_term"][0]
    assert goal["title"] == long_title[:120]
    assert goal["reason"] == long_reason[:300]


def test_llm_create_requires_non_empty_reason(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    before = manager.get_snapshot()

    missing_reason = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "이유 없는 목표",
        }
    )
    empty_reason = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "빈 이유 목표",
            "reason": "   ",
        }
    )

    assert missing_reason == before
    assert empty_reason == before


def test_apply_complete_moves_goal_to_history(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    created = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "테스트 통과 확인",
            "reason": "작업 완료 조건",
        }
    )
    goal_id = created["active"]["short_term"][0]["id"]

    snapshot = manager.apply_llm_update(
        {"action": "complete", "id": goal_id, "completion_reason": "검증 완료"}
    )

    assert snapshot["active"]["short_term"] == []
    assert len(snapshot["history"]) == 1
    assert snapshot["history"][0]["id"] == goal_id
    assert snapshot["history"][0]["status"] == "completed"
    assert snapshot["history"][0]["completion_reason"] == "검증 완료"


def test_complete_and_cancel_truncate_long_completion_reason(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    long_reason = "완료사유" * 100
    completed = manager.add_manual_goal("short_term", "완료할 목표", "")
    completed_id = completed["active"]["short_term"][0]["id"]
    cancelled = manager.add_manual_goal("long_term", "취소할 목표", "")
    cancelled_id = cancelled["active"]["long_term"][0]["id"]

    manager.complete_goal(completed_id, long_reason)
    snapshot = manager.cancel_goal(cancelled_id, long_reason)

    history_by_id = {goal["id"]: goal for goal in snapshot["history"]}
    assert history_by_id[completed_id]["completion_reason"] == long_reason[:300]
    assert history_by_id[cancelled_id]["completion_reason"] == long_reason[:300]


def test_llm_complete_validates_provided_goal_type(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    created = manager.add_manual_goal("short_term", "완료할 단기 목표", "")
    goal_id = created["active"]["short_term"][0]["id"]

    invalid_type = manager.apply_llm_update(
        {"action": "complete", "id": goal_id, "type": "daily", "completion_reason": "무시"}
    )
    mismatched_type = manager.apply_llm_update(
        {"action": "complete", "id": goal_id, "type": "long_term", "completion_reason": "무시"}
    )
    completed = manager.apply_llm_update(
        {"action": "complete", "id": goal_id, "type": "short_term", "completion_reason": "완료"}
    )

    assert invalid_type == created
    assert mismatched_type == created
    assert completed["active"]["short_term"] == []
    assert completed["history"][0]["id"] == goal_id
    assert completed["history"][0]["status"] == "completed"


def test_llm_cancel_validates_provided_goal_type_and_allows_empty_type(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    first = manager.add_manual_goal("long_term", "취소할 장기 목표", "")
    first_id = first["active"]["long_term"][0]["id"]

    invalid_type = manager.apply_llm_update(
        {"action": "cancel", "id": first_id, "type": "daily", "completion_reason": "무시"}
    )
    mismatched_type = manager.apply_llm_update(
        {"action": "cancel", "id": first_id, "type": "short_term", "completion_reason": "무시"}
    )
    matching_type = manager.apply_llm_update(
        {"action": "cancel", "id": first_id, "type": "long_term", "completion_reason": "취소"}
    )

    second = manager.add_manual_goal("short_term", "타입 없이 취소할 목표", "")
    second_id = second["active"]["short_term"][0]["id"]
    cancelled = manager.apply_llm_update(
        {"action": "cancel", "id": second_id, "type": "", "completion_reason": "취소"}
    )

    assert invalid_type == first
    assert mismatched_type == first
    assert any(goal["id"] == first_id and goal["status"] == "cancelled" for goal in matching_type["history"])
    assert any(goal["id"] == second_id and goal["status"] == "cancelled" for goal in cancelled["history"])


def test_apply_none_changes_nothing(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    before = manager.add_manual_goal("short_term", "기존 목표", "유지")

    after = manager.apply_llm_update({"action": "none", "type": "bad"})

    assert after == before


def test_apply_update_existing_goal_edits_fields_and_keeps_active(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    created = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "초안 작성",
            "reason": "처음 이유",
        }
    )
    goal = created["active"]["short_term"][0]
    manager._now_iso = lambda: "2099-01-01T00:00:00"

    snapshot = manager.apply_llm_update(
        {
            "action": "update",
            "id": goal["id"],
            "title": "초안 다듬기",
            "reason": "범위가 더 명확해짐",
        }
    )

    updated = snapshot["active"]["short_term"][0]
    assert updated["id"] == goal["id"]
    assert updated["title"] == "초안 다듬기"
    assert updated["reason"] == "범위가 더 명확해짐"
    assert updated["updated_at"] == "2099-01-01T00:00:00"
    assert updated["source"] == "llm"
    assert snapshot["history"] == []


def test_apply_update_truncates_long_fields_and_keeps_goal_active(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    created = manager.add_manual_goal("short_term", "초기 제목", "초기 이유")
    goal_id = created["active"]["short_term"][0]["id"]
    long_title = "수정제목" * 40
    long_reason = "수정이유" * 100

    snapshot = manager.apply_llm_update(
        {
            "action": "update",
            "id": goal_id,
            "title": long_title,
            "reason": long_reason,
        }
    )

    active_goals = snapshot["active"]["short_term"]
    assert len(active_goals) == 1
    assert active_goals[0]["id"] == goal_id
    assert active_goals[0]["title"] == long_title[:120]
    assert active_goals[0]["reason"] == long_reason[:300]
    assert snapshot["history"] == []


def test_update_to_duplicate_same_type_title_is_ignored(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    first = manager.add_manual_goal("short_term", "기존, 목표!", "첫 번째")
    first_id = first["active"]["short_term"][0]["id"]
    second = manager.add_manual_goal("short_term", "다른 목표", "두 번째")
    second_id = second["active"]["short_term"][1]["id"]

    snapshot = manager.update_goal(second_id, {"title": "기존 목표", "reason": "바꾸면 안 됨"})

    assert snapshot == second
    goals_by_id = {goal["id"]: goal for goal in snapshot["active"]["short_term"]}
    assert goals_by_id[first_id]["title"] == "기존, 목표!"
    assert goals_by_id[second_id]["title"] == "다른 목표"
    assert goals_by_id[second_id]["reason"] == "두 번째"


def test_update_to_same_normalized_title_of_itself_is_allowed(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    created = manager.add_manual_goal("short_term", "자기 목표!", "처음")
    goal_id = created["active"]["short_term"][0]["id"]
    manager._now_iso = lambda: "2099-01-01T00:00:00"

    snapshot = manager.update_goal(goal_id, {"title": "자기 목표", "reason": "수정"})

    goal = snapshot["active"]["short_term"][0]
    assert goal["id"] == goal_id
    assert goal["title"] == "자기 목표"
    assert goal["reason"] == "수정"
    assert goal["updated_at"] == "2099-01-01T00:00:00"


def test_update_allows_duplicate_title_in_different_goal_type(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    manager.add_manual_goal("short_term", "공유 목표", "단기")
    long_term = manager.add_manual_goal("long_term", "장기 목표", "장기")
    long_id = long_term["active"]["long_term"][0]["id"]

    snapshot = manager.update_goal(long_id, {"title": "공유 목표"})

    assert snapshot["active"]["short_term"][0]["title"] == "공유 목표"
    assert snapshot["active"]["long_term"][0]["title"] == "공유 목표"


def test_returned_snapshot_mutation_does_not_mutate_goal_manager_state(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    snapshot = manager.add_manual_goal("short_term", "스냅샷 보호", "원본")
    goal_id = snapshot["active"]["short_term"][0]["id"]

    snapshot["active"]["short_term"][0]["title"] = "외부 변경"
    snapshot["history"].append({"id": "fake"})

    fresh = manager.get_snapshot()
    assert fresh["active"]["short_term"][0]["id"] == goal_id
    assert fresh["active"]["short_term"][0]["title"] == "스냅샷 보호"
    assert fresh["history"] == []


def test_apply_update_missing_id_or_fields_returns_unchanged_snapshot(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    before = manager.add_manual_goal("short_term", "수정하지 않을 목표", "그대로")

    assert manager.apply_llm_update({"action": "update", "title": "무시"}) == before
    assert manager.apply_llm_update({"action": "update", "id": "missing"}) == before


def test_duplicate_normalized_title_does_not_create_second_active_goal(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    first = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "  릴리즈, 체크리스트! 정리  ",
            "reason": "처음 이유",
        }
    )
    goal = first["active"]["short_term"][0]
    manager._now_iso = lambda: "2099-01-01T00:00:00"

    snapshot = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "릴리즈 체크리스트 정리",
            "reason": "새 이유",
        }
    )

    goals = snapshot["active"]["short_term"]
    assert len(goals) == 1
    assert goals[0]["id"] == goal["id"]
    assert goals[0]["title"] == goal["title"]
    assert goals[0]["reason"] == "새 이유"
    assert goals[0]["updated_at"] == "2099-01-01T00:00:00"


def test_cancel_moves_goal_to_history_with_cancelled_status(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    created = manager.add_manual_goal("long_term", "장기 방향 유지", "사용자 선호")
    goal_id = created["active"]["long_term"][0]["id"]

    snapshot = manager.cancel_goal(goal_id, "더 이상 필요 없음")

    assert snapshot["active"]["long_term"] == []
    assert snapshot["history"][0]["id"] == goal_id
    assert snapshot["history"][0]["status"] == "cancelled"
    assert snapshot["history"][0]["completion_reason"] == "더 이상 필요 없음"


def test_disabled_settings_ignore_llm_updates_and_context(tmp_path):
    manager = EneGoalManager(
        state_file=str(tmp_path / "ene_goals.json"),
        settings=_Settings(enable_ene_goals=False),
    )

    snapshot = manager.apply_llm_update(
        {
            "action": "create",
            "type": "short_term",
            "title": "무시될 목표",
            "reason": "기능 꺼짐",
        }
    )

    assert snapshot == {
        "version": 1,
        "active": {"long_term": [], "short_term": []},
        "history": [],
    }
    assert manager.build_context_block() == ""


def test_build_context_block_includes_active_goal_fields(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    snapshot = manager.add_manual_goal("short_term", "컨텍스트에 넣기", "LLM에게 알려야 함")
    goal_id = snapshot["active"]["short_term"][0]["id"]

    block = manager.build_context_block()

    assert "[에네 현재 목표]" in block
    assert f"id={goal_id}" in block
    assert "type=short_term" in block
    assert "title=컨텍스트에 넣기" in block
    assert "reason=LLM에게 알려야 함" in block
    assert "[/에네 현재 목표]" in block


def test_build_context_block_uses_custom_assistant_name(tmp_path):
    manager = EneGoalManager(
        state_file=str(tmp_path / "ene_goals.json"),
        settings={
            "ui_language": "en",
            "assistant_display_name": "Luna",
            "enable_ene_goals": True,
        },
    )
    manager.add_manual_goal("short_term", "Ship", "Prepare release")

    block = manager.build_context_block(language="en")

    assert "[Luna Current Goals]" in block
    assert "[ENE Current Goals]" not in block


def test_corrupted_state_file_falls_back_to_default_structure(tmp_path):
    state_file = tmp_path / "ene_goals.json"
    state_file.write_text("{ broken", encoding="utf-8-sig")

    manager = EneGoalManager(state_file=str(state_file))

    assert manager.get_snapshot() == {
        "version": 1,
        "active": {"long_term": [], "short_term": []},
        "history": [],
    }


def test_settings_state_file_is_used_when_explicit_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ENE_USER_DATA_DIR", str(tmp_path))
    manager = EneGoalManager(settings=_Settings(ene_goal_state_file="custom_goals.json"))

    manager.add_manual_goal("short_term", "설정 경로 사용", "")

    saved_path = tmp_path / "custom_goals.json"
    assert not saved_path.read_bytes().startswith(b"\xef\xbb\xbf")
    saved = json.loads(saved_path.read_text(encoding="utf-8-sig"))
    assert saved["active"]["short_term"][0]["title"] == "설정 경로 사용"


def test_invalid_update_inputs_return_unchanged_snapshot(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    before = manager.get_snapshot()

    assert manager.apply_llm_update({"action": "unknown"}) == before
    assert manager.apply_llm_update({"action": "create", "type": "short_term"}) == before
    assert manager.apply_llm_update({"action": "create", "type": "bad", "title": "x"}) == before
    assert manager.apply_llm_update({"action": "complete"}) == before


def test_list_history_returns_most_recent_limited_items(tmp_path):
    manager = EneGoalManager(state_file=str(tmp_path / "ene_goals.json"))
    first = manager.add_manual_goal("short_term", "첫 번째", "")
    manager.complete_goal(first["active"]["short_term"][0]["id"], "")
    second = manager.add_manual_goal("short_term", "두 번째", "")
    manager.cancel_goal(second["active"]["short_term"][0]["id"], "")

    history = manager.list_history(limit=1)

    assert len(history) == 1
    assert history[0]["title"] == "두 번째"
