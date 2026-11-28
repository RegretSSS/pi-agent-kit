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

- `task_create(cmd, cwd?, name?)`：setsid 拉起 + `~/.agents/tasks/tasks.jsonl`（id/pid/cmd/state/created）+ 输出环形缓冲 `~/.agents/tasks/<id>.log`（上限 256KB 环回）+ 退出码落盘 `<id>.exit`（实例丢失后仍可观测，D25）
- **统一管理面（2026-11-28，见 D25）**：`bg_list(kind?)` / `bg_status(handle?, wait?, until: exit|idle)` / `bg_log(handle, since?)` / `bg_stop(handle)` / `bg_schedule(action)`，句柄 `task:<id>` / `agent:<id|@名>` / `wf:<run>` / `job:<id>`；命令任务、子代理、workflow run、定时任务一套工具，旧工具名不做别名
- **子代理会话标签**（2026-11-28，见 D26）：pi-subagents kit 分支给子会话起名 `<label／name> · workflow:<run id>｜agent · 父:<主会话 id 前 8 位> · <类型>#<agent id 前 8 位十六进制>`；`#`+8 位十六进制收尾不变（通知归属与 a2a-inbox 的判别口径）。`bg_status(agent:<id>)` 原样给出该标签
- **结束自动唤醒**：轮询 2s 检测退出 → `pi.sendMessage` 排队通知（id/name/exit code/tail 200 字符），多条同时结束合并一条
- **通知投递时机**（2026-11-28 收窄，见 D22）：模型回合进行中经 pi 原生 steer 插到当前工具批之后、下次 LLM 调用之前；仅在压缩/分支摘要等「不空闲且无回合在跑」的窗口内扣留，窗口结束即冲洗
- **通知归属**（2026-11-28，见 D23）：只在创建该任务的会话投递——子代理会话（pi-subagents 拉起，会话名以 `#`+8 位十六进制结尾）里的 tasks 实例只结算自己创建的任务，不回收、不发孤儿告警；任何情况下「后台任务结束」不进子代理上下文
- **结算即通报**（2026-11-29，见 D25-13）：退出一经结算就发「后台任务结束」，不管是 `sweep` 定时器还是 bg_status / bg_list / bg_log 抢先结算的；两者分家时，抢先结算的 bg_* 调用会把通知吞掉。守卫：E2E `lints/tasks_notify_not_swallowed_by_bg_query.py`
- 崩溃自恢复：pi 重启后 bg_list 仍见遗留任务；pid 不存活自动标 exited，退出码取自 `<id>.exit`
- 验收：会话内 `task_create` 一个 `sleep 5` → turn 结束 → ~7s 内收到自动唤醒；bg_log 增量读两次游标正确；bg_stop 幂等

## D21 · pi-guard 扩展 `extensions/pi-guard.ts`（bash 命令隔离 + 失控判型，aicontest 工单 b61b1a54a780）

- 范围：bash 工具的每一次调用（含 codemode 嵌套调用与子 agent 会话——同走 `tool_call` 钩子）；落盘后下次会话启动生效，不打断在跑会话
- 事件顺序（以 pi 1.5.2 的 agent-loop 为准）：`tool_execution_start` → `tool_call` → 执行 → `tool_result` → `tool_execution_end`。改写命令与登记跟踪必须同在 `tool_call` 里；`tool_execution_start` 早于 `tool_call`，不能依赖它
- 隔离底座：cgroup v2。`tool_call` 钩子把命令原地改写为 `exec systemd-run --user --scope … -- env -u INVOCATION_ID SHLVL=$((SHLVL-1)) /bin/bash -c <原命令>`，每条命令一个 scope（unit 名 `pi-guard-<pid>-<实例随机段>-<序号>`，同进程多实例不撞名），全部落在 `piguard.slice` 下；PID/进程组/cwd/env/退出码与未包装时一致
- 机器存活线（不看类型）：slice 聚合 `memory.max = ⌊MemTotal×(1−reserveFrac)⌋`（默认 75%，本机约 11.7GB）+ `memory.swap.max=0`；scope 启动后写 `memory.oom.group=1`，触顶时内核挑最大进程所在的**那条命令整组终止**，同 slice 的其他命令不受影响。slice 变空时 systemd 会把限额重置回 `max`，故有命令在跟踪时每个采样节拍校验并补写
- 判型与动作（默认值，均可配）：

