#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "subagent-jobs.ts"
    if not path.exists():
        print("workflow_status_journal_fallback: extensions/subagent-jobs.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    status = re.search(r'name: "workflow_status".{0,1800}?async execute', source, re.DOTALL)
    if not status:
        violations.append("缺 workflow_status 工具")
    else:
        block = source[status.start():status.start() + 2600]
        if "workflowJournalTail" not in block:
            violations.append("workflow_status 无 journal 降级——RPC patch 未打/超时即全盲(11-15 aicontest 工单③),只读 journal tail 是 patch 前的最小可观测面")
    if "RUN_ID_SHAPE" not in source or not re.search(r"RUN_ID_SHAPE\.test\(runId\)", source):
        violations.append("journal 降级缺 runId 白名单校验——readdir/readFile 拼 ../../ 路径即任意文件读取")
    if re.search(r'text !== "string"\s*\|\|\s*typeof entry\.text', source) or re.search(r'entry\.ok !== "boolean" \|\| typeof entry\.text !== "string"', source):
        violations.append("journal 收行以 text 存在为条件——上游 ok:false 条目从不带 text(实测 4 个落盘点),此条件把失败条目全部丢弃,跑飞的 run 在降级视图里显示为全部成功(审查#1)")
    if "workflow_list" in source:
        block = source[source.index('"workflow_list"'):source.index('"workflow_list"') + 3000]
        if "journal" not in block:
            violations.append("workflow_list 无 journal 降级——RPC 挂时连有哪些 run 都不可见")
    if violations:
        print(f"workflow_status_journal_fallback: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("workflow_status_journal_fallback: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
