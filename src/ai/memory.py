"""
장기기억 관리 시스템
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import re

from .memory_types import CURRENT_MEMORY_SCHEMA_VERSION, MemoryChunk, MemoryEntry, create_memory_entry
from .embedding import EmbeddingGenerator
from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


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
)

_QUERY_TYPE_PATTERNS = {
    "promise": ("기억해줘", "리마인드", "알려줘", "까먹지", "약속"),
    "preference": ("좋아", "싫어", "선호", "취향", "편해", "익숙"),
    "event": ("일정", "예약", "회의", "내일", "오늘", "시간", "날짜"),
    "task": ("해야", "할 일", "정리", "작업", "TODO", "todo"),
    "relationship": ("호칭", "관계", "애칭", "성격"),
}


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
    
    def load(self):
        """JSON 파일에서 기억 로드"""
        try:
            data = load_json_data(self.memory_file, encoding="utf-8")
            raw_entries = data.get('memories', [])
            if not isinstance(raw_entries, list):
                raw_entries = []

            self.memories = []
            needs_persist = False
            for raw_entry in raw_entries:
                entry = MemoryEntry.from_dict(raw_entry if isinstance(raw_entry, dict) else {})
                self.memories.append(entry)
                if self._entry_needs_persisted_migration(raw_entry):
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

    def _entry_needs_persisted_migration(self, raw_entry) -> bool:
        """레거시 항목인지 확인해 최신 스키마로 재저장이 필요한지 판단한다."""
        if not isinstance(raw_entry, dict):
            return True

        try:
            schema_version = int(raw_entry.get("schema_version", 0))
        except (TypeError, ValueError):
            schema_version = 0

        if schema_version < CURRENT_MEMORY_SCHEMA_VERSION:
            return True

        return any(field_name not in raw_entry for field_name in _MIGRATED_MEMORY_REQUIRED_FIELDS)
    
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
            
        Returns:
            생성된 MemoryEntry
        """
        # 임베딩 생성
        embedding = None
        if self.embedding_generator:
            try:
                embedding = await self.embedding_generator.embed(summary)
                print(f"[Memory] 임베딩 생성 완료 (차원: {len(embedding)})")
            except Exception as e:
                print(f"[Memory] 임베딩 생성 실패: {e}")
        
        # 기억 항목 생성
        memory = create_memory_entry(
            summary=summary,
            original_messages=original_messages,
            is_important=is_important,
            embedding=embedding,
            tags=tags,
            source=source,
            memory_type=memory_type,
            importance_reason=importance_reason,
            confidence=confidence,
            entity_names=entity_names,
        )
        
        self.memories.append(memory)
        self.save()
        
        print(f"[Memory] 새 기억 추가: {summary[:50]}...")
        return memory
    
    async def find_similar(
        self,
        query: str,
        top_k: int = 3,
        min_similarity: float = 0.5
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
        if not self.embedding_generator:
            print("[Memory] 임베딩 생성기가 없어 검색 불가")
            return []
        
        # 임베딩이 있는 기억만 필터링
        memories_with_embedding = [
            m for m in self.memories if m.embedding is not None
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
            print(f"[Memory] 검색 쿼리: '{query}' (최대 유사도: {max_similarity:.4f})")
            
            # 최종 점수 높은 순으로 정렬하고, 동점이면 기본 유사도를 우선한다.
            similarities.sort(key=lambda item: (item[1], item[2]), reverse=True)
            
            # 상위 k개 반환
            ranked = similarities[:top_k]
            result = [(memory, final_score) for memory, final_score, _ in ranked]
            self._mark_memories_retrieved([memory for memory, _ in result])
            
            if result:
                print(f"[Memory] 유사 기억 {len(result)}개 찾음 (임계값: {min_similarity})")
                for memory, sim in result:
                    print(f"  - [{sim:.3f}] {memory.summary[:50]}...")
            else:
                print(f"[Memory] 임계값({min_similarity}) 이상의 유사 기억 없음 (최대: {max_similarity:.3f})")
            
            return result
            
        except Exception as e:
            print(f"[Memory] 검색 실패: {e}")
            return []

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
                print(f"[Memory] 중요도 변경: {memory.summary[:50]}... → {is_important}")
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
