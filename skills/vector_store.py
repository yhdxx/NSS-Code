from __future__ import annotations

from pathlib import Path
from typing import Any

from config import CONFIG
from skills.embeddings import EmbeddingCache, EmbeddingService, embedding_text_hash
from skills.models import SearchResult, SkillRecord

DENSE_FIELD = "dense_vector"
SPARSE_FIELD = "sparse_vector"
TEXT_FIELD = "search_text"
TOOL_NAME_FIELD = "tool_name"
NAME_FIELD = "name"
DESCRIPTION_FIELD = "description"
CONTENT_FIELD = "content"
SOURCE_PATH_FIELD = "source_path"
CONTENT_HASH_FIELD = "content_hash"
UPDATED_AT_FIELD = "updated_at"


class SkillVectorStore:
    ready = False
    needs_full_sync = False

    def upsert(self, records: list[SkillRecord]) -> None:
        raise NotImplementedError

    def delete_missing(self, existing_tool_names: set[str]) -> None:
        raise NotImplementedError

    def stale_records(self, records: dict[str, SkillRecord]) -> list[SkillRecord]:
        return []

    def search(
        self,
        query: str,
        *,
        records: dict[str, SkillRecord],
        top_k: int,
        preferred_names: list[str] | None = None,
    ) -> list[SearchResult] | None:
        return None


