import asyncio
from functools import partial
from typing import List

import numpy as np
import requests
import voyageai


def _normalize_openai_embeddings_endpoint(api_url: str, default_base: str) -> str:
    base = str(api_url or default_base).strip() or default_base
    base = base.rstrip("/")
    if base.endswith("/embeddings"):
        return base
    return f"{base}/embeddings"


def _extract_embedding_values(value) -> list[float]:
    if isinstance(value, dict):
        if "embedding" in value:
            return [float(item) for item in value["embedding"]]
        if "values" in value:
            return [float(item) for item in value["values"]]
    if hasattr(value, "embedding"):
        return [float(item) for item in getattr(value, "embedding")]
    if hasattr(value, "values"):
        return [float(item) for item in getattr(value, "values")]
    return [float(item) for item in value]


class EmbeddingGenerator:
    """Voyage AI를 사용한 임베딩 생성"""
    
    def __init__(self, api_key: str, model: str = "voyage-3"):
        """
        Args:
            api_key: Voyage AI API 키
            model: 사용할 모델 (기본값: voyage-3)
        """
        self.client = voyageai.Client(api_key=api_key)
        self.provider = "voyage"
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


class OpenAIEmbeddingGenerator:
    """OpenAI Embeddings API 또는 호환 API를 사용하는 임베딩 생성기."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        api_url: str = "",
        provider: str = "openai",
        post_func=None,
    ):
        self.api_key = api_key
        self.provider = str(provider or "openai").strip().lower()
        self.model = str(model or "text-embedding-3-small").strip() or "text-embedding-3-small"
        default_base = "https://api.openai.com/v1"
        self.endpoint = _normalize_openai_embeddings_endpoint(api_url, default_base)
        self._post = post_func or requests.post
        print(f"[Embedding] {self.provider} 초기화: {self.model}")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if str(self.api_key or "").strip():
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        response = self._post(
            self.endpoint,
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return [_extract_embedding_values(item) for item in data.get("data", [])]

    async def embed(self, text: str) -> List[float]:
        embeddings = await self.embed_batch([text])
        if not embeddings:
            raise RuntimeError("OpenAI embedding response did not include vectors")
        return embeddings[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        request_func = partial(self._request_batch, list(texts))
        return await loop.run_in_executor(None, request_func)

    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        return EmbeddingGenerator.cosine_similarity(vec1, vec2)


class GeminiEmbeddingGenerator:
    """Google Gemini Embeddings API를 사용하는 임베딩 생성기."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-2",
        client=None,
    ):
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self.client = client
        self.provider = "gemini"
        self.model = str(model or "gemini-embedding-2").strip() or "gemini-embedding-2"
        print(f"[Embedding] Gemini 초기화: {self.model}")

    def _request_batch(self, texts: list[str]) -> list[list[float]]:
        response = self.client.models.embed_content(
            model=self.model,
            contents=texts,
        )
        embeddings = getattr(response, "embeddings", None)
        if embeddings is None and isinstance(response, dict):
            embeddings = response.get("embeddings")
        if embeddings is None:
            embedding = getattr(response, "embedding", None)
            if embedding is None and isinstance(response, dict):
                embedding = response.get("embedding")
            embeddings = [embedding] if embedding is not None else []
        return [_extract_embedding_values(item) for item in embeddings]

    async def embed(self, text: str) -> List[float]:
        embeddings = await self.embed_batch([text])
        if not embeddings:
            raise RuntimeError("Gemini embedding response did not include vectors")
        return embeddings[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        request_func = partial(self._request_batch, list(texts))
        return await loop.run_in_executor(None, request_func)

    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        return EmbeddingGenerator.cosine_similarity(vec1, vec2)


def create_embedding_generator(
    *,
    provider: str,
    api_key: str,
    model: str,
    api_url: str = "",
):
    normalized = str(provider or "voyage").strip().lower()
    if normalized == "voyage":
        return EmbeddingGenerator(api_key=api_key, model=model or "voyage-3")
    if normalized == "openai":
        return OpenAIEmbeddingGenerator(
            api_key=api_key,
            model=model or "text-embedding-3-small",
            api_url=api_url or "https://api.openai.com/v1",
            provider="openai",
        )
    if normalized == "openai_compatible":
        return OpenAIEmbeddingGenerator(
            api_key=api_key,
            model=model or "text-embedding-3-small",
            api_url=api_url or "http://127.0.0.1:8000/v1",
            provider="openai_compatible",
        )
    if normalized == "gemini":
        return GeminiEmbeddingGenerator(
            api_key=api_key,
            model=model or "gemini-embedding-2",
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")
