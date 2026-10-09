"""VL 视觉轨档位横评试验器 v2（P2b，2026-10-09）。

v1 教训（sheet 单图 16 格）：4B 量化模型对拼图没有格级空间定位，16 格全是首格复读——
**多图独立序列才是可靠形态**：每集采样 N 帧（全分辨率），4 张一组发多图请求，
逐图单独描述（真机 4/4 grounding 全对）。

起停 llama-server（官方预编译，--mmproj 多模态），OpenAI 协议发多图请求，
原始回复与耗时落 data/vl_trial/<名>/。模型无关：换候选只换 --frames/--model/--mmproj。

用法（在仓库根）：
  python scripts/vl_trial.py --name qwen4b --frames "data/vl_trial/mf-*.png" \
      --model data/models/vl/Qwen3VL-4B-Q4_K_M.gguf \
      --mmproj data/models/vl/mmproj-Qwen3VL-4B-Q8_0.gguf [--group 4] [--runs 2]
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_EXE = ROOT / "data" / "tools" / "llama.cpp" / "llama-server.exe"
OUT_DIR = ROOT / "data" / "vl_trial"

PORT = 8741
LOAD_TIMEOUT_S = 600
REQUEST_TIMEOUT_S = 900


def prompt_for(count: int) -> str:
    return f"""上面按顺序给了 {count} 张独立的剧照（第 1~{count} 张，来自同一部剧的不同时刻）。请对每张图分别输出一行 JSON：
{{"index": 1, "shot": "景别", "scene": "场景", "people": "人物外观", "action": "动作", "mood": "情绪"}}
要求：每张图单独观察、分别描述，{count} 张内容必须互不相同；只描述画面本身，图中底部的烧录字幕文字不要写进任何字段；{count} 行 JSON 之外不要输出任何文字。"""


def start_server(model: Path, mmproj: Path) -> subprocess.Popen[str]:
    """起 llama-server（CPU、12K 上下文容 4 图），进程句柄交给调用方关停。"""
    args = [
        str(SERVER_EXE),
        "-m", str(model),
        "--mmproj", str(mmproj),
        "--port", str(PORT),
        "-c", "12288",
        "--threads", "8",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    deadline = time.monotonic() + LOAD_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server 提前退出，码 {proc.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5) as resp:
                if resp.status == 200:
                    return proc
        except urllib.error.URLError:
            time.sleep(2)
    proc.kill()
    raise RuntimeError(f"llama-server {LOAD_TIMEOUT_S}s 内未就绪")


def ask_group(frames: list[Path]) -> tuple[str, float]:
    """一组（多图 + 提示词）一次请求，返回 (回复文本, 推理秒数)。temperature=0 保确定。"""
    content: list[dict[str, object]] = []
    for frame in frames:
        b64 = base64.b64encode(frame.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    content.append({"type": "text", "text": prompt_for(len(frames))})
    payload = json.dumps({
        "temperature": 0,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as resp:
        body = json.load(resp)
    elapsed = time.monotonic() - start
    return str(body["choices"][0]["message"]["content"]), elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="候选名（输出目录名）")
    parser.add_argument("--frames", required=True, help="帧文件 glob（如 data/vl_trial/mf-*.png）")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--mmproj", required=True, type=Path)
    parser.add_argument("--group", type=int, default=4, help="每次请求的帧数")
    parser.add_argument("--runs", type=int, default=2, help="整轮重复次数（首跑含模型加载）")
    args = parser.parse_args()

    if not SERVER_EXE.is_file():
        print(f"缺 llama-server: {SERVER_EXE}", file=sys.stderr)
        return 1
    frames = sorted(Path().glob(args.frames))
    if not frames:
        print(f"glob 无命中: {args.frames}", file=sys.stderr)
        return 1
    groups = [frames[i:i + args.group] for i in range(0, len(frames), args.group)]
    out = OUT_DIR / args.name
    out.mkdir(parents=True, exist_ok=True)

    print(f"[{args.name}] 加载模型 {args.model.name} …", flush=True)
    proc = start_server(args.model, args.mmproj)
    timings: list[float] = []
    try:
        for run in range(1, args.runs + 1):
            run_start = time.monotonic()
            pieces: list[str] = []
            for index, group in enumerate(groups, start=1):
                text, elapsed = ask_group(group)
                timings.append(elapsed)
                pieces.append(f"== 组 {index}（{elapsed:.0f}s）==\n{text}")
            (out / f"run-{run}.txt").write_text("\n\n".join(pieces), encoding="utf-8")
            print(
                f"[{args.name}] run {run}: {time.monotonic() - run_start:.0f}s"
                f"（{len(groups)} 组 × {args.group} 帧）",
                flush=True,
            )
    finally:
        proc.terminate()
    infer_avg = sum(timings) / len(timings)
    (out / "meta.json").write_text(json.dumps({
        "model": args.model.name,
        "mmproj": args.mmproj.name,
        "frames": len(frames),
        "group": args.group,
        "request_avg_s": round(infer_avg, 1),
        "per_frame_avg_s": round(infer_avg / args.group, 1),
        "requests_s": [round(t, 1) for t in timings],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{args.name}] 平均 {infer_avg:.0f}s/组（{infer_avg / args.group:.0f}s/帧）→ {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
