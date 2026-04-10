"""
에네 자기 정보 프로필 관리.
대화에서 추출되거나 수동으로 입력된 에네 장기 정보를 저장한다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import difflib
import re

from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


@dataclass
class EneProfileFact:
    """에네 자기 정보 항목."""

    content: str
    category: str
    timestamp: str
    source: str = ""
    origin: str = "auto"
    auto_update: bool = True
    confidence: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class EneProfile:
    """에네 자기 정보 저장소."""

    ALLOWED_CATEGORIES = {
        "basic",
        "preference",
        "goal",
        "habit",
        "speaking_style",
        "relationship_tone",
    }
    SIMILARITY_THRESHOLD = 0.80

    def __init__(self, profile_file: str | Path | None = None, user_profile=None):
        target_file = profile_file if profile_file is not None else "ene_profile.json"
        self.profile_file = resolve_user_storage_path(target_file)
        self.user_profile = user_profile
        self.core_profile: Dict[str, List[str]] = {
            "identity": [],
            "speaking_style": [],
            "relationship_tone": [],
        }
        self.facts: List[EneProfileFact] = []
        self.load()

    def load(self):
        """JSON 파일에서 프로필을 불러온다."""
        try:
            data = load_json_data(self.profile_file, encoding="utf-8-sig")
            raw_core = data.get("core_profile") or {}
            self.core_profile = {
                "identity": list(raw_core.get("identity", [])),
                "speaking_style": list(raw_core.get("speaking_style", [])),
                "relationship_tone": list(raw_core.get("relationship_tone", [])),
            }
            self.facts = [EneProfileFact(**fact) for fact in data.get("facts", [])]
            print(f"[ENE Profile] Loaded {len(self.facts)} facts")
        except Exception as e:
            if self.profile_file.exists():
                print(f"[ENE Profile] Load failed: {e}")
            else:
                print("[ENE Profile] Profile file not found. Starting fresh.")

    def save(self):
        """JSON 파일에 프로필을 저장한다."""
        try:
            payload = {
                "core_profile": self.core_profile,
                "facts": [fact.to_dict() for fact in self.facts],
                "last_updated": datetime.now().isoformat(),
            }
            save_json_data(
                self.profile_file,
                payload,
                encoding="utf-8-sig",
                indent=2,
                ensure_ascii=False,
                trailing_newline=True,
            )
            print(f"[ENE Profile] Saved {len(self.facts)} facts")
        except Exception as e:
            print(f"[ENE Profile] Save failed: {e}")

    def add_fact(
        self,
        content: str,
        category: str = "fact",
        source: str = "",
        origin: str = "auto",
        auto_update: bool = True,
        confidence: float | None = None,
    ):
        """에네 자기 정보 fact를 정책에 맞게 추가한다."""
        normalized = self._normalize_fact(content)
        if not normalized:
            return

        tagged = re.match(
            r"^\[(basic|preference|goal|habit|speaking_style|relationship_tone)\]\s*(.+)$",
            normalized,
            re.IGNORECASE,
        )
        if tagged:
            category = tagged.group(1).lower()
            normalized = tagged.group(2).strip()

        resolved_category = (category or "").strip().lower()
        if resolved_category == "fact":
            resolved_category = self._infer_category(normalized)

        if resolved_category not in self.ALLOWED_CATEGORIES:
            print(f"[ENE Profile] Skip non-durable fact: {normalized}")
            return

        if self._is_temporary_fact(normalized):
            print(f"[ENE Profile] Skip temporary fact: {normalized}")
            return

        if self._duplicates_user_profile(normalized):
            print(f"[ENE Profile] Skip user-duplicate fact: {normalized}")
            return

        if (
            (origin or "auto").strip().lower() == "auto"
            and self._has_locked_manual_fact(resolved_category)
        ):
            print(f"[ENE Profile] Skip auto fact due to locked manual category: {normalized}")
            return

        existing_index = self._find_similar_fact_index(normalized, resolved_category)
        if existing_index is not None:
            existing = self.facts[existing_index]
            if existing.origin == "manual" and not existing.auto_update:
                print(f"[ENE Profile] Keep locked manual fact: {existing.content}")
                return

            if len(normalized) > len(existing.content):
                existing.content = normalized
            existing.timestamp = datetime.now().isoformat()
            existing.source = source or existing.source
            existing.origin = origin or existing.origin
            existing.auto_update = bool(auto_update)
            existing.confidence = confidence if confidence is not None else existing.confidence
            self.save()
            print(f"[ENE Profile] Updated similar fact: [{resolved_category}] {existing.content}")
            return

        fact = EneProfileFact(
            content=normalized,
            category=resolved_category,
            timestamp=datetime.now().isoformat(),
            source=source,
            origin=(origin or "auto").strip().lower() or "auto",
            auto_update=bool(auto_update),
            confidence=confidence,
        )
        self.facts.append(fact)
        self.save()
        print(f"[ENE Profile] Added fact: [{resolved_category}] {normalized}")

    def delete_fact(self, index: int):
        """fact 인덱스로 항목을 삭제한다."""
        if 0 <= index < len(self.facts):
            deleted = self.facts.pop(index)
            self.save()
            print(f"[ENE Profile] Deleted fact: {deleted.content}")

    def _normalize_fact(self, content: str) -> str:
        text = str(content or "").strip()
        text = text.replace("에네는", "").replace("에네가", "").strip()
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _is_temporary_fact(self, content: str) -> bool:
        lowered = content.lower()
        temporary_markers = [
            "오늘",
            "지금",
            "방금",
            "최근",
            "today",
            "now",
            "recently",
            "just",
        ]
        return any(marker in lowered for marker in temporary_markers)

    def _infer_category(self, content: str) -> Optional[str]:
        lowered = content.lower()
        if any(marker in lowered for marker in ["말투", "문장", "톤", "반응", "말하는 편"]):
            return "speaking_style"
        if any(marker in lowered for marker in ["관계", "거리감", "챙긴다", "대한다"]):
            return "relationship_tone"
        if any(marker in lowered for marker in ["좋아", "선호", "취향", "싫어", "like", "prefer"]):
            return "preference"
        if any(marker in lowered for marker in ["목표", "계획", "goal", "plan"]):
            return "goal"
        if any(marker in lowered for marker in ["매일", "자주", "루틴", "habit", "usually"]):
            return "habit"
        return None

    def _duplicates_user_profile(self, content: str) -> bool:
        if not self.user_profile:
            return False

        normalized = content.lower().strip()
        for fact in getattr(self.user_profile, "facts", []) or []:
            fact_content = str(getattr(fact, "content", "") or "").strip().lower()
            if fact_content == normalized:
                return True
            ratio = difflib.SequenceMatcher(a=normalized, b=fact_content).ratio()
            if ratio >= self.SIMILARITY_THRESHOLD:
                return True

        preferences = getattr(self.user_profile, "preferences", {}) or {}
        for key in ("likes", "dislikes"):
            for item in preferences.get(key, []) or []:
                if str(item).strip().lower() == normalized:
                    return True

        return False

    def _find_similar_fact_index(self, content: str, category: str) -> Optional[int]:
        normalized = content.lower()
        best_idx = None
        best_ratio = 0.0

        for idx, fact in enumerate(self.facts):
            if fact.category != category:
                continue
            ratio = difflib.SequenceMatcher(a=normalized, b=fact.content.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = idx

        if best_idx is not None and best_ratio >= self.SIMILARITY_THRESHOLD:
            return best_idx
        return None

    def _has_locked_manual_fact(self, category: str) -> bool:
        for fact in self.facts:
            if fact.category == category and fact.origin == "manual" and not fact.auto_update:
                return True
        return False
