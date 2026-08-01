from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "MYCODINGAGENT_CONFIG": str(config_path),
    }
    env.pop("MYCODINGAGENT_MILVUS_PORT", None)
    env.pop("MYCODINGAGENT_EMBEDDING_MODEL", None)
    env.pop("MYCODINGAGENT_BGE_MODEL", None)
    env.pop("MYCODINGAGENT_LOAD_WORKSPACE_CONFIG", None)
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
    env.pop("MYCODINGAGENT_EMBEDDING_MODEL", None)
    env.pop("MYCODINGAGENT_BGE_MODEL", None)
    env.pop("MYCODINGAGENT_LOAD_WORKSPACE_CONFIG", None)
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
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
embedding:
  provider: openai_compatible
  model: text-embedding-v4
  endpoint: https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
  dimension: 1536
milvus:
  host: 127.0.0.1
  port: "19531"
  collection: custom_skills
""",
        encoding="utf-8",
    )

    data = _config_probe(config_path)

    assert data["provider"] == "openai_compatible"
    assert data["model"] == "text-embedding-v4"
    assert data["api_format"] == "openai"
    assert data["dimension"] == 1536
    assert data["milvus_uri"] == "http://127.0.0.1:19531"
    assert data["milvus_collection"] == "custom_skills"


def test_environment_variable_overrides_config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("milvus:\n  port: '19531'\n", encoding="utf-8")

    data = _config_probe(config_path, extra_env={"MYCODINGAGENT_MILVUS_PORT": "19532"})

    assert data["milvus_uri"] == "http://127.0.0.1:19532"


def test_legacy_bge_environment_variable_overrides_config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("embedding:\n  model: configured-model\n", encoding="utf-8")

    data = _config_probe(config_path, extra_env={"MYCODINGAGENT_BGE_MODEL": "legacy-env-model"})

    assert data["model"] == "legacy-env-model"


def test_workspace_config_is_not_loaded_by_default(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    (workspace / ".mycodingagent").mkdir(parents=True)
    home.mkdir()
    (workspace / ".mycodingagent" / "config.yaml").write_text(
        "embedding:\n  model: workspace-only-model\n",
        encoding="utf-8",
    )

    data = _workspace_config_probe(workspace, home)

    assert data["model"] != "workspace-only-model"


def test_workspace_config_can_be_enabled_explicitly(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    (workspace / ".mycodingagent").mkdir(parents=True)
    home.mkdir()
    (workspace / ".mycodingagent" / "config.yaml").write_text(
        "embedding:\n  model: workspace-enabled-model\n",
        encoding="utf-8",
    )

    data = _workspace_config_probe(
        workspace,
        home,
        extra_env={"MYCODINGAGENT_LOAD_WORKSPACE_CONFIG": "1"},
    )

    assert data["model"] == "workspace-enabled-model"


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
