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
- **D2-8 每条 lint 必须给出结论行(2026-11-29)**:`extension_static_typebox` 通过时什么都不打印,只有违规才出声——按退出码看 gate 是绿的,按 `: ok` 行核对输出的人会漏掉它,而且「规则跑了并通过」与「规则根本没生效」在输出上无法区分。守卫放在 pytest 而不是 run-lints.sh:`test_run_lints_green` 本就捕获全量输出,加一条断言「每条规则的区段内都有 `<name>: ok` 或 `<name>: skip` 行」,反向用例覆盖静默规则;拿掉那条 ok 行即红。不在 run-lints.sh 里硬查的理由:`enable-gate.sh` 会把它装进别的仓去跑那些仓自己的 lint,它们的输出格式不受本仓约束,硬查会波及。结论行允许 `skip` 是因为该单测的隔离环境里本来就没有 pi(真实会话类 lint 如实打 skip);区段内任何位置出现都算——`pi_guard_tool_call_order` 找不到 pi 时先打一行说明再打 ok。

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

## D21(pi-guard:临时脚本失控的机械防护,2026-11-26,aicontest 工单 b61b1a54a780)

- **D21-1 用户令与红线**:给临时脚本加机械防护,但必须识别问题类型——不能只因资源吃得多/跑得久就停;加载模型、建索引、导入大库这类合法大内存活不得误杀。
- **D21-2 选型:cgroup v2 + `systemd-run --user --scope`**。参考面:Claude Code 用时间界(`BASH_DEFAULT_TIMEOUT_MS` 默认 120000、`BASH_MAX_TIMEOUT_MS` 默认 600000)并限回读输出(`BASH_MAX_OUTPUT_LENGTH` 默认 30000),均见其官方 env-vars 文档;容器派用内核内存上限。本机实测:pi 会话近 12h 内 ≥150s 的 bash 调用 234 条全是合法的 26~48 分钟长命令 → 时长界直接否决;内核上限思路采纳,但不引入容器层,直接用 cgroup。scope 模式下命令"由 systemd-run 自己作为父进程执行并继承调用方环境"(本机 systemd-run(1) 249),PID/进程组不变,pi 的进程组 kill 照旧有效;热态每次 8~11ms,无需 root。
- **D21-3 否决项**:①rlimit(`RLIMIT_AS` 按虚拟地址空间计,Java/Node/大 mmap 的合法任务会被误杀;挡不住交换区打满);②时长阈值(见上);③节流(`memory.high` 对涨到顶持平的合法加载是净伤害,且用户会话的 cgroup 未委托 cpu 控制器);④进程自迁 cgroup / 一次性助手代写 / busctl(内核要求写 cgroup.procs 者能写公共祖先,`/non-systemd` 的公共祖先是 root → EACCES;`/run/user/1000/bus` 不存在)。
- **D21-4 硬顶只在 slice 聚合线,不给单命令分顶**(与初版方案不同):按命令分顶等于保护"先占住内存的失控者"、先杀后来的合法任务;聚合线触顶时内核按 oom_score 挑最大进程,配合 scope 的 `memory.oom.group=1`(内核 cgroup-v2 文档:"all tasks belonging to the cgroup … are killed together or not at all")正好整组终止肇事命令。E2E 实证:150MB slice 内失控者被终止,并发的 sleep 邻居正常退出。
- **D21-5 空转判据取行为签名而非资源量**:事故真签名=无 timeout 的内联脚本每圈向 stderr 刷同一行"30 秒后重试"(原始会话提取,推翻了"无读写"的设想)。可观测代理=连续 60s 高频(≥100KB/s)重复输出同一行形状(数字/时间戳归一)且几乎不读输入(≤20KB/s)。资源量(内存大小、CPU 核数、历时)只用于"只记录"的两类。已知边界:向 stdout 高速灌进度的内联数据生成器会被当作空转停掉(回执指明改重定向或加 timeout)。
- **D21-6 纯空转不停**:单核满载、内存平、不刷日志的循环,外部观测与合法满核计算不可分 → 只记录+提示。与工单字面"该停或该节流"不同,已向对方说明。
- **D21-7 实现要点(落地时核实修正)**:systemd 249 不认 `-p MemoryOOMGroup`/`PidsMax`(Unknown assignment),用 `-p TasksMax` + 直接写 scope 的 `memory.oom.group`;`--slice=pi-guard.slice` 会被解析成 `pi.slice/pi-guard.slice`,故命名 `piguard.slice`;包装会带入 `INVOCATION_ID`、`SHLVL+1`,用 `env -u INVOCATION_ID SHLVL=$((SHLVL-1))` 抵消;`tool_execution_start` 的 args 是钩子改写前的原值,须自建 toolCallId→unit 表;`tool_result` 先于 `tool_execution_end`;slice 是 transient unit,空了会被 systemd 卸掉重建,限额须在每条命令启动时重写(只写一次不够,E2E 实测);OOM 归因的基线取命令起步时的计数而非末拍(进程死后那一拍已读到新计数,会把自己当基线)。
- **D21-8 坑即 lint**:包装串 pattern lint 禁 MemoryOOMGroup/PidsMax/按命令 MemoryMax;E2E 断言测试 slice 不含连字符且不在 `piguard.slice` 之下(首版测试 slice 名 `piguard-e2e-<pid>.slice` 被解析成生产 slice 的子层)。
- **D21-9 加载顺序耦合**:pi 按文件名字典序跑 `tool_call` 钩子、首个 block 即返回;`pi-guard` 排在 `no-rogue-background` 之后,否则包装后的命令以引号结尾,绕过其「结尾 &」检测——`pi_guard_after_rogue_guard` 守护。
- **D21-10 回执克制**:只对被干预/被标注/≥30s 的命令追加 `[pi-guard]` 文本块,普通短命令不追加(防上下文膨胀,同 todo 双膨胀教训);日志只记 ≥2s 或非 normal 或非 contained。
- **D21-11 降级**:systemd 不可用或包装启动失败 → 仅观测模式(/proc 找新起的会话首进程:ppid=pi ∧ pgid=sid=pid ∧ 启动时刻≥tool_call ∧ 不在调用前快照里;argv 末项相等优先)。bash 的 exec 优化会让 `bash -c "python3 -c …"` 的 cmdline 变成 python,单靠 argv 匹配会漏——故加排除法。用户态硬顶=进程树 RssAnon ≥ 聚合线 → SIGKILL。
- **D21-12 CI**:行为 lint(driver 重放)需要 node,workflow 加 setup-node 24(`--experimental-strip-types`)。
- **D21-13 事件顺序以 pi 源码为准——跟踪必须在 `tool_call` 钩子里建立**:pi 1.5.2 的 agent-loop 对每次工具调用依次发 `tool_execution_start` → `prepareToolCall`(内含 `beforeToolCall` → 扩展 `tool_call`)→ 执行(`tool_execution_update`)→ `finalizeExecutedToolCall`(内含 `afterToolCall` → 扩展 `tool_result`)→ `tool_execution_end`。首版把建立跟踪放在 `tool_execution_start`、依赖 `tool_call` 已登记——方向相反,真实会话里跟踪从未建立:包装生效,但采样/判型/归因/日志/回执全不工作,空转热循环跑到自然结束。驱动按同一错误假设手调处理器,单测与 E2E 全绿。修正:改写命令与登记跟踪同处 `tool_call`;被后序扩展 block 的调用不经 pi-guard 的 `tool_call`,由 `tool_execution_end` 兜底清理。新增 `lints/pi_guard_tool_call_order.py`(扩展不得注册 `tool_execution_start`、驱动顺序、已安装 pi 的 agent-loop 顺序核对)。
- **D21-14 slice 限额每个采样节拍补写**:systemd 在 slice 变空(最后一个 scope 被回收)时按 unit 自身属性重新 realize 该 slice,`memory.max`/`memory.swap.max` 回到 `max`;scope 启动与中途结束不触发。多会话共用一个 slice 时,甲会话 scope 的回收可能落在乙会话新命令写好限额之后 → 该命令此后无硬顶。修正:`sampleAll()` 每拍 `enforceSlice()`(两次小文件读,值不符才写),窗口压到一个 tick(默认 50ms)。
- **D21-15 真实会话 E2E 用脚本化本地模型**:新增 `lints/pi_guard_real_session.py`——真 `pi -p` 进程 + `PI_CODING_AGENT_DIR` 隔离目录 + `models.json` 自定义 `openai-completions` 提供方指向本地 SSE 假服务,依次下发「限额自检命令」与「空转热循环」,断言:命令跑在测试 slice 的 scope 里、启动时限额在位、命令自己把限额打成 `max` 后 1s 内被补回、用量回执、空转被停(137)并折叠、日志 contained/spin、会话正常收尾。零 token 成本、约 8s;未装 pi/systemd 时跳过。反向验证:换回 8343956 → 7 项失败(热循环未被停);去掉每拍补写 → 「未补回」失败。教训:**扩展类改动的闭环必须经过真实宿主进程**;自写驱动会把假设固化,全绿不代表可用。为此日志目录支持 `PI_GUARD_LOG_DIR` 覆盖,便于隔离测试。
- **D21-16 非交互冒烟的坑**:`pi -p` 在 stdin 非 TTY 时会把 stdin 读完拼进提示词;Claude Code 的 Bash 工具给子进程的 stdin 是一个不关闭的 socket → pi 永久等待。脚本化调用 pi 必须 `stdin=/dev/null`。
- **D21-17 unit 名必须按扩展实例唯一**:pi 的扩展模块缓存按 cwd 区分,子 agent 会话(`createAgentSession` + `DefaultResourceLoader`,同进程)换 cwd 时模块被重新求值,得到独立的序号计数器;首版 unit 名 `pi-guard-<pid>-<序号>` 在同进程多实例下撞车——后到者的探针或命令因 unit 已存在而启动失败,该会话降级 60s。修正:unit 名 `pi-guard-<pid>-<实例随机段>-<序号>`,序号为实例字段。新增 `lints/pi_guard_unit_names_unique.py`(驱动以查询串导入两份模块实例并发执行;反向验证:首版行为下第二实例未被隔离)。
- **D21-18 独立审查 R2 的修复(部署前)**:审查未发现 P0,报 4 个 P1 与 13 个 P2,逐条对照代码核实后修了 7 条。①**限时豁免按段计**:首版命令串里任一段以 `timeout` 开头就整串豁免空转停止——`timeout 300 pip install … && python3 -u - <<'EOF' 热循环 EOF` 这种「事故形态前面加一步限时命令」会失去保护;改为每一段内联脚本各自须被 `timeout` 包住才豁免(`timeout` 只管到它所在的段,含 `;`/`&&` 的后续段不算)。②**`sliceMaxBytes` 只接受正数**:默认值 `null` 曾落入通用合并分支,0 与负数都被收下——0 会让每条命令一进 scope 就被 OOM 组杀,负数被内核拒写、硬顶静默不在位。③**定位不再 3 秒放弃**:scope 建立超过 3s(user manager 冷启动、系统卡顿后的第一条命令)后该命令永久失管;改为采样每拍重试 `attached()`,直到出现或命令结束。④**包装失败须「失败且仅一行」**:首版只看输出里有没有 `^Failed to (start|…)` 行,执行成功但打印了这种行的亚十毫秒命令会被误判为包装失败 → 整个会话降级 60s 并谎称「命令没有执行」;现要求 `isError` 且去掉状态行后全输出只有这一行。残留边界:整输出恰为一行 `Failed to …`、非零退出、<1s 且 scope 被 10ms 轮询漏看的命令仍会被误判(三重巧合)。⑤`timeout` 按 basename 识别(`/usr/bin/timeout`)。⑥`isWrapped` 只认包装串开头(`exec '<systemd-run>' --user --scope --quiet --collect --unit=pi-guard-`),首版是子串匹配——命令文本里含该串(例如用 heredoc 写含标记的测试文件)会整体跳过隔离与跟踪。⑦**配置夹取**:`tickMs` 夹到 [50, 5000];`rateWindowMs` 夹到不超过「时间线槽数×tick÷2」(首版 `tickMs:50` 时窗口 5000ms 超出 32 槽共 1600ms,速率恒取不到,空转停止与疑似空转静默失效;默认 500ms×32=16s 不受影响);`leakWindowSec` 不超过包络跨度 320s。**记入未修**(均为窄条件或仅降级模式,逐条有依据):内联识别的误判/漏判面(`nice -n 5 python3 -c`、`uv run`、`docker exec`、`ssh host python3 -c`、先落盘再执行等漏判;`python3 -m pip install -c …`、`node server.js -e x`、注释内含分号等误判——误判只扩大监控面,仍须同时满足 60s 重复行/输出率/不读输入才会停);仅观测模式下并行两条命令都失配时双双不被观测,极端时序下可能误绑;内联脚本派生数千进程时每拍 `/proc/<pid>/io` 读取无上限(上界 TasksMax=4096);写 `cgroup.kill` 失败不回滚(本机内核 6.18 有该文件);折叠会丢截断页脚(`details.fullOutputPath` 仍在);内层 shell 写死 `/bin/bash`(仅在自定义 `shellPath` 时有差异);扩展重载时在途命令失管;OOM 归因用 slice 级 3s 窗口,并行时可能错标。