class MilvusVectorStore(SkillVectorStore):
    """Milvus-backed hybrid retrieval for SKILL search.

    Dense semantic search uses HNSW. Keyword search uses Milvus BM25 over the
    indexed text field. Indexes are created with the collection; subsequent
    upserts let Milvus maintain HNSW/BM25 incrementally. Query-time hybrid
    search fuses both result lists with reciprocal rank fusion.
    """

    ready = False
    needs_full_sync = False

    def __init__(self, embedding_service: EmbeddingService, embedding_cache: EmbeddingCache | None = None) -> None:
        self.embedding_service = embedding_service
        self.embedding_cache = embedding_cache
        self.embedding_signature = embedding_service.signature()
        self.last_cache_hits = 0
        self.last_cache_misses = 0
        self.dim = self._detect_dim()
        self.collection_name = CONFIG.milvus.collection
        self._client: Any | None = None
        self._connect()

    def upsert(self, records: list[SkillRecord]) -> None:
        if not records:
            return None
        self._ensure_ready()
        vectors = self._vectors_for_records(records)
        rows = [
            {
                TOOL_NAME_FIELD: record.tool_name,
                NAME_FIELD: _truncate_text(record.name, 256),
                DESCRIPTION_FIELD: _truncate_text(record.description, 4096),
                CONTENT_FIELD: _truncate_text(record.content, CONFIG.milvus.text_max_bytes),
                TEXT_FIELD: _truncate_text(_search_text(record), CONFIG.milvus.text_max_bytes),
                SOURCE_PATH_FIELD: _truncate_text(str(record.source_path), 4096),
                CONTENT_HASH_FIELD: record.content_hash,
                UPDATED_AT_FIELD: float(record.updated_at),
                DENSE_FIELD: vector,
            }
            for record, vector in zip(records, vectors)
        ]
        self._client.upsert(collection_name=self.collection_name, data=rows)
        self._flush()
        self.needs_full_sync = False

    def delete_missing(self, existing_tool_names: set[str]) -> None:
        self._ensure_ready()
        if existing_tool_names:
            expr = f"{TOOL_NAME_FIELD} not in {_quoted_list(existing_tool_names)}"
        else:
            expr = f'{TOOL_NAME_FIELD} != ""'
        self._client.delete(collection_name=self.collection_name, filter=expr)
        self._flush()

    def stale_records(self, records: dict[str, SkillRecord]) -> list[SkillRecord]:
        """Return records missing from Milvus or whose stored hash is stale."""
        self._ensure_ready()
        if not records:
            return []
        try:
            rows = self._client.query(
                collection_name=self.collection_name,
                filter=f'{TOOL_NAME_FIELD} != ""',
                output_fields=[TOOL_NAME_FIELD, CONTENT_HASH_FIELD],
                limit=max(len(records), 1),
            )
        except Exception:
            return list(records.values())

        indexed_hashes = {
            str(row.get(TOOL_NAME_FIELD)): str(row.get(CONTENT_HASH_FIELD) or "")
            for row in rows
            if row.get(TOOL_NAME_FIELD)
        }
        return [
            record
            for tool_name, record in records.items()
            if indexed_hashes.get(tool_name) != record.content_hash
        ]

    def search(
        self,
        query: str,
        *,
        records: dict[str, SkillRecord],
        top_k: int,
        preferred_names: list[str] | None = None,
    ) -> list[SearchResult] | None:
        if not query.strip():
            return []
        self._ensure_ready()
        results = self._hybrid_search(query, records=records, top_k=top_k)
        if preferred_names:
            results = _boost_preferred(results, preferred_names)
        return results

    def _connect(self) -> None:
        try:
            from pymilvus import DataType, Function, FunctionType, MilvusClient
        except Exception as exc:
            raise RuntimeError(
                "pymilvus is required for SKILL retrieval. Install it with: pip install -U pymilvus"
            ) from exc

        try:
            self._client = MilvusClient(
                uri=CONFIG.milvus.uri,
                token=CONFIG.milvus.token,
            )
            if not self._client.has_collection(self.collection_name):
                self._create_collection(DataType, Function, FunctionType)
                self.needs_full_sync = True
            elif not self._schema_is_compatible():
                if not CONFIG.milvus.recreate_incompatible:
                    self._client = None
                    self.ready = False
                    return
                self._client.drop_collection(self.collection_name)
                self._create_collection(DataType, Function, FunctionType)
                self.needs_full_sync = True
            self._client.load_collection(collection_name=self.collection_name)
        except Exception as exc:
            self._client = None
            self.ready = False
            raise RuntimeError(
                "Failed to initialize local Milvus collection "
                f"{self.collection_name!r} at {CONFIG.milvus.uri}. "
                "Ensure the local Milvus service is already running and supports BM25 full-text search."
            ) from exc
        self.ready = True

    def _create_collection(self, DataType, Function, FunctionType) -> None:
        if self._client is None:
            return

        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name=TOOL_NAME_FIELD,
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=128,
        )
        schema.add_field(field_name=NAME_FIELD, datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name=DESCRIPTION_FIELD, datatype=DataType.VARCHAR, max_length=4096)
        schema.add_field(field_name=CONTENT_FIELD, datatype=DataType.VARCHAR, max_length=CONFIG.milvus.text_max_bytes)
        schema.add_field(
            field_name=TEXT_FIELD,
            datatype=DataType.VARCHAR,
            max_length=CONFIG.milvus.text_max_bytes,
            analyzer_params=CONFIG.milvus.analyzer_params,
            enable_analyzer=True,
        )
        schema.add_field(field_name=SOURCE_PATH_FIELD, datatype=DataType.VARCHAR, max_length=4096)
        schema.add_field(field_name=CONTENT_HASH_FIELD, datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name=UPDATED_AT_FIELD, datatype=DataType.DOUBLE)
        schema.add_field(field_name=DENSE_FIELD, datatype=DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field(field_name=SPARSE_FIELD, datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="skill_bm25",
                input_field_names=[TEXT_FIELD],
                output_field_names=[SPARSE_FIELD],
                function_type=FunctionType.BM25,
            )
        )

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name=DENSE_FIELD,
            index_name="skill_dense_hnsw_index",
            index_type=CONFIG.milvus.dense_index_type,
            metric_type=CONFIG.milvus.dense_metric_type,
            params={
                "M": CONFIG.milvus.hnsw_m,
                "efConstruction": CONFIG.milvus.hnsw_ef_construction,
            },
        )
        index_params.add_index(
            field_name=SPARSE_FIELD,
            index_name="skill_sparse_bm25_index",
            index_type=CONFIG.milvus.sparse_index_type,
            metric_type=CONFIG.milvus.sparse_metric_type,
            params={"inverted_index_algo": CONFIG.milvus.sparse_inverted_index_algo},
        )
        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def _schema_is_compatible(self) -> bool:
        if self._client is None:
            return False
        try:
            description = self._client.describe_collection(collection_name=self.collection_name)
        except Exception:
            return False
        fields = description.get("fields", [])
        field_names = {field.get("name") for field in fields}
        required = {
            TOOL_NAME_FIELD,
            NAME_FIELD,
            DESCRIPTION_FIELD,
            CONTENT_FIELD,
            TEXT_FIELD,
            SOURCE_PATH_FIELD,
            CONTENT_HASH_FIELD,
            UPDATED_AT_FIELD,
            DENSE_FIELD,
            SPARSE_FIELD,
        }
        if not required <= field_names:
            return False
        dense_field = next((field for field in fields if field.get("name") == DENSE_FIELD), {})
        dense_params = dense_field.get("params") or {}
        if int(dense_params.get("dim", self.dim)) != self.dim:
            return False
        return True

    def _hybrid_search(
        self,
        query: str,
        *,
        records: dict[str, SkillRecord],
        top_k: int,
    ) -> list[SearchResult]:
        self._ensure_ready()
        from pymilvus import AnnSearchRequest

        query_vector = self.embedding_service.embed_query(query)
        limit = max(top_k, 1)
        dense_request = AnnSearchRequest(
            [query_vector],
            DENSE_FIELD,
            {
                "metric_type": CONFIG.milvus.dense_metric_type,
                "params": {"ef": CONFIG.milvus.hnsw_ef},
            },
            limit=limit,
        )
        sparse_request = AnnSearchRequest(
            [query],
            SPARSE_FIELD,
            {"metric_type": CONFIG.milvus.sparse_metric_type},
            limit=limit,
        )
        raw_results = self._client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_request, sparse_request],
            ranker=_rrf_ranker(),
            limit=limit,
            output_fields=[
                TOOL_NAME_FIELD,
                NAME_FIELD,
                DESCRIPTION_FIELD,
                CONTENT_FIELD,
                SOURCE_PATH_FIELD,
                CONTENT_HASH_FIELD,
                UPDATED_AT_FIELD,
            ],
        )
        hits = raw_results[0] if raw_results else []
        results: list[SearchResult] = []
        for hit in hits:
            entity = _hit_entity(hit)
            tool_name = str(entity.get(TOOL_NAME_FIELD) or _hit_id(hit) or "")
            record = records.get(tool_name)
            if record is None:
                record = _record_from_entity(entity, tool_name)
            if record is None:
                continue
            score = float(_hit_score(hit))
            results.append(
                SearchResult(
                    record=record,
                    score=score,
                    keyword_score=0.0,
                    semantic_score=0.0,
                    metadata={"retriever": "milvus_hnsw_bm25_rrf"},
                )
            )
        return results

    def _detect_dim(self) -> int:
        if self.embedding_cache is not None:
            text = "skill vector dimension probe"
            text_hash = embedding_text_hash(text)
            cached = self.embedding_cache.get(
                tool_name="__dimension_probe__",
                text_hash=text_hash,
                embedding_signature=self.embedding_signature,
            )
            if cached:
                return len(cached)
            probe = self.embedding_service.embed_documents([text])
            if probe and probe[0]:
                self.embedding_cache.put(
                    tool_name="__dimension_probe__",
                    text_hash=text_hash,
                    embedding_signature=self.embedding_signature,
                    vector=probe[0],
                    updated_at=0.0,
                )
                return len(probe[0])
        else:
            probe = self.embedding_service.embed_documents(["skill vector dimension probe"])
            if probe and probe[0]:
                return len(probe[0])
        return self.embedding_service.dim

    def _vectors_for_records(self, records: list[SkillRecord]) -> list[list[float]]:
        if self.embedding_cache is None:
            self.last_cache_hits = 0
            self.last_cache_misses = len(records)
            return self.embedding_service.embed_documents([_semantic_document(record) for record in records])

        self.last_cache_hits = 0
        self.last_cache_misses = 0
        vectors_by_tool_name: dict[str, list[float]] = {}
        missed_records: list[SkillRecord] = []
        missed_texts: list[str] = []
        missed_hashes: list[str] = []

        for record in records:
            text = _semantic_document(record)
            text_hash = embedding_text_hash(text)
            cached = self.embedding_cache.get(
                tool_name=record.tool_name,
                text_hash=text_hash,
                embedding_signature=self.embedding_signature,
            )
            if cached is not None:
                self.last_cache_hits += 1
                vectors_by_tool_name[record.tool_name] = cached
                continue
            self.last_cache_misses += 1
            missed_records.append(record)
            missed_texts.append(text)
            missed_hashes.append(text_hash)

        if missed_records:
            missed_vectors = self.embedding_service.embed_documents(missed_texts)
            for record, text_hash, vector in zip(missed_records, missed_hashes, missed_vectors):
                vectors_by_tool_name[record.tool_name] = vector
                self.embedding_cache.put(
                    tool_name=record.tool_name,
                    text_hash=text_hash,
                    embedding_signature=self.embedding_signature,
                    vector=vector,
                    updated_at=record.updated_at,
                )

        return [vectors_by_tool_name[record.tool_name] for record in records]

    def _ensure_ready(self) -> None:
        if self.ready and self._client is not None:
            return
        raise RuntimeError(
            "Local Milvus is not ready. Ensure the service is running and keep MYCODINGAGENT_MILVUS_ENABLED=true."
        )

    def _flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush(collection_name=self.collection_name)
        except TypeError:
            self._client.flush(self.collection_name)
        except AttributeError:
            return


