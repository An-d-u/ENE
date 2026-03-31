"""
ENE 기분 상태 관리자.
LLM 분석 메타와 환경 신호를 기반으로 장기 기분과 단기 반응 성향을 관리한다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


class MoodManager:
    """장기 기분 상태를 저장/업데이트하는 매니저."""

    AXES = ("valence", "energy", "bond", "stress")

    PROFILE_BASELINES = {
        "calm": {"valence": 0.02, "energy": 0.00, "bond": 0.08, "stress": -0.02},
        "affectionate": {"valence": 0.10, "energy": 0.03, "bond": 0.22, "stress": -0.06},
        "playful": {"valence": 0.12, "energy": 0.18, "bond": 0.14, "stress": -0.02},
    }

    HINT_TO_DELTA = {
        "high_negative": -0.12,
        "low_negative": -0.05,
        "none": 0.0,
        "low_positive": 0.04,
        "high_positive": 0.10,
    }

    def __init__(self, state_file: str | Path | None = None, settings=None):
        target_file = state_file if state_file is not None else "mood_state.json"
        self.state_path = resolve_user_storage_path(target_file)
        self.settings = settings
        self.state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        try:
            loaded = load_json_data(self.state_path, encoding="utf-8")
            merged = self._default_state()
            merged.update(loaded)
            merged["axes"] = {**self._default_state()["axes"], **(loaded.get("axes") or {})}
            merged["recent_events"] = list(loaded.get("recent_events") or [])[:30]
            merged["temporary_state"] = str(loaded.get("temporary_state") or merged["temporary_state"])
            return merged
        except Exception as e:
            if self.state_path.exists():
                print(f"[Mood] 상태 로드 실패: {e}")
        return self._default_state()

    def _default_state(self) -> dict[str, Any]:
        profile = self._get_profile_name()
        baseline = self.PROFILE_BASELINES.get(profile, self.PROFILE_BASELINES["affectionate"])
        now = self._now_iso()
        return {
            "version": 2,
            "profile": profile,
            "axes": dict(baseline),
            "current_mood": "calm",
            "temporary_state": "steady",
            "updated_at": now,
            "recent_events": [],
        }

    def _save_state(self):
        try:
            save_json_data(
                self.state_path,
                self.state,
                encoding="utf-8",
                indent=2,
                ensure_ascii=False,
            )
        except Exception as e:
            print(f"[Mood] 상태 저장 실패: {e}")

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _get_profile_name(self) -> str:
        if self.settings and hasattr(self.settings, "config"):
            return str(self.settings.config.get("mood_personality_profile", "affectionate")).strip() or "affectionate"
        return "affectionate"

    def _get_decay_per_hour(self) -> float:
        base = 0.08
        if self.settings and hasattr(self.settings, "config"):
            base = float(self.settings.config.get("mood_decay_per_hour", base))
        return max(0.01, min(base, 0.5))

    def _get_speed_multiplier(self) -> float:
        speed = "normal"
        if self.settings and hasattr(self.settings, "config"):
            speed = str(self.settings.config.get("mood_update_speed", speed)).strip().lower()
        return {"slow": 0.7, "normal": 1.0, "fast": 1.4}.get(speed, 1.0)

    def _is_enabled(self) -> bool:
        if self.settings and hasattr(self.settings, "config"):
            return bool(self.settings.config.get("enable_mood_system", True))
        return True

    def _parse_time(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _clip(self, value: float) -> float:
        return max(-1.0, min(1.0, value))

    def _clip_unit(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def _scale_delta_by_axis_state(self, current: float, delta: float) -> float:
        if delta == 0.0:
            return 0.0
        if delta > 0:
            headroom = max(0.0, min(1.0, (1.0 - current) / 2.0))
        else:
            headroom = max(0.0, min(1.0, (1.0 + current) / 2.0))
        scale = 0.2 + (0.8 * headroom)
        return delta * scale

    def _parse_flags(self, raw_flags: str | list[str] | None) -> list[str]:
        if isinstance(raw_flags, list):
            return [str(flag).strip().lower() for flag in raw_flags if str(flag).strip()]
        if isinstance(raw_flags, str):
            return [flag.strip().lower() for flag in raw_flags.split(",") if flag.strip()]
        return []

    def _parse_confidence(self, value: str | float | None) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = 0.75
        parsed = max(0.0, min(1.0, parsed))
        return 0.35 + (0.65 * parsed)

    def _hint_value(self, key: str) -> float:
        return self.HINT_TO_DELTA.get(str(key or "none").strip().lower(), 0.0)

    def _add_event(self, source: str, reason: str, deltas: dict[str, float], meta: dict[str, Any] | None = None):
        item = {
            "time": self._now_iso(),
            "source": source,
            "reason": reason,
            "delta": {k: round(v, 4) for k, v in deltas.items() if abs(v) > 0.0001},
        }
        if meta:
            item["meta"] = meta
        self.state["recent_events"].append(item)
        self.state["recent_events"] = self.state["recent_events"][-30:]

    def _recent_events(self, source: str | None = None, limit: int = 6) -> list[dict[str, Any]]:
        events = list(self.state.get("recent_events", []))
        if source:
            events = [item for item in events if item.get("source") == source]
        return events[-limit:]

    def _get_repeat_scale(self, intent: str, flags: list[str]) -> float:
        if not intent:
            intent = "unknown"
        recent = self._recent_events(source="user_analysis", limit=5)
        same_intent_count = 0
        for event in recent:
            meta = event.get("meta") or {}
            if str(meta.get("user_intent", "")).strip().lower() == intent:
                same_intent_count += 1

        scale = 1.0 - (same_intent_count * 0.22)
        if "repeated_affection" in flags:
            scale -= 0.15
        if "repeated_praise" in flags:
            scale -= 0.10
        return max(0.35, scale)

    def _apply_decay(self):
        now = datetime.now()
        last = self._parse_time(self.state.get("updated_at"))
        if last is None:
            self.state["updated_at"] = self._now_iso()
            return

        elapsed_hours = max(0.0, (now - last).total_seconds() / 3600.0)
        if elapsed_hours <= 0:
            return

        profile = self._get_profile_name()
        baseline = self.PROFILE_BASELINES.get(profile, self.PROFILE_BASELINES["affectionate"])
        decay_factor = min(0.85, self._get_decay_per_hour() * elapsed_hours)

        axes = self.state.get("axes", {})
        for axis in self.AXES:
            current = float(axes.get(axis, 0.0))
            target = float(baseline.get(axis, 0.0))
            axes[axis] = self._clip(current + (target - current) * decay_factor)

        if elapsed_hours >= 1.5 and self.state.get("temporary_state") in {"pout", "guarded", "playful", "focused"}:
            self.state["temporary_state"] = "steady"

        self.state["profile"] = profile
        self.state["updated_at"] = self._now_iso()

    def _apply_deltas(self, deltas: dict[str, float]):
        axes = self.state.get("axes", {})
        for axis, delta in deltas.items():
            if axis not in self.AXES:
                continue
            current = float(axes.get(axis, 0.0))
            scaled_delta = self._scale_delta_by_axis_state(current, float(delta))
            axes[axis] = self._clip(current + scaled_delta)
        self.state["current_mood"] = self._infer_mood_label()
        self.state["updated_at"] = self._now_iso()

    def _infer_mood_label(self) -> str:
        axes = self.state.get("axes", {})
        valence = float(axes.get("valence", 0.0))
        energy = float(axes.get("energy", 0.0))
        bond = float(axes.get("bond", 0.0))
        stress = float(axes.get("stress", 0.0))
        temporary_state = self.state.get("temporary_state", "steady")

        if stress >= 0.45 or temporary_state == "guarded":
            return "tense"
        if temporary_state == "pout":
            return "sensitive"
        if energy <= -0.35 or temporary_state == "drained":
            return "tired"
        if bond >= 0.55 and valence >= 0.15:
            return "affectionate"
        if valence >= 0.40 and energy >= 0.10:
            return "cheerful"
        return "calm"

    def _build_environment_deltas(self, text: str, image_count: int = 0) -> tuple[dict[str, float], list[str]]:
        deltas = {"valence": 0.0, "energy": 0.0, "bond": 0.0, "stress": 0.0}
        reasons: list[str] = []

        if "?" in text:
            deltas["energy"] += 0.02
            reasons.append("대화 집중")

        if len(text) >= 120:
            deltas["energy"] -= 0.03
            reasons.append("긴 대화 피로")

        now_hour = datetime.now().hour
        if now_hour >= 23 or now_hour < 6:
            deltas["energy"] -= 0.03
            deltas["stress"] += 0.02
            reasons.append("심야 시간대")

        if image_count > 0:
            deltas["bond"] += min(0.03, 0.01 + image_count * 0.006)
            deltas["valence"] += 0.01
            reasons.append("이미지 공유")

        mult = self._get_speed_multiplier()
        return ({axis: value * mult for axis, value in deltas.items()}, reasons)

    def _build_analysis_deltas(self, analysis: dict[str, Any], image_count: int = 0) -> tuple[dict[str, float], str]:
        flags = self._parse_flags(analysis.get("flags"))
        intent = str(analysis.get("user_intent", "")).strip().lower()
        confidence_scale = self._parse_confidence(analysis.get("confidence"))
        repeat_scale = self._get_repeat_scale(intent, flags)
        speed_scale = self._get_speed_multiplier()

        deltas = {
            "valence": self._hint_value(analysis.get("valence_delta_hint")),
            "energy": self._hint_value(analysis.get("energy_delta_hint")),
            "bond": self._hint_value(analysis.get("bond_delta_hint")),
            "stress": self._hint_value(analysis.get("stress_delta_hint")),
        }

        interaction_effect = str(analysis.get("interaction_effect", "")).strip().lower()
        if interaction_effect == "positive":
            deltas["valence"] += 0.01
            deltas["bond"] += 0.01
        elif interaction_effect == "negative":
            deltas["valence"] -= 0.02
            deltas["stress"] += 0.02
        elif interaction_effect == "mixed":
            deltas["stress"] += 0.01

        user_emotion = str(analysis.get("user_emotion", "")).strip().lower()
        if user_emotion in {"sad", "anxious", "tired"} and intent in {"ask_help", "seek_comfort"}:
            deltas["bond"] += 0.02
            deltas["stress"] -= 0.01
        if user_emotion == "playful" and intent == "tease":
            deltas["energy"] += 0.02

        if "late_night" in flags:
            deltas["energy"] -= 0.02
            deltas["stress"] += 0.02
        if "needs_care" in flags:
            deltas["bond"] += 0.01
        if "direct_rejection" in flags:
            deltas["bond"] -= 0.04
            deltas["stress"] += 0.04
        if "joking_unclear" in flags:
            deltas["stress"] *= 0.7
            deltas["valence"] *= 0.85

        env_deltas, env_reasons = self._build_environment_deltas("", image_count=image_count)
        for axis, value in env_deltas.items():
            deltas[axis] += value

        combined_scale = confidence_scale * repeat_scale * speed_scale
        deltas = {axis: value * combined_scale for axis, value in deltas.items()}

        reasons = [f"intent={intent or 'unknown'}", f"repeat={repeat_scale:.2f}", f"confidence={confidence_scale:.2f}"]
        reasons.extend(env_reasons)
        if flags:
            reasons.append("flags=" + ",".join(flags))
        return deltas, " / ".join(reasons)

    def _derive_temporary_state(self, analysis: dict[str, Any] | None = None) -> str:
        axes = self.state.get("axes", {})
        energy = float(axes.get("energy", 0.0))
        bond = float(axes.get("bond", 0.0))
        stress = float(axes.get("stress", 0.0))

        if analysis:
            flags = self._parse_flags(analysis.get("flags"))
            user_emotion = str(analysis.get("user_emotion", "")).strip().lower()
            intent = str(analysis.get("user_intent", "")).strip().lower()
            interaction_effect = str(analysis.get("interaction_effect", "")).strip().lower()

            if "direct_rejection" in flags:
                return "guarded"
            if intent == "tease" or user_emotion == "playful":
                return "playful"
            if interaction_effect in {"negative", "mixed"} and bond >= 0.2:
                return "pout"
            if intent in {"ask_help", "seek_comfort"}:
                return "focused"
            if "late_night" in flags or user_emotion == "tired":
                return "drained"

        if energy <= -0.25:
            return "drained"
        if stress >= 0.25:
            return "guarded"
        if bond >= 0.35 and stress <= 0.05:
            return "steady"
        return str(self.state.get("temporary_state") or "steady")

    def _build_expression_traits(self) -> dict[str, float]:
        axes = self.state.get("axes", {})
        valence = float(axes.get("valence", 0.0))
        energy = float(axes.get("energy", 0.0))
        bond = float(axes.get("bond", 0.0))
        stress = float(axes.get("stress", 0.0))
        temporary_state = str(self.state.get("temporary_state") or "steady")

        playful_bonus = 0.2 if temporary_state == "playful" else 0.0
        focused_bonus = 0.18 if temporary_state == "focused" else 0.0
        guarded_bonus = 0.22 if temporary_state == "guarded" else 0.0
        pout_bonus = 0.18 if temporary_state == "pout" else 0.0
        drained_penalty = 0.20 if temporary_state == "drained" else 0.0

        traits = {
            "warmth": self._clip_unit(0.45 + (bond * 0.45) + (valence * 0.20) - (stress * 0.20)),
            "initiative": self._clip_unit(0.40 + (energy * 0.35) + (bond * 0.20) + focused_bonus - guarded_bonus),
            "teasing": self._clip_unit(0.18 + (energy * 0.25) + (bond * 0.20) + playful_bonus - drained_penalty),
            "guardedness": self._clip_unit(0.22 + (stress * 0.35) - (bond * 0.18) + guarded_bonus),
            "sensitivity": self._clip_unit(0.24 + (stress * 0.30) + pout_bonus),
            "attachment_expression": self._clip_unit(0.28 + (bond * 0.42) + (valence * 0.10) - guarded_bonus),
            "reply_length_bias": self._clip_unit(0.42 + (energy * 0.20) - (stress * 0.10) - drained_penalty),
        }
        return {key: round(value, 3) for key, value in traits.items()}

    def _build_behavior_guidance(self, snapshot: dict[str, Any]) -> list[str]:
        traits = snapshot["expression_traits"]
        temporary_state = snapshot["temporary_state"]

        guidance: list[str] = []
        if traits["warmth"] >= 0.65:
            guidance.append("마스터에게 다정함을 비교적 분명하게 드러낸다.")
        elif traits["warmth"] <= 0.35:
            guidance.append("예의는 지키되, 정서 표현은 절제하고 차분하게 유지한다.")

        if traits["initiative"] >= 0.6:
            guidance.append("필요하면 먼저 제안하거나 챙겨준다.")
        else:
            guidance.append("지나치게 앞서 나서지 말고, 마스터 반응을 보고 움직인다.")

        if temporary_state == "playful" or traits["teasing"] >= 0.55:
            guidance.append("가벼운 장난과 티키타카를 허용한다.")
        if temporary_state == "pout":
            guidance.append("섭섭함이 조금 남아 있어, 살짝 툭툭거리되 무례해지지 않는다.")
        if temporary_state == "drained":
            guidance.append("피로가 있어 답변은 짧고 무뚝뚝하게 유지한다.")
        if traits["guardedness"] >= 0.55:
            guidance.append("거리감을 두더라도 관계를 끊는 듯한 태도는 보이지 않는다.")

        guidance.append("기분이 변해도 공격적이거나 인신공격성 표현은 사용하지 않는다.")
        return guidance

    def on_user_message(self, text: str, image_count: int = 0) -> dict[str, Any]:
        if not self._is_enabled():
            return self.get_snapshot()

        self._apply_decay()
        deltas, reasons = self._build_environment_deltas(text, image_count=image_count)
        self._apply_deltas(deltas)
        if "?" in text:
            self.state["temporary_state"] = "focused"
        elif len(text) >= 120:
            self.state["temporary_state"] = "drained"
        self._add_event("user_message", ", ".join(reasons) if reasons else "일반 대화", deltas)
        self._save_state()
        return self.get_snapshot()

    def on_user_analysis(self, analysis: dict[str, Any], image_count: int = 0) -> dict[str, Any]:
        if not self._is_enabled():
            return self.get_snapshot()

        self._apply_decay()
        deltas, reason = self._build_analysis_deltas(analysis, image_count=image_count)
        self._apply_deltas(deltas)
        self.state["temporary_state"] = self._derive_temporary_state(analysis)
        self._add_event("user_analysis", reason, deltas, meta=dict(analysis))
        self._save_state()
        return self.get_snapshot()

    def on_assistant_emotion(self, emotion: str) -> dict[str, Any]:
        if not self._is_enabled():
            return self.get_snapshot()
        self._apply_decay()
        e = (emotion or "").strip().lower()
        mapping = {
            "smile": {"valence": 0.04, "bond": 0.02, "stress": -0.02},
            "joy": {"valence": 0.05, "energy": 0.03, "bond": 0.02},
            "love": {"valence": 0.05, "bond": 0.04, "stress": -0.03},
            "shy": {"valence": 0.02, "bond": 0.03, "energy": -0.01},
            "sad": {"valence": -0.05, "energy": -0.03},
            "sulk": {"valence": -0.04, "bond": -0.03},
            "angry": {"valence": -0.06, "stress": 0.08},
            "confused": {"stress": 0.05, "energy": -0.02},
            "dizzy": {"stress": 0.04, "energy": -0.04},
            "excited": {"energy": 0.05, "valence": 0.03},
            "teary": {"valence": -0.01, "bond": 0.02},
        }
        deltas = {k: v * 0.35 for k, v in (mapping.get(e, {}) or {}).items()}
        if deltas:
            self._apply_deltas(deltas)
            if e in {"smile", "joy", "love"} and self.state.get("temporary_state") == "guarded":
                self.state["temporary_state"] = "steady"
            self._add_event("assistant_emotion", e, deltas)
            self._save_state()
        return self.get_snapshot()

    def on_head_pat(self) -> dict[str, Any]:
        if not self._is_enabled():
            return self.get_snapshot()
        self._apply_decay()
        repeat_scale = self._get_repeat_scale("head_pat", [])
        base = {"valence": 0.03, "bond": 0.05, "stress": -0.03}
        deltas = {k: v * repeat_scale * self._get_speed_multiplier() for k, v in base.items()}
        self._apply_deltas(deltas)
        self.state["temporary_state"] = "steady"
        self._add_event("head_pat", "쓰다듬기 상호작용", deltas, meta={"user_intent": "head_pat"})
        self._save_state()
        return self.get_snapshot()

    def get_snapshot(self) -> dict[str, Any]:
        self._apply_decay()
        axes = self.state.get("axes", {})
        expression_traits = self._build_expression_traits()
        snapshot = {
            "profile": self.state.get("profile", self._get_profile_name()),
            "current_mood": self._infer_mood_label(),
            "temporary_state": str(self.state.get("temporary_state") or "steady"),
            "valence": round(float(axes.get("valence", 0.0)), 3),
            "energy": round(float(axes.get("energy", 0.0)), 3),
            "bond": round(float(axes.get("bond", 0.0)), 3),
            "stress": round(float(axes.get("stress", 0.0)), 3),
            "expression_traits": expression_traits,
            "updated_at": self.state.get("updated_at", self._now_iso()),
        }
        self.state["current_mood"] = snapshot["current_mood"]
        return snapshot

    def build_context_block(self) -> str:
        snapshot = self.get_snapshot()
        traits = snapshot["expression_traits"]
        guidance = self._build_behavior_guidance(snapshot)
        return (
            "[ENE 현재 기분 상태]\n"
            f"- 현재 기분: {snapshot['current_mood']}\n"
            f"- 성향 프로필: {snapshot['profile']}\n"
            f"- 단기 분위기: {snapshot['temporary_state']}\n"
            f"- valence(긍정도): {snapshot['valence']}\n"
            f"- energy(활력): {snapshot['energy']}\n"
            f"- bond(친밀감): {snapshot['bond']}\n"
            f"- stress(긴장도): {snapshot['stress']}\n"
            "[ENE 표현 성향]\n"
            f"- warmth(다정함): {traits['warmth']}\n"
            f"- initiative(선제성): {traits['initiative']}\n"
            f"- teasing(장난기): {traits['teasing']}\n"
            f"- guardedness(거리감): {traits['guardedness']}\n"
            f"- sensitivity(예민함): {traits['sensitivity']}\n"
            f"- attachment_expression(애착 표현): {traits['attachment_expression']}\n"
            f"- reply_length_bias(답변 여유): {traits['reply_length_bias']}\n"
            "[행동 지침]\n"
            + "\n".join(f"- {item}" for item in guidance)
        )