## D22(task 通知扣留收窄:回合内 steer 投递,2026-11-28,用户「task 的扣留确实要收窄」)

- **D22-1 问题**:9eb37ec(11-15)为躲 compaction 窗口,让 `deliverNotify` 以 `!ctx.isIdle()` 扣留通知;而 `isIdle = !runActive && !isCompacting`,于是整个回合期间通知都到不了模型,只能靠它自己轮询。会话日志实证(25 天/4385 会话/11.3 万次工具调用,分身统计):757 个退出的后台任务中 611 个全程靠通知、91 个被轮询;连续 task_output 环 126 个/525 次/7.2h;11-15 后通知中位晚 743s 才到(28 例 >5min,最长 66min),917 个由通知触发的回合里 226 个是纯文本应答。
- **D22-2 收窄**:扣留条件改为 `inMaintenance() = !sessionIdle() && !agentRunning`——「不空闲且无 agent 回合在跑」,即压缩/分支摘要/重试/排队续跑窗口;`agentRunning` 由 `agent_start`/`agent_end` 事件维护。回合进行中通知走 pi 原生路径:`sendCustomMessage` 的 isStreaming 分支 → `agent.steer()`,当前这批工具调用执行完、下次 LLM 调用前插入;空闲时仍 `_startRun`。
- **D22-3 以 agent_end 清零而非 agent_settled**:回合结束到核心置空闲之间 isStreaming 仍为 true,此时注入会 steer 进已收尾的循环;按 agent_end 清零后这一窗口按维护态扣留,待 agent_settled 的 sweep 冲洗(核心此时经 `_isEmittingAgentSettled` 把开回合延后到 settled 之后)。
- **D22-4 守卫**:pattern lint `task_notify_deferred_during_compaction` 改钉新不变量(deliverNotify 禁止直看 sessionIdle,inMaintenance 必须同时看「不空闲」与「无回合」);behavioral 测试 `test_factory_notify_steered_during_run_held_during_maintenance` 覆盖回合内即时投递/维护态扣留/恢复后冲洗;新增 E2E `lints/tasks_notify_in_turn_real_session.py`——真 `pi -p` + 脚本化本地模型:task_create 后用一条 6s bash 把回合撑住,断言总共 3 次模型请求且第 3 次(模型从未调 task_output)已带「后台任务结束」;反向验证旧代码为 4 次请求。隔离靠改写 HOME(tasks 登记目录随 homedir)而非 PI_CODING_AGENT_DIR;扩展副本旁软链 pi 自带的 typebox 供解析。
- **D22-5 已知边界**:手动 `/compact` 先 abort 在跑回合再进入压缩,恰在这一瞬间到达的通知会被 steer 进正在中止的循环,可能丢失(窄窗口,未处理)。task_output 的 since 缺省秒回、wait 等的是任何新输出而非退出、描述在教分片轮询——留待后台工具统一改造一并处理。

## D23(task 通知归属:子代理会话只收自己创建的任务,2026-11-28,aicontest 回函 cc853c262080 要求「任何情况下不插进子代理的上下文」)

