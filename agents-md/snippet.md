# AGENTS.md

全局 agent 工作口径。本文件「问题即 lint」「codemode 选取」两节由 pi-agent-kit 仓管理(版本化真相 `agents-md/snippet.md`,部署 `deploy.sh`);节外内容归本机维护者,部署时原样保留。

## 问题即 lint

每发现一个问题(含踩坑),先分流再落盘,四条去路:

1. 判定性知识——可写成「看到 X 就 fail」的规则 → 所在仓 `lints/`,一规则一文件,接入 `scripts/run-lints.sh`
2. 描述性事实——资产 / 端点 / 结构,脱离语境依然成立 → memory(type=reference)
3. 判断题——脱离语境无法机械判定的偏好与口径 → memory(type=feedback)
4. 战史 / batch 记录 → 只萃取教训(按 1/2/3 落盘),原文不进 memory,另行归档

lint 分类准则:

- 结构约定 → pattern lint:源码扫描即可判定
- 行为语义 → behavioral lint:加载真模块 + 临时环境 + 重放原始失败输入
- 跨端闭环 → E2E lint:双端实跑对照
- 守护行为语义的 pattern lint 必须升格 behavioral——源码扫描看不出行为对错

## codemode 选取

同一目标预计 ≥3 轮工具往返——调试循环、批量巡检、多文件同构操作、写-跑-改-再跑链——→ codemode 编一个脚本:中间态留在脚本内只 return 结论与依据,脚本内可无限量消费工具输出;单步可完成或每步需即时审视 → 直接工具。bash 里 sed 改脚本再跑的调试链 = 该进 codemode 的信号。
