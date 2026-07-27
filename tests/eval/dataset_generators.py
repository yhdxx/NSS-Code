from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DATASET_DIR = Path("tests/eval/datasets")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def generate_all(output_dir: Path = DATASET_DIR) -> dict[str, int]:
    datasets = {
        "multi_agent_tasks.jsonl": generate_multi_agent_tasks(),
        "context_virtualization_cases.jsonl": generate_context_virtualization_cases(),
        "long_term_workflow_cases.jsonl": generate_long_term_workflow_cases(),
        "skill_router_500_cases.jsonl": generate_skill_router_cases(),
        "capability_router_cases.jsonl": generate_capability_router_cases(),
        "recovery_cases.jsonl": generate_recovery_cases(),
    }
    counts: dict[str, int] = {}
    for name, rows in datasets.items():
        write_jsonl(output_dir / name, rows)
        counts[name] = len(rows)
    return counts


def generate_multi_agent_tasks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    small_specs = [
        ("add", "calculator.py", "def add(a, b):\n    return a - b\n", "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"),
        ("slug", "text_utils.py", "def slugify(text):\n    return text.replace(' ', '_')\n", "from text_utils import slugify\n\ndef test_slugify():\n    assert slugify('Hello World') == 'hello-world'\n"),
        ("discount", "pricing.py", "def apply_discount(price, pct):\n    return price + price * pct\n", "from pricing import apply_discount\n\ndef test_discount():\n    assert apply_discount(100, 0.2) == 80\n"),
        ("email", "validators.py", "def is_email(value):\n    return '@' in value\n", "from validators import is_email\n\ndef test_email():\n    assert is_email('a@example.com')\n    assert not is_email('@missing-name')\n"),
        ("csv", "csv_tools.py", "def split_csv(line):\n    return line.split(';')\n", "from csv_tools import split_csv\n\ndef test_split_csv():\n    assert split_csv('a,b,c') == ['a', 'b', 'c']\n"),
        ("stats", "stats.py", "def average(values):\n    return sum(values) / len(values)\n", "from stats import average\n\ndef test_average_empty():\n    assert average([]) == 0\n"),
        ("auth", "auth.py", "def can_edit(user):\n    return user.get('role') == 'viewer'\n", "from auth import can_edit\n\ndef test_can_edit():\n    assert can_edit({'role': 'admin'})\n    assert not can_edit({'role': 'viewer'})\n"),
        ("format", "formatters.py", "def user_label(user):\n    return user['name']\n", "from formatters import user_label\n\ndef test_user_label():\n    assert user_label({'name': 'Ada', 'role': 'admin'}) == 'Ada (admin)'\n"),
        ("date", "dates.py", "def iso_year(date):\n    return date.split('/')[2]\n", "from dates import iso_year\n\ndef test_iso_year():\n    assert iso_year('2026-07-27') == '2026'\n"),
        ("inventory", "inventory.py", "def in_stock(item):\n    return item['qty'] > 10\n", "from inventory import in_stock\n\ndef test_in_stock():\n    assert in_stock({'qty': 1})\n    assert not in_stock({'qty': 0})\n"),
        ("normalize", "names.py", "def normalize_name(name):\n    return name\n", "from names import normalize_name\n\ndef test_normalize_name():\n    assert normalize_name('  ADA LOVELACE ') == 'Ada Lovelace'\n"),
        ("ratio", "metrics.py", "def ratio(a, b):\n    return a / b\n", "from metrics import ratio\n\ndef test_ratio_zero():\n    assert ratio(5, 0) == 0\n"),
    ]
    for index, (slug, file_name, source, test_source) in enumerate(small_specs, start=1):
        rows.append({
            "case_id": f"ma_small_{index:02d}_{slug}",
            "category": "multi_agent",
            "project_size": "small",
            "expected_mode": "direct",
            "input_task": "修复这个小型 Python 项目的失败测试，只做必要修改并运行 pytest。",
            "files": {file_name: source, f"test_{file_name}": test_source},
            "test_command": "python3 -m pytest -q",
            "success_criteria": ["hidden_tests_pass", "minimal_file_changes"],
        })

    medium_features = [
        "orders", "users", "payments", "notifications", "reports", "inventory",
        "shipping", "auth", "billing", "audit", "search", "profiles",
    ]
    for index, feature in enumerate(medium_features, start=1):
        rows.append({
            "case_id": f"ma_medium_{index:02d}_{feature}",
            "category": "multi_agent",
            "project_size": "medium",
            "expected_mode": "multi_agent",
            "input_task": (
                f"在中规模 Python 项目中完成 {feature} 模块的跨层修复：保持 public API 兼容，"
                "更新 service/repository/validator 链路，并运行全部测试。"
            ),
            "files": _medium_project_files(feature),
            "test_command": "python3 -m pytest -q",
            "success_criteria": ["hidden_tests_pass", "no_unrelated_rewrite", "cross_module_behavior_preserved"],
        })
    return rows


