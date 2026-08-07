from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from mycodingagent.configuration import CONFIG
from mycodingagent.sqlite_utils import SQLITE_CONNECTION_FACTORY

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


class EmbeddingService(Protocol):
    @property
    def dim(self) -> int:
        ...

    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def signature(self) -> str:
        ...


class HashEmbeddingService:
    """Deterministic fallback used when local BGE dependencies are unavailable."""

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or CONFIG.embedding.hash_dimension

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [_hash_vector(text, self._dim) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_many(texts)

    def signature(self) -> str:
        return f"hash:{self._dim}"


class LocalEmbeddingService:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int | None = None,
        fallback_to_hash: bool | None = None,
    ) -> None:
        self.model_name = model_name or CONFIG.embedding.model
        self.device = device if device is not None else CONFIG.embedding.device
        self.batch_size = batch_size or CONFIG.embedding.batch_size
        self.query_instruction = CONFIG.embedding.query_instruction
        self.fallback_to_hash = CONFIG.embedding.fallback_to_hash if fallback_to_hash is None else fallback_to_hash
        self._fallback = HashEmbeddingService()
        self._model = None
        self._dim = CONFIG.embedding.dimension
        self._load_error: Exception | None = None
        self._load_lock = threading.Lock()

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        if model is None:
            return self._fallback.embed_many(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._encode_with_model(model, texts[start:start + self.batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        model = self._load_model()
        if model is None:
            return self._fallback.embed_query(text)
        query_text = f"{self.query_instruction}{text}" if self.query_instruction else text
        return self._encode_with_model(model, [query_text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_many(texts)

    def signature(self) -> str:
        return "|".join([
            "embedding_local",
            self.model_name,
            self.device or "",
            str(self.query_instruction or ""),
        ])

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self._load_error is not None and self.fallback_to_hash:
            return None

        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._load_error is not None and self.fallback_to_hash:
                return None
            try:
                download_timeout = str(max(1, int(CONFIG.embedding.download_timeout)))
                os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", download_timeout)
                os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", str(min(int(CONFIG.embedding.download_timeout), 120)))
                from sentence_transformers import SentenceTransformer

                kwargs = {"device": self.device} if self.device else {}
                self._model = SentenceTransformer(self.model_name, **kwargs)
                detected_dim = self._model.get_sentence_embedding_dimension()
                if detected_dim:
                    self._dim = int(detected_dim)
            except Exception as exc:
                self._load_error = exc
                if self.fallback_to_hash:
                    self._dim = self._fallback.dim
                    return None
                raise RuntimeError(f"Failed to load local embedding model {self.model_name!r}: {exc}") from exc
            return self._model

    def _encode_with_model(self, model, texts: list[str]) -> list[list[float]]:
        embeddings = model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=False,
            show_progress_bar=False,
        )
        return [_to_float_list(vector) for vector in embeddings]


class HttpEmbeddingService:
    def __init__(
        self,
        *,
        endpoint: str | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        dim: int | None = None,
    ) -> None:
        self.endpoint = endpoint or CONFIG.embedding.endpoint
        self.model_name = model_name or CONFIG.embedding.model
        self.api_format = CONFIG.embedding.api_format.strip().lower()
        self.api_key = api_key if api_key is not None else CONFIG.embedding.api_key
        self.timeout = timeout if timeout is not None else CONFIG.embedding.timeout
        self.query_instruction = CONFIG.embedding.query_instruction
        self.request_extra = dict(CONFIG.embedding.request_extra)
        self.extra_headers = {str(key): str(value) for key, value in CONFIG.embedding.headers.items()}
        self._dim = dim or CONFIG.embedding.dimension

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batch_size = max(1, CONFIG.embedding.batch_size)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(self._request_embeddings(texts[start:start + batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        query_text = f"{self.query_instruction}{text}" if self.query_instruction else text
        return self._request_embeddings([query_text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_many(texts)

    def signature(self) -> str:
        return "|".join([
            "embedding_http",
            self.api_format,
            self.endpoint,
            self.model_name,
            str(self.query_instruction or ""),
            str(self._dim),
            json.dumps(self.request_extra, ensure_ascii=False, sort_keys=True),
        ])

    def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.api_format == "ollama":
            return self._request_json(self._ollama_payload(texts), texts)
        if self.api_format == "openai":
            return self._request_json(self._openai_payload(texts), texts)
        if self.api_format == "dashscope":
            return self._request_json(self._dashscope_payload(texts), texts)
        raise RuntimeError(
            "Unsupported embedding HTTP API format: "
            f"{self.api_format}. Supported formats: ollama, openai, dashscope."
        )

    def _request_json(self, payload: dict, texts: list[str]) -> list[list[float]]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to request embedding service at {self.endpoint}: {exc}") from exc
        except ConnectionResetError as exc:
            raise RuntimeError(
                "Embedding service reset the connection. Check endpoint, protocol, and API format "
                f"(current format: {self.api_format}, endpoint: {self.endpoint})."
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(f"Timed out requesting embedding service at {self.endpoint}") from exc

        try:
            body = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Embedding service returned non-JSON response: {response_body[:500]}") from exc

        embeddings = _extract_embeddings(body)
        if len(embeddings) != len(texts):
            raise RuntimeError(
                "Embedding service returned an unexpected number of embeddings: "
                f"expected {len(texts)}, got {len(embeddings)}"
            )
        if embeddings and embeddings[0]:
            self._dim = len(embeddings[0])
        return embeddings

    def _ollama_payload(self, texts: list[str]) -> dict:
        payload = {
            "model": self.model_name,
            "input": texts[0] if len(texts) == 1 else texts,
        }
        payload.update(self.request_extra)
        return payload

    def _dashscope_payload(self, texts: list[str]) -> dict:
        payload = {
            "model": self.model_name,
            "input": {"texts": texts},
        }
        payload.update(self.request_extra)
        return payload

    def _openai_payload(self, texts: list[str]) -> dict:
        payload = {
            "model": self.model_name,
            "input": texts,
        }
        payload.update(self.request_extra)
        return payload

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        return headers


def create_embedding_service() -> EmbeddingService:
    provider = CONFIG.embedding.provider.strip().lower()
    if provider == "http":
        return HttpEmbeddingService()
    if provider == "local":
        return LocalEmbeddingService()
    if provider == "hash":
        return HashEmbeddingService()
    raise ValueError(
        "Unsupported embedding provider: "
        f"{CONFIG.embedding.provider}. Supported providers: http, local, hash."
    )


class EmbeddingCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, factory=SQLITE_CONNECTION_FACTORY)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_embeddings (
                    tool_name TEXT PRIMARY KEY,
                    text_hash TEXT NOT NULL,
                    embedding_signature TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def get(self, *, tool_name: str, text_hash: str, embedding_signature: str) -> list[float] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT vector_json FROM skill_embeddings
                WHERE tool_name = ? AND text_hash = ? AND embedding_signature = ?
                """,
                (tool_name, text_hash, embedding_signature),
            ).fetchone()
        if row is None:
            return None
        try:
            vector = json.loads(row[0])
        except json.JSONDecodeError:
            return None
        return _to_float_list(vector)

    def put(
        self,
        *,
        tool_name: str,
        text_hash: str,
        embedding_signature: str,
        vector: list[float],
        updated_at: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_embeddings (tool_name, text_hash, embedding_signature, vector_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET
                    text_hash=excluded.text_hash,
                    embedding_signature=excluded.embedding_signature,
                    vector_json=excluded.vector_json,
                    updated_at=excluded.updated_at
                """,
                (tool_name, text_hash, embedding_signature, json.dumps(vector), updated_at),
            )

    def delete_missing(self, existing_tool_names: set[str]) -> None:
        with self._connect() as conn:
            if not existing_tool_names:
                conn.execute("DELETE FROM skill_embeddings")
                return
            placeholders = ",".join("?" for _ in existing_tool_names)
            conn.execute(
                f"DELETE FROM skill_embeddings WHERE tool_name NOT IN ({placeholders})",
                tuple(existing_tool_names),
            )

    def delete(self, tool_names: set[str]) -> None:
        if not tool_names:
            return
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in tool_names)
            conn.execute(
                f"DELETE FROM skill_embeddings WHERE tool_name IN ({placeholders})",
                tuple(tool_names),
            )


def embedding_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_embeddings(body) -> list[list[float]]:
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return [
            _to_float_list(item.get("embedding"))
            for item in sorted(body["data"], key=lambda item: item.get("index", 0))
            if isinstance(item, dict) and item.get("embedding") is not None
        ]
    if isinstance(body, dict) and isinstance(body.get("output"), dict):
        output_embeddings = body["output"].get("embeddings")
        if isinstance(output_embeddings, list):
            return [
                _to_float_list(item.get("embedding") if isinstance(item, dict) else item)
                for item in sorted(
                    output_embeddings,
                    key=lambda item: item.get("text_index", item.get("index", 0)) if isinstance(item, dict) else 0,
                )
                if (isinstance(item, dict) and item.get("embedding") is not None) or not isinstance(item, dict)
            ]
    if isinstance(body, dict) and isinstance(body.get("embeddings"), list):
        return [_to_float_list(vector) for vector in body["embeddings"]]
    if isinstance(body, dict) and isinstance(body.get("embedding"), list):
        return [_to_float_list(body["embedding"])]
    if isinstance(body, list):
        return [_to_float_list(vector) for vector in body]
    raise RuntimeError(f"Embedding service returned unsupported response shape: {str(body)[:500]}")


def _hash_vector(text: str, dim: int) -> list[float]:
    vector = [0.0] * dim
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize(vector)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _to_float_list(vector) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]
