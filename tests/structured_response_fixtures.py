from copy import deepcopy
import json

from src.ai.response_envelope import ResponseRequirements


_BASE_ENVELOPE = {
    "reply": "중립 합성 답변",
    "emotion": "normal",
    "tts_text": "",
    "events": [],
    "analysis": {
        "user_emotion": "",
        "user_intent": "",
        "interaction_effect": "",
        "bond_delta_hint": "",
        "stress_delta_hint": "",
        "energy_delta_hint": "",
        "valence_delta_hint": "",
        "confidence": "",
        "flags": "",
    },
    "promises": [],
    "thought": "",
    "goal_update": {
        "action": "none",
        "type": "",
        "id": "",
        "title": "",
        "reason": "",
        "completion_reason": "",
    },
    "proactive_conversations": [],
    "gesture": "",
}


def make_valid_envelope(**overrides):
    payload = deepcopy(_BASE_ENVELOPE)
    payload.update(overrides)
    return payload


def valid_envelope_json(**overrides):
    return json.dumps(make_valid_envelope(**overrides), ensure_ascii=False)


def make_requirements(**overrides):
    values = {
        "response_language": "ko",
        "tts_language": "ko",
        "require_thought": False,
        "require_tts_text": False,
        "enable_analysis": False,
        "enable_events": False,
        "enable_promises": False,
        "enable_goal_update": False,
        "enable_proactive_conversations": False,
        "enable_gesture": False,
        "allowed_emotions": ("normal",),
        "allowed_proactive_cooldown_keys": ("synthetic",),
    }
    values.update(overrides)
    return ResponseRequirements(**values)


def no_repair_requirements():
    return make_requirements()


def thought_enabled_requirements():
    return make_requirements(require_thought=True)


def thought_and_tts_requirements():
    return make_requirements(
        tts_language="ja",
        require_thought=True,
        require_tts_text=True,
    )


def all_enabled_requirements():
    return make_requirements(
        require_thought=True,
        enable_analysis=True,
        enable_events=True,
        enable_promises=True,
        enable_goal_update=True,
        enable_proactive_conversations=True,
        enable_gesture=True,
    )


def repair_json(**fields):
    return json.dumps(fields, ensure_ascii=False)
