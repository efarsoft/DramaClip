"""vocal_separation + separation_worker：清洗「彻底档」的编排协议与模型就位。

worker 本体要在 tts-venv 里才能跑（audio_separator 函数内懒 import），这里的
单测钉的是主进程侧的编排契约：venv 缺失给人话报错、模型多源下载容错、worker
协议一行 JSON 的解析与防伪（报成功但没产物/产物路径不符都算失败）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dramaclip.engines.tts import vocal_separation as vs
from dramaclip.engines.tts.workers import separation_worker
from dramaclip.infra.compute import ComputeUnavailableError

# ---- worker 纯函数：干声挑选 ----


def test_vocals_of_picks_vocals_stem() -> None:
    stems = ["a_(Vocals)_UVR_MDXNET_KARA_2.wav", "a_(Instrumental)_UVR_MDXNET_KARA_2.wav"]
    assert separation_worker._vocals_of(stems) == stems[0]


def test_vocals_of_returns_none_without_vocals() -> None:
    assert separation_worker._vocals_of(["a_(Instrumental)_x.wav"]) is None


# ---- worker 设备决策：cpu 不碰 CUDA，显式 cuda 无 provider 即失败 ----
def test_provider_plan_cpu_never_uses_cuda() -> None:
    providers, resolved = separation_worker._provider_plan(
        "cpu", ["CUDAExecutionProvider", "CPUExecutionProvider"]
    )
    assert providers == ["CPUExecutionProvider"]
    assert resolved == "cpu"


def test_provider_plan_auto_uses_cuda_when_available() -> None:
    providers, resolved = separation_worker._provider_plan(
        "auto", ["CUDAExecutionProvider", "CPUExecutionProvider"]
    )
    assert providers == ["CUDAExecutionProvider"]
    assert resolved == "cuda"


def test_provider_plan_auto_without_cuda_stays_cpu() -> None:
    providers, resolved = separation_worker._provider_plan("auto", ["CPUExecutionProvider"])
    assert providers == ["CPUExecutionProvider"]
    assert resolved == "cpu"


def test_provider_plan_explicit_cuda_without_provider_fails() -> None:
    with pytest.raises(RuntimeError, match="CUDAExecutionProvider"):
        separation_worker._provider_plan("cuda", ["CPUExecutionProvider"])


# ---- DirectML 通道：auto 的次选、显式 dml 的承诺、cuda 不被 dml 冒充 ----
def test_provider_plan_auto_picks_dml_when_no_cuda() -> None:
    providers, resolved = separation_worker._provider_plan(
        "auto", ["DmlExecutionProvider", "CPUExecutionProvider"]
    )
    assert providers == ["DmlExecutionProvider"]
    assert resolved == "dml"


def test_provider_plan_auto_prefers_cuda_over_dml() -> None:
    _providers, resolved = separation_worker._provider_plan(
        "auto", ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    )
    assert resolved == "cuda"


def test_provider_plan_explicit_dml_without_provider_fails() -> None:
    with pytest.raises(RuntimeError, match="DmlExecutionProvider"):
        separation_worker._provider_plan("dml", ["CPUExecutionProvider"])


def test_provider_plan_explicit_cuda_not_satisfied_by_dml() -> None:
    with pytest.raises(RuntimeError, match="CUDAExecutionProvider"):
        separation_worker._provider_plan("cuda", ["DmlExecutionProvider", "CPUExecutionProvider"])


def test_provider_plan_explicit_dml_resolves() -> None:
    providers, resolved = separation_worker._provider_plan(
        "dml", ["DmlExecutionProvider", "CPUExecutionProvider"]
    )
    assert providers == ["DmlExecutionProvider"]
    assert resolved == "dml"


def test_inject_cuda_dll_dirs_only_existing_known_subdirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cuda"
    for name in ("cublas", "cudnn", "cudart"):
        (root / name).mkdir(parents=True)
    seen: list[str] = []
    monkeypatch.setattr(separation_worker, "_add_dll_dir", lambda path: seen.append(str(path)))
    monkeypatch.setattr(separation_worker.os, "add_dll_directory", None, raising=False)
    monkeypatch.setattr(separation_worker.os, "environ", {"PATH": "C:/Windows"})
    separation_worker._inject_cuda_dlls(root, torch_lib=None)
    assert seen == [str(root / "cublas"), str(root / "cudnn"), str(root / "cudart")]
    assert str(root / "cufft") not in seen


# ---- 协议解析：worker 的 stdout 只认最后一行 JSON ----


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr="")


def _ok_payload(out: Path, **overrides: object) -> str:
    payload: dict[str, object] = {
        "ok": True,
        "out": str(out),
        "requested": "auto",
        "resolved": "cuda",
        "actual": "cuda",
        "fallback": False,
        "reason": "",
        "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_collect_accepts_ok_answer(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"
    out.write_bytes(b"x")
    parsed = vs._collect(_completed(_ok_payload(out)), out, "auto")
    assert parsed.path == out
    assert parsed.compute.component == "tts.separation"
    assert (parsed.compute.actual, parsed.compute.fallback) == ("cuda", False)
    assert parsed.compute.device == "cuda"


def test_collect_accepts_auto_fallback_with_reason(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"
    out.write_bytes(b"x")
    parsed = vs._collect(
        _completed(_ok_payload(
            out, resolved="cuda", actual="cpu", fallback=True,
            reason="CUDA 初始化失败", providers=["CPUExecutionProvider"],
        )),
        out, "auto",
    )
    assert parsed.compute.fallback is True
    assert parsed.compute.reason == "CUDA 初始化失败"
    assert parsed.compute.actual == "cpu"


def test_collect_rejects_explicit_cuda_landing_cpu(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"
    out.write_bytes(b"x")
    payload = _ok_payload(
        out, requested="cuda", resolved="cuda", actual="cpu",
        providers=["CPUExecutionProvider"],
    )
    with pytest.raises(ComputeUnavailableError, match="实际 cpu"):
        vs._collect(_completed(payload), out, "cuda")


def test_collect_rejects_unknown_actual(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"
    out.write_bytes(b"x")
    payload = _ok_payload(out, actual="unknown", resolved="unknown")
    with pytest.raises(ComputeUnavailableError, match="actual=unknown"):
        vs._collect(_completed(payload), out, "auto")


def test_collect_rejects_requested_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"
    out.write_bytes(b"x")
    payload = _ok_payload(out, requested="cuda")
    with pytest.raises(RuntimeError, match="请求不一致"):
        vs._collect(_completed(payload), out, "auto")


def test_collect_rejects_error_answer(tmp_path: Path) -> None:
    result = _completed(json.dumps({"ok": False, "error": "模型读不出来"}))
    with pytest.raises(RuntimeError, match="模型读不出来"):
        vs._collect(result, tmp_path / "a.cleaned.wav", "auto")


def test_collect_rejects_non_protocol_stdout(tmp_path: Path) -> None:
    result = _completed("Traceback ... 环境没装")
    with pytest.raises(RuntimeError, match="没有返回协议应答"):
        vs._collect(result, tmp_path / "a.cleaned.wav", "auto")


def test_collect_rejects_missing_artifact(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"  # 故意不落盘
    with pytest.raises(RuntimeError, match="产物不存在"):
        vs._collect(_completed(_ok_payload(out)), out, "auto")


# ---- clean_reference 编排：venv 前提 + worker 拉起 ----


def test_clean_reference_reports_missing_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vs, "_venv_python", lambda: tmp_path / "nope" / "python.exe")
    with pytest.raises(RuntimeError, match="运行环境"):
        vs.clean_reference(tmp_path / "models", tmp_path / "src.wav")


def test_clean_reference_rejects_unknown_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vs, "_venv_python", lambda: tmp_path / "python.exe")
    with pytest.raises(ValueError, match="未知算力请求"):
        vs.clean_reference(tmp_path / "models", tmp_path / "src.wav", device="gpu")


def test_clean_reference_launches_worker_with_agreed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "src.wav"
    src.write_bytes(b"x")
    out = tmp_path / "src.cleaned.wav"
    out.write_bytes(b"vocals")
    fake_py = tmp_path / "python.exe"
    fake_py.write_bytes(b"")
    monkeypatch.setattr(vs, "_venv_python", lambda: fake_py)
    monkeypatch.setattr(vs, "ensure_model", lambda _models: None)
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _completed(_ok_payload(out))

    monkeypatch.setattr(vs.subprocess, "run", fake_run)
    parsed = vs.clean_reference(tmp_path / "models", src)
    assert parsed.path == out
    cmd: list[str] = seen["cmd"]  # type: ignore[assignment]
    kwargs: dict[str, object] = seen["kwargs"]  # type: ignore[assignment]
    assert cmd[0] == str(fake_py)
    assert cmd[-6:] == [
        "--models", str(tmp_path / "models" / "tts" / "separation"),
        "--device", "auto",
        "--cuda-dll-dir", str(tmp_path / "models" / "cuda"),
    ]
    # 中文参考路径曾因 GBK 解码把成功应答读成「没有返回协议应答」。
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    env: dict[str, str] = kwargs["env"]  # type: ignore[assignment]
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_clean_reference_passes_explicit_cuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "src.wav"
    src.write_bytes(b"x")
    out = tmp_path / "src.cleaned.wav"
    out.write_bytes(b"vocals")
    fake_py = tmp_path / "python.exe"
    fake_py.write_bytes(b"")
    monkeypatch.setattr(vs, "_venv_python", lambda: fake_py)
    monkeypatch.setattr(vs, "ensure_model", lambda _models: None)
    seen: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        return _completed(_ok_payload(out, requested="cuda"))

    monkeypatch.setattr(vs.subprocess, "run", fake_run)
    vs.clean_reference(tmp_path / "models", src, device="cuda")
    assert seen["cmd"][-4:] == [
        "--device", "cuda", "--cuda-dll-dir", str(tmp_path / "models" / "cuda"),
    ]


def test_model_path_lives_under_tts_separation(tmp_path: Path) -> None:
    assert vs.model_path(tmp_path).name == "UVR_MDXNET_KARA_2.onnx"
    assert vs.model_path(tmp_path).parent == tmp_path / "tts" / "separation"


# ---- 模型就位：在即免下载，缺则多源容错 ----


def test_ensure_model_skips_download_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = vs.model_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"model")
    calls: list[str] = []
    monkeypatch.setattr(vs, "download_file", lambda url, *_a, **_k: calls.append(url))
    assert vs.ensure_model(tmp_path) == target
    assert calls == []


def test_ensure_model_falls_over_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[str] = []

    def fake_download(
        url: str, dest: Path, size: int, *, cancel: object = None, on_progress: object = None
    ) -> None:
        used.append(url)
        if len(used) == 1:
            raise RuntimeError("代理超时")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"model")
        assert size == vs._MODEL_SIZE

    monkeypatch.setattr(vs, "download_file", fake_download)
    vs.ensure_model(tmp_path)
    assert len(used) == 2
    assert vs.model_path(tmp_path).is_file()


def test_ensure_model_raises_after_all_sources_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        vs, "download_file",
        lambda url, *_a, **_k: (_ for _ in ()).throw(RuntimeError("全挂")),
    )
    with pytest.raises(RuntimeError, match="下载失败"):
        vs.ensure_model(tmp_path)
