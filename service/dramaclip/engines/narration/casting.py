"""取材层：把「哪几集的场景」变成编排器能直接吃的、带集身份的场景表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.semantic.models import ConflictScore

# episode_id → 该集的取材原料。全链只用**一种**集键（episode_id）：
# `TimelineSegment.episode_id`、`episode_paths`、`zones_cache`、`overlap.source_spans`
# 都是它，再引入"按集号索引"的第二种键只会让两侧各查一半。
MaterialByEpisode = dict[str, "EpisodeMaterial"]


class EpisodeScene(ConflictScore):
    """一个冲突场景 + 它的取材身份（集号用于叙事排序，集 id 用于盖进时间轴段）。
    """

    number: int
    episode_id: str


@dataclass(frozen=True)
class EpisodeMaterial:
    """一集的取材原料：集号（人读标签 + 叙事排序）与台词表（编剧的唯一事实来源）。

    `beats`（B9）是该集音频的拍点时刻（秒，升序），供编排层把任意切点吸附到
    节拍上（engines/narration/beat_align）。默认空元组：旧库分析记录没有拍点、
    或装配层拿不到 audio_features 时，编排行为与 B9 之前逐字节一致。
    """

    number: int
    asr: list[AsrSegment]
    beats: tuple[float, ...] = ()

    @property
    def label(self) -> str:
        """人读集名。进编剧 prompt：跨集时间轴上「画面区间 12.0-20.0s」不说是哪一集
        就等于没说，模型无从判断两个相邻槽位是不是同一条线。"""
        return f"第{self.number}集"


def episode_order(scene: EpisodeScene) -> tuple[int, float, int]:
    """跨集叙事顺序：集号（播出序）→ 集内起点 → scene_index。
    """
    return (scene.number, scene.start, scene.scene_index)


def score_order(scene: EpisodeScene) -> tuple[int, int, float, int]:
    """冲突分降序 + 确定性次键（集号、集内起点、scene_index）。
    """
    return (-scene.score, scene.number, scene.start, scene.scene_index)


def stamp(
    scenes_by_episode: list[tuple[int, str, list[ConflictScore]]],
) -> list[EpisodeScene]:
    """逐集盖章：把 (集号, 集 id, 该集场景表) 摊平成带集身份的场景表。
    """
    stamped: list[EpisodeScene] = []
    for number, episode_id, scenes in scenes_by_episode:
        for scene in scenes:
            payload: dict[str, Any] = scene.model_dump()
            payload["number"] = number
            payload["episode_id"] = episode_id
            stamped.append(EpisodeScene.model_validate(payload))
    return stamped


def dialogue_of(material: MaterialByEpisode, episode_id: str) -> list[AsrSegment]:
    """某一集的台词表。**缺键即抛**，绝不退回"这一集没有台词"。
    """
    try:
        return material[episode_id].asr
    except KeyError:
        raise ValueError(
            f"集 {episode_id} 的台词转写没有装配进来：跨集取材的槽位必须按集取台词，"
            "缺键不是「这一集没有台词」"
        ) from None


def beats_of(material: MaterialByEpisode | None, episode_id: str) -> tuple[float, ...]:
    """某一集的拍点表（B9 节拍吸附用）。

    与 `dialogue_of` 相反，**缺键/缺表返回空而不抛**：台词是编剧的硬输入（缺了
    写不出解说），拍点只是切点吸附的意图来源——material 没传、这一集没装配、
    旧库分析记录没有 beats，都降级为「不吸附」，计划与 B9 之前一致。
    """
    if material is None:
        return ()
    entry = material.get(episode_id)
    return tuple(entry.beats) if entry is not None else ()


def label_of(material: MaterialByEpisode, episode_id: str) -> str:
    """某一集的人读集名（进编剧 prompt）。缺键即抛，与 `dialogue_of` 同一口径。"""
    try:
        return material[episode_id].label
    except KeyError:
        raise ValueError(f"集 {episode_id} 没有装配进取材原料表，无从给出集名") from None
