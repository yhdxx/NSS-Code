from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import mycodingagent.skill_runtime.vector_store as vector_store
from mycodingagent.configuration.settings import EmbeddingConfig
from mycodingagent.skill_runtime.embeddings import _extract_embeddings
from mycodingagent.skill_runtime.models import SkillRecord
from mycodingagent.skill_runtime.vector_store import (
    CONTENT_HASH_FIELD,
    EMBEDDING_SIGNATURE_FIELD,
    TOOL_NAME_FIELD,
    MilvusVectorStore,
)


ROOT = Path(__file__).resolve().parents[1]


def _config_probe(config_path: Path, *, extra_env: dict[str, str] | None = None) -> dict:
    home = config_path.parent / "home"
    user_config = home / ".mycodingagent" / "config.json"
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(ROOT),
    }
    env.pop("MYCODINGAGENT_CONFIG", None)
    env.pop("MYCODINGAGENT_MILVUS_PORT", None)
    env.pop("MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_HNSW_M", None)
    env.pop("MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION", None)
    env.pop("MYCODINGAGENT_MILVUS_HNSW_EF", None)
    env.pop("MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_SPARSE_ALGO", None)
    env.pop("MYCODINGAGENT_EMBEDDING_MODEL", None)
    env.pop("MYCODINGAGENT_SKILL_SESSION_ACTIVATION_REWARD", None)
    env.pop("MYCODINGAGENT_USER_SKILL_CACHE_MAX_ENTRIES", None)
    env.pop("MYCODINGAGENT_LOAD_WORKSPACE_CONFIG", None)
    env.pop("MYCODINGAGENT_MCP_PROJECT_CONFIG", None)
    env.pop("MYCODINGAGENT_MCP_USER_CONFIG", None)
    env.pop("MYCODINGAGENT_APPROVAL_MODE", None)
    env.pop("MYCODINGAGENT_MAX_TOOL_ROUNDS", None)
    env.pop("MYCODINGAGENT_MODEL_AUDIO_PROVIDER", None)
    env.pop("MYCODINGAGENT_MODEL_AUDIO_MODEL", None)
    env.pop("MYCODINGAGENT_MODEL_VISION_PROVIDER", None)
    env.pop("MYCODINGAGENT_MODEL_VISION_MODEL", None)
    env.pop("MYCODINGAGENT_SEARCH_ENABLED", None)
    env.pop("MYCODINGAGENT_SEARCH_ENDPOINT", None)
    env.pop("MYCODINGAGENT_SEARCH_MAX_RESULTS", None)
    env.pop("MYCODINGAGENT_MEMORY_DB_PATH", None)
    env.pop("MYCODINGAGENT_STATE_DIR", None)
    env.pop("XDG_STATE_HOME", None)
    if extra_env:
        env.update(extra_env)
    return _run_config_probe(cwd=ROOT, env=env)


def _workspace_config_probe(workspace: Path, home: Path, *, extra_env: dict[str, str] | None = None) -> dict:
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(ROOT),
    }
    env.pop("MYCODINGAGENT_CONFIG", None)
    env.pop("MYCODINGAGENT_MILVUS_PORT", None)
    env.pop("MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_HNSW_M", None)
    env.pop("MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION", None)
    env.pop("MYCODINGAGENT_MILVUS_HNSW_EF", None)
    env.pop("MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE", None)
    env.pop("MYCODINGAGENT_MILVUS_SPARSE_ALGO", None)
    env.pop("MYCODINGAGENT_EMBEDDING_MODEL", None)
    env.pop("MYCODINGAGENT_SKILL_SESSION_ACTIVATION_REWARD", None)
    env.pop("MYCODINGAGENT_USER_SKILL_CACHE_MAX_ENTRIES", None)
    env.pop("MYCODINGAGENT_LOAD_WORKSPACE_CONFIG", None)
    env.pop("MYCODINGAGENT_MCP_PROJECT_CONFIG", None)
    env.pop("MYCODINGAGENT_MCP_USER_CONFIG", None)
    env.pop("MYCODINGAGENT_APPROVAL_MODE", None)
    env.pop("MYCODINGAGENT_MAX_TOOL_ROUNDS", None)
    env.pop("MYCODINGAGENT_MODEL_AUDIO_PROVIDER", None)
    env.pop("MYCODINGAGENT_MODEL_AUDIO_MODEL", None)
    env.pop("MYCODINGAGENT_MODEL_VISION_PROVIDER", None)
    env.pop("MYCODINGAGENT_MODEL_VISION_MODEL", None)
    env.pop("MYCODINGAGENT_SEARCH_ENABLED", None)
    env.pop("MYCODINGAGENT_SEARCH_ENDPOINT", None)
    env.pop("MYCODINGAGENT_SEARCH_MAX_RESULTS", None)
    env.pop("MYCODINGAGENT_MEMORY_DB_PATH", None)
    env.pop("MYCODINGAGENT_STATE_DIR", None)
    env.pop("XDG_STATE_HOME", None)
    if extra_env:
        env.update(extra_env)
    return _run_config_probe(cwd=workspace, env=env)


