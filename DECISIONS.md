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

## Review(workflow 全量对抗 review 后)

- **R-1 journal 纯 append-only + gc tombstone**:tasks.jsonl 只许 appendFile;GC 落 `{"kind":"gc","ids":[...]}` 事件,重放时删除对应任务,不做覆写式压实。理由:rename/tmp 覆写与并发 append 有静默丢他窗事件的竞态窗口;append-only 是无锁并发安全的唯一形状,增长速率(几十任务/天,~100B/条)远低于需要压实的量级。配套 pattern lint `tasks_journal_append_only`。
- **R-2 跨会话状态实时化:refreshFromJournal 增量重放**:list/find/sweep 前按 journal 字节偏移增量读新事件(stat 短路,无新数据零读盘)。理由:journal 只在启动重放一次的旧设计下,并行 pi 会话的 logrotate/exit 事件对本进程永久不可见,logBase 过期导致游标倒退、重复 exit 通知。已知边界:事件自我 append 不推进 offset,下次 refresh 会幂等重放一次(线性重放终态一致)。
- **R-3 pid 复用防护用 /proc starttime**:created 事件记 `procStart`(第 22 字段 clock ticks),探活与 task_stop 前校验 pid 的 starttime 一致才认为是本任务;不一致视为已退出,绝不向无关进程发信号。
- **R-4 shrink 环回的残余竞态接受为边界**:log 截尾(truncate)与子进程 O_APPEND 写、跨进程双 shrink 之间仍有毫秒级窗口(尾部丢几十 ms 日志或 cursor 短暂回退,下次读取自愈);本进程内以 in-flight set 防重入。理由:彻底消除需 per-file 锁或替换 inode(会断子进程 fd),代价不成比例;环形缓冲语义本就是尽力保留。
- **R-5 MEMORY.md 并发 last-writer-wins 接受为边界**:它是从 *.md 条目文件渲染的派生物,并发覆盖丢行后由任一下次 rebuild 自愈;持久层是条目文件本身(每条独立文件无交错)。理由:MEMORY.md 加锁引入的复杂度高于自愈代价。
- **R-6 索引一致性 lint 必须对 renderIndex 真实产物验证**(behavioral lint `agentsmd_lint_parses_renderindex_output`):手写 fixture 与生产渲染格式脱节,曾让 `^` 缺 MULTILINE 的解析 bug 全绿通过。理由:守护「lint 自己」的解析正确性,重放生产格式作为原始输入。
- **R-7 注入视图与磁盘真相分离(prompt O(1) 有界)**:system prompt 只注入固定说明头 + memory_refs 热度 top-30 条 + 其余条数与 memory_search 指引;MEMORY.md 磁盘文件保持全量索引(lint 与人读的真相)。理由:全文注入是每 turn 线性税(≈20 tokens/条),407 条迁移后不可接受;截断视图信息零损失(全部条目 search 可达);热度排名只在条目集变化(mtime)时重算——search 引起的 refs 变化不触发重渲染,保证节内容缓存稳定。top-K 之外条目对模型"被动可见性"下降,由 prompt 头显式指示按需检索补偿。
- **R-8 查重词命中双向子串**:term 在 haystack 中,或 haystack(≥5 字符)在 term 中——变体名(duo-cache-probe-v2 ⊃ duo-cache-probe)计满命中;短 haystack 不触发反向防 ops 类误伤。
- **R-9 journal 重放信任边界(对抗审计后)**:任何同用户进程可 append journal,故重放逐事件过 `journalEventPlausible`(id 形状/pid 1..4194303/name≤200/cmd≤8192/cwd≤4096/state=running/gc ids 形状),畸形即丢弃;发信号一律过 `canSignalTask`(pid 在界内且 procStart 存在且匹配)——pid=1 组杀路径物理关闭。procStart 可被照抄伪造属已知残余(同用户本可直接 kill,攻击面提升有限),记边界不深防。
- **R-10 审计接受的低危边界**:①memory/tasks 目录下 symlink 跟随写入(同用户攻击面,与直接写文件等价,不做 lstat 防护);②memory save/session_start 的 rebuildIndex 全量重建(实测 233ms@440 条,审计自评未达痛点线,增长到千条再做增量 upsert);③readFile 全量 vs offset 尾读(journalOffset 短路已消除常态成本,有新数据时整读一次的窗口留待 open+read 优化);④注入视图不含 archive-candidate/expiry 元数据(磁盘 frontmatter 有,模型可读文件)。
- **R-11 enable-gate 的 LINT_ROOT 语义**:钩子导出 `LINT_ROOT=<目标仓>`,run-lints.sh 贯穿给 no_secrets/zero_comments(扫目标仓)与 commit lint(查目标仓);源码类 lint(扫 extensions/ 的 4 条)固定 kit 根。

