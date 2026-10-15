"""vision.runtime：采样参数纯函数 + 解析容差 + 会话开闭的分档判据 + 本地会话拉进程。"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from dramaclip.engines.vision import runtime


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
    """围栏/空行/坏行跳过；缺字段补空串——坏行不炸整集（分档语义）。"""
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
    assert frames[1] == {
        "t": 45.0, "shot": "", "scene": "大殿", "people": "", "action": "", "mood": "",
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
    session = runtime.VisionSession(
        model_id="qwen3-vl-4b",
        exe=tmp_path / "llama-server.exe",
        model=tmp_path / "model.gguf",
        mmproj=tmp_path / "mmproj.gguf",
    )
    return session, spawned, asked


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
