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
        "context_compression_100k_cases.jsonl": generate_context_compression_100k_cases(),
        "code_general_tasks.jsonl": generate_code_general_tasks(),
        "context_virtualization_cases.jsonl": generate_context_virtualization_cases(),
        "runtime_context_virtualization_cases.jsonl": generate_runtime_context_virtualization_cases(),
        "long_term_workflow_cases.jsonl": generate_long_term_workflow_cases(),
        "skill_router_500_cases.jsonl": generate_skill_router_cases(),
        "capability_router_cases.jsonl": generate_capability_router_cases(),
        "recovery_cases.jsonl": generate_recovery_cases(),
        "capability_routing_1200_cases.jsonl": generate_capability_routing_1200_cases(),
        "prefix_cache_cases.jsonl": generate_prefix_cache_cases(),
    }
    counts: dict[str, int] = {}
    for name, rows in datasets.items():
        write_jsonl(output_dir / name, rows)
        counts[name] = len(rows)
    return counts


def generate_context_compression_100k_cases() -> list[dict[str, Any]]:
    cases = [
        ("early_tool_fact", "V100_TOOL", "ledger_core", "ledger_adapter.py"),
        ("early_user_constraint", "V100_RULE", "auth_core", "auth_adapter.py"),
        ("topic_return", "V100_TOPIC", "pricing_core", "pricing_adapter.py"),
        ("historical_error", "V100_ERROR", "payment_core", "payment_adapter.py"),
    ]
    return [
        {
            "case_id": f"ctx100k_{index:02d}_{category}",
            "category": category,
            "initial_user": (
                f"Record the early engineering constraint for {category}; preserve exact identifiers for later recall."
            ),
            "critical_evidence": (
                f"CRITICAL_RECORD code={code} forbidden_module={module} adapter_path={adapter} "
                f"case={index:02d} category={category}."
            ),
            "tool_name": "ReadFile",
            "tool_arguments": {"path": f"/workspace/evidence/{category}_{index:02d}.txt", "intent": "load early benchmark evidence"},
            "tool_output": (
                f"CRITICAL_RECORD code={code} forbidden_module={module} adapter_path={adapter} "
                f"case={index:02d} category={category}."
            ),
            "filler_turn_count": 36,
            "large_noise_turns": [6, 12, 18, 24, 30, 36],
            "noise_unit": f"ctx100k_noise_{index:02d}",
            "noise_line_count": 750,
            "requires_recoverable_tool_output": True,
            "expected_answer_contains": [code, module, adapter],
            "final_query": (
                "Return the exact early record code, forbidden module, and adapter path in one sentence. "
                "Use recovery only when the evidence is no longer visible."
            ),
            "target_ratio": 0.90,
            "compression_full_history": True,
        }
        for index, (category, code, module, adapter) in enumerate(cases, start=1)
    ]


def generate_runtime_context_virtualization_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    categories = (
        ["long_distance_fact"] * 10
        + ["large_tool_output"] * 10
        + ["topic_return"] * 5
        + ["rollover_pressure"] * 5
    )
    for index, category in enumerate(categories, start=1):
        record_code = f"VIRT_KEY_{index:03d}"
        adapter = f"adapter_{index:03d}.py"
        module = f"billing_{index:03d}"
        critical_line = (
            f"CRITICAL_RECORD case={index:03d} code={record_code} "
            f"forbid_module={module} adapter={adapter} checksum=ctx-{index:03d}-stable"
        )
        rows.append({
            "case_id": f"runtime_ctx_{index:03d}_{category}",
            "category": category,
            "initial_user": (
                f"Please inspect the hidden evidence record for case {index:03d}. "
                "Do not repeat its values unless I ask later."
            ),
            "tool_name": "ReadFile",
            "tool_arguments": {
                "path": f"/workspace/evidence/case_{index:03d}.txt",
                "intent": "load hidden virtualization benchmark evidence",
            },
            "tool_output": _hidden_evidence_blob(index, critical_line),
            "filler_turn_count": 32 + (index % 6),
            "large_noise_turns": [8, 16, 24, 32],
            "noise_unit": f"noise_stream_{index:03d}",
            "final_query": (
                "Earlier in this conversation there was a hidden evidence tool output. "
                "Recover it if it is not fully visible. What are the exact record code, "
                "forbidden module, and adapter path? Answer in one concise sentence."
            ),
            "expected_answer_contains": [record_code, module, adapter],
            "requires_recoverable_tool_output": True,
            "success_criteria": [
                "answers_hidden_tool_output_anchors",
                "uses_recovery_when_context_virtualized",
                "does_not_recover_when_raw_context_is_sufficient",
            ],
        })
    return rows