def create_vector_store(
    embedding_service: EmbeddingService,
    embedding_cache: EmbeddingCache | None = None,
) -> SkillVectorStore:
    if not CONFIG.milvus.enabled:
        raise RuntimeError("SKILL retrieval requires local Milvus. Set MYCODINGAGENT_MILVUS_ENABLED=true.")
    return MilvusVectorStore(embedding_service, embedding_cache)


def _record_from_entity(entity: dict[str, Any], tool_name: str) -> SkillRecord | None:
    if not tool_name:
        return None
    return SkillRecord(
        name=str(entity.get(NAME_FIELD) or tool_name),
        tool_name=tool_name,
        description=str(entity.get(DESCRIPTION_FIELD) or ""),
        content=str(entity.get(CONTENT_FIELD) or ""),
        source_path=Path(str(entity.get(SOURCE_PATH_FIELD) or "")),
        content_hash=str(entity.get(CONTENT_HASH_FIELD) or ""),
        updated_at=float(entity.get(UPDATED_AT_FIELD) or 0.0),
    )


def _hit_entity(hit: Any) -> dict[str, Any]:
    if isinstance(hit, dict):
        entity = hit.get("entity") or hit.get("fields") or hit
        return entity if isinstance(entity, dict) else {}
    entity = getattr(hit, "entity", None) or getattr(hit, "fields", None)
    if isinstance(entity, dict):
        return entity
    if entity is not None:
        values: dict[str, Any] = {}
        for field in [
            TOOL_NAME_FIELD,
            NAME_FIELD,
            DESCRIPTION_FIELD,
            CONTENT_FIELD,
            SOURCE_PATH_FIELD,
            CONTENT_HASH_FIELD,
            UPDATED_AT_FIELD,
        ]:
            try:
                value = entity.get(field)
            except Exception:
                continue
            if value is not None:
                values[field] = value
        if values:
            return values
    if hasattr(entity, "to_dict"):
        value = entity.to_dict()
        return value if isinstance(value, dict) else {}
    return {}


