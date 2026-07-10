# 本模块用于 agent 内部的文件读取缓存。

from __future__ import annotations  # 启用未来版本语法特性。

import threading  # 导入当前模块需要的依赖。


class FileCache:  # 定义用于封装相关状态和行为的类。
    def __init__(self) -> None:  # 定义函数，封装可复用逻辑。
        self._store: dict[str, str] = {}  # 保存配置值或中间计算结果。
        self._lock = threading.Lock()  # 保存配置值或中间计算结果。

    def get(self, path: str) -> str | None:  # 定义函数，封装可复用逻辑。
        with self._lock:  # 使用上下文管理器管理资源生命周期。
            return self._store.get(path)  # 返回当前函数的处理结果。


    def put(self, path: str, content: str) -> None:  # 定义函数，封装可复用逻辑。
        with self._lock:  # 使用上下文管理器管理资源生命周期。
            self._store[path] = content  # 保存配置值或中间计算结果。


    def invalidate(self, path: str) -> None:  # 定义函数，封装可复用逻辑。
        with self._lock:  # 使用上下文管理器管理资源生命周期。
            self._store.pop(path, None)  # 执行当前步骤的业务逻辑。


    def clear(self) -> None:  # 定义函数，封装可复用逻辑。
        with self._lock:  # 使用上下文管理器管理资源生命周期。
            self._store.clear()  # 执行当前步骤的业务逻辑。


    def __len__(self) -> int:  # 定义函数，封装可复用逻辑。
        with self._lock:  # 使用上下文管理器管理资源生命周期。
            return len(self._store)  # 返回当前函数的处理结果。