| 类型 | 判据 | 动作 |
|---|---|---|
| 空转热循环 | 内联脚本 ∧ 该段无显式时限（`timeout` 只管到它所在的段；工具的 `timeout` 参数管整条）∧ 连续 60s：每拍都有新输出且主导行（数字/时间戳归一后）占非空行 ≥90%、行数 ≥20、近 5s 输出 ≥100KB/s、读入 ≤20KB/s | 停（写 scope 的 `cgroup.kill`），回执附证据并折叠重复输出 |
| 无界累积 | 内存涨到硬顶被内核终止（slice `memory.events` 的 `oom_kill` 在命令末段上升 ∧ 退出码 137） | 内核已停，回执说明硬顶 |
| 合法大内存 | 峰值 anon ≥2GB 且非上述两种结束 | 不动，记一行 |
| 缓慢增长（疑似泄漏） | 5s 包络下沿连续 300s 不回落且增速 ≥1MB/s | 不动，回执标注 |
| 纯空转（单核满载、内存平） | 近 5s 均核数 ∈[0.85,1.15] 连续 300s 且 anon 波动 ≤max(64MB,10%) | 不动，界面提示一次 + 回执标注 |

- 回执：`tool_result` 追加文本块 `[pi-guard] …`（替换 content 必须原样带回 structuredContent）；普通短命令不追加，仅被干预/被标注/历时 ≥30s 的命令追加
- 降级：systemd 用户管理器不可用，或包装后 <1s 失败且文本形如 `Failed to connect to bus` → 仅观测模式（/proc 找 shell、进程树采样、用户态硬顶与同一套空转判据），每 60s 重探；降级的那次调用回执提示「命令没有执行，请重试」
- 日志：`~/.pi/agent/pi-guard/log.jsonl`（`PI_GUARD_LOG_DIR` 可改目录；>1MB 轮转为 `.1`），只记 ≥2s / 非 normal / 非 contained 的命令；`/guard` 显示模式、阈值与最近 10 条
- 配置：`~/.pi/agent/pi-guard.json`，键见 `DEFAULT_CONFIG`（`enabled`、`reserveFrac`、`sliceMaxBytes`（只接受正数）、`slice`、`spinWindowSec`、`minOutBytesPerSec`、`maxInBytesPerSec`、`repeatFrac`…）；`tickMs` 夹到 [50, 5000]，`rateWindowMs` 不超过时间线跨度的一半；测试经 `PI_GUARD_CONFIG` 指定路径
- 测试面：`tests/pi_guard_driver.mjs`（`unit` 纯函数时间线重放；`run` 以假 pi API + 假 bash 工具跑仅观测模式，事件按 pi 的真实顺序发射）；`lints/pi_guard_e2e_containment.py` 用 pi 真实 bash 工具 + 真实 systemd-run 跑隔离模式，slice 名独立于生产（不得含连字符——systemd 把连字符当层级分隔），不可用时跳过并说明；`lints/pi_guard_real_session.py` 起**真实 `pi -p` 进程**（隔离的 agent 目录 + 指向本地脚本化模型服务的自定义提供方，零 token 成本），断言跟踪、限额在位与补回、空转即停在真实事件顺序下成立；`lints/pi_guard_tool_call_order.py` 钉住事件顺序；`lints/pi_guard_unit_names_unique.py` 断言同进程两个扩展实例并发时 unit 名不撞车

## D27 · TUI 单行渲染扩展 `extensions/quiet-tui.ts`（2026-11-28）