def _hidden_evidence_blob(index: int, critical_line: str) -> str:
    prefix = "\n".join(
        f"preface_line_{index:03d}_{line:03d}: ordinary operational log with no benchmark answer."
        for line in range(8)
    )
    suffix = "\n".join(
        f"suffix_line_{index:03d}_{line:03d}: unrelated diagnostic detail."
        for line in range(25)
    )
    return f"{critical_line}\n{prefix}\n{suffix}\n"


def generate_code_general_tasks() -> list[dict[str, Any]]:
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
            "case_id": f"code_small_{index:02d}_{slug}",
            "category": "code_general",
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
            "case_id": f"code_medium_{index:02d}_{feature}",
            "category": "code_general",
            "project_size": "medium",
            "expected_mode": "code",
            "input_task": (
                f"在中规模 Python 项目中完成 {feature} 模块的跨层修复：保持 public API 兼容，"
                "更新 service/repository/validator 链路，并运行全部测试。"
            ),
            "files": _medium_project_files(feature),
            "test_command": "python3 -m pytest -q",
            "success_criteria": ["hidden_tests_pass", "no_unrelated_rewrite", "cross_module_behavior_preserved"],
        })
    large_features = [
        "vip_tax", "shipping_fee", "payment_capture", "inventory_allocation", "reporting_refunds", "profile_labels",
    ]
    for index, feature in enumerate(large_features, start=1):
        rows.append({
            "case_id": f"code_large_{index:02d}_{feature}",
            "category": "code_general",
            "project_size": "large",
            "expected_mode": "code",
            "input_task": (
                "在大规模 Python 项目中完成跨模块业务修复：先理解 domain/repository/service/api/test 调用链，"
                f"修复 {feature} 场景，保持 public API 兼容，不重写无关模块，并运行全部测试。"
            ),
            "files": _large_project_files(feature),
            "test_command": "python3 -m pytest -q",
            "success_criteria": [
                "hidden_tests_pass",
                "no_unrelated_rewrite",
                "cross_module_behavior_preserved",
                "large_project_call_chain_understood",
            ],
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


def _large_project_files(feature: str) -> dict[str, str]:
    base = {
        "app/__init__.py": "",
        "app/domain/__init__.py": "",
        "app/domain/models.py": (
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class Customer:\n"
            "    id: str\n"
            "    name: str\n"
            "    tier: str\n"
            "    region: str\n\n"
            "@dataclass\n"
            "class OrderItem:\n"
            "    sku: str\n"
            "    qty: int\n"
            "    price: float\n\n"
            "@dataclass\n"
            "class Payment:\n"
            "    order_id: str\n"
            "    amount: float\n"
            "    status: str\n"
        ),
        "app/domain/policies.py": (
            "def vip_discount(customer):\n"
            "    return 0.10 if customer.tier == 'vip' else 0.0\n\n"
            "def tax_rate(customer):\n"
            "    return 0.10 if customer.region == 'domestic' else 0.0\n\n"
            "def free_shipping_threshold(customer):\n"
            "    return 100 if customer.tier == 'vip' else 200\n"
        ),
        "app/repositories/__init__.py": "",
        "app/repositories/customers.py": (
            "from app.domain.models import Customer\n\n"
            "CUSTOMERS = {\n"
            "    'c1': Customer(id='c1', name='Ada', tier='vip', region='domestic'),\n"
            "    'c2': Customer(id='c2', name='Grace', tier='standard', region='domestic'),\n"
            "}\n\n"
            "def get_customer(customer_id):\n"
            "    return CUSTOMERS[customer_id]\n"
        ),
        "app/repositories/inventory.py": (
            "STOCK = {'sku-1': 5, 'sku-2': 0}\n\n"
            "def available(sku):\n"
            "    return STOCK.get(sku, 0)\n\n"
            "def reserve(sku, qty):\n"
            "    STOCK[sku] = STOCK.get(sku, 0)\n"
            "    return STOCK[sku]\n"
        ),
        "app/repositories/orders.py": (
            "from app.domain.models import OrderItem\n\n"
            "ORDERS = {\n"
            "    'o1': {'order_id': 'o1', 'customer_id': 'c1', 'items': [OrderItem('sku-1', 2, 100.0)]},\n"
            "    'o2': {'order_id': 'o2', 'customer_id': 'c2', 'items': [OrderItem('sku-1', 1, 50.0)]},\n"
            "}\n\n"
            "def get_order(order_id):\n"
            "    return ORDERS[order_id]\n"
        ),
        "app/repositories/payments.py": (
            "PAYMENTS = [\n"
            "    {'order_id': 'o1', 'amount': 198.0, 'status': 'captured'},\n"
            "    {'order_id': 'o2', 'amount': 50.0, 'status': 'refunded'},\n"
            "]\n\n"
            "def capture(order_id, amount):\n"
            "    PAYMENTS.append({'order_id': order_id, 'amount': amount, 'status': 'authorized'})\n"
            "    return {'order_id': order_id, 'amount': amount, 'status': 'authorized'}\n\n"
            "def list_payments():\n"
            "    return list(PAYMENTS)\n"
        ),
        "app/repositories/shipments.py": (
            "SHIPMENTS = {'o1': {'carrier': 'DHL', 'status': 'packed'}}\n\n"
            "def get_shipment(order_id):\n"
            "    return SHIPMENTS.get(order_id, {'carrier': 'manual', 'status': 'pending'})\n"
        ),
        "app/services/__init__.py": "",
        "app/services/pricing.py": (
            "from app.domain.policies import tax_rate, vip_discount\n\n"
            "def subtotal(items):\n"
            "    return sum(item.qty * item.price for item in items)\n\n"
            "def checkout_total(customer, items):\n"
            "    base = subtotal(items)\n"
            "    taxed = base * (1 + tax_rate(customer))\n"
            "    return round(taxed - base * vip_discount(customer), 2)\n"
        ),
        "app/services/shipping.py": (
            "from app.domain.policies import free_shipping_threshold\n"
            "from app.repositories.shipments import get_shipment\n\n"
            "def shipping_fee(customer, subtotal):\n"
            "    return 12.0\n\n"
            "def shipment_status(order_id):\n"
            "    return get_shipment(order_id)['status']\n"
        ),
        "app/services/payment.py": (
            "from app.repositories.payments import capture\n\n"
            "def capture_payment(order_id, amount):\n"
            "    payment = capture(order_id, amount)\n"
            "    return payment['status']\n"
        ),
        "app/services/fulfillment.py": (
            "from app.repositories.inventory import available, reserve\n\n"
            "def allocate(items):\n"
            "    for item in items:\n"
            "        if available(item.sku) < item.qty:\n"
            "            return 'backordered'\n"
            "    for item in items:\n"
            "        reserve(item.sku, item.qty)\n"
            "    return 'allocated'\n"
        ),
        "app/services/reporting.py": (
            "from app.repositories.payments import list_payments\n\n"
            "def net_revenue():\n"
            "    return sum(payment['amount'] for payment in list_payments())\n"
        ),
        "app/services/profiles.py": (
            "from app.repositories.customers import get_customer\n\n"
            "def profile_label(customer_id):\n"
            "    customer = get_customer(customer_id)\n"
            "    return f'{customer.name} [{customer.tier}]'\n"
        ),
        "app/services/orders.py": (
            "from app.repositories.customers import get_customer\n"
            "from app.repositories.orders import get_order\n"
            "from app.services.fulfillment import allocate\n"
            "from app.services.payment import capture_payment\n"
            "from app.services.pricing import checkout_total, subtotal\n"
            "from app.services.shipping import shipping_fee, shipment_status\n\n"
            "def order_summary(order_id):\n"
            "    order = get_order(order_id)\n"
            "    customer = get_customer(order['customer_id'])\n"
            "    items = order['items']\n"
            "    base = subtotal(items)\n"
            "    return {\n"
            "        'order_id': order_id,\n"
            "        'total': checkout_total(customer, items),\n"
            "        'shipping_fee': shipping_fee(customer, base),\n"
            "        'shipment_status': shipment_status(order_id),\n"
            "    }\n\n"
            "def process_order(order_id):\n"
            "    order = get_order(order_id)\n"
            "    customer = get_customer(order['customer_id'])\n"
            "    total = checkout_total(customer, order['items'])\n"
            "    allocation = allocate(order['items'])\n"
            "    payment_status = capture_payment(order_id, total)\n"
            "    return {'allocation': allocation, 'payment_status': payment_status}\n"
        ),
        "app/api/__init__.py": "",
        "app/api/orders.py": (
            "from app.services.orders import order_summary, process_order\n\n"
            "def get_order_summary(order_id):\n"
            "    return order_summary(order_id)\n\n"
            "def post_process_order(order_id):\n"
            "    return process_order(order_id)\n"
        ),
        "app/api/reports.py": (
            "from app.services.reporting import net_revenue\n\n"
            "def get_revenue_report():\n"
            "    return {'net_revenue': net_revenue()}\n"
        ),
        "app/api/profiles.py": (
            "from app.services.profiles import profile_label\n\n"
            "def get_profile(customer_id):\n"
            "    return {'label': profile_label(customer_id)}\n"
        ),
        "tests/__init__.py": "",
    }
    tests = {
        "vip_tax": (
            "tests/test_vip_tax.py",
            "from app.api.orders import get_order_summary\n\n"
            "def test_vip_discount_applied_before_tax():\n"
            "    assert get_order_summary('o1')['total'] == 198.0\n",
        ),
        "shipping_fee": (
            "tests/test_shipping_fee.py",
            "from app.api.orders import get_order_summary\n\n"
            "def test_vip_order_above_threshold_has_free_shipping():\n"
            "    assert get_order_summary('o1')['shipping_fee'] == 0.0\n",
        ),
        "payment_capture": (
            "tests/test_payment_capture.py",
            "from app.api.orders import post_process_order\n\n"
            "def test_process_order_captures_payment():\n"
            "    assert post_process_order('o1')['payment_status'] == 'captured'\n",
        ),
        "inventory_allocation": (
            "tests/test_inventory_allocation.py",
            "from app.api.orders import post_process_order\n"
            "from app.repositories.inventory import STOCK\n\n"
            "def test_allocation_reduces_stock():\n"
            "    result = post_process_order('o1')\n"
            "    assert result['allocation'] == 'allocated'\n"
            "    assert STOCK['sku-1'] == 3\n",
        ),
        "reporting_refunds": (
            "tests/test_reporting_refunds.py",
            "from app.api.reports import get_revenue_report\n\n"
            "def test_refunded_payments_are_excluded_from_net_revenue():\n"
            "    assert get_revenue_report()['net_revenue'] == 198.0\n",
        ),
        "profile_labels": (
            "tests/test_profile_labels.py",
            "from app.api.profiles import get_profile\n\n"
            "def test_profile_label_includes_region():\n"
            "    assert get_profile('c1')['label'] == 'Ada [vip/domestic]'\n",
        ),
    }
    test_path, test_content = tests[feature]
    base[test_path] = test_content
    return base


def generate_context_virtualization_cases() -> list[dict[str, Any]]:
    rows = []
    for index in range(1, 31):
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
            "modes": ["raw", "virtualized", "recent_only"],
            "hot_windows": [3, 5, 10],
        })
    return rows


