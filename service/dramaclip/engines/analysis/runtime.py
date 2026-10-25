"""引擎运行时：按设置懒构建并缓存引擎单例（模型加载昂贵，进程内只加载一次）。"""

from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path

from dramaclip.engines.analysis.transcriber import (
    AsrEngine,
    DashscopeCloudAsrEngine,
    FasterWhisperEngine,
    ParaformerEngine,
    SenseVoiceEngine,
)
from dramaclip.infra import config, device_resolve

_LOGGER = logging.getLogger(__name__)

_CLOUD_ASR_MODEL = "qwen-audio-3.1-asr-flash"


class AnalysisRuntime:
    """transcriber 等引擎的懒加载单例容器（构建锁保证并发首触只构建一次）。"""

    def __init__(
        self, settings: config.Settings, models_dir: Path, data_dir: Path | None = None
    ) -> None:
        self._settings = settings
        self._models_dir = models_dir
        self._data_dir = data_dir
        self._transcriber: AsrEngine | None = None
        self._lock = threading.Lock()

    def transcriber(self) -> AsrEngine:
        # 锁是必须的：分析任务、导出 TTS 回环验证、工具箱提取三路共享这个单例，
        # 并发首触无锁会双构建（双模型加载 + 旧实例泄漏）。
        with self._lock:
            if self._transcriber is None:
                self._transcriber = _build_transcriber(
                    self._settings, self._models_dir, self._data_dir
                )
            return self._transcriber


def supported() -> frozenset[str]:
    """真能构建出来的转写引擎名——``registry.engine_ready`` 读这里，两边不各存一份。

    ``firedred`` 曾在清单里登记、2026-09-24 裁决移除：官方无 pip 包（接入需要隔离桥）、
    AED 无原生时间戳且单次推理上限 60s（整集 wav 必须先过 VAD 分窗）——清单不再挂
    「永远装不上」的死资产。

    funasr 系（sensevoice/paraformer）E-2 起依赖本地运行环境：主 venv 装了 ml 组
    （dev/测试态）或本地智能运行环境带了 funasr 组（打包态按需装）二者其一才上清单。
    """
    names = {"faster_whisper"}
    # dashscope 上清单前先验包在场（v0.2.2 曾有发布包缺 dashscope 的事故）：
    # 缺包时不挂清单——选了也只会首轮转写裸 ImportError，不如如实「待接入」。
    if importlib.util.find_spec("dashscope") is not None:
        names.add("dashscope_cloud")
    try:
        import funasr  # noqa: F401

        names |= {"sensevoice", "paraformer"}
    except ImportError:
        from dramaclip.infra.model_manager import tts_runtime
        from dramaclip.infra.paths import resolve_data_dir

        if tts_runtime.analysis_ready(resolve_data_dir()):
            names |= {"sensevoice", "paraformer"}
    return frozenset(names)


def _resolve_diarization(
    settings: config.Settings, *, engine: str, supports: bool
) -> bool:
    """`asr.diarization` 三态：auto 按引擎能力，true 强制，其余关闭。

    说话人标签决定编剧台词本里的「谁在说」和自动音色挑选找的主角，所以显式 true
    遇上做不到的引擎必须炸——静默少一层信息就是改观众所见所闻。真值集仍归
    `config.get_bool` 管，这里只多认一个 auto。
    """
    mode = str(settings.get("asr.diarization") or "auto").strip().lower()
    if mode == "auto":
        if not supports:
            _LOGGER.info("asr.diarization=auto：%s 不支持说话人分离，本轮段不带说话人", engine)
        return supports
    wanted = config.get_bool(settings, "asr.diarization")
    if wanted and not supports:
        raise ValueError(
            f"{engine} 不支持说话人分离：请把 asr.diarization 改成 auto 或关闭"
        )
    return wanted


def _build_transcriber(
    settings: config.Settings, models_dir: Path, data_dir: Path | None = None
) -> AsrEngine:
    engine = settings.get("asr.engine", "faster_whisper")
    if engine not in supported():
        available = " / ".join(sorted(supported()))
        raise ValueError(f"未知 ASR 引擎: {engine}（可用: {available}）")
    if engine == "dashscope_cloud":
        model = settings.get("asr.model", _CLOUD_ASR_MODEL) or _CLOUD_ASR_MODEL
        return DashscopeCloudAsrEngine(
            api_key=settings.get("asr.api_key", ""),
            model=model,
            diarization=_resolve_diarization(
                settings, engine=engine, supports=DashscopeCloudAsrEngine.supports_model(model)
            ),
        )
    device = resolve_asr_device(engine, settings.get("asr.device", "auto"), data_dir)
    if engine == "paraformer":
        diarize = _resolve_diarization(
            settings, engine=engine, supports=ParaformerEngine.supports_diarization
        )
        return ParaformerEngine(
            models_dir=models_dir,
            vad_model_dir=models_dir / "asr" / "fsmn-vad" if diarize else None,
            spk_model_dir=models_dir / "asr" / "campplus" if diarize else None,
            num_speakers=config.get_int(settings, "asr.num_speakers"),
            device=device,
        )
    # 剩下两个引擎没有说话人通道：auto 关、false 关，显式 true 在核验里炸
    _resolve_diarization(settings, engine=engine, supports=False)
    if engine == "sensevoice":
        return SenseVoiceEngine(models_dir=models_dir, device=device)
    model_size = settings.get("asr.model", "base")
    return FasterWhisperEngine(
        model_size,
        device=device,
        models_dir=models_dir / "asr" / "faster-whisper",
        compute_type=settings.get("asr.compute_type", "auto"),
    )


def resolve_asr_device(engine: str, requested: str | None, data_dir: Path | None) -> str:
    """设备解析的唯一入口是 `device_resolve`；这里只决定「有没有解析入口」。

    `data_dir is None` 原样透传意图：`resolve_data_dir()` 会 mkdir，不该藏在引擎构造里
    （测试会因此往真实用户目录写）。自检（`selftest._build_asr`）调同一个函数，判据
    只有这一份。`compute_type` 不在解析范围——它是 ctranslate2 的量化档位
    （int8/float16），CPU 上同样有意义。
    """
    if data_dir is None:
        return requested or "auto"
    resolution = device_resolve.resolve_engine("asr", engine, requested, data_dir)
    return resolution.device if resolution is not None else (requested or "auto")


def language(settings: config.Settings) -> str:
    return settings.get("asr.language", "zh")
