---
name: subagent-workflows
description: "Use when writing, editing, or re-running a SubagentWorkflow script: routing (workflow vs Agent vs codemode), topology (fresh-per-item vs resume), pipeline vs parallel, schema results, deterministic gates, independent confirmation, report shape, early-stop + resumeFromRunId, saving parameterized workflows — plus the pattern library (adversarial verify, judge panel, loop-until-dry, multi-modal sweep, completeness critic) and pi-ecosystem combinations (memory warm-up, history recall, job re-checks)."
---

# 用 SubagentWorkflow 编排 subagent

本 skill 是写 SubagentWorkflow 脚本的判断层。机制参考:`~/.pi/agent/npm/node_modules/@tintinweb/pi-subagents/docs/workflows.md`(先读它拿到原语签名,本文件管"怎么选、怎么写才对")。

## 0. 路由:什么时候根本不该起 workflow

| 请求 | 用什么 |
| --- | --- |
| 一件事委托一个 agent | `Agent` 工具 |
| 几个独立查询,互不读对方结果 | `Agent`,单消息并行 |
| 用户点名 "workflow / 工作流 / 编排" | SubagentWorkflow,必选,再小也是小 workflow |
| agent 数量要跑起来才知道(审计每个文件/每个路由);工作分阶段流转;发现需要独立验证后才可信 | SubagentWorkflow |

数量在运行时才存在、阶段间有流转、结论要独立确认——这三条是 workflow 的正当地盘。一个任务硬拆成三个 agent 不是。每个 agent 是一次完整模型会话,把会话花在能提升置信度的地方,不是花在互相复读上。

## 1. 拓扑:fresh-per-item 还是共享上下文

每次 `agent()` 都是新上下文。两种形态:

```js
const verdicts = await parallel(items.map((it) =>
  agent(`Judge ${it.id}. Other items are not your concern.`, { label: `judge:${it.id}` })))
```

fresh-per-item(默认):各 item 互不污染,可并发。评审、审计、迁移——答案之间无需一致时,永远用它。

```js
await agent('Triage this batch. Rank on one scale.', { label: 'triage' })
const verdict = await agent(`Classify: ${finding}`, { label: 'triage', resume: 'triage' })
```

共享上下文 = `resume` 同一 label:child 保留前文,后面的判定与前面一致(校准),代价是排队串行。适合:跨批次统一排名、需要累积理解的分类。把 `agent()` 提出循环"图整洁"会把 fan-out 变 FIFO 队列,没有任何机制拦你——这是最贵的笔误。

**循环必须带上限,feedback 前传,同 label 复用:**

```js
let feedback = 'none'
for (let round = 1; round <= 5; round++) {
  const fix = await agent(`Fix it. Gate said: ${feedback}`, { label: 'fix', resume: round > 1 ? 'fix' : undefined })
  if (await passesGate(fix)) break
  feedback = await agent(`What still fails? ${fix}`, { label: 'check', resume: round > 1 ? 'check' : undefined })
}
```

round 5 复用 round 4 的上下文,便宜;但 reviewer 会锚定自己的旧批判——最后一轮换一个从未参与的新 agent 做独立复核(§4)。

## 2. 阶间接缝:pipeline 默认,barrier 要挣得

`pipeline(items, s1, s2)`:无 barrier,A 文件已在验证时 B 文件还在被审计,总时长 = 最慢单链。`parallel(thunks)`:barrier,等齐才动。**barrier 只在下一步真的需要全量时用**:跨文件去重、单一尺度排名、综合报告——并在旁边写一句为什么需要全量。map/filter/flatten 不是 barrier 理由,塞进 pipeline 的 stage 里做。

stage 回调拿 `(prevResult, originalItem, index)`,不用把 item 穿透返回值。pipeline 内用 `phase` **选项**分组(ambient `phase()` 在并发下会串组)。

## 3. 结构化结果:schema 是压力不是保证

pi 的 `schema` 给 child 加 StructuredOutput 工具 + 采样偏好 + 校验重试——三重软压力,仍可能返回 `null`。纪律:

- 控制流要分支的结果,**永远带 schema**;纯文本交付不用。
- schema 小而平,字段语义写进 prompt(JSON Schema 的 description 子 agent 真的会读):
  ```js
  const VERDICT = {
    type: 'object',
    properties: {
      holds: { type: 'boolean', description: 'true 仅当你在代码/命令输出里亲眼复核了证据' },
      why: { type: 'string', description: 'file:line 依据,一句话' },
    },
    required: ['holds', 'why'],
  }
  ```
