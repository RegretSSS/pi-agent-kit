# pi-agent-kit 开发规格（主控签发 2026-11-04）

目标：为 desktop 的 pi（@earendil-works/pi-coding-agent 1.5.0，~/.local/bin/pi）补齐四件基础设施 + 一件配置迁移。按 D1→D2→D4（可与 D1/D2 并行）→D3→D5 顺序实施，逐件 gate+commit+部署+实测，全部完成后待命汇报。

## 环境事实（已核实）

- desktop pi：`~/.local/bin/pi`（node 24/npm 11）；扩展目录 `~/.pi/agent/extensions/`，现有 `compact-tool.ts`（registerTool("compact",{brief}) 立即返回 scheduled + `agent_settled` 时 ctx.compact）——**收编入本仓 `extensions/compact-tool.ts` 作为源，部署脚本负责拷出**，行为不变
- pi 扩展 API 本地参考源（读它，别猜）：`/home/remedy/.local/share/pnpm`…查不到就 `find ~/.local ~/.pi -name extensions.md -path "*pi-coding-agent*"`；配套 `examples/extensions/`（subagent/trigger-compact/custom-compaction/todo 都是现成范文）
- 工具签名：`execute(toolCallId, params, signal, onUpdate, ctx)` 返回 `{content:[{type:"text",text}],details:{}}`；参数 schema 用 `import { Type } from "typebox"`
- 事件面可用：`session_start/session_before_compact/agent_settled/turn_end/tool_call/tool_result/before_provider_request`
- 已装 pi 包（勿动）：@tintinweb/pi-subagents、billion-context
- a2a-mailbox 仓在 `~/workspace/a2a-mailbox`（lints/run-lints.sh 风格参照，只读勿改）。laptop 侧（回程 ssh/halle）已停用，不做双端部署，deploy.sh 只管 desktop

## D1 · 全局 AGENTS.md（先做）

- 目标 `~/.agents/AGENTS.md`：若已存在（可能含 8 行 aliyun 运维口径）**保留原内容，合并追加**；不存在则创建
- 新增「问题即 lint」节：
  - **四分流器**：判定性知识（可写成"看到 X 就 fail"）→ lints/；描述性事实（资产/端点/结构）→ memory(type=reference)；脱离语境无法机械判定的判断题 → memory(type=feedback)；战史/batch 记录 → 萃取教训后归档
  - **lint 分类准则**：结构约定→pattern（源码扫描）；行为语义→behavioral（加载真模块+临时环境+重放原始失败输入）；跨端闭环→E2E。守护行为语义的 pattern lint 必须升格 behavioral
- 同一份存本仓 `agents-md/snippet.md` 作版本化真相（部署脚本负责拷出）

## D2 · lints 闸 + commit CI

- 本仓 `lints/` 一规则一文件 + `scripts/run-lints.sh`（风格参照 a2a-mailbox 同名件）
- 种子规则三条：
  1. `commit-must-clear-git-status`：提交时 `git status --porcelain` 非空即 fail（工作树必须收干净）
  2. `no-secrets`：sk-/ghp_/github_pat_/AKIA/xox/zai 凭据形态全树扫描，豁免 lint 定义文件自身
  3. `agentsmd-index-consistency`：若 `~/.agents/memory` 存在，MEMORY.md 每行链接指向的文件必须存在，反之每文件必有索引行
- `scripts/enable-gate.sh <repo>`：向目标仓装 pre-commit 钩子（调用本仓 run-lints.sh），opt-in，默认不给本机任何已有仓装
- `.github/workflows/lints.yml`：push/PR 跑 run-lints.sh
- gate 定义：pytest（tests/）全绿 + run-lints.sh 全绿

## D4 · MCP 同步（可与 D1/D2 并行）

