# DECISIONS.md

SPEC 未覆盖处的自行决策记录。格式:编号、决策、理由。

## D1

- **D1-1 部署合并语义**:`~/.agents/AGENTS.md` 落位时,「## 问题即 lint」节固定为文件最后一节;部署 = 刷新该节(从节标题到文件尾),节外内容原样保留;目标不存在则整文件创建。理由:单节替换可幂等重放,避免整文件覆盖吞掉本机手工内容;节放最后使"到文件尾"边界成立。
- **D1-2 gate 起算时点**:pytest + run-lints.sh 的 gate 自 D2 交付后生效;D1 为纯文档件,以 pytest 全绿提交。理由:gate 本身是 D2 的交付物,不可回溯要求。

## D2

- **D2-1 lint 文件名 snake_case**:SPEC 行文用 kebab-case(如 `commit-must-clear-git-status`),落盘用 `commit_must_clear_git_status.py`。理由:python 模块名约束,风格参照 a2a-mailbox。
- **D2-2 `commit_must_clear_git_status` 的"非空"精确语义**:`git status --porcelain` 中允许纯 staged 行(第一列非空、第二列为空)——pre-commit 钩子运行时被提交内容必然出现;fail 条件 = 存在未暂存改动(第二列非空)或 untracked(`??`)行。理由:字面"非空即 fail"会让任何提交(包括钩子自身触发的检查)永远 fail,唯一自洽解读是"提交时工作树无未收干净的杂项";CI 干净 checkout 下该语义同样成立。
- **D2-3 run-lints.sh 自动发现规则**:遍历 `lints/*.py` 逐个执行,不维护手写清单。理由:a2a-mailbox 的手写清单模式新增规则要改两处、易漏;自动发现保证"一规则一文件接入"零成本。
- **D2-4 增设 `zero_comments` 为第四条种子规则**(SPEC 只列三条):扫描 .py/.sh/.ts 源码注释。理由:CLAUDE.md 铁律 2「代码零注释」需要机械守护;本仓 extensions/ 是 TypeScript,a2a-mailbox 先例的 zero_comments 只扫 py/sh,本仓扩展覆盖 ts。py 的 shebang 与 sh 的首行豁免沿用先例;ts 中 `://`(URL scheme)不判为注释。
- **D2-5 no-secrets 的 zai 形态**:`zai[-_][A-Za-z0-9_-]{12,}`(server/变量名前缀形态)之外,增加 z.ai API key 实际形态 `\b[0-9a-f]{32}\.[A-Za-z0-9]{12,}\b`。理由:本机 CC 配置实测该 key 形态(32 hex + `.` + 尾串),前缀形态扫不出值本身。
- **D2-6 gate 提交流程顺序**:先 `git add` 再跑 run-lints.sh。理由:commit lint 允许纯 staged 行,未 add 的新文件是 untracked 必 fail,顺序颠倒会让 gate 永远红。
- **D2-7 commit lint 的仓路径可注入**:`COMMIT_MUST_CLEAR_REPO` 环境变量覆盖检查目标。理由:pytest 内跑 run-lints.sh 时工作树必然带未 add 改动(自指冲突),测试把该项指到临时干净仓。

## D4

- **D4-1 server 白名单映射**:CC 配置无 `chrome-devtools`;按 SPEC「名字以实际为准」,同步 zai 家族三件 `zai-mcp-server`(截图/图像分析)+ `web-search-prime`(search)+ `web-reader`(fetch),正好覆盖 SPEC 所述「截图/search/fetch」能力;`zread` 不在 SPEC 能力清单内不同步。理由:同步目的是让 pi 具备截图/search/fetch,逐能力对齐实际 server 名。
- **D4-2 条目零转换直接拷贝**:pi 官方迁移表(Claude Code → Copy the existing mcpServers entry)且 `type` 字段可选接受,stdio/http 条目原样并入。理由:少一层转换少一类错。

## D3

