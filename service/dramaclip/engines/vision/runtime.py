"""视觉描述引擎（P2b）：llama-server 子进程会话 + 帧采样 + 逐图 JSON 解析。

会话生命周期＝一个分析任务：任务级懒加载（首个配置了视觉档的集拉起 llama-server），
跨集复用模型，任务结束关停。失败语义是分档——视觉不可用只记 warn 落空 frames，
分析照常完成，消费端对空 frames 回退纯台词行为（同 subtitle_band 的 NULL 口径）。

形态来自 2026-10-09 真机横评：拼图单请求出局（4B 无格级定位，16 格全首格复读），
**多图独立序列可靠**——每集 16 帧全分辨率采样，4 张一组发多图请求逐图描述。
"""

from __future__ import annotations

import base64
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.infra.ffmpeg import runner

MODEL_KEY = "vision.model"  # 档位 = 模型中心 kind=vision 的 model_id；空 = 视觉轨关闭
_SERVER_REL = Path("tools") / "llama.cpp" / "llama-server.exe"
_FRAMES_PER_REQUEST = 4
_FRAME_WIDTH = 640
_LOAD_TIMEOUT_S = 600.0
_REQUEST_TIMEOUT_S = 900.0
_MMPROJ_PREFIX = "mmproj"


def enabled(settings: dict[str, str]) -> bool:
    return settings.get(MODEL_KEY, "").strip() != ""


def open_session(
    data_dir: Path, models_dir: Path, settings: dict[str, str]
) -> VisionSession | None:
    """按 vision.model 设置开会话；档位空/模型未装/llama-server 缺失 → None（分档，不报错）。"""
    model_id = settings.get(MODEL_KEY, "").strip()
    if model_id == "":
        return None
    model_dir = models_dir / "vl" / model_id
    ggufs = sorted(model_dir.glob("*.gguf"))
    mains = [p for p in ggufs if not p.name.startswith(_MMPROJ_PREFIX)]
    mmprojs = [p for p in ggufs if p.name.startswith(_MMPROJ_PREFIX)]
    exe = data_dir / _SERVER_REL
    if not mains or not mmprojs or not exe.is_file():
        return None
    return VisionSession(model_id=model_id, exe=exe, model=mains[0], mmproj=mmprojs[0])


def sample_frames_args(
    video: str, pattern: str, *, duration_s: float, count: int = 16
) -> list[str]:
    """帧采样 ffmpeg 参数（纯函数）：fps=count/时长 → 640px 宽 → 按序号落盘。"""
    if duration_s <= 0:
        raise ValueError(f"集时长非法: {duration_s}")
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video,
        "-vf",
        f"fps={count / duration_s:.6f},scale={_FRAME_WIDTH}:-2",
        "-frames:v",
        str(count),
        pattern,
    ]


def parse_descriptions(text: str, count: int, episode_s: float) -> list[dict[str, Any]]:
    """逐行解析模型输出 → 时间戳帧描述；坏行跳过不炸（分档语义）。

    第 i 帧的时间取该帧采样窗的中点 (i-0.5)*时长/帧数——帧按时间序采样，序号即时间轴。
    """
    frames: list[dict[str, Any]] = []
    step = episode_s / count if count > 0 else 0.0
    for line in text.splitlines():
        line = line.strip().strip("`").rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or "index" not in item:
            continue
        index = int(item["index"])
        frames.append({
            "t": round((index - 0.5) * step, 2),
            "shot": str(item.get("shot", "")),
            "scene": str(item.get("scene", "")),
            "people": str(item.get("people", "")),
            "action": str(item.get("action", "")),
            "mood": str(item.get("mood", "")),
        })
    return frames


def _prompt_for(count: int) -> str:
    lines = [
        f"上面按顺序给了 {count} 张独立的剧照（第 1~{count} 张，来自同一部剧的不同时刻）。"
        "请对每张图分别输出一行 JSON：",
        '{"index": 1, "shot": "景别", "scene": "场景", "people": "人物外观",'
        ' "action": "动作", "mood": "情绪"}',
        f"要求：每张图单独观察、分别描述，{count} 张内容必须互不相同；",
        "只描述画面本身，图中出现的任何文字（底部烧录字幕、角落人名字条、书法题字）"
        "都是视频叠加物，不是画面内容，禁止写进任何字段；",
        f"{count} 行 JSON 之外不要输出任何文字。",
    ]
    return "\n".join(lines)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class VisionSession:
    """一只 llama-server 子进程：跨集复用模型，用完 close。"""

    def __init__(self, *, model_id: str, exe: Path, model: Path, mmproj: Path) -> None:
        self.model_id = model_id
        self._exe = exe
        self._model = model
        self._mmproj = mmproj
        self._proc: subprocess.Popen[str] | None = None

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._proc is not None:
            raise RuntimeError("llama-server 进程已退出，无法继续视觉描述")
        port = _free_port()
        self._port = port
        self._proc = subprocess.Popen(  # noqa: S603
            [
                str(self._exe),
                "-m", str(self._model),
                "--mmproj", str(self._mmproj),
                "--port", str(port),
                "-c", "12288",
                "--threads", "8",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        deadline = time.monotonic() + _LOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"llama-server 提前退出，码 {self._proc.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
                    if resp.status == 200:
                        return
            except urllib.error.URLError:
                time.sleep(2)
        self.close()
        raise RuntimeError(f"llama-server {_LOAD_TIMEOUT_S:.0f}s 内未就绪")

    def describe_episode(
        self,
        video: Path,
        episode_s: float,
        work_dir: Path,
        *,
        count: int = 16,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        """采样 → 分组多图请求 → 解析；任一环失败上抛（调用方按分档落空）。"""
        if episode_s <= 0:
            raise ValueError(f"集时长非法: {episode_s}")
        self._ensure()
        assert self._proc is not None
        work_dir.mkdir(parents=True, exist_ok=True)
        pattern = str(work_dir / "frame-%02d.png")
        runner.run(
            sample_frames_args(str(video), pattern, duration_s=episode_s, count=count),
            total_duration_s=episode_s,
        )
        frames = sorted(work_dir.glob("frame-*.png"))
        if not frames:
            raise RuntimeError("帧采样未产出")
        pieces: list[str] = []
        groups = [frames[i:i + _FRAMES_PER_REQUEST] for i in range(0, len(frames), _FRAMES_PER_REQUEST)]
        for index, group in enumerate(groups, start=1):
            if on_progress is not None:
                on_progress(index / len(groups), f"画面理解 {index}/{len(groups)} 组")
            pieces.append(self._ask_group(group, len(frames)))
        return parse_descriptions("\n".join(pieces), len(frames), episode_s)

    def _ask_group(self, frames: list[Path], total: int) -> str:
        content: list[dict[str, Any]] = []
        for frame in frames:
            b64 = base64.b64encode(frame.read_bytes()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        content.append({"type": "text", "text": _prompt_for(total)})
        payload = json.dumps({
            "temperature": 0,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": content}],
        }).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self._port}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as resp:
            body = json.load(resp)
        return str(body["choices"][0]["message"]["content"])

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
