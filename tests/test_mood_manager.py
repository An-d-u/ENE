from src.ai.mood_manager import MoodManager


def test_repeated_positive_affection_meta_has_reduced_effect(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))
    meta = {
        "user_emotion": "affectionate",
        "user_intent": "affection",
        "bond_delta_hint": "high_positive",
        "valence_delta_hint": "low_positive",
        "stress_delta_hint": "low_negative",
        "energy_delta_hint": "none",
        "confidence": "0.95",
        "flags": "",
    }

    base_bond = manager.get_snapshot()["bond"]
    first = manager.on_user_analysis(meta)
    second = manager.on_user_analysis(meta)

    first_gain = first["bond"] - base_bond
    second_gain = second["bond"] - first["bond"]

    assert first_gain > 0
    assert second_gain > 0
    assert second_gain < first_gain


def test_snapshot_includes_temporary_state_and_expression_traits(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))
    manager.on_user_analysis(
        {
            "user_emotion": "playful",
            "user_intent": "tease",
            "bond_delta_hint": "low_positive",
            "energy_delta_hint": "low_positive",
            "valence_delta_hint": "low_positive",
            "stress_delta_hint": "none",
            "confidence": "0.90",
            "flags": "",
        }
    )

    snapshot = manager.get_snapshot()

    assert snapshot["temporary_state"] == "playful"
    assert "expression_traits" in snapshot
    assert snapshot["expression_traits"]["teasing"] > 0
    assert snapshot["expression_traits"]["warmth"] > 0


def test_context_block_includes_expression_guidance(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))
    manager.on_user_analysis(
        {
            "user_emotion": "tired",
            "user_intent": "ask_help",
            "bond_delta_hint": "low_positive",
            "energy_delta_hint": "low_negative",
            "valence_delta_hint": "none",
            "stress_delta_hint": "low_positive",
            "confidence": "0.92",
            "flags": "late_night",
        }
    )

    block = manager.build_context_block()

    assert "[ENE 표현 성향]" in block
    assert "[행동 지침]" in block