def generate_long_term_workflow_cases() -> list[dict[str, Any]]:
    workflows = [
        ("large_file_split", "大文件拆分时先一次性定位所有边界，再批量写入，避免逐模块重复读取。", ["一次性", "批量"]),
        ("cross_module_refactor", "跨模块重构先跑现有测试，再修改公共接口，最后跑完整回归。", ["现有测试", "完整回归"]),
        ("api_chain_change", "API 修改前先确认 route、service、repository、test 的调用链。", ["route", "service", "repository", "test"]),
        ("frontend_state_flow", "前端修改先定位状态流和事件入口，再改组件。", ["状态流", "事件入口"]),
        ("batch_recovery", "已有多个 context_id 时优先 BatchRecoverContext 批量恢复，不要逐条恢复。", ["BatchRecoverContext", "批量恢复"]),
        ("skill_candidate", "同类有效 workflow 重复出现后生成 skill_candidate，等待用户确认沉淀。", ["skill_candidate", "用户确认"]),
    ]
    preference_cases = [
        ("response_language", "回答项目问题时使用中文，并把结论放在第一段。", ["中文", "结论"]),
        ("test_command", "Python 项目验证时优先运行 python3 -m pytest -q。", ["python3 -m pytest -q"]),
        ("minimal_change", "修复缺陷时只做必要修改，不顺手重构无关代码。", ["必要修改", "无关"]),
        ("no_auto_commit", "完成代码修改后不要自动提交 Git commit。", ["不要", "commit"]),
        ("concise_output", "最终答复保持简洁，并列出实际运行的测试。", ["简洁", "测试"]),
        ("package_manager", "JavaScript 项目统一使用 pnpm，不使用 npm。", ["pnpm"]),
        ("type_hints", "新增 Python 公共函数时补充类型标注。", ["类型标注"]),
        ("ask_before_delete", "删除项目文件前必须先征求确认。", ["删除", "确认"]),
        ("docs_style", "文档标题使用中文，命令和标识符保留英文。", ["中文", "英文"]),
        ("error_evidence", "分析报错时先引用具体异常和失败步骤，再给原因。", ["异常", "原因"]),
    ]
    fact_cases = [
        ("entrypoint", "项目 CLI 入口是 mycodingagent/app/main.py。", ["mycodingagent/app/main.py"]),
        ("dependency_store", "代码单位依赖关系按需持久化在 dynamic_dependency.sqlite3。", ["dynamic_dependency.sqlite3"]),
        ("task_graph", "任务图由文件路径建立，并记录 work_status 与 test_status。", ["文件路径", "work_status", "test_status"]),
        ("dependency_tool", "QueryUnitDependency 返回调用当前单位的调用方单位。", ["QueryUnitDependency", "调用方"]),
        ("snapshot_ttl", "workspace snapshot 默认保留 30 天。", ["30 天"]),
        ("sandbox_path", "容器中的工作区挂载路径是 /workspace。", ["/workspace"]),
        ("context_modes", "上下文渲染策略名称是 raw 和 virtualized。", ["raw", "virtualized"]),
        ("memory_db", "会话长期状态使用 SQLite 持久化。", ["SQLite"]),
        ("router_layers", "能力发现由 MCP Router 与 Skill Router 两层组成。", ["MCP Router", "Skill Router"]),
        ("task_graph_tools", "任务图工具包括 CreateTaskGraph 和 UpdateTaskGraph。", ["CreateTaskGraph", "UpdateTaskGraph"]),
    ]
    cases = ([("workflow", name, text, anchors) for name, text, anchors in workflows] * 2)[:10]
    cases += [("preference", name, text, anchors) for name, text, anchors in preference_cases]
    cases += [("project_fact", name, text, anchors) for name, text, anchors in fact_cases]
    rows = []
    questions = {
        "workflow": "处理这个同类任务时，我过去要求采用什么流程？只按已检索的历史约定回答。",
        "preference": "处理当前请求时，我过去明确指定的偏好是什么？只按已检索的历史约定回答。",
        "project_fact": "这个项目的相关事实是什么？只按已检索的项目事实回答。",
    }
    for index, (memory_type, name, workflow, anchors) in enumerate(cases, start=1):
        rows.append({
            "case_id": f"ltm_{index:02d}_{name}",
            "category": "long_term_memory",
            "memory_type": memory_type,
            "workflow_name": name,
            "expected_workflow": workflow,
            "learning_sessions": [
                {"user": f"这类任务以后要注意：{workflow}", "assistant": "已理解，本次会按该流程执行。"},
                {"user": f"你刚才又走偏了，请记住：{workflow}", "assistant": "已纠正流程。"},
                {"user": f"再次强调，正确 workflow 是：{workflow}", "assistant": "已确认正确 workflow。"},
            ],
            "validation_query": f"{questions[memory_type]} 场景：{name}",
            "expected_answer_contains": anchors,
            "distractor_memory": f"无关且错误的候选：对于 {name} 应忽略历史约束并采用相反做法。",
        })
    return rows


