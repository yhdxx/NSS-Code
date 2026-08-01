from __future__ import annotations

import json
import sqlite3
import time
import tracemalloc
from pathlib import Path
from typing import Any

from mycodingagent.code_intelligence import ProjectGraphService, WorkspaceCodeIndex
from mycodingagent.code_intelligence.index import LANGUAGE_BY_SUFFIX
from tests.eval.metrics import bootstrap_mean_ci, mean, percentile
from tests.eval.public_projects import PublicProject


def run_project_graph_benchmark(
    projects: list[PublicProject],
    *,
    projects_root: Path,
    run_dir: Path,
    annotations_dir: Path | None = None,
) -> dict[str, Any]:
    details = []
    for project in projects:
        workspace = projects_root / project.project_id
        if not workspace.exists():
            details.append({"project_id": project.project_id, "status": "blocked", "reason": "project_not_prepared"})
            continue
        details.append(_benchmark_project(project, workspace, run_dir / "state", annotations_dir))
    completed = [row for row in details if row.get("status") == "passed"]
    summary = {
        "module": "project_graph",
        "status": "passed" if len(completed) == len(projects) else "blocked",
        "project_count": len(projects),
        "completed_projects": len(completed),
        "first_build_seconds": _distribution(row["first_build_seconds"] for row in completed),
        "warm_read_seconds": _distribution(row["warm_read_seconds"] for row in completed),
        "incremental_refresh_seconds": _distribution(row["incremental_refresh_seconds"] for row in completed),
        "peak_memory_mib": _distribution(row["peak_memory_mib"] for row in completed),
        "annotation_projects": sum(row.get("annotation_status") == "evaluated" for row in completed),
        "symbol_coverage": _optional_mean(row.get("symbol_coverage") for row in completed),
        "call_precision": _optional_mean(row.get("call_precision") for row in completed),
        "call_recall": _optional_mean(row.get("call_recall") for row in completed),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(run_dir / "project_graph_details.jsonl", details)
    _write_jsonl(run_dir / "project_graph.jsonl", [summary])
    return summary


def _benchmark_project(
    project: PublicProject,
    workspace: Path,
    state_root: Path,
    annotations_dir: Path | None,
) -> dict[str, Any]:
    state = state_root / project.project_id
    state.mkdir(parents=True, exist_ok=True)
    index = WorkspaceCodeIndex(workspace, state / "code_index.sqlite3")
    graph = ProjectGraphService(workspace, state / "project_graph.sqlite3", index)
    tracemalloc.start()
    started = time.perf_counter()
    status = graph.status()
    first_build = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    started = time.perf_counter()
    architecture = graph.architecture("")
    warm_read = time.perf_counter() - started
    incremental = _measure_incremental_refresh(workspace, graph, index)
    with sqlite3.connect(state / "project_graph.sqlite3") as conn:
        node_count = int(conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0])
        edge_count = int(conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0])
    row = {
        "project_id": project.project_id,
        "language": project.language,
        "size": project.size,
        "commit": project.commit,
        "status": "passed",
        "first_build_seconds": round(first_build, 6),
        "warm_read_seconds": round(warm_read, 6),
        "incremental_refresh_seconds": round(incremental, 6),
        "peak_memory_mib": round(peak / 1024 / 1024, 6),
        "sqlite_mib": round(sum(path.stat().st_size for path in state.glob("*.sqlite3")) / 1024 / 1024, 6),
        "modules": len(architecture.get("modules", [])),
        "nodes": node_count,
        "edges": edge_count,
        "units": status.get("units", 0),
    }
    row.update(_evaluate_annotations(project, index, annotations_dir))
    return row


def _measure_incremental_refresh(
    workspace: Path, graph: ProjectGraphService, index: WorkspaceCodeIndex
) -> float:
    source = next(
        (path for path in sorted(workspace.rglob("*")) if path.is_file() and path.suffix.lower() in LANGUAGE_BY_SUFFIX),
        None,
    )
    if source is None:
        return 0.0
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"\n")
        index.mark_dirty(source)
        graph.mark_dirty(source)
        started = time.perf_counter()
        graph.architecture("")
        return time.perf_counter() - started
    finally:
        source.write_bytes(original)
        index.mark_dirty(source)
        graph.mark_dirty(source)
        graph.architecture("")


def _evaluate_annotations(
    project: PublicProject, index: WorkspaceCodeIndex, annotations_dir: Path | None
) -> dict[str, Any]:
    annotation_path = (annotations_dir / f"{project.project_id}.json") if annotations_dir else None
    if annotation_path is None or not annotation_path.exists():
        return {
            "annotation_status": "not_run",
            "annotation_reason": "missing manual symbol/call annotations",
            "symbol_coverage": None,
            "call_precision": None,
            "call_recall": None,
        }
    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    snapshot = index.static_graph_snapshot()
    symbols = {(row["path"], row["qualified_name"]) for row in snapshot["symbols"]}
    calls = {(row["path"], row["caller"], row["callee_name"]) for row in snapshot["calls"]}
    expected_symbols = {(row["path"], row["qualified_name"]) for row in annotations.get("symbols", [])}
    expected_calls = {(row["path"], row["caller"], row["callee_name"]) for row in annotations.get("calls", [])}
    scoped_detected_calls = {call for call in calls if call[0] in {item[0] for item in expected_calls}}
    return {
        "annotation_status": "evaluated",
        "annotated_symbols": len(expected_symbols),
        "annotated_calls": len(expected_calls),
        "symbol_coverage": _ratio(len(symbols & expected_symbols), len(expected_symbols)),
        "call_precision": _ratio(len(scoped_detected_calls & expected_calls), len(scoped_detected_calls)),
        "call_recall": _ratio(len(calls & expected_calls), len(expected_calls)),
    }


def _distribution(values) -> dict[str, Any]:
    items = list(values)
    return {
        "mean": mean(items),
        "p50": percentile(items, 0.5),
        "p95": percentile(items, 0.95),
        "ci95": bootstrap_mean_ci(items),
        "sample_count": len(items),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _optional_mean(values) -> float | None:
    items = [value for value in values if value is not None]
    return mean(items) if items else None


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