def _hit_id(hit: Any) -> Any:
    if isinstance(hit, dict):
        return hit.get("id")
    return getattr(hit, "id", None)


def _hit_score(hit: Any) -> float:
    if isinstance(hit, dict):
        return hit.get("distance") or hit.get("score") or 0.0
    return getattr(hit, "distance", None) or getattr(hit, "score", None) or 0.0


def _rrf_ranker() -> Any:
    try:
        from pymilvus import RRFRanker

        return RRFRanker(k=CONFIG.milvus.rrf_k)
    except TypeError:
        return RRFRanker(CONFIG.milvus.rrf_k)


def _boost_preferred(results: list[SearchResult], preferred_names: list[str]) -> list[SearchResult]:
    preferred = {name.lower() for name in preferred_names}
    for result in results:
        tool_name = result.record.tool_name.lower()
        name = result.record.name.lower()
        if tool_name in preferred or name in preferred or any(item in tool_name or item in name for item in preferred):
            result.score += 1.0
            result.metadata["preferred_name_boost"] = True
    results.sort(key=lambda item: item.score, reverse=True)
    return results


def _quoted_list(values: set[str]) -> str:
    return "[" + ",".join(f'"{value}"' for value in sorted(values)) + "]"


def _semantic_document(record: SkillRecord) -> str:
    return "\n".join([record.tool_name, record.name, record.description])


def _search_text(record: SkillRecord) -> str:
    return "\n".join([record.tool_name, record.name, record.description, record.content])


def _truncate_text(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