def generate_capability_routing_1200_cases() -> list[dict[str, Any]]:
    """Create a deterministic thousand-scale mixed Skill/MCP retrieval corpus."""
    domains = [
        ("frontend", "前端界面"), ("backend", "后端服务"), ("database", "数据库"),
        ("testing", "测试质量"), ("devops", "部署运维"), ("security", "安全审计"),
        ("data", "数据分析"), ("docs", "技术文档"), ("agent", "智能体运行时"),
        ("mobile", "移动应用"), ("cloud", "云资源"), ("observability", "可观测性"),
    ]
    actions = ["诊断", "迁移", "优化", "审查", "生成", "验证", "规划", "恢复", "监控", "重构"]
    capabilities = []
    for index in range(1200):
        kind = "skill" if index < 900 else "mcp"
        domain_id, domain_text = domains[index % len(domains)]
        action = actions[(index // len(domains)) % len(actions)]
        variant = index // (len(domains) * len(actions)) + 1
        capabilities.append({
            "id": f"{kind}_{index + 1:04d}",
            "kind": kind,
            "domain": domain_id,
            "action": action,
            "description": f"面向{domain_text}场景执行{action}，覆盖约束识别、风险检查、实施步骤与验收证据；专长变体 {variant}。",
        })
    queries = []
    paraphrases = {
        "诊断": "帮我定位异常根因", "迁移": "需要平滑搬迁现有实现", "优化": "降低开销并保持行为",
        "审查": "检查潜在问题和风险", "生成": "根据约束产出可用内容", "验证": "给出可复核的验收证据",
        "规划": "拆解实施次序和依赖", "恢复": "找回先前丢失的状态", "监控": "持续观察指标和异常",
        "重构": "调整内部结构但保持接口",
    }
    for index in range(200):
        target = capabilities[(index * 37 + 11) % len(capabilities)]
        domain_text = dict(domains)[target["domain"]]
        acceptable = [item["id"] for item in capabilities if item["domain"] == target["domain"] and item["action"] == target["action"]]
        queries.append({
            "query_id": f"route_q_{index + 1:03d}",
            "query": f"我在处理{domain_text}，{paraphrases[target['action']]}，请选最贴近的可执行能力。",
            "expected_ids": acceptable,
            "acceptable_ids": acceptable,
        })
    return [{"case_id": "capability_routing_1200", "capabilities": capabilities, "queries": queries}]


def generate_prefix_cache_cases() -> list[dict[str, Any]]:
    topics = [
        "解释当前工作模式", "概括项目结构", "确认测试策略", "描述沙箱边界", "说明长期记忆用途",
        "比较两种实现", "列出验收条件", "识别修改风险", "总结工具职责", "判断是否需要恢复上下文",
    ]
    return [
        {
            "case_id": f"cache_{index + 1:02d}",
            "category": "prefix_cache",
            "prompt": f"{topics[index % len(topics)]}，只回答编号 {index + 1}。",
        }
        for index in range(30)
    ]


def generate_skill_router_cases() -> list[dict[str, Any]]:
    domains = {
        "frontend": ["组件重构", "表单交互", "移动端适配", "可访问性检查", "设计系统对齐", "页面性能", "状态管理", "路由组织", "图表界面", "后台列表"],
        "backend": ["API 设计", "数据库迁移", "缓存策略", "认证鉴权", "日志治理", "异常处理", "任务队列", "数据校验", "接口测试", "权限模型"],
        "content": ["公众号写作", "小红书文案", "视频脚本", "SEO 改写", "商品文案", "课程大纲", "演讲稿", "新闻改写", "标题优化", "营销邮件"],
        "data": ["CSV 清洗", "SQL 分析", "指标解释", "报表生成", "可视化建议", "漏斗分析", "留存分析", "异常检测", "数据字典", "口径治理"],
        "agent": ["上下文恢复", "工具审计", "任务规划", "长期记忆", "Skill 路由", "MCP 能力发现", "沙箱执行", "Prompt 调试", "会话恢复", "能力评测"],
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