def _run_config_probe(*, cwd: Path, env: dict[str, str]) -> dict:
    code = (
        "import json\n"
        "from mycodingagent.configuration import CONFIG\n"
        "print(json.dumps({\n"
        "  'provider': CONFIG.embedding.provider,\n"
        "  'model': CONFIG.embedding.model,\n"
        "  'endpoint': CONFIG.embedding.endpoint,\n"
        "  'api_format': CONFIG.embedding.api_format,\n"
        "  'dimension': CONFIG.embedding.dimension,\n"
        "  'milvus_uri': CONFIG.milvus.uri,\n"
        "  'milvus_collection': CONFIG.milvus.collection,\n"
        "  'milvus_dense_index_type': CONFIG.milvus.dense_index_type,\n"
        "  'milvus_dense_metric_type': CONFIG.milvus.dense_metric_type,\n"
        "  'milvus_hnsw_m': CONFIG.milvus.hnsw_m,\n"
        "  'milvus_hnsw_ef_construction': CONFIG.milvus.hnsw_ef_construction,\n"
        "  'milvus_hnsw_ef': CONFIG.milvus.hnsw_ef,\n"
        "  'milvus_sparse_index_type': CONFIG.milvus.sparse_index_type,\n"
        "  'milvus_sparse_metric_type': CONFIG.milvus.sparse_metric_type,\n"
        "  'milvus_sparse_inverted_index_algo': CONFIG.milvus.sparse_inverted_index_algo,\n"
        "  'milvus_has_legacy_index_type': hasattr(CONFIG.milvus, 'index_type'),\n"
        "  'milvus_has_legacy_metric_type': hasattr(CONFIG.milvus, 'metric_type'),\n"
        "  'memory_state_dir': str(CONFIG.memory.state_dir),\n"
        "  'memory_db_path': str(CONFIG.memory.db_path),\n"
        "  'mcp_project_config_path': str(CONFIG.mcp.project_config_path),\n"
        "  'mcp_user_config_path': str(CONFIG.mcp.user_config_path),\n"
        "  'approval_mode': CONFIG.approval.mode,\n"
        "  'max_tool_rounds': CONFIG.client.max_tool_rounds,\n"
        "  'research_max_tool_rounds': CONFIG.research.max_tool_rounds,\n"
        "  'research_max_sources': CONFIG.research.max_sources,\n"
        "  'research_fetch_max_chars': CONFIG.research.fetch_max_chars_per_source,\n"
        "  'audio_provider': CONFIG.model.audio.provider,\n"
        "  'audio_model': CONFIG.model.audio.model,\n"
        "  'vision_provider': CONFIG.model.vision.provider,\n"
        "  'vision_model': CONFIG.model.vision.model,\n"
        "  'search_enabled': CONFIG.search.enabled,\n"
        "  'search_endpoint': CONFIG.search.endpoint,\n"
        "  'search_max_results': CONFIG.search.max_results,\n"
        "  'network_enabled': CONFIG.network.enabled,\n"
        "  'network_upstream_proxy': CONFIG.network.upstream_proxy,\n"
        "  'session_activation_reward': CONFIG.skills.session_activation_reward,\n"
        "  'user_skill_cache_max_entries': CONFIG.skills.user_skill_cache_max_entries,\n"
        "}, ensure_ascii=False, sort_keys=True))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(result.stdout)


def test_config_file_controls_embedding_and_milvus(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "embedding": {
                    "provider": "http",
                    "api_format": "openai",
                    "model": "text-embedding-v4",
                    "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
                    "dimension": 1536,
                },
                "milvus": {
                    "host": "127.0.0.1",
                    "port": "19531",
                    "collection": "custom_skills",
                    "dense_index_type": "FLAT",
                    "dense_metric_type": "IP",
                    "hnsw_m": 32,
                    "hnsw_ef_construction": 300,
                    "hnsw_ef": 96,
                    "sparse_index_type": "SPARSE_INVERTED_INDEX",
                    "sparse_metric_type": "BM25",
                    "sparse_inverted_index_algo": "DAAT_WAND",
                },
            }
        ),
        encoding="utf-8",
    )

    data = _config_probe(config_path)

    assert data["provider"] == "http"
    assert data["model"] == "text-embedding-v4"
    assert data["api_format"] == "openai"
    assert data["dimension"] == 1536
    assert data["milvus_uri"] == "http://127.0.0.1:19531"
    assert data["milvus_collection"] == "custom_skills"
    assert data["milvus_dense_index_type"] == "FLAT"
    assert data["milvus_dense_metric_type"] == "IP"
    assert data["milvus_hnsw_m"] == 32
    assert data["milvus_hnsw_ef_construction"] == 300
    assert data["milvus_hnsw_ef"] == 96
    assert data["milvus_sparse_index_type"] == "SPARSE_INVERTED_INDEX"
    assert data["milvus_sparse_metric_type"] == "BM25"
    assert data["milvus_sparse_inverted_index_algo"] == "DAAT_WAND"
    assert data["milvus_has_legacy_index_type"] is False
    assert data["milvus_has_legacy_metric_type"] is False


