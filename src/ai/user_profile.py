"""
User profile manager.
Stores durable user facts extracted from conversations.
"""
from dataclasses import dataclass, asdict, field, fields
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

from .profile_updates import is_current_update, parse_memory_time

from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


@dataclass
class ProfileFact:
    """Single user fact."""
    content: str
    category: str  # basic, preference, goal, habit
    timestamp: str
    source: str = ""
    id: str = ""
    subject: str = ""
    state: str = "active"
    effective_at: str = ""
    source_memory_id: str = ""
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid5(NAMESPACE_URL, f"{self.category}|{self.timestamp}|{self.content}"))

    @classmethod
    def from_dict(cls, data):
        """구형 저장 파일과 추가 필드가 있는 파일을 함께 읽는다."""
        names = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})

    def to_dict(self) -> dict:
        return asdict(self)


class UserProfile:
    """User profile manager."""

    ALLOWED_CATEGORIES = {"basic", "preference", "goal", "habit"}
    MIN_CONFIDENCE = 0.65

    def __init__(self, profile_file: str | Path | None = None):
        target_file = profile_file if profile_file is not None else "user_profile.json"
        self.profile_file = resolve_user_storage_path(target_file)
        self.facts: List[ProfileFact] = []

        self.basic_info: Dict[str, str] = {}
        self.preferences: Dict[str, List[str]] = {
            "likes": [],
            "dislikes": [],
        }

        self.load()

    def load(self):
        """Load profile from JSON file."""
        try:
            data = load_json_data(self.profile_file, encoding="utf-8-sig")

            self.facts = [ProfileFact.from_dict(fact) for fact in data.get("facts", [])]
            self.basic_info = data.get("basic_info", {})
            self.preferences = data.get("preferences", {"likes": [], "dislikes": []})

            print(f"[Profile] Loaded {len(self.facts)} facts")

        except Exception as e:
            if self.profile_file.exists():
                print(f"[Profile] Load failed: {e}")
            else:
                print("[Profile] Profile file not found. Starting fresh.")

    def save(self):
        """Save profile to JSON file."""
        try:
            data = {
                "facts": [fact.to_dict() for fact in self.facts],
                "basic_info": self.basic_info,
                "preferences": self.preferences,
                "last_updated": datetime.now().isoformat(),
            }

            save_json_data(
                self.profile_file,
                data,
                encoding="utf-8",
                indent=2,
                ensure_ascii=False,
                trailing_newline=True,
            )

            print(f"[Profile] Saved {len(self.facts)} facts")

        except Exception as e:
            print(f"[Profile] Save failed: {e}")

    def add_fact(self, content: str, category: str = "fact", source: str = ""):
        """Add a new durable fact if it passes policy checks."""
        content = self._normalize_fact(content)
        if not content:
            return

        tagged = re.match(r"^\[(basic|preference|goal|habit)\]\s*(.+)$", content, re.IGNORECASE)
        if tagged:
            category = tagged.group(1).lower()
            content = tagged.group(2).strip()

        inferred_category = (category or "fact").lower().strip()
        if inferred_category == "fact":
            inferred_category = self._infer_category(content)

        if inferred_category not in self.ALLOWED_CATEGORIES:
            print(f"[Profile] Skip non-durable or unclassified fact: {content}")
            return

        if self._is_temporary_fact(content):
            print(f"[Profile] Skip temporary fact: {content}")
            return

        confidence = self._estimate_confidence(content, inferred_category)
        if confidence < self.MIN_CONFIDENCE:
            print(f"[Profile] Skip low-confidence fact ({confidence:.2f}): {content}")
            return

        for fact in self.facts:
            if fact.content == content:
                print(f"[Profile] Fact already exists: {content}")
                return

        fact = ProfileFact(
            content=content,
            category=inferred_category,
            timestamp=datetime.now().isoformat(),
            source=source,
        )
        self.facts.append(fact)

        if inferred_category == "basic":
            self._update_basic_info(content)
        elif inferred_category == "preference":
            self._update_preferences(content)

        self.save()
        print(f"[Profile] Added fact: [{inferred_category}] {content}")

    def apply_summary_facts(self, facts, updates, *, original_messages, source="", source_memory_id="", observed_at="", reviewed=False):
        """선택된 내용과 검증된 변경안만 반영하며 원래 값을 이력으로 남긴다."""
        if updates is None:
            # 구형 응답은 원문 요약만 보존한다. 명시적으로 검토한 사실만 추가한다.
            if reviewed:
                for content in facts:
                    self.add_fact(content, source=source)
            return
        selected = {self._normalize_fact(value) for value in facts if isinstance(value, str)}
        timestamp = observed_at or datetime.now().astimezone().isoformat()
        for update in updates if isinstance(updates, list) else []:
            manual_edit = reviewed and isinstance(update, dict) and update.get("manual_edit") is True
            if not manual_edit and not is_current_update(update, original_messages):
                continue
            category = str(update.get("category", "")).strip()
            content = self._normalize_fact(update.get("content", ""))
            state = str(update.get("state", "active"))
            if category not in self.ALLOWED_CATEGORIES or state not in {"active", "completed", "cancelled", "paused"}:
                continue
            if f"[{category}] {content}" not in selected or not content:
                continue
            recorded_at = datetime.now().astimezone().isoformat() if manual_edit else timestamp
            effective_at = str(update.get("effective_at") or recorded_at)
            effective_time = parse_memory_time(effective_at)
            observed_time = parse_memory_time(recorded_at)
            if effective_time is None or observed_time is None or effective_time > observed_time:
                continue
            target_id = str(update.get("replaces") or "")
            existing = next((fact for fact in self.facts if fact.id == target_id), None)
            if target_id and existing is None:
                continue
            subject = str(update.get("subject") or "").strip()
            if not subject:
                continue
            if existing is None:
                matches = [fact for fact in self.facts if fact.category == category and fact.subject == subject]
                if len(matches) > 1:
                    continue
                existing = matches[0] if matches else None
            if existing:
                previous_time = parse_memory_time(existing.effective_at or existing.timestamp)
                if (existing.category != category and not manual_edit) or (previous_time and effective_time < previous_time):
                    continue
                if existing.content == content and existing.state == state and existing.category == category:
                    if previous_time is None or effective_time > previous_time:
                        existing.effective_at = effective_at
                        existing.timestamp = recorded_at
                        existing.source = source
                        existing.source_memory_id = "" if manual_edit else source_memory_id
                    continue
                # 같은 출처의 재시도나 뒤늦은 결과가 이미 반영된 값을 다시 바꾸지 않는다.
                if source_memory_id and existing.source_memory_id == source_memory_id:
                    continue
                self._remove_derived_fact(existing)
                previous = existing.to_dict()
                previous.pop("history", None)
                existing.history.append(previous)
                existing.content = content
                existing.category = category
                existing.timestamp = recorded_at
                existing.source = source
            else:
                if any(fact.content == content and fact.category == category for fact in self.facts):
                    continue
                existing = ProfileFact(content, category, recorded_at, source)
                self.facts.append(existing)
            existing.subject = subject
            existing.state = state
            existing.effective_at = effective_at
            existing.source_memory_id = "" if manual_edit else source_memory_id
            if manual_edit:
                existing.source = f"수동 검토 ({recorded_at})"
            if category == "basic":
                self._update_basic_info(content)
            elif category == "preference":
                self._update_preferences(content)
        self.save()

    def _remove_derived_fact(self, fact):
        """해당 사실에서 만들어진 값만 제거해 무관한 수동 값은 보존한다."""
        for kind in ("likes", "dislikes"):
            self.preferences[kind] = [value for value in self.preferences.get(kind, []) if value != fact.content]
        if fact.category == "basic":
            derived = self.basic_values(fact.content)
            self.basic_info = {key: value for key, value in self.basic_info.items() if derived.get(key) != value}

    def _normalize_fact(self, content: str) -> str:
        text = content.strip() if isinstance(content, str) else ""
        text = text.replace("마스터는", "").replace("마스터가", "").strip()
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _is_temporary_fact(self, content: str) -> bool:
        content_lower = content.lower()
        temporary_markers = [
            "오늘", "지금", "방금", "최근", "요즘", "이번 주", "오늘은",
            "today", "now", "recently", "just", "this week",
        ]
        return any(marker in content_lower for marker in temporary_markers)

    def _infer_category(self, content: str) -> Optional[str]:
        text = content.lower()

        basic_markers = [
            "이름", "name", "성별", "gender", "생일", "birthday",
            "직업", "occupation", "전공", "major",
        ]
        preference_markers = [
            "좋아", "선호", "취향", "싫어", "like", "prefer", "favorite", "dislike",
        ]
        goal_markers = [
            "목표", "계획", "취업", "toeic", "토익", "준비", "goal", "plan", "aim",
        ]
        habit_markers = [
            "매일", "평소", "보통", "자주", "습관", "루틴", "habit", "usually", "often", "routine",
        ]

        if any(marker in text for marker in basic_markers):
            return "basic"
        if any(marker in text for marker in goal_markers):
            return "goal"
        if any(marker in text for marker in habit_markers):
            return "habit"
        if any(marker in text for marker in preference_markers):
            return "preference"
        return None

    def _estimate_confidence(self, content: str, category: str) -> float:
        score = 0.4
        lowered = content.lower()

        if len(content) >= 10:
            score += 0.2
        if len(content) >= 18:
            score += 0.1

        explicit_markers = [
            "좋아", "싫어", "목표", "계획", "매일", "평소",
            "like", "prefer", "goal", "plan", "usually",
        ]
        if any(marker in lowered for marker in explicit_markers):
            score += 0.15

        if category == "basic" and not re.search(r"\d{4}|name|gender|birthday|major|occupation|이름|성별|생일|전공|직업", lowered):
            score -= 0.15

        uncertain_markers = ["아마", "인듯", "추정", "가끔", "maybe", "probably", "seems"]
        if any(marker in lowered for marker in uncertain_markers):
            score -= 0.2

        return max(0.0, min(1.0, score))

    def _update_basic_info(self, content: str):
        self.basic_info.update(self.basic_values(content))

    @classmethod
    def basic_values(cls, content: str) -> dict[str, str]:
        """기억 문장에서 추출 가능한 기본 정보만 반환한다."""
        text = content.strip()
        values = {}

        if "이름" in text:
            value = cls._extract_korean_field(
                text,
                "이름",
                stop_words=("전공", "성별", "생일", "직업"),
            )
            if value:
                values["name"] = value

        if "성별" in text:
            value = text.split(":", 1)[-1].strip() if ":" in text else text
            if value:
                values["gender"] = value

        if "생일" in text:
            m = re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text)
            if m:
                values["birthday"] = m.group(0).replace("/", "-").replace(".", "-")

        if "직업" in text:
            value = text.split(":", 1)[-1].strip() if ":" in text else text
            if value:
                values["occupation"] = value

        if "전공" in text:
            value = cls._extract_korean_field(
                text,
                "전공",
                stop_words=("이름", "성별", "생일", "직업"),
            )
            if value:
                values["major"] = value
        return values

    @staticmethod
    def _extract_korean_field(text: str, label: str, stop_words: tuple[str, ...] = ()) -> str:
        """한 문장에 여러 기본 정보가 섞인 경우 특정 필드 값만 잘라낸다."""
        pattern = rf"{re.escape(label)}\s*(?:[:：]|은|는)?\s*(.+)"
        match = re.search(pattern, text)
        if not match:
            return ""

        value = match.group(1).strip()
        for stop_word in stop_words:
            value = re.split(rf"\s*{re.escape(stop_word)}\s*(?:[:：]|은|는)?", value, maxsplit=1)[0].strip()
        value = re.split(r"(?:이고|이며|입니다|이에요|예요|,|\.|;)", value, maxsplit=1)[0].strip()
        return value

    def _update_preferences(self, content: str):
        """선호 목록에 같은 기억이 중복되지 않게 반영한다."""
        kind = self.preference_kind(content)
        if kind and content not in self.preferences[kind]:
            self.preferences[kind].append(content)

    @staticmethod
    def preference_kind(content: str) -> str:
        """부정 표현부터 판정하여 선호와 비선호를 구분한다."""
        lowered = content.lower()
        if any(k in lowered for k in ["싫어", "dislike", "좋아하지", "선호하지", "do not like", "don't like"]):
            return "dislikes"
        if any(k in lowered for k in ["좋아", "선호", "like", "prefer", "favorite"]):
            return "likes"
        return ""

    def get_facts_by_category(self, category: str) -> List[ProfileFact]:
        """Return facts by category."""
        return [fact for fact in self.facts if fact.category == category]

    def get_all_facts(self) -> List[ProfileFact]:
        """Return all facts."""
        return self.facts

    def delete_fact(self, index: int):
        """Delete one fact by list index."""
        if 0 <= index < len(self.facts):
            deleted = self.facts.pop(index)
            self._remove_derived_fact(deleted)
            self.save()
            print(f"[Profile] Deleted fact: {deleted.content}")

    def get_context_string(self) -> str:
        """Build context string from recent durable facts."""
        if not self.facts:
            return ""

        lines = ["[Known user profile]"]
        recent_facts = sorted(self.facts, key=lambda f: f.timestamp, reverse=True)[:10]
        for fact in recent_facts:
            label = fact.category if fact.state == "active" else f"{fact.category}/{fact.state}"
            lines.append(f"- [{label}] {fact.content}")

        return "\n".join(lines)
