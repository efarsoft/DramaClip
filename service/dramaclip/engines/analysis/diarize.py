"""说话人聚类：funasr sentence_info → 句级段说话人归属。

自 transcriber.py 拆出（拆分专项）：聚类是 ASR 后处理的独立环节——输入是
funasr 原始输出（sentence_info），输出是句级段的 speaker 标签（角色A/B…）。
被 ParaformerEngine 调用；测试经 `transcriber._assign_speakers` /
`transcriber._spk_spans` 直呼（transcriber.py 用 `as` re-export 保持兼容）。
"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.analysis.models import AsrSegment


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
