"""
ENE 기분 상태 관리자.
발화 단위 감정과 분리된 장기 기분 축을 관리한다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class MoodManager:
    """장기 기분 상태를 저장/업데이트하는 매니저."""

    AXES = ("valence", "energy", "bond", "stress")

    PROFILE_BASELINES = {
        "calm": {"valence": 0.10, "energy": 0.00, "bond": 0.20, "stress": -0.10},
        "affectionate": {"valence": 0.25, "energy": 0.05, "bond": 0.45, "stress": -0.15},
        "playful": {"valence": 0.20, "energy": 0.25, "bond": 0.25, "stress": 0.00},
    }

    def __init__(self, state_file: str = "mood_state.json", settings=None):
        self.state_path = Path(state_file)
        self.settings = settings
        self.state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                merged = self._default_state()
                merged.update(loaded)
                merged["axes"] = {**self._default_state()["axes"], **(loaded.get("axes") or {})}
                merged["recent_events"] = list(loaded.get("recent_events") or [])[:30]
                return merged
            except Exception as e:
                print(f"[Mood] 상태 로드 실패: {e}")
        return self._default_state()

    def _default_state(self) -> dict[str, Any]:
        profile = self._get_profile_name()
        baseline = self.PROFILE_BASELINES.get(profile, self.PROFILE_BASELINES["affectionate"])
        now = self._now_iso()
        return {
            "version": 1,
            "profile": profile,
            "axes": dict(baseline),
            "current_mood": "calm",
            "updated_at": now,
            "recent_events": [],
        }

    def _save_state(self):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
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

    def _add_event(self, source: str, reason: str, deltas: dict[str, float]):
        item = {
            "time": self._now_iso(),
            "source": source,
            "reason": reason,
            "delta": {k: round(v, 4) for k, v in deltas.items() if abs(v) > 0.0001},
        }
        self.state["recent_events"].append(item)
        self.state["recent_events"] = self.state["recent_events"][-30:]

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

        self.state["profile"] = profile
        self.state["updated_at"] = self._now_iso()

    def _apply_deltas(self, deltas: dict[str, float]):
        axes = self.state.get("axes", {})
        for axis, delta in deltas.items():
            if axis not in self.AXES:
                continue
            current = float(axes.get(axis, 0.0))
            axes[axis] = self._clip(current + delta)
        self.state["current_mood"] = self._infer_mood_label()
        self.state["updated_at"] = self._now_iso()

    def _infer_mood_label(self) -> str:
        axes = self.state.get("axes", {})
        valence = float(axes.get("valence", 0.0))
        energy = float(axes.get("energy", 0.0))
        bond = float(axes.get("bond", 0.0))
        stress = float(axes.get("stress", 0.0))

        if stress >= 0.45:
            return "tense"
        if bond <= -0.25 and valence <= -0.15:
            return "lonely"
        if energy <= -0.35:
            return "tired"
        if bond >= 0.55 and valence >= 0.15:
            return "affectionate"
        if valence >= 0.40 and energy >= 0.10:
            return "cheerful"
        return "calm"

    def _build_user_message_deltas(self, text: str, image_count: int = 0) -> tuple[dict[str, float], str]:
        t = text.lower()
        mult = self._get_speed_multiplier()

        deltas = {"valence": 0.0, "energy": 0.0, "bond": 0.0, "stress": 0.0}
        reasons = []

        positive_pattern = r"(고마|감사|좋아|사랑|귀여|잘했|대단|수고|최고|love|thanks|great|good job)"
        negative_pattern = r"(싫어|짜증|꺼져|미워|닥쳐|별로|한심|바보|hate|annoy|stupid|shut up)"
        warm_pattern = r"(에네|ene|쓰다듬|안아|보고싶|같이|우리)"

        if re.search(positive_pattern, t):
            deltas["valence"] += 0.09
            deltas["bond"] += 0.10
            deltas["stress"] -= 0.05
            reasons.append("긍정 표현")

        if re.search(negative_pattern, t):
            deltas["valence"] -= 0.12
            deltas["bond"] -= 0.10
            deltas["stress"] += 0.12
            reasons.append("부정 표현")

        if re.search(warm_pattern, t):
            deltas["bond"] += 0.06
            reasons.append("친밀 상호작용")

        if "?" in t or "?" in text:
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
            deltas["bond"] += min(0.08, 0.03 + image_count * 0.01)
            deltas["valence"] += 0.03
            reasons.append("이미지 공유")

        for axis in deltas:
            deltas[axis] *= mult
        return deltas, ", ".join(reasons) if reasons else "일반 대화"

    def on_user_message(self, text: str, image_count: int = 0) -> dict[str, Any]:
        if not self._is_enabled():
            return self.get_snapshot()
        self._apply_decay()
        deltas, reason = self._build_user_message_deltas(text, image_count=image_count)
        self._apply_deltas(deltas)
        self._add_event("user_message", reason, deltas)
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
        deltas = {k: v * 0.6 for k, v in (mapping.get(e, {}) or {}).items()}
        if deltas:
            self._apply_deltas(deltas)
            self._add_event("assistant_emotion", e, deltas)
            self._save_state()
        return self.get_snapshot()

    def on_head_pat(self) -> dict[str, Any]:
        if not self._is_enabled():
            return self.get_snapshot()
        self._apply_decay()
        deltas = {"valence": 0.05, "bond": 0.08, "stress": -0.04}
        deltas = {k: v * self._get_speed_multiplier() for k, v in deltas.items()}
        self._apply_deltas(deltas)
        self._add_event("head_pat", "쓰다듬기 상호작용", deltas)
        self._save_state()
        return self.get_snapshot()

    def get_snapshot(self) -> dict[str, Any]:
        self._apply_decay()
        axes = self.state.get("axes", {})
        snapshot = {
            "profile": self.state.get("profile", self._get_profile_name()),
            "current_mood": self._infer_mood_label(),
            "valence": round(float(axes.get("valence", 0.0)), 3),
            "energy": round(float(axes.get("energy", 0.0)), 3),
            "bond": round(float(axes.get("bond", 0.0)), 3),
            "stress": round(float(axes.get("stress", 0.0)), 3),
            "updated_at": self.state.get("updated_at", self._now_iso()),
        }
        self.state["current_mood"] = snapshot["current_mood"]
        return snapshot

    def build_context_block(self) -> str:
        s = self.get_snapshot()
        return (
            "[ENE 현재 기분 상태]\n"
            f"- 현재 기분: {s['current_mood']}\n"
            f"- 성향 프로필: {s['profile']}\n"
            f"- valence(긍정도): {s['valence']}\n"
            f"- energy(활력): {s['energy']}\n"
            f"- bond(친밀감): {s['bond']}\n"
            f"- stress(긴장도): {s['stress']}\n"
            "- 규칙: 현재 발화 감정 태그와 별개로, 말투/제안 강도/반응 온도에만 은은하게 반영한다."
        )
