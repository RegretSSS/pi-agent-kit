#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = """
import { buildFtsQuery } from "%s/extensions/memory.ts";
import { DatabaseSync } from "node:sqlite";
const db = new DatabaseSync(":memory:");
db.exec("CREATE VIRTUAL TABLE f USING fts5(name, description, tokenize='trigram')");
db.prepare("INSERT INTO f VALUES (?,?)").run("aliyun-ops", "阿里云口径");
const query = buildFtsQuery(["aliyun-ops", "阿里云口径"]);
const rows = db.prepare("SELECT name FROM f WHERE f MATCH ?").all(query);
if (rows.length !== 1 || rows[0].name !== "aliyun-ops") {
  throw new Error("kebab 查询丢命中: " + query);
}
db.close();
""" % ROOT


def lint() -> list[str]:
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", PROBE],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        detail = "; ".join(result.stderr.strip().splitlines()[:5]) or "无输出"
        return [
            "fts5_query_quotes_kebab_names: buildFtsQuery 重放 kebab-case 原始失败输入未通过——"
            "FTS5 MATCH 中裸连字符被解析为 NOT 运算,查询词必须引号包裹:" + detail
        ]
    return []


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    print("fts5_query_quotes_kebab_names: ok" if not found else "")
    sys.exit(1 if found else 0)