def test_config_file_overrides_environment_variable(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"milvus": {"port": "19531"}}), encoding="utf-8")

    data = _config_probe(config_path, extra_env={"MYCODINGAGENT_MILVUS_PORT": "19532"})

    assert data["milvus_uri"] == "http://127.0.0.1:19531"


def test_approval_mode_loads_from_config_and_overrides_environment(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"approval": {"mode": "auto"}}), encoding="utf-8")

    data = _config_probe(
        config_path,
        extra_env={"MYCODINGAGENT_APPROVAL_MODE": "default"},
    )

    assert data["approval_mode"] == "auto"


def test_max_tool_rounds_defaults_to_100_and_supports_user_override(tmp_path):
    missing_path = tmp_path / "missing.json"
    empty_path = tmp_path / "empty.json"
    custom_path = tmp_path / "custom.json"
    missing_path.write_text("{}", encoding="utf-8")
    empty_path.write_text(json.dumps({"client": {"max_tool_rounds": ""}}), encoding="utf-8")
    custom_path.write_text(json.dumps({"client": {"max_tool_rounds": 240}}), encoding="utf-8")

    assert _config_probe(missing_path)["max_tool_rounds"] == 100
    assert _config_probe(empty_path)["max_tool_rounds"] == 100
    assert _config_probe(custom_path)["max_tool_rounds"] == 240


def test_research_max_tool_rounds_defaults_to_100_and_is_capped(tmp_path):
    missing_path = tmp_path / "missing.json"
    custom_path = tmp_path / "custom.json"
    oversized_path = tmp_path / "oversized.json"
    missing_path.write_text("{}", encoding="utf-8")
    custom_path.write_text(json.dumps({"research": {"max_tool_rounds": 40}}), encoding="utf-8")
    oversized_path.write_text(json.dumps({"research": {"max_tool_rounds": 240}}), encoding="utf-8")

    assert _config_probe(missing_path)["research_max_tool_rounds"] == 100
    assert _config_probe(custom_path)["research_max_tool_rounds"] == 40
    assert _config_probe(oversized_path)["research_max_tool_rounds"] == 100


