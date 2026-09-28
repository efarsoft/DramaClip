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

# ---- worker 纯函数：干声挑选 ----


def test_vocals_of_picks_vocals_stem() -> None:
    stems = ["a_(Vocals)_UVR_MDXNET_KARA_2.wav", "a_(Instrumental)_UVR_MDXNET_KARA_2.wav"]
    assert separation_worker._vocals_of(stems) == stems[0]


def test_vocals_of_returns_none_without_vocals() -> None:
    assert separation_worker._vocals_of(["a_(Instrumental)_x.wav"]) is None


# ---- 协议解析：worker 的 stdout 只认最后一行 JSON ----


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr="")


def test_collect_accepts_ok_answer(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"
    out.write_bytes(b"x")
    result = _completed(json.dumps({"ok": True, "out": str(out)}, ensure_ascii=False))
    assert vs._collect(result, out) == out


def test_collect_rejects_error_answer(tmp_path: Path) -> None:
    result = _completed(json.dumps({"ok": False, "error": "模型读不出来"}))
    with pytest.raises(RuntimeError, match="模型读不出来"):
        vs._collect(result, tmp_path / "a.cleaned.wav")


def test_collect_rejects_non_protocol_stdout(tmp_path: Path) -> None:
    result = _completed("Traceback ... 环境没装")
    with pytest.raises(RuntimeError, match="没有返回协议应答"):
        vs._collect(result, tmp_path / "a.cleaned.wav")


def test_collect_rejects_missing_artifact(tmp_path: Path) -> None:
    out = tmp_path / "a.cleaned.wav"  # 故意不落盘
    result = _completed(json.dumps({"ok": True, "out": str(out)}))
    with pytest.raises(RuntimeError, match="产物不存在"):
        vs._collect(result, out)


# ---- clean_reference 编排：venv 前提 + worker 拉起 ----


def test_clean_reference_reports_missing_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vs, "_venv_python", lambda: tmp_path / "nope" / "python.exe")
    with pytest.raises(RuntimeError, match="运行环境"):
        vs.clean_reference(tmp_path / "models", tmp_path / "src.wav")


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

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        return _completed(json.dumps({"ok": True, "out": str(out)}, ensure_ascii=False))

    monkeypatch.setattr(vs.subprocess, "run", fake_run)
    assert vs.clean_reference(tmp_path / "models", src) == out
    cmd: list[str] = seen["cmd"]  # type: ignore[assignment]
    assert cmd[0] == str(fake_py)
    assert cmd[-6:] == [
        "--in", str(src), "--out", str(out),
        "--models", str(tmp_path / "models" / "tts" / "separation"),
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
