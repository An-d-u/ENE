"""ENE Mood Engine V3의 저장소와 호환 facade."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone, tzinfo
import json
import math
from pathlib import Path
from typing import Any
import uuid

from ..core import app_paths
from . import mood_engine
from .prompt_language import resolve_prompt_language


_EVENT_FIELDS = {
    "kind",
    "target_scope",
    "relation_category",
    "intensity",
    "clarity",
    "certainty",
    "controllability",
    "repair_signal",
}
_PROFILE_ALIASES = {
    "calm": "calm",
    "affectionate": "balanced",
    "balanced": "balanced",
    "playful": "expressive",
    "expressive": "expressive",
}


class MoodManager:
    """V3 기분 상태의 검증, 원자 저장, 마이그레이션을 담당합니다."""

    def __init__(
        self,
        state_file: str | Path | None = None,
        settings: Any = None,
        clock: Callable[[], datetime] | None = None,
        local_timezone: tzinfo | None = None,
    ):
        target_file = state_file if state_file is not None else "mood_state.json"
        self.state_path = app_paths.resolve_user_storage_path(target_file)
        self.settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._local_timezone = local_timezone or datetime.now().astimezone().tzinfo or timezone.utc
        self._error_code: str | None = None
        self._write_locked = False
        self._last_primary_emotion: str | None = None
        self.state = self._load_state()

    def _setting(self, key: str, default: Any) -> Any:
        source = self.settings
        if source is None:
            return default
        config = getattr(source, "config", source)
        if isinstance(config, Mapping):
            return config.get(key, default)
        getter = getattr(source, "get", None)
        if callable(getter):
            return getter(key, default)
        return default

    def _preset(self) -> str:
        raw = self._setting("mood_personality_profile", "affectionate")
        if not isinstance(raw, str):
            return "balanced"
        return _PROFILE_ALIASES.get(raw.strip().lower(), "balanced")

    def _is_enabled(self) -> bool:
        return bool(self._setting("enable_mood_system", True))

    def _now_utc(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock은 timezone-aware datetime을 반환해야 합니다.")
        return value.astimezone(timezone.utc)

    def _fresh_state(self, now_utc: datetime | None = None) -> dict[str, Any]:
        return mood_engine.new_mood_state(now_utc or self._now_utc(), self._preset())

    def _lock(self, error_code: str) -> None:
        self._error_code = error_code
        self._write_locked = True

    def _load_state(self) -> dict[str, Any]:
        fallback = self._fresh_state()
        try:
            original = app_paths.read_bytes_data(self.state_path)
        except FileNotFoundError:
            return fallback
        except OSError:
            self._lock("state_read_failed")
            return fallback
        try:
            loaded = json.loads(original.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._lock("corrupt_state")
            return fallback
        if not isinstance(loaded, Mapping) or type(loaded.get("version")) is not int:
            self._lock("corrupt_state")
            return fallback
        version = loaded["version"]
        if version > 3:
            self._lock("future_version")
            return fallback
        if version == 3:
            try:
                return mood_engine.validate_state(loaded)
            except (TypeError, ValueError):
                self._lock("corrupt_state")
                return fallback
        if version != 2:
            self._lock("corrupt_state")
            return fallback
        try:
            validated_v2 = self._validate_v2(loaded)
        except (TypeError, ValueError):
            self._lock("corrupt_state")
            return fallback
        try:
            migrated = self._migrate_v2(validated_v2)
            migrated = mood_engine.validate_state(migrated)
        except Exception:
            self._lock("migration_failed")
            return fallback
        backup_path = self.state_path.with_name(f"{self.state_path.name}.v2.bak")
        try:
            if not self._authoritative_exists(backup_path):
                app_paths.write_bytes_data_atomic(backup_path, original)
            self._write_state(migrated)
        except Exception:
            self._lock("migration_failed")
            return fallback
        return migrated

    @staticmethod
    def _authoritative_exists(path: Path) -> bool:
        try:
            app_paths.read_bytes_data(path)
        except FileNotFoundError:
            return False
        return True

    def _validate_v2(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        axes = raw.get("axes")
        if not isinstance(axes, Mapping):
            raise ValueError("V2 axes가 없습니다.")
        validated_axes: dict[str, float] = {}
        for field in ("valence", "energy", "bond", "stress"):
            value = axes.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("V2 축 값의 타입이 올바르지 않습니다.")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("V2 축 값은 유한해야 합니다.")
            validated_axes[field] = max(-1.0, min(1.0, number))
        profile = raw.get("profile", "affectionate")
        if not isinstance(profile, str):
            raise ValueError("V2 profile이 올바르지 않습니다.")
        updated_at = raw.get("updated_at")
        if not isinstance(updated_at, str):
            raise ValueError("V2 updated_at이 올바르지 않습니다.")
        try:
            parsed = datetime.fromisoformat(updated_at)
        except ValueError as exc:
            raise ValueError("V2 updated_at이 올바르지 않습니다.") from exc
        return {"profile": profile, "axes": validated_axes, "updated_at": parsed}

    def _migrate_v2(self, validated: Mapping[str, Any]) -> dict[str, Any]:
        updated_at = validated["updated_at"]
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            updated_at = updated_at.replace(tzinfo=self._local_timezone)
        updated_at_utc = updated_at.astimezone(timezone.utc)
        preset = _PROFILE_ALIASES.get(str(validated["profile"]).strip().lower(), "balanced")
        state = mood_engine.new_mood_state(updated_at_utc, preset)
        axes = validated["axes"]
        state["background"] = {
            "valence": axes["valence"],
            "energy": axes["energy"],
            "tension": axes["stress"],
        }
        state["relationship"] = {"affection": axes["bond"], "trust": 0.0}
        return state

    def _write_state(self, candidate: Mapping[str, Any]) -> None:
        validated = mood_engine.validate_state(candidate)
        app_paths.save_json_data(
            self.state_path,
            validated,
            encoding="utf-8",
            indent=2,
            ensure_ascii=False,
            trailing_newline=True,
        )

    def _coerce_occurred_at(self, value: datetime | str | None) -> datetime:
        if value is None:
            return self._now_utc()
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("occurred_at_utc는 timezone-aware datetime이어야 합니다.")
            return value.astimezone(timezone.utc)
        if not isinstance(value, str):
            raise TypeError("occurred_at_utc 타입이 올바르지 않습니다.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("occurred_at_utc 문자열이 올바르지 않습니다.") from exc
        if parsed.tzinfo != timezone.utc or mood_engine.format_utc(parsed) != value:
            raise ValueError("occurred_at_utc 문자열은 canonical UTC ISO 형식이어야 합니다.")
        return parsed

    def _host_event(self, event_id: str, analysis: object) -> dict[str, Any]:
        source: object = analysis
        if isinstance(analysis, Mapping) and "event" in analysis:
            source = analysis.get("event")
        data = source if isinstance(source, Mapping) else {}
        event = {field: deepcopy(data[field]) for field in _EVENT_FIELDS if field in data}
        event["event_id"] = event_id
        return event

    def _snapshot_for(self, state: Mapping[str, Any], *, update_hysteresis: bool) -> dict[str, Any]:
        derived = mood_engine.derive_snapshot(state, self._last_primary_emotion)
        primary = derived["primary_emotion"]
        if update_hysteresis:
            self._last_primary_emotion = primary if isinstance(primary, str) else None
        stored = derived["state"]
        background = deepcopy(stored["background"])
        relationship = deepcopy(stored["relationship"])
        active_affects = deepcopy(stored["active_affects"])
        ruptures = deepcopy(stored["ruptures"])
        temporary_state = self._legacy_temporary_state(primary)
        current_mood = self._legacy_mood(background, relationship, temporary_state)
        expression_traits = self._expression_traits(background, relationship, temporary_state)
        return {
            "version": stored["version"],
            "revision": stored["revision"],
            "preset": stored["preset"],
            "profile": stored["preset"],
            "background": background,
            "relationship": relationship,
            "active_affects": active_affects,
            "ruptures": ruptures,
            "primary_emotion": primary,
            "secondary_emotion": derived["secondary_emotion"],
            "behavior_guidance": derived["behavior_guidance"],
            "valence": background["valence"],
            "energy": background["energy"],
            "bond": relationship["affection"],
            "stress": background["tension"],
            "current_mood": current_mood,
            "temporary_state": temporary_state,
            "expression_traits": expression_traits,
            "updated_at": stored["updated_at_utc"],
        }

    @staticmethod
    def _legacy_temporary_state(primary: object) -> str:
        return {
            "amusement": "playful",
            "interest": "focused",
            "hurt": "pout",
            "anger": "guarded",
            "anxiety": "guarded",
            "sadness": "drained",
        }.get(primary, "steady")

    @staticmethod
    def _legacy_mood(background: Mapping[str, float], relationship: Mapping[str, float], temporary: str) -> str:
        if background["tension"] >= 0.32 or temporary == "guarded":
            return "tense"
        if background["energy"] <= -0.20 or temporary == "drained":
            return "tired"
        if relationship["affection"] >= 0.34 and background["valence"] >= 0.12:
            return "affectionate"
        if background["valence"] >= 0.18 and background["energy"] >= 0.04:
            return "cheerful"
        return "calm"

    @staticmethod
    def _expression_traits(
        background: Mapping[str, float], relationship: Mapping[str, float], temporary: str
    ) -> dict[str, float]:
        valence, energy, tension = (background["valence"], background["energy"], background["tension"])
        affection, trust = relationship["affection"], relationship["trust"]
        warmth_base = (affection + trust) / 2.0
        bonuses = {
            "playful": 0.20 if temporary == "playful" else 0.0,
            "focused": 0.18 if temporary == "focused" else 0.0,
            "guarded": 0.22 if temporary == "guarded" else 0.0,
            "pout": 0.18 if temporary == "pout" else 0.0,
            "drained": 0.20 if temporary == "drained" else 0.0,
        }
        clip = lambda value: round(max(0.0, min(1.0, value)), 3)
        return {
            "warmth": clip(0.45 + warmth_base * 0.45 + valence * 0.20 - tension * 0.20),
            "initiative": clip(0.40 + energy * 0.35 + warmth_base * 0.20 + bonuses["focused"] - bonuses["guarded"]),
            "teasing": clip(0.18 + energy * 0.25 + affection * 0.20 + bonuses["playful"] - bonuses["drained"]),
            "guardedness": clip(0.22 + tension * 0.35 - trust * 0.18 + bonuses["guarded"]),
            "sensitivity": clip(0.24 + tension * 0.30 + bonuses["pout"]),
            "attachment_expression": clip(0.28 + affection * 0.42 + valence * 0.10 - bonuses["guarded"]),
            "reply_length_bias": clip(0.42 + energy * 0.20 - tension * 0.10 - bonuses["drained"]),
        }

    def apply_event(
        self, event_id: str, analysis: object, occurred_at_utc: datetime | str | None = None
    ) -> dict[str, Any]:
        if self._write_locked or not self._is_enabled():
            return self.get_snapshot()
        occurred_at = self._coerce_occurred_at(occurred_at_utc)
        transition = mood_engine.reduce_mood(
            self.state, self._host_event(event_id, analysis), occurred_at, self._preset()
        )
        if not transition.applied:
            return self.get_snapshot()
        try:
            self._write_state(transition.state)
        except Exception:
            return self.get_snapshot()
        self.state = transition.state
        return self.get_snapshot()

    def preview_event(
        self, event_id: str, analysis: object, occurred_at_utc: datetime | str | None = None
    ) -> dict[str, Any]:
        if self._write_locked or not self._is_enabled():
            return self._snapshot_for(self.state, update_hysteresis=False)
        occurred_at = self._coerce_occurred_at(occurred_at_utc)
        transition = mood_engine.reduce_mood(
            deepcopy(self.state), self._host_event(event_id, analysis), occurred_at, self._preset()
        )
        return self._snapshot_for(transition.state, update_hysteresis=False)

    def advance_time_and_save(self, now_utc: datetime | str | None = None) -> dict[str, Any]:
        if self._write_locked or not self._is_enabled():
            return self.get_snapshot()
        occurred_at = self._coerce_occurred_at(now_utc)
        transition = mood_engine.advance_time(self.state, occurred_at, self._preset())
        if not transition.applied:
            try:
                if self.state_path.exists():
                    return self.get_snapshot()
            except OSError:
                return self.get_snapshot()
        candidate = transition.state if transition.applied else deepcopy(self.state)
        try:
            self._write_state(candidate)
        except Exception:
            return self.get_snapshot()
        if transition.applied:
            self.state = candidate
        return self.get_snapshot()

    def get_snapshot(self) -> dict[str, Any]:
        return self._snapshot_for(self.state, update_hysteresis=True)

    def build_context_block(self, language: str | None = None) -> str:
        if not self._is_enabled():
            return ""
        selected = resolve_prompt_language(language, settings_source=self.settings)
        derived = mood_engine.derive_snapshot(self.state, self._last_primary_emotion)
        guidance = mood_engine.derive_behavior_guidance(self.state, selected)
        labels = {
            "ko": ("ENE 기분 방향", "주 감정", "보조 감정", "관계 균열", "행동 지침", "없음"),
            "en": ("ENE Mood Direction", "Primary emotion", "Secondary emotion", "Relationship rupture", "Behavior guidance", "none"),
            "ja": ("ENEの気分方向", "主感情", "副感情", "関係の亀裂", "行動指針", "なし"),
        }[selected]
        rupture_categories = sorted({item["category"] for item in self.state["ruptures"]})
        primary = derived["primary_emotion"] or labels[5]
        secondary = derived["secondary_emotion"] or labels[5]
        ruptures = ", ".join(rupture_categories) if rupture_categories else labels[5]
        lines = [
            f"[{labels[0]}]",
            f"- {labels[1]}: {primary}",
            f"- {labels[2]}: {secondary}",
            f"- {labels[3]}: {ruptures}",
            f"[{labels[4]}]",
        ]
        lines.extend(f"- {item}" for item in guidance)
        return "\n".join(lines)

    def get_load_status(self) -> dict[str, Any]:
        return {"error_code": self._error_code, "write_locked": self._write_locked}

    def reset_state(self, now_utc: datetime | str | None = None) -> dict[str, Any]:
        occurred_at = self._coerce_occurred_at(now_utc)
        candidate = mood_engine.new_mood_state(occurred_at, self._preset())
        previous_state = self.state
        previous_error = self._error_code
        previous_lock = self._write_locked
        try:
            try:
                original = app_paths.read_bytes_data(self.state_path)
            except FileNotFoundError:
                original = None
            if original is not None:
                stamp = occurred_at.strftime("%Y%m%dT%H%M%S%fZ")
                recovery = self.state_path.with_name(f"{self.state_path.name}.recovery.{stamp}.bak")
                if self._authoritative_exists(recovery):
                    recovery = self.state_path.with_name(
                        f"{self.state_path.name}.recovery.{stamp}.{uuid.uuid4().hex}.bak"
                    )
                app_paths.write_bytes_data_atomic(recovery, original)
            self._write_state(candidate)
        except Exception:
            self.state = previous_state
            self._error_code = previous_error
            self._write_locked = previous_lock
            return self.get_snapshot()
        self.state = candidate
        self._error_code = None
        self._write_locked = False
        self._last_primary_emotion = None
        return self.get_snapshot()

    def on_user_message(self, text: str, image_count: int = 0) -> dict[str, Any]:
        return self.get_snapshot()

    def on_user_analysis(
        self,
        analysis: object,
        event_id: str | None = None,
        occurred_at_utc: datetime | str | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        if event_id is None:
            return self.get_snapshot()
        return self.apply_event(event_id, analysis, occurred_at_utc)

    def on_head_pat(self) -> dict[str, Any]:
        return self.apply_event(
            str(uuid.uuid4()),
            {
                "kind": "connection",
                "target_scope": "relationship",
                "relation_category": "none",
                "intensity": 1,
                "clarity": "explicit",
                "certainty": "high",
                "controllability": "high",
                "repair_signal": "none",
            },
        )

    def on_assistant_emotion(self, emotion: str) -> dict[str, Any]:
        return self.get_snapshot()
