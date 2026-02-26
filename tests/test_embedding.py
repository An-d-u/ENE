from src.ai.embedding import EmbeddingGenerator


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
