from __future__ import annotations

__all__ = ["SkillRuntime"]


def __getattr__(name: str):
    if name == "SkillRuntime":
        from skills.runtime import SkillRuntime

        return SkillRuntime
    raise AttributeError(name)
