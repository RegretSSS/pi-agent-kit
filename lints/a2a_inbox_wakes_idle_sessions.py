#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "a2a-inbox.ts"
    if not path.exists():
        print("a2a_inbox_wakes_idle_sessions: extensions/a2a-inbox.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if not re.search(r"sendUserMessage\(", source):
        violations.append("缺少 sendUserMessage 唤醒通道")
    if re.search(r"(?:await\s+)?(?:pi|ctx)\.sendUserMessage\([^;]*?\)\s*\.(?:then|catch|finally)\b", source, re.DOTALL):
        violations.append("sendUserMessage 被链式调用——ExtensionAPI 层(pi 1.5.0 agent-session.js:2792)fire-and-forget 返回 undefined,.then 即 TypeError 崩掉宿主 pi(11-07 事故第一雷)")
    if re.search(r"await\s+(?:pi|ctx)\.sendUserMessage", source):
        violations.append("await sendUserMessage——同因返回 undefined,await undefined 虽不炸但语义是假承诺;直调即可")
    if not re.search(r'deliverAs:\s*"steer"', source):
        violations.append("缺少 deliverAs: \"steer\"——idle 时 streamingBehavior 被整体忽略走正常提交(唤醒),streaming 时入打断队列;缺省则 streaming 中同步 throw")
    if re.search(r'deliverAs:\s*"followUp"', source):
        violations.append("deliverAs: followUp 禁用——两级队列里恒劣后于用户手打字,长回合场景信饿死(11-07 事故结论)")
    send_at = source.find("sendUserMessage(")
    if send_at >= 0:
        window = source[send_at:send_at + 1200]
        catch_at = window.find("catch")
        if catch_at < 0:
            violations.append("sendUserMessage 未包同步 try-catch——运行时未就绪时 action 方法同步 throw,裸调会在加载期炸 pi(11-07 事故第二雷)")
        else:
            catch_block = re.search(r"catch\s*\{([^{}]*)\}", window[catch_at:], re.DOTALL)
            if catch_block and re.search(r"rcpt|openSync", catch_block.group(1)):
                violations.append("catch 分支里写 rcpt——发送已失败还标已送达,信会被跳过;正确语义是留队由周期重扫幂等补投")
    if not re.search(r"setInterval\(\s*scanQueue", source):
        violations.append("缺少 setInterval(scanQueue) 周期重扫——fs.watch 单独不可靠(事件丢失/启动期遗留),5s 幂等重扫是兜底(11-07 事故第二雷的解)")
    for violation in violations:
        print(f"a2a_inbox_wakes_idle_sessions: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
