"""取材层：把「哪几集的场景」变成编排器能直接吃的、带集身份的场景表。

规格 §1「一次提交（剧 × 模式）→ 每模式产出 1..K 条**卖点角度互异**的**跨集**方案」——
"跨集"写在**方案**的定义里，不是写在批次之间的比较里，所以一条方案的时间轴可以
（并且通常会）含来自多集的段。

链路上只缺一层身份，其余早就跨集了：`TimelineSegment.episode_id` 逐段存在
（`engines/narration/models.py`）、`api/export.py::render_export` 的 `episode_paths`
覆盖项目**全部**集、`exporter/encoder.py::export_plan` 的 `zones_cache` 与 `dialogue_zones`
都按 `episode_id` 分键、`overlap.source_spans` 按 `episode_id` 分组合并区间，
而 `dialogue_narration` 已经在生产上出多集成片（`pipeline.build_from_script_episodes`）。
缺的是六个规则编排器：它们吃的是一集的 `ConflictScore` 表，而 `ConflictScore`
（`engines/semantic/models.py`）只有 scene_index/start/end/score/reason，**不带集身份**。
本模块补的就是这一层。
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

    **继承 `ConflictScore` 而不是包一层**：六个编排器里读的全是 `scene.start` /
    `scene.end` / `scene.score` / `scene.scene_index`，包一层会把这几十处读点改成
    `item.scene.start`，而它们与跨集毫无关系。继承之后只有两类点要动——排序键与
    `episode_id=` 的盖章处。

    **为什么不把这两个字段直接加到 `ConflictScore` 上**（那是最省事的写法，也是错的）：
    `ConflictScore` 是**落库结构**——`engines/semantic/models.py` 的模块 docstring 逐字写着
    「落库结构对齐 docs/service/04 episode_analysis 列」，而 `api/analysis.py` 两处用
    `json.dumps([s.model_dump() for s in ...])` 把它写进 `episode_analysis.conflict_scores`。
    加字段之后新写入的行会带上 `episode_number: 0` / `episode_id: ""`——分析层根本不知道
    自己在为哪一集打分（它按集被调用），于是这两个值恒为假的默认值，而 `0` 与 `""`
    都长得像"有值"。这正是 `loudnorm` 键名那次的失败形态：一个说得通的值被烤进存储，
    下游所有人都会信它。集身份属于**规划期的取材决定**，故落在本模块、由 `stamp` 注入。
    """

    number: int
    episode_id: str


@dataclass(frozen=True)
class EpisodeMaterial:
    """一集的取材原料：集号（人读标签 + 叙事排序）与台词表（编剧的唯一事实来源）。

    台词表**按集分开**是硬要求，不是整洁癖：`start`/`end` 是集内相对秒，活库实测十集的
    场景起点全部从 `0.0` 开始，集与集的秒轴互相覆盖。摊平成一张表之后按秒过滤，
    第 3 集 12-20s 的槽位会捞到第 7 集 12-20s 的对白。
    """

    number: int
    asr: list[AsrSegment]

    @property
    def label(self) -> str:
        """人读集名。进编剧 prompt：跨集时间轴上「画面区间 12.0-20.0s」不说是哪一集
        就等于没说，模型无从判断两个相邻槽位是不是同一条线。"""
        return f"第{self.number}集"


def episode_order(scene: EpisodeScene) -> tuple[int, float, int]:
    """跨集叙事顺序：集号（播出序）→ 集内起点 → scene_index。

    单集时代六个编排器一律 `sorted(scenes, key=lambda s: s.start)`；跨集之后这个键
    **没有意义**：活库实测十集的场景起点全部从 `0.0` 开始，按 start 排会把十集交错成
    一条谁也不是的时间线。剧本驱动模式的叙事顺序来自模型写的剧本
    （`pipeline.build_from_script_episodes` 逐 `script.segments` 顺序装配、按集各持一个
    cursor）；规则选取的场景没有模型，于是唯一不武断的顺序就是**播出序**——
    `episode_number` 已经是这个语义，`api/narration.py::_collect_episode_inputs`
    就按它排（`sorted(episodes, key=lambda ep: int(ep["episode_number"]))`）。

    第三个键 `scene_index` 只为确定性：同集同起点（零长场景与舍入会让 start 相等）时
    不补次键，结果就稳定于输入顺序，而输入顺序来自 `episodes_repo.list_by_project`，
    那个顺序没有契约——与 `pipeline.top_conflict_windows` 补两个次键是同一条理由。
    """
    return (scene.number, scene.start, scene.scene_index)


def score_order(scene: EpisodeScene) -> tuple[int, int, float, int]:
    """冲突分降序 + 确定性次键（集号、集内起点、scene_index）。

    同分在全剧尺度上不是边角情况而是常态：活库实测十集共 **333** 个场景、
    只有 **19** 个不同的分值（平均一个分值上压着 17.5 个场景），最热的分值出现 **45** 次。
    只按 `-score` 排时 Python 的 sorted 虽然稳定，但稳定于**输入顺序**，于是
    「整组重规划两次取到不同的集」——而取材集正是界面卡片四要素之一。
    """
    return (-scene.score, scene.number, scene.start, scene.scene_index)


def stamp(
    scenes_by_episode: list[tuple[int, str, list[ConflictScore]]],
) -> list[EpisodeScene]:
    """逐集盖章：把 (集号, 集 id, 该集场景表) 摊平成带集身份的场景表。

    集身份在这里注入，而不是从库里读：`episode_analysis.conflict_scores` 是**按集一行**的
    JSON（`migrations/001_init.sql` 的 `conflict_scores TEXT -- JSON`，经
    `analysis_repo.get(conn, episode_id)` 取），集身份就是那一行的主键。于是活库里已有的
    十集分析结果**一行都不用改、也不用重跑分析、不需要任何迁移**。

    用 `model_dump()` + `model_validate` 而不是逐字段抄：`ConflictScore` 将来加字段时，
    逐字段抄会**静默丢掉**新字段（pydantic 默认忽略未知 kwargs，照抄旧字段名不报错，
    只会少一个值——P-1.5 的《实现定案修正》就是为这件事写的）。
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

    缺键与"该集这一区间没有台词"是两件事：后者是素材事实（`modes_w9.strongest_line`
    回 `None`、`copywriter._slot_block` 明写「该区间无台词转写」），前者是装配漏了一集。
    静默当成"没台词"会让编剧对着**别的集**的画面写这一段，而它拿到的台词是空的，
    于是它按 §3.3.1 的禁令「不得编造台词之外的事件」产出一段什么都不说的解说——
    不报错、不降级、成片看着正常，正是本仓最贵的那一类缺陷。
    """
    try:
        return material[episode_id].asr
    except KeyError:
        raise ValueError(
            f"集 {episode_id} 的台词转写没有装配进来：跨集取材的槽位必须按集取台词，"
            "缺键不是「这一集没有台词」"
        ) from None


def label_of(material: MaterialByEpisode, episode_id: str) -> str:
    """某一集的人读集名（进编剧 prompt）。缺键即抛，与 `dialogue_of` 同一口径。"""
    try:
        return material[episode_id].label
    except KeyError:
        raise ValueError(f"集 {episode_id} 没有装配进取材原料表，无从给出集名") from None
