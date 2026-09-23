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
    一致性由本用例强制。
    """
    from dramaclip.api import jobs as jobs_api

    limit = _schema_method(repo_root / "protocol" / "schemas", "jobs.list")["params"]["properties"][
        "limit"
    ]
    assert limit["maximum"] == jobs_api._LIMIT_MAX
    assert limit["default"] == jobs_api._LIMIT_DEFAULT


def test_notifier_payloads_match_declared_notifications(repo_root: Path) -> None:
    """通知面无运行时校验，渲染层拿到什么全凭约定：实际发出的字段必须都在 protocol 声明里。

    字段悄悄多出来（如 log.append 的 job_id），protocol 追不上的话第三方案例里就是永久黑户。
    """
    from dramaclip.transport.notify import Notifier

    common = repo_root / "protocol" / "schemas" / "common.json"
    data = json.loads(common.read_text(encoding="utf-8"))
    declared = {
        str(item["name"]): {str(key).rstrip("?") for key in item["params"]}
        for item in data["x-notifications"]
    }
    sent: list[dict[str, Any]] = []
    notifier = Notifier(sent.append)
    notifier.progress("job-1", 10.0, "跑起来了", detail={"step": 1})
    notifier.log("info", "第一段解说已配音", job_id="job-1")
    notifier.model_download("model-1", 42.0, speed="3MB/s", eta="00:10")
    notifier.model_download("model-1", 0.0, status="failed", message="网络超时——稍后重试")

    assert {str(item["method"]) for item in sent} == set(declared), (
        "声明的通知与实际发出的不是一套"
    )
    for item in sent:
        name = str(item["method"])
        extra = set(item["params"]) - declared[name]
        assert extra == set(), f"{name} 发出了 protocol 未声明的字段：{extra}"
