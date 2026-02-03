"""
장기기억 데이터 구조
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
import json


@dataclass
class MemoryEntry:
    """단일 기억 항목"""
    id: str
    summary: str
    original_messages: List[str]
    timestamp: str  # ISO format
    is_important: bool = False
    embedding: Optional[List[float]] = None
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환 (JSON 저장용)"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryEntry':
        """딕셔너리에서 복원"""
        return cls(**data)
    
    def __repr__(self) -> str:
        important = "⭐" if self.is_important else ""
        return f"{important}[{self.timestamp}] {self.summary[:50]}..."


def create_memory_entry(
    summary: str,
    original_messages: List[str],
    is_important: bool = False,
    embedding: Optional[List[float]] = None,
    tags: Optional[List[str]] = None
) -> MemoryEntry:
    """새 기억 항목 생성"""
    import uuid
    
    return MemoryEntry(
        id=str(uuid.uuid4()),
        summary=summary,
        original_messages=original_messages,
        timestamp=datetime.now().isoformat(),
        is_important=is_important,
        embedding=embedding,
        tags=tags or []
    )
