from __future__ import annotations

import re
import asyncio
import os
import sqlite3
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, time
from typing import Awaitable, Callable, Literal

from tree_sitter_language_pack import get_parser

from mycodingagent.configuration import CONFIG
from mycodingagent.terminal_ui.application import SharedTerminalInput, TerminalCancelled, TerminalInput
from mycodingagent.terminal_ui.output import render_command_approval_request
from mycodingagent.sqlite_utils import SQLITE_CONNECTION_FACTORY, require_component_schema
from mycodingagent.tool_runtime.base import Tool, ToolResult
from pydantic import BaseModel

CommandRisk = Literal["normal", "dangerous"]
ExecutionRisk = Literal["read", "write", "network", "process", "dangerous", "unknown"]
PolicyLevel = Literal["low", "approval", "high"]
LOCK_KEY = "bash_policy:global"
DEFAULT_LOCK_TTL_SECONDS = 120
BASH_POLICY_SCHEMA_VERSION = 1

USER_DENIED_COMMAND_MESSAGE = "用户拒绝执行该命令"

# 高危命令模式。判定原则是"难以撤销"或"影响范围超出当前工作区"，
# 而不是"会写文件"——普通写入由沙箱和先读后改约束覆盖，不在这里拦截。
_DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR][a-zA-Z]*f|\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*f[a-zA-Z]*[rR]", "递归强制删除（rm -rf）"),
    (r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)", "强制推送（git push --force）"),
    (r"\bgit\s+reset\b.*--hard\b", "丢弃本地改动（git reset --hard）"),
    (r"\bgit\s+clean\b.*-[a-zA-Z]*f", "删除未跟踪文件（git clean -f）"),
    (r"\bgit\s+checkout\s+\.(\s|$)", "丢弃工作区改动（git checkout .）"),
    (r"\bgit\s+branch\s+(-D|--delete\s+--force)", "强制删除分支"),
    (r"\bgit\b.*\s--amend\b", "修改已有 commit（--amend）"),
    (r"\bgit\b.*\s--no-verify\b", "跳过 git hooks（--no-verify）"),
    (r"\bchmod\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rR]\b", "递归修改权限（chmod -R）"),
    (r"\bchown\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rR]\b", "递归修改属主（chown -R）"),
    (r"\b(curl|wget)\b[^|;&]*[|]\s*(sudo\s+)?(ba)?sh\b", "下载后直接执行脚本"),
    (r"\bdd\s+.*\bof=", "裸设备写入（dd of=）"),
    (r"\bmkfs(\.[a-z0-9]+)?\b", "格式化文件系统（mkfs）"),
    (r">\s*/dev/(sd|nvme|hd|vd)", "直接写入块设备"),
    (r"\bshred\b", "不可恢复擦除（shred）"),
    (r"\bsudo\b", "提权执行（sudo）"),
    (r"\btruncate\s+.*-s\s*0", "清空文件内容（truncate -s 0）"),
    (r":\(\)\s*\{.*\}\s*;\s*:", "fork 炸弹"),
    (r"\bhistory\s+-c\b", "清空命令历史"),
)

# 指向工作区之外的绝对路径写入/删除。容器内工作区固定挂载在 /workspace，
# 因此对 / 下其他系统目录的破坏性操作视为越界。
_OUT_OF_SANDBOX_PATTERN = re.compile(
    r"\b(rm|mv|cp|dd|tee|truncate|install)\b[^|;&]*\s(/(?!workspace\b|tmp\b|dev/null\b|proc\b)[a-zA-Z][^\s]*)"
)

_READ_COMMANDS = {"pwd", "ls", "cat", "head", "tail", "grep", "rg", "find", "stat", "wc", "git"}
_WRITE_COMMANDS = {"mkdir", "touch", "cp", "mv", "rm", "install", "chmod", "chown", "truncate"}
_NETWORK_COMMANDS = {"curl", "wget", "ssh", "scp", "rsync", "git"}

