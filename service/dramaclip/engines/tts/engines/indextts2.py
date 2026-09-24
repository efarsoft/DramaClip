"""IndexTTS-2.5 引擎：子进程桥到隔离 venv worker（主 venv Python 3.13 与上游
`<3.12` 约束、transformers 4.52 vendored 内部 API 均不兼容，物理隔离是唯一干净解）。

worker 进程常驻（一次加载模型），按行 JSON 协议逐段合成；voice=参考音频绝对路径
（零样本克隆：任意 3~10 秒人声 wav）。首次合成前若隔离 venv 不存在，引导脚本可
重建（见 ensure_runtime）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import wave
from pathlib import Path

from dramaclip.engines.tts import reference_qc
from dramaclip.engines.tts.base import EngineCaps
from dramaclip.engines.tts.text_split import split_long_text
from dramaclip.infra.paths import resolve_data_dir

_WORKER_SRC = Path(__file__).parents[1] / "workers" / "indextts_worker.py"
_LAUNCH_TIMEOUT_S = 600.0  # 首次加载全模型：CPU 实测 ~25s，留足余量
_SYNTH_TIMEOUT_S = 900.0  # CPU 档单段可达 2~3 分钟（RTF≈14.5）

#: 克隆场景的单块字符预算。worker 协议只透传 {id,text,voice,out,lang}，传不了预算
#: （隔离 venv 实测 infer 签名有 max_text_tokens_per_segment=120，但桥不转发），
#: 只能在 split 层收紧：参考音频越长 + 文本越长，flow-matching/s2mel 的显存占用
#: 越大，超长单段在 4GB 卡上会崩——120 字符对齐 worker 上游自己的默认分段预算。
_CLONE_MAX_CHARS = 120

#: worker 落盘采样率（量自隔离 venv 内 infer_v2_5.py：sampling_rate = 22050）。
_SAMPLE_RATE = 22050

#: 模型加载判据文件（与 registry._REQUIREMENTS["indextts2"] 同口径的轻探测副本）。
_REQUIRED_FILES = ("config.yaml", "gpt.pth", "s2mel.pth")

_LOCK = threading.Lock()
# 共享 worker 的 stdin/stdout 一问一答整段持锁：试听（RPC 执行池）与出片任务的
# 合成并发打同一进程时，无锁的 write/readline 会应答错配拿到别人的音频。
_IO_LOCK = threading.Lock()
_PROC: subprocess.Popen[str] | None = None
# 就绪行整个 worker 生命周期只发一次，读过没有要记在进程身份上、不能记在引擎实例
# 上——factory 每次都可能 new 新实例，第二个实例再读就绪行会永远挂在 readline 上。
# 按进程对象记账：respawn 出新对象天然重置，不依赖额外的复位分支。
_HELLOED_FOR: subprocess.Popen[str] | None = None
_RUNTIME_OK: bool | None = None


def _venv_python() -> Path:
    # 与 CosyVoice 共用的 TTS 运行时（infra/model_manager/tts_runtime.py 维护）
    return resolve_data_dir() / "runtimes" / "tts-venv" / "Scripts" / "python.exe"


def _src_dir() -> Path:
    return resolve_data_dir() / "runtimes" / "indextts-src"


def runtime_ready() -> bool:
    """隔离 venv 可用（存在且能 import indextts）。成功即进程内缓存：

    30s 的 import 探针放在逐段合成热路径上重复跑是纯开销（narration 每段一次）；
    venv 中途被删的场景由 _ensure_worker 的 spawn 失败如实兜底，不会假装成功。
    """
    global _RUNTIME_OK
    if _RUNTIME_OK is True:
        return True
    py = _venv_python()
    if not py.is_file():
        return False
    try:
        probe = subprocess.run( # noqa: S603 - 固定路径受控参数
            [str(py), "-c", "import indextts, torch"],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if probe.returncode == 0:
            _RUNTIME_OK = True
            return True
        return False
    except (OSError, subprocess.TimeoutExpired):
        return False


def shutdown_worker() -> None:
    """服务退出时收走常驻 worker：Windows 上不收会留孤儿 python.exe

    一直占着数 GB 的模型内存/显存。挂在优雅退出路径（system.shutdown/SIGTERM
    → service_app.run 的 finally）上；Electron 强杀（TerminateProcess）到不了
    这里，那类场景进程树随主进程终止，无法善后。
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
        # device 交给 worker 内 torch 自检：探测层不区分 CUDA 代际（M4000 cc5.2 这类
        # 「有 N 卡但新栈不支持」的机器，init 失败进程即退，错误经 stdout 空行带回）。
        # stderr 走继承：worker 的 CUDA 回退/加载诊断（">> CUDA 探针失败"）经服务
        # stderr 落进 Electron 主进程日志——DEVNULL 吞掉等于盲飞。
        _PROC = subprocess.Popen( # noqa: S603 - 固定脚本固定参数
            [str(_venv_python()), str(_WORKER_SRC), str(models_dir), "auto"],
            env={
                **os.environ,
                "DRAMACLIP_INDEXTTS_SRC": str(_src_dir()),
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return _PROC


class IndexTts2Engine:
    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir

    @property
    def name(self) -> str:
        return "indextts2"

    def capabilities(self) -> EngineCaps:
        available, reason = self.is_available()
        return EngineCaps(
            sample_rate=_SAMPLE_RATE,
            supports_cloning=True,  # 零样本克隆：voice=参考音频路径，桥已接通
            # 库本身支持情绪（infer 签名 emo_text/emo_vector，实测），但 worker 桥
            # 协议不转发情绪参数——按「接进来了才算数」的口径声明 False，不冒充。
            supports_emotion=False,
            # 同理：infer 有 duration_factor，但桥不转发 → 当前接入形态无变速控制。
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
                "未装运行环境：需要隔离 Python 3.11 venv"
                "（引擎页「安装运行环境」）"
            )
        return True, "运行环境与模型就绪"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        if not runtime_ready():
            raise RuntimeError(
                "IndexTTS 运行环境未就绪：需要隔离 Python 3.11 venv"
                "（引擎页「安装运行环境」）"
            )
        if voice == "" or not Path(voice).is_file():
            raise ValueError(
                "IndexTTS 需要参考音频作为音色（任意 3~10 秒人声 wav），当前 voice 为空"
            )
        # B6 质检：poor 只留痕不阻断——质检是报告不是门禁，用户可能就是要用这段
        # 参考，拦死是假门禁（硬约束是批次一的「显式引擎不回退」，不在这一层）。
        # 为什么不做 (ref_audio, ref_text) 重转写核对：worker 桥协议只透传
        # {id,text,voice,out,lang}，没有 ref_text 槽位，IndexTTS2 内部自转写
        # 参考音频——「参考对不配对」这个问题形态在当前接入里不存在。
        quality = reference_qc.inspect_reference(Path(voice))
        if quality.grade == "poor":
            logging.getLogger(__name__).warning(
                "indextts2 参考音频质检 poor（%s）：%s",
                quality.metrics or "无指标",
                "；".join(quality.reasons),
            )
        # B7 长文本：克隆预算收紧切块（见 _CLONE_MAX_CHARS 注释），逐块送 worker，
        # wav 帧拼接落 out_path 单文件——对调用方透明（契约见 base.TtsEngine）。
        # 拼接后实测时长由下游 audio_duration_s 读最终 wav 天然取得；批次二 hook
        # 槽位的 atempo 决策用的就是那个实测值，无需在这里做任何补偿。
        # 中文数字归一化不在这一层做：worker 上游 infer(text_normalization=True)
        # 自己归一化（实测默认值），这里再转一遍就是双重转换。
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
                "indextts2 长文本切分丢弃 %d 个空块（%d 块合成）", dropped, len(chunks)
            )
        return out_path

    def _synth_one(self, text: str, ref: str, out_path: Path) -> None:
        """送一个 job 给 worker 并等应答（协议见文件头注释）。

        整段持 _IO_LOCK：一问一答中间不许插队（并发场景见 _IO_LOCK 注释）。
        """
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
                raise RuntimeError(f"IndexTTS 合成失败：{reply.get('error', '未知错误')}")


def _concat_wav(parts: list[Path], out_path: Path) -> None:
    """同参 wav（worker 恒定 22050Hz/单声道/16bit）按帧拼接。

    直接拼 PCM 帧不做 crossfade：块间 worker 自己会落 interval_silence=200ms
    的静音间隔（infer 默认参数），再叠 50ms crossfade 反而会削掉句间停顿。
    """
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
