"""
ENE 현재 목표 관리자.
LLM이 제안한 목표 업데이트를 작게 검증하고 활성 목표/이력 상태로 저장한다.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data
from .persona_names import resolve_prompt_persona_names
from .prompt_language import resolve_prompt_language


class EneGoalManager:
    """ENE의 장단기 목표 상태를 저장하고 갱신하는 매니저."""

    ALLOWED_ACTIONS = {"none", "create", "update", "complete", "cancel"}
    ALLOWED_TYPES = {"short_term", "long_term"}
    TITLE_MAX = 120
    REASON_MAX = 300
    DEFAULT_STATE = {"version": 1, "active": {"long_term": [], "short_term": []}, "history": []}
    DUPLICATE_PUNCTUATION = ".,!?;:，。！？、"

    def __init__(self, state_file: str | Path | None = None, settings=None):
        self.settings = settings
        target_file = state_file if state_file is not None else self._read_setting("ene_goal_state_file", "ene_goals.json")
        self.state_path = resolve_user_storage_path(target_file)
        self.state = self._load_state()

    def _default_state(self) -> dict[str, Any]:
        return deepcopy(self.DEFAULT_STATE)

    def _load_state(self) -> dict[str, Any]:
        try:
            loaded = load_json_data(self.state_path, encoding="utf-8-sig")
            if not isinstance(loaded, dict):
                raise ValueError("목표 상태가 딕셔너리가 아닙니다.")
            return self._sanitize_state(loaded)
        except Exception as e:
            if self.state_path.exists():
                print(f"[Goals] 상태 로드 실패: {e}")
        return self._default_state()

    def _sanitize_state(self, loaded: dict[str, Any]) -> dict[str, Any]:
        state = self._default_state()
        state["version"] = int(loaded.get("version") or 1)

        active = loaded.get("active") or {}
        if isinstance(active, dict):
            for goal_type in self.ALLOWED_TYPES:
                items = active.get(goal_type) or []
                if isinstance(items, list):
                    state["active"][goal_type] = [deepcopy(item) for item in items if isinstance(item, dict)]

        history = loaded.get("history") or []
        if isinstance(history, list):
            state["history"] = [deepcopy(item) for item in history if isinstance(item, dict)]
        return state

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
            print(f"[Goals] 상태 저장 실패: {e}")

    def _read_setting(self, key: str, default):
        if self.settings is None:
            return default
        if isinstance(self.settings, dict):
            return self.settings.get(key, default)
        getter = getattr(self.settings, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except Exception:
                pass
        config = getattr(self.settings, "config", None)
        if isinstance(config, dict):
            return config.get(key, default)
        return default

    def _is_enabled(self) -> bool:
        return bool(self._read_setting("enable_ene_goals", True))

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _trim_text(self, value: Any, max_length: int) -> str:
        return str(value or "").strip()[:max_length]

    def _new_goal_id(self) -> str:
        return f"goal_{uuid4().hex[:12]}"

    def _normalize_title(self, title: str) -> str:
        text = re.sub(r"\s+", " ", str(title or "").strip()).lower()
        text = text.translate(str.maketrans("", "", self.DUPLICATE_PUNCTUATION))
        return re.sub(r"\s+", " ", text).strip()

    def _find_active_goal(self, goal_id: str) -> tuple[str, int, dict[str, Any]] | None:
        for goal_type in ("short_term", "long_term"):
            for index, goal in enumerate(self.state["active"].get(goal_type, [])):
                if goal.get("id") == goal_id:
                    return goal_type, index, goal
        return None

    def _find_duplicate_goal(self, goal_type: str, title: str) -> dict[str, Any] | None:
        normalized = self._normalize_title(title)
        if not normalized:
            return None
        for goal in self.state["active"].get(goal_type, []):
            if self._normalize_title(goal.get("title", "")) == normalized:
                return goal
        return None

    def _create_goal(self, goal_type: str, title: str, reason: str, source: str) -> dict[str, Any]:
        title = self._trim_text(title, self.TITLE_MAX)
        reason = self._trim_text(reason, self.REASON_MAX)
        if goal_type not in self.ALLOWED_TYPES or not title:
            return self.get_snapshot()

        duplicate = self._find_duplicate_goal(goal_type, title)
        if duplicate is not None:
            if reason and duplicate.get("reason") != reason:
                duplicate["reason"] = reason
            duplicate["updated_at"] = self._now_iso()
            self._save_state()
            return self.get_snapshot()

        now = self._now_iso()
        goal = {
            "id": self._new_goal_id(),
            "type": goal_type,
            "title": title,
            "reason": reason,
            "source": source,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        self.state["active"][goal_type].append(goal)
        self._save_state()
        return self.get_snapshot()

    def apply_llm_update(self, update: dict) -> dict:
        if not self._is_enabled() or not isinstance(update, dict):
            return self.get_snapshot()

        action = str(update.get("action") or "").strip().lower()
        if action == "none":
            return self.get_snapshot()
        if action not in self.ALLOWED_ACTIONS:
            return self.get_snapshot()

        if action == "create":
            goal_type = str(update.get("type") or "").strip()
            title = self._trim_text(update.get("title"), self.TITLE_MAX)
            reason = self._trim_text(update.get("reason"), self.REASON_MAX)
            if goal_type not in self.ALLOWED_TYPES or not title or not reason:
                return self.get_snapshot()
            return self._create_goal(goal_type, title, reason, source="llm")

        if action == "update":
            goal_id = str(update.get("id") or "").strip()
            fields = {key: update[key] for key in ("title", "reason") if key in update}
            if not goal_id or not fields:
                return self.get_snapshot()
            return self.update_goal(goal_id, fields)

        goal_id = str(update.get("id") or "").strip()
        if not goal_id:
            return self.get_snapshot()
        goal_type = str(update.get("type") or "").strip()
        if goal_type:
            found = self._find_active_goal(goal_id)
            if goal_type not in self.ALLOWED_TYPES or found is None or found[0] != goal_type:
                return self.get_snapshot()
        reason = update.get("completion_reason", "")
        if action == "complete":
            return self.complete_goal(goal_id, reason)
        if action == "cancel":
            return self.cancel_goal(goal_id, reason)
        return self.get_snapshot()

    def add_manual_goal(self, goal_type: str, title: str, reason: str = "") -> dict:
        if not self._is_enabled():
            return self.get_snapshot()
        return self._create_goal(str(goal_type or "").strip(), title, reason, source="manual")

    def update_goal(self, goal_id: str, fields: dict) -> dict:
        if not self._is_enabled() or not isinstance(fields, dict):
            return self.get_snapshot()

        goal_id = str(goal_id or "").strip()
        found = self._find_active_goal(goal_id)
        if found is None:
            return self.get_snapshot()

        editable: dict[str, str] = {}
        if "title" in fields:
            title = self._trim_text(fields.get("title"), self.TITLE_MAX)
            if title:
                editable["title"] = title
        if "reason" in fields:
            editable["reason"] = self._trim_text(fields.get("reason"), self.REASON_MAX)
        if not editable:
            return self.get_snapshot()

        goal_type, _index, goal = found
        if "title" in editable:
            duplicate = self._find_duplicate_goal(goal_type, editable["title"])
            if duplicate is not None and duplicate.get("id") != goal_id:
                return self.get_snapshot()

        goal.update(editable)
        goal["updated_at"] = self._now_iso()
        self._save_state()
        return self.get_snapshot()

    def _finish_goal(self, goal_id: str, status: str, reason: str) -> dict:
        if not self._is_enabled():
            return self.get_snapshot()

        found = self._find_active_goal(str(goal_id or "").strip())
        if found is None:
            return self.get_snapshot()

        goal_type, index, goal = found
        finished = deepcopy(goal)
        now = self._now_iso()
        finished["status"] = status
        finished["completion_reason"] = self._trim_text(reason, self.REASON_MAX)
        finished["updated_at"] = now
        if status == "completed":
            finished["completed_at"] = now
        else:
            finished["cancelled_at"] = now

        del self.state["active"][goal_type][index]
        self.state["history"].append(finished)
        self._save_state()
        return self.get_snapshot()

    def complete_goal(self, goal_id: str, reason: str = "") -> dict:
        return self._finish_goal(goal_id, "completed", reason)

    def cancel_goal(self, goal_id: str, reason: str = "") -> dict:
        return self._finish_goal(goal_id, "cancelled", reason)

    def list_history(self, limit=None) -> list:
        history = deepcopy(self.state.get("history", []))
        if limit is None:
            return history
        try:
            count = max(0, int(limit))
        except Exception:
            return history
        if count == 0:
            return []
        return history[-count:]

    def get_snapshot(self) -> dict:
        return deepcopy(self.state)

    def build_context_block(self, language=None) -> str:
        if not self._is_enabled():
            return ""

        goals: list[dict[str, Any]] = []
        for goal_type in ("short_term", "long_term"):
            goals.extend(self.state["active"].get(goal_type, []))
        if not goals:
            return ""

        resolved_language = resolve_prompt_language(language, settings_source=self.settings)
        assistant_name = resolve_prompt_persona_names(
            settings_source=self.settings,
            language=resolved_language,
        ).assistant
        labels = {
            "ko": f"{assistant_name} 현재 목표",
            "en": f"{assistant_name} Current Goals",
            "ja": f"{assistant_name}現在の目標",
        }[resolved_language]

        lines = [f"[{labels}]"]
        for goal in goals:
            lines.extend(
                [
                    f"- id={goal.get('id', '')}",
                    f"  type={goal.get('type', '')}",
                    f"  title={goal.get('title', '')}",
                    f"  reason={goal.get('reason', '')}",
                ]
            )
        lines.append(f"[/{labels}]")
        return "\n".join(lines)
