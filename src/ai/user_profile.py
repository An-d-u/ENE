"""
User profile manager.
Stores durable user facts extracted from conversations.
"""
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime
import json
from pathlib import Path
import difflib
import re


@dataclass
class ProfileFact:
    """Single user fact."""
    content: str
    category: str  # basic, preference, goal, habit
    timestamp: str
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class UserProfile:
    """User profile manager."""

    ALLOWED_CATEGORIES = {"basic", "preference", "goal", "habit"}
    MIN_CONFIDENCE = 0.65
    SIMILARITY_THRESHOLD = 0.80

    def __init__(self, profile_file: str = "user_profile.json"):
        self.profile_file = Path(profile_file)
        self.facts: List[ProfileFact] = []

        self.basic_info: Dict[str, str] = {}
        self.preferences: Dict[str, List[str]] = {
            "likes": [],
            "dislikes": [],
        }

        self.load()

    def load(self):
        """Load profile from JSON file."""
        if not self.profile_file.exists():
            print("[Profile] Profile file not found. Starting fresh.")
            return

        try:
            with open(self.profile_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.facts = [ProfileFact(**fact) for fact in data.get("facts", [])]
            self.basic_info = data.get("basic_info", {})
            self.preferences = data.get("preferences", {"likes": [], "dislikes": []})

            print(f"[Profile] Loaded {len(self.facts)} facts")

        except Exception as e:
            print(f"[Profile] Load failed: {e}")

    def save(self):
        """Save profile to JSON file."""
        try:
            data = {
                "facts": [fact.to_dict() for fact in self.facts],
                "basic_info": self.basic_info,
                "preferences": self.preferences,
                "last_updated": datetime.now().isoformat(),
            }

            with open(self.profile_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

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

        similar_index = self._find_similar_fact_index(content, inferred_category)
        if similar_index is not None:
            existing = self.facts[similar_index]
            if len(content) > len(existing.content):
                existing.content = content
            existing.timestamp = datetime.now().isoformat()
            if source:
                existing.source = source
            self.save()
            print(f"[Profile] Updated similar fact: [{inferred_category}] {existing.content}")
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

    def _normalize_fact(self, content: str) -> str:
        text = (content or "").strip()
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

    def _find_similar_fact_index(self, content: str, category: str) -> Optional[int]:
        normalized = content.lower()
        best_idx = None
        best_ratio = 0.0

        for idx, fact in enumerate(self.facts):
            if fact.category not in {category, "fact"}:
                continue
            ratio = difflib.SequenceMatcher(a=normalized, b=fact.content.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = idx

        if best_idx is not None and best_ratio >= self.SIMILARITY_THRESHOLD:
            return best_idx
        return None

    def _update_basic_info(self, content: str):
        """Best-effort parser for basic profile fields."""
        text = content.strip()

        if "이름" in text:
            value = text.split(":", 1)[-1].strip() if ":" in text else text
            if value:
                self.basic_info["name"] = value

        if "성별" in text:
            value = text.split(":", 1)[-1].strip() if ":" in text else text
            if value:
                self.basic_info["gender"] = value

        if "생일" in text:
            m = re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text)
            if m:
                self.basic_info["birthday"] = m.group(0).replace("/", "-").replace(".", "-")

        if "직업" in text:
            value = text.split(":", 1)[-1].strip() if ":" in text else text
            if value:
                self.basic_info["occupation"] = value

        if "전공" in text:
            value = text.split(":", 1)[-1].strip() if ":" in text else text
            if value:
                self.basic_info["major"] = value

    def _update_preferences(self, content: str):
        """Keep likes/dislikes arrays in sync."""
        lowered = content.lower()
        if any(k in lowered for k in ["좋아", "선호", "like", "prefer", "favorite"]):
            if content not in self.preferences["likes"]:
                self.preferences["likes"].append(content)
        elif any(k in lowered for k in ["싫어", "dislike"]):
            if content not in self.preferences["dislikes"]:
                self.preferences["dislikes"].append(content)

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
            self.save()
            print(f"[Profile] Deleted fact: {deleted.content}")

    def get_context_string(self) -> str:
        """Build context string from recent durable facts."""
        if not self.facts:
            return ""

        lines = ["[Known user profile]"]
        recent_facts = sorted(self.facts, key=lambda f: f.timestamp, reverse=True)[:10]
        for fact in recent_facts:
            lines.append(f"- [{fact.category}] {fact.content}")

        return "\n".join(lines)
