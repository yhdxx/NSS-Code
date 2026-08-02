from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.eval.artifacts import (
    METRIC_SPECS, complete_metric_run, metric_run_dir, render_metric_document,
)
from tests.eval.dataset_generators import (
    generate_capability_routing_1200_cases, generate_context_virtualization_cases,
    generate_long_term_workflow_cases, generate_prefix_cache_cases,
    generate_runtime_context_virtualization_cases,
)
from tests.eval.metrics import (
    bootstrap_mean_ci, cache_hit_rate, percentile, reduction_rate, stable_json_hash,
)
from tests.eval.prefix_cache_benchmark import extract_cache_usage
from tests.eval.public_projects import load_manifest
from tests.eval.run_context import build_run_metadata, write_run_metadata


def test_metrics_are_deterministic_and_use_expected_formulas() -> None:
    assert percentile([1, 2, 3, 4], .5) == 2.5
    assert percentile([1, 2, 3, 4], .95) == 3.85
    assert cache_hit_rate(935, 65) == .935
    assert cache_hit_rate(0, 0) is None
    assert reduction_rate(100, 30) == .7
    assert bootstrap_mean_ci([0, 1, 1], seed=7) == bootstrap_mean_ci([0, 1, 1], seed=7)
    assert stable_json_hash({"b": 1, "a": 2}) == stable_json_hash({"a": 2, "b": 1})


def test_cache_usage_is_unavailable_when_provider_omits_fields() -> None:
    assert extract_cache_usage({"prompt_tokens": 100}) == {
        "status": "unavailable", "hit_tokens": None, "miss_tokens": None, "hit_rate": None,
    }
    assert extract_cache_usage({"prompt_cache_hit_tokens": 90, "prompt_cache_miss_tokens": 10})["hit_rate"] == .9


def test_standard_datasets_have_locked_scale_and_no_exact_capability_ids() -> None:
    assert len(generate_context_virtualization_cases()) == 30
    runtime_context = generate_runtime_context_virtualization_cases()
    assert len(runtime_context) == 30
    assert {row["category"] for row in runtime_context} == {
        "long_distance_fact", "large_tool_output", "topic_return", "rollover_pressure",
    }
    memory = generate_long_term_workflow_cases()
    assert len(memory) == 30
    assert {row["memory_type"] for row in memory} == {"workflow", "preference", "project_fact"}
    assert len(generate_prefix_cache_cases()) == 30
    routing = generate_capability_routing_1200_cases()[0]
    assert len(routing["capabilities"]) == 1200
    assert sum(row["kind"] == "skill" for row in routing["capabilities"]) == 900
    assert sum(row["kind"] == "mcp" for row in routing["capabilities"]) == 300
    assert len(routing["queries"]) == 200
    capability_ids = {row["id"] for row in routing["capabilities"]}
    assert all(not any(identifier in query["query"] for identifier in capability_ids) for query in routing["queries"])


def test_public_project_manifest_has_fixed_commits() -> None:
    projects = load_manifest(Path("tests/eval/manifests/public_projects.json"))
    assert len(projects) == 10
    assert len({project.project_id for project in projects}) == 10
    assert all(len(project.commit) == 40 for project in projects)


def test_metadata_hashes_dataset_and_tool_schema(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text('{"case_id": "one"}\n', encoding="utf-8")
    metadata = build_run_metadata(run_id="run-one", repeats=3, tool_schemas=[{"name": "ReadFile"}], dataset_path=dataset)
    assert metadata.dataset_sha256
    assert metadata.tool_schema_hash
    output = write_run_metadata(tmp_path / "run", metadata)
    assert json.loads(output.read_text(encoding="utf-8"))["run_id"] == "run-one"


def test_versioned_run_refuses_to_overwrite_completed_summary(tmp_path: Path) -> None:
    path = metric_run_dir(tmp_path, "run-one", "prefix_cache")
    (path / "summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        metric_run_dir(tmp_path, "run-one", "prefix_cache")


def test_every_metric_document_has_required_sections_and_failure_evidence(tmp_path: Path) -> None:
    required = [
        "## 指标定义", "## 计算公式", "## 数据集与样本", "## 测试环境",
        "## 执行命令", "## 结果与置信区间", "## 失败、超时与异常样例",
        "## 局限与有效性威胁", "## 简历可用结论",
    ]
    for metric in METRIC_SPECS:
        document = render_metric_document(
            metric, {"status": "not_run", "reason": "dependency absent"},
            {"run_id": "test"}, "python command",
            [{"case_id": "failed-case", "status": "timeout", "passed": False}],
        )
        assert all(section in document for section in required)
        assert "failed-case" in document
        assert "不可使用量化结论" in document


def test_complete_metric_run_writes_summary_details_and_both_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-one" / "prefix_cache"
    docs_dir = tmp_path / "docs"
    report = complete_metric_run(
        metric="prefix_cache", run_dir=run_dir,
        summary={"status": "unavailable", "reason": "provider omitted fields"},
        metadata={"run_id": "run-one"}, command="python eval.py",
        details=[{"case_id": "one", "status": "unavailable"}], docs_dir=docs_dir,
    )
    assert report.exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "details.jsonl").exists()
    assert (docs_dir / "prefix_cache.md").exists()