def _medium_project_files(feature: str) -> dict[str, str]:
    return {
        "app/__init__.py": "",
        f"app/{feature}_repo.py": "DATA = [{'name': 'Ada', 'role': 'admin'}]\n\ndef list_items():\n    return DATA\n",
        f"app/{feature}_service.py": (
            f"from .{feature}_repo import list_items\n\n"
            "def labels():\n"
            "    return [item['name'] for item in list_items()]\n"
        ),
        f"app/{feature}_validator.py": "def is_valid(item):\n    return bool(item.get('name'))\n",
        f"test_{feature}.py": (
            f"from app.{feature}_service import labels\n\n"
            "def test_labels_include_role():\n"
            "    assert labels() == ['Ada (admin)']\n"
        ),
    }


def generate_context_virtualization_cases() -> list[dict[str, Any]]:
    rows = []
    for index in range(1, 13):
        early_fact = f"ARCH_CONSTRAINT_{index:02d}: 禁止修改 billing 模块，所有适配必须放在 adapter_{index:02d}.py。"
        messages = [
            {"role": "user", "content": f"请记住这个项目约束：{early_fact}"},
            {"role": "assistant", "content": "已记录该项目约束。"},
        ]
        for turn in range(1, 141):
            messages.append({"role": "user", "content": f"中间无关需求 {turn}: 简短确认即可。"})
            messages.append({"role": "assistant", "content": f"已确认中间需求 {turn}。"})
            if turn % 10 == 0:
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"tool_{index}_{turn}",
                    "content": "LOG\n" + ("irrelevant tool output\n" * 120),
                })
        rows.append({
            "case_id": f"ctx_{index:02d}",
            "category": "context_virtualization",
            "early_fact": early_fact,
            "messages": messages,
            "final_query": "请回答会话初期我提出的项目约束是什么？必须完整说出禁止修改哪个模块以及适配文件名。",
            "expected_answer_contains": ["billing", f"adapter_{index:02d}.py"],
            "modes": ["raw", "virtualized", "summary_baseline", "recent_only"],
            "hot_windows": [3, 5, 10],
        })
    return rows


def generate_long_term_workflow_cases() -> list[dict[str, Any]]:
    workflows = [
        ("large_file_split", "大文件拆分时先一次性定位所有边界，再批量写入，避免逐模块重复读取。"),
        ("cross_module_refactor", "跨模块重构先跑现有测试，再修改公共接口，最后跑完整回归。"),
        ("api_chain_change", "API 修改前先确认 route、service、repository、test 的调用链。"),
        ("frontend_state_flow", "前端修改先定位状态流和事件入口，再改组件。"),
        ("batch_recovery", "已有多个 context_id 时优先 BatchRecoverContext 批量恢复，不要逐条恢复。"),
        ("skill_candidate", "同类有效 workflow 重复出现后生成 skill_candidate，等待用户确认沉淀。"),
    ]
    rows = []
    for index, (name, workflow) in enumerate(workflows, start=1):
        rows.append({
            "case_id": f"ltm_{index:02d}_{name}",
            "category": "long_term_memory_workflow",
            "workflow_name": name,
            "expected_workflow": workflow,
            "learning_sessions": [
                {"user": f"这类任务以后要注意：{workflow}", "assistant": "已理解，本次会按该流程执行。"},
                {"user": f"你刚才又走偏了，请记住：{workflow}", "assistant": "已纠正流程。"},
                {"user": f"再次强调，正确 workflow 是：{workflow}", "assistant": "已确认正确 workflow。"},
            ],
            "validation_query": f"现在处理一个相似任务，请说明你会采用什么 workflow。场景：{name}",
            "expected_answer_contains": [workflow[:12]],
        })
    return rows


