# myCodingAgent 有效性测试说明

生成时间：2026-07-27  
测试原则：先生成测试集，再执行真实组件/真实 API 测试，最后根据结果生成结论。  
结果来源：`tests/eval/datasets/*.jsonl` 与 `tests/eval/results/*.jsonl`。

## 总览

| 测试模块 | 测试集规模 | 执行状态 | 核心结论 |
|---|---:|---|---|
| BGE 嵌入服务预检 | 3 条 embedding 输入 | 已执行 | `bge-m3` 服务可用，返回 1024 维向量 |
| Capability Router 能力路由 | 20 条 query | 已执行 | 路由准确率 100% |
| Context Virtualization 上下文虚拟化 | 12 组长对话测试集，已抽样执行 2 组 | 已执行小样本 | 虚拟化模式保持 100% 早期约束召回，且显著低于 raw 上下文成本 |
| Long-Term Memory Workflow 长期记忆 | 6 个 workflow 场景，已抽样执行 3 个 | 已执行小样本 | 注入 workflow 记忆后准确率 100%，无记忆基线 0% |
| BatchRecoverContext 恢复工具 | 10 条恢复测试集，已抽样执行 3 条 | 已执行小样本 | 恢复工具调用率 100%，答案准确率 100% |
| 500+ Skill Router | 520 个 Skill，100 条 query | 已执行 | Recall@1/3/5 与 MRR 均为 100% |
| Multi-Agent 多智能体 | 24 个代码任务，48 次真实执行 | 已执行 | direct 与 multi-agent 准确率均为 100%，但多智能体耗时和工具调用成本显著更高 |

## 1. BGE 嵌入服务预检

| 项目 | 内容 |
|---|---|
| 测试模块 | BGE embedding 服务 |
| 测试指标 | 服务可用性、返回数量、向量维度、请求耗时 |
| 测试方式 | 调用 `http://127.0.0.1:11434/api/embed`，使用 `bge-m3` 对 3 条中文能力描述生成 embedding |
| 测试结果 | 返回 3 条 embedding，向量维度为 1024，请求耗时约 2115.2ms |
| 测试结论 | BGE 服务可用于正式 Skill 语义检索评测，未使用 hash embedding 降级结果 |

## 2. Capability Router 能力路由

| 项目 | 内容 |
|---|---|
| 测试模块 | Capability Router / 能力发现 |
| 测试指标 | 目标能力识别准确率、Skill 推荐命中、MCP server 推荐命中、基础工具任务是否保持可处理 |
| 测试方式 | 生成 20 条 query，覆盖文件读取、文件搜索、Shell、Skill、MCP、上下文恢复等能力类型；通过 Capability Router 判断是否能提供目标能力 |
| 测试结果 | 20 条 case 全部通过，准确率 100% |
| 测试结论 | 当前能力路由可以区分核心工具、Skill 与 MCP 能力；在测试覆盖范围内，能将明确任务路由到正确能力类型 |

典型样例：

| Query | 预期能力 | 实际推荐 |
|---|---|---|
| 读取当前项目 README 并总结 | ReadFile | 基础工具任务，判定通过 |
| 搜索所有调用 BatchRecoverContext 的地方 | Grep | 基础搜索任务，判定通过 |
| 把项目经历改成简历责任描述 | Skill | 推荐 `skill_resume_writer` |
| 查看 GitHub issue 列表 | MCP | 推荐 `github` MCP server |

## 3. Context Virtualization 上下文虚拟化

| 项目 | 内容 |
|---|---|
| 测试模块 | 冷/热工作区与上下文虚拟化 |
| 测试指标 | 早期需求召回率、不同上下文模式的 prompt 长度、recent-only 失忆对照 |
| 测试方式 | 生成 12 组 100+ 轮长对话测试集，早期注入项目约束，中后期插入大量无关对话和工具输出；抽样执行 2 组，对比 `raw`、`virtualized`、`summary_baseline`、`recent_only` |
| 测试结果 | `raw`、`virtualized`、`summary_baseline` 准确率均为 100%，`recent_only` 为 0% |
| 测试结论 | 虚拟化上下文能够保留会话初期关键约束；相比 raw 模式显著降低上下文输入规模，同时明显优于仅保留最近轮次的策略 |

模式对比：

| 模式 | 准确率 | 平均 Prompt 字符数 | 说明 |
|---|---:|---:|---|
| raw | 100% | 55,545 | 完整保留历史，准确但上下文成本最高 |
| virtualized | 100% | 16,793 | 保留用户/模型关键历史，虚拟化工具输出，成本显著下降 |
| summary_baseline | 100% | 4,087 | 摘要基线在本测试中可召回明确早期约束 |
| recent_only | 0% | 3,985 | 只保留最近消息会丢失早期需求 |

## 4. Long-Term Memory Workflow 长期记忆

| 项目 | 内容 |
|---|---|
| 测试模块 | 长期记忆中的 workflow_candidate |
| 测试指标 | 有记忆准确率、无记忆准确率、workflow 是否影响模型工作流程 |
| 测试方式 | 生成 6 个 workflow 场景，抽样执行 3 个；分别测试不注入长期记忆与注入 workflow_candidate 后模型是否采用正确流程 |
| 测试结果 | 注入长期记忆后准确率 100%，无记忆基线准确率 0% |
| 测试结论 | workflow 记忆能够显著改变模型执行策略，使模型在相似任务中采用用户反复纠正后的流程 |

已执行 workflow：

| 场景 | 记忆内容 | 有记忆结果 | 无记忆结果 |
|---|---|---:|---:|
| 大文件拆分 | 先一次性定位所有边界，再批量写入，避免逐模块重复读取 | 通过 | 未通过 |
| 跨模块重构 | 先跑现有测试，再改公共接口，最后跑完整回归 | 通过 | 未通过 |
| API 链路修改 | 先确认 route / service / repository / test 调用链 | 通过 | 未通过 |

