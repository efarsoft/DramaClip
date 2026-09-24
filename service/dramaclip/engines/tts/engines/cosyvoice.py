"""CosyVoice（300M，funasr 之外的阿里系）引擎：子进程桥到隔离 conda env worker。

为什么物理隔离：主 venv Python 3.13 与上游约束不可调和——与 indextts2 共用同一个隔离
venv（tts-venv，见 tts_runtime.py）。文本前端是上游自带的 wetext（纯 pip
wheel，frontend.py:67 实测 import）。

协议（与 indextts worker 逐字同形，见 workers/cosyvoice_worker.py）：
  就绪行: {"ready": true, "device": "cuda"|"cpu"}
  请求:   {"id", "text", "voice": 参考音频路径, "out": 输出wav路径, "lang"}
  应答:   {"id", "ok": true|false, "error"?}

克隆模式用 cross_lingual：zero_shot 需要参考音频的转写文本（prompt_text），
桥协议里没有这个槽位——cross_lingual 免转写直接克隆音色，代价是音色相似度
略逊。要 zero_shot 得先扩协议（voice, prompt_text 双槽），留接入后裁决。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess  # noqa: S404 - 参数为受控列表
import threading
import wave
from pathlib import Path

from dramaclip.engines.tts import reference_qc
from dramaclip.engines.tts.base import EngineCaps
from dramaclip.engines.tts.text_split import split_long_text
from dramaclip.infra.paths import resolve_data_dir

_WORKER_SRC = Path(__file__).parents[1] / "workers" / "cosyvoice_worker.py"
_LAUNCH_TIMEOUT_S = 900.0  # 首次加载三件套权重（llm/flow/hift 约 1.7GB）：CPU 留足余量
_SYNTH_TIMEOUT_S = 900.0

#: 克隆场景的单块字符预算（与 indextts2 同一收紧哲学）：超长单块在生成侧
#: token 预算不足会截断，切短逐块合成再拼。首跑后可按实测调。
_CLONE_MAX_CHARS = 150

#: worker 落盘采样率：模型原生输出统一重采样到 24000Hz（本机 Windows 实测组合
#: 的统一口径；worker 就绪行回带同值，两处不会各漂各的）。
_SAMPLE_RATE = 24_000

#: 模型加载判据（registry._REQUIREMENTS 同口径的轻探测副本）：三件套权重 +
#: zero-shot 必需的语音 tokenizer（cross_lingual 也要它提语义 token）。
_REQUIRED_FILES = ("cosyvoice.yaml", "llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v1.onnx")

_LOCK = threading.Lock()
# 共享 worker 的 stdin/stdout 一问一答整段持锁：试听（RPC 执行池）与出片任务的
# 合成并发打同一进程时，无锁的 write/readline 会应答错配拿到别人的音频。
_IO_LOCK = threading.Lock()
_PROC: subprocess.Popen[str] | None = None
# 就绪行整个 worker 生命周期只发一次，按进程对象身份记账（respawn 天然重置；
# 记在引擎实例上会让第二个实例永远挂在 readline——indextts2 踩过的坑）。
_HELLOED_FOR: subprocess.Popen[str] | None = None
_RUNTIME_OK: bool | None = None


def _env_python() -> Path:
    # 与 IndexTTS 共用的 TTS 运行时（infra/model_manager/tts_runtime.py 维护）
    return resolve_data_dir() / "runtimes" / "tts-venv" / "Scripts" / "python.exe"


def _src_dir() -> Path:
    """上游仓库落位（tts_runtime.py 安装时解包），桥与探针共用一份。"""
    return resolve_data_dir() / "runtimes" / "cosyvoice-src"


def runtime_ready() -> bool:
    """隔离 env 可用（存在且 worker 依赖可 import）。成功即进程内缓存：

    import 探针在逐段合成热路径上重复跑是纯开销；env 中途被删由
    _ensure_worker 的 spawn 失败如实兜底，不会假装成功。
    """
    global _RUNTIME_OK
    if _RUNTIME_OK is True:
        return True
    py = _env_python()
    if not py.is_file():
        return False
    try:
        probe = subprocess.run(  # noqa: S603 - 固定路径受控参数
            [str(py), str(_WORKER_SRC), "--check"],
            capture_output=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "DRAMACLIP_COSYVOICE_SRC": str(_src_dir())},
        )
        if probe.returncode == 0:
            _RUNTIME_OK = True
            return True
        return False
    except (OSError, subprocess.TimeoutExpired):
        return False


def shutdown_worker() -> None:
    """服务退出时收走常驻 worker（Windows 上不收会留占着模型内存的孤儿进程）。

    挂在优雅退出路径（service_app.run 的 finally）；Electron 强杀到不了这里。
    """
    global _PROC
    with _IO_LOCK:
        proc = _PROC
        _PROC = None
    if proc is not None and proc.poll() is None:
        proc.terminate()


def _ensure_worker(models_dir: Path | None) -> subprocess.Popen[str]:
    global _PROC
    with _LOCK:
        if _PROC is not None and _PROC.poll() is None:
            return _PROC
        # device 交给 worker 内 torch 自检（老卡新栈无内核，载入才崩——最小 CUDA
        # 运算探针失败即回 CPU）。stderr 走继承：加载诊断落进服务日志，不盲飞。
        _PROC = subprocess.Popen(  # noqa: S603 - 固定脚本固定参数
            [str(_env_python()), str(_WORKER_SRC), str(models_dir), "auto"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "DRAMACLIP_COSYVOICE_SRC": str(_src_dir())},
        )
        return _PROC


class CosyVoiceEngine:
    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir

    @property
    def name(self) -> str:
        return "cosyvoice"

    def capabilities(self) -> EngineCaps:
        available, reason = self.is_available()
        return EngineCaps(
            sample_rate=_SAMPLE_RATE,
            supports_cloning=True,  # cross_lingual 免转写克隆（zero_shot 需扩协议，见文件头）
            # 上游 infer 有 emotion/instruct 相关入口，但 300M 的 cross_lingual 桥
            # 不透传情绪参数——按「接进来了才算数」声明 False，不冒充。
            supports_emotion=False,
            speed_control="none",
            available=available,
            reason=reason,
        )

    def is_available(self) -> tuple[bool, str]:
        if self._model_dir is not None:
            missing = [
                name
                for name in _REQUIRED_FILES
                if not (self._model_dir / name).is_file()
            ]
            if missing:
                return False, f"缺模型：{self._model_dir} 下没有 {', '.join(missing)}"
        if not runtime_ready():
            return False, (
                "未装运行环境：需要隔离 Python 3.10 conda env"
                "（引擎页「安装运行环境」）"
            )
        return True, "运行环境与模型就绪"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        if not runtime_ready():
            raise RuntimeError(
                "CosyVoice 运行环境未就绪：需要隔离 Python 3.10 conda env"
                "（引擎页「安装运行环境」）"
            )
        if voice == "" or not Path(voice).is_file():
            raise ValueError(
                "CosyVoice 克隆需要参考音频作为音色（任意 3~10 秒人声 wav），当前 voice 为空"
            )
        # B6 质检：poor 只留痕不阻断（与 indextts2 同判——质检是报告不是门禁）。
        quality = reference_qc.inspect_reference(Path(voice))
        if quality.grade == "poor":
            logging.getLogger(__name__).warning(
                "cosyvoice 参考音频质检 poor（%s）：%s",
                quality.metrics or "无指标",
                "；".join(quality.reasons),
            )
        chunks, dropped = split_long_text(text, max_chars=_CLONE_MAX_CHARS)
        if len(chunks) <= 1:
            self._synth_one(text, str(Path(voice).resolve()), out_path)
            return out_path
        parts_dir = out_path.parent / f".{out_path.stem}.parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        try:
            ref = str(Path(voice).resolve())
            parts: list[Path] = []
            for index, chunk in enumerate(chunks):
                part = parts_dir / f"part-{index:04d}.wav"
                self._synth_one(chunk, ref, part)
                parts.append(part)
            _concat_wav(parts, out_path)
        finally:
            for part in parts_dir.glob("*"):
                part.unlink(missing_ok=True)
            parts_dir.rmdir()
        if dropped:
            logging.getLogger(__name__).info(
                "cosyvoice 长文本切分丢弃 %d 个空块（%d 块合成）", dropped, len(chunks)
            )
        return out_path

    def _synth_one(self, text: str, ref: str, out_path: Path) -> None:
        """送一个 job 给 worker 并等应答。整段持 _IO_LOCK：一问一答中间不许插队。"""
        global _HELLOED_FOR
        with _IO_LOCK:
            proc = _ensure_worker(self._model_dir)
            if proc.stdin is None or proc.stdout is None:
                raise RuntimeError("worker 进程管道不可用")
            if _HELLOED_FOR is not proc:
                json.loads(proc.stdout.readline())  # 就绪行只此一条，按进程身份记（见模块头）
                _HELLOED_FOR = proc
            job = {"id": "0", "text": text, "voice": ref, "out": str(out_path)}
            proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            reply = json.loads(proc.stdout.readline())
            if not reply.get("ok"):
                raise RuntimeError(f"CosyVoice 合成失败：{reply.get('error', '未知错误')}")


def _concat_wav(parts: list[Path], out_path: Path) -> None:
    """同参 wav 按帧拼接（worker 恒定单声道 16bit，采样率见 _SAMPLE_RATE 注释）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as out_wav:
        params_set = False
        for part in parts:
            with wave.open(str(part), "rb") as in_wav:
                if not params_set:
                    out_wav.setnchannels(in_wav.getnchannels())
                    out_wav.setsampwidth(in_wav.getsampwidth())
                    out_wav.setframerate(in_wav.getframerate())
                    params_set = True
                out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))