- **D3-1 索引注入选 before_agent_start + systemPromptOptions.sections(第三通道,优于 SPEC 两备选)**:`sections["agent-memory-index"] = MEMORY.md 全文`。理由:官方结构化通道,pi 对 sections 做 diff 只 patch 变更部分,内容稳定时缓存前缀不受扰动;`before_provider_request` 是 provider payload 级改写,形状随 provider(anthropic/openai)变,官方定位为调试钩子,且绕过 pi 的 prompt 状态管理;`session_start` + appendEntry 的 custom entry 明文不进 LLM 上下文(文档:do NOT participate in LLM context),语义不符。
- **D3-2 sqlite 选 node:sqlite**:Node 24.11 内置,FTS5 + trigram 实测可用(SQLite 3.50.4),不降级 python 子进程/纯 JS BM25。
- **D3-3 FTS 表三列(name/description/body),查重列过滤** `{name description} : query`;<3 字符查询(trigram 无法成 token)与 fts5 虚表上 LIKE 直接语法错的兜底统一走内存全扫(条目个人量级)。理由:body 是记忆正文主体,不进索引则中文检索大量落空(实测发现);查重语义是 name+description 相近,含 body 会把正文关键词撞车误判重复。
- **D3-4 查重判定:FTS MATCH 命中即拒,bm25 弃用**:trigram phrase 查询下 bm25() 恒返回 0(实测),打分不可用;"高分命中"落地为命中即拒,排序用内存词重叠数。
- **D3-5 problem 进 schema enum 但 execute 内拒**:模型误传 type=problem 时拿到的是完整分流文案(lints 模板)而非干瘪的 schema 校验错。
- **D3-6 归档候选落地**:frontmatter `archive_candidate: true` + MEMORY.md 索引行尾注,文件原地保留不物理删;引用记录在 sqlite memory_refs(memory_search 命中即 upsert last_referenced),过期(expiry_at)且 last_referenced < expiry 才升级候选。
- **D3-7 值导入全部动态 import 进 async factory**:顶层仅 node 内置 + type-only import,使 extensions/memory.ts 可被 `node --experimental-strip-types` 纯环境直接加载单测;pi 环境 await import 经 jiti 模块映射正常解析(实测)。
- **D3-8 migrate 脚本保守分流**:缺 type 或 frontmatter 不完整的条目不猜类型,列「需人工分流」清单;跨项目同名自动加项目 slug 后缀;迁移条目 body 尾注 `migrated from Claude Code memory` 溯源;--apply 后复用 MemoryStore.rebuildIndex 重建索引(单一真相)。

## D5

- **D5-1 游标单位 = UTF-8 字节(虚拟偏移)**:cursor = logBase + 文件内字节偏移;环回截尾(>256KB 保后 128KB)时 logBase 前移丢弃字节数,游标单调不减,旧 cursor 永远可用。理由:字符偏移在多字节截断下会漂移。
- **D5-2 tasks.jsonl 事件流单文件真相**:created/exit/logrotate 三类事件 append,启动重放得全量状态(含 logBase),崩溃自恢复即重放 + 死 pid 探活(process.kill(pid,0),EPERM 视为存活)。
- **D5-3 遗留任务 exit code 记 unknown**:pi 重启后 child 已被收养拿不到精确退出码,reapDeadPids 记 null(呈现 unknown);会话内任务走 child exit 事件记精确码。
- **D5-4 task_stop 在 execute 内最多等 5s**:等待本地进程退出,非跨回合回调/事件,不触死锁红线(bash 工具同样等待命令)。
- **D5-5 通知唤醒链路**:2s 轮询 + agent_settled 双触发 sweep;退出合并周期内多任务为一条 pi.sendMessage({triggerTurn: true});pi busy 时 sendMessage steer 排队不阻塞。
- **D5-6 协议字段必须进 content**(验收实测踩坑后立 lint `tool_protocol_fields_in_content`):cursor 等增量协议字段只进 details 时模型不可见(模型只读 content),增量读协议整个失效;修复为 content 末尾回显 `[cursor=N state=.. exit=..]`。
