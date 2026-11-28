"""CosyVoice（300M，funasr 之外的阿里系）引擎：子进程桥到隔离 conda env worker。

为什么物理隔离：主 venv Python 3.13 与上游约束不可调和——与 indextts2 共用同一个隔离
venv（tts-venv，见 tts_runtime.py）。文本前端是上游自带的 wetext（纯 pip
wheel，frontend.py:67 实测 import）。

协议（与 indextts worker 逐字同形，见 workers/cosyvoice_worker.py）：
  就绪行: {"ready": true, "requested": ..., "device": "cuda"|"cpu",
           "fallback": bool, "reason": ...}
  请求:   {"id", "text", "voice": 参考音频路径, "out": 输出wav路径, "lang"}
  应答:   {"id", "ok": true|false, "error"?}

克隆模式用 cross_lingual：zero_shot 需要参考音频的转写文本（prompt_text），
桥协议里没有这个槽位——cross_lingual 免转写直接克隆音色，代价是音色相似度
略逊。要 zero_shot 得先扩协议（voice, prompt_text 双槽），留接入后裁决。
"""

from __future__ import annotations

import logging
import os
import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path

from dramaclip.engines.tts import reference_qc
from dramaclip.engines.tts.base import EngineCaps
from dramaclip.engines.tts.local_bridge import WorkerBridge, concat_wav
from dramaclip.engines.tts.text_split import split_long_text
from dramaclip.infra import compute
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

_RUNTIME_OK: bool | None = None


def _env_python() -> Path:
    # 与 IndexTTS 共用的 TTS 运行时（infra/model_manager/tts_runtime.py 维护）
    return resolve_data_dir() / "runtimes" / "tts-venv" / "Scripts" / "python.exe"


def _src_dir() -> Path:
    """上游仓库落位（tts_runtime.py 安装时解包），桥与探针共用一份。"""
    return resolve_data_dir() / "runtimes" / "cosyvoice-src"


def _worker_env() -> dict[str, str]:
    return {
        "DRAMACLIP_COSYVOICE_SRC": str(_src_dir()),
        # stdin/stdout 协议是 UTF-8；不指定时子进程按系统 ANSI 代码页解码
        # （中文 Windows=GBK），v3 的 Rust tokenizer 遇孤立代理项即拒。
        "PYTHONIOENCODING": "utf-8",
    }


_BRIDGE = WorkerBridge(
    label="CosyVoice",
    worker_src=_WORKER_SRC,
    venv_python=_env_python,
    env=_worker_env,
    launch_timeout_s=_LAUNCH_TIMEOUT_S,
    synth_timeout_s=_SYNTH_TIMEOUT_S,
)


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

    挂在优雅退出路径（首次 spawn 时已向 worker_bridge 自登记，退出钩子一并收割；
    本函数保留给显式关闭与测试打桩）。Electron 强杀到不了这里。
    """
    _BRIDGE.shutdown()


def _ensure_worker(models_dir: Path | None, device: str = "auto") -> subprocess.Popen[str]:
    return _BRIDGE.ensure(models_dir, device)


class CosyVoiceEngine:
    def __init__(
        self, model_dir: Path | None = None, engine: str = "cosyvoice", device: str = "auto"
    ) -> None:
        self._model_dir = model_dir
        self._engine = engine
        self._device = compute.normalize_requested(device)

    @property
    def name(self) -> str:
        return self._engine

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
        """模型就绪判据取自 registry.requirements(self._engine) 那一份表。

        300M 与 CosyVoice3 的 yaml 名和 speech_tokenizer 代际都不同，引擎侧再抄
        一份 v1 清单，装得再全的 v3 也会被判成「缺模型」。
        """
        if self._model_dir is not None:
            from dramaclip.infra.model_manager import registry

            missing = registry.missing_requirements(
                self._model_dir, registry.requirements(self._engine)
            )
            if missing:
                return False, f"缺模型：{self._model_dir} 下没有 {', '.join(missing)}"
        if not runtime_ready():
            return False, (
                "未装运行环境：需要隔离 Python 3.10 conda env"
                "（引擎页「安装运行环境」）"
            )
        return True, "运行环境与模型就绪"

    def compute(self) -> compute.ComputeReport | None:
        proc = _BRIDGE.current_proc()
        hello = _BRIDGE.hello_of(proc) if proc is not None else None
        if hello is None:
            return None
        actual = "cuda" if str(hello.get("device") or "").startswith("cuda") else "cpu"
        fallback = bool(hello.get("fallback"))
        return compute.ComputeReport(
            component="tts.cosyvoice",
            requested=str(hello.get("requested") or self._device),
            resolved="cuda" if fallback or actual == "cuda" else "cpu",
            actual=actual,
            fallback=fallback,
            reason=str(hello.get("reason") or ""),
        )

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
            concat_wav(parts, out_path)
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
        """送一个 job 给 worker 并等应答（看门狗与握手记账在 local_bridge 单源）。"""
        proc = _ensure_worker(self._model_dir, self._device)
        _BRIDGE.synth_one(proc, text, ref, out_path)
