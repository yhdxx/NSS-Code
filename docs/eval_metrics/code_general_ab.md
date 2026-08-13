# Code / General 工作模式 A/B 评测

- 状态：`passed`
- 指标 ID：`code_general_ab`

## 指标定义

在相同模型、任务和工具 schema 下，对比 Code 图谱导航与 General 自主探索的任务成功率和执行成本。

## 计算公式

- 任务成功率 = 验收测试通过的运行数 / 总运行数
- 成本降幅 = (General 均值 - Code 均值) / General 均值

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/code_general_tasks.jsonl",
  "dataset_sha256": "5213c55b18c41f1db7c0edd33f197e479103f92ddee00793f7edda4609c4aa7a",
  "sample_count": 180,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T19:58:21+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "standard-code-general-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-code-general-ab --dataset tests/eval/datasets/code_general_tasks.jsonl --repeats 3
```

## 结果与置信区间

```json
{
  "by_mode": {
    "code": {
      "duration_mean_seconds": 32.080078,
      "graph_tool_calls_mean": 1.044444,
      "invalid_tool_calls_mean": 0.7,
      "prompt_tokens_mean": 51561.477778,
      "readfile_visible_bytes_mean": 1167.144444,
      "repeated_tool_calls_mean": 0.0,
      "run_count": 90,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 11.777778,
      "total_tokens_mean": 53512.1
    },
    "general": {
      "duration_mean_seconds": 31.529322,
      "graph_tool_calls_mean": 0.444444,
      "invalid_tool_calls_mean": 1.211111,
      "prompt_tokens_mean": 46833.655556,
      "readfile_visible_bytes_mean": 1110.766667,
      "repeated_tool_calls_mean": 0.0,
      "run_count": 90,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 10.955556,
      "total_tokens_mean": 48745.077778
    }
  },
  "case_count": 30,
  "code_cost_reduction_ci95": {
    "prompt_tokens": {
      "high": 0.025554,
      "low": -0.247011,
      "mean": -0.100949
    },
    "readfile_visible_bytes": {
      "high": 0.072676,
      "low": -0.187054,
      "mean": -0.050756
    },
    "tool_calls": {
      "high": -0.016873,
      "low": -0.138826,
      "mean": -0.075051
    },
    "total_tokens": {
      "high": 0.026789,
      "low": -0.240335,
      "mean": -0.097795
    }
  },
  "code_cost_reductions": {
    "prompt_tokens": -0.100949,
    "readfile_visible_bytes": -0.050756,
    "tool_calls": -0.075051,
    "total_tokens": -0.097795
  },
  "code_success_rate_delta": 0.0,
  "efficiency_claim_gate_passed": false,
  "paired_run_count": 90,
  "reason": "",
  "repeats": 3,
  "resume_conclusion": "30 个开发任务、每模式 3 次的 A/B 中两种模式成功率均为 100%，但 Code 的工具调用、可见读取字节和 token 成本均未下降，当前不可宣称 Code 模式提高效率。",
  "run_count": 180
}
```

## 失败、超时与异常样例

```json
{
  "count": 137,
  "examples": [
    {
      "case_id": "ma_small_01_add",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "calculator.py"
      ],
      "completion_tokens": 690,
      "duration_seconds": 15.672,
      "final_answer_tail": "测试已全部通过（1 passed）。\n\n**修复内容**：`calculator.py` 第 2 行，`add` 函数的返回语句误写为 `a - b`，改为正确的 `a + b`。",
      "graph_tool_calls": 0,
      "invalid_tool_calls": 1,
      "mode": "general",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 28683,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.01s\n",
      "readfile_visible_bytes": 112,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 6,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n___________________________________ test_add ___________________________________\n\n    def test_add():\n>       assert add(2, 3) == 5\nE       assert -1 == 5\nE        +  where -1 = add(2, 3)\n\ntest_calculator.py:4: AssertionError\n=========================== short test summary info ============================\nFAILED test_calculator.py:",
          "tool_call_id": "call_01_qrFoROoWEHs2falgAnRJ4402",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "Glob",
        "Bash",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 29373
    },
    {
      "case_id": "ma_small_02_slug",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "text_utils.py"
      ],
      "completion_tokens": 727,
      "duration_seconds": 17.4,
      "final_answer_tail": "测试通过。修复内容：将 `text_utils.py` 中 `slugify` 的 `text.replace(' ', '_')` 改为 `text.lower().replace(' ', '-')`，使其小写化并用连字符替换空格，与测试预期一致。",
      "graph_tool_calls": 0,
      "invalid_tool_calls": 1,
      "mode": "general",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 28922,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.00s\n",
      "readfile_visible_bytes": 166,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 6,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n_________________________________ test_slugify _________________________________\n\n    def test_slugify():\n>       assert slugify('Hello World') == 'hello-world'\nE       AssertionError: assert 'Hello_World' == 'hello-world'\nE         \nE         - hello-world\nE         + Hello_World\n\ntest_text_utils.py:4: AssertionError\n=============",
          "tool_call_id": "call_00_tebU9legp9cpmrqCMtGr6665",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "Bash",
        "Glob",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 29649
    },
    {
      "case_id": "ma_small_01_add",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "calculator.py"
      ],
      "completion_tokens": 836,
      "duration_seconds": 18.44,
      "final_answer_tail": "测试全部通过 ✅\n\n**问题**：`calculator.py` 中的 `add(a, b)` 函数错误地返回 `a - b`（减法）而非 `a + b`（加法）。\n\n**修复**：将 `return a - b` 改为 `return a + b`。\n\n```\n1 passed in 0.00s\n```",
      "graph_tool_calls": 1,
      "invalid_tool_calls": 1,
      "mode": "code",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 36395,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.00s\n",
      "readfile_visible_bytes": 112,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 7,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n___________________________________ test_add ___________________________________\n\n    def test_add():\n>       assert add(2, 3) == 5\nE       assert -1 == 5\nE        +  where -1 = add(2, 3)\n\ntest_calculator.py:4: AssertionError\n=========================== short test summary info ============================\nFAILED test_calculator.py:",
          "tool_call_id": "call_01_prWnwCUIJjNKSEAL1dIf7543",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "ProjectArchitecture",
        "Bash",
        "Glob",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 37231
    },
    {
      "case_id": "ma_small_03_discount",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "pricing.py"
      ],
      "completion_tokens": 798,
      "duration_seconds": 18.643,
      "final_answer_tail": "测试全部通过。问题在 `pricing.py` 第 2 行：`apply_discount` 将折扣金额加到了原价上（`price + price * pct`），导致 `100 + 20 = 120`。修改为 `price - price * pct`，现在 `apply_discount(100, 0.2)` 正确返回 `80`。",
      "graph_tool_calls": 1,
      "invalid_tool_calls": 1,
      "mode": "code",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 36537,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.00s\n",
      "readfile_visible_bytes": 172,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 7,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n________________________________ test_discount _________________________________\n\n    def test_discount():\n>       assert apply_discount(100, 0.2) == 80\nE       assert 120.0 == 80\nE        +  where 120.0 = apply_discount(100, 0.2)\n\ntest_pricing.py:4: AssertionError\n=========================== short test summary info ===============",
          "tool_call_id": "call_01_7HHhoRUyjSqpNj2AkPvp6689",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "ProjectArchitecture",
        "Bash",
        "Glob",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 37335
    },
    {
      "case_id": "ma_small_06_stats",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "stats.py"
      ],
      "completion_tokens": 726,
      "duration_seconds": 17.794,
      "final_answer_tail": "测试已通过 ✅。修改内容：在 `stats.py` 的 `average()` 函数开头增加了空列表判断，若 `values` 为空则直接返回 `0`，避免除零错误。",
      "graph_tool_calls": 0,
      "invalid_tool_calls": 1,
      "mode": "general",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 29106,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.00s\n",
      "readfile_visible_bytes": 149,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 6,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n______________________________ test_average_empty ______________________________\n\n    def test_average_empty():\n>       assert average([]) == 0\n               ^^^^^^^^^^^\n\ntest_stats.py:4: \n_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ \n\nvalues = []\n\n    def average(values):\n>       return sum(valu",
          "tool_call_id": "call_01_GoHijVurSFDbzMNFuzcV1054",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "Glob",
        "Bash",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 29832
    },
    {
      "case_id": "ma_small_06_stats",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "stats.py"
      ],
      "completion_tokens": 822,
      "duration_seconds": 18.009,
      "final_answer_tail": "测试通过。修复内容：在 `stats.py` 的 `average` 函数中增加了空列表判断，当列表为空时返回 `0`，避免除零错误。",
      "graph_tool_calls": 1,
      "invalid_tool_calls": 1,
      "mode": "code",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 36509,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.00s\n",
      "readfile_visible_bytes": 149,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 7,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n______________________________ test_average_empty ______________________________\n\n    def test_average_empty():\n>       assert average([]) == 0\n               ^^^^^^^^^^^\n\ntest_stats.py:4: \n_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ \n\nvalues = []\n\n    def average(values):\n>       return sum(valu",
          "tool_call_id": "call_00_VvO1Y8G9AwPmWJxI5uob4888",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "ProjectArchitecture",
        "Glob",
        "ReadFile",
        "ReadFile",
        "Bash",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 37331
    },
    {
      "case_id": "ma_small_04_email",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "validators.py"
      ],
      "completion_tokens": 1169,
      "duration_seconds": 25.429,
      "final_answer_tail": "测试通过，1 passed。\n\n**问题原因**：`is_email` 仅检查 `'@' in value`，导致 `'@missing-name'`（`@` 在开头，缺少 local-part）错误地返回 `True`。\n\n**修复**：在 `validators.py` 中增加 `not value.startswith('@')` 条件，确保 `@` 不在字符串开头时才会被认为是合法邮箱。这是最小且与现有测试兼容的修改。",
      "graph_tool_calls": 0,
      "invalid_tool_calls": 1,
      "mode": "general",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 29697,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.01s\n",
      "readfile_visible_bytes": 186,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 6,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n__________________________________ test_email __________________________________\n\n    def test_email():\n        assert is_email('a@example.com')\n>       assert not is_email('@missing-name')\nE       AssertionError: assert not True\nE        +  where True = is_email('@missing-name')\n\ntest_validators.py:5: AssertionError\n==============",
          "tool_call_id": "call_01_1O5kMK1XeYgyzicWJjUC1220",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "Glob",
        "Bash",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 30866
    },
    {
      "case_id": "ma_small_07_auth",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "auth.py"
      ],
      "completion_tokens": 916,
      "duration_seconds": 18.307,
      "final_answer_tail": "测试通过了。修复内容：将 `auth.py` 中 `can_edit` 函数的角色判断从 `'viewer'` 改为 `'admin'`——现在 `admin` 角色可以编辑，而 `viewer` 角色不能编辑，与测试预期一致。",
      "graph_tool_calls": 0,
      "invalid_tool_calls": 1,
      "mode": "general",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 29305,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.01s\n",
      "readfile_visible_bytes": 203,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 6,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n________________________________ test_can_edit _________________________________\n\n    def test_can_edit():\n>       assert can_edit({'role': 'admin'})\nE       AssertionError: assert False\nE        +  where False = can_edit({'role': 'admin'})\n\ntest_auth.py:4: AssertionError\n=========================== short test summary info ========",
          "tool_call_id": "call_01_xIt5ov6XL1u9psyCpvGW0847",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "Glob",
        "Bash",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 30221
    },
    {
      "case_id": "ma_small_08_format",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "formatters.py"
      ],
      "completion_tokens": 723,
      "duration_seconds": 15.479,
      "final_answer_tail": "测试全部通过。修复内容：\n\n- **`formatters.py`** 第 2 行：`user_label` 函数从只返回 `user['name']` 改为返回 `f\"{user['name']} ({user['role']})\"`，使其与测试期望的 `'Ada (admin)'` 格式一致。",
      "graph_tool_calls": 0,
      "invalid_tool_calls": 1,
      "mode": "general",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 28880,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.00s\n",
      "readfile_visible_bytes": 187,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 6,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n_______________________________ test_user_label ________________________________\n\n    def test_user_label():\n>       assert user_label({'name': 'Ada', 'role': 'admin'}) == 'Ada (admin)'\nE       AssertionError: assert 'Ada' == 'Ada (admin)'\nE         \nE         - Ada (admin)\nE         + Ada\n\ntest_formatters.py:4: AssertionError\n====",
          "tool_call_id": "call_01_oUG7dRDSJDSs480VeZ0Y9140",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "Glob",
        "Bash",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 29603
    },
    {
      "case_id": "ma_small_07_auth",
      "changed_files": [
        ".pytest_cache/.gitignore",
        ".pytest_cache/CACHEDIR.TAG",
        ".pytest_cache/README.md",
        ".pytest_cache/v/cache/lastfailed",
        ".pytest_cache/v/cache/nodeids",
        "auth.py"
      ],
      "completion_tokens": 1022,
      "duration_seconds": 20.265,
      "final_answer_tail": "测试全部通过。修复内容：\n\n- **`auth.py`** 第 2 行：将 `user.get('role') == 'viewer'` 改为 `user.get('role') == 'admin'`\n\n`can_edit` 的逻辑现在与测试期望一致：`admin` 角色有编辑权限（返回 `True`），`viewer` 角色没有（返回 `False`）。",
      "graph_tool_calls": 1,
      "invalid_tool_calls": 1,
      "mode": "code",
      "passed": true,
      "project_size": "small",
      "prompt_tokens": 36841,
      "pytest_returncode": 0,
      "pytest_stdout_tail": ".                                                                        [100%]\n1 passed in 0.00s\n",
      "readfile_visible_bytes": 203,
      "repeat": 0,
      "repeated_tool_calls": 0,
      "status": "passed",
      "tool_call_count": 7,
      "tool_errors": [
        {
          "error_excerpt": "标准输出：\nF                                                                        [100%]\n=================================== FAILURES ===================================\n________________________________ test_can_edit _________________________________\n\n    def test_can_edit():\n>       assert can_edit({'role': 'admin'})\nE       AssertionError: assert False\nE        +  where False = can_edit({'role': 'admin'})\n\ntest_auth.py:4: AssertionError\n=========================== short test summary info ========",
          "tool_call_id": "call_01_gMIl2Lce9hwAjWZNb1hZ8535",
          "tool_name": "Bash"
        }
      ],
      "tool_names": [
        "ProjectArchitecture",
        "Bash",
        "Glob",
        "ReadFile",
        "ReadFile",
        "EditFile",
        "Bash"
      ],
      "total_tokens": 37863
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 30 个任务、每模式 3 次；Code 成功率不得比 General 低超过 5 个百分点，且 token 或读取/工具调用成本显著下降，才可表述为提高效率。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

30 个开发任务、每模式 3 次的 A/B 中两种模式成功率均为 100%，但 Code 的工具调用、可见读取字节和 token 成本均未下降，当前不可宣称 Code 模式提高效率。
