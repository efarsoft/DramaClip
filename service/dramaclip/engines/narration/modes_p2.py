"""P2 模式编排（原案 6.10/6.11）：双人对谈式与角色内心独白式。

两模式都基于「全程 TTS 旁白」骨架（同 full），差异在音色与文案视角：
- dual_host_chat：双音色 A/B 交替对谈（主持人 x 嘉宾），原声压低；
- inner_monologue：单一角色第一人称内心 OS，情绪更内收。
配音用 edge 多音色（zh-CN-YunxiNeural 男 / zh-CN-XiaoyiNeural 女）；
kokoro/IndexTTS-2 本地引擎接入后仅需替换 voice 参数与引擎工厂。
场景表带集身份（`casting.EpisodeScene`），故一条对谈/独白弧可以横跨多集。
"""

from __future__ import annotations

from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)

_VOICE_A = "zh-CN-YunxiNeural"  # 主持人（男）
_VOICE_B = "zh-CN-XiaoyiNeural"  # 嘉宾（女）
_SCENE_S = 10.0
_MAX_SCENES = 8


def _pick(scenes: list[EpisodeScene]) -> list[EpisodeScene]:
    ranked = sorted(scenes, key=score_order)[:_MAX_SCENES]
    return sorted(ranked, key=episode_order)


def build_dual_host(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """双人对谈（原案 6.10）：A 抛话题、B 推剧情，交替对谈 + 原声压低。"""
    picked = _pick(scenes)
    if not picked:
        return PlanData(mode="dual_host_chat", strategy=strategy)

    count = len(picked)
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        slot_id = f"dual-{index + 1}"
        voice = _VOICE_A if index % 2 == 0 else _VOICE_B
        speaker = "主持人 A" if index % 2 == 0 else "嘉宾 B"
        if index == 0:
            brief = f"{speaker} 开场抛话题：用剧名点出这片为什么值得看"
        elif index == count - 1:
            brief = f"{speaker} 收尾：放狠话评结局并引导看全集"
        elif index % 2 == 1:
            brief = f"{speaker} 接话：情绪反应 + 补一个刚才没说的细节"
        else:
            brief = f"{speaker} 抛下一层：把冲突往更狠处推一句"
        end = round(min(scene.start + _SCENE_S, scene.end), 3)
        timeline.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=end,
                audio="narration",
                narration_id=slot_id,
            )
        )
        texts.append(NarrationText(id=slot_id, brief=brief, voice=voice))
    return PlanData(
        mode="dual_host_chat", timeline=timeline, narration_texts=texts, strategy=strategy
    )


def build_monologue(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """角色内心独白（原案 6.11）：主角第一人称 OS 贯穿，情绪内收。"""
    picked = _pick(scenes)
    if not picked:
        return PlanData(mode="inner_monologue", strategy=strategy)

    count = len(picked)
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        slot_id = f"mono-{index + 1}"
        if index == 0:
            brief = "第一人称开场：主角此刻的处境与误判，一句话"
        elif index == count - 1:
            brief = "第一人称收尾：态度反转落定 + 一句点击引导"
        elif scene.score >= 85:
            brief = "第一人称高潮：这一刻主角想明白了什么，短促、带情绪"
        else:
            brief = "第一人称推进：忍让如何一点点失效"
        end = round(min(scene.start + _SCENE_S, scene.end), 3)
        timeline.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=end,
                audio="narration",
                narration_id=slot_id,
            )
        )
        texts.append(NarrationText(id=slot_id, brief=brief, voice=_VOICE_A))
    return PlanData(
        mode="inner_monologue", timeline=timeline, narration_texts=texts, strategy=strategy
    )
