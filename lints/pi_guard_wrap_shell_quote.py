#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAP_TAIL = '-c",\n\t\tshq(command),'
WRAP_REQUIRED = ("--user --scope --quiet --collect", "shq(config.systemdRun)", "shq(config.bash)", "-p MemorySwapMax=0", "-p TasksMax=")
WRAP_FORBIDDEN = ("-p MemoryMax=", "MemoryOOMGroup", "PidsMax=")


def lint(root: Path | None = None) -> list[str]:
    path = (root or ROOT) / "extensions" / "pi-guard.ts"
    if not path.exists():
        return ["pi-guard.ts 不存在"]
    source = path.read_text(errors="ignore")
    problems = []
    wrap = re.search(r"export function wrapCommand\(.*?\n\}", source, re.DOTALL)
    if wrap is None:
        problems.append("缺 wrapCommand")
        return problems
    body = wrap.group(0)
    if WRAP_TAIL not in body:
        problems.append("包装串末段必须是把原命令整体作为 /bin/bash -c 的单个参数并经 shq 转义——拼接或分词会让引号/元字符逃逸")
    for needle in WRAP_REQUIRED:
        if needle not in body:
            problems.append(f"包装串缺 {needle}")
    for forbidden in WRAP_FORBIDDEN:
        if forbidden in body:
            problems.append(f"包装串含 {forbidden}——systemd 249 不认 MemoryOOMGroup/PidsMax(Unknown assignment 使命令直接失败);按命令设 MemoryMax 会先杀合法任务放过失控者")
    if "-u INVOCATION_ID" not in body or "SHLVL=$((SHLVL - 1))" not in body:
        problems.append("包装串未抵消 systemd-run 注入的 INVOCATION_ID 与多一层 bash 带来的 SHLVL+1——被包命令看到的环境与未包装时不一致")
    rewrite = re.search(r"private rewrite\(.*?\n\t\}\n", source, re.DOTALL)
    if rewrite is None:
        problems.append("缺 tool_call 改写入口 rewrite")
    else:
        if "isWrapped(command)) return;" not in rewrite.group(0):
            problems.append("改写前未做幂等判定 isWrapped——重复包装会让命令层层套壳")
        if "wrapFits(wrapCommand(command, candidate, this.config))" not in rewrite.group(0):
            problems.append("改写前未做单参数长度判定 wrapFits——超 128KB 的单个 argv 会让 spawn 以 E2BIG 失败")
    if 'writeCgroup(entry.scopeDir, "cgroup.kill", "1")' not in source:
        problems.append("隔离模式的停止动作必须是写 scope 的 cgroup.kill=1——整组 SIGKILL 且不误伤 scope 外进程")
    if 'ensureLimit(this.sliceDir, "memory.max", String(this.config.sliceMax))' not in source:
        problems.append("硬顶必须经 ensureLimit 落在 slice 聚合线上")
    if re.search(r'writeCgroup\([^)]*"memory\.max"', source):
        problems.append("不得向单命令 scope 写 memory.max——按命令分顶会先杀后来的合法任务、放过先占住内存的失控者")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(f"pi_guard_wrap_shell_quote: {item}")
    print("pi_guard_wrap_shell_quote: ok" if not found else "")
    sys.exit(1 if found else 0)
