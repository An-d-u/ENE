import asyncio
from types import SimpleNamespace

from src.ai.embedding import (
    EmbeddingGenerator,
    GeminiEmbeddingGenerator,
    OpenAIEmbeddingGenerator,
)


def test_cosine_similarity_identical_vectors_is_one():
    vec = [1.0, 2.0, 3.0]
    sim = EmbeddingGenerator.cosine_similarity(vec, vec)
    assert sim == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero():
    vec1 = [1.0, 0.0]
    vec2 = [0.0, 1.0]
    sim = EmbeddingGenerator.cosine_similarity(vec1, vec2)
    assert sim == 0.0


def test_cosine_similarity_zero_norm_returns_zero():
    vec1 = [0.0, 0.0, 0.0]
    vec2 = [1.0, 2.0, 3.0]
    sim = EmbeddingGenerator.cosine_similarity(vec1, vec2)
    assert sim == 0.0


def test_openai_embedding_generator_posts_embeddings_payload():
    calls = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    def post(url, *, headers, json, timeout):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        calls["timeout"] = timeout
        return Response()

    generator = OpenAIEmbeddingGenerator(
        api_key="openai-key",
        model="text-embedding-3-large",
        post_func=post,
    )

    embedding = asyncio.run(generator.embed("synthetic text"))

    assert embedding == [0.1, 0.2, 0.3]
    assert calls["url"] == "https://api.openai.com/v1/embeddings"
    assert calls["headers"]["Authorization"] == "Bearer openai-key"
    assert calls["json"] == {
        "model": "text-embedding-3-large",
        "input": ["synthetic text"],
        "encoding_format": "float",
    }


def test_openai_embedding_generator_uses_compatible_base_url():
    calls = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.4]}]}

    def post(url, *, headers, json, timeout):
        calls["url"] = url
        return Response()

    generator = OpenAIEmbeddingGenerator(
        api_key="compatible-key",
        model="local-embedding",
        api_url="http://127.0.0.1:8000/v1",
        provider="openai_compatible",
        post_func=post,
    )

    assert asyncio.run(generator.embed("synthetic text")) == [0.4]
    assert calls["url"] == "http://127.0.0.1:8000/v1/embeddings"
    assert generator.provider == "openai_compatible"


def test_openai_compatible_embedding_omits_auth_header_without_key():
    calls = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.4]}]}

    def post(url, *, headers, json, timeout):
        calls["headers"] = headers
        return Response()

    generator = OpenAIEmbeddingGenerator(
        api_key="",
        model="local-embedding",
        api_url="http://127.0.0.1:8000/v1",
        provider="openai_compatible",
        post_func=post,
    )

    assert asyncio.run(generator.embed("synthetic text")) == [0.4]
    assert "Authorization" not in calls["headers"]


def test_gemini_embedding_generator_reads_sdk_values():
    calls = {}

    class FakeModels:
        def embed_content(self, *, model, contents):
            calls["model"] = model
            calls["contents"] = contents
            return SimpleNamespace(
                embeddings=[
                    SimpleNamespace(values=[0.7, 0.8]),
                    SimpleNamespace(values=[0.9, 1.0]),
                ]
            )

    fake_client = SimpleNamespace(models=FakeModels())
    generator = GeminiEmbeddingGenerator(
        api_key="gemini-key",
        model="gemini-embedding-2",
        client=fake_client,
    )

    embeddings = asyncio.run(generator.embed_batch(["first", "second"]))

    assert embeddings == [[0.7, 0.8], [0.9, 1.0]]
    assert calls == {"model": "gemini-embedding-2", "contents": ["first", "second"]}
