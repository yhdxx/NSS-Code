# 终端界面

负责输入、渲染、历史展示、会话选择和用户确认，不持有业务状态。

`output.py` 是终端输出入口：最终模型回答用 Rich Markdown 渲染；模型等待期间显示 `H-Agent:分析中.` / `..` / `...` 动画；只读工具执行期间显示读取/搜索状态。

颜色约定：普通文本灰色；Markdown 标题亮白加粗；Search/Read 蓝色；Bash 低危绿色、需审批黄色、高危红色；EditFile/写入 diff 中旧内容黄色、新内容绿色；错误红色。

历史恢复由 `history.py` 调用同一套渲染器，`/resume`、`/fork` 和 `/rewind conversation|both` 会重新展示恢复后的用户消息、Markdown 答案、工具调用和工具输出预览。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
