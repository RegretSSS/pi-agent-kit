#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "memory.ts"
    if not path.exists():
        print("memory_cache_fingerprint_filelevel: extensions/memory.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    probe = re.search(r"private async probeDirFingerprint\(\)[^{]*\{(.{0,900}?)\n\t\}", source, re.DOTALL)
    if not probe:
        violations.append("缺少 probeDirFingerprint——缓存失效探测不存在")
    else:
        body = probe.group(1)
        if "readdir" not in body or "stat" not in body:
            violations.append("指纹必须聚合目录内逐文件 stat——只看目录 mtime 探测不到'已存在文件的内容更新'(writeFile 原地改内容不改父目录 mtime,11-08 实证:另一进程增量更新后本进程 listEntries 永用旧缓存,索引少报条目)")
    if re.search(r"probeDirMtime|dirMtimeMs", source):
        violations.append("残留目录级 mtime 探测——已被文件级指纹取代,双探测并存会出现强弱失效不一致")
    if re.search(r"private async dirUnchanged\(\)[^{]*\{(.{0,300}?)\n\t\}", source, re.DOTALL) and "probeDirFingerprint" not in re.search(r"private async dirUnchanged\(\)[^{]*\{(.{0,300}?)\n\t\}", source, re.DOTALL).group(1):
        violations.append("dirUnchanged 未走 probeDirFingerprint——失效判断绕过文件级指纹")
    if violations:
        print(f"memory_cache_fingerprint_filelevel: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("memory_cache_fingerprint_filelevel: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