## D7(history 检索 + compact fold-index,基于 billion-context 机制研究)

- **D7-1 侧车存块摘要全文而非轮廓**:`~/.agents/history/sidecar.jsonl` 拷贝 bili blocks 表的 summary 全文,refresh 才碰 bili db(mtime+size 签名短路),运行时检索零依赖——bili 停止/卸载/db 损坏后历史检索照常工作,db 缺失时沿用旧侧车(stale 降级)。理由:块摘要总量个人量级(24 块 ≈50KB),全拷的鲁棒性远超省下的磁盘。
- **D7-2 检索三层漏斗+硬预算**:history_search 默认只出轮廓(每块一行 topic+关键词 ±120 字符预览,总预算 4000 字符,超限截断并回显 truncated);history_read 带 around 只取 ±500 合并窗口(预算 8000),不带取全块。理由:块摘要最坏 4k+ 字符/块,宽词一次返回就是洪水;模型先看地图再点菜。
- **D7-3 CJK 无空格长词 2-gram 兜底**:整词 includes 未命中且词长 ≥4 含 CJK 时,按二字滑窗子词命中率 ≥0.5 计半分命中。理由:「民法典重灌」连写对「…民法典…重灌…」分置文本整词必落空(实测踩坑)。
- **D7-4 fold-index 单活代际链+单靶点溯源**:compact 摘要强制以 <fold-index> 头开始,指示"若上下文已有旧 fold-index,蒸馏并入、至多一个存活";溯源列只有 history_search 一个入口(bili 活跃时)。理由:pi 的 jsonl 机制天然是"显式单靶点(内存只见最新 compaction)+底层多靶点(每代落盘)",索引头遵守同构约束;多入口列(jsonl/grep)只增加模型选择噪声。
- **D7-5 compact-instructions 纯函数抽出**:fold-index 指示文本与 buildCompactInstructions 独立成无依赖文件,compact-tool.ts 的 typebox 改动态 import。理由:静态值导入 typebox 使 driver 无法裸 node --experimental-strip-types 直测(D3-7 原则重申,新增 pattern lint extension_static_typebox 守护)。
- **D7-6 codemode 选取决策树入 AGENTS.md 管理节**:deploy.sh 从单节管理改为多节列表驱动(["## 问题即 lint","## codemode 选取"]),节外内容仍原样保留。决策树 ≤100 字,依据夜班实测 miss 模式(bash 里 sed 改脚本再跑的调试链 ×7 轮、同主题连续状态收集 ×9 条)。

## D7 补遗(四轮对抗审计后)

- **D7-7 sidecar 快照发布协议**:锁文件 + 锁内 db 签名复查——只有"当前 db 签名与读取时一致"的快照才可落盘,旧签名持有者放弃写;实例内 persist 串行链 + epoch 复查罩住全部晚到赋值。理由(R3/R4 实证教训):①跨进程写没有全序,行数当新近度的启发式把 GC 合法收缩变成永久毒化(删块幽灵服务);②"锁内重验数据签名"是唯一不需要分布式协调的单调发布条件。记边界:锁等待上限 5s(50×100ms),超限抛错走 persistFailed 重试路径。
- **D7-8 部署语义**:扩展部署 = prune 清单先行 + 全量 *.ts 拷贝;库文件(compact-instructions 类)一律内联进扩展文件,不落 pi 自动发现目录。理由:pi 加载器把目录内每个 .ts 当扩展,库文件会报"does not export a valid factory";排除名单曾使全新安装的 compact 静默失效(R3 实证),prune 先行防同名复发。