def test_research_source_and_page_limits_are_hard_capped(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "research": {
                    "max_sources": 20,
                    "fetch_max_chars_per_source": 50000,
                }
            }
        ),
        encoding="utf-8",
    )

    config = _config_probe(config_path)

    assert config["research_max_sources"] == 5
    assert config["research_fetch_max_chars"] == 6000


def test_media_model_defaults_and_environment_overrides(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    defaults = _config_probe(config_path)
    overridden = _config_probe(
        config_path,
        extra_env={
            "MYCODINGAGENT_MODEL_AUDIO_PROVIDER": "zhipu",
            "MYCODINGAGENT_MODEL_AUDIO_MODEL": "glm-asr-2512",
            "MYCODINGAGENT_MODEL_VISION_PROVIDER": "qwen",
            "MYCODINGAGENT_MODEL_VISION_MODEL": "qwen3-vl-flash",
        },
    )

    assert defaults["audio_provider"] == "qwen"
    assert defaults["audio_model"] == "qwen3-asr-flash"
    assert defaults["vision_provider"] == "zhipu"
    assert defaults["vision_model"] == "glm-4v-flash"
    assert overridden["audio_provider"] == "zhipu"
    assert overridden["audio_model"] == "glm-asr-2512"
    assert overridden["vision_provider"] == "qwen"
    assert overridden["vision_model"] == "qwen3-vl-flash"


def test_search_defaults_and_environment_overrides(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    defaults = _config_probe(config_path)
    overridden = _config_probe(
        config_path,
        extra_env={
            "MYCODINGAGENT_SEARCH_ENABLED": "false",
            "MYCODINGAGENT_SEARCH_ENDPOINT": "http://127.0.0.1:9999/search",
            "MYCODINGAGENT_SEARCH_MAX_RESULTS": "6",
        },
    )

    assert defaults["search_enabled"] is True
    assert defaults["search_endpoint"] == ""
    assert defaults["search_max_results"] == 10
    assert defaults["network_enabled"] is True
    assert defaults["network_upstream_proxy"] == "auto"
    assert overridden["search_enabled"] is False
    assert overridden["search_endpoint"] == "http://127.0.0.1:9999/search"
    assert overridden["search_max_results"] == 6


def test_empty_config_string_falls_back_to_environment_variable(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"embedding": {"model": ""}}), encoding="utf-8")

    data = _config_probe(config_path, extra_env={"MYCODINGAGENT_EMBEDDING_MODEL": "env-model"})

    assert data["model"] == "env-model"


def test_skill_lrfu_settings_are_loaded_from_config_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "skills": {
                    "session_activation_reward": 0.7,
                    "user_skill_cache_max_entries": 321,
                }
            }
        ),
        encoding="utf-8",
    )

    data = _config_probe(config_path)

    assert data["session_activation_reward"] == 0.7
    assert data["user_skill_cache_max_entries"] == 321


