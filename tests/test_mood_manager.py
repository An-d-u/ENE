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


def test_repair_flow_recovers_from_guarded_state(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))

    rejected = manager.on_user_analysis(
        {
            "user_emotion": "angry",
            "user_intent": "complain",
            "interaction_effect": "negative",
            "bond_delta_hint": "low_negative",
            "valence_delta_hint": "low_negative",
            "stress_delta_hint": "high_positive",
            "energy_delta_hint": "none",
            "confidence": "0.9",
            "flags": "direct_rejection",
        }
    )
    repaired = manager.on_user_analysis(
        {
            "user_emotion": "sad",
            "user_intent": "seek_comfort",
            "interaction_effect": "positive",
            "bond_delta_hint": "low_positive",
            "valence_delta_hint": "none",
            "stress_delta_hint": "low_negative",
            "energy_delta_hint": "none",
            "confidence": "0.95",
            "flags": "needs_care",
        }
    )

    assert rejected["temporary_state"] == "guarded"
    assert repaired["temporary_state"] != "guarded"
    assert repaired["bond"] > rejected["bond"]
    assert repaired["stress"] < rejected["stress"]


def test_playful_teasing_with_joking_unclear_does_not_turn_into_pout(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))

    snapshot = manager.on_user_analysis(
        {
            "user_emotion": "playful",
            "user_intent": "tease",
            "interaction_effect": "mixed",
            "bond_delta_hint": "low_positive",
            "valence_delta_hint": "low_positive",
            "stress_delta_hint": "none",
            "energy_delta_hint": "low_positive",
            "confidence": "0.9",
            "flags": "joking_unclear",
        }
    )

    assert snapshot["temporary_state"] in {"playful", "steady"}
    assert snapshot["expression_traits"]["teasing"] >= 0.24
    assert snapshot["expression_traits"]["guardedness"] < 0.3


def test_tired_help_request_stays_warm_but_lowers_energy(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))

    snapshot = manager.on_user_analysis(
        {
            "user_emotion": "tired",
            "user_intent": "ask_help",
            "interaction_effect": "positive",
            "bond_delta_hint": "low_positive",
            "valence_delta_hint": "none",
            "stress_delta_hint": "low_positive",
            "energy_delta_hint": "low_negative",
            "confidence": "0.92",
            "flags": "late_night",
        }
    )

    assert snapshot["energy"] < 0
    assert snapshot["expression_traits"]["warmth"] > 0.55
    assert snapshot["expression_traits"]["reply_length_bias"] < snapshot["expression_traits"]["warmth"]


def test_noncanonical_analysis_values_are_normalized_into_visible_tired_state(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))

    snapshot = manager.on_user_analysis(
        {
            "user_emotion": "calm, tired",
            "user_intent": "greeting_and_check_status",
            "interaction_effect": "positive",
            "bond_delta_hint": "low_positive",
            "valence_delta_hint": "low_positive",
            "stress_delta_hint": "none",
            "energy_delta_hint": "none",
            "confidence": "high",
            "flags": "interaction_start",
        }
    )

    assert snapshot["current_mood"] == "tired"
    assert snapshot["temporary_state"] == "drained"
    assert snapshot["bond"] > 0.22
    assert snapshot["valence"] > 0.10


def test_repeated_positive_affection_can_escape_calm_label(tmp_path):
    manager = MoodManager(state_file=str(tmp_path / "mood.json"))
    meta = {
        "user_emotion": "affectionate",
        "user_intent": "affection",
        "interaction_effect": "positive",
        "bond_delta_hint": "high_positive",
        "valence_delta_hint": "low_positive",
        "stress_delta_hint": "low_negative",
        "energy_delta_hint": "none",
        "confidence": "0.95",
        "flags": "",
    }

    snapshot = None
    for _ in range(4):
        snapshot = manager.on_user_analysis(meta)

    assert snapshot is not None
    assert snapshot["current_mood"] == "affectionate"
