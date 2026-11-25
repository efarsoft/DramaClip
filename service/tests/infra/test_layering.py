"""分层守卫：infra 是底座，不许反过来依赖 engines。

底座依赖上层，改上层就会牵动底座；依赖方向一旦倒过来就只增不减（2026-11-24
审查实锤：infra 里 4 个文件 11 条语句反向引用 engines，其中能力层自检整个模块
放错了层，已归位到 engines/）。剩下的几处是函数内的延迟导入（防环），记在
台账里只降不升——新加一处先红，而不是等下一轮审查才发现。
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "dramaclip"

#: 现存欠账：文件 → 允许的**函数内**延迟导入条数。清一笔就改一个数，不许往里加。
_LAZY_DEBT = {
    "infra/ffmpeg/cover.py": 1,
    "infra/model_manager/registry.py": 2,
    "infra/model_manager/tts_runtime.py": 2,
}


def _engine_imports(tree: ast.Module, module: str) -> list[tuple[int, str, bool]]:
    """扫出一棵语法树里所有指向 engines 的导入：(行号, 被导入模块, 是否在函数体内)。"""
    inside_function: set[int] = set()
    for func in ast.walk(tree):
        if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            inside_function.update(id(node) for node in ast.walk(func))
    parts = module.split(".")
    rows: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # 相对导入按当前包解析；绝对导入（level=0）没有前缀
            head = parts[: len(parts) - node.level] if node.level else []
            base = ".".join([*head, *([node.module] if node.module else [])])
            names = [base, *(f"{base}.{alias.name}" for alias in node.names)]
        else:
            continue
        target = next((name for name in names if name.startswith("dramaclip.engines.")), None)
        if target is not None:
            rows.append((node.lineno, target, id(node) in inside_function))
    return rows


def test_infra_imports_engines_only_lazily_and_only_where_listed() -> None:
    found: dict[str, int] = {}
    offenders: list[str] = []
    for path in sorted((PACKAGE / "infra").rglob("*.py")):
        module = ".".join(path.relative_to(PACKAGE.parent).with_suffix("").parts)
        rel = path.relative_to(PACKAGE).as_posix()
        for line, target, lazy in _engine_imports(ast.parse(path.read_text("utf-8")), module):
            if not lazy:
                offenders.append(f"{rel}:{line} 在模块顶层 import {target}")
            found[rel] = found.get(rel, 0) + 1

    assert not offenders, "infra 在模块顶层依赖 engines（会成环、底座被上层牵动）：" + "; ".join(
        offenders
    )
    assert found == _LAZY_DEBT, f"infra→engines 的反向引用变了：实测 {found}，台账 {_LAZY_DEBT}"
