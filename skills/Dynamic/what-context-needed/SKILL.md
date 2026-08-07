---
name: what-context-needed
description: 用于“上下文 上下文 needed”的工程工作流。适用于通用代码开发相关的代码开发、测试、调试、集成与维护任务。
---
## 中文摘要
用于“上下文 上下文 needed”的工程工作流。适用于通用代码开发相关的代码开发、测试、调试、集成与维护任务。


# What Context Do You Need?

Before answering my question, tell me what files you need to see.

## My Question

{{question}}

## Instructions

1. Based on my question, list the files you would need to examine
2. Explain why each file is relevant
3. Note any files you've already seen in this conversation
4. Identify what you're uncertain about

## Output Format

```markdown
## Files I Need

### Must See (required for accurate answer)
- `path/to/file.ts` — [why needed]

### Should See (helpful for complete answer)
- `path/to/file.ts` — [why helpful]

### Already Have
- `path/to/file.ts` — [from earlier in conversation]

### Uncertainties
- [What I'm not sure about without seeing the code]
```

After I provide these files, I'll ask my question again.