def test_workspace_config_is_not_loaded_by_default(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    (workspace / ".mycodingagent").mkdir(parents=True)
    home.mkdir()
    (workspace / ".mycodingagent" / "config.json").write_text(
        json.dumps({"embedding": {"model": "workspace-only-model"}}),
        encoding="utf-8",
    )

    data = _workspace_config_probe(workspace, home)

    assert data["model"] != "workspace-only-model"


def test_legacy_workspace_config_flag_is_ignored(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    (workspace / ".mycodingagent").mkdir(parents=True)
    home.mkdir()
    (workspace / ".mycodingagent" / "config.json").write_text(
        json.dumps({"embedding": {"model": "workspace-enabled-model"}}),
        encoding="utf-8",
    )

    data = _workspace_config_probe(
        workspace,
        home,
        extra_env={"MYCODINGAGENT_LOAD_WORKSPACE_CONFIG": "1"},
    )

    assert data["model"] != "workspace-enabled-model"


def test_mcp_project_config_path_defaults_to_current_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    data = _workspace_config_probe(workspace, home)

    assert data["mcp_project_config_path"] == str(workspace / ".mycodingagent" / "mcp.json")
    assert data["mcp_user_config_path"] == str(home / ".mycodingagent" / "mcp.json")


def test_memory_db_path_defaults_to_mycodingagent_state_dir(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    data = _workspace_config_probe(
        workspace,
        home,
        extra_env={"XDG_STATE_HOME": str(tmp_path / "xdg-state")},
    )

    assert data["memory_state_dir"] == str(home / ".mycodingagent" / "state")
    assert data["memory_db_path"] == str(home / ".mycodingagent" / "state" / "sessions.sqlite3")


def test_dashscope_embedding_response_shape_is_supported():
    vectors = _extract_embeddings(
        {
            "output": {
                "embeddings": [
                    {"text_index": 1, "embedding": [0.3, 0.4]},
                    {"text_index": 0, "embedding": [0.1, 0.2]},
                ]
            }
        }
    )

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_embedding_config_rejects_removed_provider_alias():
    config = EmbeddingConfig(provider="bge_http")

    assert config.validation_errors() == [
        "embedding.provider='bge_http' 不受支持；支持：http、local、hash"
    ]


def test_http_embedding_config_validates_api_contract():
    config = EmbeddingConfig(provider="http", api_format="custom", endpoint="", model="")

    assert config.validation_errors() == [
        "embedding.api_format='custom' 不受支持；支持：ollama、openai、dashscope",
        "embedding.endpoint 不能为空",
        "embedding.model 不能为空",
    ]


def test_milvus_dense_params_are_hnsw_specific(monkeypatch):
    monkeypatch.setattr(
        vector_store,
        "CONFIG",
        SimpleNamespace(
            milvus=SimpleNamespace(
                dense_index_type="HNSW",
                dense_metric_type="COSINE",
                hnsw_m=16,
                hnsw_ef_construction=200,
                hnsw_ef=64,
            )
        ),
    )

    assert vector_store._dense_index_params() == {"M": 16, "efConstruction": 200}
    assert vector_store._dense_search_params() == {
        "metric_type": "COSINE",
        "params": {"ef": 64},
    }

    monkeypatch.setattr(
        vector_store,
        "CONFIG",
        SimpleNamespace(
            milvus=SimpleNamespace(
                dense_index_type="FLAT",
                dense_metric_type="COSINE",
                hnsw_m=16,
                hnsw_ef_construction=200,
                hnsw_ef=64,
            )
        ),
    )

    assert vector_store._dense_index_params() == {}
    assert vector_store._dense_search_params() == {"metric_type": "COSINE"}


class _FakeMilvusClient:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **_kwargs):
        return self.rows


def _record() -> SkillRecord:
    return SkillRecord(
        name="Demo",
        tool_name="demo",
        description="demo skill",
        content="demo content",
        source_path=Path("skills/demo/SKILL.md"),
        content_hash="hash-1",
        updated_at=1.0,
    )


def test_milvus_stale_records_include_embedding_signature_changes():
    store = MilvusVectorStore.__new__(MilvusVectorStore)
    store.ready = True
    store.collection_name = "skills"
    store.embedding_signature = "sig-new"
    store._client = _FakeMilvusClient(
        [
            {
                TOOL_NAME_FIELD: "demo",
                CONTENT_HASH_FIELD: "hash-1",
                EMBEDDING_SIGNATURE_FIELD: "sig-old",
            }
        ]
    )

    assert store.stale_records({"demo": _record()}) == [_record()]


def test_milvus_stale_records_skip_matching_hash_and_embedding_signature():
    store = MilvusVectorStore.__new__(MilvusVectorStore)
    store.ready = True
    store.collection_name = "skills"
    store.embedding_signature = "sig-current"
    store._client = _FakeMilvusClient(
        [
            {
                TOOL_NAME_FIELD: "demo",
                CONTENT_HASH_FIELD: "hash-1",
                EMBEDDING_SIGNATURE_FIELD: "sig-current",
            }
        ]
    )

    assert store.stale_records({"demo": _record()}) == []
