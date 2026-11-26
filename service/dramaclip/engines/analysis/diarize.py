"""说话人聚类：funasr sentence_info → 句级段说话人归属。

自 transcriber.py 拆出（拆分专项）：聚类是 ASR 后处理的独立环节——输入是
funasr 原始输出（sentence_info），输出是句级段的 speaker 标签（角色A/B…）。
被 ParaformerEngine 调用；测试经 `transcriber._assign_speakers` /
`transcriber._spk_spans` 直呼（transcriber.py 用 `as` re-export 保持兼容）。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from dramaclip.engines.analysis.models import AsrSegment

_LOGGER = logging.getLogger(__name__)

# funasr 1.4.16 的聚类后端有一条硬门槛：嵌入不足 20 条时全员判 0 号说话人，
# 连 preset_spk_num 都被忽略（funasr/models/campplus/cluster_backend.py 的
# `if X.shape[0] < 20: return np.zeros(...)`）。嵌入按 0.75s 步进提取——VAD
# 检出的语音不足约 15 秒就触发：重 BGM 的微短剧集 VAD 检出语音骤减，正是
# 这个形状（0.2.5 装测实锤「多人全识别为角色A、指定人数也无效」）。
_FUNASR_MIN_EMBEDDINGS = 20


class _SmallSampleClustering:
    """cb_model 的小样本包装：嵌入够多走 funasr 原路径，少量自己聚。

    指定人数（`asr.num_speakers`）时用 funasr 自带的 KMeans 直聚 k 簇——
    数学上两条嵌入也能聚，门槛对它毫无必要；自动估人数时照走谱聚类
    （小矩阵照样成立），但**不做** 0.78 余弦合并——BGM 把嵌入推得彼此相似
    时，合并会把仅有的几簇抹成一个，正是要修的塌缩。两条兜底都失败时回
    全零标签（与原行为一致：转写不受影响，只是没有分声）。
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __call__(self, X: Any, oracle_num: int | None = None) -> Any:
        n = int(X.shape[0])
        if n >= _FUNASR_MIN_EMBEDDINGS or n < 2:
            return self._inner(X, oracle_num=oracle_num)
        try:
            if oracle_num is not None and oracle_num > 0:
                return self._inner.kmeans_cluster(X, min(int(oracle_num), n))
            return self._inner.spectral_cluster(X, None)
        except Exception as exc:  # noqa: BLE001 - 聚类炸了不能拖死整段转写
            _LOGGER.warning("小样本说话人聚类失败，回退单一说话人：%s", exc)
            return np.zeros(n, dtype="int")


def install_small_sample_clustering(model: Any) -> bool:
    """给 funasr AutoModel 换上小样本可用的聚类后端；返回是否装上。

    模型没有聚类后端（未挂 spk）或形状不对时不装。funasr 内部只把 cb_model
    当 callable 用（说话人聚类是唯一调用点），换包装安全；测试桩没有它也不受影响。
    """
    inner = getattr(model, "cb_model", None)
    if not callable(inner) or not (
        hasattr(inner, "spectral_cluster") and hasattr(inner, "kmeans_cluster")
    ):
        return False
    model.cb_model = _SmallSampleClustering(inner)
    return True


def _spk_spans(raw: list[Any]) -> list[tuple[float, float, int]]:
    """从 funasr 输出收集说话人区间 [(start_s, end_s, 簇id)]（sentence_info，ms 单位）。

    没启用分离时 raw 里没有 sentence_info，返回空表——调用方据此跳过归属。
    """
    spans: list[tuple[float, float, int]] = []
    for item in raw:
        for sentence in item.get("sentence_info") or []:
            try:
                start = float(sentence["start"]) / 1000
                end = float(sentence["end"]) / 1000
                label = int(sentence["spk"])
            except (KeyError, TypeError, ValueError):
                continue  # 缺字段的条目跳过，不编造归属
            if end > start:
                spans.append((start, end, label))
    return spans


def _assign_speakers(
    segments: list[AsrSegment], spans: list[tuple[float, float, int]]
) -> list[AsrSegment]:
    """句级段按重叠时长多数归属说话人：一段话里的字属谁，看谁的声音盖的时间长。

    与任何区间都不重叠的段（纯静音误检等）speaker 保持 None——量不到的不编。
    """
    out: list[AsrSegment] = []
    for seg in segments:
        totals: dict[int, float] = {}
        for start, end, label in spans:
            overlap = min(seg.end, end) - max(seg.start, start)
            if overlap > 0:
                totals[label] = totals.get(label, 0.0) + overlap
        if not totals:
            out.append(seg)
            continue
        winner = max(totals, key=lambda label: totals[label])
        out.append(
            AsrSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=_speaker_label(winner),
                emotion=seg.emotion,
                words=seg.words,
                source=seg.source,
            )
        )
    return out


def _speaker_label(label: int) -> str:
    """簇 id → 界面可读标签：角色A/角色B…（id 是聚类产物，不代表真实姓名）。"""
    if 0 <= label < 26:
        return f"角色{chr(ord('A') + label)}"
    return f"角色{label + 1}"
