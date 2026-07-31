from __future__ import annotations  # 启用未来版本语法特性。

from pathlib import Path  # 导入当前模块需要的依赖。
from threading import Lock


class FileStateCache:  # 定义用于封装相关状态和行为的类。
    # 记录哪些文件已经被读取过，用于强制“先读后改”。
    # 缓存内容结构为 { absolute_path: (content, mtime_ns) }。
    # `EditFile` 和 `WriteFile` 会在执行前检查该缓存。

    def __init__(self) -> None:  # 定义函数，封装可复用逻辑。
        self._cache: dict[str, tuple[str, int]] = {}  # 保存配置值或中间计算结果。
        self._lock = Lock()

    def record(self, path: str, content: str, mtime_ns: int) -> None:  # 定义函数，封装可复用逻辑。
        # 在成功读取文件后记录内容和修改时间。
        with self._lock:
            self._cache[path] = (content, mtime_ns)  # 保存配置值或中间计算结果。

    def has_read(self, path: str) -> bool:
        with self._lock:
            return path in self._cache

    def get_state(self, path: str) -> tuple[str, int] | None:
        with self._lock:
            return self._cache.get(path)

    def to_dict(self) -> dict:
        with self._lock:
            items = [
                {"path": path, "content": content, "mtime_ns": mtime_ns}
                for path, (content, mtime_ns) in self._cache.items()
            ]
        return {"files": items}

    def load_dict(self, data: dict) -> None:
        files = data.get("files", []) if isinstance(data, dict) else []
        restored: dict[str, tuple[str, int]] = {}
        for item in files:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            content = item.get("content", "")
            mtime_ns = item.get("mtime_ns")
            if not isinstance(path, str) or not isinstance(content, str) or not isinstance(mtime_ns, int):
                continue
            restored[path] = (content, mtime_ns)
        with self._lock:
            self._cache = restored

    def is_stale(self, path: str) -> bool:
        with self._lock:
            entry = self._cache.get(path)
        if entry is None:
            return False
        _, cached_mtime_ns = entry
        try:
            current_mtime_ns = Path(path).stat().st_mtime_ns
        except OSError:
            return True
        return current_mtime_ns != cached_mtime_ns

    def check(self, path: str) -> tuple[bool, str]:  # 定义函数，封装可复用逻辑。
        # 检查文件是否允许被编辑或写入；返回 `(ok, error_message)`。
        with self._lock:
            entry = self._cache.get(path)  # 保存配置值或中间计算结果。
        if entry is None:  # 根据条件决定是否执行后续分支。
            return False, "错误：尚未读取该文件，请先读取再编辑。"  # 返回当前函数的处理结果。

        _, cached_mtime_ns = entry  # 保存配置值或中间计算结果。
        try:  # 开始可能抛出异常的保护代码块。
            current_mtime_ns = Path(path).stat().st_mtime_ns  # 保存配置值或中间计算结果。
        except OSError:  # 捕获并处理指定异常。
            # File may have been deleted; allow the write to proceed
            # (WriteFile will create it, EditFile will fail on its own).
            return True, ""  # 返回当前函数的处理结果。

        if current_mtime_ns != cached_mtime_ns:  # 根据条件决定是否执行后续分支。
            return False, "错误：文件在上次读取后已被修改，请重新读取再编辑。"  # 返回当前函数的处理结果。

        return True, ""  # 返回当前函数的处理结果。

    def update(self, path: str) -> None:  # 定义函数，封装可复用逻辑。
        # 在成功编辑或写入后刷新缓存条目。
        try:  # 开始可能抛出异常的保护代码块。
            p = Path(path)  # 保存配置值或中间计算结果。
            content = p.read_text(encoding="utf-8")  # 保存配置值或中间计算结果。
            mtime_ns = p.stat().st_mtime_ns  # 保存配置值或中间计算结果。
            with self._lock:
                self._cache[path] = (content, mtime_ns)  # 保存配置值或中间计算结果。
        except OSError:  # 捕获并处理指定异常。
            # If we can't read it back, just remove the stale entry.
            with self._lock:
                self._cache.pop(path, None)  # 执行当前步骤的业务逻辑。


def file_state_paths(snapshot: dict) -> list[str]:
    files = snapshot.get("files", []) if isinstance(snapshot, dict) else []
    return [
        item["path"]
        for item in files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