- **每个 schema 阶段之后 `.filter(Boolean)`**——`null` 是失败或被你在 inspector 里 skip,无法区分。
- 无 schema 的文本返回要可解析:prompt 里规定"每行一个路径,别无其他",然后 `split('\n').map(s => s.trim()).filter(Boolean)`。任何 `parse` 外面包 try,坏行丢弃并 `log` 裁剪数,别让一条脏行炸整链。
- 结果传 **path 不传内容**:child 有自己的文件工具,把 4000 行文件插值进 prompt 是花两遍 token。

## 4. 确定性 gate 优先,findings 独立确认

命令能判定的事,不问 agent。`gate: 'npm test'` 在 agent 结束后真跑命令,非零即失败——比"让 agent 跑测试然后转述"强一个量级(agent 的转述是可以伪造的声明,exit code 不能)。

选 gate 先侦察:项目的 package.json scripts / Makefile / CI 配置里最强的检查是什么?单测 < e2e < README 点名的验收命令。快档驱动循环,最强档在最终 `return` 前真跑一次——"存在而没跑的检查"不是"没覆盖",是未验证的交付,要么跑要么在结论里明说。

**用户会当事实采纳的 finding,逐条独立确认**:新 `agent()`、只给证据、要求复现或反驳("Try to REFUTE"),找到它的人不确认它。确认失败的 **保留并标 `unconfirmed`**——复现不出来的真问题仍值得人眼,标签区分"见过"与"疑似"。

三种假验证,都是浪费:命令已判定的 finding 再派 confirmer(exit code 就是确认);没人当事实用的产出(诗、头脑风暴)派验证者(至多一次独立通读);hunter、confirmer、gate 各跑一遍套件(gate 只跑一次,由脚本跑,ask 里写明"脚本会跑全量套件,你不要自己跑")。

## 5. report 形状:返回值是唯一交付

调用方只见 `return`,不见各 agent 的输出。返回这个形状而不是裸数组:

```js
return {
  conclusion: '直接回答用户问的问题,两三句。',
  findings: [{ where: 'src/a.ts:42', what: '一句话:错在哪', evidence: '读过的行/证明它的命令与输出',
               status: 'verified', severity: 'medium' }],
  verified: ['实际跑过的判定:npm test 全绿;覆盖 6 个路由文件'],
  notCovered: ['没查内存占用——只测了查询延迟;原因:无内存基准存在'],
}
```

- `status` 只有 `verified`(独立 agent 或命令确认过)/ `unconfirmed`,让用户分清"见过"与"疑似"。
- `verified`/`notCovered` 让用户拿它对撞自己的请求:"我们没找到"和"我们没看"是两回事。
- `severity` 的 high 留给数据丢失、崩溃、错误结果。
- 实体产物(网页/报告/数据文件):让 subagent 写进 workspace 并返回路径,主 agent 转述时点名路径——pi 没有 artifact 系统,return + 落盘文件就是全部交付面。
- 用户用中文提问,四个字段全用中文写。

## 6. pi 机制红线(违反 = 炸运行)

- `meta` 必须纯字面量(name/description 必填),脚本体是 async 函数体(顶层 await 与裸 return 合法)。
- **`Date.now()` / `new Date()` / `Math.random()` 抛异常**——可重放的脚本不能含不确定性;时间戳从 `args` 传入,随机用循环索引。
- 无 fs/network/模块访问:一切实际工作在 agent 里。
- 工具立即返回,run 后台进行,**不要轮询或 sleep 等通知**;迭代 = 编辑 `Script:` 行指的文件,再用 `scriptPath` 重跑——不是让模型重新生成源码。
- `resumeFromRunId` = 前缀重放:未改动的 `agent()` 前缀免费回放,第一个改动点之后全部真跑。**只改后段、只付后段**。同 session 有效;run 必须先停。
- 常量别插进 prompt:改阈值会改写所有提到它的 ask 文本 = cache 全清 + 下游全重付。阈值、轮数上限放控制流,子 agent 只需要 verdict 和 feedback,不需要数字。
- 并发自动 cap 在 `min(16, cpus-2)`,超发只排队不炸;单 run 上限 1000 agents。

## 7. 提前收笔:只写确定的部分,让 findings 写剩下

不确定后段拓扑时,**写到发现阶段的输出为止就 return**——先把 discovery 跑完,读结果,再编辑脚本补后段,`resumeFromRunId` 重跑(discovery 前缀免费,只付新段)。猜一个拓扑不是深度,是浪费。对应地:值得再用的脚本落盘到 `.pi/workflows/<name>.js`(项目)或 `<agent dir>/workflows/<name>.js`(全局),目标路径换成 `args?.root ?? 默认值`,之后"run the auth-audit workflow against src/api" 一句话复用。

## 8. 最小检查单(提交脚本前过一遍)

