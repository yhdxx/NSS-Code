# 前缀缓存命中率评测

- 状态：`not_run`
- 指标 ID：`prefix_cache`

## 指标定义

在 system prompt 与工具 schema 稳定的连续请求中，测量服务商返回的缓存命中 token 占比；预热请求不计入。该评测不依赖或假设项目图谱消息常驻。

## 计算公式

- 缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)

## 数据集与样本

```json
{
  "sample_count": 0
}
```

## 测试环境

```json
{
  "base_url": "",
  "generated_at": "2026-08-01T17:24:59+0800",
  "git_commit": "",
  "git_dirty": "",
  "model": "",
  "platform": "",
  "python": "",
  "random_seed": "",
  "repeats": "",
  "run_id": "not-run"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-prefix-cache
```

## 结果与置信区间

```json
{
  "reason": "尚未执行新版标准评测",
  "status": "not_run"
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

不可使用量化结论（status=not_run）：尚未执行新版标准评测
