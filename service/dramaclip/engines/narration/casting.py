"""取材层：把「哪几集的场景」变成编排器能直接吃的、带集身份的场景表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration.line_scoring import score_line
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


# ---- A3 段长跟随台词：三模式（金句流/交叉/超短）共用的唯一口径 ----------------
SCENE_WINDOW_MAX_S = 8.0
# 下限与 snap_window_end 的 min_len 同口径：低于两秒的画面在竖屏上就是「闪了一下」，
# 比不卡点更伤（B9 规则）。
SCENE_WINDOW_MIN_S = 2.0
# 呼吸尾垫：台词结束瞬间切走是硬切（业主「不要硬切」）。0.5s 的取值依据：导出层
# jitter.safe_times 为避台词保护区还会把切点再挪 ±0.3s（台词保护 > 节拍），尾垫
# 0.5s 保证即使被挪走 0.3s，台词后仍有 ≥0.2s 的画面呼吸；0.3s 的尾垫被挪一次就归零。
DIALOGUE_TAIL_PAD_S = 0.5


def strongest_line(
    scene: EpisodeScene,
    segments: list[AsrSegment],
) -> tuple[str | None, tuple[float, float] | None]:
    """场景内最强金句（冲突/情绪词密度最高的对白）**及其台词 span**。

    span=(start, end) 取自同一句 AsrSegment——段长收缩（A3）与字幕选择必须看同一句，
    否则「画面长度跟 A 句走、字幕显示 B 句」又是一个各说各话的第二真相。
    无对白返回 (None, None)。同分取先出现者（max 的稳定性=原 `>` 严格比较的行为）。
    """
    inside = [
        segment
        for segment in segments
        if segment.start < scene.end and segment.end > scene.start
    ]
    if not inside:
        return None, None
    best = max(inside, key=lambda s: score_line(s.text, s.end - s.start))
    return best.text, (best.start, best.end)


def strongest_span_of(
    material: MaterialByEpisode | None, scene: EpisodeScene
) -> tuple[float, float] | None:
    """A3：某场景最强金句的台词 span（段长收缩用）。

    与 `beats_of` 同一降级口径：material 没传 / 缺该集键 / 场景内无台词 → None
    （不收缩，保持固定窗）——段长收缩和节拍吸附一样是意图层增强，不为它付
    「缺台词表就炸」的代价。与 `dialogue_of`（缺键即抛，编剧的硬输入）刻意不同。
    """
    if material is None:
        return None
    entry = material.get(scene.episode_id)
    if entry is None:
        return None
    _text, span = strongest_line(scene, entry.asr)
    return span


def fit_scene_window(
    scene_len_s: float, dialogue_span: tuple[float, float] | None
) -> float:
    """A3 段长公式（三模式唯一真相）：

    - 无台词（span=None）→ `min(场景长, 8.0)`，与固定 8s 时代逐字节一致
      （没收缩依据，收了就是拍脑袋）；
    - 有台词 → `min(场景长, clamp(台词 span + 尾垫, 2.0, 8.0))`：
      段长跟随该段实际台词时长，消除「台词 2s 说完、画面空挂 6s」（业主「蛋疼」）；
      上下限与场景边界都是既有口径，不因收缩而放松。

    调用方随后把收缩后的 end 交给 `snap_window_end` 做 B9 节拍吸附——**吸附必须
    排在收缩之后**：吸附是对最终 end 的微调（容差 0.25s），先吸附再收缩会把吸附
    结果整个丢掉，卡点失效。
    """
    if dialogue_span is None:
        return min(scene_len_s, SCENE_WINDOW_MAX_S)
    line_s = dialogue_span[1] - dialogue_span[0]
    fitted = max(
        SCENE_WINDOW_MIN_S, min(line_s + DIALOGUE_TAIL_PAD_S, SCENE_WINDOW_MAX_S)
    )
    return min(scene_len_s, fitted)
