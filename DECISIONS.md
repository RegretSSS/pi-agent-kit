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
