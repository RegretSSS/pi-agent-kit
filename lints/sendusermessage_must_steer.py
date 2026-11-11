#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    violations = []
    for path in sorted((ROOT / "extensions").glob("*.ts")):
        source = path.read_text(errors="ignore")
        for m in re.finditer(r"sendUserMessage\(", source):
            window = source[m.start():m.start() + 400]
            if "deliverAs" in window.split(");")[0] or re.search(r"deliverAs:\s*\"steer\"", window):
                continue
            line = source[:m.start()].count("\n") + 1
            violations.append(f"{path.name}:{line} sendUserMessage 未带 deliverAs: \"steer\"——idle 时 steer 被忽略走正常提交(启动 run),busy/streaming 语境下缺省则 prompt() 同步 throw(D16 三坑之三),错误被 bind 层 .catch 静默吞(11-11 compact 唤醒失灵事故)")
    if violations:
        print(f"sendusermessage_must_steer: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("sendusermessage_must_steer: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
