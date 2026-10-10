"""vision.runtime：采样参数纯函数 + 解析容差 + 会话开闭的分档判据。"""

from __future__ import annotations

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