- **D23-1 问题**:pi-subagents 拉起的子代理会话与父会话同进程,默认加载全部全局扩展,各自有一份 tasks 实例并各自巡检共享登记表 `~/.agents/tasks/tasks.jsonl`。旧 `sweep()` 的 `reapDeadPids` 把「登记表里仍是 running、pid 已死、不在本实例 children 里」的任务当作结束并通知;同进程子代理的 `process.pid` 与父会话相同,`foreignOwner` 判不出来,于是子代理实例在「进程已死、父会话尚未标记」的窗口内抢先回收并发通知——通知经 steer 插进子代理正在进行的回合(aicontest 11-27 判官串扰同款路径;抢先者还会把退出码写成 unknown)。
- **D23-2 实证**:这是竞态——父会话实例靠子进程 exit 事件在自己下一个 2s 拍点标记,子代理实例只有恰好在该窗口巡检才抢得到,所以表现为偶发事故。E2E 先测父会话巡检相位、再让任务在「子代理下一拍之前约 1s、父会话下一拍之前约 2s」退出,使旧代码下必现:旧代码 3/3 次复现,新代码 0 次。
- **D23-3 修法**:`isSubagentSessionName(ctx.sessionManager.getSessionName())`——pi-subagents 给每个子会话起名 `<类型>#<agent id 前 8 位十六进制>`(0.23.2 与上游 0.26.3 均如此,`bindExtensions` 之前已设好),顶层会话没有该后缀。子代理会话里的实例只结算自己创建的任务(`reportOwnExits`),不回收、不标孤儿、不做登记表维护;顶层会话行为不变。
- **D23-4 选型**:会话名后缀而非 RPC 或导入 pi-subagents 内部模块——零依赖、同步可得、两版上游通用;误判方向是安全的(顶层会话被误判为子代理只会少收非自建任务的通知)。已知边界:顶层会话被手工命名成 `#`+8 位十六进制结尾会被当作子代理;顶层会话对其他会话(含已结束的子代理)留下的任务仍会回收并通知——既有行为,本次未动,待用户裁决。
- **D23-5 守卫**:behavioral `test_factory_notify_scoped_to_creating_session_not_subagent`(双实例共享登记表)+ E2E `lints/tasks_notify_subagent_real_session.py`(真 pi + 真 pi-subagents)+ pattern `lints/task_notify_scoped_in_subagent_sessions.py`。
## D24(pi-subagents 分支布局与部署方式:kit 分支为唯一真相,2026-11-28,用户「可以对上游进行分支（方便后续我们抓上游自行合并的）」)

