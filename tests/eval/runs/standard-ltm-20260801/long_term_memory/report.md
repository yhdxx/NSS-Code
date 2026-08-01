# 长期记忆有效性评测

- 状态：`passed`
- 指标 ID：`long_term_memory`

## 指标定义

比较无记忆、正确检索记忆和错误干扰记忆对用户偏好、项目事实及历史 Workflow 任务的影响。

## 计算公式

- 分组准确率 = 满足预定义答案锚点的运行数 / 分组总运行数
- 正确记忆增益 = 正确记忆准确率 - 无记忆准确率

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/long_term_workflow_cases.jsonl",
  "dataset_sha256": "f4a6537a451cf22d1b5ad6dac73a0976794b78cd6ea68f186dacfa9b860ec16e",
  "sample_count": 270,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T19:26:39+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "standard-ltm-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-long-term-memory --dataset tests/eval/datasets/long_term_workflow_cases.jsonl --repeats 3
```

## 结果与置信区间

```json
{
  "by_memory_type": {
    "preference": {
      "correct_memory": 0.066667,
      "distractor_memory": 0.0,
      "without_memory": 0.0
    },
    "project_fact": {
      "correct_memory": 0.1,
      "distractor_memory": 0.0,
      "without_memory": 0.0
    },
    "workflow": {
      "correct_memory": 0.2,
      "distractor_memory": 0.0,
      "without_memory": 0.0
    }
  },
  "by_variant": {
    "correct_memory": {
      "accuracy": 0.122222,
      "accuracy_ci95": {
        "high": 0.188889,
        "low": 0.055556,
        "mean": 0.122222
      },
      "run_count": 90
    },
    "distractor_memory": {
      "accuracy": 0.0,
      "accuracy_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      },
      "run_count": 90
    },
    "without_memory": {
      "accuracy": 0.0,
      "accuracy_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      },
      "run_count": 90
    }
  },
  "case_count": 30,
  "reason": "",
  "run_count": 270
}
```

## 失败、超时与异常样例

```json
{
  "count": 259,
  "examples": [
    {
      "answer": "For large file splitting, I’ll adopt a **two-pass, metadata-first workflow**:\n\n1. **Scan & index boundaries**:  \n   Read the file once sequentially (streaming) to locate all split points (e.g., per‑line limits, record delimiters, or byte offsets). Store these offsets in an efficient list/array without holding file content in memory.\n\n2. **Parallel/batch writing**:  \n   Open the source file once more (or use a pre‑existing file descriptor) and, for each chunk, seek directly to the recorded offset, read exactly the chunk’s bytes, and write to the corresponding output part. This avoids re‑scanning and repeated I/O.\n\nThis aligns with the key insight: *locate boundaries once, then write in bulk*, minimizing redundant passes and memory pressure.",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 7820.388,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 1,
      "status": "passed",
      "variant": "correct_memory"
    },
    {
      "answer": "我会采用以下 workflow 处理 large_file_split 任务：\n\n1. **需求分析与文件评估**  \n   - 明确分割依据（按行数、文件大小、内容标记等）。  \n   - 检查文件大小、编码、换行符类型，评估内存限制。\n\n2. **工具选择**  \n   - 小文件或中等文件：直接用 Python 脚本（按行读取，流式写入）。  \n   - 超大文件（远超内存）：使用系统命令（如 `split`，`csplit`）或流式处理避免全量加载。\n\n3. **实现分割逻辑**  \n   - 按行分割：逐行读取源文件，计数到阈值时切换到新分片文件。  \n   - 按大小分割：以二进制或行缓冲方式累计字节数，达标后切换。  \n   - 按内容标记：用正则匹配分隔符，动态创建分片。\n\n4. **命名与元数据保留**  \n   - 自动生成有序文件名（如 `part_001.txt`）。  \n   - 保留原扩展名、编码不变，必要时生成索引文件记录分片信息。\n\n5. **验证与校验**  \n   - 验证分片总数、大小总和、行数总和与原文件一致。  \n   - 合并回原文件测试完整性。\n\n6. **异常处理与日志**  \n   - 处理磁盘满、写入错误等，支持断点续传或回滚。  \n   - 记录分割参数、耗时及分片清单。\n\n我会根据实际文件大小和分割需求灵活选择实现方式，优先保证内存效率和数据完整性。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 9174.441,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 2,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "采用以下工作流：\n\n1. **一次性扫描定位边界**：以只读方式打开大文件，顺序遍历内容，根据指定的拆分规则（如按行数、按固定字节大小或按分隔符）快速识别所有拆分点，同时记录每个块的起始偏移和长度（或结束偏移），收集为边界索引列表。此过程仅做记录，不进行写入操作。\n2. **批量顺序读取并写入**：根据边界索引，从源文件对应位置分批读取数据块（可一次读取若干块以利用磁盘顺序IO），然后迭代地将每个数据块写入各自的目标小文件中。确保对源文件只做一次完整的顺序读取，各输出文件按需创建并接收对应的数据块。\n3. **验证与清理**：完成后校验文件数量与大小，关闭所有句柄，确保无数据遗漏或覆盖。\n\n该流程完全避免针对每个子模块重复遍历和读取源文件，将IO开销降至最低。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 10344.221,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 2,
      "status": "passed",
      "variant": "correct_memory"
    },
    {
      "answer": "我会采用以下 **结构化分步执行流程（workflow）** 来处理大文件分割任务：\n\n---\n\n### 1. 明确需求 & 约束\n- 确认文件类型（文本、二进制、日志、CSV 等）\n- 明确分割方式：按**行数**、按**文件大小**、按**逻辑分块**（如按时间/ID）、或**指定 chunk 数量**\n- 了解命名规则（`part_001.csv`、`chunk_0001.dat` 等）\n- 确定是否需要保留表头（CSV/表格文件）\n- 确认分块后是否还要支持**无损合并还原**\n\n### 2. 文件扫描与评估\n- 获取原始文件总大小、行数、编码（Windows/Linux 换行符）\n- 检查可用磁盘空间是否足够存下临时输出\n- 对大文件做只读流式打开，避免一次性读入内存\n\n### 3. 分割策略选型\n| 场景 | 策略 |\n|------|------|\n| 按固定大小分割 | 使用字节流读取固定大小 chunk |\n| 按固定行数分割 | 逐行读取计数，达到阈值即输出新文件 |\n| 带表头的日志/CSV | 读出表头 → 写入每个 chunk 首行 |\n| 二进制大文件 | 直接用 seek/read 分块 |\n| 超大文件（10 GB+） | 完全流式处理，单线程顺序 I/O |\n\n### 4. 分割执行（核心步骤）\n1. **打开源文件**（只读、流式）\n2. **循环处理**：\n   - 按策略读取一片数据/若干行\n   - 写入新的 chunk 文件（命名递增）\n   - 记录已处理的字节/行数\n   - 输出日志/进度（每 1% 或每 100 MB 回显）\n3. **收尾**：关闭所有文件，输出 manifest（chunk 列表及校验信息）\n\n### 5. 校验与验证\n- 校验所有 chunk 总大小/总行数是否与源文件一致\n- 对每个 chunk 做快速校验（如 SHA256）\n- （可选）合并回原始文件并比对哈希，确保可逆\n\n### 6. 信息输出\n返回：\n- 原始文件信息（大小、行数）\n- 分块数量、每个 chunk 大小\n- 校验和列表\n- 合并还原命令（Linux `cat`、PowerShell `Get-Content` 等）\n\n---\n\n**工具选择**：根据用户环境可用 Python（跨平台）、PowerShell（Windo",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 15529.801,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 1,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "针对“large_file_split”这一场景，我会采用以下工作流：\n\n1. **明确拆分目标与规则**\n   - 确定拆分依据：按行数、文件大小（MB/GB），还是按特定分隔标记（如每万行一个子文件，或遇到指定字符串时分段）。\n   - 确定输出命名规则：原文件名_part1、原文件名_part2 等，或添加序号/时间戳。\n\n2. **评估文件特征**\n   - 检测文件类型（文本、二进制、CSV、日志等）及编码。\n   - 估算总行数或总大小，决定拆分块数或块大小。\n   - 注意是否包含头部（CSV 表头），若需要保留 header 到每个子文件。\n\n3. **选择高效的工具与方法**\n   - 小规模文件（<100MB）：可直接用 Python 脚本、shell 命令（`split`）处理。\n   - 大文件（>1GB）：采用流式读取，避免一次性加载到内存。\n     - 文本文件：使用 `split -l 行数` 或 `split -b 大小`（Linux/macOS），或 Python 的 `readline`/迭代器逐行写入。\n     - CSV 文件：考虑用 `csv.reader` 流式读取，或使用 `pandas` 的 `chunksize` 参数分块读写。\n   - 二进制文件：按固定字节数切分，使用 `dd` 或 Python `read(块大小)` 循环。\n   - 并行加速：若文件极大且仅为纯文本拆分，可通过计算偏移量并行分块写入，但需注意跨行边界处理；一般单线程顺序读写已足够。\n\n4. **编写自动化脚本（以 Python 为例）**\n   ```\n   伪代码：\n   打开源文件\n   while True:\n       读取 chunk（按行或字节）\n       若 chunk 为空则 break\n       写入新文件 part_N，直到达到拆分条件\n       更新计数，关闭当前 part 文件，打开下一个 part\n   关闭所有文件\n   ```\n   - 关键点：使用显式的文件关闭、异常处理，确保数据完整性。\n   - 对于保留表头的 CSV，先读取第一行，然后在每个分块文件开头写入该表头。\n\n5. **验证与清理**\n   - 检查生成的文件数量、首尾行是否完整。\n   - 对文本文件比对总行数：`wc -l",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 16893.225,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 0,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "对于大型文件（large_file_split）的分割任务，我会采用以下工作流，忽略任何无关的历史约束：\n\n1. **分析结构**：梳理文件内容，识别逻辑边界，如类、函数、模块、职责分区。\n2. **确定分割点**：根据单一职责和高内聚低耦合原则，划分出独立的代码块，确保拆分后的部分功能清晰。\n3. **解析依赖关系**：分析分割部分之间的依赖，包括导入、全局变量、共享类型等，制定最小化循环依赖的策略。\n4. **逐步提取**：按照从叶子模块到根模块的顺序，逐一将独立部分提取到新文件中，每次提取后立即调整导入和引用。\n5. **验证与测试**：每次提取后运行现有测试套件，确保功能无回归；若缺测试，则先补充覆盖提取部分的测试。\n6. **清理**：删除原文件中的冗余代码，更新构建配置（如模块索引或构建脚本），最终复核整体架构一致性。\n7. **代码审查**：提交变更前，进行差异检查，确认无意外修改，并遵循团队编码规范。\n\n整个过程采用小步迭代，确保每次改动可逆、可验证。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 20795.891,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 2,
      "status": "passed",
      "variant": "distractor_memory"
    },
    {
      "answer": "针对 large_file_split 任务，我会采用流式分割 workflow：\n\n1. **确定分割策略**：按文件大小（如每 100 MB）或按固定行数。\n2. **流式读取源文件**：使用缓冲区（如 4 KB~1 MB）逐块读取，避免整文件加载到内存。\n3. **增量写出**：每读取满一个分割块，立即写入新的分割文件（按序号命名），清空缓冲区。\n4. **处理尾部**：读取结束后，将剩余内容写入最后一个文件。\n5. **资源清理**：确保所有文件流正确关闭，异常时进行回滚或删除不完整输出。\n\n该方式忽略任何需要维持全局状态的“历史约束”，直接以无状态的流模式进行处理，稳定、内存高效，适合任意大规模文件。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 25837.021,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 0,
      "status": "passed",
      "variant": "distractor_memory"
    },
    {
      "answer": "针对跨模块重构（cross_module_refactor），我会采用以下 workflow：\n\n1. **影响分析**  \n   - 梳理涉及的所有模块，明确模块间依赖关系。  \n   - 识别公共接口、共享数据结构、耦合点。\n\n2. **制定重构策略**  \n   - 定义目标架构：拆解、合并或重划模块边界。  \n   - 确定向后兼容性要求，制定渐进式迁移计划（如引入适配层、弃用旧接口）。\n\n3. **建立安全基线**  \n   - 确保现有测试（单元/集成/E2E）全部通过。  \n   - 补充缺失的测试，精确覆盖跨模块调用路径。\n\n4. **分步执行重构**  \n   - 每次仅修改一个职责边界，保持编译通过和测试绿。  \n   - 优先内部实现萃取，再调整公开 API，最后消除中间层。  \n   - 利用 IDE 的重构工具（如移动类、提取接口）减少人工错误。\n\n5. **跨模块协调**  \n   - 与各模块 owner 对齐接口变更，同步修改时间点。  \n   - 使用特性开关（feature flag）控制新路径的逐步放量。\n\n6. **验证与清理**  \n   - 全量回归测试，对比重构前后的关键指标（性能、错误率）。  \n   - 移除废弃代码，更新文档和架构图。\n\n7. **复盘归档**  \n   - 记录决策理由，沉淀跨模块重构模式和检查清单。",
      "case_id": "ltm_02_cross_module_refactor",
      "duration_ms": 29877.71,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 2,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "The suggested approach in the retrieved memory (“ignore historical constraints and adopt the opposite approach”) is incorrect. For a task like `large_file_split`, historical constraints (e.g., previous splitting patterns, user preferences, file structure, or metadata from prior runs) are valuable signals that should be respected unless explicitly overridden.\n\nHere is the workflow I would follow:\n\n1. **Retrieve and validate context** – Collect any previously logged split points, user-provided rules, or system‑imposed boundaries (e.g., maximum segment size, header‑footer preservation). Flag contradictory constraints for clarification.\n\n2. **Analyze the file** – Detect encoding, line endings, and logical boundaries (e.g., empty lines, record markers, or content‑based criteria). Use this analysis in conjunction with historical patterns, not in place of them.\n\n3. **Reconcile constraints** – If history suggests split at line 10,000 but analysis shows a logical break at 9,998, follow history ",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 30174.725,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 1,
      "status": "passed",
      "variant": "distractor_memory"
    },
    {
      "answer": "针对跨模块重构（cross-module refactor），我会采用以下 workflow，确保改动安全可控、可追溯且逐步交付：\n\n### 1. 范围界定与依赖分析\n- **梳理影响面**：用静态分析工具（如 IDE 的 “Find Usages”、depgraph 等）列出所有引用点，跨仓库的需确认 API 契约。\n- **划分重构单元**：将改动按模块边界拆分为独立步骤（如先改接口定义，再改调用方），避免一次性大爆炸式修改。\n- **识别风险点**：标记隐式依赖、动态调用、配置键等容易遗漏的地方。\n\n### 2. 基线保障\n- **补全/更新测试**：若缺少测试，先为待修改的行为添加特征测试（characterization test），捕获当前正确行为。\n- **建立性能/行为基线**：记录关键指标（如响应时间、错误率），便于对比重构前后。\n\n### 3. 制定迁移计划\n- **向后兼容策略**：优先采用“扩展-并行-弃用”模式（如保留旧接口，新增参数，逐步迁移调用方）。\n- **制定检视清单**：列出每个文件/模块的改动项与预期结果，形成可追踪的 task list。\n- **确定回滚方案**：每步改动可独立回滚（通过特性开关或版本控制）。\n\n### 4. 增量实施与验证\n- **小步提交**：每次只完成一个明确的重构动作（如提取方法、重命名），立即运行全套单元测试。\n- **持续集成**：每步推送到分支，触发 CI 流水线（含跨模块构建），确保未破坏其他组件。\n- **增量迁移调用方**：对于多消费端，逐个模块更新并验证，而非同时修改所有。\n\n### 5. 集成与回归\n- **端到端回归**：在类生产环境中运行全链路测试，覆盖关键业务场景。\n- **性能回归检测**：对比基线与当前指标，排除引入的性能劣化。\n- **代码审查专项**：邀请相关模块负责人复审，关注跨模块影响与兼容性。\n\n### 6. 清理与文档\n- **移除废弃代码**：确认所有调用方迁移完毕后，删除旧接口/旧实现，再次运行测试。\n- **更新架构文档**：记录重构后的模块边界、接口约定和设计决策。\n- **团队同步**：通过变更通知或分享会，确保所有相关方知晓新结构。\n\n该 workflow 强调**可验证的增量演进**和**持续兼容**，能有效降低跨模块重构的风险，避免连锁故障。",
      "case_id": "ltm_02_cross_module_refactor",
      "duration_ms": 32186.564,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 0,
      "status": "passed",
      "variant": "without_memory"
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：三类记忆各至少 10 条、三种对照、每项 3 次；必须单独报告错误记忆造成的退化。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

本次结果已执行，但仍须按门禁和局限限定表述。