- 探明 desktop CC 的 MCP 配置实际位置（`~/.claude.json` 的 mcpServers 段或 `~/.claude/settings*.json`），抽取 `chrome-devtools` 与 `zai`（截图/search/fetch，名字以实际为准）两个 server 定义
- `scripts/sync-mcp.sh`：读 CC 配置 → 幂等并入 pi 的 `~/.pi/agent/mcp.json`（**保留现有 mailbox 条目**）→ 打印结果
- 验收：新 pi 会话中两组 MCP 工具可见，实调一次（截图或 search 任一）

## D3 · memory 扩展 `extensions/memory.ts`（核心件）

- 存储：`~/.agents/memory/*.md` 单一真相；frontmatter `name/description/type(user|project|feedback|reference)`；`MEMORY.md` 索引一行一条（`- [name](file) — 钩子`）
- **索引注入**：`before_provider_request` 把 MEMORY.md 全文并入 system prompt（验证不破坏 pi 原生 system prompt；备选 session_start appendEntry——两者择优，决策记 DECISIONS.md）
- `memory_save(name, description, type, body)` handler 四闸：
  1. type 必填；type=problem 或 description/body 呈现"可检测错误形态"特征时反问分流：拒绝写入，返回"这条该去 lints/AGENTS.md"+模板
  2. FTS5 以 name+description 查重，高分命中 → 拒绝新建，返回旧条路径要求走更新
  3. 写文件 + **自动重建 MEMORY.md**（模型不可手写索引）
  4. type=project 自动记 `expiry_at=now+30d`，过期未引用进归档候选（不物理删）
- `memory_search(query, top_k=5)`：FTS5 bm25 + trigram tokenizer（中文/子串友好）
- `agent_settled` 无 LLM 记账：本轮 tool_result 错误、非零退出命令、token 增量 → 追加 `~/.agents/memory/.candidates.jsonl`
- sqlite 选型：优先 node:sqlite（验证 FTS5 可用，Node 24），不行降级 python3 子进程或纯 JS BM25——决策记 DECISIONS.md
- 备好 `scripts/migrate-cc-memory.py`（**暂不执行**）：desktop CC `~/.claude/projects/*/memory/` → 四分流 → 目标布局
- **死锁红线：任何工具 execute 内禁止等待跨回合回调/事件**
- 验收：新会话索引自动可见；save 新建→索引自动更新；查重路径实测（重复提交被导向更新）；search 中文与子串各命中一次

## D5 · 后台任务扩展 `extensions/tasks.ts`

- `task_create(cmd, cwd?, name?)`：setsid 拉起 + `~/.agents/tasks/tasks.jsonl`（id/pid/cmd/state/created）+ 输出环形缓冲 `~/.agents/tasks/<id>.log`（上限 256KB 环回）
- `task_output(id, since?)`：自 offset 增量读，返回新内容+新游标
- `task_stop(id)`：SIGTERM→5s→SIGKILL，幂等；`task_list()`
- **结束自动唤醒**：轮询 2s 检测退出 → `pi.sendMessage` 排队通知（id/name/exit code/tail 200 字符），多条同时结束合并一条
- 崩溃自恢复：pi 重启后 task_list 仍见遗留任务；pid 不存活自动标 exited
- 验收：会话内 `task_create` 一个 `sleep 5` → turn 结束 → ~7s 内收到自动唤醒；增量读两次游标正确；task_stop 幂等

## 部署（每件完成即部署+实测，独立 commit）

- desktop：`extensions/*.ts` → `~/.pi/agent/extensions/`；MCP 同步实跑；AGENTS.md 落位
- `deploy.sh` 一键部署 desktop（幂等；laptop 已停用不涉及）

## 开发铁律（沿用）

代码零注释（要注释=改名）；每发现一个问题新建一条 lint；热路径对象字面量/闭包/new 谨慎（防碎片）；conventional commits；测试过才提交；一切选型决策记 DECISIONS.md。无人值守模式：SPEC 未覆盖的自行决策；花钱/破坏性/对外发布的停下来列入最终汇报。