- **D24-1 布局**:`~/workspace/pi-subagents-kit`,`main` 跟踪 `upstream/master`(tintinweb/pi-subagents,当前 v0.26.3-1-g3ebbb5f,保持纯净);`kit` = v0.23.2 + 6 个小而独立的补丁提交:16af139 schedule RPC 写通道、c7f8996 workflow run 管理 RPC、038c6cc 描述瘦身、83a7c04 `subagents:rpc:list`/`get` 快照 + ping 的 `features`、3c5b05f 快照补 `result`/`error`、a5f67bf 子会话名带标签(D26)。抓上游 = `git fetch upstream && git rebase v<新版本> kit`,补丁按文件分散,失配即冲突可见。
- **D24-2 基线留 0.23.2**:部署位就是 0.23.2,行为不变、零风险;升 0.26.3 会改动子代理生命周期事件、`pi -p` 等后台 agent、stop 语义,且 aicontest 要求升前书面核实 5 条(续跑兼容、args 原样、并发上限与 gate 语义、其两个钩子兼容、一键回退)并等其空档——列为待办,不在本轮。
- **D24-3 list/get 是上游 0019e64(#450)的小型回移**:该提交改动面大(agent-manager/index/subagent-info/completion-outbox,含嵌套 agent 生命周期事件的破坏性变更),不适合作补丁;kit 版只加两个只读快照处理器,回复形状照上游 SubagentInfo,另带 `handle`/`alias`/`outputFile`/`sessionId`(bg_* 与子代理标签要用)。将来 rebase 到含 0019e64 的版本时,冲突解法是取上游、弃 kit 这一处。
- **D24-4 部署改为从 kit 分支同步**:`scripts/sync-subagents-kit.mjs` 取代锚点文本替换的 `patch-subagents-schedule-rpc.mjs`(D11-2 的机制到此为止)。理由:补丁一旦超出 3 处锚点(83a7c04 即是),在脚本里再抄一遍源码等于两份真相;分支才是真相。脚本行为:校验已安装 `package.json` 的 version 等于 kit 分支基线版本,不等则报错退出不动文件;`git archive kit src` 到临时目录,与部署位逐字节相同则跳过,否则整目录换入并清 jiti 缓存。只同步 `src`(pi 经 jiti 直接加载 src/*.ts)。
- **D24-5 生效面**:同步只影响新启动的 pi 进程(在跑进程的模块已在内存;子代理会话不加载 pi-subagents),且 83a7c04 只加 RPC 不改工具 schema,故可在 aicontest 运行期间同步。守卫:E2E `lints/subagents_kit_rpc_real_session.py` 实测 ping 的 features 与 list/get 形状(被测源的解析见 D24-7)。
- **D24-5b 随之退役**:D14-3 的 lint `patch_replacement_reanchors`(锚点注入点存活不变量)只对锚点替换机制有意义,机制没了规则一并删除;新机制的不变量(版本校验、幂等、部署位==分支)由 `tests/test_sync_subagents_kit.py` 与上述 E2E 承担。
- **D24-6 托管**:目前只是本机克隆(保留 upstream 远端)。建私有镜像仓与推送属对外动作,待用户批准。
- **D24-7 被测对象是 kit 分支头,不是部署位**:kit 补丁在分支里没有任何单元测试(v0.23.2 的测试套件要 vitest,本机没装),3c5b05f 提交时也没有任何自动覆盖,只能事后手工搭隔离安装根实测。于是把这一步固化:加载 pi-subagents 且依赖 kit 补丁的两个 E2E(`subagents_kit_rpc_real_session`、`bg_tools_real_session`)按 `KIT_SUBAGENTS_SRC` → kit 分支 → 部署位 解析被测源;kit 分支须满足基线版本等于已安装版本(与 D24-4 的同步脚本同一道闸),满足则 `git archive <分支> src` 进临时安装根、声明的依赖软链到已安装目录。只有「kit 分支检出」才做严格断言(终态快照的 `result`/`error`),回退到部署位时 ok 行写明原因,不判——这样部署滞后(等空档、D25-9)不会让 gate 变红,而分支头一坏 gate 立刻红。`tasks_notify_subagent_real_session` 验的是通知归属(D23),与补丁版本无关,仍对部署位实测。
- **D24-8 升级前验证(2026-11-28 夜)**:D24-7 的闸「分支基线 = 已安装版本」恰好挡住了升级本身——要升到下一基线,就得在部署位还是旧版时验证新基线的分支。于是给两条 E2E 的被测源解析加两个**显式声明**的开关,默认行为一字不变:`PI_SUBAGENTS_KIT_BASELINE=<版本>` 放行「分支基线 = 该版本」(未设即已安装版本;声明错了照旧退回部署位并在 ok 行写明原因,所以不会误测),`PI_SUBAGENTS_DEP_ROOT=<目录>` 指定依赖目录(新基线多出的依赖,如 0.26.3 的 `ajv`,部署位顶层 `node_modules` 里没有;该目录里没有的仍回退部署位)。归档范围从 `src` 扩到 `src` + `skills`:0.26.x 默认的 `workflowToolExposure: "inline"` 读包内 `skills/workflow-authoring/SKILL.md`,只归档 `src` 时 E2E 立刻报「扩展报错」——这也说明**部署位升级后必须有 `skills/` 目录**。ok 行标签带基线版本(`kit@<头>·基线<版本>`),gate 输出一眼看出被测的是哪个基线。实测:v0.26.3 基线的分支两条 E2E 含严格断言全绿;不加开关时原 kit 分支两条仍绿;声明错基线时退回部署位。
- **D24-9 kit 升 v0.26.3 的取舍(2026-11-28 夜,试验分支 `kit-on-0263-tmp`,未部署)**:把 kit 的 6 个补丁重放到 v0.26.3,留 4 个、丢 2 个。丢的两个已被上游取代:描述瘦身(038c6cc)对上游 0.26.0 的 `workflowToolExposure: "skill"`(2.9k 字符,比 kit 的 4.5k 更短且带完整范例),快照补 result/error(3c5b05f)对上游 `toSubagentInfo` 原生就有的字段——少一个补丁就少一处每次 rebase 都要手工解的冲突。撞名的解法以「对外形状不变」为准:上游的 `subagents:rpc:workflow_list`(返回 `{ workflows }`)删掉,留 kit 的 `{ runs }`(bg_list 读其中的 scriptPath/journalPath/replayedCount/logCount);上游的 `workflow_get` 原样保留;kit 自己的 snapshot 块删掉,在上游 `snapshot()` 上追加 handle/alias/outputFile/sessionId/sessionName;FEATURES 取上游 13 项再加 `kit-schedule`、`kit-workflow`。结果是 `tasks.ts` 一行不改就能在 0.26.3 上工作(E2E 证明),所以回退只换 pi-subagents 与 tasks.ts。两条部署约束随之而来:① 升级后**必须设 `workflowToolExposure: "skill"`**(`~/.pi/agent/subagents.json`),否则默认 inline 约 21k 字符,是现在的 4.7 倍;② 部署位需要 `ajv` 与 `skills/`。`kit` 分支到升级时才前进——现在动,sync 脚本会因版本不一致拒绝,E2E 默认路径也会静默退回部署位。

## D25(后台工具统一:bg_* 五件套并入 tasks.ts,2026-11-28,用户「给我统一这些工具的方案」+ aicontest 回函口径)

- **D25-1 工具面**:上游 4 个不动;本仓 12 个 → 6 个——`task_create` 保留,新增 `bg_list(kind?)` / `bg_status(handle?, wait?, until: exit|idle, lines?)` / `bg_log(handle, since?)` / `bg_stop(handle)` / `bg_schedule(action: list|cancel|update, …)`。统一句柄 `task:<id|名>` / `agent:<id|@名>` / `wf:<run>` / `job:<id>`;不带前缀的裸 id 不收——四类 id 空间不相通,前缀即类型。旧名→新名对照写进各工具描述,**不做过渡别名**(aicontest:其提示与 skill 未点名旧工具名)。
- **D25-2 为什么是一个文件而不是 bg.ts + 库**:pi 对**每个扩展文件用独立 jiti 实例**加载(`dist/core/extensions/loader.js` 的 `loadExtensionModule`,`moduleCache:false`),扩展之间相对 import 拿到的是另一份模块实例——登记表、子进程表、停任务逻辑这些引擎状态永不相通;且部署位是平铺目录,没有默认导出的库文件会被报成「does not export a valid factory function」。故 bg_* 与任务引擎同在 `tasks.ts`,`subagent-jobs.ts` 的库内容并入后删除。守卫:pattern `extensions_self_contained`(扩展文件之间禁止相对导入)+ E2E `bg_tools_real_session`(真 pi 加载后 bg_* 能等到并读出本会话 task_create 的任务与 Agent 起的子代理)。
- **D25-3 等待语义**:bg_status 只等「目标退出」与「本会话全部后台空闲」,上限 120 秒(aicontest 口径);不再有「有新输出就返回」。idle 的口径:登记表里本进程拥有且进程仍存活的命令任务 + pi-subagents 清单里未到终态的子代理 + 未到终态的 workflow run;别的会话的任务不计,workflow RPC 不可达时明示「未计入」——跨会话、跨进程只能尽力而为。
- **D25-4 游标语义**:bg_log 不传 since 只给尾部(命令输出 4KB、子代理会话记录末 12 行、log() 末 20 条),单次返回有上限(命令 16KB、会话 64KB),超出即跳到末尾并标 `省略=N字节`。命令任务与子代理记录用字节游标,子代理记录的游标对齐到完整行(末行没写完时下次从行首读),workflow 用条数游标。协议行 `[cursor=…]` 必须进 content(模型只读 content)。
- **D25-5 退出码落盘**:task_create 的命令经 `trap 'printf %s "$?" > <id>.exit' EXIT` 包裹;`markExit` 在「无码无信号」时回落读 `<id>.exit`,`reapDeadPids` 走 markExit,gc 一并清。修的是「创建它的实例丢了子进程句柄(reload/重启)后,退出码只能记成 unknown(reaped)」。选 trap 而非子 shell:保住 `exec` 与 `set -e` 的旧语义。已知边界:命令里 `exec`、或自带 EXIT trap 时不落盘(退回旧行为);任务 pid 现在是包裹 bash 而非命令进程本身,单独 `kill <pid>` 不再等于结束命令——要停请走 bg_stop(按进程组发信号)。守卫:behavioral `test_factory_exit_code_survives_instance_loss` 与 `test_exit_recording_command`(反向验证:去掉包裹即退回 unknown),pattern `task_exit_code_persisted`。
- **D25-6 pause/resume 退役**:实测 pause 只在把新 agent 交给管理器之前停靠,已交出的照常起跑,保证不了「不再起新代理」(aicontest:保证不了就别留)。`bg_schedule` 只有 list / cancel / update;腾车道用 bg_stop(wf) + scriptPath + resumeFromRunId 续跑,路径不变。kit 分支的 pause/resume RPC(c7f8996)暂留——/agents 面板仍在用。
- **D25-7 降级三态**:子代理与 workflow 通道按 ping 的 `features` 分「未装 pi-subagents(子代理会话或未安装)/ 已装但缺 kit RPC / 可用」。未装时 bg_list 不刷「不可用」噪声,点名要时才报;workflow 不可达时回落本机 journal(D14-3 的不变量迁到 lint `bg_workflow_journal_fallback`,原名 `workflow_status_journal_fallback` 随工具改名退役)。
- **D25-8 列表降噪**:bg_list 的命令任务只列在跑的 + 最近 10 条已退出,子代理最多 40 个;要的几类都空才回「无后台事务」。
- **D25-9 部署与配套**:改的是工具 schema,会话内冻结——**只落仓与隔离实测,不往部署位拷,等 aicontest 报空档**(其 mock 与判官工作流在跑)。配套:`no-rogue-background` 的拦截提示改指 bg_*;`tests/test_deploy.py` 的扩展集合去掉 subagent-jobs.ts;typebox 替身补 Boolean;既有的 factory 场景测试过去写真实 `~/.agents/tasks`,本次改为隔离 HOME。
- **D25-10 类型检查的空档**:pi 用 jiti 去类型加载,gate 里没有任何 TS 类型检查——本次靠手工 `tsc --strict` 抓到 3 处(纯函数误放进工厂函数体导致 `export` 位置非法、工具结果字面量被拓宽、`filter(Boolean)` 未收窄)。tsc 不在本仓依赖里(本机只有 Windows 侧的全局安装),未做成 lint;是否引入 devDependency 版 typescript 并加一条类型检查 lint,待用户裁决。
- **D25-11 旧决策的归宿**:D11(job_*)与 D14(workflow_*)的通道到此为止;D22-5 留下的三条(task_output 的 since 缺省秒回、wait 等新输出、描述教轮询)在此解决。
- **D25-12 失败子代理的 result 是空串**:真会话实测(kit 3c5b05f)三种终态——完成的子代理 `result` 是最终正文、不带 `error`;被停的两个都不带;模型报错的 `status: error`、`error` 是原因、**`result` 是 `""` 而非缺省**。原判 `agent.result !== undefined` 会给失败的子代理多打一行空的 `result(尾 300 字): `,改为非空才打。守卫:behavioral `test_bg_status_failed_agent_with_empty_result_prints_no_result_line`(重放真会话的快照形状)+ 上述 E2E 的失败子代理一步(真 500,关掉 pi 重试以免 gate 多等 14 秒)。
- **D25-13 结算即通报(2026-11-29,aicontest 问「wait 期间的完成通知会不会提前返回」,实测才发现)**:原实现里退出结算(`settleOwnExits`)与发通知(`sweep` → `reportOwnExits`)分在两处——`collectOwnExits` 结算时把任务从 `children` 删掉并返回「已退出」列表,而只有 `sweep` 拿这份列表去通报。`sweep` 每 2 秒一拍;bg_status 的 wait 每 0.2 秒调一次 `settleOwnExits`,bg_list / bg_log / 不带 wait 的 bg_status 也调。谁抢在 `sweep` 之前结算,列表就被丢掉,`sweep` 再跑已无可通报之物。真实会话实测(修复前):只用 bg_status(wait) 等到退出的任务,通知 0 次;任务退出后紧接着调 bg_list,通知 0 次;用 bash 占位的对照场景通知正常——所以既有 E2E(`tasks_notify_in_turn_real_session`,bash 占位)一直绿着,没覆盖到。影响面:照 aicontest 的口径「等后台用 bg_status 的 wait」,上线后被等的任务将一律不通报。修法:`settleOwnExits` 结算后自己走 `reportOwnExits`,`sweep` / `reapUnownedAndReport` 只通报自己回收的无主任务;子代理会话的分流不变;通报失败不向上抛(通报是旁路,不该让状态查询报错)。守卫:E2E `tasks_notify_not_swallowed_by_bg_query`(两个场景各一条真实会话:通知恰好 1 次、随工具返回后的那次模型请求送达、不多唤醒、带尾部日志;还原成修复前的写法两场景都红),pattern `task_notify_scoped_in_subagent_sessions` 加「结算处必须通报」。同一轮实测坐实、并写进给 aicontest 的答复的两点:①pi 对同一批里的多个工具调用并行执行——bash 排在 bg_status(wait) 前还是后,都在十几毫秒内执行完;②通知随 bg_status 返回后的同一次模型调用送达。**没查清的**:14 次运行里有 2 次 bg_status 报 `waited=5s`(任务只 `sleep 3`),都发生在给任务加起止时间戳之前;之后带时间戳的 11 次都是 3s,未复现,成因未定。

## D26(子代理会话标签:子会话名自带 label／归属 run／父会话,2026-11-28,用户「试试能否把subagent自行打好自己的标签」+ aicontest 回函口径)

- **D26-1 落点是会话名**:pi-subagents 给子会话起名只有 `<类型>#<agentId 前 8 位>`,会话列表、会话文件、日志里分不出是哪个 run、哪个主会话的哪个 agent。kit 分支第 6 个补丁 a5f67bf 把命名点改为 `sessionLabelFor`:`<label／name> · <workflow:<run id>｜agent> · 父:<根会话 id 前 8 位> · <类型>#<agentId 前 8 位>`。选会话名而不是系统提示或另设登记表:它在 `bindExtensions` 之前就设好、随会话文件落盘(`session_info` 条目),`/resume` 列表、TUI 页脚、所有打印会话名的日志都自带,谁都不用再查表;「自行」体现为子会话一存在就带着标签。真会话实例:`probe:wf-a · workflow:wf_3d19b6f3a4e5 · 父:01a221bc · general-purpose#04f664fc`、`v8-audit · agent · 父:01a221bc · general-purpose#c0d93b39`。
- **D26-2 取名规则**:Agent 工具给了 `name` 用 name,否则用描述。工作流脚本给的 label(`agent(prompt, { label })` 的 `opts.label`)整段保留——aicontest 起跑后按 label 在日志里核对生效配置;Agent 工具的描述是自由文本,超过 80 字截断加省略号。run id 用全的(`wf_`+12 位十六进制,本身就是合法的 `wf:` 句柄),没按 aicontest 信里写的「短 id」——15 个字符不长,还能直接喂给 bg_stop。父取根会话 id 前 8 位,嵌套子代理也归到同一个主会话。
- **D26-3 `#`+8 位十六进制收尾是承重墙,不动**:D23 的通知归属与 node-2 的 a2a-inbox(2026-11-28 17:55 已部署 `isSubagentSessionName`,`/#[0-9a-f]{8}$/`;子代理会话里 `beginSessionRole` 直接返回,不装 resolver、不轮询不注入)都靠它判子代理会话。所以标签只做前缀,类型与 id 尾巴照旧。通读部署位 a2a-inbox 确认子代理路径无漏水:`agentId` 只在 `tryResolve` 赋值,`scanQueue`/`takeMsg` 均因它为空而短路。给 node-2 的信只确认口径、告知格式将变。
- **D26-4 主会话怎么读到**:kit 的 list/get 快照带回 `sessionName`;`bg_status(agent:<id>)` 多一行 `标签: …`(快照没有该字段就不打,兼容旧部署位)。
- **D26-5 守卫**:E2E `subagents_kit_rpc_real_session`(新增一步真工作流——`SubagentWorkflow` + `scriptPath`;Agent 起的、失败的、工作流起的三种子代理都断言会话名,并核对会话文件里落盘的名字;kit 的工作流 RPC 由此第一次有了真会话覆盖)、`bg_tools_real_session`(bg_status 原样回显)、behavioral `test_bg_status_agent_shows_session_label`。踩坑:pi-subagents 的工作流 API 两版都是 `agent(prompt, { label })`,`agent(label, prompt)` 是 Claude Code 的形状——传错报 `agent(prompt, opts) expects opts to be an object`。
- **D26-6 部署**:kit 补丁随 3c5b05f 一起等空档同步;在那之前会话名仍是旧形状,两版都满足 D26-3 的判别。

## D27(TUI 工具调用折叠成单行,2026-11-28,用户「pi的minimal补丁如果GitHub有高星实现，可以拉来用用看」)

- **D27-1 选型:自写,不引入第三方**。刷屏的实测来源(100 列、9 个调用,走 pi 自己的 `ToolExecutionComponent`):每次调用前面有一个硬空行,默认外壳 `Box` 再上下各垫一行,合计 4~17 行/次——bash 折叠态带末 5 行预览,没有自带渲染器的工具(bg_*、subagent-jobs、memory、pi-guard、MCP)走通用回退「标题 + 输出前 10 行」。GitHub/npm 搜到三个现成实现,都不够格「高星」或不对口:`@diegopetrucci/pi-quiet-tools`(所在仓库 68 星、月下载约 1361、MIT、11-27 仍在发版)只接管 7 个内建与 `mcp__*`,实测 101 行 → 56 行(55%),每条固定 5 行其中 3 行空白,`read` 原本 4 行反而变 5 行,扩展工具不覆盖;`fahmiirsyadk/pi-minimal-toolcall`(2 星,npm 上只发了 0.2.1 旧版——正是重注册内建工具的做法,GitHub 0.5.0 的干净设计未发布)自带 4 个批量工具改工具 schema;`pi-compact-display`(1 星,npm 写 ISC、仓库写 GPL-3.0)。同一实测台自写 self-shell 单行:101 行 → 18 行(18%),覆盖全部工具。
- **D27-2 接管规则**:一个 `pi.registerToolRenderer` resolver。内建 8 个、`mcp__*`、以及没有自带渲染器的工具(含已卸载的)接管;自带渲染器的(`Agent`、`SubagentWorkflow`、`todo`)原样 `next()`——pi-subagents 的运行进度卡(spinner、活动、用量)有价值,不压。不重注册任何工具:schema、description、execute 一字不动,所以不改模型可见面、不依赖 aicontest 空档。
- **D27-3 折叠形态**:`renderShell: "self"` 去掉色块与上下垫,每次调用 = 硬空行 + 1 行摘要(空行是 pi 组件硬编码,扩展层去不掉)。行尾状态:参数未收尾 ` …`,成功 `✓ 1.2s`,失败 `✗` 且多一行红色错误首行(失败原因不能藏在展开态后面);运行中有流式输出时显示末 3 行预览(长命令不静默),结束即收起。不带 `ctrl+o` 提示——pi 页脚已有。
- **D27-4 展开委托与 HTML 导出**:展开态委托回原渲染器(`PaddedFrame` 补回左缩进;`lastComponent` 是自家的行/框时解包或置空再传)。原工具没有渲染器时抛 `DelegateToDefault`,pi 的 `ToolExecutionComponent` 接住走原生回退——TUI 得全文。HTML 导出(`core/export-html`)对结果同时渲染折叠态与展开态:折叠为空、展开为全文,导出的页面直接显示全文;无渲染器的工具回落结构化结果。导出不丢内容是承重性质,E2E 钉住。
- **D27-5 单行渲染的安全前提**:参数文本先清 OSC、CSI、C0 控制字符,再折叠空白。bash 原生渲染器不清洗是因为它按多行原样显示;压成单行后不清洗,`\x1b]0;标题\x07` 可改终端标题、`\n` 可撑开行数。
- **D27-6 守卫**:behavioral `quiet_tui_collapsed_rows`(真 pi-tui + 真 `ToolExecutionComponent` 重放 11 个场景并走 pi 的 HTML 导出渲染器;反向验证——折叠态吐全文、清洗失效、自带渲染器的也接管,各自变红)、`test_quiet_tui` 纯函数、E2E `quiet_tui_real_session`(有无扩展两个隔离会话,模型可见的工具结果逐字节一致,加载无报错)、`test_deploy` 的部署集合加入新文件。
- **D27-7 踩坑**:①lint 找 pi 必须带 `~/.local/bin/pi` 兜底——本机 `pi` 不在 PATH,只靠 `which` 会直接 skip 且 exit 0,gate 照样绿(静默失效);②Node strip-only 模式不支持 TS 参数属性(`constructor(private x)`),须显式字段;③`ToolRenderContext` 不从包根导出,用 `Parameters<NonNullable<ToolRenderers["renderCall"]>>[2]` 推导;pi-tui 的 `Component` 要求 `invalidate()` 必有;④driver 剥 ANSI 只能剥 SGR 颜色码——连 OSC 一起剥会掩盖注入,断言「行内不得残留 ESC/C0」就落空;⑤`fs/promises.readFile` 不收数字 fd,读 stdin 用同步 `readFileSync(0, "utf8")`。
- **D27-8 没做的**:相邻调用合并成一行(`pi-minimal-toolcall` 的做法:同一组里前面的调用画 0 行、最后一条画汇总行,纯扩展可行,留二期——逐条可见便于回看模型做了什么);行内计时 spinner(pi 自带 working indicator)。
- **D27-9 部署**:单文件 `cp extensions/quiet-tui.ts ~/.pi/agent/extensions/`;不改 schema,不需要空档。在跑的会话 reload 才换(不替用户重启),新会话自动加载;回退 = 删文件 + reload。

## D28(a2a-inbox.ts 移出本仓:归 a2a-mailbox hub 仓管,2026-11-28 夜,用户「你做到你认为最好就行」)

- **D28-1 问题**:`extensions/a2a-inbox.ts` 在仓里有一份,部署位那份却由 node-2 维护并于 2026-11-28 17:55 更新(带子代理会话判别 `isSubagentSessionName`),两边各缺对方一个改动。`deploy.sh` 无条件安装 `extensions/*.ts`,谁跑一次完整部署就会拿仓里的旧版覆盖 node-2 的新版——子代理会话会被装上来函 resolver,11-27 那种「来函进判官会话」的事故会回来。这条隐患此前只能靠纪律(「绝不跑完整 deploy.sh」)守。
- **D28-2 决定**:仓里不再保存、不再部署、不再测试这个文件,唯一真相源是 node-2 的 hub 仓(`~/workspace/a2a-mailbox`,本机只读)。随文件一起删除的还有只为它存在的三个 lint、一个 driver 与 7 条单测:它们守护的是仓内那套带 `wakeLanded` 落地检测的实现(含 11-18 事故后的 `inj-` claim 幂等化)。对比过 hub 源与部署位:两边都没有那套落地检测与重注机制,而 11-18 的 36 连注事故根因正是「检测不到即重注」——所以没有需要移交的修复;已去函 node-2(103d7cbeb526),它若要跨进程单注入者保护,再把那段整理过去。
- **D28-3 守卫**:`lints/foreign_owned_extensions_absent.py`——「归外部所有」的扩展文件不得出现在 `extensions/`,清单写在 lint 里(现只有 `a2a-inbox.ts`),自动被 run-lints.sh 发现;反向验证:往 `extensions/` 放一个同名空文件即红。
- **D28-4 顺带修的测试泄漏**:`tests/test_sync_subagents_kit.py` 的 `run()` 继承了调用方环境里的 `PI_SUBAGENTS_KIT_BRANCH`,带着它跑 gate 时同步脚本的单测会去临时仓库里找一个不存在的分支。现在该测试不再继承这个变量。这是在 pi 1.7.0 上跑 gate 时暴露的假红。

## D29(no-long-sleep.ts 收编入仓:沿用部署位原文件与原取舍,2026-11-29,用户「做到你认为最好就行」)

- **D29-1 来历**:`~/.pi/agent/extensions/no-long-sleep.ts` 于 2026-11-07 14:05 直接落在部署位,从未入仓(`git log --all` 无记录)。原始决策只记在 pi 侧全局记忆桶(`~/.agents/memory/no-long-sleep-in-session.md`):用户令「会话内禁止 sleep 超过 100 秒阻塞自身」,起因是会话用 `sleep 1500`/`2700` 阻塞等批、期间用户消息被卡;需要等待改用 `task_create`(结束自动唤醒)或定时任务。留在仓外的代价:新机装不上、行为没有测试、哪天被误删没人发现。
- **D29-2 原样收编**:入仓文件与部署位逐字节一致(sha256 相同),零行为差异。归属核实过两处:hub 仓(`~/workspace/a2a-mailbox`)与 kit 仓三个分支都没有同名文件,它不是 `a2a-inbox.ts` 那种外部所有件,也不是同步脚本从 kit 分支拷出来的。
- **D29-3 沿用原取舍——不做命令位区分**:分隔符枚举追不上 shell 语法,原决策迭代过两轮(`do … sleep`、`then sleep`)仍漏,于是定成「bash 工具是同步阻塞的,`sleep>100` 本身就是阻塞信号,宁误杀不放行」。所以 `echo sleep 999`、`grep "sleep 300" x` 这类读操作也被拦,这是有意为之,不是缺陷;被拦的模型换一种不经过 bash 命令行的写法即可,代价远小于会话被卡几分钟。
- **D29-4 已知漏网(实测本机 GNU coreutils 8.32)**:原意图是「任何 `sleep N` 折算秒 >100 一律拦」,但正则只认「空白 + 纯十进制数字 + 可选后缀」。实测 sleep 还接受 `1e-3`、`+0.001`、`.001`、`inf`/`infinity`(永久阻塞,实测时靠 `timeout 2` 兜底才截断)、`0x1p-10`、多个参数累加(`sleep 0.001 0.001`),对应 `sleep 1e3`、`sleep +300`、`sleep .5e3`、`sleep inf`、`sleep 90 90` 现版全部放行。补法见 D29-7。
- **D29-5 守卫**:behavioral `tests/test_no_long_sleep.py`(加载真模块,重放原始失败输入 `sleep 1500`/`2700`、后缀换算、`do`/`then` 嵌套、误杀样例;「尾部长 sleep 被拦后紧接着开头就是长 sleep」两条连发钉住 `g` 正则的 `lastIndex` 重置——不重置时第二条从残留位置开始扫,必然漏);pattern `lints/no_long_sleep.py` 守结构(`tool_call` 注册、限定 bash、阈值走 `SLEEP_LIMIT_SECONDS`、每个带 `g` 的正则使用前重置、拦截提示带 `task_create`);`test_deploy` 的部署集合加入新文件。
- **D29-6 部署**:部署位已有同内容文件,收编不需要部署动作;此后以仓内为源。只订阅 pi 核心 `tool_call`、不改工具 schema,单文件 `cp` 即生效(新会话自动加载),不需要空档。
- **D29-7 补漏(同日第二个提交)**:数值放宽到 GNU sleep 实际接受的十进制形态——前导 `+`、无整数部分(`.5`)、以 `.` 结尾(`5.`)、科学计数(`1e3`、`1E+3`),以及 `inf`/`infinity`,后缀不变;同一次 `sleep` 的多个参数先求和再比上限(`sleep 90 90` 按 180s 拦,`sleep 30 30` 放行)。实现改成两段正则:带 `g` 的 `SLEEP_WORD` 定位命令里每个 `sleep`,粘性正则 `SLEEP_DURATION` 从它后面连续吃时长参数;拦截提示回显全部参数与合计秒数,`inf` 写「永不返回」。新增会拦的字面量全是真等待形态,但按 D29-3 它们出现在字符串里也会被拦,所以误杀面随之略增(如 `echo "sleep 1e3"`)。**没做的**:①十六进制浮点(`sleep 0x1.2p10`,实测被接受)不认——要自己写解析,而它只可能是蓄意绕过;蓄意绕过还有变量、算术展开、写进脚本文件、内联解释器(`python3 -c "time.sleep(300)"`)等无穷种写法,机械护栏挡顺手不挡蓄意。②不同 `sleep` 之间不累加(`sleep 60; sleep 60` 各自放行),延续原设计逐个判定;循环体内的短 sleep(`for …; do sleep 5; done`)同理——要累加就得数循环次数,回到 D29-3 追不上 shell 语法的老路。③`sleep nan` 实测被 sleep 自己拒绝,不用管。守卫同步补了 18 条拦/放行用例(10 拦 8 放)与一条「提示回显每个参数与合计」。

## D30(扩展类型检查进 gate:tsc --noEmit 对已装 pi 的声明,2026-11-29,用户「做到你认为最好就行」)

- **D30-1 来历**:仓内 .ts 由 pi 的 jiti 与测试的裸 node 直接跑,从未经过类型检查;原以为只是「MODULE_TYPELESS_PACKAGE_JSON 警告被 pytest 吞掉」的小事,首跑 tsc(strict,对 pi 1.5.2 的声明)得到 16 条错误,其中**两个真缺陷**——①`todo.ts` 的 `renderResult(result, theme)`:pi 调的是 `renderResult(result, { expanded, isPartial }, theme, ctx)` 并 try/catch 回退默认渲染,第二参其实是 options,`theme.fg` 即 TypeError,自定义摘要行从没显示过、TUI 一直显示工具全文,回退是静默的所以一直没人发现(ee3beee);②`memory.ts` 的 `memory_save` 判重回执:store 层 hits 不带 scope/root,`formatHits` 里 `join(undefined, file)` 抛 ERR_INVALID_ARG_TYPE,模型只看到一句报错、看不到「疑似重复」与改法,用真实扩展复现并存 alpha-note 后再存 alpha-note-2 即抛(a585033)。其余是 `StringEnum`(JSON schema 对象,静态类型不随 `Type.Object` 流动)带来的 `unknown` 入参与非空假设,按类型收窄;`todo` 的 switch 走空还会返回 `undefined`(pi 1.5.2 调 execute 前不校验 schema),补了错误回执。
- **D30-2 做法**:`package.json`(private,`type: "module"`——顺带消掉 node 的 MODULE_TYPELESS 警告,仓内唯一 .js 是 ESM 模板)+ devDependency `typescript` ^7.0.2(锁文件入仓,`node_modules/` 忽略);`tsconfig.json` 是与机器无关的基线(strict / NodeNext / allowImportingTsExtensions / `types: ["node"]`);`lints/extension_types_check.py` 在临时目录生成 `extends` 基线的配置,把 `paths` 与 `typeRoots` 指向**已装 pi 包**里的声明文件。
- **D30-3 指向已装 pi 而不是自带一份声明**:扩展运行时用的就是部署位那份 pi,检查对象与运行对象一致,升级 pi 后的漂移当场暴露——实测 1.7.0 起 pi-tui 的 `Component.render` 返回 `readonly string[]`,quiet-tui 手写的本地类型在 1.7.0 下两个方向都冲突,已改成 `import type { Component }`(28ba64d)。代价:检查随本机安装走,CI 与干净 clone 上 `skip`。
- **D30-4 `paths` 必须指到声明文件而不是包目录**:TS 7 对 paths 映射到的目录不走 exports(typebox 只有 `exports`/`types`,指到目录会 TS2307)。四个映射:pi-coding-agent → `dist/index.d.ts`,pi-ai / pi-tui → 各自 `dist/index.d.ts`,typebox → `build/index.d.mts`;`typeRoots` 用 pi 包里的 `@types/node`。
- **D30-5 强制点**:`tests/test_lints.py::TestExtensionTypesCheck` 在 pytest 里真跑——仓内扩展零错误;把 todo 那种错误签名放进临时树必须被抓出来(报 `ToolRenderResultOptions`)。提交钩子(pre-commit 跑 pytest)在本机必过这一关;`run-lints.sh` 里它给出结论行(D2-8),缺 typescript 或缺 pi 时打 `skip(原因)`。耗时约 2 秒。
- **D30-6 没做的**:不给 `StringEnum` 造带类型的替身(它是 pi-ai 给不支持 anyOf 的供应商用的,保持原样,在工具入参处收窄);不把 tests/*.mjs 纳入检查(驱动是脚手架,靠 pytest 守);**发现但没动** `pi_guard_real_session` 满载下偶发「slice 限额不在位: max」——`enforceSlice()` 要等守卫第一次观察到 scope 的 cgroup 才写 memory.max,首条命令起跑到写入之间有窗口,单独重跑 3/3 绿。

## D31(kit 分支回归上游测试套:三个既有缺陷修复、workflowMaxConcurrency、同步范围扩到 skills,2026-11-29,aicontest 来信 9049377128d4 所托 + 用户「做到你认为最好就行」)

- **D31-1 来历**:kit 分支(0.26.3 + 四个补丁)rebase 之后从没跑过上游测试套——仓里没有 node_modules,pi-agent-kit 的两条 kit E2E 起的是**分支归档**的隔离会话而不是部署位。aicontest 托加 `workflowMaxConcurrency`,装依赖跑基线时发现:145 个测试文件里 8 个红(155 条),tsc 7 个错,biome 1 个错 7 个警告;逐条对过,**没有一条是 pi 1.5.2→1.7.0 造成的,全是 kit 自己的补丁在 rebase 后没跟上**。
- **D31-2 三个既有缺陷(kit 45ef955、151adba)**:①子会话标签补丁在 `AgentManager.launch` 里直接读 `ctx.sessionManager.getSessionId()` 与 `record.description.replace()`——上游测试的 ctx 替身没有 sessionManager(或只有 getSessionFile),Agent 工具的 `description` 只靠 schema 必填;任一缺失,派生本身抛 TypeError。修:标签模块加 `parentSessionIdOf`(可选链读取)、`sessionLabelFor` 接受可选 description——标签变短而不是派生失败;上游测试文件一行不动(为了以后合并)。②kit 自己的 7 个 RPC 处理器(schedule_list/remove/update、workflow_stop/pause/resume/status)的 unsub 创建后被丢:`RpcHandle` 只带上游的键,会话结束不清;同一进程里每次 session_start 再注册一遍,越积越多(一个请求 N 个回复、写操作执行 N 次)。biome 一直在报(7 条「未使用变量」)。修:归成一个 `unsubKit` 返回并在 shutdown 调用;变异验证去掉即红。③同批处理器从没过过 tsc:`handleRpc` 的泛型没写、import 顺序、`getSessionName()` 少一个 `?.`——一并修掉,kit 分支现在过得了上游 CI 的 `lint && typecheck`。测试侧:FEATURES 契约钉加上 `kit-schedule`/`kit-workflow`,`workflow_list` 按 kit 的 `{ runs }` 形状断言(rebase 时的郑重决定:一个频道一个处理器,bg_list 读 `{ runs }`);kit 的频道此前零单测,现在有了。
- **D31-3 workflowMaxConcurrency(kit 697e624)**:键名与读法同其它键(项目覆盖全局,`loadSettings` 按键合并);范围 1–16 的整数(`NUMERIC_SETTING_BOUNDS`),其它值载入时丢弃——即「回落到 CPU 口径」;语义 = 每个 run 的信号量取 `min(max(1, min(16, cpus−2)), 上限)`,run 各自为政、不跨 run 合计、不拒绝派生(只是发槽慢);生效时点 = run 起跑时读模块状态(改文件下次启动生效,设置面板里改则从下一个 run 起)。显式 `RunWorkflowOptions.concurrency` 仍优先(测试在用,生产无人传)。`/agents → Settings` 加一行(排在三个并发上限之后,未设时显示 `CPU (N)`);Del 回落到默认时必须显式清内存(`resetSetting` 分支)——`SETTING_DEFAULTS` 里它是 `undefined`。三条必修测试(设 3 + parallel 10 → 峰值 3;未设 → 峰值 = min(10, CPU 口径);非法值回落)都在,另加设置面板的「输入→重启→Del」闭环;三处变异验证全转红。
- **D31-4 同步范围扩到 skills(D24-4 的「只同步 src」作废)**:`skills/workflow-authoring/SKILL.md` 是模型读的说明,kit 这次改了它;同步脚本原来只归档 `src`,部署位的 skills 悄悄落后。现在归档 `src` 与 `skills`(分支里有哪个带哪个),幂等判定看全部已同步目录,逐目录换入。单测 `test_sync_carries_skills_and_spots_one_left_behind` 守「src 一致而 skills 落后」这一种漂移。
- **D31-5 kit 仓的开发依赖不落盘**:上游 devDeps 钉的是 pi 1.1.0,本机装的是 1.7.0——vitest 全家(71 个包)与 typescript/biome/@types/node 隔离装在 `/tmp`(重启即失),仓内 `node_modules`(已 gitignore)是拼接的:vitest 全家物理拷入(**不能软链到 /tmp——`vi.mock` 路径下 `timers/promises` 会被解析到仓根**),pi 三个包与 typebox 软链到已装 pi 包的嵌套副本,ajv/croner/nanoid 软链到部署位(postcss 要的 nanoid 3 嵌套到它自己下面)。跑法:`node node_modules/vitest/vitest.mjs run`、`node node_modules/typescript/bin/tsc --noEmit`、`node node_modules/@biomejs/biome/bin/biome check src/ test/`(剩的 1 条 warning 是上游 main 自己的 `useOptionalChain`)。

## D32(quiet-tui 折叠 codemode,2026-11-29,用户「收拢工具没有收拢codemode」)

- **D32-1 来历与根因**:用户开了 `+codemode`(pi 1.7.0 的内建工具:在 QuickJS 沙箱里跑模型写的 JS,`await tools.<name>()` 调别的工具)后,codemode 调用在 TUI 里仍是多行块。根因:pi 1.7.0 把 codemode 的渲染器**挂在工具定义上**(`dist/extensions/codemode/tool.js` 展开 `codemodeRenderers`),不在 `createAllToolRenderers()` 那张表里;quiet-tui 的 `takesOver` 只认「内建名单 + `mcp__*` + 没有自带渲染器的」,于是把 codemode 当成「自带渲染器的工具」原样透传 → pi 默认块(实测 19 行:标题 + 代码预览 ≤10 行 + 嵌套调用 ≤8 条 + 输出预览 + 计时)。
- **D32-2 折叠形态**:摘要行 = `codemode <脚本首个有效行,截 60 字符> (+N lines)`——跳过可选首行 `// @options: {...}`(元数据不是脚本),行数只数有效行。运行中给一行嵌套调用进度:`N calls · <状态符> <最近一次调用名> <耗时>`,有失败加 `· K failed`——嵌套调用不会单独成行(pi 的设计:它们从不到达模型),折叠后不给这一行就完全看不出脚本在做什么。完成且无错 → 只剩摘要行(与其它工具一致,输出靠 Ctrl+O);出错 → 摘要行 `✗` + 一行真正的错误首行:剥掉 `Script failed`／`Wall time …`／`Output:`／`Script error:` 这些头,直接给 `TypeError: …`／`Script timed out: …`(沿用通用 `firstLine` 只会显示 `Script failed`)。展开态沿用既有委托(`base.renderCall`／`PaddedFrame`):代码高亮、嵌套调用明细、全文输出都在。
- **D32-3 守卫**:①behavioral `quiet_tui_collapsed_rows` 加三个场景(codemode／codemode_fail／codemode_expanded),base 用 pi 真的 `codemodeRenderers`(`dist/extensions/codemode/renderer.js`)——`withBuiltInRenderers("codemode")` 得 undefined,场景会平凡通过;driver 对形状做断言,pi 把渲染器挪了位置会显式失败;变异验证:名单去掉 codemode → 9 条红,复现 19 行。②新 lint `quiet_tui_covers_pi_tools`(问题即 lint):隔离会话(空 HOME、不加载任何扩展与包)、`defaultTools` 全开内建,取首个模型请求的 tools 名单,每个都必须在 `BUILTIN_TOOLS` 里——pi 升级后再冒出名单外的内建工具当场报。③纯函数:`scriptLines`、`nestedCallProgress`(未知状态与原型键 `constructor` 都回落到「进行中」)、`codemodeFailure`。
- **D32-4 踩坑**:①守护 lint 不能加 `--no-extensions`——它连内建扩展一起关(codemode、grep、find、ls、powershell 都是内建扩展),名单只剩 bash／edit／read／write;隔离 HOME 本来就没有用户扩展与包,不加即可。②pi 的默认集合只有 bash／edit／read／write;grep／find／ls／powershell／codemode 都要 `+` 才激活——用户 `defaultTools: ["+codemode"]` 的会话实际是五个内建工具。lint 的 `ACTIVATED_BUILTINS` 写全开,覆盖九个。③HTML 导出里脚本代码属于调用头(单行摘要),结果区只有嵌套调用与输出——断言别写成「展开态含代码」。
- **D32-5 没做的**:①`details.fullOutputPath`(输出被截断时存全文的临时文件)折叠态不另起一行——与其它工具一致(输出靠展开),展开态 pi 原渲染器会给;②pi 新增「不默认激活」的内建工具时守护 lint 发现不了(只能发现默认集合的变化),要在 `ACTIVATED_BUILTINS` 登记;③折叠态不启动 pi 的计时器(`startToolTimer`)——没有 Elapsed 实时计时,与 bash 折叠一致,展开时才启动。
- **D32-6 部署**:单文件 `cp extensions/quiet-tui.ts ~/.pi/agent/extensions/quiet-tui.ts`;不改 schema。在跑的会话要 `/reload` 或重启才换(不替用户重启);回退 = `git revert` 本提交后重新 cp + reload。

## D33(命令输出转存件一天吃掉 29G:pi-guard 停掉热循环后删转存件、测试的临时目录隔离,2026-11-29,aicontest 来信 cee755d481d1)

- **D33-1 事故**:aicontest 发现 `/tmp/pi-bash-*.log` 24 小时堆了 97 个、29G,全部出自本仓的失控防护测试,它已删掉。核对:pi 1.7.0 的命令工具在输出超过 50KB／2000 行后,由 `OutputAccumulator` 把**全部**输出流式写进 `tmpdir()/pi-bash-<16 位 hex>.log`——没有上限,全仓没有任何清理(设计意图是给模型留全文)。本仓起真实会话／真命令工具的测试里,`hot_loop`／`reading_loop` 夹具满速刷同一行(实测 ~230MB/s):每次 gate 落 4 个文件(`pi_guard_real_session` 1 个、`pi_guard_e2e_containment` 的 spin／reads／bounded 3 个),单文件 95–517MB,没人清。`tests/test_pi_guard.py` 用的是假命令工具,不落盘。
- **D33-2 工具侧(pi-guard)**:停掉空转热循环后顺手删掉它的输出转存件,回执写明「完整输出转存件(NMB,只有这一行的重复)已删除」——被停的热循环全文只有同一行的重复,折叠后的回执已带证据,全文没有保留价值。只对 `spin` 裁决做,只删 basename 形如 `pi-bash-<16 位 hex>.log` 的路径(`spillPathOf`);没被停的命令(带 timeout 的、读输入的)转存件原样保留。变异验证:去掉删除动作,两条真实会话 lint 都红。
- **D33-3 测试侧**:①凡起 pi 子进程或 pi-guard 驱动的测试／lint,子进程的 `TMPDIR` 指向测试自己的临时目录,跑完随目录删除——pi 的转存、jiti 编译缓存、驱动的 home 目录都落在里面,共享的 `/tmp` 不再留东西。新 pattern lint `real_session_tmpdir_isolated` 守这条(文件含 `PI_CODING_AGENT_DIR` 或 `pi_guard_driver.mjs` 且调用 subprocess → 必须有 `"TMPDIR"`);它一落地就抓出四个我漏数的文件。②刷屏夹具降速:每批 100 行后 sleep 5ms,输出率 ~2MB/s——仍是热循环判定阈值(100KB/s)的 20 倍,写盘量降约 110 倍(每次 gate 从 ~1.3GB 降到几十 MB,且不再遗留)。③顺手清掉 `/tmp` 下历史遗留的 613 个 `pi-guard-driver-*`(11MB,驱动每次运行留下的 home 目录)。
- **D33-4 没做的**:①转存上限(只留头尾若干 MB)在 `OutputAccumulator` 里,是 pi 上游的事;扩展层只能 monkey-patch 内部模块,不做,建议向上游提。②会话结束时清掉本会话的全部转存件——改变上游语义(TUI 里的 `Full output: …` 路径失效、事后看不了全文)、被杀的会话清不了、也超出 pi-guard「失控防护」的职责;前两项做完后日常遗留的量级可控(只有超过 50KB 的输出才转存),不做。③热循环判定窗口(默认 60s)内已写入的转存:被停即删,瞬时占用取决于输出率,不另限速。
- **D33-5 踩坑**:断言「临时目录为空」太宽——pi 把 jiti 编译缓存也放在 `tmpdir()/jiti`,只看 `pi-*.log`;规则只按「含触发词」判定会误伤只读驱动源码的 lint,要加「且调用 subprocess」。
- **D33-6 部署**:`cp extensions/pi-guard.ts ~/.pi/agent/extensions/`;不改 schema;在跑的会话 reload 才换,新会话自动生效。
