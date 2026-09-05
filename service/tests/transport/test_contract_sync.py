"""契约同步：Router.method_names 必须与 protocol/schemas 的 x-methods 集合相等。"""

from __future__ import annotations

import json
from pathlib import Path

from dramaclip.api import build_router


def _schema_methods(schema_dir: Path) -> set[str]:
    names: set[str] = set()
    for file in sorted(schema_dir.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        for method in data.get("x-methods", []):
            names.add(str(method["name"]))
    return names


def test_router_matches_schemas(repo_root: Path) -> None:
    schema_dir = repo_root / "protocol" / "schemas"
    assert schema_dir.is_dir(), f"schema 目录不存在: {schema_dir}"
    from types import SimpleNamespace

    context = SimpleNamespace()  # 注册阶段不触碰上下文，空壳即可
    router = build_router(context, shutdown=lambda: None)  # type: ignore[arg-type]
    assert set(router.method_names) == _schema_methods(schema_dir)
