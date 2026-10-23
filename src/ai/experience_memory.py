"""원본과 이력에서 요청 중에만 구성하는 대화 경험 근거."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from .memory_types import MemoryMessage


def _digest(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def memory_revision(memory) -> str:
    """사용 횟수와 벡터를 제외한 원본 개정 지문."""
    return _digest({"summary": memory.summary, "timestamp": memory.timestamp,
                    "messages": [asdict(message) for message in memory.original_messages]})


def _history_revision(item) -> str:
    return _digest({key: getattr(item, key, None) for key in
                    ("state", "text", "source_memory_id", "effective_at", "timestamp")})


@dataclass(frozen=True)
class EvidenceRef:
    memory_id: str
    conversation_id: str
    turn_indexes: tuple[int, ...]
    topic_id: str | None
    clue_id: str | None
    revision: str
    history_revision: str | None = None


@dataclass(frozen=True)
class ExperienceEvidence:
    refs: tuple[EvidenceRef, ...]
    event_at: str | None
    recorded_at: str | None
    messages: tuple[MemoryMessage, ...]
    historical_state: str | None
    source_quality: str
    score: float = 0.0


def collect_history_evidence(results, memories) -> list[ExperienceEvidence]:
    """존재하는 원본에 연결된 이력을 날짜순 절단 없이 읽는다."""
    sources = {memory.id: memory for memory in memories}
    revisions = {}
    seen = set()
    evidence = []
    for result in results:
        for clue in result.topic.clues:
            for item in clue.history:
                memory = sources.get(item.source_memory_id)
                if memory is None:
                    continue
                history_revision = _history_revision(item)
                identity = (memory.id, history_revision)
                if identity in seen:
                    continue
                seen.add(identity)
                if memory.id not in revisions:
                    revisions[memory.id] = memory_revision(memory)
                evidence.append(ExperienceEvidence(
                    refs=(EvidenceRef(memory.id, memory.conversation_id or "", (), result.topic.id,
                                      clue.id, revisions[memory.id], history_revision),),
                    event_at=item.effective_at or None, recorded_at=memory.timestamp or None,
                    messages=(), historical_state=item.text,
                    source_quality="history_only", score=float(result.score),
                ))
    return evidence


def evidence_is_current(evidence, memories, results=()) -> bool:
    """삭제·정정된 출처를 응답 직전에 차단한다."""
    sources = {memory.id: memory for memory in memories}
    for ref in evidence.refs:
        memory = sources.get(ref.memory_id)
        if memory is None or memory_revision(memory) != ref.revision:
            return False
        if ref.history_revision:
            matching = [item for result in results if result.topic.id == ref.topic_id
                        for clue in result.topic.clues if clue.id == ref.clue_id for item in clue.history]
            if not any(_history_revision(item) == ref.history_revision for item in matching):
                return False
    return True