- 经 `pi.registerToolRenderer` 把工具调用折叠成单行：每次调用 = 硬空行 + 摘要行（`$ cmd ✓ 1.2s`／`✗` + 错误首行），运行中显示末 3 行预览；Ctrl+O 或鼠标点击展开时委托回 pi 原渲染器
- 接管内建工具、`mcp__*` 与没有自带渲染器的扩展工具；自带渲染器的（Agent、SubagentWorkflow、todo）原样透传
- 内建 codemode（pi 1.7.0 起渲染器挂在工具定义上，D32）：摘要行 = `codemode` + 脚本首个有效行（跳过 `// @options:`）+ `(+N lines)`；运行中一行嵌套调用进度（`N calls · <状态> <最近一次调用> <耗时>`，有失败加 `· K failed`）；出错给剥掉 `Script failed`／`Script error:` 头的真正错误首行；展开时委托回 pi 原渲染器
- 只改显示：不重注册工具、不改 schema、模型可见结果不变；HTML 导出不受损
- 参数文本入行前清 OSC/CSI/C0（单行渲染的安全前提）

## D29 · no-long-sleep 扩展 `extensions/no-long-sleep.ts`（2026-11-07 立于部署位，2026-11-29 收编入仓）

- 用户令（2026-11-07）：会话内禁止 `sleep` 超过 100 秒阻塞自身；起因是会话用 `sleep 1500`／`2700` 阻塞等批，期间用户消息被卡
- `tool_call` 钩子：bash 工具的命令里任何 `sleep` 调用，其时长参数（GNU sleep 接受的十进制形态：整数／小数／前导 `+`／科学计数／`inf`，可带 `s`／`m`／`h`／`d` 后缀；多个参数求和）折算秒数 > `SLEEP_LIMIT_SECONDS`（100）即 `block`，提示回显参数与合计秒数，并指向 `task_create`（结束自动唤醒）或定时任务
- 不做「命令位」语义区分：分隔符枚举追不上 shell 语法（`do … sleep`／`then sleep` 两轮补丁仍漏），bash 工具同步阻塞，`sleep>100` 本身就是阻塞信号——宁误杀（`echo sleep 999` 也拦）不放行
- 不认的形态（接受边界，D29-7）：变量／算术展开给的时长、十六进制浮点、内联解释器里的等待；不同 `sleep` 之间不累加
- 测试面：`tests/no_long_sleep_driver.mjs` 重放原始失败输入（含误杀样例与「先长后短」两条连发，钉住 `g` 正则的 `lastIndex` 重置）；`lints/no_long_sleep.py` 守结构

## D30 · 扩展类型检查进 gate（2026-11-29）

- `extensions/*.ts` 由 `lints/extension_types_check.py` 用 `tsc --noEmit`（strict）对**已装 pi 的声明**检查；基线 `tsconfig.json`，与机器相关的 `paths`/`typeRoots` 由 lint 临时生成；`tests/test_lints.py` 里有一条真跑的测试，本机提交必过；缺 typescript 或缺 pi 时 `skip(原因)`
- 工具渲染器的签名是 `renderCall(args, theme, context)`、`renderResult(result, { expanded, isPartial }, theme, context)`；pi 对渲染器抛错静默回退，签名写错不会报错、只会让自定义渲染失效
- `StringEnum` 出来的工具入参是 `unknown`，在 execute 开头按类型收窄

## 部署（每件完成即部署+实测，独立 commit）

- desktop：`extensions/*.ts` → `~/.pi/agent/extensions/`；MCP 同步实跑；AGENTS.md 落位
- `deploy.sh` 一键部署 desktop（幂等；laptop 已停用不涉及）
- `a2a-inbox.ts` 不归本仓（归 a2a-mailbox hub 仓，node-2 维护）：仓内不保存、不部署，`lints/foreign_owned_extensions_absent.py` 守着（D28）

## 开发铁律（沿用）

代码零注释（要注释=改名）；每发现一个问题新建一条 lint；热路径对象字面量/闭包/new 谨慎（防碎片）；conventional commits；测试过才提交；一切选型决策记 DECISIONS.md。无人值守模式：SPEC 未覆盖的自行决策；花钱/破坏性/对外发布的停下来列入最终汇报。
