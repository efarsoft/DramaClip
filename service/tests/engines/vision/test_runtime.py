"""vision.runtime：采样参数纯函数 + 解析容差 + 会话开闭的分档判据 + 本地会话拉进程。"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from dramaclip.engines.vision import runtime
from dramaclip.infra import llama_device
from dramaclip.infra.compute import ComputeUnavailableError


def test_sample_frames_args_deterministic() -> None:
    args = runtime.sample_frames_args("v.mp4", "out/frame-%02d.png", duration_s=68.0)
    assert args == [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        "v.mp4",
        "-vf",
        f"fps={16 / 68.0:.6f},scale=640:-2",
        "-frames:v",
        "16",
        "out/frame-%02d.png",
    ]


def test_sample_frames_args_rejects_bad_duration() -> None:
    with pytest.raises(ValueError, match="集时长非法"):
        runtime.sample_frames_args("v.mp4", "o.png", duration_s=0.0)


def test_parse_descriptions_maps_index_to_time() -> None:
    import json

    rows = [
        {"index": 1, "shot": "特写", "scene": "室内", "people": "甲", "action": "看", "mood": "静"},
        {"index": 3, "shot": "全景", "scene": "大殿", "people": "乙", "action": "跪", "mood": "肃"},
    ]
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    frames = runtime.parse_descriptions(text, count=4, episode_s=68.0)
    assert [f["t"] for f in frames] == [8.5, 42.5]
    assert frames[0]["people"] == "甲" and frames[1]["mood"] == "肃"


def test_parse_descriptions_tolerates_noise() -> None:
    """围栏/空行/坏行跳过；缺字段补空串——坏行不炸整集（分档语义）。

    `watch_score` 是后加的封面冲击力字段（vision 引擎）：模型没给就补中性分 5，
    所以缺字段的帧也会带上它——断言按实际契约写全字段，别只挑关心的几个比。
    """
    text = (
        "```json\n"
        "\n"
        '{"index": 1, "shot": "特写", "scene": "室内",'
        ' "people": "甲", "action": "看", "mood": "静"}\n'
        "这不是 JSON 的行\n"
        '{"index": 2, "scene": "大殿"}\n'
        "```"
    )
    frames = runtime.parse_descriptions(text, count=2, episode_s=60.0)
    assert len(frames) == 2
    assert frames[0]["mood"] == "静"
    assert frames[0]["watch_score"] == 5
    assert frames[1] == {
        "t": 45.0, "shot": "", "scene": "大殿", "people": "", "action": "", "mood": "",
        "watch_score": 5,
    }


def test_open_session_gates(tmp_path) -> None:
    """档位空/模型没装/llama-server 缺失 → None（分档：不报错、不拉进程）。"""
    models = tmp_path / "models"
    exe = tmp_path / "tools" / "llama.cpp" / "llama-server.exe"
    assert runtime.open_session(tmp_path, models, {}) is None
    assert runtime.open_session(tmp_path, models, {"vision.model": "qwen3-vl-4b"}) is None

    model_dir = models / "vl" / "qwen3-vl-4b"
    model_dir.mkdir(parents=True)
    (model_dir / "Qwen3VL-4B-Instruct-Q4_K_M.gguf").write_bytes(b"x")
    (model_dir / "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf").write_bytes(b"x")
    assert runtime.open_session(tmp_path, models, {"vision.model": "qwen3-vl-4b"}) is None, (
        "llama-server 二进制缺失 → None"
    )

    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    session = runtime.open_session(tmp_path, models, {"vision.model": "qwen3-vl-4b"})
    assert session is not None and session.model_id == "qwen3-vl-4b"


class _FakeResp:
    """urlopen 返回体：/health 只看 status，chat 走 json.load(→read)。"""

    def __init__(self, body: str = "{}") -> None:
        self.status = 200
        self._body = body

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> str:
        return self._body


def _fake_chat_body(total: int) -> str:
    row = {
        "shot": "特写", "scene": "室内", "people": "甲", "action": "看", "mood": "静",
    }
    lines = [json.dumps({"index": i, **row}, ensure_ascii=False) for i in range(1, total + 1)]
    return json.dumps({"choices": [{"message": {"content": "\n".join(lines)}}]}, ensure_ascii=False)


@pytest.fixture()
def local_session(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """一只"能跑起来"的本地会话：Popen/端口/urlopen/ffmpeg 采样全部替身，只留流程本身。"""
    spawned: list[list[str]] = []
    asked: list[str] = []

    class _FakeProc:
        returncode = None

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

    def fake_popen(cmd: list[str], **_kwargs: object) -> _FakeProc:
        spawned.append(list(cmd))
        return _FakeProc()

    def fake_urlopen(request: object, *_args: object, **_kwargs: object) -> _FakeResp:
        url = str(request.full_url) if hasattr(request, "full_url") else str(request)
        asked.append(url)
        return _FakeResp() if url.endswith("/health") else _FakeResp(_fake_chat_body(2))

    def fake_run(args: list[str], **_kwargs: object) -> None:
        pattern = str(args[-1])  # 已是 work_dir 下的绝对 frame-%02d.png
        for index in (1, 2):
            Path(pattern % index).write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)  # type: ignore[attr-defined]
    monkeypatch.setattr(runtime, "_free_port", lambda: 45123)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runtime.runner, "run", fake_run)
    # 设备探测默认「没有 CUDA 设备」：Popen 已是替身，真去跑 --list-devices 只会炸在替身上
    monkeypatch.setattr(runtime.llama_device, "list_cuda_devices", lambda *_a, **_k: [])
    session = _session(tmp_path)
    return session, spawned, asked


def _session(tmp_path: Path, requested: str = "auto") -> runtime.VisionSession:
    return runtime.VisionSession(
        model_id="qwen3-vl-4b",
        exe=tmp_path / "llama-server.exe",
        model=tmp_path / "model.gguf",
        mmproj=tmp_path / "mmproj.gguf",
        requested=requested,
    )


def test_describe_episode_boots_llama_server_before_asking(
    local_session: tuple[runtime.VisionSession, list[list[str]], list[str]], tmp_path
) -> None:
    """回归钉（4fcfde8）：抽公共 _describe_with 时丢了 self._ensure()——_port 只在
    _ensure 里赋值，漏掉就是 AttributeError，本地视觉轨整条哑掉（云端仍正常，
    所以当时没有任何测试报警）。"""
    session, spawned, asked = local_session
    frames = session.describe_episode(tmp_path / "ep01.mp4", 68.0, tmp_path / "work", count=2)

    assert spawned[0][0].endswith("llama-server.exe")
    assert spawned[0][spawned[0].index("--port") + 1] == "45123"
    assert "http://127.0.0.1:45123/v1/chat/completions" in asked
    assert [f["shot"] for f in frames] == ["特写", "特写"]


def test_describe_episode_reuses_the_live_server(
    local_session: tuple[runtime.VisionSession, list[list[str]], list[str]], tmp_path
) -> None:
    """跨集复用是同一只进程：第二次描述不该再拉一次 llama-server。"""
    session, spawned, _asked = local_session
    for _ in range(2):
        session.describe_episode(tmp_path / "ep.mp4", 60.0, tmp_path / "work", count=2)
    assert len(spawned) == 1


# ── 算力解析：vision.device × llama-server 设备清单 → 启动参数与回执 ──

_M4000 = llama_device.CudaDevice("CUDA0", "Quadro M4000", 8191, 7305)
_Local = tuple[runtime.VisionSession, list[list[str]], list[str]]


class _DeadProc:
    """拉起即退出的 llama-server（GPU 初始化失败的形态）。"""

    returncode = 1

    def poll(self) -> int:
        return 1

    def terminate(self) -> None:
        return None


def _offer_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.llama_device, "list_cuda_devices", lambda *_a, **_k: [_M4000])
    monkeypatch.setattr(runtime.llama_device, "has_cuda_build", lambda _exe: True)


def _device_arg(cmd: list[str]) -> str:
    return cmd[cmd.index("--device") + 1]


def _gpu_dies(monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]) -> None:
    """卸载到真设备的启动立刻退出；禁用卸载（--device none）的照常活着（沿用夹具替身）。"""
    alive = runtime.subprocess.Popen

    def popen(cmd: list[str], **kwargs: object) -> object:
        if _device_arg(cmd) != "none":
            spawned.append(list(cmd))
            return _DeadProc()
        return alive(cmd, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(runtime.subprocess, "Popen", popen)  # type: ignore[attr-defined]


def test_auto_offloads_to_the_cuda_device(
    local_session: _Local, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """auto + 清单里有 CUDA 设备：整模型卸载，回执写实际设备名。"""
    session, spawned, _asked = local_session
    _offer_gpu(monkeypatch)
    assert session.compute() is None, "没拉起过就没有证据，不许先发回执"
    session.describe_episode(tmp_path / "ep.mp4", 60.0, tmp_path / "work", count=2)

    cmd = spawned[0]
    assert cmd[cmd.index("--device") + 1] == "CUDA0"
    assert cmd[cmd.index("-ngl") + 1] == "99"
    report = session.compute()
    assert report is not None
    assert (report.component, report.requested, report.resolved, report.actual) == (
        "vision.llama", "auto", "cuda", "cuda",
    )
    assert report.fallback is False and report.device == "Quadro M4000"


def test_auto_without_cuda_device_stays_on_cpu_and_says_why(
    local_session: _Local, tmp_path: Path
) -> None:
    """清单为空（CPU 构建）：回执是 CPU 且带原因，但不算回退。"""
    session, spawned, _asked = local_session
    session.describe_episode(tmp_path / "ep.mp4", 60.0, tmp_path / "work", count=2)

    assert _device_arg(spawned[0]) == "none"
    assert spawned[0][spawned[0].index("-ngl") + 1] == "0"
    report = session.compute()
    assert report is not None
    assert (report.resolved, report.actual, report.fallback) == ("cpu", "cpu", False)
    assert "CPU 构建" in report.reason


def test_auto_falls_back_to_cpu_when_gpu_launch_dies(
    local_session: _Local, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GPU 起不来（显存不够/驱动不认）：回退 CPU 重启一次，描述照出，回执标 fallback。"""
    session, spawned, _asked = local_session
    _offer_gpu(monkeypatch)
    _gpu_dies(monkeypatch, spawned)
    frames = session.describe_episode(tmp_path / "ep.mp4", 60.0, tmp_path / "work", count=2)

    assert len(spawned) == 2
    assert _device_arg(spawned[0]) == "CUDA0" and _device_arg(spawned[1]) == "none"
    assert [f["shot"] for f in frames] == ["特写", "特写"]
    report = session.compute()
    assert report is not None
    assert (report.resolved, report.actual, report.fallback) == ("cuda", "cpu", True)
    assert "提前退出" in report.reason


