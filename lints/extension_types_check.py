#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SDK = "@earendil-works/pi-coding-agent"
DECLARATIONS = {
    SDK: "dist/index.d.ts",
    "@earendil-works/pi-ai": "node_modules/@earendil-works/pi-ai/dist/index.d.ts",
    "@earendil-works/pi-tui": "node_modules/@earendil-works/pi-tui/dist/index.d.ts",
    "typebox": "node_modules/typebox/build/index.d.mts",
}
SKIP = object()


def sdk_root() -> Path | None:
    override = os.environ.get("PI_PACKAGE_ROOT")
    pi = shutil.which("pi") or str(Path.home() / ".local" / "bin" / "pi")
    resolved = Path(override or pi).resolve()
    candidates = [resolved] if override else resolved.parents
    for candidate in candidates:
        if (candidate / DECLARATIONS[SDK]).exists():
            return candidate
    return None


def generated_config(root: Path, sdk: Path) -> dict:
    return {
        "extends": str(ROOT / "tsconfig.json"),
        "compilerOptions": {
            "typeRoots": [str(sdk / "node_modules" / "@types")],
            "paths": {name: [str(sdk / relative)] for name, relative in DECLARATIONS.items()},
        },
        "include": [str(root / "extensions" / "**" / "*.ts")],
    }


def check(root: Path | None = None) -> list[str] | object:
    root = root or ROOT
    tsc = ROOT / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.exists():
        print("extension_types_check: skip(仓内未装 typescript,npm install 后生效)")
        return SKIP
    sdk = sdk_root()
    if sdk is None:
        print("extension_types_check: skip(默认路径下无 pi,取不到 SDK 声明)")
        return SKIP
    with tempfile.TemporaryDirectory(prefix="extension-types-") as tmp:
        config = Path(tmp) / "tsconfig.json"
        config.write_text(json.dumps(generated_config(root, sdk)))
        result = subprocess.run(["node", str(tsc), "-p", str(config)], capture_output=True, text=True, cwd=root)
    return [line for line in result.stdout.splitlines() if "error TS" in line]


def main() -> int:
    problems = check()
    if problems is SKIP:
        return 0
    for line in problems:
        print(f"extension_types_check: {line}")
    if problems:
        return 1
    version = json.loads((sdk_root() / "package.json").read_text())["version"]
    print(f"extension_types_check: ok(对已装 pi {version} 的声明,strict)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
