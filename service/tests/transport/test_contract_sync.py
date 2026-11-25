"""契约同步：Router.method_names 必须与 protocol/schemas 的 x-methods 集合相等；
另外守住「运行时常量 == schema 声明值」这一类无法在运行时读 schema 的重复（docs/04 §5.2）。"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

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

    # 注册阶段不触碰上下文：data_dir 仅被 system.health 惰性读取，空壳给个占位
    context = SimpleNamespace(data_dir=None)
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


def _ts_interface_keys(ts_source: str, name: str) -> set[str]:
    """TS 接口的全部键（含 extends 继承来的）——与 schema 的 allOf 并集同口径。"""
    match = re.search(rf"export interface {name}\b([^{{]*)\{{(.*?)\n\}}", ts_source, re.S)
    assert match is not None, f"protocol/ts/index.ts 里找不到 interface {name}"
    keys = set(re.findall(r"readonly (\w+)\??:", match.group(2)))
    parent = re.search(r"extends (\w+)", match.group(1))
    if parent is not None:
        keys |= _ts_interface_keys(ts_source, parent.group(1))
    return keys


def _model_name(declaration: dict[str, Any]) -> str | None:
    """属性声明 → 模型名：``$ref`` 直取；可空（anyOf）取其中带 ``$ref`` 的那一支；基本类型 None。"""
    if "$ref" in declaration:
        return str(declaration["$ref"]).rsplit("/", 1)[-1]
    for branch in declaration.get("anyOf", []):
        if "$ref" in branch:
            return _model_name(branch)
    return None


def _declared_keys(models: dict[str, Any], name: str) -> set[str]:
    """模型声明的全部键；allOf 组合的取并集（基类 + 自带属性）。"""
    model = models[name]
    keys = set(model.get("properties", {}))
    for part in model.get("allOf", []):
        if "$ref" in part:
            keys |= _declared_keys(models, str(part["$ref"]).rsplit("/", 1)[-1])
        keys |= set(part.get("properties", {}))
    return keys


def test_selfcheck_report_matches_schema_and_ts(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成绩单契约三方对齐：服务端实际写出的键 = schema 声明 = TS 声明。

    x-models 没有运行时校验，也没有测试看守，三处于是各写各的（2026-11-24
    审查实锤：服务端 14 个顶层键、schema 7 个、TS 9 个）。TS 类型里没有的键
    渲染层就用不了——响度读数、开场质检早已写进库，却从来没上过屏。
    """
    from dramaclip.engines.exporter import loudness, selfcheck

    models = json.loads(
        (repo_root / "protocol" / "schemas" / "export.json").read_text(encoding="utf-8")
    )["x-models"]
    ts_source = (repo_root / "protocol" / "ts" / "index.ts").read_text(encoding="utf-8")

    # 跑一遍真实的 run（三处解码测量打桩），拿到服务端实际写出的成绩单
    measurement = loudness.LoudnessMeasurement(
        integrated_lufs=-14.6, true_peak_dbtp=-1.2, lra=8.4, threshold=-24.3, offset_lu=0.0
    )
    monkeypatch.setattr(loudness, "measure_integrated_lufs", lambda _p: measurement)
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.5))
    monkeypatch.setattr(selfcheck, "measure_opening_audio", lambda _v: -18.0)
    payload = selfcheck.run(
        tmp_path / "film.mp4", measured_s=60.0, has_audio=True, mode="raw_clip",
        budget_s=60.0, planned_segments=3, loudness_target=(-14.0, -1.5),
    )

    written = set(payload)
    declared = models["SelfCheck"]["properties"]
    assert written == set(declared), "schema 与写出的顶层键不一致"
    assert written == _ts_interface_keys(ts_source, "SelfCheck"), "TS 与写出的顶层键不一致"

    # 每个带模型的键：schema 模型名 == TS 接口名且键集合相等；实际写出的检查项键都在声明里
    for key, declaration in declared.items():
        name = _model_name(declaration)
        if name is None:  # version / checked_at / dedup_jitter：基本类型，没有模型
            continue
        schema_keys = _declared_keys(models, name)
        assert schema_keys == _ts_interface_keys(ts_source, name), f"{name}: schema 与 TS 不一致"
        item = payload[key]
        if isinstance(item, dict):
            extra = set(item) - schema_keys
            assert not extra, f"{key} 写出的键 {name} 没声明：{sorted(extra)}"

    # 只在部分分支才出现的度量键（收尾被拦腰、音画同步有样本）静态兜住：
    # 每个 check_* 直接返回的字典键都得在它那一项的模型里
    source = Path(selfcheck.__file__).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("check_")):
            continue
        returned = {
            key.value
            for ret in ast.walk(node)
            if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Dict)
            for key in ret.value.keys
            if isinstance(key, ast.Constant)
        }
        name = _model_name(declared[node.name.removeprefix("check_")])
        assert name is not None
        missing = returned - _declared_keys(models, name)
        assert not missing, f"{node.name} 写出的键 {name} 没声明：{sorted(missing)}"
