"""
장기기억 관리 시스템
"""
import json
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime

from .memory_types import MemoryEntry, create_memory_entry
from .embedding import EmbeddingGenerator
from ..core.app_paths import resolve_user_storage_path


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
        
        # 파일에서 기억 로드
        self.load()
        
        print(f"[Memory] 기억 파일: {self.memory_file}")
        print(f"[Memory] 로드된 기억 수: {len(self.memories)}")
    
    def load(self):
        """JSON 파일에서 기억 로드"""
        if not self.memory_file.exists():
            print("[Memory] 기억 파일 없음. 새로 생성합니다.")
            self.memories = []
            return
        
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.memories = [
                MemoryEntry.from_dict(entry)
                for entry in data.get('memories', [])
            ]
            
            print(f"[Memory] {len(self.memories)}개 기억 로드 완료")
            
        except Exception as e:
            print(f"[Memory] 로드 실패: {e}")
            self.memories = []
    
    def save(self):
        """JSON 파일에 기억 저장"""
        try:
            # 디렉토리 생성
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'memories': [memory.to_dict() for memory in self.memories],
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[Memory] {len(self.memories)}개 기억 저장 완료")
            
        except Exception as e:
            print(f"[Memory] 저장 실패: {e}")
    
    async def add_summary(
        self,
        summary: str,
        original_messages: List[str],
        is_important: bool = False,
        tags: Optional[List[str]] = None
    ) -> MemoryEntry:
        """
        새 요약 추가
        
        Args:
            summary: 요약 텍스트
            original_messages: 원본 메시지 리스트
            is_important: 중요 여부
            tags: 태그 리스트
            
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
            tags=tags
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
                    similarities.append((memory, similarity))
            
            # 디버깅: 최대 유사도 출력
            print(f"[Memory] 검색 쿼리: '{query}' (최대 유사도: {max_similarity:.4f})")
            
            # 유사도 높은 순으로 정렬
            similarities.sort(key=lambda x: x[1], reverse=True)
            
            # 상위 k개 반환
            result = similarities[:top_k]
            
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
