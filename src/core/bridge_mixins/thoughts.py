"""
WebBridge? ?? ??? ??? ENE thought ???? ??.
"""
import re

from ...ai.prompt_language import resolve_prompt_language
from ...ai.response_cleanup import extract_goal_update_metadata, extract_thought_metadata, strip_thinking_markers


VISIBLE_RESPONSE_ANALYSIS_KEYS = (
    "user_emotion",
    "user_intent",
    "interaction_effect",
    "bond_delta_hint",
    "stress_delta_hint",
    "energy_delta_hint",
    "valence_delta_hint",
    "confidence",
    "flags",
)


class ThoughtBridgeMixin:
    def _sanitize_visible_response_text(self, text: str) -> str:
        """표시 직전 응답에서 내부 메타데이터와 잔여 감정 태그를 제거한다."""
        sanitized = strip_thinking_markers(text)
        sanitized = re.sub(r"\[analysis\]\s*.*?\s*\[/analysis\]\s*", "", sanitized, flags=re.IGNORECASE | re.DOTALL)
        sanitized, _ = extract_thought_metadata(sanitized)
        sanitized, goal_update = extract_goal_update_metadata(sanitized)
        if goal_update:
            sanitized = re.sub(r"\n{2,}", "\n", sanitized)

        key_pattern = "|".join(re.escape(key) for key in VISIBLE_RESPONSE_ANALYSIS_KEYS)
        leading_meta_pattern = rf"^\s*(?:(?:{key_pattern})\s*=\s*.*(?:\r?\n|$))+"
        sanitized = re.sub(leading_meta_pattern, "", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"^\s*\n+", "", sanitized)

        sanitized = re.sub(r"\[(\w+)\]", "", sanitized)
        return sanitized.strip()

    def _sanitize_visible_thought_text(self, thought: str) -> str:
        """표시용 속마음에서 블록 태그와 과도한 공백을 제거한다."""
        sanitized = strip_thinking_markers(thought)
        _, extracted = extract_thought_metadata(sanitized)
        if extracted:
            sanitized = extracted
        sanitized = re.sub(r"\[/?(?:subconscious|thought|ene_thought|inner_thought|생각|속마음|에네\s*생각|에네생각)\]", "", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"\s+", " ", sanitized)
        return sanitized.strip()

    def _are_ene_thoughts_enabled(self) -> bool:
        """설정에서 에네 생각 표시 기능 활성화 여부를 확인한다."""
        settings_source = getattr(self, "settings", None)
        if isinstance(settings_source, dict):
            return bool(settings_source.get("enable_ene_thoughts", True))
        getter = getattr(settings_source, "get", None)
        if callable(getter):
            try:
                return bool(getter("enable_ene_thoughts", True))
            except TypeError:
                pass
        config = getattr(settings_source, "config", None)
        if isinstance(config, dict):
            return bool(config.get("enable_ene_thoughts", True))
        return True

    def _read_bool_setting(self, key: str, default: bool = False) -> bool:
        """dict/Settings 객체 양쪽에서 bool 설정을 안전하게 읽는다."""
        settings_source = getattr(self, "settings", None)
        if isinstance(settings_source, dict):
            return bool(settings_source.get(key, default))
        getter = getattr(settings_source, "get", None)
        if callable(getter):
            try:
                return bool(getter(key, default))
            except TypeError:
                pass
        config = getattr(settings_source, "config", None)
        if isinstance(config, dict):
            return bool(config.get(key, default))
        return bool(default)

    def _read_int_setting(self, key: str, default: int = 0, minimum: int = 0, maximum: int = 50) -> int:
        """dict/Settings 객체 양쪽에서 int 설정을 범위 안으로 읽는다."""
        settings_source = getattr(self, "settings", None)
        raw_value = default
        if isinstance(settings_source, dict):
            raw_value = settings_source.get(key, default)
        else:
            getter = getattr(settings_source, "get", None)
            if callable(getter):
                try:
                    raw_value = getter(key, default)
                except TypeError:
                    raw_value = default
            else:
                config = getattr(settings_source, "config", None)
                if isinstance(config, dict):
                    raw_value = config.get(key, default)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    def _is_ene_thought_context_enabled(self) -> bool:
        """생각 표시와 컨텍스트 반영 설정이 모두 켜져 있는지 확인한다."""
        thoughts_enabled = getattr(self, "_are_ene_thoughts_enabled", None)
        if not callable(thoughts_enabled):
            thoughts_enabled = lambda: ThoughtBridgeMixin._are_ene_thoughts_enabled(self)
        read_bool = getattr(self, "_read_bool_setting", None)
        if not callable(read_bool):
            read_bool = lambda key, default=False: ThoughtBridgeMixin._read_bool_setting(self, key, default)
        return thoughts_enabled() and read_bool(
            "include_ene_thoughts_in_context",
            False,
        )

    def _resolve_ene_thought_context_limit(self) -> int:
        """다음 턴에 반영할 최근 에네 생각 개수를 읽는다."""
        read_int = getattr(self, "_read_int_setting", None)
        if not callable(read_int):
            read_int = lambda key, default=0, minimum=0, maximum=50: ThoughtBridgeMixin._read_int_setting(
                self,
                key,
                default,
                minimum,
                maximum,
            )
        return read_int("ene_thought_context_limit", 2, minimum=0, maximum=20)

    def _remember_ene_thought_for_context(self, thought: str) -> None:
        """표시용 생각을 다음 턴 선택 컨텍스트용 메타 버퍼에 보관한다."""
        thoughts_enabled = getattr(self, "_are_ene_thoughts_enabled", None)
        if not callable(thoughts_enabled):
            thoughts_enabled = lambda: ThoughtBridgeMixin._are_ene_thoughts_enabled(self)
        if not thoughts_enabled():
            return
        sanitize_thought = getattr(self, "_sanitize_visible_thought_text", None)
        if not callable(sanitize_thought):
            sanitize_thought = lambda value: ThoughtBridgeMixin._sanitize_visible_thought_text(self, value)
        sanitized = sanitize_thought(thought)
        if not sanitized:
            return
        entries = getattr(self, "_ene_thought_context_buffer", None)
        if not isinstance(entries, list):
            entries = []
            self._ene_thought_context_buffer = entries

        conversation = getattr(self, "conversation_buffer", []) or []
        conversation_index = len(conversation) - 1 if conversation else -1
        timestamp = ""
        if conversation_index >= 0:
            item = conversation[conversation_index]
            if item and len(item) >= 3:
                timestamp = str(item[2] or "").strip()

        entries.append(
            {
                "conversation_index": conversation_index,
                "timestamp": timestamp,
                "thought": sanitized,
            }
        )
        del entries[:-50]

    def _discard_ene_thought_context_from_index(self, conversation_index: int) -> None:
        """리롤/수정으로 제거되는 assistant 턴 이후의 생각 메타를 버린다."""
        entries = getattr(self, "_ene_thought_context_buffer", None)
        if not isinstance(entries, list):
            return
        kept = []
        for entry in entries:
            try:
                entry_index = int(entry.get("conversation_index", -1))
            except Exception:
                entry_index = -1
            if entry_index < 0 or entry_index < conversation_index:
                kept.append(entry)
        self._ene_thought_context_buffer = kept

    def _ene_thought_context_labels(self) -> dict[str, str]:
        """프롬프트 언어에 맞는 에네 생각 컨텍스트 라벨을 반환한다."""
        language = resolve_prompt_language(settings_source=getattr(self, "settings", None))
        if language == "ko":
            return {
                "open": "[에네의 이전 내심 메모]",
                "close": "[/에네의 이전 내심 메모]",
                "latest": "직전 생각",
                "previous": "이전 생각 {index}",
            }
        if language == "ja":
            return {
                "open": "[エネの以前の内心メモ]",
                "close": "[/エネの以前の内心メモ]",
                "latest": "直前の内心メモ",
                "previous": "以前の内心メモ {index}",
            }
        return {
            "open": "[ENE Previous Inner Notes]",
            "close": "[/ENE Previous Inner Notes]",
            "latest": "Previous thought",
            "previous": "Earlier thought {index}",
        }

    def _build_ene_thought_context(self) -> str:
        """설정이 켜져 있으면 최근 에네 생각을 다음 턴 내부 컨텍스트로 만든다."""
        context_enabled = getattr(self, "_is_ene_thought_context_enabled", None)
        if not callable(context_enabled):
            context_enabled = lambda: ThoughtBridgeMixin._is_ene_thought_context_enabled(self)
        if not context_enabled():
            return ""
        resolve_limit = getattr(self, "_resolve_ene_thought_context_limit", None)
        if not callable(resolve_limit):
            resolve_limit = lambda: ThoughtBridgeMixin._resolve_ene_thought_context_limit(self)
        limit = resolve_limit()
        if limit <= 0:
            return ""
        entries = getattr(self, "_ene_thought_context_buffer", []) or []
        thoughts = []
        for entry in entries:
            text = ""
            if isinstance(entry, dict):
                text = str(entry.get("thought", "") or "").strip()
            else:
                text = str(entry or "").strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                thoughts.append(text)
        if not thoughts:
            return ""

        label_builder = getattr(self, "_ene_thought_context_labels", None)
        if not callable(label_builder):
            label_builder = lambda: ThoughtBridgeMixin._ene_thought_context_labels(self)
        labels = label_builder()
        lines = [labels["open"]]
        for index, thought in enumerate(reversed(thoughts[-limit:]), start=1):
            label = labels["latest"] if index == 1 else labels["previous"].format(index=index)
            lines.append(f"- {label}: {thought}")
        lines.append(labels["close"])
        return "\n".join(lines)

    def _with_ene_thought_context(self, message: str) -> str:
        """현재 사용자 메시지 앞에 선택형 에네 생각 컨텍스트를 붙인다."""
        build_context = getattr(self, "_build_ene_thought_context", None)
        if not callable(build_context):
            build_context = lambda: ThoughtBridgeMixin._build_ene_thought_context(self)
        context = build_context()
        if not context:
            return message
        return f"{context}\n\n{message}"