- **D7-9 sidecar 快照改单属主文件(503f408 后为每实例一个)**:每实例只写 `sidecar.<pid>.<instanceId>.jsonl`(实例内 persistMu 互斥串行),读侧取 mtime 最新,2h 外清扫(含残留 .tmp);彻底放弃跨进程锁/双检/行数守卫三代协议(R3~R5 连续实证:POSIX 上多写者单调发布没有廉价正确原语——行数启发式把 GC 收缩变幽灵、锁+签名双检在 stall>10s 被抢占复活幽灵、锁获取在权限异常下 busy-spin 挂起)。残余边界:stall 场景旧快照可能成为 mtime 最新,幽灵仅在「db 已消失且无任何 db-backed refresh 自愈」同时发生时暴露——db 存在时 refresh 恒直读 db,该窗口即快照语义(最后已知状态)。

## D9(memory_save 增量更新,FR1)

- **D9-1 增量协议:mode=append / section 两参数正交**:mode=append 整体追加段落;给 section 即命名小节级替换(存在同名 `## ` 节则换内容,不存在则尾插),与 append 互斥;未命中 name 时增量模式降级新建(section 模式把 body 包装成单节结构)。查重闸仅挂新建路径(命中更新沿用跳过语义);description/type 命中时照旧总是覆盖——程序化调用方(pi-backend)重传原值零成本,不为"保留旧值"引入模式相关验证分歧;命中即清 archive_candidate 并对 project 重算 TTL(更新=条目重新活跃)。
- **D9-2 小节边界围栏感知**:splitSections 逐行跑 CommonMark 围栏状态机(与 deploy.sh 同规则:同字符+长度≥+无 info string 闭合),fenced block 内的 `## ` 行不是小节边界——R3(deploy 围栏违背 CommonMark)教训前移到 memory 正文;测试钉住「块内同名假节不吃掉替换」。
- **D9-3 前导空行往返 quirk 的增量路径规范化**:parseFrontmatter 的 slice 往返使读回 body 恒带一个前导 `\n`(存量行为,replace 模式下稳定无害);appendBody 若只 trimEnd 会让该前导随每次 append 复制累积(实测抓到),故统一 trim() 归一——合并路径(append/section)产出的 body 首尾空白都是工具管辖,原文模式不动调用者原文。

## D10(context-gauge 水位可见性,FR4)

- **D10-1 水位=常态可见的仪表盘而非越线告警**:每 turn(每次 LLM 循环)第一个工具结果后附加一行短水位(正常档仅 `[ctx 62% 124k/200k]`),75%/90% 档同行升级为行动信号文案——仪表盘与哨兵合一为单机制。理由:模型自主择时压缩(compact 哲学)的最佳边界常在 50~70%,越线才告警已过最佳时机;自查工具被否决(自动可见后主动查询需求趋零,且 /reload 不刷新会话内工具 schema)。
- **D10-2 附加通道=tool_result 事件改写(零缓存损失、零额外条目)**:改写发生在工具结果入上下文之前,持久化的即改写后版本,下请求直接命中缓存;水位行随工具结果同生命周期,compact 折叠时一并被压——累积自限于单个压缩周期。排除的形态:水位值进 system prompt 尾节(pi-ai 断点在最后一条 user/system 消息,system 是头部块,任何变化打碎全部缓存前缀);followUp 注入(纯追加,可行但产生独立对话条目且常态注入会累积);context_edit 滚动替换(每回合编辑中部条目打碎上一回合后缀缓存)。
- **D10-3 附加节流**:turn_start 重置,仅本 turn 首个非错误工具结果附加(pi 的 turn=单次 LLM 调用循环,串行工具链下每个工具结果各处一个 turn 故都附加——每 LLM 决策点看到最新水位,粒度即决策粒度,实测后由验收修正措辞)(并行批不重复);isError 结果跳过(错误输出保持干净,水位不应被误读为错误的一部分);getContextUsage().tokens 为 null(压缩后未获响应)不附加。structuredContent 改写 content 时原样回传(否则被丢弃)。TUI 场景 footer setStatus 常显精确水位,零上下文成本。
- **D10-4 bili 压缩基线不入水位行**:blocks 表 session_id 与 pi 会话无映射,全局 active 块合计对当前会话决策是误导;水位行只给 pi 侧三件套(百分比/占用/窗口)。
- **D10-5 /reload 刷新事件处理器但不刷新会话内工具 schema**(pi-backend 实测):a2a-inbox triggerTurn 行为 reload 即生效 vs memory_save 新参数 reload 后仍为旧 4 参数冻结。交付回执必须注明生效条件(事件侧=reload,工具侧=会话重启)。

