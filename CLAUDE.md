# pi-agent-kit 开发规则

1. 一切以 SPEC.md 为准；未覆盖的选型自行决策并记 DECISIONS.md
2. 代码零注释：想写注释 = 命名不好，去改名
3. 问题即 lint：每发现一个问题（含踩坑）在 lints/ 新建一条规则，一规则一文件，接入 scripts/run-lints.sh
4. lint 分层：结构约定→pattern（源码扫描）；行为语义→behavioral（加载真模块+临时环境+重放原始失败输入）；跨端闭环→E2E
5. 内存纪律：热路径对象字面量/闭包/new 慎用（能提升/复用/池化就做），发现乱分配立即写一条 lint
6. conventional commits；gate（pytest + run-lints.sh 全绿）过了才提交；逐件独立 commit
7. 死锁红线：扩展工具 execute 内禁止等待任何跨回合回调/事件（立即返回，边界事件续做）
8. 无人值守模式：不问询、不等待；花钱/破坏性/对外发布的动作列入最终汇报待批
