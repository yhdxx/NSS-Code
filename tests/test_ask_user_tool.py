from __future__ import annotations

import asyncio

from mycodingagent.tool_runtime.ask_user import AskUser


def test_ask_user_returns_terminal_input(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "yhdxx")
    tool = AskUser()

    result = asyncio.run(
        tool.execute(
            tool.params_model(
                query="你的 GitHub 用户名是什么？",
                intent="需要确认账号，避免猜测用户名",
            )
        )
    )

    output = capsys.readouterr().out
    assert result.output == "yhdxx"
    assert "[需要用户输入]" in output
    assert "需要确认账号" in output
    assert "你的 GitHub 用户名是什么？" in output


def test_ask_user_renders_optional_choices(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "2")
    tool = AskUser()

    result = asyncio.run(
        tool.execute(
            tool.params_model(
                query="请选择要查看的仓库范围",
                choice="1. 公开仓库\n2. 私有仓库\n3. 全部仓库",
                intent="需要用户选择仓库范围",
            )
        )
    )

    output = capsys.readouterr().out
    assert result.output == "2"
    assert "请选择要查看的仓库范围" in output
    assert "1. 公开仓库" in output
    assert "2. 私有仓库" in output
    assert "3. 全部仓库" in output


def test_ask_user_schema_has_optional_choice_and_required_intent():
    schema = AskUser().get_schema()["input_schema"]

    assert "query" in schema["properties"]
    assert "choice" in schema["properties"]
    assert "intent" in schema["properties"]
    assert "query" in schema["required"]
    assert "intent" in schema["required"]
    assert "choice" not in schema["required"]
