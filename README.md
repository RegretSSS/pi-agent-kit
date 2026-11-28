# pi-agent-kit

把 [pi](https://github.com/earendil-works/pi-coding-agent) 变成可长期生产使用的编码 agent:跨会话记忆、后台任务、上下文治理、机械可验证的工程纪律,一条命令部署。

## 采用的手段与措施

- **问题即 lint**:每个踩过的坑固化成一条机械规则(一规则一文件:结构约定 → pattern 源码扫描,行为语义 → behavioral 加载真模块重放原始失败输入),`pytest + run-lints.sh` 双 gate 全绿才允许提交
- **memory 系统**:`node:sqlite` FTS5 trigram 中文全文检索、双桶 scoped(项目桶按 cwd 映射不进仓/全局桶)、查重闸(规则腔分流到 lints)、增量更新(append 段落/命名小节替换,围栏感知)、项目全量+全局分层索引注入、trigram 自动召回(recall 消息,会话内不重复,compact 后重注入)
- **tasks 后台任务**:append-only journal 单一真相、跨会话状态增量重放、pid 复用防护(`/proc` starttime)、owner 必收通知
- **compact 闭环**:模型在自然工作边界自主发起压缩(摘要强制携带 `<fold-index>` 索引头,单活代际链,蒸馏并集),压缩完成自动注入 `[compact 完成]` 续作唤醒词(按 fold-index 重定位,willRetry 时不扰)
- **context-gauge 自主运行监控**:工具结果按需附加水位+时钟行(15min 时间档/5% 水位档/30% 提示 50% 催压缩/50% 后每工具直报),TUI footer 常显——频控对齐 CC gauge_hook
- **pi-guard**:每条 bash 命令跑在各自的 cgroup scope 里(slice 聚合内存硬顶、禁 swap),对失控的临时脚本判型——空转热循环即停并附证据,无界累积被内核终止时在回执里说明,合法大内存与缓慢增长只标注不动;systemd 不可用时降级为仅观测
- **quiet-tui**:工具调用折叠成单行(自写;同一实测台 101 行 → 18 行),codemode 也收(脚本首行 + 嵌套调用进度一行),Ctrl+O 展开时委托回 pi 原渲染器;只改显示,不改 schema、模型可见结果不变
- **两个拦截扩展**:`no-long-sleep`——会话内 `sleep` 折算超过 100 秒即拦,指向 `task_create`/定时任务;`no-rogue-background`——`nohup`/`setsid`/`disown`/结尾 `&` 的后台化即拦,不允许后台跑完不通报的任务
- **后台工具统一(D25)**:task_create + bg_list / bg_status / bg_log / bg_stop / bg_schedule——命令任务、子代理、workflow run、定时任务一套句柄(12 个工具收到 6 个);子代理与 workflow 走 pi-subagents kit 分支的 RPC 通道,不可达时回落本机 journal
- **AGENTS.md 管理节部署**:CommonMark 围栏感知的节级替换,幂等,节外用户内容原样保留
- **codemode 选取决策树**:≥3 轮工具往返的目标编译成脚本,中间态留在脚本内只 return 结论
- **七轮对抗性审计**:21 项确认缺陷全部修复并钉回归(含 6 次"修复引入回归"由轻量回归轮抓出),详见 `DECISIONS.md`

## 配合使用的项目

- [pi](https://github.com/earendil-works/pi-coding-agent) — 宿主编码 agent
- [@tintinweb/pi-subagents](https://github.com/tintinweb/pi-subagents) — subagent 与 SubagentWorkflow 编排;后台工具统一依赖它 kit 分支的补丁(D24),没有补丁时回落本机 journal
- 模型侧:任意 Anthropic/OpenAI 兼容端点(生产实测 GLM 系列)

## 安装

一条命令(克隆到 `~/.pi-agent-kit` 并部署):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/RegretSSS/pi-agent-kit/master/quick-install.sh)
```

等价手动方式:

```bash
git clone https://github.com/RegretSSS/pi-agent-kit ~/.pi-agent-kit
~/.pi-agent-kit/deploy.sh
```

部署内容:`~/.agents/AGENTS.md` 管理节、`extensions/` 下的全部扩展(名单见「结构」)、`~/.agents/skills/` 下的 queue-watch 与 subagent-workflows、pi-subagents 的 kit 补丁同步;装有 Claude Code 的机器自动同步 MCP server 配置。重启 pi 生效。

可选:在你的项目仓启用提交 gate(双钩子:lint gate + 拒绝 AI 署名):

```bash
~/.pi-agent-kit/scripts/enable-gate.sh /path/to/your-repo
```

## 结构

```
agents-md/    AGENTS.md 管理节版本化真相
extensions/   pi 扩展(compact-tool / context-gauge / memory / no-long-sleep / no-rogue-background / pi-guard / quiet-tui / tasks / todo)
lints/        机械规则(一规则一文件,run-lints.sh 自动发现)
package.json / tsconfig.json   类型检查(devDependency typescript;lints/extension_types_check.py 对已装 pi 的声明跑 tsc,D30)
scripts/      run-lints / enable-gate / sync-mcp / sync-subagents-kit,另有一次性的记忆迁移工具
skills/       queue-watch / subagent-workflows
tests/        pytest(pytest 驱动 node 直载 TS 模块;每条 lint 的反向用例也在这里)
DECISIONS.md  全部选型决策与接受边界
```
