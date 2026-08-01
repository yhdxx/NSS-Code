# 前缀缓存命中率评测

- 状态：`passed`
- 指标 ID：`prefix_cache`

## 指标定义

在 system prompt 与工具 schema 稳定的连续请求中，测量服务商返回的缓存命中 token 占比；预热请求不计入。该评测不依赖或假设项目图谱消息常驻。

## 计算公式

- 缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/prefix_cache_cases.jsonl",
  "dataset_sha256": "d392fb85d7015f02fb1a28c3b897821e4ff7454f4293e7265f15438b6abaa8a5",
  "sample_count": 90,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T18:40:50+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "standard-prefix-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-prefix-cache --dataset tests/eval/datasets/prefix_cache_cases.jsonl --repeats 3
```

## 结果与置信区间

```json
{
  "available_run_count": 90,
  "case_count": 30,
  "hit_rate_ci95": {
    "high": 0.986615,
    "low": 0.986586,
    "mean": 0.986601
  },
  "mean_session_hit_rate": 0.986601,
  "p50_session_hit_rate": 0.986659,
  "p95_session_hit_rate": 0.986659,
  "reason": "",
  "repeats": 3,
  "resume_conclusion": "30 个会话、每会话 1 次预热和 3 次正式测量中，服务商原生字段统计的 token 加权前缀缓存命中率为 98.66%；system prompt 与工具 schema 固定，项目图谱未常驻 message。",
  "run_count": 90,
  "token_weighted_hit_rate": 0.9866,
  "warmup_excluded": true
}
```

## 失败、超时与异常样例

```json
{
  "count": 0,
  "examples": []
}
```

## 局限与有效性威胁

- 结论门禁：服务商必须返回 hit/miss token，至少 30 个会话且每会话完成预热与 3 次测量；否则 93.5% 不得用于简历。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

30 个会话、每会话 1 次预热和 3 次正式测量中，服务商原生字段统计的 token 加权前缀缓存命中率为 98.66%；system prompt 与工具 schema 固定，项目图谱未常驻 message。