def test_explicit_cuda_without_device_fails_before_launch(
    local_session: _Local, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式 cuda 是承诺：没有 CUDA 设备就报错，不拉 CPU 进程慢慢跑。"""
    _auto, spawned, _asked = local_session
    monkeypatch.setattr(runtime.llama_device, "has_cuda_build", lambda _exe: True)
    session = _session(tmp_path, "cuda")
    with pytest.raises(ComputeUnavailableError, match="CUDA 运行库"):
        session.describe_episode(tmp_path / "ep.mp4", 60.0, tmp_path / "work", count=2)
    assert spawned == []
    assert session.compute() is None, "没跑成的事不留回执"


def test_explicit_cuda_launch_failure_is_not_retried_on_cpu(
    local_session: _Local, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _auto, spawned, _asked = local_session
    _offer_gpu(monkeypatch)
    _gpu_dies(monkeypatch, spawned)
    session = _session(tmp_path, "cuda")
    with pytest.raises(ComputeUnavailableError, match="GPU 启动失败"):
        session.describe_episode(tmp_path / "ep.mp4", 60.0, tmp_path / "work", count=2)
    assert len(spawned) == 1, "显式 cuda 失败后不得再拉一只 CPU 进程"


def test_cpu_request_skips_the_device_probe(
    local_session: _Local, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式 cpu 是逃生口：不跑探测、显式禁用卸载——哪怕机器上有可用的 CUDA 设备。

    禁用不能靠「不带参数」：带 GPU 后端的构建默认把能卸的全卸上显卡（2026-11-12
    实测 CUDA 构建无参数启动即占 5GB 显存，只给 -ngl 0 视觉编码器仍在卡上）——
    回执写 CPU、实际在 GPU，cpu 逃生口就名存实亡。
    """
    _auto, spawned, _asked = local_session

    def must_not_probe(*_a: object, **_k: object) -> list[llama_device.CudaDevice]:
        raise AssertionError("请求 cpu 不该跑设备探测")

    monkeypatch.setattr(runtime.llama_device, "list_cuda_devices", must_not_probe)
    session = _session(tmp_path, "cpu")
    session.describe_episode(tmp_path / "ep.mp4", 60.0, tmp_path / "work", count=2)

    assert _device_arg(spawned[0]) == "none"
    assert spawned[0][spawned[0].index("-ngl") + 1] == "0"
    report = session.compute()
    assert report is not None and (report.requested, report.actual) == ("cpu", "cpu")


def test_open_session_normalizes_the_device_setting(tmp_path: Path) -> None:
    """vision.device 透传给会话；写坏的值按 auto——配置错不该挡住分析。"""
    models = tmp_path / "models"
    model_dir = models / "vl" / "qwen3-vl-4b"
    model_dir.mkdir(parents=True)
    (model_dir / "Qwen3VL-4B-Instruct-Q4_K_M.gguf").write_bytes(b"x")
    (model_dir / "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf").write_bytes(b"x")
    exe = tmp_path / "tools" / "llama.cpp" / "llama-server.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")

    def requested(value: str) -> str:
        session = runtime.open_session(
            tmp_path, models, {"vision.model": "qwen3-vl-4b", "vision.device": value}
        )
        assert isinstance(session, runtime.VisionSession)
        return session._requested  # noqa: SLF001 - 解析结果没有公开读口

    assert requested("cpu") == "cpu"
    assert requested("CUDA") == "cuda"
    assert requested("") == "auto"
    assert requested("gpu-please") == "auto"


def test_cloud_session_reports_only_after_answering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = runtime.CloudVisionSession(base_url="https://x/v1", api_key="k", model="qwen-vl")
    assert session.compute() is None, "一组都没答过（各集走缓存）不发回执"
    frame = tmp_path / "frame-01.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *_a, **_k: _FakeResp(_fake_chat_body(1))
    )
    session._ask_group([frame], 1)  # noqa: SLF001 - 直走传输层，不起采样
    report = session.compute()
    assert report is not None
    assert (report.component, report.actual) == ("vision.cloud", "cloud")
