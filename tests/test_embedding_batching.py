from __future__ import annotations

from dataclasses import replace

from mycodingagent.configuration.settings import CONFIG
from mycodingagent.skill_runtime import embeddings


def test_http_embedding_requests_are_split_into_configured_batches(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "CONFIG",
        replace(CONFIG, embedding=replace(CONFIG.embedding, batch_size=2)),
    )
    service = embeddings.HttpEmbeddingService(endpoint="http://embedding.test", timeout=300)
    calls: list[list[str]] = []

    def fake_request(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[float(index)] for index, _ in enumerate(texts)]

    service._request_embeddings = fake_request  # type: ignore[method-assign]

    vectors = service.embed_many(["一", "二", "三", "四", "五"])

    assert [len(batch) for batch in calls] == [2, 2, 1]
    assert len(vectors) == 5


def test_local_embedding_requests_are_split_into_configured_batches(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "CONFIG",
        replace(CONFIG, embedding=replace(CONFIG.embedding, batch_size=2)),
    )
    service = embeddings.LocalEmbeddingService(model_name="test-model", batch_size=2)
    service._model = object()
    calls: list[list[str]] = []

    def fake_encode(_model, texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[float(index)] for index, _ in enumerate(texts)]

    service._encode_with_model = fake_encode  # type: ignore[method-assign]

    vectors = service.embed_many(["一", "二", "三", "四", "五"])

    assert [len(batch) for batch in calls] == [2, 2, 1]
    assert len(vectors) == 5
