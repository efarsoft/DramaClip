"""版本号单一源 bump 脚本：八处声明一次改齐，杜绝徽章/清单/锁文件漂移。

背景（2026-11-18 外部审查实锤）：v0.2.5 发版齐平了五处，README 徽章仍停在
0.2.4——版本声明散落多处时，手工齐平必有遗漏。本脚本把「改版本」收敛为
一条命令：`python scripts/bump_version.py 0.2.6 [--dry-run]`。

覆盖八处（各自格式不同，逐一定位）：
  1. service/pyproject.toml            `version = "x.y.z"`
  2. desktop/package.json + 根 package.json + protocol/package.json  `"version": "x.y.z"`
  3. service/dramaclip/__init__.py     `__version__ = "x.y.z"`
  4. README.md 徽章                    `badge/version-x.y.z-`
  5. package-lock.json                 根 + packages 的 ""/desktop/protocol 四个版本字段
  6. service/uv.lock                   dramaclip 包条目的 `version = "x.y.z"`

第 5、6 处是两个锁文件（2026-11-24 审查补入：0.2.6 期间它们各自漏带过一次，
都是事后手工追平的）。锁文件只能用带包名的多行锚——单行 `"version": "x.y.z"`
全文件替换，会连带改掉恰好同版本号的第三方包。

只动**版本声明行**（精确锚），不碰注释/提交信息里的历史版本号。
任一锚失配即整体放弃、一个字节都不写（改了一半比没改更难查）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (文件, 旧串→新串的替换对列表)；旧串按精确锚匹配。
def _targets(repo: Path) -> tuple[tuple[Path, tuple[tuple[str, str], ...]], ...]:
    json_pair = ('"version": "{old}"', '"version": "{new}"')
    return (
        (repo / "service" / "pyproject.toml", (('version = "{old}"', 'version = "{new}"'),)),
        (repo / "desktop" / "package.json", (json_pair,)),
        (repo / "package.json", (json_pair,)),
        (repo / "protocol" / "package.json", (json_pair,)),
        (
            repo / "service" / "dramaclip" / "__init__.py",
            (('__version__ = "{old}"', '__version__ = "{new}"'),),
        ),
        (repo / "README.md", (("badge/version-{old}-", "badge/version-{new}-"),)),
        (
            repo / "package-lock.json",
            tuple(
                (head + '"version": "{old}"', head + '"version": "{new}"')
                for head in (
                    '  "name": "dramaclip",\n  ',  # 根
                    '    "": {\n      "name": "dramaclip",\n      ',
                    '    "desktop": {\n      "name": "@dramaclip/desktop",\n      ',
                    '    "protocol": {\n      "name": "@dramaclip/protocol",\n      ',
                )
            ),
        ),
        (
            repo / "service" / "uv.lock",
            (('name = "dramaclip"\nversion = "{old}"', 'name = "dramaclip"\nversion = "{new}"'),),
        ),
    )


def _current_version(init_file: Path) -> str | None:
    match = re.search(r'__version__ = "(\d+\.\d+\.\d+)"', init_file.read_text(encoding="utf-8"))
    return match.group(1) if match else None


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

    old = args.old_version or _current_version(REPO / "service" / "dramaclip" / "__init__.py")
    if old is None:
        print("__init__.py 读不到当前版本", file=sys.stderr)
        return 1
    new = args.new_version
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        print(f"版本号格式不对：{new}", file=sys.stderr)
        return 1

    # 先全量核对再落盘：任何一个锚失配就整体放弃，不许改了一半。
    planned: list[tuple[Path, str, str]] = []
    for path, pairs in _targets(REPO):
        # 读盘走通用换行（工作树是 CRLF 也能命中 \n 锚）；写盘 newline="" 保持 LF。
        original = path.read_text(encoding="utf-8")
        text = original
        for template_old, template_new in pairs:
            needle = template_old.replace("{old}", old)
            if needle not in text:
                print(f"[缺锚] {path.relative_to(REPO)}: {needle!r}", file=sys.stderr)
                return 1
            text = text.replace(needle, template_new.replace("{new}", new))
        planned.append((path, original, text))

    for path, original, text in planned:
        if text == original:
            print(f"[无变化] {path.relative_to(REPO)}")
        elif args.dry_run:
            print(f"[dry-run] 将改写 {path.relative_to(REPO)}")
        else:
            path.write_text(text, encoding="utf-8", newline="")
            print(f"[已改] {path.relative_to(REPO)}: {old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