## D11(subagent-jobs 定时任务查询桥,FR5 收窄后)

- **D11-1 job_list 双源:RPC 实时态优先,文件镜像降级**:job_list 直读 `<cwd>/.pi/subagent-schedules/<sessionId>.json`(pi-subagents ScheduleStore 落盘,PID 锁+原子写,读侧天然一致);factory 只注册工具、listJobs 独立成不依赖 typebox 的函数(D3-7 拆分模式,driver 裸 node 可测)。
- **D11-2 写通道=本地 patch 注入 schedule RPC(脚本化,非一次性 hack)**:上游无模型侧写通道(executeJob 源码注释明证 fire 不 reload from disk,外部改文件后 timer 照 spawn;RPC 面只有 ping/spawn/stop/consume/steer)。落地为 `scripts/patch-subagents-schedule-rpc.mjs`:锚点注入 getScheduler 依赖 + schedule_list/remove/update 三个 handler(幂等可重跑,上游升级锚点失配时报错退出而非静默错注);失败语义用 throw(handleRpc 把返回值包成 data,不 throw 则失败被吞)。kit 侧 job_cancel/job_reschedule 走 pi.events RPC(同进程事件总线,毫秒级往返,非跨回合等待);job_list RPC 优先(实时态含 nextRun)文件降级(未 patch 机器 list 仍可用)。已知边界:pi update 覆盖后需重跑 patch(deploy.sh 自动重试);上游收 PR 后 patch 锚点自然失配退出,转正。
- **D11-5 patch 必须打 src/*.ts 且后清 jiti 缓存(pi-backend FR5 试用中断的根因)**:pi 经 jiti 加载 npm 扩展的 **src/*.ts 源码**(jiti 原生吃 TS),dist/*.js 是死路径——第一版 patch 打 dist 全部无效;且 /tmp/jiti 编译缓存按内容 hash 复用,磁盘改动对已缓存模块零影响,「文件已验标记存在」与「运行行为是旧的」并存(实测:原生 ping RPC 通而注入 handler 全哑,黑盒三探针定位)。patch 脚本尾部强制 rm jiti 缓存目录(TMPDIR 可隔离测试)。诊断方法论:原生通道(ping)与注入通道分离开关式定位,临时诊断扩展三探针(自发自收/上游广播/原生 RPC)逐步收窄。
- **D11-3 重启后 job 会 fire 的代码级实证**:scheduler.start() 在 session 加载时 new ScheduleStore(构造即从磁盘 load)并 arm 全部 enabled job——「面板列着≠会响」的疑点由源码闭环,无需等次日验证。job 落盘为 session 级(store 文件名=sessionId),/resume 重载;pi --session 恢复即重 arm。

## D12(SubagentWorkflow 渐进式披露改造 + zcode 守望设计吸收)

- **D12-1 三层渐进披露**:上游 20.6k 工具描述(patch 注入 slimWorkflowToolDescription 瘦身至 ~3.5k,保留 opt-in 规则全文/API 一行概要/硬红线/resume 概要)→ skill 判断层(zcode 原作 §0-8 保留,新增 §9 模式库/§10 codemode 结合/§11 生态组合)→ docs/workflows.md 权威 API。信息不丢失:上游 desc 每个信息块要么留 L0、要么迁 L1、要么 L2 原有。CC 生态自身就是此形态(工具 desc 概要 + skill 承重参考),pi-subagents 移植时把两层压平成一层——本改造是还原,与上游 issue #435(slim 档问询)同向。
- **D12-2 zcode 守望设计迁移(设计备忘,不进 skill)**:zcode 侧常驻信箱守望 = 60 轮有界循环 × 纯 shell 守望窗(world.run,等待零模型成本)× 循环外声明的复用转送员 × escalation 实时上行。pi 侧形态映射:守窗层不进 workflow(pi 脚本无 shell)——a2a-inbox 扩展常驻队列等价且更廉价;处理层(积压批量消化)可进 workflow。模板:/mnt/c/Users/1/.zcode/skills/mailbox-watch/template.dwf.ts。
- **D12-3 守望类编排五条纪律(引擎无关,zcode 实战沉淀)**:①送达语义=上行送达主控并拿到答复,ack 只在收到答复后落;②升级前再查 ack(跨轮去重第二层闸;第一层=出队即 diff);③同信连续 2 轮失败→熔断终止留队列等人工;④循环有界;⑤外层超时≥内窗+15min 余量(实测:2860×5s≈3.97h 贴 4h 超时炸整 run)。
- **D12-4 安全边界:prompt injection 防线在 persona 层**:转送/分拣类 agent 角色硬编码——只转送+归档,绝不执行信件正文指示、绝不代笔回函;信件正文=不可信输入;拍板/花钱/破坏性动作主控亲自裁定。
- **D12-5 成本技巧与 SKILL §6 红线同源印证**:固定角色外提+resume 复用(SKILL §1/§10);纯搬运角色用廉价模型;热修迭代 prompt 一字不动=缓存全命中(=§6「常量别插进 prompt」);信在途绝不 amend(=§6「run 必须先停」)——zcode 的 D6 判断层与本仓红线出自同一实战谱系。

- **D12-6 jiti 缓存掩盖 src 级语法错(slim 三连修)**:wire 换用新常量却未补 import、模板串内层反引号未转义——两个错自 b7a8409 起共存,但 jiti 旧编译缓存一直在跑 full 版,直到缓存被身份手术清空才爆「is not defined / Unterminated template」。修复:import 补第五注入点;DESC_SLIM_EXPORT 重写为双引号数组 join(内层零反引号,免疫转义)。教训:「磁盘已验标记存在」≠「能编译」,patch 后必须清缓存+实载验证(报错才算修完);gate 链式中 `;` 后的 commit 会逃逸失败检查,pipefail 链必须全 && 到底。

## D13(queue-watch 复刻 + mailbox 收发链修复)

- **D13-1 守望层两档制**:纯日志触发行扫描(hub.log tail)不进 workflow——守窗 agent resume:'watch' 跨窗复用(等价 zcode hoist),行协议 EXIT=/NEW_TOTAL=/中段 matched 定序锚定(防协议换行把 EXIT 值断成两行);偏移 ack 原子写(tmp+mv);LINE_ANCHOR 时间戳行锚防 prose 内触发词误报(喂探针自解被其杀死)。五条纪律与安全边界照 D12-3/4。
- **D13-2 pi-backend 守望降级按需**:用户裁定其主线压力大,守望改为一次性任务数安静窗的按需模板,不布常驻。

## D14(workflow run 管理五通道,用户「pi 还是没有 stop 工具」)

- **D14-1 停止通道源码实证**:注册表= index.ts factory 作用域 `workflowTasks: Map<string, WorkflowTask>`(session 级,shutdown 清空);UI 菜单 stop 语义= `task.abortController.abort()`(先查 signal.aborted 幂等护栏),abort 同时杀 worker 与子 agent(host 每次spawn 透传 signal,manager onParentAbort 级联);killed 后 Map 条目留存,resolveResumeTarget 支持 scriptPath+resumeFromRunId 续跑(journal 回放)。
- **D14-2 五通道设计**:workflow_list(全部 run 摘要,cached 计数器零推导——fleet list 200ms tick 同款纪律)/workflow_stop(幂等,已 abort 返回 {stopped:false,status})/workflow_pause/workflow_resume(pauseWorkflowTask/resumeWorkflowTask 直用,UI 同源,状态机错 throw)/workflow_status(单 run 详情,collapse() 出 agent 状态行+logs 尾;P1 的 log_tail 并入其 lines 参数,默认 20 上限 200)。P2 的 run 内 steer/skip/retry 留上游 #433 讨论(control 句柄有,索引语义需对齐)。
- **D14-3 注入点锚点存活不变量(新 lint patch_replacement_reanchors)**:wf-deps 与 rpc-deps 共用 `manager: SpawnCapable;\n}` interface 尾巴——后打者必须保持前打者锚点子串完整(replacement ⊇ anchor 或 ⊇ marker)。lint 用 node 求值 mjs 头部 const 实参(模板插值/数组 join/拼接全解),对每个 patchFile 调用检查;防「已 patch 机器上后继注入锚点失配」这一静默失效模式。
- **D14-4 工具层测试用 typebox 替身**:repo 无可解析 typebox 安装(extension 靠 pi 运行时解析裸 specifier),driver 以镜像所用表面(Object/String/Number/Boolean/Optional)的替身注册工具——被测对象是 execute 逻辑与格式化,非 schema 发射。

## D15(memory 双桶 scoped + 设定全局适配,用户"新项目 pi 没继承设定/记忆混桶")

- **D15-1 项目桶映射模仿 CC**:~/.agents/memory/projects/<cwd 非[a-zA-Z0-9]全替->/(项目私有记忆不进项目仓——用户约束);全局桶 ~/.agents/memory/ 原地不动,存量零迁移。pi 全局根即 ~/.agents(skills 同根实证),CC 同构 ~/.claude/projects/<encoded>/。
- **D15-2 写入语义**:memory_save 加 scope 参数默认 project;global 准入闸=type=project 拒绝(项目认知不进全局桶)+"真正重要跨项目才 global、偶尔使用"进工具 description 引导。查重限同桶(跨桶同名是合法副本)。
- **D15-3 读取无感混搜**:默认两桶各搜合并按 termsHit 排序取 top_k(不传参=无感——用户规格),scope 参数才限定;ScopedHit 带 [project]/[global] 来源标与真实路径;context 注入两桶按引用热度合并 top-30。
- **D15-4 设定继承链实证**:pi 读 agentDir(~/.pi/agent)下 AGENTS.md/CLAUDE.md 为全局 context+逐级祖先目录(缺省无全局文件→通用约定无载体);skills 双轨全局 ~/.agents/skills+项目 .agents/skills(trust 后);扩展/模型/settings 本就全局。补 ~/.pi/agent/AGENTS.md 四节通用约定(记忆/workflow opt-in/tmux 绝对路径/mailbox 纪律)。
- **D15-5 已知存量缺口(记档不动)**:splitTerms 过滤 <3 字符词(与 FTS trigram 对齐),2 字中文词两桶都搜不到;兜底 countTermHits 依赖同一 terms 数组故不救。

## D16(a2a-inbox 11-07 崩溃事故吸收,A2A 工单)

- **D16-1 三坑源码实证(pi-coding-agent 1.5.0)**:①ExtensionAPI 层 sendUserMessage(agent-session.js:2792)fire-and-forget 无 return,.then 即 TypeError;类型面双定义(session 层 1928 行才是 Promise<void>)。②prompt() 1670 行 `isStreaming ? streamingBehavior : undefined`——idle 时该选项整体被忽略走正常提交(唤醒),streaming 中缺省则 1684 行同步 throw(加载期遗留信撞未就绪运行时=PI_EXIT 循环)。③followUp 两级队列恒劣后用户手打字,长回合信饿死。
- **D16-2 终版形态(sendUserMessage+deliverAs:steer 单形态)**:直调不链式;markDelivered 闭包与 send 的 try 分离(send throw 不写 rcpt 留队);5s setInterval(scanQueue) 幂等重扫兜 fs.watch 丢事件。lint 按此重写为四条事故免疫(禁链式/必 steer 禁 followUp/同步 try-catch 且 catch 禁写 rcpt/周期重扫必备),旧 lint 禁 sendUserMessage 是过时知识已废;反证:事故版三雷全红终版绿。
- **D16-3 教训:过时 lint 比没有 lint 危险**——旧规则用旧语义拦正确实现;事故后 lint 必须随上游语义演进重写,实证源码优先于相信存量规则。

## D18(pi-aicontest"乱流"三定谳 + 守护纪律,2026-11-08 凌晨)

- **D18-1 三层定谳(a2a-mailbox 会话与 kit 独立取证合并)**:①投递面干净(pi-native 全闭环,首判"同秒双信道并发"系 ack 时刻耦合误读)②m02905 本体=外部执行体错层键入:respawn 命令(带 A2A_HOST_TAG,形态即本仓处方格式)经 tmux send-keys 打进活 pi 前台窗,被 TUI 当用户输入提交(session line2764 实证,94 字符)③f2a94a465b29 伪信=模型幻觉:hub 零痕+session 零 user 行,模型退化时自产 A2A 格式+伪造引用链+伪造 task-notification(Done>Done 错乱标签为自产特征)。
- **D18-2 因果链**:错层键入(17:05:10)嵌在模型退化序列(16:24-17:15)正中,非语义 shell 命令突入对话流疑为退化诱因;同一退化产出"批量已跑完"幻觉伪报(journal 实际在跑)——退化会话的口头总结不可信,以投递记录/journal/盘面为准。
- **D18-3 守护纪律固化**(两源:a2a-mailbox 对齐请求+本事故):判 pi 生死以 native-inbox/<id>/alive.json 心跳(20s 级)为准,输出静止≠死(长回合/workflow 天然安静);恢复/通知永不向 TUI 前台窗 send-keys,恢复直接 mail_send;确需 respawn 先验 alive.json。已入 ~/.pi/agent/AGENTS.md 全局约定+memory 档案(pi-liveness-alive-json)。
- **D18-4 方法论铁律**:投递排查以投递记录(hub.log+queue/rcpt/ack)为唯一证据源;session user 行判据(真实注入必有 user 行)与之互补成对;退化会话内呈现的"信"不可作证据(模型自产伪信与真信不可分辨)。

## D18(pi-aicontest"乱流"定谳 + 同模型退化差异,2026-11-08 凌晨)

- **D18-1 三层定谳(a2a-mailbox 会话与 kit 独立取证合并+用户亲证)**:①投递面干净(pi-native 全闭环;首判"同秒双信道并发"系 ack 时刻耦合误读)②m02905 本体=用户错层键入:用户看到乱码输出后 respawn,命令(A2A_HOST_TAG=desktop ~/.local/bin/pi --session...)经 send-keys 打进活 pi 前台窗被 TUI 当用户输入提交(session line2764,94 字符,01:05:10)③f2a94a465b29 伪信=模型幻觉:hub 零痕+session 零 user 行,模型自产 A2A 格式+伪造引用链+伪 task-notification(Done>Done 错乱标签为自产特征)。
- **D18-2 因果序(用户修正)**:退化在先(00:24"批量已跑完"伪报,journal 实际在跑),错层键入在后——非诱因;但 01:05 键入触发 13 连发工具循环(全 200,20s/50507in 起步),退化在这段被放大产出(伪信/重复循环),01:15 用户中断(499)。
- **D18-3 同模型同 key 的差异定谳(request-archive 实证)**:pi 主会话走 group/auto-glm-5-3 的 OpenAI-completions 形(reasoning_effort/max_completion_tokens),magpie 内部转换后仍打 plugin://zcode/v1/messages——与 CC 的 anthropic 形最终同端点,参数面健康;真差异在会话体质:57KB system/累计 2.2M/输入史极脏(A2A 信+通知+数字语境+错层命令),GLM 退化是概率性的,脏语境放大之。结论:非 pi bug;pi 缺退化防线是真缺口(候选:degeneration-guard 扩展,输出重复度检测)。
- **D18-4 守护纪律固化**:判 pi 生死以 native-inbox/<id>/alive.json 心跳(20s 级)为准,输出静止≠死;恢复/通知永不向 TUI 前台窗 send-keys(本次用户手滑实证错层机制),恢复直接 mail_send;确需 respawn 先验 alive.json。已入 ~/.pi/agent/AGENTS.md+memory(pi-liveness-alive-json)。
- **D18-5 方法论铁律**:投递排查以投递记录(hub.log+queue/rcpt/ack)为唯一证据源;session user 行判据互补成对;退化会话的口头总结不可信(会幻觉完成态),以 journal/盘面为准。

## D19(memory 可见性重做:索引分层+trigram 自动召回,2026-11-08)

- **D19-1 诊断("只写不读"根因)**:注入链路本通(10:28 请求 system prompt 实证含索引),坏在可见性策略——mergedContextText 单一 top-30 热度排序,43 条全局存量(含 18 条 D15 准入闸前的 type:project 误放)全占坑,本项目 2 条被挤进"其余略";新写条目 ref=0 恒垫底→不进索引→不被引用→ref 恒 0 恶性循环。pi 侧行为数据其实有读(主会话 search=34),但 push 通道失效后读退化为偶发 pull。
- **D19-2 索引重写(对齐 CC 的 MEMORY.md 全量注入语义)**:项目桶全列(PROJECT_INDEX_TOP_K=30 兜底)+全局桶 type 分层(user/feedback>reference>project 误放沉底)截 GLOBAL_INDEX_TOP_K=18;索引行 description 截 64 字符(存量实测 avg 128 字符,30 行吃 system prompt 16%——行肥即冗余);header 给两桶正文绝对路径(read 直达)+行为指引。实测 45 条存量渲染 ~1.5k 字符,较旧 3.9k 减 60%。
- **D19-3 recall 自动召回(用户设计:扫 output,trigram 命中即拉入,上下文不出现第二次)**:before_agent_start(messageType==="user" 限定,subagent/custom 不召回)取 trigger=本轮用户输入+尾部 assistant(各截 1500 字符),FTS trigram 混搜两桶,termsHit>=2 门槛,excludeKeys 会话内去重,命中≤3 条以 customType=agent-memory-recall 消息注入(display:false)——走消息流不碰 system prompt(cache 友好;pi sections diff 机制虽也 cache 友好,但消息通道与 CC system-reminder 同构且不累积 patch);search 既有 markReferenced 使召回顺手养权重。
- **D19-4 缓存指纹修复(1/2 疑案破案)**:listEntries 缓存探测原为目录 mtime——writeFile 原地更新已存在文件不改父目录 mtime,他进程的增量更新对本进程永不可见(实证:项目桶 2 文件索引只报 1 条);改文件级指纹(readdir+逐文件 mtimeMs 聚合)。
- **D19-5 误放存量迁移**:scripts/migrate-misplaced-global-memories.mjs(dry-run 默认,--apply 先备份 memory.bak-d19,幂等)——18 条 type:project 按名字前缀迁对应项目桶(backend-*/cc-*→EngAssistantBackend 15 条,aicontest-*→aicontest 3 条),dry-run 全映射无遗漏;--apply 待用户批准。配套 lints 三条(index 行截断/recall 去重护栏/文件级指纹)。

## D20(compact 唤醒闭环 + bili 残留清除,2026-11-11)

- **D20-1 compact 唤醒**:session_compact(非 willRetry)经 sendUserMessage 直调注入『[compact 完成](手动/溢出/水位)』唤醒词——按 fold-index 重定位任务状态、续作未完成工作、自然边界则收尾;willRetry 早退防 overflow 重试输入被污染;description 显式接通 gauge 契约(30% 择机/50% 立即)。链路:gauge 提示→compact(brief)→fold-index 摘要→唤醒→重定位续作。
- **D20-2 bili 残留清除**:history.ts 扩展退役(bili db 失去数据源,钻取成死链)+其测试/lint 删;compact-tool 单模板化(去 trace 列与 historyLikelyActive 探测);盘上五处 888M 全删(npm 包×2/config/cache/local/share)+部署侧 history.ts;README 移除 bili 致谢与互补提法。工具表再省 1,710 字符。
- **D20-3 footer 百分比取整**:透传 usage.percent 浮点改 Math.round。