## 5. BatchRecoverContext 恢复工具

| 项目 | 内容 |
|---|---|
| 测试模块 | 虚拟化工具输出恢复链路 |
| 测试指标 | 恢复工具调用率、答案准确率、是否使用可见 `context_id` |
| 测试方式 | 生成 10 条恢复 case，抽样执行 3 条；每条 case 将隐藏配置埋入大型历史工具输出，只向模型提供虚拟化 metadata 和 `context_id`，要求模型调用 `BatchRecoverContext` 恢复原文后回答 |
| 测试结果 | 3 条 case 全部调用恢复工具，工具调用率 100%，答案准确率 100% |
| 测试结论 | 在需要历史原文时，模型能够根据虚拟化 metadata 调用 `BatchRecoverContext`，并从恢复内容中提取精确信息 |

已执行样例：

| Case | 目标值 | 是否调用恢复工具 | 是否答对 |
|---|---|---:|---:|
| `rec_01` | `RECOVERY_SECRET_01=VALUE-9001` | 是 | 是 |
| `rec_02` | `RECOVERY_SECRET_02=VALUE-9002` | 是 | 是 |
| `rec_03` | `RECOVERY_SECRET_03=VALUE-9003` | 是 | 是 |

## 6. 500+ Skill Router

| 项目 | 内容 |
|---|---|
| 测试模块 | Skill Router 大规模检索 |
| 测试指标 | Recall@1、Recall@3、Recall@5、MRR、Top5 无关召回数量、耗时 |
| 测试方式 | 生成 520 个仅包含 `name + description` 的 Skill，覆盖前端、后端、内容、数据、Agent、DevOps 等领域；生成 100 条 query，使用 BGE-M3 + Milvus 混合检索执行 Top-K 召回测试 |
| 测试结果 | Recall@1 = 100%，Recall@3 = 100%，Recall@5 = 100%，MRR = 100%，Top5 平均无关召回数 0.04，耗时约 215.8s |
| 测试结论 | 在 500+ Skill 场景下，当前 Skill Router 能准确召回目标 Skill，并将无关 Skill 控制在较低水平 |

核心指标：

| 指标 | 结果 |
|---|---:|
| Skill 数量 | 520 |
| Query 数量 | 100 |
| Recall@1 | 1.0 |
| Recall@3 | 1.0 |
| Recall@5 | 1.0 |
| MRR | 1.0 |
| Avg Unrelated Top5 | 0.04 |
| 总耗时 | 215.816s |

## 7. Multi-Agent 多智能体

| 项目 | 内容 |
|---|---|
| 测试模块 | 多智能体协作有效性 |
| 测试指标 | direct mode 与 multi-agent mode 的准确率、平均耗时、平均工具调用次数、隐藏测试通过率 |
| 测试方式 | 对 24 个代码任务执行完整 A/B：小规模项目 12 个、中规模项目 12 个；每个任务分别运行 direct mode 和 multi-agent mode，共 48 次真实执行；每次执行后运行 pytest 验证 |
| 测试结果 | direct 准确率 100%，multi-agent 准确率 100%；direct 平均耗时 21.0418s，multi-agent 平均耗时 322.4428s；direct 平均工具调用 8.2917 次，multi-agent 平均工具调用 27.5417 次 |
| 测试结论 | 当前测试集难度下，多智能体没有体现准确率优势，但显著增加耗时和工具调用成本；因此简单/中等确定性修复任务不应默认走多智能体，多智能体更适合高风险、影响范围不清、需要独立计划/测试/审查闭环的复杂任务 |

分规模结果：

| 项目规模 | 模式 | Case 数 | 准确率 | 平均耗时 | 平均工具调用 |
|---|---|---:|---:|---:|---:|
| small | direct | 12 | 100% | 13.9752s | 6.1667 |
| small | multi-agent | 12 | 100% | 219.4178s | 22.4167 |
| medium | direct | 12 | 100% | 28.1083s | 10.4167 |
| medium | multi-agent | 12 | 100% | 425.4678s | 32.6667 |

## 总体结论

| 能力 | 当前证据强度 | 结论 |
|---|---|---|
| BGE 嵌入 | 强 | 服务可用，可支撑语义检索 |
| Capability Router | 中-强 | 20 条能力路由 case 全部通过 |
| 上下文虚拟化 | 中 | 小样本显示虚拟化可保持早期需求召回并降低上下文成本 |
| 长期记忆 workflow | 中 | 小样本显示 workflow 记忆能显著改善模型流程选择 |
| 恢复工具链 | 中 | 小样本显示 BatchRecoverContext 可按需恢复历史工具输出 |
| 500+ Skill 路由 | 强 | 520 Skill / 100 query 正式评测全部命中目标 Skill |
| 多智能体 | 中-强 | 24 个任务完整 A/B 显示准确率均为 100%，但 multi-agent 成本显著更高，适合复杂高风险任务而非普通确定性修复 |

因此，当前测试结果可以支撑以下项目表述：

- 构建了基于 BGE-M3 + Milvus 的大规模 Skill 检索与路由能力。
- 构建了 Capability Router，用于在核心工具、Skill、MCP、恢复工具等能力之间进行选择。
- 构建了上下文虚拟化与恢复机制，能够在长对话中降低上下文成本并保留早期关键信息。
- 构建了 workflow 长期记忆机制，能够在相似任务中复用用户纠正后的工作流程。

当前仍需补充的数据：

- 上下文虚拟化 12 组全量测试结果。
- 长期记忆 workflow 6 组全量测试结果。
- 恢复工具 10 组全量测试结果。
