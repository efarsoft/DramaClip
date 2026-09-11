"""契约同步：Router.method_names 必须与 protocol/schemas 的 x-methods 集合相等；
另外守住「运行时常量 == schema 声明值」这一类无法在运行时读 schema 的重复（docs/04 §5.2）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dramaclip.api import build_router


def _schema_methods(schema_dir: Path) -> set[str]:
    names: set[str] = set()
    for file in sorted(schema_dir.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        for method in data.get("x-methods", []):
            names.add(str(method["name"]))
    return names


def _schema_method(schema_dir: Path, name: str) -> dict[str, Any]:
    """取单个方法的 schema 条目（按 x-methods 的 name 匹配）。"""
    for file in sorted(schema_dir.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        for method in data.get("x-methods", []):
            if str(method.get("name")) == name:
                return dict(method)
    raise AssertionError(f"schema 里没有方法 {name}")


def test_router_matches_schemas(repo_root: Path) -> None:
    schema_dir = repo_root / "protocol" / "schemas"
    assert schema_dir.is_dir(), f"schema 目录不存在: {schema_dir}"
    from types import SimpleNamespace

    context = SimpleNamespace()  # 注册阶段不触碰上下文，空壳即可
    router = build_router(context, shutdown=lambda: None)  # type: ignore[arg-type]
    assert set(router.method_names) == _schema_methods(schema_dir)


def test_jobs_limit_constants_match_schema(repo_root: Path) -> None:
    """jobs.list 的 limit 钳制值/默认值：schema 是接口真相源，Python 侧只是运行时副本。

    Router 不做 schema 校验，服务端必须自己钳制；而 protocol/schemas/ 不随 sidecar
    打包（scripts/build-service.py 未收录），运行时读不到声明值——所以副本留着，
    一致性由本用例强制。改 schema 不改代码（或反之）都会在这里红。
    """
    from dramaclip.api import jobs as jobs_api

    limit = _schema_method(repo_root / "protocol" / "schemas", "jobs.list")["params"]["properties"][
        "limit"
    ]
    assert limit["maximum"] == jobs_api._LIMIT_MAX
    assert limit["default"] == jobs_api._LIMIT_DEFAULT