DEFAULT_HIGH_COMMANDS = {
    "sudo", "su", "doas", "eval", "mkfs", "shred", "dd", "shutdown", "reboot", "history",
}
DEFAULT_APPROVAL_COMMANDS = {
    "bash", "sh", "zsh", "python", "python3", "node", "npm", "pytest", "pip", "pip3",
    "make", "cargo", "curl", "wget", "ssh", "scp", "rsync", "rm", "mv", "cp", "chmod",
    "chown", "sed", "tee", "install", "touch", "mkdir", "docker","sudo",
}
DEFAULT_LOW_COMMANDS = {
    "pwd", "ls", "cat", "head", "tail", "grep", "rg", "find", "stat", "wc", "file",
    "which", "git", "echo", "printf", "true", "false", "date", "uname","cd",
}
DEFAULT_HIGH_EVENTS = {
    "recursive_delete", "force_delete", "pipe_to_shell", "network_to_shell",
    "dynamic_command", "workspace_external_path", "eval",
}
DEFAULT_APPROVAL_EVENTS = {
    "redirect_write", "redirect_append", "heredoc", "command_substitution", "source",
    "network_command", "git_mutation", "git_network",
}
DEFAULT_LOW_EVENTS = {"redirect_read"}


@dataclass(frozen=True)
class CommandApprovalRequest:
    command: str
    risk: CommandRisk
    reason: str
    intent: str = ""


@dataclass(frozen=True)
class CommandApprovalDecision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class BashPolicyEvidence:
    policy_key: str
    entry_type: Literal["command", "event"]
    name: str
    source_text: str = ""
    reason: str = ""


@dataclass(frozen=True)
class BashPolicyDecision:
    level: PolicyLevel | Literal["unknown"]
    evidence: tuple[BashPolicyEvidence, ...] = ()
    matched_keys: tuple[str, ...] = ()
    unknown_keys: tuple[str, ...] = ()
    reason: str = ""


Classifier = Callable[[BashPolicyEvidence], Awaitable[PolicyLevel | None]]


class EmptyBashClassificationParams(BaseModel):
    pass


class _BashClassificationSubmission(Tool):
    category = "read"
    params_model = EmptyBashClassificationParams

    def __init__(self, name: str, level: PolicyLevel, sink: Callable[[PolicyLevel], None]) -> None:
        self.name = name
        self._level = level
        self._sink = sink

    def get_schema(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        }

    async def execute(self, params: EmptyBashClassificationParams) -> ToolResult:
        self._sink(self._level)
        return ToolResult(output=f"已提交 Bash 命令名分类：{self._level}")


class SubmitBashLowRisk(_BashClassificationSubmission):
    description = "将当前待分类的 Bash 命令名或规范化策略事件提交到低危表。无参数。"

    def __init__(self, sink: Callable[[PolicyLevel], None]) -> None:
        super().__init__("SubmitBashLowRisk", "low", sink)


class SubmitBashApproval(_BashClassificationSubmission):
    description = "将当前待分类的 Bash 命令名或规范化策略事件提交到审批表。无参数。"

    def __init__(self, sink: Callable[[PolicyLevel], None]) -> None:
        super().__init__("SubmitBashApproval", "approval", sink)


class SubmitBashHighRisk(_BashClassificationSubmission):
    description = "将当前待分类的 Bash 命令名或规范化策略事件提交到高危表并拒绝执行。无参数。"

    def __init__(self, sink: Callable[[PolicyLevel], None]) -> None:
        super().__init__("SubmitBashHighRisk", "high", sink)


class BashPolicyLease:
    """A database-backed expiring lease with a background renewal heartbeat."""

    def __init__(self, store: "BashPolicyStore", lock_key: str, owner_id: str, ttl_seconds: int) -> None:
        self.store = store
        self.lock_key = lock_key
        self.owner_id = owner_id
        self.ttl_seconds = max(3, int(ttl_seconds))
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._heartbeat, name="bash-policy-lease-heartbeat", daemon=True)
        self._thread.start()

    def _heartbeat(self) -> None:
        interval = max(1.0, self.ttl_seconds / 3)
        while not self._stop.wait(interval):
            if not self.store.renew_lease(self.lock_key, self.owner_id, self.ttl_seconds):
                self._lost.set()
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.ttl_seconds / 3) + 1)
            self._thread = None

    def __enter__(self) -> "BashPolicyLease":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()
        self.store.release_lease(self.lock_key, self.owner_id)


