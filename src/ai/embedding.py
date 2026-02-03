"""
Voyage AI 임베딩 생성기
"""
import voyageai
import numpy as np
from typing import List
import asyncio
from functools import partial


class EmbeddingGenerator:
    """Voyage AI를 사용한 임베딩 생성"""
    
    def __init__(self, api_key: str, model: str = "voyage-3"):
        """
        Args:
            api_key: Voyage AI API 키
            model: 사용할 모델 (기본값: voyage-3)
        """
        self.client = voyageai.Client(api_key=api_key)
        self.model = model
        print(f"[Embedding] Voyage AI 초기화: {model}")
    
    async def embed(self, text: str) -> List[float]:
        """
        단일 텍스트를 벡터로 변환
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            임베딩 벡터
        """
        # Voyage AI는 동기 API이므로 비동기로 래핑
        loop = asyncio.get_event_loop()
        embed_func = partial(
            self.client.embed,
            texts=[text],
            model=self.model
        )
        
        result = await loop.run_in_executor(None, embed_func)
        return result.embeddings[0]
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        여러 텍스트를 한 번에 임베딩 (효율적)
        
        Args:
            texts: 임베딩할 텍스트 리스트
            
        Returns:
            임베딩 벡터 리스트
        """
        if not texts:
            return []
        
        loop = asyncio.get_event_loop()
        embed_func = partial(
            self.client.embed,
            texts=texts,
            model=self.model
        )
        
        result = await loop.run_in_executor(None, embed_func)
        return result.embeddings
    
    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """
        코사인 유사도 계산
        
        Args:
            vec1: 첫 번째 벡터
            vec2: 두 번째 벡터
            
        Returns:
            코사인 유사도 (0~1)
        """
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)
        
        dot_product = np.dot(vec1_np, vec2_np)
        norm1 = np.linalg.norm(vec1_np)
        norm2 = np.linalg.norm(vec2_np)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot_product / (norm1 * norm2))
