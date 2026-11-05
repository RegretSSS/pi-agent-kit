# pi-agent-kit

把 [pi](https://github.com/earendil-works/pi-coding-agent) 变成可长期生产使用的编码 agent:跨会话记忆、后台任务、上下文治理、机械可验证的工程纪律,一条命令部署。

## 采用的手段与措施

- **问题即 lint**:每个踩过的坑固化成一条机械规则(13 条:结构约定 → pattern 源码扫描,行为语义 → behavioral 加载真模块重放原始失败输入),`pytest + run-lints.sh` 双 gate 全绿才允许提交
- **memory 系统**:`node:sqlite` FTS5 trigram 中文全文检索、查重闸(规则腔分流到 lints)、增量更新(append 段落/命名小节替换,围栏感知)、热度 top-K 注入——system prompt 开销 O(1) 有界,磁盘索引全量保留
- **tasks 后台任务**:append-only journal 单一真相、跨会话状态增量重放、pid 复用防护(`/proc` starttime)、owner 必收通知
- **compact 工具**:模型在自然工作边界自主发起压缩,摘要强制携带 `<fold-index>` 索引头(单活代际链,蒸馏并集)
- **context-gauge 水位可见性**:每 turn 首个工具结果后附加一行上下文水位(越过 75%/90% 线同行升级为压缩提示),TUI footer 常显——零缓存损失,水位史随 compact 自清理
- **history 跨会话检索**:检索 billion-context 的压缩块摘要(侧车快照降级、预算轮廓+关键词窗口钻取、会话歧义候选拒绝)
- **subagent-jobs 查询桥**:只读镜像 pi-subagents 定时任务 store(job_list),agent 侧可自查闹钟死活
- **AGENTS.md 管理节部署**:CommonMark 围栏感知的节级替换,幂等,节外用户内容原样保留
- **codemode 选取决策树**:≥3 轮工具往返的目标编译成脚本,中间态留在脚本内只 return 结论
- **七轮对抗性审计**:21 项确认缺陷全部修复并钉回归(含 6 次"修复引入回归"由轻量回归轮抓出),详见 `DECISIONS.md`

## 配合使用的项目

- [pi](https://github.com/earendil-works/pi-coding-agent) — 宿主编码 agent
- [billion-context](https://github.com/ranxianglei/billion-context) — 上下文压缩代理(模型驱动的增量分层压缩;本项目 `history` 工具检索其落盘摘要)——依其许可证附加条款在此致谢
- [@tintinweb/pi-subagents](https://github.com/tintinweb/pi-subagents) — subagent 与 SubagentWorkflow 编排
- 模型侧:任意 Anthropic/OpenAI 兼容端点(生产实测 GLM 系列;pi 原生压缩与 billion-context 的 `compress` 分工互补)

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

部署内容:`~/.agents/AGENTS.md` 管理节、`~/.pi/agent/extensions/` 四个扩展(memory / tasks / compact / history)、`~/.agents/skills/subagent-workflows`;装有 Claude Code 的机器自动同步 MCP server 配置。重启 pi 生效。

可选:在你的项目仓启用提交 gate(双钩子:lint gate + 拒绝 AI 署名):

```bash
~/.pi-agent-kit/scripts/enable-gate.sh /path/to/your-repo
```

## 结构

```
agents-md/    AGENTS.md 管理节版本化真相
extensions/   pi 扩展(memory / tasks / compact-tool / history / a2a-inbox / context-gauge / subagent-jobs)
lints/        机械规则(一规则一文件,run-lints.sh 自动发现)
scripts/      run-lints / enable-gate / sync-mcp / quick-install
skills/       subagent-workflows 编排引导
tests/        96 项(pytest 驱动 node 直载 TS 模块)
DECISIONS.md  全部选型决策与接受边界
```