class BashPolicyStore:
    """Persistent three-table command/event policy store."""

    TABLES = {"high": "bash_high_risk_commands", "approval": "bash_approval_commands", "low": "bash_low_risk_commands"}

    def __init__(self, db_path: Path | str | None = None) -> None:
        if str(db_path) == ":memory:":
            fd, path = tempfile.mkstemp(prefix="mycodingagent-bash-policy-", suffix=".sqlite3")
            os.close(fd)
            self.db_path = Path(path)
        else:
            self.db_path = Path(db_path).expanduser() if db_path is not None else CONFIG.memory.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, factory=SQLITE_CONNECTION_FACTORY)
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            require_component_schema(
                conn,
                db_path=self.db_path,
                component="bash_policy",
                version=BASH_POLICY_SCHEMA_VERSION,
                owned_tables=tuple(self.TABLES.values()),
            )
            for table in self.TABLES.values():
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("
                    "policy_key TEXT PRIMARY KEY, entry_type TEXT NOT NULL, name TEXT NOT NULL, "
                    "source TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 1.0, "
                    "created_at REAL NOT NULL, updated_at REAL NOT NULL, version_id TEXT NOT NULL DEFAULT '')"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bash_policy_versions ("
                "version_id TEXT PRIMARY KEY, parent_version_id TEXT NOT NULL, status TEXT NOT NULL, "
                "owner_id TEXT NOT NULL, source_session_id TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, "
                "committed_at REAL NOT NULL DEFAULT 0, error_text TEXT NOT NULL DEFAULT '')"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bash_policy_heads (scope TEXT PRIMARY KEY, version_id TEXT NOT NULL, updated_at REAL NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bash_policy_version_entries ("
                "version_id TEXT NOT NULL, policy_key TEXT NOT NULL, level TEXT NOT NULL, entry_type TEXT NOT NULL, "
                "name TEXT NOT NULL, source TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 1.0, "
                "created_at REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(version_id, policy_key))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bash_policy_locks ("
                "lock_key TEXT PRIMARY KEY, owner_id TEXT NOT NULL, acquired_at REAL NOT NULL, "
                "expires_at REAL NOT NULL, heartbeat_at REAL NOT NULL)"
            )
            now = time()
            head = conn.execute("SELECT version_id FROM bash_policy_heads WHERE scope = 'global'").fetchone()
            if head is None:
                version_id = f"bootstrap-{int(now * 1000)}"
                conn.execute(
                    "INSERT INTO bash_policy_versions(version_id, parent_version_id, status, owner_id, created_at, committed_at) VALUES (?, '', 'committed', 'bootstrap', ?, ?)",
                    (version_id, now, now),
                )
                conn.execute("INSERT INTO bash_policy_heads(scope, version_id, updated_at) VALUES ('global', ?, ?)", (version_id, now))
            for level, names in (("high", DEFAULT_HIGH_COMMANDS), ("approval", DEFAULT_APPROVAL_COMMANDS), ("low", DEFAULT_LOW_COMMANDS)):
                self._seed(conn, level, names, "command", "builtin", now, head_version=head[0] if head else version_id)
            for level, names in (("high", DEFAULT_HIGH_EVENTS), ("approval", DEFAULT_APPROVAL_EVENTS), ("low", DEFAULT_LOW_EVENTS)):
                self._seed(conn, level, names, "event", "builtin", now, head_version=head[0] if head else version_id)

    def _seed(self, conn: sqlite3.Connection, level: str, names: set[str], entry_type: str, source: str, now: float, *, head_version: str) -> None:
        table = self.TABLES[level]
        for name in names:
            key = f"{entry_type}:{name}"
            conn.execute(
                f"INSERT OR IGNORE INTO {table}(policy_key, entry_type, name, source, reason, created_at, updated_at, version_id) VALUES (?, ?, ?, ?, '', ?, ?, ?)",
                (key, entry_type, name, source, now, now, head_version),
            )

    def lookup(self, policy_key: str) -> PolicyLevel | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT level FROM ("
                "SELECT 'high' AS level FROM bash_high_risk_commands WHERE policy_key = ? UNION ALL "
                "SELECT 'approval' FROM bash_approval_commands WHERE policy_key = ? UNION ALL "
                "SELECT 'low' FROM bash_low_risk_commands WHERE policy_key = ?"
                ") LIMIT 1",
                (policy_key, policy_key, policy_key),
            ).fetchone()
            if row is not None:
                return str(row[0])  # type: ignore[return-value]
        return None

    def acquire_lease(self, lock_key: str = LOCK_KEY, *, owner_id: str, ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS) -> BashPolicyLease | None:
        now = time()
        expires = now + max(3, int(ttl_seconds))
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO bash_policy_locks(lock_key, owner_id, acquired_at, expires_at, heartbeat_at) VALUES (?, ?, ?, ?, ?)",
                    (lock_key, owner_id, now, expires, now),
                )
            except sqlite3.IntegrityError:
                cursor = conn.execute(
                    "UPDATE bash_policy_locks SET owner_id = ?, acquired_at = ?, expires_at = ?, heartbeat_at = ? "
                    "WHERE lock_key = ? AND expires_at < ?",
                    (owner_id, now, expires, now, lock_key, now),
                )
                if cursor.rowcount != 1:
                    return None
        return BashPolicyLease(self, lock_key, owner_id, ttl_seconds)

    def renew_lease(self, lock_key: str, owner_id: str, ttl_seconds: int) -> bool:
        now = time()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE bash_policy_locks SET expires_at = ?, heartbeat_at = ? "
                "WHERE lock_key = ? AND owner_id = ? AND expires_at >= ?",
                (now + max(3, int(ttl_seconds)), now, lock_key, owner_id, now),
            )
            return cursor.rowcount == 1

    def release_lease(self, lock_key: str, owner_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM bash_policy_locks WHERE lock_key = ? AND owner_id = ?", (lock_key, owner_id))

    def current_version(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT version_id FROM bash_policy_heads WHERE scope = 'global'").fetchone()
            return str(row[0]) if row else ""

    def put(self, policy_key: str, level: PolicyLevel, *, entry_type: str, name: str, source: str, reason: str = "", confidence: float = 1.0) -> None:
        owner_id = f"put-{os.getpid()}-{threading.get_ident()}-{int(monotonic() * 1_000_000)}"
        lease = self.acquire_lease(owner_id=owner_id)
        if lease is None:
            raise sqlite3.OperationalError("bash policy lease is held")
        try:
            lease.start()
            parent_version = self.current_version()
            now = time()
            version_id = f"policy-{os.getpid()}-{threading.get_ident()}-{int(now * 1_000_000)}"
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if lease.lost:
                    raise sqlite3.OperationalError("bash policy lease lost")
                current = conn.execute("SELECT version_id FROM bash_policy_heads WHERE scope = 'global'").fetchone()
                if current is None or str(current[0]) != parent_version:
                    raise sqlite3.OperationalError("bash policy version conflict")
                conn.execute(
                    "INSERT INTO bash_policy_versions(version_id, parent_version_id, status, owner_id, created_at) VALUES (?, ?, 'staging', ?, ?)",
                    (version_id, parent_version, owner_id, now),
                )
                snapshot: dict[str, tuple] = {}
                for snapshot_level, table in self.TABLES.items():
                    rows = conn.execute(
                        f"SELECT policy_key, entry_type, name, source, reason, confidence, created_at, updated_at FROM {table}"
                    ).fetchall()
                    for row in rows:
                        if row[0] != policy_key:
                            snapshot.setdefault(row[0], (snapshot_level, *row[1:]))
                conn.executemany(
                    "INSERT INTO bash_policy_version_entries(version_id, policy_key, level, entry_type, name, source, reason, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(version_id, key, *value) for key, value in snapshot.items()],
                )
                for table in self.TABLES.values():
                    conn.execute(f"DELETE FROM {table} WHERE policy_key = ?", (policy_key,))
                conn.execute(
                    f"INSERT INTO {self.TABLES[level]}(policy_key, entry_type, name, source, reason, confidence, created_at, updated_at, version_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (policy_key, entry_type, name, source, reason, max(0.0, min(1.0, confidence)), now, now, version_id),
                )
                conn.execute("DELETE FROM bash_policy_version_entries WHERE version_id = ? AND policy_key = ?", (version_id, policy_key))
                conn.execute(
                    "INSERT INTO bash_policy_version_entries(version_id, policy_key, level, entry_type, name, source, reason, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (version_id, policy_key, level, entry_type, name, source, reason, max(0.0, min(1.0, confidence)), now, now),
                )
                head_cursor = conn.execute(
                    "UPDATE bash_policy_heads SET version_id = ?, updated_at = ? WHERE scope = 'global' AND version_id = ?",
                    (version_id, now, parent_version),
                )
                if head_cursor.rowcount != 1:
                    raise sqlite3.OperationalError("bash policy head conflict")
                conn.execute("UPDATE bash_policy_versions SET status = 'committed', committed_at = ? WHERE version_id = ?", (now, version_id))
                conn.commit()
        finally:
            lease.stop()
            self.release_lease(LOCK_KEY, owner_id)


class BashPolicyEvaluator:
    """AST evidence extraction, three-table lookup, and serialized unknown classification."""

    def __init__(self, store: BashPolicyStore | None = None, classifier: Classifier | None = None) -> None:
        self.store = store or BashPolicyStore()
        self.classifier = classifier
        self._classification_tasks: dict[str, asyncio.Task[PolicyLevel | None]] = {}
        self._classification_lock = asyncio.Lock()

    def evaluate(self, command: str) -> BashPolicyDecision:
        evidence = extract_policy_evidence(command)
        matched: list[tuple[int, str, BashPolicyEvidence]] = []
        unknown: list[str] = []
        rank = {"low": 0, "approval": 1, "high": 2}
        for item in evidence:
            level = self.store.lookup(item.policy_key)
            if level is None:
                unknown.append(item.policy_key)
            else:
                matched.append((rank[level], level, item))
        if any(level == "high" for _, level, _ in matched):
            level: PolicyLevel | Literal["unknown"] = "high"
        elif unknown:
            level: PolicyLevel | Literal["unknown"] = "unknown"
        elif matched:
            level = max(matched, key=lambda value: value[0])[1]  # type: ignore[assignment]
        else:
            level = "unknown"
        reason = ", ".join(item.reason or item.policy_key for _, _, item in matched) or "存在未分类命令或策略事件"
        return BashPolicyDecision(
            level=level,
            evidence=tuple(evidence),
            matched_keys=tuple(item.policy_key for _, _, item in matched),
            unknown_keys=tuple(dict.fromkeys(unknown)),
            reason=reason,
        )

    async def resolve_unknowns(self, evidence: tuple[BashPolicyEvidence, ...], *, persist: bool = True) -> dict[str, PolicyLevel]:
        if self.classifier is None:
            return {}
        results: dict[str, PolicyLevel] = {}
        async with self._classification_lock:
            tasks: list[tuple[str, asyncio.Task[PolicyLevel | None]]] = []
            for item in evidence:
                if self.store.lookup(item.policy_key) is not None:
                    continue
                task = self._classification_tasks.get(item.policy_key)
                if task is None:
                    task = asyncio.create_task(self._classify_one(item, persist=persist))
                    self._classification_tasks[item.policy_key] = task
                tasks.append((item.policy_key, task))
        for key, task in tasks:
            try:
                level = await task
            except Exception:
                level = None
            if level is not None:
                results[key] = level
        return results

    async def _classify_one(self, item: BashPolicyEvidence, *, persist: bool = True) -> PolicyLevel | None:
        try:
            level = await asyncio.wait_for(self.classifier(item), timeout=30.0) if self.classifier else None
            if level not in {"low", "approval", "high"}:
                level = None
            resolved = level or "approval"
            if persist:
                self.store.put(item.policy_key, resolved, entry_type=item.entry_type, name=item.name, source="classifier_agent", reason=item.reason)
            return resolved
        finally:
            self._classification_tasks.pop(item.policy_key, None)

    def persist_classification(
        self,
        evidence: tuple[BashPolicyEvidence, ...],
        classifications: dict[str, PolicyLevel],
        *,
        user_allowed: bool,
    ) -> None:
        for item in evidence:
            level = classifications.get(item.policy_key)
            if level is None:
                continue
            if user_allowed:
                target: PolicyLevel = "low" if level == "low" else "approval"
            else:
                target = "high" if level == "high" else "approval"
            self.store.put(
                item.policy_key,
                target,
                entry_type=item.entry_type,
                name=item.name,
                source="classifier_agent",
                reason=item.reason,
            )

    def has_pending(self, policy_keys: tuple[str, ...]) -> bool:
        return any(key in self._classification_tasks for key in policy_keys)


def extract_policy_evidence(command: str) -> tuple[BashPolicyEvidence, ...]:
    """Extract command names and normalized AST policy events."""
    if not command.strip():
        return ()
    source = command.encode("utf-8")
    try:
        tree = get_parser("bash").parse(source)
    except Exception:
        return (BashPolicyEvidence("event:unknown_command", "event", "unknown_command", command, "Shell 解析器不可用"),)
    if tree.root_node.has_error:
        return (BashPolicyEvidence("event:unknown_command", "event", "unknown_command", command, "无法安全解析 Shell 语法"),)
    items: list[BashPolicyEvidence] = []
    names: list[str] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        text = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
        if node.type in {"file_redirect", "heredoc_redirect"}:
            if re.search(r"(^|\s)(>|>>|<>|&>)", text):
                event = "redirect_append" if ">>" in text else "redirect_write"
                items.append(BashPolicyEvidence(f"event:{event}", "event", event, text, "Shell 输出重定向"))
            elif node.type == "heredoc_redirect":
                items.append(BashPolicyEvidence("event:heredoc", "event", "heredoc", text, "Shell heredoc"))
            else:
                items.append(BashPolicyEvidence("event:redirect_read", "event", "redirect_read", text, "Shell 输入重定向"))
        if node.type == "command":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                if "$" in name or "`" in name:
                    items.append(BashPolicyEvidence("event:dynamic_command", "event", "dynamic_command", name, "动态命令名"))
                elif name:
                    command_name = name.rsplit("/", 1)[-1]
                    names.append(command_name)
                    items.append(BashPolicyEvidence(f"command:{command_name}", "command", command_name, text))
        stack.extend(node.named_children)
    lowered = command.lower()
    delete_match = re.search(r"\brm\b[^|;&]*-[a-zA-Z]*[rf][a-zA-Z]*[^|;&]*\s(\S+)", lowered)
    if delete_match:
        target = delete_match.group(1).strip("'\"")
        if target in {"/", "/workspace", "/root", "/etc", "/usr", "/var", "/home"} or target.startswith(("/dev/", "/proc/", "/sys/")):
            items.append(BashPolicyEvidence("event:recursive_delete", "event", "recursive_delete", command, "递归或强制删除系统目录、工作区根目录或设备"))
    if re.search(r"\b(curl|wget)\b[^|;&]*\|\s*(ba)?sh\b", lowered):
        items.append(BashPolicyEvidence("event:network_to_shell", "event", "network_to_shell", command, "网络内容直接交给 Shell"))
    if re.search(r"\beval\b", lowered):
        items.append(BashPolicyEvidence("event:eval", "event", "eval", command, "动态执行 Shell 内容"))
    if re.search(r"\b(git)\s+(push|clone|fetch|pull)\b", lowered):
        items.append(BashPolicyEvidence("event:git_network", "event", "git_network", command, "Git 网络操作"))
    if re.search(r"\b(git)\s+(add|commit|checkout|switch|merge|rebase)\b", lowered):
        items.append(BashPolicyEvidence("event:git_mutation", "event", "git_mutation", command, "Git 状态修改"))
    if not items or not names:
        items.append(BashPolicyEvidence("event:unknown_command", "event", "unknown_command", command, "无法识别命令"))
    return tuple(dict((item.policy_key, item) for item in items).values())


def classify_command(command: str) -> tuple[CommandRisk, str]:
    """Return the risk level for a shell command plus a human-readable reason.

    Only flags operations that are hard to undo or reach outside the workspace. Ordinary
    reads and writes stay unflagged -- the Docker sandbox and read-before-write rules
    already cover those, and prompting on every write would make the agent unusable.
    """
    normalized = " ".join(command.split())
    if not normalized:
        return "normal", ""
    lowered = normalized.lower()
    for pattern, reason in _DANGEROUS_PATTERNS:
        if re.search(pattern, lowered):
            return "dangerous", reason
    match = _OUT_OF_SANDBOX_PATTERN.search(normalized)
    if match:
        return "dangerous", f"操作指向工作区之外的路径：{match.group(2)}"
    return "normal", ""


def analyze_command(command: str) -> tuple[ExecutionRisk, str]:
    """Classify shell semantics for the execution gate.

    Regex rules retain precise destructive-operation messages while the syntax tree
    prevents malformed or indirect shell from being mistaken for a read-only call.
    """
    legacy_risk, legacy_reason = classify_command(command)
    if legacy_risk == "dangerous":
        return "dangerous", legacy_reason
    if not command.strip():
        return "read", ""
    try:
        parser = get_parser("bash")
        tree = parser.parse(command.encode("utf-8"))
    except Exception as exc:
        return "unknown", f"Shell 解析器不可用：{exc}"
    if tree.root_node.has_error:
        return "unknown", "无法安全解析 Shell 语法"

    command_names: list[str] = []
    has_write_redirect = False
    has_dynamic_command = False
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in {"file_redirect", "heredoc_redirect"}:
            text = command.encode("utf-8")[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
            if re.search(r"(^|\s)(>|>>|<>|&>)", text):
                has_write_redirect = True
        if node.type == "command":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = command.encode("utf-8")[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", errors="ignore"
                ).strip()
                if "$" in name or "`" in name:
                    has_dynamic_command = True
                elif name:
                    command_names.append(name.rsplit("/", 1)[-1])
        stack.extend(node.named_children)
    if has_dynamic_command or not command_names:
        return "unknown", "命令目标是动态值或无法识别"
    if has_write_redirect:
        return "write", "Shell 输出重定向到文件"
    if any(name in _NETWORK_COMMANDS for name in command_names):
        if all(name == "git" for name in command_names):
            lowered = " ".join(command.lower().split())
            if re.search(r"\bgit\s+(status|diff|log|show|branch\s+--show-current)\b", lowered):
                return "read", ""
        return "network", "命令可能访问网络或远程系统"
    if any(name in _WRITE_COMMANDS for name in command_names):
        return "write", "命令可能修改工作区文件"
    if all(name in _READ_COMMANDS for name in command_names):
        return "read", ""
    return "process", "命令会启动无法静态判断副作用的进程"


class CommandApprovalHook:
    """Default hook: allow everything. Keeps non-interactive callers unchanged."""

    async def approve(self, request: CommandApprovalRequest) -> CommandApprovalDecision:
        return CommandApprovalDecision(allowed=True, reason="自动批准")


@dataclass
class CLICommandApprovalHook(CommandApprovalHook):
    coordinator: TerminalInput = field(default_factory=SharedTerminalInput)
    max_command_chars: int = 2000

    async def approve(self, request: CommandApprovalRequest) -> CommandApprovalDecision:
        command_text = request.command
        if len(command_text) > self.max_command_chars:
            command_text = command_text[: self.max_command_chars] + "\n... <命令已截断>"
        render_command_approval_request(
            command=command_text,
            reason=request.reason,
            intent=request.intent,
            dangerous=request.risk == "dangerous",
        )
        try:
            answer = await self.coordinator.read_choice(
                "允许执行该命令吗？[y/N]：", allowed={"y", "yes"}
            )
        except TerminalCancelled:
            return CommandApprovalDecision(allowed=False, reason="用户取消")
        if answer in {"y", "yes"}:
            return CommandApprovalDecision(allowed=True, reason="用户批准")
        return CommandApprovalDecision(allowed=False, reason="用户拒绝")