def generate_skill_router_cases() -> list[dict[str, Any]]:
    domains = {
        "frontend": ["组件重构", "表单交互", "移动端适配", "可访问性检查", "设计系统对齐", "页面性能", "状态管理", "路由组织", "图表界面", "后台列表"],
        "backend": ["API 设计", "数据库迁移", "缓存策略", "认证鉴权", "日志治理", "异常处理", "任务队列", "数据校验", "接口测试", "权限模型"],
        "content": ["公众号写作", "小红书文案", "视频脚本", "SEO 改写", "商品文案", "课程大纲", "演讲稿", "新闻改写", "标题优化", "营销邮件"],
        "data": ["CSV 清洗", "SQL 分析", "指标解释", "报表生成", "可视化建议", "漏斗分析", "留存分析", "异常检测", "数据字典", "口径治理"],
        "agent": ["上下文恢复", "工具审计", "多智能体规划", "长期记忆", "Skill 路由", "MCP 能力发现", "沙箱执行", "Prompt 调试", "会话恢复", "能力评测"],
        "devops": ["Docker 构建", "CI 配置", "部署脚本", "日志采集", "资源限制", "环境变量", "依赖升级", "回滚流程", "健康检查", "监控告警"],
    }
    skills: list[dict[str, Any]] = []
    for domain, capabilities in domains.items():
        for cap in capabilities:
            for variant in range(1, 10):
                skills.append({
                    "name": f"{domain}_{cap}_{variant}",
                    "description": f"用于处理{domain}领域的{cap}问题，关注流程、约束、验收标准和常见错误。变体{variant}覆盖相邻但不完全相同的任务。",
                })
    while len(skills) < 520:
        idx = len(skills) + 1
        skills.append({
            "name": f"misc_capability_{idx:03d}",
            "description": f"通用辅助能力 {idx}，用于低频工程、写作或数据整理场景，避免与主测试目标完全重复。",
        })
    queries: list[dict[str, Any]] = []
    query_id = 1
    for domain, capabilities in domains.items():
        for cap in capabilities[:8]:
            expected = [skill["name"] for skill in skills if skill["name"].startswith(f"{domain}_{cap}_")]
            queries.append({
                "query_id": f"skill_q_{query_id:03d}",
                "query": f"我需要处理{cap}相关任务，请推荐最合适的工作流 skill。",
                "domain": domain,
                "expected_skill_names": expected,
                "acceptable_related_skill_names": [skill["name"] for skill in skills if skill["name"].startswith(f"{domain}_")],
            })
            query_id += 1
    while len(queries) < 100:
        cap = "上下文恢复" if len(queries) % 2 == 0 else "数据库迁移"
        domain = "agent" if cap == "上下文恢复" else "backend"
        expected = [skill["name"] for skill in skills if skill["name"].startswith(f"{domain}_{cap}_")]
        queries.append({
            "query_id": f"skill_q_{query_id:03d}",
            "query": f"针对{cap}场景选择标准 skill。",
            "domain": domain,
            "expected_skill_names": expected,
            "acceptable_related_skill_names": [skill["name"] for skill in skills if skill["name"].startswith(f"{domain}_")],
        })
        query_id += 1
    return [{"case_id": "skill_router_500", "category": "skill_router", "skills": skills[:520], "queries": queries[:100]}]


def generate_capability_router_cases() -> list[dict[str, Any]]:
    capabilities = [
        ("file_read", "读取当前项目 README 并总结", "ReadFile"),
        ("file_search", "搜索所有调用 BatchRecoverContext 的地方", "Grep"),
        ("shell", "运行 pytest 验证测试", "Bash"),
        ("skill", "把项目经历改成简历责任描述", "Skill"),
        ("mcp", "查看 GitHub issue 列表", "MCP"),
        ("memory", "恢复之前虚拟化的工具输出", "BatchRecoverContext"),
    ]
    rows = []
    for index in range(20):
        name, query, expected = capabilities[index % len(capabilities)]
        rows.append({
            "case_id": f"cap_{index + 1:02d}_{name}",
            "category": "capability_router",
            "query": query,
            "expected_capability": expected,
        })
    return rows


def generate_recovery_cases() -> list[dict[str, Any]]:
    rows = []
    for index in range(1, 11):
        context_id = f"ctx_eval_{index:02d}"
        secret = f"RECOVERY_SECRET_{index:02d}=VALUE-{9000 + index}"
        rows.append({
            "case_id": f"rec_{index:02d}",
            "category": "recovery",
            "context_id": context_id,
            "virtualized_tool_metadata": {
                "tool_name": "ReadFile",
                "intent": "读取大型配置文件以确认隐藏配置值",
                "context_id": context_id,
                "recover": f"Use BatchRecoverContext with this exact context_id in items: {context_id}",
            },
            "stored_output": ("prefix\n" * 200) + secret + "\n" + ("suffix\n" * 200),
            "query": "请恢复历史工具输出并回答隐藏配置值。",
            "expected_answer_contains": [secret],
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate real API eval datasets.")
    parser.add_argument("--output-dir", default=str(DATASET_DIR))
    args = parser.parse_args()
    counts = generate_all(Path(args.output_dir))
    print(json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

