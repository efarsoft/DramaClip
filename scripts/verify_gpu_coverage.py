"""全流程算力覆盖验真：逐部件真跑最小负载，不读 profile、不信声明。

状态纪律：
  pass        真实负载成功，且实际设备/编码器与请求一致；
  fail        负载失败或实际结果违背请求（产品/代码问题）；
  unsupported 本机能力或运行环境不满足（无内核、缺模型、缺运行库），不算通过。

GPU 项必须真跑（样例转写 / 短句合成 / 黑帧真编 / 短参考分离）；CPU 项同表真跑。
退出码：0 = 无 fail 且所有 --require 满足；1 = 有 fail 或 require 未满足；2 = 参数错误。

用法（真机推荐 service/.venv，ASR 的 torch cu126 路径才可见）：
  service/.venv/Scripts/python.exe scripts/verify_gpu_coverage.py
  service/.venv/Scripts/python.exe scripts/verify_gpu_coverage.py \
      --require asr.funasr.cuda=pass --require separation.cuda=pass --require video.encode.cuda=pass
  service/.venv/Scripts/python.exe scripts/verify_gpu_coverage.py --list
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess  # noqa: S404 - 参数为受控列表
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))

STATUSES = frozenset({"pass", "fail", "unsupported"})
REQUESTS = frozenset({"auto", "cpu", "cuda"})
REASON_MAX_CHARS = 500
_VIDEO_SIZE = (320, 240)
_LABEL_MIN_MEAN = 8.0
_LABEL_MIN_DELTA = 6.0
_HW_ENCODERS = frozenset({"h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"})

#: 只认「本机能力/运行库」类失败；普通的模型/参数错误仍判 fail——把产品 bug
#: 说成 unsupported 会让发布门禁放过真正的回归。
_UNSUPPORTED_PATTERNS = (
    r"ComputeUnavailableError",
    r"请求 CUDA",
    r"torch\.cuda\.is_available",
    r"not compiled with CUDA",
    r"no kernel image",
    r"compute capability",
    r"sm_\d+",
    r"cublas|cudnn|cudart|cufft",
    r"CUDA (failed|error|driver)",
    r"CUDAExecutionProvider",
)

CheckFn = Callable[[], "str | tuple[str, str]"]


class Unsupported(RuntimeError):
    """本机不满足前置条件（不是产品失败）。"""


@dataclass(frozen=True)
class Record:
    component: str
    requested: str
    runtime: str
    status: str
    actual: str = "unknown"
    reason: str = ""
    elapsed_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.component or not self.runtime:
            raise ValueError("record 的 component/runtime 不能为空")
        if self.requested not in REQUESTS:
            raise ValueError(f"未知请求: {self.requested!r}")
        if self.status not in STATUSES:
            raise ValueError(f"未知 status: {self.status!r}（只允许 pass/fail/unsupported）")
        if self.status == "pass" and self.actual in ("", "unknown"):
            raise ValueError("pass 必须带实际设备/编码器（actual）")
        if self.status != "pass" and not self.reason.strip():
            raise ValueError("非 pass 必须带 reason")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["elapsed_s"] = round(self.elapsed_s, 2)
        return payload


@dataclass
class Context:
    data_dir: Path
    models_dir: Path
    resources_dir: Path
    work_dir: Path


# --------------------------------------------------------------------------- 纯逻辑


def parse_require(values: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for value in values:
        name, sep, status = value.partition("=")
        if not sep or not name.strip() or status not in STATUSES:
            raise ValueError(
                f"--require 形状应为 component=pass|fail|unsupported，收到 {value!r}"
            )
        out.append((name.strip(), status))
    return out


def unmet_requirements(
    records: list[Record], requirements: list[tuple[str, str]]
) -> list[str]:
    by_name: dict[str, list[Record]] = {}
    for record in records:
        by_name.setdefault(record.component, []).append(record)
    unmet: list[str] = []
    for name, want in requirements:
        matched = by_name.get(name)
        if not matched:
            unmet.append(f"{name}={want}（本轮没有产出该组件的结果）")
            continue
        for record in matched:
            if record.status != want:
                detail = record.reason or record.actual
                unmet.append(f"{name}={want}（实际 {record.status}：{detail}）")
    return unmet


def judge_actual(component: str, requested: str, actual: str) -> str:
    actual = (actual or "").strip()
    if actual in ("", "unknown"):
        return "成功路径没有实际设备证据（actual=unknown）"
    if component.startswith("video."):
        if requested == "cpu" and actual != "libx264":
            return f"请求 cpu，实际编码器 {actual}"
        if requested == "cuda" and actual not in _HW_ENCODERS:
            return f"请求 cuda，实际编码器 {actual}"
        return ""
    if requested == "cpu" and actual != "cpu":
        return f"请求 cpu，实际 {actual}"
    if requested == "cuda" and actual != "cuda":
        return f"请求 cuda，实际 {actual}"
    if requested == "auto" and actual not in {"cpu", "cuda", "cloud"}:
        return f"auto 解析到未知设备 {actual}"
    return ""


def classify_error(exc: Exception, requested: str) -> str:
    if requested != "cuda":
        return "fail"
    text = f"{type(exc).__name__}: {exc}"
    if any(re.search(pattern, text, re.I) for pattern in _UNSUPPORTED_PATTERNS):
        return "unsupported"
    return "fail"


def sanitize(text: str, roots: dict[str, str]) -> str:
    cleaned = str(text or "")
    for root, label in sorted(roots.items(), key=lambda item: len(item[0]), reverse=True):
        if not root:
            continue
        cleaned = cleaned.replace(root, label)
        cleaned = cleaned.replace(root.replace("\\", "/"), label)
    cleaned = re.sub(r"C:\\Users\\[^\\/\s]+", "<home>", cleaned, flags=re.I)
    cleaned = re.sub(r"/home/[^/\s]+", "<home>", cleaned)
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    if len(cleaned) > REASON_MAX_CHARS:
        cleaned = cleaned[: REASON_MAX_CHARS - 1] + "…"
    return cleaned


def selected(check_id: str, selectors: list[str]) -> bool:
    if not selectors:
        return True
    for selector in selectors:
        raw = selector.strip()
        if raw in ("", "all", "*"):
            return True
        prefix = raw[:-1] if raw.endswith("*") else raw
        if check_id == prefix or check_id.startswith(prefix.rstrip(".") + "."):
            return True
    return False


# --------------------------------------------------------------------------- 运行时


def runtime_label() -> str:
    exe = sys.executable.replace("\\", "/").lower()
    if "/runtimes/tts-venv/" in exe:
        return "tts-venv"
    if "/service/.venv/" in exe:
        return "service-venv"
    if "/.venv/" in exe:
        return "root-venv"
    return "python"


def _venv_python(ctx: Context) -> Path:
    return ctx.data_dir / "runtimes" / "tts-venv" / "Scripts" / "python.exe"


def _require_tts_venv(ctx: Context) -> None:
    if not _venv_python(ctx).is_file():
        raise Unsupported("TTS 运行环境未安装（tts-venv）：先安装本地运行环境")


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise Unsupported(f"{label}缺失：{path.name}")


def _require_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise Unsupported(f"{label}未安装：{path.name}")


def _report_actual(report: Any, label: str) -> str:
    if report is None:
        raise RuntimeError(f"{label} 没有算力回执（引擎没有真加载/推理）")
    from dramaclip.infra import compute

    compute.assert_success(report)
    return str(report.actual)


def _audio_duration(path: Path) -> float:
    from dramaclip.engines.tts.base import audio_duration_s

    return float(audio_duration_s(path))


def _sample(ctx: Context, name: str) -> Path:
    path = ctx.resources_dir / "selftest" / name
    _require_file(path, f"随包样例 {name} ")
    return path


# --------------------------------------------------------------------------- ASR


def _whisper_size(models_dir: Path) -> str:
    for size in ("base", "small", "medium", "large-v3"):
        if (models_dir / f"models--Systran--faster-whisper-{size}").is_dir():
            return size
    raise Unsupported("faster-whisper 模型未安装")


def _asr_whisper(ctx: Context, requested: str) -> str:
    from dramaclip.engines.analysis.transcriber import FasterWhisperEngine

    models_dir = ctx.models_dir / "asr" / "faster-whisper"
    size = _whisper_size(models_dir)
    sample = _sample(ctx, "sample_zh.wav")
    engine = FasterWhisperEngine(size, device=requested, models_dir=models_dir)
    segments = engine.transcribe(sample, "zh")
    if not "".join(segment.text for segment in segments).strip():
        raise RuntimeError("转写结果为空——引擎没有真跑通")
    return _report_actual(engine.compute(), "asr.whisper")


def _asr_funasr(ctx: Context, requested: str) -> str:
    from dramaclip.engines.analysis.transcriber import SenseVoiceEngine

    model_dir = ctx.models_dir / "asr" / "iic" / "SenseVoiceSmall"
    _require_dir(model_dir, "SenseVoice 模型")
    sample = _sample(ctx, "sample_zh.wav")
    engine = SenseVoiceEngine(models_dir=ctx.models_dir, device=requested)
    segments = engine.transcribe(sample, "zh")
    if not "".join(segment.text for segment in segments).strip():
        raise RuntimeError("转写结果为空——引擎没有真跑通")
    return _report_actual(engine.compute(), "asr.funasr")


def _asr_funasr_runtime() -> str:
    return runtime_label() if importlib.util.find_spec("funasr") is not None else "tts-venv"


# --------------------------------------------------------------------------- TTS


def _tts_kokoro(ctx: Context, requested: str) -> str:
    from dramaclip.engines.tts.engines import kokoro as kokoro_mod

    _require_tts_venv(ctx)
    model_dir = ctx.models_dir / "tts" / "kokoro" / "Kokoro-82M-v1.1-zh"
    _require_file(model_dir / "config.json", "Kokoro 模型 ")
    _require_file(model_dir / "kokoro-v1_1-zh.pth", "Kokoro 权重 ")
    _require_file(model_dir / "voices" / "zf_001.pt", "Kokoro 音色 ")

    # 生产态（冻结包）没有进程内 kokoro：强制 worker 路径，验的才是随包运行环境。
    original = kokoro_mod._kokoro_importable
    kokoro_mod._kokoro_importable = lambda: False
    try:
        engine = kokoro_mod.KokoroEngine(model_dir, device=requested)
        out = ctx.work_dir / f"kokoro-{requested}.wav"
        engine.synthesize("你好，这是算力自检。", "zf_001", out)
        if _audio_duration(out) <= 0:
            raise RuntimeError("合成结果不是有效音频")
        return _report_actual(engine.compute(), "tts.kokoro")
    finally:
        kokoro_mod._kokoro_importable = original


def _tts_engine(ctx: Context, engine_name: str, requested: str) -> str:
    from dramaclip.engines.tts.factory import create

    _require_tts_venv(ctx)
    engine = create(engine_name, ctx.models_dir, device=requested)
    available, reason = engine.is_available()
    if not available:
        raise Unsupported(reason)
    voice = _sample(ctx, "sample_ref_voice.wav")
    out = ctx.work_dir / f"{engine_name}-{requested}.wav"
    engine.synthesize("你好。", str(voice), out)
    if _audio_duration(out) <= 0:
        raise RuntimeError("合成结果不是有效音频")
    return _report_actual(engine.compute(), f"tts.{engine_name}")


def _cosyvoice_name(ctx: Context) -> str:
    v3 = ctx.models_dir / "tts" / "funcosyvoice3" / "cosyvoice3.yaml"
    return "cosyvoice3" if v3.is_file() else "cosyvoice"


# --------------------------------------------------------------------------- 人声分离


def _separation(ctx: Context, requested: str) -> str:
    from dramaclip.engines.tts import vocal_separation

    _require_tts_venv(ctx)
    _require_file(
        vocal_separation.model_path(ctx.models_dir), "人声分离模型 "
    )
    source = ctx.work_dir / f"separate-{requested}.wav"
    shutil.copyfile(_sample(ctx, "sample_ref_voice.wav"), source)
    result = vocal_separation.clean_reference(
        ctx.models_dir, source, device=requested
    )
    if _audio_duration(result.path) <= 0:
        raise RuntimeError("分离产物不是有效音频")
    return _report_actual(result.compute, "tts.separation")


# --------------------------------------------------------------------------- 视频


def _ffmpeg() -> Path:
    from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

    try:
        return Path(resolve_ffmpeg())
    except Exception as exc:  # noqa: BLE001 - 缺 ffmpeg 是环境未就绪
        raise Unsupported(f"ffmpeg 不可用：{exc}") from exc


def _run(cmd: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - 固定可执行文件、受控参数
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout_s, check=False,
    )


def _make_source(ctx: Context) -> Path:
    source = ctx.work_dir / "source.mp4"
    result = _run(
        [
            str(_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={_VIDEO_SIZE[0]}x{_VIDEO_SIZE[1]}:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=48000",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(source),
        ],
        timeout_s=120,
    )
    if result.returncode != 0 or not source.is_file():
        raise Unsupported(f"测试源生成失败：{(result.stderr or '')[-300:]}")
    return source


def _ensure_source(ctx: Context) -> Path:
    source = ctx.work_dir / "source.mp4"
    if not source.is_file():
        _make_source(ctx)
    return source


def _probe_video_codec(path: Path) -> str:
    from dramaclip.infra.ffmpeg.binaries import resolve_ffprobe

    result = _run(
        [
            str(resolve_ffprobe()), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1",
            str(path),
        ],
        timeout_s=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败：{(result.stderr or '')[-300:]}")
    return result.stdout.strip()


def _encode_segment(
    ctx: Context, source: Path, out: Path, codec: str, label_vf: str | None
) -> None:
    from dramaclip.engines.exporter import encoder

    args = encoder.cut_segment_args(
        str(source),
        str(out),
        start=0.0,
        end=1.0,
        audio="original",
        tts_audio=None,
        rng=random.Random(7),
        out_size=_VIDEO_SIZE,
        video_codec=codec,
        ai_label_vf=label_vf,
    )
    encoder._run_cut(args, timeout_s=180)
    if not out.is_file() or out.stat().st_size <= 0:
        raise RuntimeError(f"{codec} 编码没有产物")


def _select_hw_encoder() -> tuple[str, str]:
    """按 encoder 的候选序逐个真试编，返回（首个通过者, 跳过项原因）。

    候选序与探针形状都读 encoder 的同一处函数：脚本另写一张表就会出现在
    「产品能导出、验收说 unsupported」的两套结论（规格 §5.2）。全失败抛
    `Unsupported`——本机没有硬编不是产品失败，但必须逐项说清为什么不算。
    """
    from dramaclip.engines.exporter import encoder

    skipped: list[str] = []
    for codec in encoder._hw_candidates():
        try:
            encoder._run_cut(encoder._hw_probe_args(codec), timeout_s=30)
        except Exception as exc:  # noqa: BLE001 - 真试编失败即该候选在本机不可用
            skipped.append(f"{codec}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        return codec, "；".join(skipped)
    raise Unsupported(
        "本机没有任何硬编候选通过真试编：" + ("；".join(skipped) or "候选序为空")
    )


def _video_encode(ctx: Context, codec: str) -> str:
    source = _ensure_source(ctx)
    out = ctx.work_dir / f"encode-{codec}.mp4"
    _encode_segment(ctx, source, out, codec, None)
    probed = _probe_video_codec(out)
    if probed != "h264":
        raise RuntimeError(f"产物编码不是 h264：{probed}")
    if _video_duration(out) <= 0:
        raise RuntimeError("产物时长无效")
    return codec


def _video_duration(path: Path) -> float:
    from dramaclip.infra.ffmpeg.probe import probe

    return float(probe(path).duration_s)


def _label_region_mean(path: Path) -> float:
    # rawvideo 是原始灰度字节，不能走 text=True 的解码→重编码往返。
    result = subprocess.run(  # noqa: S603 - 固定可执行文件、受控参数
        [
            str(_ffmpeg()), "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-ss", "0.5", "-frames:v", "1",
            "-vf", "crop=iw*0.4:ih*0.3:iw*0.6:0,format=gray",
            "-f", "rawvideo", "-",
        ],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"抽帧失败：{stderr[-300:]}")
    data = result.stdout
    return sum(data) / len(data)


def _video_ai_label(ctx: Context, codec: str) -> tuple[str, str]:
    from dramaclip.engines.exporter import ai_label

    source = _ensure_source(ctx)
    label_dir = ctx.work_dir / f"label-{codec}"
    spec = ai_label.prepare(label_dir, _VIDEO_SIZE)
    labeled = ctx.work_dir / f"label-{codec}.mp4"
    plain = ctx.work_dir / f"plain-{codec}.mp4"
    _encode_segment(ctx, source, labeled, codec, spec.vf)
    _encode_segment(ctx, source, plain, codec, None)
    if _probe_video_codec(labeled) != "h264":
        raise RuntimeError("标注产物编码不是 h264")
    with_label = _label_region_mean(labeled)
    without_label = _label_region_mean(plain)
    delta = with_label - without_label
    if with_label < _LABEL_MIN_MEAN or delta < _LABEL_MIN_DELTA:
        raise RuntimeError(
            f"标注区未见文字：有标注亮度 {with_label:.1f}，无标注 {without_label:.1f}"
            f"（阈值 {_LABEL_MIN_MEAN:.0f}/{_LABEL_MIN_DELTA:.0f}）"
        )
    return codec, f"标注区亮度 {with_label:.1f}（无标注 {without_label:.1f}）"


# --------------------------------------------------------------------------- 检查表


def _checks(ctx: Context) -> list[tuple[str, str, str, CheckFn]]:
    return [
        ("video.encode.cpu", "cpu", "ffmpeg", lambda: _video_encode(ctx, "libx264")),
        ("video.encode.cuda", "cuda", "ffmpeg", _video_encode_cuda(ctx)),
        ("video.ai_label.cpu", "cpu", "ffmpeg", lambda: _video_ai_label(ctx, "libx264")),
        ("video.ai_label.cuda", "cuda", "ffmpeg", _video_ai_label_cuda(ctx)),
        ("separation.cpu", "cpu", "tts-venv", lambda: _separation(ctx, "cpu")),
        ("separation.cuda", "cuda", "tts-venv", lambda: _separation(ctx, "cuda")),
        ("asr.whisper.cpu", "cpu", runtime_label(), lambda: _asr_whisper(ctx, "cpu")),
        ("asr.whisper.cuda", "cuda", runtime_label(), lambda: _asr_whisper(ctx, "cuda")),
        ("asr.funasr.cpu", "cpu", _asr_funasr_runtime(), lambda: _asr_funasr(ctx, "cpu")),
        ("asr.funasr.cuda", "cuda", _asr_funasr_runtime(), lambda: _asr_funasr(ctx, "cuda")),
        ("tts.kokoro.cpu", "cpu", "tts-venv", lambda: _tts_kokoro(ctx, "cpu")),
        ("tts.kokoro.cuda", "cuda", "tts-venv", lambda: _tts_kokoro(ctx, "cuda")),
        (
            "tts.indextts2.cpu", "cpu", "tts-venv",
            lambda: _tts_engine(ctx, "indextts2", "cpu"),
        ),
        (
            "tts.indextts2.cuda", "cuda", "tts-venv",
            lambda: _tts_engine(ctx, "indextts2", "cuda"),
        ),
        (
            "tts.cosyvoice.cpu", "cpu", "tts-venv",
            lambda: _tts_engine(ctx, _cosyvoice_name(ctx), "cpu"),
        ),
        (
            "tts.cosyvoice.cuda", "cuda", "tts-venv",
            lambda: _tts_engine(ctx, _cosyvoice_name(ctx), "cuda"),
        ),
    ]


def _video_encode_cuda(ctx: Context) -> CheckFn:
    def run() -> tuple[str, str]:
        codec, skipped = _select_hw_encoder()
        return _video_encode(ctx, codec), skipped

    return run


def _video_ai_label_cuda(ctx: Context) -> CheckFn:
    def run() -> tuple[str, str]:
        codec, skipped = _select_hw_encoder()
        actual, note = _video_ai_label(ctx, codec)
        return actual, f"{note}｜候选回落：{skipped}" if skipped else note

    return run


# --------------------------------------------------------------------------- 执行与记录


def run_check(component: str, requested: str, runtime: str, fn: CheckFn) -> Record:
    started = time.monotonic()
    try:
        result = fn()
    except Unsupported as exc:
        return Record(
            component=component, requested=requested, runtime=runtime,
            status="unsupported", actual="unknown", reason=str(exc),
            elapsed_s=time.monotonic() - started,
        )
    except Exception as exc:  # noqa: BLE001 - 失败原文就是验收结论
        status = classify_error(exc, requested)
        return Record(
            component=component, requested=requested, runtime=runtime,
            status=status, actual="unknown",
            reason=f"{type(exc).__name__}: {exc}",
            elapsed_s=time.monotonic() - started,
        )
    actual, note = result if isinstance(result, tuple) else (result, "")
    elapsed = time.monotonic() - started
    violation = judge_actual(component, requested, str(actual))
    if violation:
        return Record(
            component=component, requested=requested, runtime=runtime,
            status="fail", actual=str(actual), reason=violation, elapsed_s=elapsed,
        )
    return Record(
        component=component, requested=requested, runtime=runtime,
        status="pass", actual=str(actual), reason=note, elapsed_s=elapsed,
    )


def _environment() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "interpreter": sys.executable,
    }
    try:
        from dramaclip.infra import gpu

        host = gpu.detect()
        info["host_gpu"] = {
            "vendor": host.get("vendor"),
            "name": host.get("name"),
            "driver_version": host.get("driver_version"),
            "adapters": [
                {
                    "name": a.get("name"),
                    "vendor": a.get("vendor"),
                    "driver_version": a.get("driver_version"),
                }
                for a in (host.get("adapters") or [])
            ],
        }
    except Exception as exc:  # noqa: BLE001 - 宿主探测失败不是验收失败
        info["host_gpu"] = f"unavailable: {type(exc).__name__}"
    try:
        import torch

        info["torch"] = torch.__version__
        info["torch_cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
            info["compute_capability"] = ".".join(
                str(part) for part in torch.cuda.get_device_capability(0)
            )
    except Exception as exc:  # noqa: BLE001 - 环境探测失败不是验收失败
        info["torch"] = f"unavailable: {type(exc).__name__}"
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        result = _run(
            [nvidia, "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"],
            timeout_s=30,
        )
        if result.returncode == 0:
            info["nvidia_smi"] = result.stdout.strip().splitlines()[:2]
    try:
        result = _run([str(_ffmpeg()), "-version"], timeout_s=30)
        info["ffmpeg"] = (result.stdout or "").splitlines()[0][:160]
    except Exception:  # noqa: BLE001 - 已由视频检查给出明确 unsupported
        info["ffmpeg"] = "unavailable"
    return info


def _print_record(record: Record) -> None:
    mark = {"pass": "PASS", "fail": "FAIL", "unsupported": "UNSUPPORTED"}[record.status]
    line = f"[{mark:11}] {record.component:24} actual={record.actual:12} {record.elapsed_s:6.1f}s"
    if record.reason:
        line += f"  {record.reason}"
    print(line, flush=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DramaClip 全流程算力覆盖验真")
    parser.add_argument(
        "--components", default="all",
        help="逗号分隔；支持前缀（asr / tts.kokoro / video.encode.*），默认 all",
    )
    parser.add_argument(
        "--require", action="append", default=[],
        help="发布门禁：component=pass（可重复）；unsupported 不算满足",
    )
    parser.add_argument("--data-dir", default="", help="覆盖 DRAMACLIP_DATA_DIR")
    parser.add_argument("--out", default="", help="验收记录 JSON 路径")
    parser.add_argument("--no-record", action="store_true", help="只打印，不写 docs 记录")
    parser.add_argument("--keep", action="store_true", help="保留临时产物")
    parser.add_argument("--list", action="store_true", help="列出全部检查项后退出")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        requirements = parse_require(args.require)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    selectors = [part for part in args.components.split(",") if part.strip()]

    if args.data_dir:
        os.environ["DRAMACLIP_DATA_DIR"] = str(Path(args.data_dir).resolve())
    from dramaclip.infra.paths import resolve_data_dir, resolve_resources_dir

    data_dir = resolve_data_dir()
    # 与 service_app 启动路径一致：ctranslate2 用 LoadLibrary 找 cublas/cudnn，
    # 不注入时 whisper 会把「没找到 DLL」误报成设备不可用。
    from dramaclip.infra.model_manager import cuda_runtime

    cuda_runtime.inject_dll_dirs(data_dir)
    work_dir = Path(tempfile.mkdtemp(prefix="dramaclip-gpu-verify-"))
    ctx = Context(
        data_dir=data_dir,
        models_dir=data_dir / "models",
        resources_dir=resolve_resources_dir(),
        work_dir=work_dir,
    )
    checks = _checks(ctx)
    if args.list:
        for component, requested, runtime, _fn in checks:
            print(f"{component:24} requested={requested:5} runtime={runtime}")
        shutil.rmtree(work_dir, ignore_errors=True)
        return 0

    chosen = [check for check in checks if selected(check[0], selectors)]
    if not chosen:
        print(f"没有匹配的检查项：{args.components!r}", file=sys.stderr)
        shutil.rmtree(work_dir, ignore_errors=True)
        return 2

    print(f"data_dir={data_dir}", flush=True)
    print(f"interpreter={sys.executable}", flush=True)
    print(f"checks={len(chosen)}", flush=True)
    records: list[Record] = []
    interrupted = False
    try:
        for component, requested, runtime, fn in chosen:
            print(f"→ {component} ({requested}) ...", flush=True)
            record = run_check(component, requested, runtime, fn)
            records.append(record)
            _print_record(record)
    except KeyboardInterrupt:
        interrupted = True
        print("已中断：已完成的记录仍会落盘", file=sys.stderr)
    finally:
        if args.keep:
            print(f"临时产物保留在 {work_dir}", flush=True)
        else:
            shutil.rmtree(work_dir, ignore_errors=True)

    roots = {
        str(REPO): "<repo>",
        str(data_dir): "<data>",
        str(ctx.resources_dir): "<resources>",
        str(Path.home()): "<home>",
        str(work_dir): "<work>",
    }
    cleaned = [
        {**record.to_dict(), "reason": sanitize(record.reason, roots)}
        for record in records
    ]
    unmet = unmet_requirements(records, requirements)
    counts = Counter(record.status for record in records)
    environment = {
        key: sanitize(str(value), roots)
        for key, value in _environment().items()
    }
    payload = {
        "tool": "verify_gpu_coverage",
        "version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "environment": environment,
        "summary": {
            "pass": counts.get("pass", 0),
            "fail": counts.get("fail", 0),
            "unsupported": counts.get("unsupported", 0),
            "note": "unsupported 不计入通过",
        },
        "records": cleaned,
        "requirements": [
            {"component": name, "status": status} for name, status in requirements
        ],
        "unmet": unmet,
    }
    if not args.no_record:
        out = (
            Path(args.out)
            if args.out
            else REPO / "docs" / "superpowers" / "verification"
            / f"gpu-coverage-{datetime.now():%Y-%m-%d}.json"
        )
        _write_json(out, payload)
        print(f"验收记录：{out}", flush=True)

    print(
        f"汇总：pass={counts.get('pass', 0)} fail={counts.get('fail', 0)} "
        f"unsupported={counts.get('unsupported', 0)}（unsupported 不算通过）"
    )
    if unmet:
        print("未满足的发布门禁：")
        for item in unmet:
            print(f"  - {item}")
    if interrupted:
        return 130
    return 1 if counts.get("fail", 0) or unmet else 0


if __name__ == "__main__":
    raise SystemExit(main())
