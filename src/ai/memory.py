"""
장기기억 관리 시스템
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime
import re

from .memory_types import CURRENT_MEMORY_SCHEMA_VERSION, MemoryChunk, MemoryEntry, create_memory_entry
from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data

if TYPE_CHECKING:
    from .embedding import EmbeddingGenerator


_MIGRATED_MEMORY_REQUIRED_FIELDS = (
    "source",
    "memory_type",
    "importance_reason",
    "retrieval_count",
    "last_used_at",
    "confidence",
    "user_confirmed",
    "entity_names",
    "conversation_id",
    "expires_at",
    "schema_version",
    "migration_meta",
    "aliases",
    "trigger_terms",
    "linked_memory_ids",
    "activation_weight",
    "last_activated_at",
    "embedding_provider",
    "embedding_model",
)

_QUERY_TYPE_PATTERNS = {
    "promise": ("기억해줘", "리마인드", "알려줘", "까먹지", "약속"),
    "preference": ("좋아", "싫어", "선호", "취향", "편해", "익숙"),
    "event": ("일정", "예약", "회의", "내일", "오늘", "시간", "날짜"),
    "task": ("해야", "할 일", "정리", "작업", "TODO", "todo"),
    "relationship": ("호칭", "관계", "애칭", "성격"),
}


@dataclass
class MemoryActivationResult:
    """활성화 검색 결과와 점수 근거."""

    memory: MemoryEntry
    activation_score: float
    similarity_score: float
    keyword_score: float
    recent_context_score: float
    link_score: float = 0.0
    direct_match_score: float = 0.0


class MemoryManager:
    """장기기억 관리자"""
    
    def __init__(
        self,
        memory_file: str | Path | None = None,
        embedding_generator: Optional[EmbeddingGenerator] = None
    ):
        """
        Args:
            memory_file: 기억 저장 JSON 파일 경로
            embedding_generator: 임베딩 생성기 (옵션)
        """
        target_file = memory_file if memory_file is not None else "memory.json"
        self.memory_file = resolve_user_storage_path(target_file)
        self.embedding_generator = embedding_generator
        self.memories: List[MemoryEntry] = []
        self._raw_chunk_embedding_cache: Dict[tuple[str, int, int, str], List[float]] = {}
        
        # 파일에서 기억 로드
        self.load()
        
        print(f"[Memory] 기억 파일: {self.memory_file}")
        print(f"[Memory] 로드된 기억 수: {len(self.memories)}")
    
    def _current_embedding_source(self) -> tuple[str | None, str | None]:
        """현재 연결된 임베딩 생성기의 제공자와 모델을 반환한다."""
        if not self.embedding_generator:
            return None, None
        provider = str(getattr(self.embedding_generator, "provider", "voyage") or "voyage").strip().lower()
        model = str(getattr(self.embedding_generator, "model", "") or "").strip()
        return provider or None, model or None

    def _embedding_matches_current_source(self, memory: MemoryEntry) -> bool:
        """저장된 임베딩이 현재 생성기와 같은 출처인지 확인한다."""
        if not getattr(memory, "embedding", None):
            return False
        current_provider, current_model = self._current_embedding_source()
        if not current_provider or not current_model:
            return True
        memory_provider = str(getattr(memory, "embedding_provider", "") or "").strip().lower()
        memory_model = str(getattr(memory, "embedding_model", "") or "").strip()
        return memory_provider == current_provider and memory_model == current_model

    def _embedding_is_stale(self, memory: MemoryEntry) -> bool:
        """임베딩은 있지만 현재 생성기와 출처가 다르면 재생성 대상으로 본다."""
        if not getattr(memory, "embedding", None):
            return False
        return not self._embedding_matches_current_source(memory)

    def mark_unknown_embeddings_source(self, provider: str, model: str) -> int:
        """출처가 비어 있는 기존 임베딩을 지정한 제공자/모델로 표시한다."""
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip()
        if not normalized_provider or not normalized_model:
            return 0

        updated = 0
        for memory in self.memories:
            if not getattr(memory, "embedding", None):
                continue
            if getattr(memory, "embedding_provider", None) or getattr(memory, "embedding_model", None):
                continue
            memory.embedding_provider = normalized_provider
            memory.embedding_model = normalized_model
            updated += 1

        if updated:
            self.save()
        return updated

    def load(self):
        """JSON 파일에서 기억 로드"""
        try:
            data = load_json_data(self.memory_file, encoding="utf-8-sig")
            raw_entries = data.get('memories', [])
            if not isinstance(raw_entries, list):
                raw_entries = []

            self.memories = []
            needs_persist = False
            for raw_entry in raw_entries:
                entry = MemoryEntry.from_dict(raw_entry if isinstance(raw_entry, dict) else {})
                self.memories.append(entry)
                if self._entry_needs_persisted_migration(raw_entry, entry):
                    needs_persist = True
            
            print(f"[Memory] {len(self.memories)}개 기억 로드 완료")
            if needs_persist and self.memory_file.exists():
                print("[Memory] 레거시 기억 스키마를 최신 형식으로 저장합니다.")
                self.save()
            
        except Exception as e:
            if self.memory_file.exists():
                print(f"[Memory] 로드 실패: {e}")
            else:
                print("[Memory] 기억 파일 없음. 새로 생성합니다.")
            self.memories = []

    def _entry_needs_persisted_migration(
        self,
        raw_entry,
        normalized_entry: MemoryEntry | None = None,
    ) -> bool:
        """레거시 항목인지 확인해 최신 스키마로 재저장이 필요한지 판단한다."""
        if not isinstance(raw_entry, dict):
            return True

        try:
            schema_version = int(raw_entry.get("schema_version", 0))
        except (TypeError, ValueError):
            schema_version = 0

        if schema_version < CURRENT_MEMORY_SCHEMA_VERSION:
            return True

        if any(field_name not in raw_entry for field_name in _MIGRATED_MEMORY_REQUIRED_FIELDS):
            return True

        entry = normalized_entry or MemoryEntry.from_dict(raw_entry)
        canonical = entry.to_dict()
        return any(
            raw_entry.get(field_name) != canonical.get(field_name)
            for field_name in _MIGRATED_MEMORY_REQUIRED_FIELDS
        )
    
    def save(self):
        """JSON 파일에 기억 저장"""
        try:
            data = {
                'memories': [memory.to_dict() for memory in self.memories],
                'last_updated': datetime.now().isoformat()
            }

            save_json_data(
                self.memory_file,
                data,
                encoding="utf-8",
                indent=2,
                ensure_ascii=False,
            )
            
            print(f"[Memory] {len(self.memories)}개 기억 저장 완료")
            
        except Exception as e:
            print(f"[Memory] 저장 실패: {e}")
    
    async def add_summary(
        self,
        summary: str,
        original_messages: List[str],
        is_important: bool = False,
        tags: Optional[List[str]] = None,
        source: str = "chat",
        memory_type: str = "general",
        importance_reason: Optional[str] = None,
        confidence: Optional[float] = None,
        entity_names: Optional[List[str]] = None,
        aliases: Optional[List[str]] = None,
        trigger_terms: Optional[List[str]] = None,
    ) -> MemoryEntry:
        """
        새 요약 추가
        
        Args:
            summary: 요약 텍스트
            original_messages: 원본 메시지 리스트
            is_important: 중요 여부
            tags: 태그 리스트
            source: 기억 출처
            memory_type: 기억 유형
            importance_reason: 중요도 이유
            confidence: 기억 신뢰도
            entity_names: 연관 엔티티 이름 목록
            aliases: 기억을 다르게 부를 수 있는 별칭 목록
            trigger_terms: 기억 활성화에 사용할 짧은 키워드 목록
            
        Returns:
            생성된 MemoryEntry
        """
        # 임베딩 생성
        embedding = None
        embedding_provider = None
        embedding_model = None
        if self.embedding_generator:
            try:
                embedding = await self.embedding_generator.embed(summary)
                embedding_provider, embedding_model = self._current_embedding_source()
                print(f"[Memory] 임베딩 생성 완료 (차원: {len(embedding)})")
            except Exception as e:
                print(f"[Memory] 임베딩 생성 실패: {e}")
        
        # 기억 항목 생성
        memory = create_memory_entry(
            summary=summary,
            original_messages=original_messages,
            is_important=is_important,
            embedding=embedding,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            tags=tags,
            source=source,
            memory_type=memory_type,
            importance_reason=importance_reason,
            confidence=confidence,
            entity_names=entity_names,
            aliases=aliases,
            trigger_terms=trigger_terms,
        )
        
        self.memories.append(memory)
        self.save()
        
        print(f"[Memory] 새 기억 추가 chars={len(summary or '')}")
        return memory
    
    async def find_similar(
        self,
        query: str,
        top_k: int = 3,
        min_similarity: float = 0.5,
        *,
        mark_retrieved: bool = True,
    ) -> List[Tuple[MemoryEntry, float]]:
        """
        유사 기억 검색
        
        Args:
            query: 검색 쿼리
            top_k: 상위 k개 반환
            min_similarity: 최소 유사도 임계값
            
        Returns:
            (MemoryEntry, 유사도) 튜플 리스트
        """
        ranked = await self._rank_similar_memories(
            query,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        result = [(memory, final_score) for memory, final_score, _ in ranked]
        if mark_retrieved:
            self._mark_memories_retrieved([memory for memory, _ in result])

        if result:
            print(f"[Memory] 유사 기억 {len(result)}개 찾음 (임계값: {min_similarity})")
            for memory, sim in result:
                print(f"  - [{sim:.3f}] chars={len(memory.summary or '')}")
        return result

    async def regenerate_embeddings(self) -> dict[str, int]:
        """현재 임베딩 생성기로 모든 메모리 요약 임베딩을 다시 만든다."""
        result = {
            "total": len(self.memories),
            "updated": 0,
            "failed": 0,
            "skipped": 0,
        }
        if not self.embedding_generator:
            result["skipped"] = len(self.memories)
            return result

        current_provider, current_model = self._current_embedding_source()
        updated = False
        for memory in self.memories:
            summary = str(getattr(memory, "summary", "") or "").strip()
            if not summary:
                result["skipped"] += 1
                continue
            try:
                memory.embedding = await self.embedding_generator.embed(summary)
                memory.embedding_provider = current_provider
                memory.embedding_model = current_model
                result["updated"] += 1
                updated = True
            except Exception as error:
                result["failed"] += 1
                print(f"[Memory] 임베딩 재생성 실패: {error}")

        if updated:
            self._raw_chunk_embedding_cache.clear()
            self.save()
        return result

    async def _rank_similar_memories(
        self,
        query: str,
        top_k: int = 3,
        min_similarity: float = 0.5,
    ) -> List[Tuple[MemoryEntry, float, float]]:
        """기억 검색 후보를 최종 점수와 순수 유사도로 함께 반환한다."""
        if not self.embedding_generator:
            print("[Memory] 임베딩 생성기가 없어 검색 불가")
            return []
        
        # 임베딩이 있는 기억만 필터링
        memories_with_embedding = [
            m for m in self.memories if self._embedding_matches_current_source(m)
        ]
        
        if not memories_with_embedding:
            print("[Memory] 임베딩된 기억 없음")
            return []
        
        try:
            # 쿼리 임베딩
            query_embedding = await self.embedding_generator.embed(query)
            query_memory_type = self._infer_query_memory_type(query)
            
            # 유사도 계산
            similarities = []
            max_similarity = 0.0
            
            for memory in memories_with_embedding:
                similarity = self.embedding_generator.cosine_similarity(
                    query_embedding,
                    memory.embedding
                )
                
                if similarity > max_similarity:
                    max_similarity = similarity
                
                if similarity >= min_similarity:
                    final_score = similarity + self._metadata_rank_bonus(memory, query_memory_type)
                    similarities.append((memory, final_score, similarity))
            
            # 디버깅: 최대 유사도 출력
            print(f"[Memory] 검색 쿼리 chars={len(query or '')} max_similarity={max_similarity:.4f}")
            
            # 최종 점수 높은 순으로 정렬하고, 동점이면 기본 유사도를 우선한다.
            similarities.sort(key=lambda item: (item[1], item[2]), reverse=True)
            ranked = similarities[:top_k]

            if not ranked:
                print(f"[Memory] 임계값({min_similarity}) 이상의 유사 기억 없음 (최대: {max_similarity:.3f})")

            return ranked
            
        except Exception as e:
            print(f"[Memory] 검색 실패: {e}")
            return []

    async def find_activated(
        self,
        latest_query: str,
        recent_context: str = "",
        top_k: int = 3,
        min_similarity: float = 0.5,
        expand_hops: int = 1,
    ) -> List[MemoryActivationResult]:
        """유사도 위에 별칭/트리거/최근 대화 신호를 얹어 기억을 고른다."""
        max_results = max(0, int(top_k or 0))
        if max_results == 0:
            return []

        candidate_k = max(max_results * 3, max_results)
        similar_candidates = await self._rank_similar_memories(
            latest_query,
            top_k=candidate_k,
            min_similarity=min_similarity,
        )
        direct_match_scores = self._direct_activation_match_scores(latest_query)
        ranked: list[MemoryActivationResult] = []
        raw_similarity_by_id = {
            str(getattr(memory, "id", "") or "").strip(): raw_similarity
            for memory, _, raw_similarity in similar_candidates
        }
        ranked_memory_ids: set[str] = set()
        for memory, _, raw_similarity in similar_candidates:
            memory_id = str(getattr(memory, "id", "") or "").strip()
            if memory_id:
                ranked_memory_ids.add(memory_id)
            ranked.append(
                self._build_activation_result(
                    memory=memory,
                    similarity_score=raw_similarity,
                    latest_query=latest_query,
                    recent_context=recent_context,
                    direct_match_score=direct_match_scores.get(memory_id, 0.0),
                )
            )
        direct_only_candidates = [
            (memory, score)
            for memory, score in self._direct_activation_candidates(direct_match_scores)
            if str(getattr(memory, "id", "") or "").strip() not in ranked_memory_ids
        ]
        for memory, direct_match_score in direct_only_candidates:
            ranked.append(
                self._build_activation_result(
                    memory=memory,
                    similarity_score=0.0,
                    latest_query=latest_query,
                    recent_context=recent_context,
                    direct_match_score=direct_match_score,
                )
            )

        if not ranked:
            return []

        ranked.sort(key=lambda item: item.activation_score, reverse=True)
        selected = self._select_activation_results(
            ranked,
            latest_query=latest_query,
            recent_context=recent_context,
            max_results=max_results,
            expand_hops=expand_hops,
            raw_similarity_by_id=raw_similarity_by_id,
        )
        self._mark_activation_results_used(selected)

        if selected:
            print(f"[Memory] 활성화 기억 {len(selected)}개 찾음")
            for result in selected:
                print(
                    "  - "
                    f"[{result.activation_score:.3f}] "
                    f"chars={len(result.memory.summary or '')}"
                )
        else:
            print("[Memory] 활성화 기억 없음")

        return selected

    def _build_activation_result(
        self,
        memory: MemoryEntry,
        similarity_score: float,
        latest_query: str,
        recent_context: str,
        link_score: float = 0.0,
        direct_match_score: float = 0.0,
    ) -> MemoryActivationResult:
        """단일 기억의 활성화 점수와 근거를 계산한다."""
        activation_text = self._memory_activation_text(memory)
        keyword_score = self._keyword_overlap_score(latest_query, activation_text)
        recent_context_score = self._keyword_overlap_score(recent_context, activation_text)
        weight = self._activation_weight(memory)
        bounded_direct_match_score = max(0.0, min(1.0, float(direct_match_score)))
        activation_score = (
            (max(0.0, float(similarity_score)) * 0.64)
            + (bounded_direct_match_score * 0.42)
            + (keyword_score * 0.22)
            + (recent_context_score * 0.10)
            + (link_score * 0.04)
        ) * weight
        return MemoryActivationResult(
            memory=memory,
            activation_score=activation_score,
            similarity_score=float(similarity_score),
            keyword_score=keyword_score,
            recent_context_score=recent_context_score,
            link_score=link_score,
            direct_match_score=bounded_direct_match_score,
        )

    def _memory_activation_text(self, memory: MemoryEntry) -> str:
        """활성화 검색에 사용할 대표 텍스트를 모은다."""
        parts: list[str] = [
            str(getattr(memory, "summary", "") or ""),
            " ".join(getattr(memory, "tags", []) or []),
            " ".join(getattr(memory, "entity_names", []) or []),
            " ".join(getattr(memory, "aliases", []) or []),
            " ".join(getattr(memory, "trigger_terms", []) or []),
        ]
        for message in getattr(memory, "original_messages", []) or []:
            parts.append(str(getattr(message, "text", message) or ""))
        return "\n".join(part for part in parts if part)

    def _activation_weight(self, memory: MemoryEntry) -> float:
        """기억별 활성화 가중치를 안전한 범위로 제한한다."""
        try:
            return max(0.1, min(3.0, float(getattr(memory, "activation_weight", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    def _select_activation_results(
        self,
        ranked: list[MemoryActivationResult],
        latest_query: str,
        recent_context: str,
        max_results: int,
        expand_hops: int,
        raw_similarity_by_id: dict[str, float],
    ) -> list[MemoryActivationResult]:
        """직접 후보와 연결 후보를 같은 점수 기준으로 고른다."""
        candidate_pool = list(ranked)
        if int(expand_hops or 0) > 0:
            for result in ranked:
                candidate_pool.extend(
                    self._expand_linked_activation_results(
                        result,
                        latest_query=latest_query,
                        recent_context=recent_context,
                        raw_similarity_by_id=raw_similarity_by_id,
                    )
                )

        candidate_pool.sort(key=lambda item: item.activation_score, reverse=True)
        selected: list[MemoryActivationResult] = []
        seen_ids: set[str] = set()

        for result in candidate_pool:
            memory_id = str(getattr(result.memory, "id", "") or "").strip()
            if memory_id and memory_id in seen_ids:
                continue
            if memory_id:
                seen_ids.add(memory_id)
            selected.append(result)
            if len(selected) >= max_results:
                break

        return selected

    def _expand_linked_activation_results(
        self,
        parent: MemoryActivationResult,
        latest_query: str,
        recent_context: str,
        raw_similarity_by_id: dict[str, float],
    ) -> list[MemoryActivationResult]:
        """선택된 기억의 1-hop 연결 기억을 활성화 결과로 변환한다."""
        linked_results: list[MemoryActivationResult] = []
        memory_by_id = self._memory_by_id()
        for linked_id in getattr(parent.memory, "linked_memory_ids", []) or []:
            linked_memory = memory_by_id.get(str(linked_id or "").strip())
            if linked_memory is None:
                continue
            if linked_memory.id == parent.memory.id:
                continue
            linked_memory_id = str(getattr(linked_memory, "id", "") or "").strip()
            link_score = max(0.0, min(1.0, parent.activation_score))
            direct_similarity = raw_similarity_by_id.get(linked_memory_id)
            relation_similarity = (
                direct_similarity
                if direct_similarity is not None
                else min(0.45, max(0.0, parent.similarity_score * 0.55))
            )
            linked_result = self._build_activation_result(
                memory=linked_memory,
                similarity_score=relation_similarity,
                latest_query=latest_query,
                recent_context=recent_context,
                link_score=link_score,
            )
            if (
                direct_similarity is None
                and linked_result.keyword_score <= 0.0
                and linked_result.recent_context_score <= 0.0
            ):
                continue
            linked_results.append(linked_result)
        return linked_results

    def _memory_by_id(self) -> dict[str, MemoryEntry]:
        """현재 로드된 기억을 id 기준으로 조회할 수 있게 만든다."""
        return {
            str(getattr(memory, "id", "") or "").strip(): memory
            for memory in self.memories
            if str(getattr(memory, "id", "") or "").strip()
        }

    def _mark_activation_results_used(self, results: list[MemoryActivationResult]):
        """실제로 주입 대상으로 선택된 기억만 사용 메타데이터를 갱신한다."""
        if not results:
            return

        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        for result in results:
            memory = result.memory
            memory.retrieval_count = int(memory.retrieval_count or 0) + 1
            memory.last_used_at = now_iso
            memory.last_activated_at = now_iso
        self.save()

    def _direct_activation_candidates(
        self,
        direct_match_scores: dict[str, float],
    ) -> list[tuple[MemoryEntry, float]]:
        """별칭/대상/트리거가 직접 맞은 기억 후보를 점수순으로 반환한다."""
        candidates: list[tuple[MemoryEntry, float]] = []
        for memory in self.memories:
            memory_id = str(getattr(memory, "id", "") or "").strip()
            score = direct_match_scores.get(memory_id, 0.0)
            if score <= 0.0:
                continue
            candidates.append((memory, score))
        candidates.sort(
            key=lambda item: (
                item[1],
                str(getattr(item[0], "timestamp", "") or ""),
            ),
            reverse=True,
        )
        return candidates

    def _direct_activation_match_scores(self, query: str) -> dict[str, float]:
        """현재 질문과 직접 맞는 별칭/대상/트리거 점수를 계산한다."""
        normalized_query = self._normalize_direct_match_text(query)
        compact_query = normalized_query.replace(" ", "")
        if not compact_query:
            return {}

        scores: dict[str, float] = {}
        for memory in self.memories:
            memory_id = str(getattr(memory, "id", "") or "").strip()
            if not memory_id:
                continue

            alias_match_count = sum(
                1
                for term in getattr(memory, "aliases", []) or []
                if self._direct_phrase_matches(normalized_query, compact_query, term)
            )
            entity_match_count = sum(
                1
                for term in getattr(memory, "entity_names", []) or []
                if self._direct_phrase_matches(normalized_query, compact_query, term)
            )
            trigger_matches = [
                term
                for term in getattr(memory, "trigger_terms", []) or []
                if self._direct_phrase_matches(normalized_query, compact_query, term)
            ]

            score = 0.0
            if alias_match_count > 0:
                score = 1.0
            elif entity_match_count > 0:
                score = 0.62
            elif self._has_conservative_trigger_match(trigger_matches):
                score = min(0.85, 0.45 + (0.15 * len(trigger_matches)))

            if score > 0.0:
                scores[memory_id] = score
        return scores

    def _normalize_direct_match_text(self, text: str) -> str:
        """직접 매칭용으로 대소문자와 구두점을 정규화한다."""
        normalized = re.sub(r"[^0-9a-z가-힣]+", " ", str(text or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _direct_phrase_matches(
        self,
        normalized_query: str,
        compact_query: str,
        term: str,
    ) -> bool:
        """공백 차이를 허용해 짧은 별칭/트리거가 질문에 들어있는지 본다."""
        normalized_term = self._normalize_direct_match_text(term)
        compact_term = normalized_term.replace(" ", "")
        if len(compact_term) < 2:
            return False
        if re.search(r"[a-z0-9]", compact_term):
            return self._ascii_term_matches(normalized_query, normalized_term)
        return normalized_term in normalized_query or compact_term in compact_query

    def _ascii_term_matches(self, normalized_query: str, normalized_term: str) -> bool:
        """영문/숫자 포함 용어는 다른 단어 내부 부분문자열로 보지 않는다."""
        term_tokens = normalized_term.split()
        if not term_tokens:
            return False
        query_tokens = normalized_query.split()
        if len(term_tokens) == 1:
            return term_tokens[0] in query_tokens
        window_size = len(term_tokens)
        return any(
            query_tokens[index : index + window_size] == term_tokens
            for index in range(0, len(query_tokens) - window_size + 1)
        )

    def _has_conservative_trigger_match(self, trigger_matches: list[str]) -> bool:
        """짧은 트리거 하나만으로 직접 후보가 되는 일을 막는다."""
        normalized_matches = [
            self._normalize_direct_match_text(term).replace(" ", "")
            for term in trigger_matches
        ]
        normalized_matches = [term for term in normalized_matches if len(term) >= 2]
        return (
            any(self._is_strong_single_trigger_term(term) for term in normalized_matches)
            or len(normalized_matches) >= 2
        )

    def _is_strong_single_trigger_term(self, normalized_term: str) -> bool:
        """단독 직접 후보가 될 만큼 구체적인 트리거인지 판단한다."""
        if re.fullmatch(r"[a-z0-9]+", normalized_term):
            return len(normalized_term) >= 3
        if re.fullmatch(r"[가-힣]+", normalized_term):
            return len(normalized_term) >= 3
        return len(normalized_term) >= 4

    def build_raw_chunks(self, memory: MemoryEntry, chunk_turns: int = 6) -> List[MemoryChunk]:
        """기억 원문에서 고정 길이 turn window chunk를 생성한다."""
        messages = list(getattr(memory, "original_messages", []) or [])
        if not messages:
            return []

        window_size = max(1, int(chunk_turns or 6))
        if len(messages) <= window_size:
            return [self._create_raw_chunk(memory, messages)]

        stride = max(1, window_size // 2)
        chunks: List[MemoryChunk] = []
        start_indexes = list(range(0, len(messages) - window_size + 1, stride))
        last_start = len(messages) - window_size
        if start_indexes[-1] != last_start:
            start_indexes.append(last_start)

        for start_index in start_indexes:
            chunk_messages = messages[start_index : start_index + window_size]
            chunks.append(self._create_raw_chunk(memory, chunk_messages))
        return chunks

    def _create_raw_chunk(self, memory: MemoryEntry, messages) -> MemoryChunk:
        """메시지 리스트를 raw chunk 객체로 변환한다."""
        chunk_messages = list(messages or [])
        start_turn_index = int(getattr(chunk_messages[0], "turn_index", 0)) if chunk_messages else 0
        end_turn_index = int(getattr(chunk_messages[-1], "turn_index", start_turn_index)) if chunk_messages else start_turn_index
        lines = []
        for message in chunk_messages:
            role = str(getattr(message, "role", "unknown") or "unknown").strip() or "unknown"
            text = str(getattr(message, "text", "") or "").strip()
            lines.append(f"[{role}] {text}")
        conversation_id = (
            str(getattr(chunk_messages[0], "conversation_id", "") or "").strip()
            if chunk_messages
            else str(getattr(memory, "conversation_id", "") or "").strip()
        )
        return MemoryChunk(
            memory_id=str(getattr(memory, "id", "") or "").strip(),
            conversation_id=conversation_id,
            start_turn_index=start_turn_index,
            end_turn_index=end_turn_index,
            text="\n".join(lines),
            messages=chunk_messages,
        )

    async def find_relevant_raw_chunks(
        self,
        latest_query: str,
        candidate_memories: List[Tuple[MemoryEntry, float]],
        recent_context: str = "",
        top_k: int = 2,
        chunk_turns: int = 6,
    ) -> List[Tuple[MemoryChunk, float, dict[str, float]]]:
        """후보 memory 안에서 최신 사용자 메시지 중심 raw chunk를 선별한다."""
        normalized_query = str(latest_query or "").strip()
        normalized_recent = str(recent_context or "").strip()
        if not candidate_memories or not (normalized_query or normalized_recent):
            return []

        max_chunks = max(0, int(top_k or 0))
        if max_chunks == 0:
            return []

        all_chunks: list[tuple[MemoryChunk, float]] = []
        for memory, memory_score in candidate_memories:
            for chunk in self.build_raw_chunks(memory, chunk_turns=chunk_turns):
                all_chunks.append((chunk, float(memory_score)))

        if not all_chunks:
            return []

        query_embedding = None
        recent_embedding = None
        if self.embedding_generator and normalized_query:
            try:
                query_embedding = await self.embedding_generator.embed(normalized_query)
            except Exception as error:
                print(f"[Memory] 최신 메시지 chunk 검색 임베딩 실패: {error}")
        if self.embedding_generator and normalized_recent:
            try:
                recent_embedding = await self.embedding_generator.embed(normalized_recent)
            except Exception as error:
                print(f"[Memory] 최근 문맥 chunk 검색 임베딩 실패: {error}")

        await self._ensure_chunk_embeddings([chunk for chunk, _ in all_chunks])

        ranked: list[tuple[MemoryChunk, float, dict[str, float]]] = []
        for chunk, memory_score in all_chunks:
            primary_similarity = self._cosine_if_available(query_embedding, chunk.embedding)
            support_similarity = self._cosine_if_available(recent_embedding, chunk.embedding)
            keyword_score = self._keyword_overlap_score(normalized_query, chunk.text)
            support_keyword_score = self._keyword_overlap_score(normalized_recent, chunk.text)
            temporal_score = self._temporal_overlap_score(normalized_query, chunk.text)
            memory_bonus = self._memory_score_bonus(memory_score)
            recency_bonus = self._chunk_recency_bonus(chunk)
            user_bonus = self._chunk_user_bonus(chunk)

            final_score = (
                (primary_similarity * 0.52)
                + (support_similarity * 0.14)
                + (keyword_score * 0.14)
                + (support_keyword_score * 0.06)
                + (temporal_score * 0.05)
                + (memory_bonus * 0.05)
                + (recency_bonus * 0.02)
                + (user_bonus * 0.02)
            )
            ranked.append(
                (
                    chunk,
                    final_score,
                    {
                        "primary_similarity": primary_similarity,
                        "support_similarity": support_similarity,
                        "keyword_score": keyword_score,
                        "support_keyword_score": support_keyword_score,
                        "temporal_score": temporal_score,
                        "memory_bonus": memory_bonus,
                        "recency_bonus": recency_bonus,
                        "user_bonus": user_bonus,
                    },
                )
            )

        ranked.sort(key=lambda item: item[1], reverse=True)

        selected: list[tuple[MemoryChunk, float, dict[str, float]]] = []
        for chunk, score, meta in ranked:
            if any(self._chunks_overlap(chunk, existing_chunk) for existing_chunk, _, _ in selected):
                continue
            selected.append((chunk, score, meta))
            if len(selected) >= max_chunks:
                break

        return selected

    async def _ensure_chunk_embeddings(self, chunks: List[MemoryChunk]):
        """아직 임베딩이 없는 raw chunk만 lazy 생성해서 캐시에 저장한다."""
        if not self.embedding_generator:
            return

        uncached_chunks: list[MemoryChunk] = []
        uncached_texts: list[str] = []
        for chunk in chunks:
            cache_key = self._raw_chunk_cache_key(chunk)
            cached_embedding = self._raw_chunk_embedding_cache.get(cache_key)
            if cached_embedding is not None:
                chunk.embedding = cached_embedding
                continue
            uncached_chunks.append(chunk)
            uncached_texts.append(chunk.text)

        if not uncached_chunks:
            return

        try:
            if hasattr(self.embedding_generator, "embed_batch"):
                embeddings = await self.embedding_generator.embed_batch(uncached_texts)
            else:
                embeddings = []
                for text in uncached_texts:
                    embeddings.append(await self.embedding_generator.embed(text))
        except Exception as error:
            print(f"[Memory] raw chunk 임베딩 생성 실패: {error}")
            return

        for chunk, embedding in zip(uncached_chunks, embeddings):
            cache_key = self._raw_chunk_cache_key(chunk)
            chunk.embedding = embedding
            self._raw_chunk_embedding_cache[cache_key] = embedding

    def _raw_chunk_cache_key(self, chunk: MemoryChunk) -> tuple[str, int, int, str]:
        """raw chunk 캐시 키를 만든다."""
        return (
            str(chunk.memory_id or "").strip(),
            int(chunk.start_turn_index),
            int(chunk.end_turn_index),
            str(chunk.text or ""),
        )

    def _cosine_if_available(self, vec1: List[float] | None, vec2: List[float] | None) -> float:
        """벡터가 모두 있을 때만 코사인 유사도를 계산한다."""
        if not vec1 or not vec2 or not self.embedding_generator:
            return 0.0
        try:
            return float(self.embedding_generator.cosine_similarity(vec1, vec2))
        except Exception:
            return 0.0

    def _keyword_overlap_score(self, query: str, text: str) -> float:
        """질의와 chunk 사이의 단순 키워드 겹침 비율을 계산한다."""
        query_tokens = self._tokenize_overlap_text(query)
        text_tokens = self._tokenize_overlap_text(text)
        if not query_tokens or not text_tokens:
            return 0.0
        overlap = query_tokens.intersection(text_tokens)
        return len(overlap) / len(query_tokens)

    def _tokenize_overlap_text(self, text: str) -> set[str]:
        """겹침 계산용 간단 토큰화."""
        tokens = re.findall(r"[0-9A-Za-z가-힣]+", str(text or "").lower())
        return {token for token in tokens if len(token) >= 2}

    def _temporal_overlap_score(self, query: str, text: str) -> float:
        """날짜/시간/숫자 토큰이 겹치면 작은 보정치를 준다."""
        query_tokens = self._extract_temporal_tokens(query)
        text_tokens = self._extract_temporal_tokens(text)
        if not query_tokens or not text_tokens:
            return 0.0
        overlap = query_tokens.intersection(text_tokens)
        return len(overlap) / len(query_tokens)

    def _extract_temporal_tokens(self, text: str) -> set[str]:
        """시간성 토큰만 추출한다."""
        normalized = str(text or "").lower()
        keyword_tokens = set(
            re.findall(
                r"(오늘|내일|모레|어제|주말|월요일|화요일|수요일|목요일|금요일|토요일|일요일|오전|오후|새벽|밤)",
                normalized,
            )
        )
        numeric_tokens = set(re.findall(r"\b\d{1,4}\b", normalized))
        return keyword_tokens.union(numeric_tokens)

    def _memory_score_bonus(self, memory_score: float) -> float:
        """후보 summary 검색 점수를 작은 보정치로 정규화한다."""
        return max(0.0, min(1.0, float(memory_score) / 1.5))

    def _chunk_recency_bonus(self, chunk: MemoryChunk) -> float:
        """같은 기억 안에서는 더 뒤쪽 turn window에 약한 가산점을 준다."""
        if not chunk.messages:
            return 0.0
        window_size = max(1, len(chunk.messages))
        end_turn = int(getattr(chunk.messages[-1], "turn_index", chunk.end_turn_index))
        return end_turn / max(1, end_turn + window_size)

    def _chunk_user_bonus(self, chunk: MemoryChunk) -> float:
        """사용자 발화가 포함된 chunk에 작은 가산점을 준다."""
        if any(str(getattr(message, "role", "")).strip() == "user" for message in chunk.messages):
            return 1.0
        return 0.0

    def _chunks_overlap(self, left: MemoryChunk, right: MemoryChunk) -> bool:
        """같은 memory 안에서 turn 구간이 겹치면 중복 chunk로 본다."""
        if left.memory_id != right.memory_id:
            return False
        return not (
            left.end_turn_index < right.start_turn_index
            or right.end_turn_index < left.start_turn_index
        )

    def _infer_query_memory_type(self, query: str) -> str:
        """검색 질의에서 대략적인 기억 유형을 추정한다."""
        normalized = str(query or "").strip().lower()
        if not normalized:
            return "general"

        for memory_type, patterns in _QUERY_TYPE_PATTERNS.items():
            if any(pattern.lower() in normalized for pattern in patterns):
                return memory_type
        return "general"

    def _metadata_rank_bonus(self, memory: MemoryEntry, query_memory_type: str) -> float:
        """메타데이터 기반의 작은 보정 점수를 계산한다."""
        bonus = 0.0

        try:
            confidence = float(memory.confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        bonus += max(0.0, min(confidence, 1.0) - 0.5) * 0.2

        if memory.is_important:
            bonus += 0.04

        memory_type = str(memory.memory_type or "general").strip().lower() or "general"
        if query_memory_type != "general":
            if memory_type == query_memory_type:
                bonus += 0.06
            elif {memory_type, query_memory_type} == {"event", "promise"}:
                bonus += 0.03

        last_used_at = self._parse_iso_datetime(memory.last_used_at)
        if last_used_at is not None:
            now = datetime.now(last_used_at.tzinfo) if last_used_at.tzinfo else datetime.now()
            age_seconds = max(0.0, (now - last_used_at).total_seconds())
            if age_seconds <= 7 * 24 * 60 * 60:
                bonus += 0.02
            elif age_seconds <= 30 * 24 * 60 * 60:
                bonus += 0.01

        return bonus

    def _parse_iso_datetime(self, value: str | None) -> datetime | None:
        """ISO 날짜 문자열을 안전하게 파싱한다."""
        text = str(value or "").strip()
        if not text:
            return None

        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _mark_memories_retrieved(self, memories: List[MemoryEntry]):
        """실제로 사용된 기억의 회수 메타데이터를 갱신한다."""
        if not memories:
            return

        updated = False
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        for memory in memories:
            memory.retrieval_count = int(memory.retrieval_count or 0) + 1
            memory.last_used_at = now_iso
            updated = True

        if updated:
            self.save()
    
    def get_recent(self, count: int = 5) -> List[MemoryEntry]:
        """
        최근 기억 반환
        
        Args:
            count: 반환할 개수
            
        Returns:
            최근 기억 리스트 (시간순)
        """
        # 시간순 정렬 (최신순)
        sorted_memories = sorted(
            self.memories,
            key=lambda m: m.timestamp,
            reverse=True
        )
        
        return sorted_memories[:count]
    
    def get_important(self) -> List[MemoryEntry]:
        """
        중요 기억 반환
        
        Returns:
            중요 표시된 기억 리스트
        """
        return [m for m in self.memories if m.is_important]
    
    def set_important(self, memory_id: str, is_important: bool):
        """
        기억의 중요도 설정
        
        Args:
            memory_id: 기억 ID
            is_important: 중요 여부
        """
        for memory in self.memories:
            if memory.id == memory_id:
                memory.is_important = is_important
                self.save()
                print(f"[Memory] 중요도 변경 chars={len(memory.summary or '')} -> {is_important}")
                return
        
        print(f"[Memory] ID {memory_id} 기억을 찾을 수 없음")
    
    def delete(self, memory_id: str):
        """
        기억 삭제
        
        Args:
            memory_id: 기억 ID
        """
        original_count = len(self.memories)
        self.memories = [m for m in self.memories if m.id != memory_id]
        
        if len(self.memories) < original_count:
            self.save()
            print(f"[Memory] 기억 삭제됨: {memory_id}")
        else:
            print(f"[Memory] ID {memory_id} 기억을 찾을 수 없음")
    
    def clear(self):
        """모든 기억 삭제"""
        self.memories = []
        self.save()
        print("[Memory] 모든 기억 삭제됨")
    
    def get_stats(self) -> dict:
        """통계 반환"""
        total = len(self.memories)
        important = len(self.get_important())
        with_embedding = len([m for m in self.memories if m.embedding])
        
        return {
            'total': total,
            'important': important,
            'with_embedding': with_embedding
        }
