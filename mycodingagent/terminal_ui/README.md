# 终端界面

负责输入、渲染、历史展示、会话选择和用户确认，不持有业务状态。

`output.py` 是终端输出入口：最终模型回答交给高亮器识别后按 Markdown 渲染；模型等待期间显示 `H-Agent:分析中.` / `..` / `...` 动画；只读工具执行期间显示读取/搜索状态。

`highlighters/` 集中放置语言识别器、Markdown 高亮器、默认高亮器，以及 Python、Java、C++、C、Go、Rust、JavaScript、TypeScript、HTML 等代码高亮器。终端展示使用这些渲染器；真实文件写入仍保持原始文本，不写入 ANSI/Rich 标记。

颜色约定：最终模型回答亮白；工具参数和普通预览灰色；Markdown 标题亮白加粗；Search/Read 动词蓝色、路径参数灰色；Bash 低危绿色、需审批黄色、高危红色；EditFile/写入 diff 中旧内容黄色、新内容绿色；错误红色。

输入框由 `input.py` 驱动，`input_document.py` 负责普通文本与粘贴 token 的分段模型。粘贴内容在编辑期间显示为浅蓝色 `[Pasted Content N chars]`，删除时作为整体删除，提交给模型时展开为真实内容。

快捷键由 `keymap.py` 管理，默认支持 Enter 提交、Ctrl+J 换行、Tab/Shift+Tab 缩进/取消缩进、Alt+A 全选、Ctrl+C 复制选区或中断、Ctrl+V 粘贴。用户可通过 `MYCODINGAGENT_KEYMAP` 指向 JSON 文件覆盖 action 绑定。

历史恢复由 `history.py` 调用同一套渲染器，`/resume`、`/fork` 和 `/rewind conversation|both` 会清理 Agent 可控区域并重新展示恢复后的用户消息、Markdown 答案、工具调用和工具输出预览；`/clear` 也会重绘 Agent 区域后显示新会话状态，不发送清除 scrollback 的控制序列。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
