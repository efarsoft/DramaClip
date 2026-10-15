"""CUDA 运行库的下载对账：wheel 的 SHA256 从两条源都要拿到，装进校验。

这里落盘的是会被进程直接加载的 DLL。只比字节数等于「长度对、内容被换过」也照装——
清华索引的 href 锚点和 pypi.org 的 ``digests.sha256`` 本来就给了凭据，不校验等于没拿来。
"""

from __future__ import annotations

import urllib.error

import pytest

from dramaclip.infra.model_manager import cuda_runtime


def test_href_anchor_parsed_only_when_shaped_right() -> None:
    digest = "a" * 64
    assert cuda_runtime._href_sha256(f"pkg-1.0.whl#sha256={digest}") == digest  # noqa: SLF001
    assert cuda_runtime._href_sha256("pkg-1.0.whl") == ""  # noqa: SLF001
    assert cuda_runtime._href_sha256(f"pkg-1.0.whl#sha256={'b' * 40}") == ""  # noqa: SLF001


def test_wheel_meta_surfaces_the_pypi_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """镜像索引读不通时，兜底源的 digests.sha256 同样是校验凭据。"""

    def _boom(*_args, **_kwargs):
        raise urllib.error.URLError("镜像 DNS 挂了")

    def _json(_url: str) -> dict:
        return {
            "urls": [
                {
                    "filename": "nvidia_cublas-12.4.5.8-py3-none-win_amd64.whl",
                    "url": "https://files.pythonhosted.org/x.whl",
                    "size": 4096,
                    "digests": {"sha256": "B" * 64},
                }
            ]
        }

    monkeypatch.setattr(cuda_runtime.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(cuda_runtime, "fetch_json", _json)

    meta = cuda_runtime._wheel_meta("nvidia-cublas-cu12", "12.4.5.8")  # noqa: SLF001

    assert meta["sha256"] == "b" * 64, "大小写归一，且必须带上"
    assert meta["size"] == 4096


def test_wheel_meta_without_digest_degrades_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上游没给哈希就留空串（退字节数校验），不许造一个假的出来。"""

    def _boom(*_args, **_kwargs):
        raise urllib.error.URLError("镜像 DNS 挂了")

    def _json(_url: str) -> dict:
        return {
            "urls": [
                {
                    "filename": "nvidia_cublas-12.4.5.8-py3-none-win_amd64.whl",
                    "url": "https://files.pythonhosted.org/x.whl",
                    "size": 4096,
                }
            ]
        }

    monkeypatch.setattr(cuda_runtime.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(cuda_runtime, "fetch_json", _json)

    meta = cuda_runtime._wheel_meta("nvidia-cublas-cu12", "12.4.5.8")  # noqa: SLF001

    assert meta["sha256"] == ""
