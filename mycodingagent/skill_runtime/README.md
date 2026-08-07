# Skill 运行时

负责 Skill 生命周期、索引、检索与路由。每个配置的 Skill 基础根目录必须包含：

- `fixed/`：启动时将 `skill_name + name + description` 卡片稳定注入 system prompt，不参与检索与 LRFU。
- `Dynamic/`：参与向量/关键词检索与用户级、会话级 LRFU；完整正文只通过 `invoke_skill` 加载。

Runtime 对 Dynamic Skill 的 `name + description` 计算指纹。只有指纹变化时才调用总结模型并更新
`dynamic_skill_summary.json`，随后把精简能力摘要注入 system prompt，供模型判断是否需要检索 Skill。

长期记忆中经用户批准的 `skill_candidate` 会物化到用户根目录的 `Dynamic/`；失败状态在下次启动回填时重试。
不支持旧的根目录平铺 Skill、默认 Skill 或 pin 表。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
