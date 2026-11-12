"""Paraformer 引擎（funasr 同栈）：字级时间戳原生，热词有原生槽位。

自 transcriber.py 拆出（拆分专项）：依赖 common（设备解析、文本简化、
_pair/_group_by_gap、_punc_false_alarm_silenced）与 funasr（worker 桥）
与 diarize（说话人聚类）。长音频靠 batch_size_s 动态批整集进；时间戳
是字级的——按字间静音间隙聚成句级段，供 OCR 融合与台词保护区用。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis import pause_split
from dramaclip.engines.analysis.asr.common import (
    _CUDA_PROBLEM,
    _LOGGER,
    _adopt_loaded_device,
    _group_by_gap,
    _pair,
    _probe_cuda_op,
    _punc_false_alarm_silenced,
    _report_from_state,
    _resolve_torch_device,
    simplify,
)
from dramaclip.engines.analysis.asr.funasr import (
    _FunasrWorker,
    _inproc_funasr,
    _spawn_funasr_worker,
)
from dramaclip.engines.analysis.diarize import _assign_speakers, _spk_spans
from dramaclip.engines.analysis.models import AsrSegment, WordSpan
from dramaclip.infra import compute


class ParaformerEngine:
    """Paraformer-large（funasr 同栈）：字级时间戳原生，热词有原生槽位。

    与 SenseVoice 的两处关键差异：长音频靠 `batch_size_s` 动态批整集进；
    时间戳是字级的——按字间静音间隙聚成句级段，供 OCR 融合与台词保护区用。

    说话人分离（`spk_model_dir` 在场时启用）：funasr 的 diarization 路径
    **必须**挂 vad_model（嵌入按语音区间提取，无 vad 直接没有输入窗），
    且 spk_mode 显式走 "vad_segment"——"punc_segment"（默认值）需要标点模型，
    不装标点时会先打一条 error 日志再被库自己改回，明着写对省那条假警报。
    说话人数：`num_speakers>0` 经 `preset_spk_num` 指定，0 交给聚类自动估
    （1~15 人范围，短剧每集 2~6 人绰绰有余）。
    """

    # 字间隙超过这个数（秒）就断句：短剧台词句间停顿普遍 >0.5s，标点模型不挂
    # （那是另两笔下载），靠间隙本身就是可靠的句边界。
    _SENTENCE_GAP_S = 0.6

    supports_diarization = True  # CAM++ 聚类通道已接线（见类 docstring）
    # CAM++ 权重的仓库实名（registry 同名判据；funasr 本地加载默认找 model.pt）
    _CAMPP_WEIGHT = "campplus_cn_common.bin"

    def __init__(
        self,
        model_dir: Path | None = None,
        *,
        models_dir: Path | None = None,
        vad_model_dir: Path | None = None,
        spk_model_dir: Path | None = None,
        num_speakers: int = 0,
        device: str = "auto",
    ) -> None:
        resolved = model_dir if model_dir is not None else (
            models_dir / "asr" / "paraformer" if models_dir is not None else None
        )
        self._model_dir = resolved
        self._vad_model_dir = vad_model_dir
        self._spk_model_dir = spk_model_dir
        self._num_speakers = num_speakers
        self._requested = compute.normalize_requested(device)
        self._model: Any = None
        self._actual_device: str | None = None
        self._fallback_reason = ""

    @property
    def name(self) -> str:
        return "paraformer"

    @property
    def diarization(self) -> bool:
        """说话人分离是否启用（由调用方决定传入 spk 模型目录与否）。"""
        return self._spk_model_dir is not None

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        model = self._ensure_model()
        try:
            clips = pause_split.speech_clips(wav_path)
        except (OSError, pause_split.PauseAnalysisUnavailable) as exc:
            # 停顿分析量不出来（文件不可读/过短）→ 退回整条直喂（分档：老路径仍可用）。
            # 只认这一类型：编程错误往这儿抛就是真失败，让它出去。
            _LOGGER.warning(
                "停顿切分退回整条直喂（%s: %s）：字级时间戳失去片段起点锚，跨停顿并句可能复现",
                type(exc).__name__,
                exc,
            )
            clips = []
        else:
            # 切分退化＝谷被 BGM 填满（《颠勺》EP1 形态的前兆）：片段顶格无真实停顿，
            # 逐段转写的防并句前提已经不成立。引擎层只作如实记录——用户的账面由
            # pipeline 的产物级坍缩检测兜（两条信号互补：这条在转写前，那条在转写后）。
            degenerate = pause_split.fill_degenerate(clips)
            if degenerate:
                _LOGGER.warning(
                    "停顿切分退化（%s）：能量谷疑被 BGM 填满，"
                    "并句/时间戳漂移风险高，建议切云端 ASR",
                    degenerate,
                )
        with _punc_false_alarm_silenced():
            if len(clips) <= 1:
                return self._transcribe_one(model, wav_path, language, hotwords)
            # 停顿切分：BGM 素材下 funasr 内部 VAD 分不清「人声停了」与「安静」，
            # 跨停顿并句 + 字戳插值漂移都源于整条直喂。按能量谷切短语片段逐段转写，
            # 时间戳以片段起点为锚（真实切分位置），并句/串音物理消失。
            work = wav_path.parent / f"{wav_path.stem}-clips"
            segments: list[AsrSegment] = []
            failures: list[str] = []
            try:
                for index, (clip, clip_path) in enumerate(
                    pause_split.split_wav(wav_path, clips, work)
                ):
                    # 切片级隔离（真机 2026-10-27 大明第8集立案）：funasr 上游
                    # sentence_postprocess 在 token 与时间戳列表不齐时 IndexError
                    # （`time_stamp[i][0]`，VAD 报 speech 的 BGM 退化切片易触发），
                    # 一个坏切片曾连坐整集。跳过该切片留痕，其余照常出词——
                    # 全部切片都失败才让最后的错误出去（诚实失败，不静默出空转写）。
                    try:
                        clip_segments = self._transcribe_one(
                            model, clip_path, language, hotwords
                        )
                    except Exception as exc:  # noqa: BLE001 - 上游天书在切片级收口
                        failures.append(
                            f"clip{index:02d}@{clip.start:.1f}s: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        _LOGGER.warning(
                            "切片 %02d（%.1f-%.1fs）转写失败，跳过（%s: %s）",
                            index,
                            clip.start,
                            clip.end,
                            type(exc).__name__,
                            exc,
                        )
                        continue
                    for seg in clip_segments:
                        # 词级时间戳同样是 clip 相对值：只平移 start/end 会把词锚留在
                        # 片段内——refine 字流按词取时间，整份时间轴就会坍缩到首个
                        # clip 的跨度（真机第1集实锤：46 段全挤 0-11.58s）。
                        shifted_words = [
                            w.model_copy(
                                update={
                                    "start": round(w.start + clip.start, 3),
                                    "end": round(w.end + clip.start, 3),
                                }
                            )
                            for w in (seg.words or [])
                        ]
                        segments.append(
                            seg.model_copy(
                                update={
                                    "start": round(seg.start + clip.start, 3),
                                    "end": round(seg.end + clip.start, 3),
                                    "words": shifted_words,
                                }
                            )
                        )
                if failures and not segments:
                    raise RuntimeError(
                        f"全部 {len(failures)} 个切片转写失败，首个原因：{failures[0]}"
                    )
                if failures:
                    _LOGGER.warning(
                        "停顿切分转写 %d/%d 个切片失败被跳过：%s",
                        len(failures),
                        len(failures) + len(segments),
                        "；".join(failures[:3]),
                    )
            finally:
                shutil.rmtree(work, ignore_errors=True)
            segments.sort(key=lambda s: s.start)
            return segments

    def _transcribe_one(
        self, model: Any, wav_path: Path, language: str, hotwords: str
    ) -> list[AsrSegment]:
        with _punc_false_alarm_silenced():
            raw = model.generate(
                input=str(wav_path),
                batch_size_s=300,  # 长音频动态批：整集 wav 一次进，按 300s 预算切批
                hotword=hotwords or None,  # paraformer 原生热词槽（热词反哺直接受益）
                # 必须显式要时间戳：不传时 funasr 只回 {key,text}，_parse_paraformer
                # 对无时间戳条目整条丢弃 → 全文静默变空（2026-09-24 真样例实测）。
                output_timestamp=True,
                **(
                    {"preset_spk_num": self._num_speakers}
                    if self.diarization and self._num_speakers > 0
                    else {}
                ),
            )
        segments = _parse_paraformer(raw, self._SENTENCE_GAP_S)
        spans = _spk_spans(raw)
        return _assign_speakers(segments, spans) if spans else segments

    def _ensure_model(self) -> Any:
        if self._model is None:
            auto_model = _inproc_funasr()
            if auto_model is None:
                self._model = self._venv_model()
                return self._model
            spk_kwargs: dict[str, Any] = {}
            if self.diarization:
                spk_dir = self._spk_model_dir
                vad_dir = self._vad_model_dir
                assert spk_dir is not None  # diarization=True 的定义就是这个字段在场
                spk_kwargs["vad_model"] = (
                    str(vad_dir) if vad_dir is not None and vad_dir.is_dir() else "fsmn-vad"
                )
                if spk_dir.is_dir():
                    spk_kwargs["spk_model"] = str(spk_dir)
                    # funasr 本地目录加载把权重名硬编码成 model.pt（download_from_hub
                    # 的断言），CAM++ 的权重实名是 campplus_cn_common.bin——经
                    # spk_kwargs 组件通道用 init_param 指路（绝对路径绕开 CWD 相对
                    # 解析）。不能放顶层 kwargs：那里会把 cam++ 权重喂给主模型。
                    weight = spk_dir / self._CAMPP_WEIGHT
                    if weight.is_file():
                        spk_kwargs["spk_kwargs"] = {"init_param": str(weight)}
                else:
                    spk_kwargs["spk_model"] = "cam++"
                spk_kwargs["spk_mode"] = "vad_segment"
            device = _resolve_torch_device(self._requested)
            if device.startswith("cuda"):
                problem = _probe_cuda_op(device)
                if problem:
                    if self._requested == "cuda":
                        raise compute.ComputeUnavailableError(
                            f"Paraformer 请求 CUDA，但 CUDA 不可计算：{problem}"
                        )
                    _LOGGER.warning("Paraformer CUDA 探针失败回退 CPU：%s", problem)
                    self._actual_device = "cpu"
                    self._fallback_reason = problem
                    device = "cpu"
            model_id = str(self._model_dir) if (
                self._model_dir is not None and self._model_dir.is_dir()
            ) else "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
            kwargs: dict[str, Any] = {
                "model": model_id,
                "disable_update": True,  # 启动期联网检查版本：桌面应用不联网也能转写
                "device": device,
                **spk_kwargs,
            }
            try:
                self._model = auto_model(**kwargs)
            except Exception as exc:  # noqa: BLE001 - CUDA 类失败按请求语义处理
                if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                    raise
                if self._requested == "cuda":
                    raise compute.ComputeUnavailableError(
                        f"Paraformer 请求 CUDA，加载失败：{type(exc).__name__}: {exc}"
                    ) from exc
                _LOGGER.warning("Paraformer CUDA 加载失败回退 CPU：%s", str(exc)[:160])
                self._actual_device = "cpu"
                self._fallback_reason = f"{type(exc).__name__}: {exc}"
                kwargs["device"] = "cpu"
                self._model = auto_model(**kwargs)
            else:
                self._actual_device, reason = _adopt_loaded_device(
                    "Paraformer", self._requested, device, self._model
                )
                if reason:
                    self._fallback_reason = reason
        return self._model

    def compute(self) -> compute.ComputeReport | None:
        return _report_from_state(
            "asr.funasr", self._requested, self._actual_device, self._fallback_reason
        )

    def _venv_model(self) -> _FunasrWorker:
        """冻结/无 ml 态：本地智能运行环境里的 funasr worker（构造语义 worker 端镜像）。"""
        model_id = str(self._model_dir) if (
            self._model_dir is not None and self._model_dir.is_dir()
        ) else "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        worker = _spawn_funasr_worker({
            "engine": "paraformer",
            "model": model_id,
            "device": self._requested,
            "vad_model_dir": str(self._vad_model_dir) if self._vad_model_dir else None,
            "spk_model_dir": str(self._spk_model_dir) if self._spk_model_dir else None,
        })
        self._adopt_worker_hello(worker)
        _LOGGER.info(
            "Paraformer 走本地运行环境 worker（device=%s diarization=%s）",
            worker.device, self.diarization,
        )
        return worker

    def _adopt_worker_hello(self, worker: _FunasrWorker) -> None:
        hello = worker.ready
        self._actual_device = "cuda" if worker.device.startswith("cuda") else "cpu"
        self._fallback_reason = (
            str(hello.get("reason") or "") if hello.get("fallback") else ""
        )


def _parse_paraformer(raw: list, gap_s: float) -> list[AsrSegment]:  # type: ignore[type-arg]
    """[{text, timestamp:[[beg_ms,end_ms], ...]}] → 句级段（按字间隙聚句 + 字级 words）。

    text 与 timestamp 逐字配对；长度对不上时按可配对的前缀走、剩余文本并入末字
    的跨度——文本一个不丢，边界取实测值（量不到的不编）。
    """
    segments: list[AsrSegment] = []
    for item in raw:
        text = str(item.get("text", "")).strip()
        timestamps = [span for span in (item.get("timestamp") or []) if len(span) == 2]
        if not text or not timestamps:
            continue
        chars = [ch for ch in text if not ch.isspace()]
        words = [
            WordSpan(start=beg_ms / 1000, end=end_ms / 1000, word=char)
            for char, (beg_ms, end_ms) in _pair(chars, timestamps)
        ]
        for run in _group_by_gap(words, gap_s):
            segments.append(
                AsrSegment(
                    start=run[0].start,
                    end=run[-1].end,
                    text=simplify("".join(w.word for w in run)),
                    words=list(run),
                )
            )
    return segments
