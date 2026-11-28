"""独立 Python 拉取的多源回退（装测 10061 实锤的修复面）。

单镜像被拒/毒化即全链死、死本地代理连镜像都毒死——阶梯 = 镜像逐个换 +
末轮剥代理。只测阶梯编排本身（_run_uv 打桩，桩打 uv_sources 模块全局——
_create_venv 裸名调用解析在定义侧），不做真网络。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.infra.model_manager import uv_sources


def test_without_proxy_strips_and_pins_noproxy() -> None:
    env = {
        "HTTP_PROXY": "http://127.0.0.1:7890",
        "https_proxy": "http://127.0.0.1:7890",
        "ALL_PROXY": "socks5://127.0.0.1:7890",
        "PATH": "kept",
        "UV_HTTP_TIMEOUT": "120",
    }
    clean = uv_sources._without_proxy(env)
    for key in uv_sources._PROXY_ENV_KEYS:
        assert key not in clean
    assert clean["NO_PROXY"] == "*" and clean["no_proxy"] == "*"
    assert clean["PATH"] == "kept", "非代理键原样保留"


def _fake_run_uv(monkeypatch: pytest.MonkeyPatch, fail_first: int) -> list[dict[str, Any]]:
    """记录每次调用的 (env_patch, strip_proxy)；前 fail_first 次抛 RuntimeError。"""
    calls: list[dict[str, Any]] = []

    def _fake(uv: Path, venv: Path, *args: str, **kwargs: Any) -> None:
        calls.append(
            {"env_patch": kwargs.get("env_patch"), "strip_proxy": kwargs.get("strip_proxy")}
        )
        if len(calls) <= fail_first:
            raise RuntimeError(f"uv venv 失败（exit 2）: 第 {len(calls)} 次失败")

    monkeypatch.setattr(uv_sources, "_run_uv", _fake)
    return calls


def test_create_venv_falls_back_to_next_mirror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_run_uv(monkeypatch, fail_first=1)
    uv_sources._create_venv(tmp_path / "uv.exe", tmp_path / "venv")
    assert len(calls) == 2, "首镜像失败应立即换下一来源"
    mirrors = [c["env_patch"]["UV_PYTHON_INSTALL_MIRROR"] for c in calls]
    assert mirrors[0] == uv_sources._PYTHON_MIRRORS[0]
    assert mirrors[1] == uv_sources._PYTHON_MIRRORS[1]
    assert all(c["strip_proxy"] is False for c in calls[:2]), "非末轮不动代理环境"


def test_create_venv_strips_proxy_on_final_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_run_uv(monkeypatch, fail_first=len(uv_sources._PYTHON_MIRRORS) - 1)
    uv_sources._create_venv(tmp_path / "uv.exe", tmp_path / "venv")
    assert len(calls) == len(uv_sources._PYTHON_MIRRORS)
    assert calls[-1]["strip_proxy"] is True, (
        "末轮（GitHub 直连）必须剥代理：镜像源国内可达，死本地代理只会毒死连接"
    )
    assert calls[-1]["env_patch"]["UV_PYTHON_INSTALL_MIRROR"] == uv_sources._PYTHON_MIRRORS[-1]


def test_create_venv_all_sources_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_run_uv(monkeypatch, fail_first=99)
    with pytest.raises(RuntimeError, match="全部来源失败"):
        uv_sources._create_venv(tmp_path / "uv.exe", tmp_path / "venv")
    assert len(calls) == len(uv_sources._PYTHON_MIRRORS), "阶梯必须走满"