- [ ] 路由对吗——这是 Agent 能干的事吗?数量是运行时才知道的吗?
- [ ] 拓扑:每个接缝下一步拿单件还是全量?全量的 barrier 写了理由吗?
- [ ] 循环有上限;feedback 在前传;最终复核是新鲜上下文。
- [ ] 分支用结果都有 schema,且每段后 `filter(Boolean)`;传 path 不传内容。
- [ ] 命令能判定的都走了 gate;最强检查 return 前真跑过一次或明说未验证。
- [ ] 会被当事实的 findings 逐条独立确认;未确认的标着保留。
- [ ] return 是 report 形状,四字段齐全,中文提问中文作答。
- [ ] 脚本里没有 Date/Math.random;没有常量插进 ask 文本。

## 9. 模式库(按需展开;常驻工具描述只留指针)

单阶段可跨回合串联:Understand(并行读→结构图)/ Design(N 独立方案→并行评分→综合)/ Review(维度→找→对抗验证)/ Research(多模态扫→深读→综合)/ Migrate(发现点→逐点改造(worktree 隔离)→验证)。大工作拆多个 workflow 顺序跑,每个结果读完再定下一阶段——你在环上,每个 workflow 只管一次有界的 fan-out。

**对抗验证**(每 finding 派 N 个独立怀疑者,只许反驳;多数反驳即杀):

```js
const votes = await parallel(Array.from({length: 3}, () => () =>
  agent(`Try to refute: ${claim}. Default to refuted=true if uncertain.`, {schema: VERDICT})))
const survives = votes.filter(Boolean).filter(v => !v.refuted).length >= 2
```

**判定面板**:N 个不同角度(MVP 优先/风险优先/用户优先)独立生成,并行评分,赢家做骨架、吸收亚军的好点子——解空间宽时胜过单案迭代。

**loop-until-dry**:未知规模的发现类任务,连续 K 轮无新发现才停;简单计数器(while < N)会漏尾部。

**多模态扫描**:每个 agent 一种找法(按容器/按内容/按实体/按时间),互不可见——单一检索角度找不全时。

**完备性批评**:收尾一个 agent 只问"缺了什么——没跑的模态、没验证的声称、没读的源",它的产出是下一轮的工单。

**无静默截断**:有界覆盖(top-N/无重试/抽样)必须 `log()` 丢弃了什么——静默截断读起来像"全覆盖"。

**规模跟着请求走**:"找点 bug"→几个 finder+单票验证;"彻底审计"→大 finder 池+3-5 票对抗+综合阶段。

完整可运行示例(review-changes 管线、barrier 去重、loop-until-count、gate-and-retry、find→dedup→panel→until-dry 组合)见 `docs/workflows.md` 同目录的 tool-description 存档或上游仓库;写脚本时按 §8 检查单组装,不照抄示例。

## 10. 与 codemode 结合

workflow 脚本无 fs/shell,确定性长任务的等价能力分两处:

- **确定性节点** = codemode:子任务预计 ≥3 轮工具往返(调试循环/批量巡检/守窗式轮询、写-跑-改链)→ 在 agent() 的 prompt 里明确指示"编一个脚本跑,只返回结论与依据";子代理读 AGENTS.md 自动继承「codemode 选取」决策树。纯等待类(长时间盯一个外部状态)不进 workflow——那是扩展常驻层的活(§12)。
- **编排层**:跨 agent 扇出/阶段流转/收敛判定 = SubagentWorkflow;单链多轮工具 = codemode。不要用 workflow 编排"一个人的串行工作",也不要用 codemode 硬模拟扇出。

**持久角色**:循环里的固定角色(fixer/checker/relay)首轮创建、后续轮次全部 `resume: '<label>'` 复用同一上下文(§1)——省重建成本且行为前后一致。

finder/verifier 的 prompt 模板显式带工具纪律:"读文件用 read 不用 cat;≥3 轮就进 codemode;返回 path 不返回内容"。

## 11. pi 生态组合

- **记忆预热**:finder prompt 首行加 `先 memory_search "<领域词>" 再动手`——子代理各自有 memory 工具,跨会话事实不用重新推导
- **跨代溯源**:长任务跨多次 compact 后,让 reporter 用 `history_search("<主题>")` 回捞前代压缩块核对结论连续性
- **定时复查**:小时级的长周期 workflow 不挂在会话里等——job(定时任务)到点巡查,发现需要深挖时在晨报里建议起 workflow,由主 agent/用户决策规模(opt-in 规则不破)
- **gate 挂仓内纪律**:有 lints 的仓,gate 首选 `run-lints.sh` 或 pytest(管道退出码),比"看起来对"强一个量级;最强检查在 return 前真跑一次(§4)
