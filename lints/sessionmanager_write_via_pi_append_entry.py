#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    violations = []
    for path in sorted((ROOT / "extensions").glob("*.ts")):
        source = path.read_text(errors="ignore")
        for m in re.finditer(r"ctx\.sessionManager\.(append\w*)\(", source):
            line = source[:m.start()].count("\n") + 1
            violations.append(f"{path.name}:{line} ctx.sessionManager.{m.group(1)}——工具/事件 ctx 的 sessionManager 是 ReadonlySessionManager(pi types.d.ts,只有读方法),写入口在 ExtensionAPI 层:pi.appendEntry(customType, data)。错层调用运行时 TypeError,execute 内无捕获则工具整体报错(11-13 aicontest 实锤:todo add 五连\"ctx.sessionManager.appendEntry is not a function\",状态从未落盘)")
    for path in sorted((ROOT / "tests").glob("*_driver.mjs")):
        source = path.read_text(errors="ignore")
        if re.search(r"sessionManager:\s*\{[^}]*append", source, re.DOTALL):
            violations.append(f"{path.name}: driver 给 mock ctx.sessionManager 造了写方法——mock 按错误假设自证绿灯(D21 事故根因),写入口 mock 必须挂在 pi.appendEntry 上")
    if violations:
        print(f"sessionmanager_write_via_pi_append_entry: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("sessionmanager_write_via_pi_append_entry: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
