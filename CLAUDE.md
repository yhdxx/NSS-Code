# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

myCodingAgent is itself a local coding-agent harness (a Claude-Code-like CLI). Terminal input → capability routing →
LLM tool loop → sandboxed tool execution → SQLite-backed session/context/long-term memory. Two long-form design docs
already exist and are kept current — **read them before changing runtime behavior**:

- `README.md` — end-to-end walkthrough of the main flow.
- `PROJECT_FRAMEWORK.md` — per-stage flow diagrams, persistence tables, module dependency boundaries.

Per-module `README.md` files (e.g. `mycodingagent/memory/README.md`) state each module's one-line responsibility and
its dependency rules. Both root docs and the module READMEs are written in Chinese; keep that language when editing them.

## Commands

```bash
# Run the agent — the installer places this launcher in ~/.local/bin and the CWD becomes the sandbox root
myAgent

# Upgrade runtime dependencies and optionally install missing language servers before startup
myAgent --upgrade

# Full unit/integration suite (Python 3.12, deps in .venv)
PYTHONPATH=. .venv/bin/python -m pytest -q

# Core regression trio touched by most memory/multi-agent changes
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_long_term_memory.py tests/test_memory_runtime.py tests/test_multi_agent.py

# Main agent loop: API retry, turn preservation, tool failure detection, command approval
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_llm_runtime_client.py tests/test_command_policy.py

# Single test
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_memory_runtime.py::test_name

# Rebuild the Bash sandbox image after editing Dockerfile.sandbox / requirements-sandbox.txt
DOCKER_CONFIG=$PWD/.docker-cli docker build --network=host -f Dockerfile.sandbox -t mycodingagent-sandbox:py312 .
```

`PYTHONPATH=.` is required — there is no installed package or `pyproject.toml`; imports resolve from the repo root.
There is no configured linter or formatter.

### Effectiveness evals (real API / Milvus / Docker — slow, costs tokens)

Separate from pytest, driven by `tests/eval/runner.py` subcommands. Generate datasets first:

```bash
PYTHONPATH=. .venv/bin/python -m tests.eval.dataset_generators
PYTHONPATH=. .venv/bin/python -m tests.eval.runner precheck-bge          # verify BGE endpoint before anything else
PYTHONPATH=. .venv/bin/python -m tests.eval.runner run-skill-router      # also: run-context, run-recovery,
                                                                          # run-capability-router, run-long-term-workflow,
                                                                          # run-multi-agent-ab [--project-size small|medium|large]
PYTHONPATH=. .venv/bin/python -m tests.eval.runner report                # writes docs/eval_report.md
```

Results land in `tests/eval/results/*.jsonl`; conclusions in `docs/`.

## Architecture invariants

These are enforced by `tests/test_architecture_boundaries.py` or by design, and are easy to break accidentally:

- **`mycodingagent/app/main.py` is the only composition root.** It is the sole place allowed to construct and wire
  concrete implementations of multiple modules. Nothing may import `app`. Shutdown order must mirror init order
  (long-term memory → memory → MCP → skill watcher → workspace tracker → API client), or sessions lose messages.
- **No import cycles inside `mycodingagent/`** (Tarjan check in the boundary test). Cross-module collaboration goes
  through Protocols in `*/contracts.py`, not concrete classes: `tool_runtime/skill_tools.py` depends on
  `skill_runtime.contracts.SkillService`, `tool_runtime/memory_lookup.py` on `memory.contracts.ContextEpochControl`,
  `memory/context_epoch.py` on a local `ContextEpochStore` Protocol, and `capability_discovery/` must never import
  `mycodingagent.mcp_integration`.
- **The repo root holds only a thin entrypoint.** `__main__.py` must stay a two-line delegation to
  `mycodingagent.app.main`; the boundary test asserts a list of legacy root modules (`client.py`, `config.py`, …)
  stays deleted.
- **Adding an MCP server must not grow the model's tool schema.** MCP is exposed via a fixed set of discovery/execution
  tools (`list_mcp_*`/`search_mcp_*`/`call_mcp_tool`/`read_mcp_resource`/`get_mcp_prompt`) enumerated in `app/main.py`.
  Do not register legacy aliases: MCP names must remain visibly distinct from Skill discovery tools such as `search_tool`.
- **Multi-agent is user-triggered only.** No delegation tool is registered for the main model; `/multiAgent` is the
  only entry. Read-only subagent roles must not receive write tools.
- **Every tool call carries a short `intent`.** `Tool.get_schema()` in `tool_runtime/base.py` injects `intent` into
  every tool's properties and required list automatically — don't declare it in `params_model`. Cold-history
  virtualization replaces tool output with metadata and falls back to `intent` as the readable summary, so tools that
  bypass the base schema degrade long sessions.
- **Large tool output is never inlined.** Store the full text and return a head/tail preview plus `context_id`
  recoverable via `SearchRecoverableContext` / `BatchRecoverContext`.
