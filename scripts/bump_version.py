"""版本号单一源 bump 脚本：四处声明一次改齐，杜绝徽章/清单漂移。

背景（2026-11-18 外部审查实锤）：v0.2.5 发版齐平了五处，README 徽章仍停在
0.2.4——版本声明散落多处时，手工齐平必有遗漏。本脚本把「改版本」收敛为
一条命令：`python scripts/bump_version.py 0.2.6 [--dry-run]`。

覆盖四处（各自格式不同，逐一定位）：
  1. service/pyproject.toml            `version = "x.y.z"`
  2. desktop/package.json + 根 package.json + protocol/package.json  `"version": "x.y.z"`
  3. service/dramaclip/__init__.py     `__version__ = "x.y.z"`
  4. README.md 徽章                    `badge/version-x.y.z-`

只动**版本声明行**（精确锚），不碰注释/提交信息里的历史版本号。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (文件, 旧串→新串的替换对列表)；旧串按精确锚匹配，失配即报错退出——
# 静默跳过会让「以为改齐了」比「忘了改」更难查。
_TARGETS: tuple[tuple[Path, tuple[tuple[str, str], ...]], ...] = (
    (
        REPO / "service" / "pyproject.toml",
        (('version = "{old}"', 'version = "{new}"'),),
    ),
    (
        REPO / "desktop" / "package.json",
        (('"version": "{old}"', '"version": "{new}"'),),
    ),
    (
        REPO / "package.json",
        (('"version": "{old}"', '"version": "{new}"'),),
    ),
    (
        REPO / "protocol" / "package.json",
        (('"version": "{old}"', '"version": "{new}"'),),
    ),
    (
        REPO / "service" / "dramaclip" / "__init__.py",
        (('__version__ = "{old}"', '__version__ = "{new}"'),),
    ),
    (
        REPO / "README.md",
        (
            ("badge/version-{old}-", "badge/version-{new}-"),
        ),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("new_version", help="目标版本号（如 0.2.6）")
    parser.add_argument(
        "--from",
        dest="old_version",
        default=None,
        help="当前版本号（缺省时从 service/dramaclip/__init__.py 读）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划不写盘")
    args = parser.parse_args()

    init_file = REPO / "service" / "dramaclip" / "__init__.py"
    old = args.old_version
    if old is None:
        match = re.search(r'__version__ = "(\d+\.\d+\.\d+)"', init_file.read_text(encoding="utf-8"))
        if match is None:
            print("__init__.py 读不到当前版本", file=sys.stderr)
            return 1
        old = match.group(1)
    new = args.new_version
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        print(f"版本号格式不对：{new}", file=sys.stderr)
        return 1

    failures = 0
    for path, pairs in _TARGETS:
        text = path.read_text(encoding="utf-8")
        original = text
        for template_old, template_new in pairs:
            needle = template_old.format(old=old)
            replacement = template_new.format(new=new)
            if needle not in text:
                print(f"[缺锚] {path.relative_to(REPO)}: {needle}", file=sys.stderr)
                failures += 1
                continue
            text = text.replace(needle, replacement)
        if text != original:
            if args.dry_run:
                print(f"[dry-run] 将改写 {path.relative_to(REPO)}")
            else:
                path.write_text(text, encoding="utf-8", newline="")
                print(f"[已改] {path.relative_to(REPO)}: {old} -> {new}")
        else:
            print(f"[无变化] {path.relative_to(REPO)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
