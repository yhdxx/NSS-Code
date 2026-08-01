# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.12 local coding-agent runtime. The main package lives in `mycodingagent/`, with `app/` as the CLI composition root, `llm_runtime/` for model execution, `tool_runtime/` for tool implementations, `memory/` and `long_term_memory/` for persistence, `skill_runtime/` for skills, `mcp_integration/` for MCP support, and `code_intelligence/` for indexing/LSP features. Tests live in `tests/`; versioned evaluation harnesses and datasets are under `tests/eval/`. User-facing docs are in `README.md`, `docs/`, and module-level `README.md` files. Install and launcher scripts are in `scripts/`; built-in skill examples are under `skills/`.

## Build, Test, and Development Commands

- `bash scripts/install.sh`: create `.venv`, install `requirements.txt`, install the `myAgent` launcher, and build the Docker sandbox image.
- `bash scripts/install.sh --skip-docker --skip-lsp`: install Python dependencies without Docker or optional language servers.
- `PYTHONPATH=. .venv/bin/python -m pytest -q`: run the normal test suite.
- `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_command_registry.py`: run a focused test file.
- `PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner generate-datasets`: run explicit evaluation workflow steps; see `tests/eval/README.md` before running API/Docker-backed evaluations.

## Coding Style & Naming Conventions

Use 4-space indentation, type hints, and `from __future__ import annotations` in new Python modules when consistent with nearby files. Prefer `pathlib.Path`, dataclasses/Pydantic models for structured data, and async APIs where the runtime already uses them. Keep environment variables prefixed with `MYCODINGAGENT_`. Name tests `test_*.py` and functions `test_<behavior>`. There is no project-wide formatter config, so match local style and keep imports simple.

## Testing Guidelines

Add or update pytest coverage for behavioral changes, especially tool execution, command parsing, memory, MCP, skills, and workspace safety. Keep ordinary unit tests separate from `tests/eval/`, which may require real APIs, Docker, Milvus, or model calls. Prefer focused tests with `tmp_path`/`monkeypatch` over touching real user state.

## Commit & Pull Request Guidelines

Recent commits use concise Chinese summaries describing the feature or fix, sometimes with detailed rationale. Follow that style unless the surrounding branch uses another convention. PRs should include the problem, implementation summary, tests run, configuration or migration notes, and screenshots/log excerpts only for UI or terminal-output changes.

## Security & Configuration Tips

Do not commit secrets, local memory databases, `.venv/`, `.pytest_cache/`, or generated eval runs unless intentionally documenting results. Document new `MYCODINGAGENT_*` settings in `README.md` and keep Docker sandbox defaults conservative.