- **`ToolResult.is_error` is the only failure signal.** `execute_local_tool` returns `(output, is_error)` and that flag
  lands in the tool message's `metadata`. Never infer failure by sniffing the output text — a normal JSON file
  containing an `"error"` key is not a failed call, and that misfire used to poison the model with "don't retry".
- **A failed API call must not discard completed work.** `ask_deepseek` rolls back the turn only when nothing ran;
  once any tool has executed, the results stay in `messages`. `stream_one_round` retries connection/timeout/429/5xx
  with exponential backoff (never 4xx), discarding partial chunks between attempts so retries can't produce doubled
  text or truncated tool-call JSON. Regression locks live in `tests/test_llm_runtime_client.py`.
- **Long-term memory writes go through typed buckets.** `user_profiles`, `user_preferences`, `project_facts`,
  `workflows`, `skill_candidates` map to memory type + namespace in `long_term_memory/namespaces.py`
  (global user / workflow staging / current workspace). For `workflow_candidate` / `skill_candidate` items the store's
  `_validate_workflow_metadata` requires non-empty `metadata.workflow.{name,description,when_to_use}` and a
  `when_not_use` array of at most 3 non-empty entries.

## Things that surprise newcomers

- **Config is one frozen dataclass tree**, `CONFIG` in `mycodingagent/configuration/settings.py`, built at import
  time. Every knob is an env var; nothing is read from a config file at runtime. Because the dataclasses are frozen and
  evaluated at import, tests that need different settings must set the env var *before* importing, or monkeypatch.
- **The sandbox root is `os.getcwd()` at startup** unless `MYCODINGAGENT_SANDBOX_ROOT` is set. All file tools reject
  paths outside it, and `resolve_sandbox_path` maps container-side `/workspace/...` paths back onto the host root.
- **`Bash` runs in a throwaway Docker container** (`mycodingagent-sandbox:py312`, network `none` by default). Startup
  aborts if the image can't be prepared. Packages installed inside a running container do not persist — add them to
  `requirements-sandbox.txt` and rebuild (see `Docker_Image_Configuration.md`).
- **File writes require a prior read.** `WriteFile`/`EditFile` check `FileStateCache` for a recorded read and compare
  mtime/size, so external edits between read and write are rejected rather than clobbered.
- **Dangerous shell commands prompt for approval.** `tool_runtime/command_policy.py::classify_command` flags only
  hard-to-undo or out-of-sandbox operations (`rm -rf`, `git push --force`, `sudo`, `chmod -R`, curl-pipe-sh, raw device
  writes, absolute paths outside the workspace). Ordinary commands never prompt — false positives train users to
  blind-approve. The hook is injected by `app/main.py` only when `sys.stdin.isatty()`; `approval_hook=None` disables
  the gate entirely, which is what keeps tests and non-interactive runs working.
- **`DEEPSEEK_API_KEY` has no default.** Startup exits early with setup instructions when it's unset.
- **Two SQLite databases.** Sessions/context/long-term memory live in `CONFIG.memory.db_path`
  (`~/.local/state/myCodingAgent/sessions.sqlite3` by default, overridable via `MYCODINGAGENT_STATE_DIR` /
  `XDG_STATE_HOME`); multi-agent runs live in `multi_agent.sqlite3` beside it. Skill metadata and LRFU state live in
  `skills/.skill_runtime/*.sqlite3` (gitignored); vectors live in Milvus, with keyword-match fallback when it's down.
- **Skills are loaded from `CONFIG.skills.builtin_root` (repo `skills/`) plus `MYCODINGAGENT_EXTRA_SKILLS_ROOTS`** —
  the current workspace's `skills/` directory is *not* auto-watched. New/changed skills pass code review and prompt
  review before being indexed.
- **The model sees `<RUNTIME_CONTEXT>` and `<USER_REQUEST>` blocks**, built per turn by `RuntimeContextBuilder` /
  `PromptRenderer` in `llm_runtime/context.py` and driven from `ask_deepseek`. Long-term memory is flattened into a
  single `long_term_memory.memory` string (four sections; `未查询到相关记忆` when empty), never a structured array.
- **`scripts/` holds one-off long-term-memory migrations** (`migrate_ltm_*.py`). Schema changes to memory items
  generally need a matching migration script.

## Code conventions

- Python 3.12, `from __future__ import annotations`, PEP 604 unions (`X | None`), `pathlib`, dataclasses for config
  and models, Pydantic `BaseModel` only for tool parameter schemas (`Tool.params_model`).
- Comment density is **not** uniform: older modules (`app/main.py`, `tool_runtime/`, `llm_runtime/client.py`) carry a
  Chinese inline comment on nearly every line, while newer ones (`long_term_memory/`, `capability_discovery/`) are
  essentially comment-free. Match the file you are editing rather than imposing one style.
- New tools subclass `Tool` in `mycodingagent/tool_runtime/base.py` (set `name`, `description`, `params_model`,
  `category` of read/write/command) and are registered in `create_default_registry`. Return `ToolResult`; signal
  failure with `is_error=True` rather than raising.
