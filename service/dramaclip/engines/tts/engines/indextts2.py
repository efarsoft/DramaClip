"""IndexTTS-2.5 引擎：子进程桥到隔离 venv worker（主 venv Python 3.13 与上游
`<3.12` 约束、transformers 4.52 vendored 内部 API 均不兼容，物理隔离是唯一干净解）。

worker 进程常驻（一次加载模型），按行 JSON 协议逐段合成；voice=参考音频绝对路径
（零样本克隆：任意 3~10 秒人声 wav）。首次合成前若隔离 venv 不存在，引导脚本可
重建（见 ensure_runtime）。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from dramaclip.engines.tts import reference_qc
from dramaclip.engines.tts.base import EngineCaps
from dramaclip.engines.tts.local_bridge import WorkerBridge, concat_wav
from dramaclip.engines.tts.text_split import split_long_text
from dramaclip.infra import compute
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

_RUNTIME_OK: bool | None = None


def _venv_python() -> Path:
    # 与 CosyVoice 共用的 TTS 运行时（infra/model_manager/tts_runtime.py 维护）
    return resolve_data_dir() / "runtimes" / "tts-venv" / "Scripts" / "python.exe"


def _src_dir() -> Path:
    return resolve_data_dir() / "runtimes" / "indextts-src"


def _worker_env() -> dict[str, str]:
    return {
        "DRAMACLIP_INDEXTTS_SRC": str(_src_dir()),
        # 协议是 UTF-8；不指定时子进程按系统 ANSI 代码页解码中文。
        "PYTHONIOENCODING": "utf-8",
    }


_BRIDGE = WorkerBridge(
    label="IndexTTS",
    worker_src=_WORKER_SRC,
    venv_python=_venv_python,
    env=_worker_env,
    launch_timeout_s=_LAUNCH_TIMEOUT_S,
    synth_timeout_s=_SYNTH_TIMEOUT_S,
    pre_spawn=lambda models_dir: _ensure_aux_models(models_dir),
)


def runtime_ready() -> bool:
    """隔离 venv 可用（存在且能按 worker 同款引导 import indextts）。成功即进程内缓存：

    30s 的 import 探针放在逐段合成热路径上重复跑是纯开销（narration 每段一次）；
    venv 中途被删的场景由 _ensure_worker 的 spawn 失败如实兜底，不会假装成功。

    探针必须与 indextts_worker 同一导入契约：indextts 不是 pip 包，源码落位在
    runtimes/indextts-src，靠 sys.path 引入——裸 `import indextts` 永远
    ModuleNotFoundError，引擎会被自己的探针冤判成「未装运行环境」。
    """
    global _RUNTIME_OK
    if _RUNTIME_OK is True:
        return True
    py = _venv_python()
    if not py.is_file():
        return False
    probe_code = (
        f"import sys; sys.path.insert(0, r'{_src_dir()}'); import indextts, torch"
    )
    try:
        probe = subprocess.run(  # noqa: S603 - 固定路径受控参数
            [str(py), "-c", probe_code],
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
    这里，那类场景进程树随主进程终止，无法善后。首次 spawn 时桥已向
    worker_bridge 自登记，退出钩子会一并收割；本函数保留给显式关闭与测试打桩。
    """
    _BRIDGE.shutdown()


def _ensure_worker(models_dir: Path | None, device: str = "auto") -> subprocess.Popen[str]:
    return _BRIDGE.ensure(models_dir, device)


_AUX_READY = False


def _ensure_aux_models(models_dir: Path | None) -> None:
    """worker 拉起前补齐上游辅助模型（bigvgan/w2v-bert/semantic_codec/campplus）。

    上游 ensure_models_available 的重试门有缺口：只看 w2v 目录在不在，bigvgan
    下载中断过一次（半截被清）就永远缺、加载必炸（2026-11-19 自检实锤
    FileNotFoundError: bigvgan_generator.pt）。引擎层在 spawn 前显式补齐：
    文件齐时是毫秒级空转，缺时走上游双源（modelscope/HF）真下载，失败原文抛。
    """
    global _AUX_READY
    if _AUX_READY:
        return
    venv_py = _venv_python()
    if not venv_py.is_file():
        return  # 无运行环境：spawn 自会如实报错，预检不是这条错误链的负责段
    model_dir = (
        Path(models_dir) if models_dir is not None
        else resolve_data_dir() / "models" / "tts" / "indextts2"
    )
    probe = (
        f"import sys; sys.path.insert(0, r'{_src_dir()}'); "
        f"from indextts.utils.model_download import ensure_models_available; "
        f"ensure_models_available(r'{model_dir}')"
    )
    result = subprocess.run(  # noqa: S603 - 固定解释器受控参数
        [str(_venv_python()), "-c", probe],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-300:]
        raise RuntimeError(
            f"IndexTTS 辅助模型补齐失败（bigvgan/w2v-bert 等，网络重试可解）：{tail or '未知原因'}"
        )
    _AUX_READY = True


class IndexTts2Engine:
    def __init__(self, model_dir: Path | None = None, device: str = "auto") -> None:
        self._model_dir = model_dir
        self._device = compute.normalize_requested(device)

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

    def compute(self) -> compute.ComputeReport | None:
        proc = _BRIDGE.current_proc()
        hello = _BRIDGE.hello_of(proc) if proc is not None else None
        if hello is None:
            return None
        device_str = str(hello.get("device") or "")
        # xpu 落点此前被换算成 cpu——「请求 xpu 实际 cpu：无原因」的谎就是它撒的
        # （worker 明明在 xpu 上真算成功，2026-11-19 Arc 130T 自检实锤）
        actual = (
            "cuda" if device_str.startswith("cuda")
            else "xpu" if device_str.startswith("xpu")
            else "cpu"
        )
        fallback = bool(hello.get("fallback"))
        resolved = (
            "cuda" if fallback or actual == "cuda"
            else "xpu" if actual == "xpu"
            else "cpu"
        )
        return compute.ComputeReport(
            component="tts.indextts2",
            requested=str(hello.get("requested") or self._device),
            resolved=resolved,
            actual=actual,
            fallback=fallback,
            reason=str(hello.get("reason") or ""),
        )

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        if not runtime_ready():
            raise RuntimeError(
                "IndexTTS 运行环境未就绪：需要隔离 Python 3.11 venv"
                "（引擎页「安装运行环境」）"
            )
        if voice == "" or not Path(voice).is_file():
            raise ValueError(
                "IndexTTS 需要参考音频作为音色（任意 3~10 秒人声 wav），"
                f"当前 voice 不是有效文件：{voice or '(空)'}"
                "——请在引擎中心选择参考音频，或把配音引擎切到 Edge/Kokoro"
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
            concat_wav(parts, out_path)
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

        IO 锁/看门狗/握手记账在 local_bridge 单源—— cosyvoice 同引，一次挂死
        不再能把任一引擎的合成链锁死。
        """
        proc = _ensure_worker(self._model_dir, self._device)
        _BRIDGE.synth_one(proc, text, ref, out_path)
