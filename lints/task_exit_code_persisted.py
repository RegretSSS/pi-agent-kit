#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "tasks.ts"
    if not path.exists():
        print("task_exit_code_persisted: extensions/tasks.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if 'spawn("/bin/bash", ["-c", exitRecordingCommand(params.cmd, registry.exitPath(id))]' not in source:
        violations.append("task_create 没有经 exitRecordingCommand 包裹——创建它的实例丢失子进程句柄(reload/重启)后,退出码只能记成 unknown(reaped)")
    if "const code = exitCode ?? (signal ? null : await this.readExitCode(id));" not in source:
        violations.append("markExit 未在无码无信号时回落读 <id>.exit——回收路径拿不到真实退出码")
    if "await this.markExit(task.id, null);" not in source:
        violations.append("reapDeadPids 未走 markExit——绕过即丢 <id>.exit 里的退出码")
    if "await rm(this.exitPath(id), { force: true });" not in source:
        violations.append("gc 未清 <id>.exit——登记目录随任务数线性留垃圾")
    if violations:
        print(f"task_exit_code_persisted: {len(violations)} 处违规")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("task_exit_code_persisted: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
